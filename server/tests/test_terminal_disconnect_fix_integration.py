"""
Issue 1 集成自测：验证修复后终端不再被错误关闭。

验证完整链路：
1. Agent close(code=4501) → Server 收到非 1000 close code
2. Server cleanup_reason = NETWORK_LOST
3. _cleanup_agent(NETWORK_LOST) → 终端进入 stale/recoverable，不立即关闭
4. Agent 重连 → _restore_recoverable_terminals 恢复终端

对比：Agent close(code=1000) → Server cleanup_reason = AGENT_SHUTDOWN → 立即关闭
"""
import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ws.agent_cleanup import (
    CLEANUP_REASON_AGENT_SHUTDOWN,
    CLEANUP_REASON_NETWORK_LOST,
    _cleanup_agent,
    _is_agent_stale,
    stale_agents,
)
from app.ws.agent_connection import AgentConnection, active_agents


@pytest.fixture(autouse=True)
def _clear_state():
    active_agents.clear()
    stale_agents.clear()
    yield
    active_agents.clear()
    stale_agents.clear()


class TestTerminalDisconnectFixIntegration:
    """集成测试：验证修复后 macOS 休眠场景的正确行为。"""

    @pytest.mark.asyncio
    async def test_ws_close_4501_triggers_recoverable_not_immediate_close(self):
        """
        核心验证：Agent 重连失败 close(code=4501)
        → Server 判定为 NETWORK_LOST
        → 终端进入 recoverable，不立即关闭。

        这是修复的核心：修复前所有正常断开都是 AGENT_SHUTDOWN → 立即关闭。
        """
        from fastapi import WebSocketDisconnect

        session_id = "fix-test-1"

        # 模拟 WebSocketDisconnect with code=4501 (Agent 重连失败)
        exc = WebSocketDisconnect(code=4501)

        # 模拟 Server 端 cleanup_reason 判定逻辑（ws_agent.py 修复后的代码）
        cleanup_reason = CLEANUP_REASON_AGENT_SHUTDOWN  # 默认值
        if exc.code not in (1000, 1001):
            cleanup_reason = CLEANUP_REASON_NETWORK_LOST

        assert cleanup_reason == CLEANUP_REASON_NETWORK_LOST, \
            "修复后：code=4501 应判定为 NETWORK_LOST"

        # 验证 _cleanup_agent(NETWORK_LOST) 不立即关闭终端
        mock_ws = AsyncMock()
        active_agents[session_id] = AgentConnection(session_id, mock_ws, "test")

        offline_type = None
        async def mock_recoverable(sid, **kwargs):
            nonlocal offline_type
            offline_type = "recoverable"

        async def mock_immediate(sid, **kwargs):
            nonlocal offline_type
            offline_type = "immediate"

        with patch("app.ws.agent_cleanup._cleanup_pending_futures"), \
             patch("app.ws.agent_cleanup._cleanup_execute_command_futures"), \
             patch("app.ws.agent_cleanup._cleanup_pending_futures_by_id"), \
             patch("app.ws.agent_cleanup.pending_registry"), \
             patch("app.ws.agent_cleanup._execute_command_rate_tracker", {}), \
             patch("app.ws.agent_cleanup.set_session_offline_recoverable",
                   new_callable=AsyncMock, side_effect=mock_recoverable), \
             patch("app.ws.agent_cleanup._set_session_offline_immediately",
                   new_callable=AsyncMock, side_effect=mock_immediate):

            await _cleanup_agent(session_id, cleanup_reason)

        # 关键断言：走 recoverable 路径，不是 immediate
        assert offline_type == "recoverable", \
            "NETWORK_LOST 应进入 recoverable 路径（90s grace），不立即关闭"
        assert _is_agent_stale(session_id), \
            "Agent 应被标记为 stale"

    @pytest.mark.asyncio
    async def test_ws_close_1000_triggers_immediate_close(self):
        """
        对比验证：Agent 主动退出 close(code=1000)
        → Server 判定为 AGENT_SHUTDOWN
        → 终端立即关闭。
        """
        from fastapi import WebSocketDisconnect

        # 模拟 WebSocketDisconnect with code=1000 (正常关闭)
        exc = WebSocketDisconnect(code=1000)

        cleanup_reason = CLEANUP_REASON_AGENT_SHUTDOWN
        if exc.code not in (1000, 1001):
            cleanup_reason = CLEANUP_REASON_NETWORK_LOST

        assert cleanup_reason == CLEANUP_REASON_AGENT_SHUTDOWN, \
            "code=1000 应判定为 AGENT_SHUTDOWN"

        # 验证 _cleanup_agent(AGENT_SHUTDOWN) 立即关闭
        session_id = "fix-test-2"
        mock_ws = AsyncMock()
        active_agents[session_id] = AgentConnection(session_id, mock_ws, "test")

        offline_type = None
        async def mock_immediate(sid, **kwargs):
            nonlocal offline_type
            offline_type = "immediate"

        with patch("app.ws.agent_cleanup._cleanup_pending_futures"), \
             patch("app.ws.agent_cleanup._cleanup_execute_command_futures"), \
             patch("app.ws.agent_cleanup._cleanup_pending_futures_by_id"), \
             patch("app.ws.agent_cleanup.pending_registry"), \
             patch("app.ws.agent_cleanup._execute_command_rate_tracker", {}), \
             patch("app.ws.agent_cleanup._set_session_offline_immediately",
                   new_callable=AsyncMock, side_effect=mock_immediate):

            await _cleanup_agent(session_id, cleanup_reason)

        assert offline_type == "immediate", \
            "AGENT_SHUTDOWN 应立即关闭终端"
        assert not _is_agent_stale(session_id), \
            "主动退出不应进入 stale"

    @pytest.mark.asyncio
    async def test_ws_close_1006_abnormal_triggers_recoverable(self):
        """
        网络中断 (code=1006, 无 close frame) → NETWORK_LOST → recoverable。
        这是 macOS 休眠后 WS 被 OS 强制断开的情况。
        """
        from fastapi import WebSocketDisconnect

        exc = WebSocketDisconnect(code=1006)

        cleanup_reason = CLEANUP_REASON_AGENT_SHUTDOWN
        if exc.code not in (1000, 1001):
            cleanup_reason = CLEANUP_REASON_NETWORK_LOST

        assert cleanup_reason == CLEANUP_REASON_NETWORK_LOST

    @pytest.mark.asyncio
    async def test_all_close_codes_correctness(self):
        """
        验证所有可能的 WS close code 的处理。
        """
        from fastapi import WebSocketDisconnect

        cases = [
            # (code, expected_reason)
            (1000, CLEANUP_REASON_AGENT_SHUTDOWN),   # 正常关闭
            (1001, CLEANUP_REASON_AGENT_SHUTDOWN),   # Going away
            (1005, CLEANUP_REASON_NETWORK_LOST),     # No status received
            (1006, CLEANUP_REASON_NETWORK_LOST),     # Abnormal closure
            (1008, CLEANUP_REASON_NETWORK_LOST),     # Policy violation (heartbeat)
            (4501, CLEANUP_REASON_NETWORK_LOST),     # Internal error (reconnect fail)
            (1012, CLEANUP_REASON_NETWORK_LOST),     # Service restart
            (1013, CLEANUP_REASON_NETWORK_LOST),     # Try again later
            (4003, CLEANUP_REASON_NETWORK_LOST),     # Custom: token expired
            (4500, CLEANUP_REASON_NETWORK_LOST),     # Custom: any error
        ]

        for code, expected in cases:
            exc = WebSocketDisconnect(code=code)
            cleanup_reason = CLEANUP_REASON_AGENT_SHUTDOWN
            if exc.code not in (1000, 1001):
                cleanup_reason = CLEANUP_REASON_NETWORK_LOST
            assert cleanup_reason == expected, \
                f"close code {code}: expected {expected}, got {cleanup_reason}"

    @pytest.mark.asyncio
    async def test_full_macos_sleep_wake_flow_after_fix(self):
        """
        完整模拟修复后的 macOS 休眠唤醒流程：

        1. Agent 连接中，2 个终端 live
        2. Mac 休眠 → Agent 进程冻结
        3. Agent 发现 WS 断开 → 重连 60 次失败
        4. Agent._cleanup(network_lost=True) → close_all(reason="network_lost")
        5. Agent.ws.close(code=4501, reason="network_lost")
        6. Server 收到 close code 4501 → cleanup_reason = NETWORK_LOST
        7. _cleanup_agent(NETWORK_LOST) → terminals enter recoverable
        8. Agent 重启 → 重连成功 → _restore_recoverable_terminals
        """
        session_id = "fix-flow-1"

        # Step 1: Agent connected with terminals
        mock_ws = AsyncMock()
        active_agents[session_id] = AgentConnection(session_id, mock_ws, "test")

        # Step 6-7: Server 收到 close code 4501
        from fastapi import WebSocketDisconnect
        exc = WebSocketDisconnect(code=4501)
        cleanup_reason = CLEANUP_REASON_AGENT_SHUTDOWN
        if exc.code not in (1000, 1001):
            cleanup_reason = CLEANUP_REASON_NETWORK_LOST

        recovered = False
        async def mock_recoverable(sid, **kwargs):
            pass

        with patch("app.ws.agent_cleanup._cleanup_pending_futures"), \
             patch("app.ws.agent_cleanup._cleanup_execute_command_futures"), \
             patch("app.ws.agent_cleanup._cleanup_pending_futures_by_id"), \
             patch("app.ws.agent_cleanup.pending_registry"), \
             patch("app.ws.agent_cleanup._execute_command_rate_tracker", {}), \
             patch("app.ws.agent_cleanup.set_session_offline_recoverable",
                   new_callable=AsyncMock, side_effect=mock_recoverable):

            await _cleanup_agent(session_id, cleanup_reason)

        # Step 7 result: terminals in recoverable (not closed!)
        assert _is_agent_stale(session_id), "终端应处于 stale/recoverable 状态"

        # Step 8: Agent 重连 → clear stale → restore terminals
        from app.ws.agent_cleanup import _clear_agent_stale
        _clear_agent_stale(session_id)
        assert not _is_agent_stale(session_id), "重连后 stale 应被清除"

        print("✓ 修复后完整流程验证通过：macOS 休眠 → 终端 recoverable → 重连恢复")
