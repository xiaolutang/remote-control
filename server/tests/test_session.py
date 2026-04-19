"""
Redis 会话存储测试
"""
import pytest
import json
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
from concurrent.futures import ThreadPoolExecutor

from app.session import (
    create_session,
    get_session,
    update_session_status,
    update_session_device_metadata,
    update_session_device_heartbeat,
    create_session_terminal,
    update_session_terminal_status,
    list_session_terminals,
    list_recoverable_session_terminals,
    bulk_update_session_terminals,
    is_terminal_recoverable,
    update_session_terminal_metadata,
    update_session_terminal_pty,
    update_session_terminal_views,
    append_history,
    get_history,
    get_history_count,
    cleanup_old_history,
    _validate_session_id,
    _normalize_session_data,
    _default_device_state,
    _close_expired_detached_terminals,
    _backfill_terminal_views,
    redis_conn,
)
from fastapi import HTTPException


class TestValidateSessionId:
    """session_id 验证测试"""

    def test_valid_session_id(self):
        """有效的 session_id"""
        # 不应抛出异常
        _validate_session_id("valid-session-123")
        _validate_session_id("abc")

    def test_empty_session_id(self):
        """空 session_id → 400"""
        with pytest.raises(HTTPException) as e:
            _validate_session_id("")
        assert e.value.status_code == 400
        assert "空" in e.value.detail

    def test_oversized_session_id(self):
        """超长 session_id (1KB) → 400"""
        long_id = "a" * 1500
        with pytest.raises(HTTPException) as e:
            _validate_session_id(long_id)
        assert e.value.status_code == 400
        assert "过长" in e.value.detail


class TestCreateSession:
    """创建会话测试"""

    @pytest.mark.asyncio
    async def test_create_and_read_session(self):
        """创建会话 → 读取状态一致"""
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=False)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            result = await create_session("test-session-1")

        assert result["session_id"] == "test-session-1"
        assert result["status"] == "pending"
        assert "created_at" in result

    @pytest.mark.asyncio
    async def test_create_session_with_name(self):
        """创建带名称的会话"""
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=False)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            result = await create_session("session-2", name="My Project")

        assert result["session_id"] == "session-2"

    @pytest.mark.asyncio
    async def test_create_session_includes_default_device_state(self):
        """新会话默认带 device 状态"""
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=False)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            await create_session("device-session")

        saved = json.loads(mock_redis.set.await_args.args[1])
        assert saved["device"] == _default_device_state("device-session")

    @pytest.mark.asyncio
    async def test_create_duplicate_session(self):
        """创建重复会话 → 409"""
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=True)  # 已存在

        with patch.object(redis_conn, '_redis', mock_redis):
            with pytest.raises(HTTPException) as e:
                await create_session("existing-session")
            assert e.value.status_code == 409


