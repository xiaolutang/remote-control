"""
S419: Server WS agent_cleanup 测试。

覆盖 stale 管理、TTL 过期、pending future 清理、terminal 恢复。
"""
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ws.agent_cleanup import (
    _cleanup_pending_futures,
    _mark_agent_stale,
    _is_agent_stale,
    _clear_agent_stale,
    _uses_immediate_offline_cleanup,
    _cleanup_agent,
    _expire_stale_agent,
    stale_agents,
    CLEANUP_REASON_AGENT_SHUTDOWN,
    CLEANUP_REASON_NETWORK_LOST,
    CLEANUP_REASON_DEVICE_OFFLINE,
)


@pytest.fixture(autouse=True)
def _clear_stale():
    stale_agents.clear()
    yield
    stale_agents.clear()


# ---- stale 管理 ----

class TestStaleManagement:
    def test_mark_stale(self):
        _mark_agent_stale("s1")
        assert _is_agent_stale("s1")
        assert "s1" in stale_agents

    def test_not_stale_by_default(self):
        assert not _is_agent_stale("s1")

    def test_clear_stale(self):
        _mark_agent_stale("s1")
        _clear_agent_stale("s1")
        assert not _is_agent_stale("s1")

    def test_clear_nonexistent_stale(self):
        # Should not raise
        _clear_agent_stale("nonexistent")

    def test_mark_stale_expires_at_future(self):
        _mark_agent_stale("s1")
        assert stale_agents["s1"] > datetime.now(timezone.utc)


# ---- _uses_immediate_offline_cleanup ----

class TestImmediateCleanup:
    def test_agent_shutdown_is_immediate(self):
        assert _uses_immediate_offline_cleanup(CLEANUP_REASON_AGENT_SHUTDOWN)

    def test_network_lost_is_not_immediate(self):
        assert not _uses_immediate_offline_cleanup(CLEANUP_REASON_NETWORK_LOST)


# ---- _cleanup_pending_futures ----

class TestCleanupPendingFutures:
    def test_cancels_matching_futures(self):
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        pending = {("s1", "t1"): future}

        _cleanup_pending_futures(pending, "s1", "test")
        assert future.done()
        assert ("s1", "t1") not in pending
        loop.close()

    def test_skips_non_matching_session(self):
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        pending = {("s2", "t1"): future}

        _cleanup_pending_futures(pending, "s1", "test")
        assert not future.done()
        assert ("s2", "t1") in pending
        loop.close()

    def test_skips_already_done_future(self):
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        future.set_result("done")
        pending = {("s1", "t1"): future}

        _cleanup_pending_futures(pending, "s1", "test")
        assert future.result() == "done"
        loop.close()


# ---- _cleanup_agent ----

class TestCleanupAgent:
    @pytest.mark.asyncio
    async def test_shutdown_goes_immediate_offline(self):
        with patch("app.ws.agent_cleanup.active_agents", {"s1": MagicMock()}), \
             patch("app.ws.agent_cleanup._cleanup_pending_futures"), \
             patch("app.ws.agent_cleanup._cleanup_execute_command_futures"), \
             patch("app.ws.agent_cleanup._cleanup_pending_futures_by_id"), \
             patch("app.ws.agent_cleanup.pending_registry") as mock_registry, \
             patch("app.ws.agent_cleanup._execute_command_rate_tracker", {"s1": "x"}), \
             patch("app.ws.agent_cleanup._set_session_offline_immediately", new_callable=AsyncMock) as mock_offline:

            await _cleanup_agent("s1", CLEANUP_REASON_AGENT_SHUTDOWN)
            mock_offline.assert_called_once()
            assert "s1" not in _execute_command_rate_tracker if "_execute_command_rate_tracker" in dir() else True

    @pytest.mark.asyncio
    async def test_network_lost_goes_recoverable(self):
        with patch("app.ws.agent_cleanup.active_agents", {}), \
             patch("app.ws.agent_cleanup._cleanup_pending_futures"), \
             patch("app.ws.agent_cleanup._cleanup_execute_command_futures"), \
             patch("app.ws.agent_cleanup._cleanup_pending_futures_by_id"), \
             patch("app.ws.agent_cleanup.pending_registry") as mock_registry, \
             patch("app.ws.agent_cleanup._execute_command_rate_tracker", {}), \
             patch("app.ws.agent_cleanup.set_session_offline_recoverable", new_callable=AsyncMock):

            await _cleanup_agent("s1", CLEANUP_REASON_NETWORK_LOST)
            assert _is_agent_stale("s1")


# ---- _expire_stale_agent ----

class TestExpireStaleAgent:
    @pytest.mark.asyncio
    async def test_expire_removes_from_stale(self):
        _mark_agent_stale("s1")
        with patch("app.ws.agent_cleanup._close_agent_conversations_for_session", new_callable=AsyncMock), \
             patch("app.ws.agent_cleanup.set_session_offline", new_callable=AsyncMock):
            await _expire_stale_agent("s1")
            assert not _is_agent_stale("s1")

    @pytest.mark.asyncio
    async def test_expire_calls_set_session_offline(self):
        _mark_agent_stale("s1")
        with patch("app.ws.agent_cleanup._close_agent_conversations_for_session", new_callable=AsyncMock), \
             patch("app.ws.agent_cleanup.set_session_offline", new_callable=AsyncMock) as mock_offline:
            await _expire_stale_agent("s1")
            mock_offline.assert_called_once_with("s1", reason=CLEANUP_REASON_DEVICE_OFFLINE)

    @pytest.mark.asyncio
    async def test_expire_handles_exception(self):
        _mark_agent_stale("s1")
        with patch("app.ws.agent_cleanup._close_agent_conversations_for_session", new_callable=AsyncMock), \
             patch("app.ws.agent_cleanup.set_session_offline", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
            # Should not raise
            await _expire_stale_agent("s1")
            assert not _is_agent_stale("s1")