class TestUpdateStatus:
    """更新状态测试"""

    @pytest.mark.asyncio
    async def test_update_status(self):
        """更新状态 → 读取一致"""
        existing_data = json.dumps({
            "status": "pending",
            "created_at": "2026-03-26T10:00:00Z",
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=existing_data)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            result = await update_session_status("session-1", "online")

        assert result["status"] == "online"
        assert "updated_at" in result

    @pytest.mark.asyncio
    async def test_update_nonexistent_session(self):
        """更新不存在的会话 → 404"""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch.object(redis_conn, '_redis', mock_redis):
            with pytest.raises(HTTPException) as e:
                await update_session_status("nonexistent", "online")
            assert e.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_invalid_status(self):
        """更新为无效状态 → 400"""
        with pytest.raises(HTTPException) as e:
            await update_session_status("session-1", "invalid-status")
        assert e.value.status_code == 400


class TestDeviceState:
    """device 状态测试"""

    def test_normalize_legacy_session_adds_device_defaults(self):
        """旧 session 自动补齐 device 字段"""
        legacy = {
            "status": "pending",
            "created_at": "2026-03-26T10:00:00Z",
            "agent_online": False,
        }

        normalized = _normalize_session_data("legacy-session", legacy)

        assert normalized["device"]["device_id"] == "legacy-session"
        assert normalized["device"]["max_terminals"] == 3
        assert normalized["views"] == {"mobile": 0, "desktop": 0}

    def test_normalize_legacy_terminal_adds_terminal_pty(self):
        """旧 terminal 自动继承 session 级 PTY。"""
        legacy = {
            "status": "pending",
            "created_at": "2026-03-26T10:00:00Z",
            "agent_online": False,
            "pty": {"rows": 42, "cols": 120},
            "terminals": [
                {
                    "terminal_id": "term-1",
                    "title": "Claude / one",
                    "cwd": "/tmp/one",
                    "command": "claude code",
                    "env": {},
                    "status": "detached",
                    "created_at": "2026-03-26T10:00:00Z",
                    "updated_at": "2026-03-26T10:00:00Z",
                }
            ],
        }

        normalized = _normalize_session_data("legacy-session", legacy)

        assert normalized["terminals"][0]["pty"] == {"rows": 42, "cols": 120}

    @pytest.mark.asyncio
    async def test_get_session_persists_normalized_device_state(self):
        """读取旧 session 时会回写兼容后的 device 字段"""
        legacy_data = json.dumps({
            "status": "pending",
            "created_at": "2026-03-26T10:00:00Z",
            "owner": "user1",
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=legacy_data)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            result = await get_session("legacy-session")

        assert result["device"]["device_id"] == "legacy-session"
        mock_redis.set.assert_awaited()

    @pytest.mark.asyncio
    async def test_get_session_migrates_unconfigured_max_terminals_to_default(self):
        """旧设备未显式配置 max_terminals 时，自动迁移到新的默认值。"""
        legacy_data = json.dumps({
            "status": "pending",
            "created_at": "2026-03-26T10:00:00Z",
            "owner": "user1",
            "device": {
                "device_id": "legacy-session",
                "name": "Legacy Mac",
                "platform": "macos",
                "hostname": "legacy-mac",
                "max_terminals": 1,
            },
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=legacy_data)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            result = await get_session("legacy-session")

        assert result["device"]["max_terminals"] == 3
        assert result["device"]["max_terminals_configured"] is False
        mock_redis.set.assert_awaited()

    @pytest.mark.asyncio
    async def test_update_session_device_metadata(self):
        """更新 device 元数据"""
        existing_data = json.dumps({
            "status": "pending",
            "created_at": "2026-03-26T10:00:00Z",
            "agent_online": False,
            "device": _default_device_state("legacy-session"),
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=existing_data)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            result = await update_session_device_metadata(
                "legacy-session",
                device_id="mbp-01",
                name="Tang MacBook Pro",
                platform="macos",
                hostname="tang-mbp",
                max_terminals=5,
                online=True,
            )

        assert result["agent_online"] is True
        assert result["device"]["device_id"] == "mbp-01"
        assert result["device"]["name"] == "Tang MacBook Pro"
        assert result["device"]["max_terminals"] == 5

    @pytest.mark.asyncio
    async def test_update_session_device_metadata_rejects_invalid_max_terminals(self):
        """max_terminals 必须大于 0"""
        existing_data = json.dumps({
            "status": "pending",
            "created_at": "2026-03-26T10:00:00Z",
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=existing_data)

        with patch.object(redis_conn, '_redis', mock_redis):
            with pytest.raises(HTTPException) as e:
                await update_session_device_metadata("legacy-session", max_terminals=0)

        assert e.value.status_code == 400

    @pytest.mark.asyncio
    async def test_update_session_device_heartbeat(self):
        """device 心跳会刷新时间并标记在线"""
        existing_data = json.dumps({
            "status": "pending",
            "created_at": "2026-03-26T10:00:00Z",
            "agent_online": False,
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=existing_data)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            result = await update_session_device_heartbeat("legacy-session")

        assert result["agent_online"] is True
        assert result["device"]["last_heartbeat_at"] is not None


class TestTerminalState:
    """terminal 状态与上限测试"""

    def test_reconcile_attached_terminal_without_views(self):
        """read-path 不再根据陈旧 views 推断 attached/detached。"""
        now = datetime.now(timezone.utc)
        terminals = [
            {
                "terminal_id": "term-stale",
                "status": "attached",
                "views": {"mobile": 0, "desktop": 0},
                "updated_at": now.isoformat(),
            },
            {
                "terminal_id": "term-live",
                "status": "attached",
                "views": {"mobile": 1, "desktop": 0},
                "updated_at": now.isoformat(),
            },
        ]

        changed = _backfill_terminal_views(terminals)

        assert changed == 0
        assert terminals[0]["status"] == "attached"
        assert terminals[1]["status"] == "attached"

    def test_normalize_invalid_geometry_owner_view_to_none(self):
        legacy = {
            "status": "pending",
            "created_at": "2026-03-26T10:00:00Z",
            "agent_online": False,
            "terminals": [
                {
                    "terminal_id": "term-1",
                    "title": "Claude / one",
                    "cwd": "/tmp/one",
                    "command": "claude code",
                    "env": {},
                    "status": "detached",
                    "geometry_owner_view": "tablet",
                    "created_at": "2026-03-26T10:00:00Z",
                    "updated_at": "2026-03-26T10:00:00Z",
                }
            ],
        }

        normalized = _normalize_session_data("legacy-session", legacy)

        assert normalized["terminals"][0]["geometry_owner_view"] is None

    def test_close_expired_detached_terminals(self):
        """超出 grace period 的 detached terminal 会被关闭。"""
        now = datetime.now(timezone.utc)
        terminals = [
            {
                "terminal_id": "term-expired",
                "status": "detached_recoverable",
                "disconnect_reason": "network_lost",
                "grace_expires_at": (now - timedelta(seconds=1)).isoformat(),
                "updated_at": now.isoformat(),
            },
            {
                "terminal_id": "term-active",
                "status": "detached_recoverable",
                "disconnect_reason": "network_lost",
                "grace_expires_at": (now + timedelta(seconds=30)).isoformat(),
                "updated_at": now.isoformat(),
            },
        ]

        changed = _close_expired_detached_terminals(terminals, now)

        assert changed == 1
        assert terminals[0]["status"] == "closed"
        assert terminals[0]["disconnect_reason"] == "network_lost"
        assert terminals[0]["grace_expires_at"] is None
        assert terminals[1]["status"] == "detached_recoverable"

    @pytest.mark.asyncio
    async def test_create_multiple_terminals_on_same_device(self):
        """同一 device 下创建多个 terminal"""
        existing_data = json.dumps({
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "device": {
                **_default_device_state("session-1"),
                "max_terminals": 2,
            },
            "terminals": [],
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=[existing_data, json.dumps({
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "device": {
                **_default_device_state("session-1"),
                "max_terminals": 2,
            },
            "terminals": [
                {
                    "terminal_id": "term-1",
                    "title": "Claude / one",
                    "cwd": "/tmp/one",
                    "command": "claude code",
                    "env": {},
                    "status": "pending",
                    "disconnect_reason": None,
                    "views": {"mobile": 0, "desktop": 0},
                    "created_at": "2026-03-26T10:00:00Z",
                    "updated_at": "2026-03-26T10:00:00Z",
                }
            ],
        })])
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            first = await create_session_terminal(
                "session-1",
                terminal_id="term-1",
                title="Claude / one",
                cwd="/tmp/one",
                command="claude code",
            )
            second = await create_session_terminal(
                "session-1",
                terminal_id="term-2",
                title="Claude / two",
                cwd="/tmp/two",
                command="/bin/bash",
            )

        assert first["terminal_id"] == "term-1"
        assert second["terminal_id"] == "term-2"

    @pytest.mark.asyncio
    async def test_reject_create_terminal_when_reaching_max_terminals(self):
        """超过 max_terminals 时拒绝创建"""
        existing_data = json.dumps({
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "device": {
                **_default_device_state("session-1"),
                "max_terminals": 1,
                "max_terminals_configured": True,
            },
            "terminals": [
                {
                    "terminal_id": "term-1",
                    "title": "Claude / one",
                    "cwd": "/tmp/one",
                    "command": "claude code",
                    "env": {},
                    "status": "attached",
                    "disconnect_reason": None,
                    "views": {"mobile": 0, "desktop": 0},
                    "created_at": "2026-03-26T10:00:00Z",
                    "updated_at": "2026-03-26T10:00:00Z",
                }
            ],
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=existing_data)

        with patch.object(redis_conn, '_redis', mock_redis):
            with pytest.raises(HTTPException) as e:
                await create_session_terminal(
                    "session-1",
                    terminal_id="term-2",
                    title="Claude / two",
                    cwd="/tmp/two",
                    command="/bin/bash",
                )

        assert e.value.status_code == 409

    @pytest.mark.asyncio
    async def test_closed_terminal_releases_capacity(self):
        """terminal 关闭后释放名额"""
        existing_data = json.dumps({
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "device": {
                **_default_device_state("session-1"),
                "max_terminals": 1,
                "max_terminals_configured": True,
            },
            "terminals": [
                {
                    "terminal_id": "term-1",
                    "title": "Claude / one",
                    "cwd": "/tmp/one",
                    "command": "claude code",
                    "env": {},
                    "status": "attached",
                    "disconnect_reason": None,
                    "views": {"mobile": 0, "desktop": 0},
                    "created_at": "2026-03-26T10:00:00Z",
                    "updated_at": "2026-03-26T10:00:00Z",
                }
            ],
        })
        after_close = json.dumps({
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "device": {
                **_default_device_state("session-1"),
                "max_terminals": 1,
                "max_terminals_configured": True,
            },
            "terminals": [
                {
                    "terminal_id": "term-1",
                    "title": "Claude / one",
                    "cwd": "/tmp/one",
                    "command": "claude code",
                    "env": {},
                    "status": "closed",
                    "disconnect_reason": "terminal_exit",
                    "views": {"mobile": 0, "desktop": 0},
                    "created_at": "2026-03-26T10:00:00Z",
                    "updated_at": "2026-03-26T10:01:00Z",
                }
            ],
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=[existing_data, after_close, after_close])
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            closed = await update_session_terminal_status(
                "session-1",
                "term-1",
                terminal_status="closed",
                disconnect_reason="terminal_exit",
            )
            created = await create_session_terminal(
                "session-1",
                terminal_id="term-2",
                title="Claude / two",
                cwd="/tmp/two",
                command="/bin/bash",
            )

        assert closed["status"] == "closed"
        assert created["terminal_id"] == "term-2"

    @pytest.mark.asyncio
    async def test_closing_terminal_clears_view_counts(self):
        """terminal 标记 closed 后不再保留活动 views。"""
        existing_data = json.dumps({
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "device": _default_device_state("session-1"),
            "terminals": [
                {
                    "terminal_id": "term-1",
                    "title": "Claude / one",
                    "cwd": "/tmp/one",
                    "command": "claude code",
                    "env": {},
                    "status": "attached",
                    "disconnect_reason": None,
                    "views": {"mobile": 1, "desktop": 1},
                    "created_at": "2026-03-26T10:00:00Z",
                    "updated_at": "2026-03-26T10:00:00Z",
                }
            ],
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=existing_data)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            closed = await update_session_terminal_status(
                "session-1",
                "term-1",
                terminal_status="closed",
                disconnect_reason="server_forced_close",
            )

        assert closed["views"] == {"mobile": 0, "desktop": 0}
        assert closed["geometry_owner_view"] is None
        saved = json.loads(mock_redis.set.await_args.args[1])
        assert saved["terminals"][0]["views"] == {"mobile": 0, "desktop": 0}

    @pytest.mark.asyncio
    async def test_update_terminal_views_prefers_first_attached_owner(self):
        existing_data = json.dumps({
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "device": _default_device_state("session-1"),
            "terminals": [
                {
                    "terminal_id": "term-1",
                    "title": "Claude / one",
                    "cwd": "/tmp/one",
                    "command": "claude code",
                    "env": {},
                    "status": "attached",
                    "disconnect_reason": None,
                    "views": {"mobile": 1, "desktop": 0},
                    "geometry_owner_view": "mobile",
                    "created_at": "2026-03-26T10:00:00Z",
                    "updated_at": "2026-03-26T10:00:00Z",
                }
            ],
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=existing_data)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            updated = await update_session_terminal_views(
                "session-1",
                "term-1",
                views={"mobile": 1, "desktop": 1},
                preferred_owner_view="desktop",
            )

        assert updated["geometry_owner_view"] == "mobile"

    @pytest.mark.asyncio
    async def test_update_terminal_views_assigns_new_owner_when_previous_owner_left(self):
        existing_data = json.dumps({
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "device": _default_device_state("session-1"),
            "terminals": [
                {
                    "terminal_id": "term-1",
                    "title": "Claude / one",
                    "cwd": "/tmp/one",
                    "command": "claude code",
                    "env": {},
                    "status": "attached",
                    "disconnect_reason": None,
                    "views": {"mobile": 1, "desktop": 1},
                    "geometry_owner_view": "mobile",
                    "created_at": "2026-03-26T10:00:00Z",
                    "updated_at": "2026-03-26T10:00:00Z",
                }
            ],
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=existing_data)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            updated = await update_session_terminal_views(
                "session-1",
                "term-1",
                views={"mobile": 0, "desktop": 1},
            )

        assert updated["geometry_owner_view"] == "desktop"

    @pytest.mark.asyncio
    async def test_expired_detached_terminal_releases_capacity(self):
        """过期 detached terminal 不应继续占用名额。"""
        now = datetime.now(timezone.utc)
        existing_data = json.dumps({
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "device": {
                **_default_device_state("session-1"),
                "max_terminals": 1,
            },
            "terminals": [
                {
                    "terminal_id": "term-old",
                    "title": "Claude / one",
                    "cwd": "/tmp/one",
                    "command": "claude code",
                    "env": {},
            "status": "detached_recoverable",
                    "disconnect_reason": "network_lost",
                    "grace_expires_at": (now - timedelta(seconds=1)).isoformat(),
                    "views": {"mobile": 0, "desktop": 0},
                    "created_at": "2026-03-26T10:00:00Z",
                    "updated_at": "2026-03-26T10:00:00Z",
                }
            ],
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=existing_data)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            created = await create_session_terminal(
                "session-1",
                terminal_id="term-2",
                title="Claude / two",
                cwd="/tmp/two",
                command="/bin/bash",
            )

        assert created["terminal_id"] == "term-2"
        saved = json.loads(mock_redis.set.await_args.args[1])
        assert saved["terminals"][0]["status"] == "closed"
        assert saved["terminals"][0]["disconnect_reason"] == "network_lost"
        assert saved["terminals"][1]["terminal_id"] == "term-2"

    @pytest.mark.asyncio
    async def test_list_session_terminals(self):
        """列出 session 下的 terminals"""
        existing_data = json.dumps({
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "terminals": [
                {
                    "terminal_id": "term-1",
                    "title": "Claude / one",
                    "cwd": "/tmp/one",
                    "command": "claude code",
                    "env": {},
                    "status": "live",
                    "disconnect_reason": None,
                    "views": {"mobile": 0, "desktop": 0},
                    "created_at": "2026-03-26T10:00:00Z",
                    "updated_at": "2026-03-26T10:00:00Z",
                }
            ],
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=existing_data)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            terminals = await list_session_terminals("session-1")

        assert len(terminals) == 1
        assert terminals[0]["terminal_id"] == "term-1"

    @pytest.mark.asyncio
    async def test_list_session_terminals_closes_expired_detached(self):
        """列 terminal 时会自动关闭过期 detached terminal。"""
        now = datetime.now(timezone.utc)
        existing_data = json.dumps({
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "terminals": [
                {
                    "terminal_id": "term-1",
                    "title": "Claude / one",
                    "cwd": "/tmp/one",
                    "command": "claude code",
                    "env": {},
                    "status": "detached_recoverable",
                    "disconnect_reason": "network_lost",
                    "grace_expires_at": (now - timedelta(seconds=1)).isoformat(),
                    "views": {"mobile": 0, "desktop": 0},
                    "created_at": "2026-03-26T10:00:00Z",
                    "updated_at": "2026-03-26T10:00:00Z",
                }
            ],
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=existing_data)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            terminals = await list_session_terminals("session-1")

        assert terminals[0]["status"] == "closed"
        mock_redis.set.assert_awaited()

    @pytest.mark.asyncio
    async def test_list_session_terminals_keeps_attached_status_until_ws_cleanup(self):
        """列 terminal 时不再凭陈旧 views 把 live 改成 detached_recoverable。"""
        now = datetime.now(timezone.utc)
        existing_data = json.dumps({
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "terminals": [
                {
                    "terminal_id": "term-1",
                    "title": "Claude / one",
                    "cwd": "/tmp/one",
                    "command": "claude code",
                    "env": {},
                    "status": "live",
                    "disconnect_reason": None,
                    "grace_expires_at": None,
                    "views": {"mobile": 0, "desktop": 0},
                    "created_at": "2026-03-26T10:00:00Z",
                    "updated_at": now.isoformat(),
                }
            ],
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=existing_data)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            terminals = await list_session_terminals("session-1")

        assert terminals[0]["status"] == "live"
        mock_redis.set.assert_awaited()

    @pytest.mark.asyncio
    async def test_update_session_terminal_views_syncs_status(self):
        """terminal views 同步时会收敛 live/detached_recoverable。"""
        existing_data = json.dumps({
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "terminals": [
                {
                    "terminal_id": "term-1",
                    "title": "Claude / one",
                    "cwd": "/tmp/one",
                    "command": "claude code",
                    "env": {},
                    "status": "detached_recoverable",
                    "disconnect_reason": None,
                    "grace_expires_at": None,
                    "views": {"mobile": 0, "desktop": 0},
                    "created_at": "2026-03-26T10:00:00Z",
                    "updated_at": "2026-03-26T10:00:00Z",
                }
            ],
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=existing_data)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            terminal = await update_session_terminal_views(
                "session-1",
                "term-1",
                views={"mobile": 1, "desktop": 0},
            )

        assert terminal["status"] == "live"
        assert terminal["views"] == {"mobile": 1, "desktop": 0}

    @pytest.mark.asyncio
    async def test_update_session_terminal_pty_syncs_terminal_geometry(self):
        """terminal PTY 尺寸更新会落到 terminal 记录。"""
        existing_data = json.dumps({
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "pty": {"rows": 24, "cols": 80},
            "terminals": [
                {
                    "terminal_id": "term-1",
                    "title": "Claude / one",
                    "cwd": "/tmp/one",
                    "command": "claude code",
                    "env": {},
                    "pty": {"rows": 24, "cols": 80},
                    "status": "detached",
                    "disconnect_reason": None,
                    "grace_expires_at": None,
                    "views": {"mobile": 0, "desktop": 0},
                    "created_at": "2026-03-26T10:00:00Z",
                    "updated_at": "2026-03-26T10:00:00Z",
                }
            ],
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=existing_data)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            terminal = await update_session_terminal_pty(
                "session-1",
                "term-1",
                rows=40,
                cols=120,
            )

        assert terminal["pty"] == {"rows": 40, "cols": 120}

    @pytest.mark.asyncio
    async def test_list_session_terminals_trims_to_recent_five_records(self):
        """terminal 列表最多保留 5 条，优先保留活动 terminal。"""
        terminals = []
        for index in range(6):
            terminals.append({
                "terminal_id": f"closed-{index}",
                "title": f"Closed {index}",
                "cwd": f"/tmp/{index}",
                "command": "/bin/bash",
                "env": {},
                "status": "closed",
                "disconnect_reason": "terminal_exit",
                "views": {"mobile": 0, "desktop": 0},
                "created_at": f"2026-03-26T10:00:0{index}Z",
                "updated_at": f"2026-03-26T10:00:0{index}Z",
            })
        terminals.append({
            "terminal_id": "attached-1",
            "title": "Attached",
            "cwd": "/tmp/attached",
            "command": "/bin/bash",
            "env": {},
            "status": "attached",
            "disconnect_reason": None,
            "views": {"mobile": 1, "desktop": 0},
            "created_at": "2026-03-26T10:01:00Z",
            "updated_at": "2026-03-26T10:01:00Z",
        })

        existing_data = json.dumps({
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "terminals": terminals,
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=existing_data)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            result = await list_session_terminals("session-1")

        assert len(result) == 5
        assert any(terminal["terminal_id"] == "attached-1" for terminal in result)
        assert all(
            terminal["terminal_id"] != "closed-0"
            for terminal in result
        )
        mock_redis.set.assert_awaited()

    @pytest.mark.asyncio
    async def test_list_recoverable_session_terminals_filters_by_grace(self):
        """只返回 grace period 内仍可恢复的 detached_recoverable terminal。"""
        now = datetime.now(timezone.utc)
        existing_data = json.dumps({
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "terminals": [
                {
                    "terminal_id": "term-ok",
                    "title": "Claude / one",
                    "cwd": "/tmp/one",
                    "command": "claude code",
                    "env": {},
                    "status": "detached_recoverable",
                    "disconnect_reason": "network_lost",
                    "grace_expires_at": (now + timedelta(seconds=30)).isoformat(),
                    "views": {"mobile": 0, "desktop": 0},
                    "created_at": "2026-03-26T10:00:00Z",
                    "updated_at": "2026-03-26T10:00:00Z",
                },
                {
                    "terminal_id": "term-expired",
                    "title": "Claude / two",
                    "cwd": "/tmp/two",
                    "command": "/bin/bash",
                    "env": {},
                    "status": "detached_recoverable",
                    "disconnect_reason": "network_lost",
                    "grace_expires_at": (now - timedelta(seconds=1)).isoformat(),
                    "views": {"mobile": 0, "desktop": 0},
                    "created_at": "2026-03-26T10:00:00Z",
                    "updated_at": "2026-03-26T10:00:00Z",
                },
                {
                    "terminal_id": "term-closed",
                    "title": "Claude / three",
                    "cwd": "/tmp/three",
                    "command": "/bin/bash",
                    "env": {},
                    "status": "closed",
                    "disconnect_reason": "terminal_exit",
                    "grace_expires_at": None,
                    "views": {"mobile": 0, "desktop": 0},
                    "created_at": "2026-03-26T10:00:00Z",
                    "updated_at": "2026-03-26T10:00:00Z",
                },
            ],
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=existing_data)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            terminals = await list_recoverable_session_terminals("session-1")

        assert [terminal["terminal_id"] for terminal in terminals] == ["term-ok"]

    @pytest.mark.asyncio
    async def test_bulk_update_session_terminals_marks_disconnect_reason(self):
        """批量更新 terminal 状态与关闭原因"""
        existing_data = json.dumps({
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "terminals": [
                {
                    "terminal_id": "term-1",
                    "title": "Claude / one",
                    "cwd": "/tmp/one",
                    "command": "claude code",
                    "env": {},
                    "status": "live",
                    "disconnect_reason": None,
                    "views": {"mobile": 1, "desktop": 0},
                    "created_at": "2026-03-26T10:00:00Z",
                    "updated_at": "2026-03-26T10:00:00Z",
                }
            ],
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=existing_data)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            result = await bulk_update_session_terminals(
                "session-1",
                from_statuses={"live"},
                to_status="detached_recoverable",
                disconnect_reason="network_lost",
                grace_seconds=60,
            )

        assert result["changed"] == 1
        assert result["terminals"][0]["status"] == "detached_recoverable"
        assert result["terminals"][0]["disconnect_reason"] == "network_lost"
        assert result["terminals"][0]["grace_expires_at"] is not None

    @pytest.mark.asyncio
    async def test_bulk_update_closed_terminals_clears_views_and_grace(self):
        """批量收口为 closed 时清理 views 与 grace。"""
        existing_data = json.dumps({
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "terminals": [
                {
                    "terminal_id": "term-1",
                    "title": "Claude / one",
                    "cwd": "/tmp/one",
                    "command": "claude code",
                    "env": {},
                    "status": "detached",
                    "disconnect_reason": "network_lost",
                    "grace_expires_at": "2026-03-26T10:01:00+00:00",
                    "views": {"mobile": 1, "desktop": 1},
                    "created_at": "2026-03-26T10:00:00Z",
                    "updated_at": "2026-03-26T10:00:00Z",
                }
            ],
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=existing_data)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            result = await bulk_update_session_terminals(
                "session-1",
                from_statuses={"detached_recoverable"},
                to_status="closed",
                disconnect_reason="device_offline",
            )

        assert result["changed"] == 1
        assert result["terminals"][0]["status"] == "closed"
        assert result["terminals"][0]["disconnect_reason"] == "device_offline"
        assert result["terminals"][0]["grace_expires_at"] is None
        assert result["terminals"][0]["views"] == {"mobile": 0, "desktop": 0}

    def test_is_terminal_recoverable_within_grace_period(self):
        """grace period 内允许恢复"""
        now = datetime.now(timezone.utc)
        terminal = {
            "status": "detached_recoverable",
            "grace_expires_at": (now + timedelta(seconds=30)).isoformat(),
        }

        assert is_terminal_recoverable(terminal, now=now) is True

    def test_is_terminal_recoverable_after_grace_period(self):
        """grace period 过后不可恢复"""
        now = datetime.now(timezone.utc)
        terminal = {
            "status": "detached_recoverable",
            "grace_expires_at": (now - timedelta(seconds=1)).isoformat(),
        }

        assert is_terminal_recoverable(terminal, now=now) is False

    @pytest.mark.asyncio
    async def test_update_session_terminal_metadata(self):
        """更新 terminal 标题元数据。"""
        existing_data = json.dumps({
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "terminals": [
                {
                    "terminal_id": "term-1",
                    "title": "Old Title",
                    "cwd": "/tmp/one",
                    "command": "/bin/bash",
                    "env": {},
                    "status": "detached",
                    "disconnect_reason": None,
                    "views": {"mobile": 0, "desktop": 0},
                    "created_at": "2026-03-26T10:00:00Z",
                    "updated_at": "2026-03-26T10:00:00Z",
                }
            ],
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=existing_data)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            terminal = await update_session_terminal_metadata(
                "session-1",
                "term-1",
                title="New Title",
            )

        assert terminal["title"] == "New Title"
        mock_redis.set.assert_awaited()


class TestHistoryOperations:
    """历史记录操作测试"""

    @pytest.mark.asyncio
    async def test_append_history(self):
        """追加历史 → 读取正确"""
        mock_redis = AsyncMock()
        mock_redis.rpush = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            result = await append_history("session-1", "Hello World")

        assert "timestamp" in result
        assert "index" in result

    @pytest.mark.asyncio
    async def test_get_history_filters_by_terminal_and_direction(self):
        """terminal 级历史过滤只返回对应 terminal 的 output。"""
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=True)
        mock_redis.llen = AsyncMock(return_value=4)
        mock_redis.lrange = AsyncMock(return_value=[
            json.dumps({"timestamp": "2026-03-26T10:00:00Z", "direction": "output", "terminal_id": "term-1", "data": "a"}),
            json.dumps({"timestamp": "2026-03-26T10:00:01Z", "direction": "input", "terminal_id": "term-1", "data": "ignored-input"}),
            json.dumps({"timestamp": "2026-03-26T10:00:02Z", "direction": "output", "terminal_id": "term-2", "data": "ignored-other-terminal"}),
            json.dumps({"timestamp": "2026-03-26T10:00:03Z", "direction": "output", "terminal_id": "term-1", "data": "b"}),
        ])

        with patch.object(redis_conn, '_redis', mock_redis):
            result = await get_history(
                "session-1",
                offset=0,
                limit=10,
                terminal_id="term-1",
                direction="output",
            )

        assert [item["data"] for item in result] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_pagination(self):
        """分页查询 → 返回正确切片"""
        # Mock 会话存在
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=True)
        mock_redis.llen = AsyncMock(return_value=100)

        # Mock 历史数据
        records = [
            json.dumps({"timestamp": f"2026-03-26T10:00:0{i}Z", "data": f"output {i}"})
            for i in range(10)
        ]
        mock_redis.lrange = AsyncMock(return_value=records)

        with patch.object(redis_conn, '_redis', mock_redis):
            result = await get_history("session-1", offset=0, limit=10)

        assert len(result) == 10

    @pytest.mark.asyncio
    async def test_get_history_empty_session(self):
        """查询不存在会话的历史 → 404"""
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=False)

        with patch.object(redis_conn, '_redis', mock_redis):
            with pytest.raises(HTTPException) as e:
                await get_history("nonexistent")
            assert e.value.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_pagination_offset(self):
        """无效分页参数 offset=-1 → 400"""
        with pytest.raises(HTTPException) as e:
            await get_history("session-1", offset=-1, limit=10)
        assert e.value.status_code == 400

    @pytest.mark.asyncio
    async def test_large_limit(self):
        """limit=10000 → 限制为 1000"""
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=True)
        mock_redis.llen = AsyncMock(return_value=100)
        mock_redis.lrange = AsyncMock(return_value=[])

        with patch.object(redis_conn, '_redis', mock_redis):
            # limit 会被限制为 1000
            await get_history("session-1", offset=0, limit=10000)
            # 验证 lrange 被调用（说明通过了参数验证）
            assert mock_redis.lrange.called


class TestConcurrentOperations:
    """并发操作测试"""

    @pytest.mark.asyncio
    async def test_concurrent_append(self):
        """并发写入同一条历史 100 次 → 无丢失"""
        mock_redis = AsyncMock()
        mock_redis.rpush = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock(return_value=True)

        async def append_one(i):
            with patch.object(redis_conn, '_redis', mock_redis):
                return await append_history("session-1", f"output {i}")

        # 模拟并发
        tasks = [append_one(i) for i in range(100)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 100


class TestCleanup:
    """清理操作测试"""

    @pytest.mark.asyncio
    async def test_cleanup_not_needed(self):
        """记录数少于阈值 → 不清理"""
        mock_redis = AsyncMock()
        mock_redis.llen = AsyncMock(return_value=50)

        with patch.object(redis_conn, '_redis', mock_redis):
            deleted = await cleanup_old_history("session-1", max_records=100)

        assert deleted == 0

    @pytest.mark.asyncio
    async def test_cleanup_needed(self):
        """记录数超过阈值 → 清理旧记录"""
        mock_redis = AsyncMock()
        mock_redis.llen = AsyncMock(return_value=150)
        mock_redis.ltrim = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            deleted = await cleanup_old_history("session-1", max_records=100)

        assert deleted == 50


class TestRedisConnectionFailure:
    """Redis 连接失败测试"""

    @pytest.mark.asyncio
    async def test_redis_connection_failure(self):
        """Redis 断开 → 返回 503 + 友好错误"""
        # 重置连接
        redis_conn._redis = None
        redis_conn._pool = None

        # Mock 连接失败
        with patch('app.session.aioredis.ConnectionPool.from_url') as mock_pool:
            mock_pool.side_effect = Exception("Connection refused")

            with pytest.raises(HTTPException) as e:
                await create_session("test-session")

            assert e.value.status_code == 503
            assert "Redis" in e.value.detail
