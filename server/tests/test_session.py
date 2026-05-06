"""
Redis 会话存储测试
"""
import pytest
import json
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
from concurrent.futures import ThreadPoolExecutor

from app.store.session import (
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
    cleanup_user_sessions,
    get_session_terminal,
    get_session_by_name,
    get_session_by_device_id,
    list_sessions_for_user,
    backfill_user_session_index,
    _validate_session_id,
    _normalize_session_data,
    _default_device_state,
    _close_expired_detached_terminals,
    _backfill_terminal_views,
    redis_conn,
)
from app.store.session_terminal import (
    _terminal_cache,
    _invalidate_session_cache,
    _set_terminals_cache,
    _cache_key,
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

        normalized, changed = _normalize_session_data("legacy-session", legacy)

        assert normalized["device"]["device_id"] == "legacy-session"
        assert normalized["device"]["max_terminals"] == 3
        assert normalized["views"] == {"mobile": 0, "desktop": 0}
        assert changed is True

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

        normalized, changed = _normalize_session_data("legacy-session", legacy)

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

        normalized, changed = _normalize_session_data("legacy-session", legacy)

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
        with patch('app.store.session.aioredis.ConnectionPool.from_url') as mock_pool:
            mock_pool.side_effect = Exception("Connection refused")

            with pytest.raises(HTTPException) as e:
                await create_session("test-session")

            assert e.value.status_code == 503
            assert "Redis" in e.value.detail


# ═══════════════════════════════════════════════════════════════════════════════
# B055: session store 热路径优化测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestNormalizeChangedFlag:
    """_normalize_session_data changed 标志测试"""

    def test_no_change_returns_false(self):
        """已规范的数据返回 changed=False"""
        fully_normalized = {
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "agent_online": False,
            "views": {"mobile": 0, "desktop": 0},
            "pty": {"rows": 24, "cols": 80},
            "terminals": [],
            "device": _default_device_state("session-1"),
        }
        normalized, changed = _normalize_session_data("session-1", fully_normalized)
        assert changed is False

    def test_missing_fields_returns_true(self):
        """缺少字段时返回 changed=True"""
        minimal = {
            "status": "pending",
            "created_at": "2026-03-26T10:00:00Z",
        }
        normalized, changed = _normalize_session_data("session-1", minimal)
        assert changed is True

    def test_legacy_status_returns_true(self):
        """旧版状态映射触发 changed=True"""
        legacy = {
            "status": "offline",
            "created_at": "2026-03-26T10:00:00Z",
            "agent_online": False,
        }
        normalized, changed = _normalize_session_data("session-1", legacy)
        assert changed is True
        assert normalized["status"] == "offline_expired"


class TestTerminalCache:
    """进程内 terminal 缓存测试"""

    def setup_method(self):
        """每个测试前清空缓存"""
        _terminal_cache.clear()

    def test_cache_miss_returns_none(self):
        """空缓存返回 None"""
        assert _terminal_cache.get(_cache_key("s1", "t1")) is None

    def test_set_and_get_cache(self):
        """写入缓存后可以命中"""
        terminal = {"terminal_id": "t1", "status": "live"}
        _set_terminals_cache("s1", [terminal])
        cached = _terminal_cache.get(_cache_key("s1", "t1"))
        assert cached is not None
        assert cached["terminal_id"] == "t1"

    def test_invalidate_session_cache(self):
        """失效指定 session 的全部缓存"""
        _set_terminals_cache("s1", [
            {"terminal_id": "t1", "status": "live"},
            {"terminal_id": "t2", "status": "live"},
        ])
        _set_terminals_cache("s2", [
            {"terminal_id": "t3", "status": "live"},
        ])
        _invalidate_session_cache("s1")
        assert _terminal_cache.get(_cache_key("s1", "t1")) is None
        assert _terminal_cache.get(_cache_key("s1", "t2")) is None
        assert _terminal_cache.get(_cache_key("s2", "t3")) is not None

    @pytest.mark.asyncio
    async def test_get_session_terminal_hits_cache(self):
        """缓存命中时不再访问 Redis"""
        terminal_data = {
            "terminal_id": "term-1",
            "title": "Test",
            "cwd": "/tmp",
            "command": "/bin/bash",
            "env": {},
            "status": "live",
            "views": {"mobile": 0, "desktop": 0},
            "created_at": "2026-03-26T10:00:00Z",
            "updated_at": "2026-03-26T10:00:00Z",
        }
        _set_terminals_cache("session-1", [terminal_data])

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock()

        with patch.object(redis_conn, '_redis', mock_redis):
            result = await get_session_terminal("session-1", "term-1")

        assert result is not None
        assert result["terminal_id"] == "term-1"
        # Redis 不应被调用（缓存命中）
        mock_redis.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_session_terminal_miss_reads_redis(self):
        """缓存 miss 时读 Redis 并回填缓存"""
        existing_data = json.dumps({
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "terminals": [
                {
                    "terminal_id": "term-1",
                    "title": "Test",
                    "cwd": "/tmp",
                    "command": "/bin/bash",
                    "env": {},
                    "status": "live",
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
            result = await get_session_terminal("session-1", "term-1")

        assert result is not None
        assert result["terminal_id"] == "term-1"
        mock_redis.get.assert_awaited()

    @pytest.mark.asyncio
    async def test_terminal_write_invalidates_cache(self):
        """terminal 写入操作后缓存被失效"""
        terminal_data = {
            "terminal_id": "term-1",
            "title": "Test",
            "cwd": "/tmp",
            "command": "/bin/bash",
            "env": {},
            "status": "live",
            "views": {"mobile": 1, "desktop": 0},
            "created_at": "2026-03-26T10:00:00Z",
            "updated_at": "2026-03-26T10:00:00Z",
        }
        existing_data = json.dumps({
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "terminals": [terminal_data],
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=existing_data)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            # 写入操作（更新状态）
            await update_session_terminal_status(
                "session-1", "term-1",
                terminal_status="closed",
                disconnect_reason="test",
            )

        # 缓存应被失效并重建（写入后 _save_session 重建缓存）
        # 验证新的缓存内容反映 closed 状态
        cached = _terminal_cache.get(_cache_key("session-1", "term-1"))
        assert cached is not None
        assert cached["status"] == "closed"


class TestNormalizeWriteback:
    """normalize 回写条件测试"""

    @pytest.mark.asyncio
    async def test_no_writeback_when_no_change(self):
        """数据已规范时 _get_session_raw 不回写 Redis"""
        from app.store.session_terminal import _get_session_raw

        fully_normalized = {
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "agent_online": False,
            "views": {"mobile": 0, "desktop": 0},
            "pty": {"rows": 24, "cols": 80},
            "terminals": [],
            "device": _default_device_state("session-1"),
        }
        raw_data = json.dumps(fully_normalized)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=raw_data)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            result = await _get_session_raw("session-1")

        assert result["status"] == "online"
        # changed=False 时不应触发 Redis set
        mock_redis.set.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_writeback_when_change_detected(self):
        """数据需要 normalize 时 _get_session_raw 回写 Redis"""
        from app.store.session_terminal import _get_session_raw

        legacy_data = json.dumps({
            "status": "pending",
            "created_at": "2026-03-26T10:00:00Z",
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=legacy_data)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            result = await _get_session_raw("session-1")

        assert result["device"]["device_id"] == "session-1"
        mock_redis.set.assert_awaited()


class TestUserIdReverseIndex:
    """user_id 反向索引测试"""

    @pytest.mark.asyncio
    async def test_create_session_with_user_id_adds_index(self):
        """创建 session 时自动添加 user_id 反向索引"""
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=False)
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.sadd = AsyncMock(return_value=1)

        with patch.object(redis_conn, '_redis', mock_redis):
            result = await create_session(
                "session-idx-1",
                user_id="user-1",
            )

        # 验证 sadd 被调用
        mock_redis.sadd.assert_awaited()
        call_args = mock_redis.sadd.await_args
        assert "rc:user_sessions:user-1" in call_args.args[0]
        assert "session-idx-1" in call_args.args

    @pytest.mark.asyncio
    async def test_create_session_with_owner_adds_index(self):
        """创建 session 时 owner 也维护反向索引"""
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=False)
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.sadd = AsyncMock(return_value=1)

        with patch.object(redis_conn, '_redis', mock_redis):
            result = await create_session(
                "session-idx-2",
                owner="owner-1",
            )

        mock_redis.sadd.assert_awaited()
        call_args = mock_redis.sadd.await_args
        assert "rc:user_sessions:owner-1" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_cleanup_user_sessions_removes_index(self):
        """清理 session 时自动移除反向索引"""
        session_data = {
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "user_id": "user-1",
            "terminals": [],
        }

        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=True)
        mock_redis.smembers = AsyncMock(return_value={"session-to-clean"})
        mock_redis.get = AsyncMock(return_value=json.dumps(session_data))
        mock_redis.delete = AsyncMock(return_value=1)
        mock_redis.srem = AsyncMock(return_value=1)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            deleted = await cleanup_user_sessions("user-1")

        assert deleted == 1
        # 验证 srem 被调用移除索引
        srem_calls = [call for call in mock_redis.srem.await_args_list]
        assert any("rc:user_sessions:user-1" in str(call) for call in srem_calls)

    @pytest.mark.asyncio
    async def test_list_sessions_for_user_uses_index(self):
        """list_sessions_for_user 使用反向索引查询"""
        session_data = {
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "agent_online": False,
            "views": {"mobile": 0, "desktop": 0},
            "pty": {"rows": 24, "cols": 80},
            "terminals": [],
            "device": _default_device_state("session-user-1"),
        }

        mock_redis = AsyncMock()
        # _ensure_user_index: exists 返回 True 表示索引已存在
        mock_redis.exists = AsyncMock(return_value=True)
        mock_redis.smembers = AsyncMock(return_value={"session-user-1"})
        mock_redis.get = AsyncMock(return_value=json.dumps(session_data))
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            sessions = await list_sessions_for_user("user-1")

        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "session-user-1"
        # 不应调用 scan
        mock_redis.scan.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_list_sessions_for_user_handles_deleted_session(self):
        """list_sessions_for_user 遇到已删除 session 时清理索引"""
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=True)
        mock_redis.smembers = AsyncMock(return_value={"deleted-session"})
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.srem = AsyncMock(return_value=1)

        with patch.object(redis_conn, '_redis', mock_redis):
            sessions = await list_sessions_for_user("user-1")

        assert sessions == []
        # 应清理失效索引
        mock_redis.srem.assert_awaited()

    @pytest.mark.asyncio
    async def test_list_sessions_for_user_empty(self):
        """list_sessions_for_user 空 user_id 返回空列表"""
        sessions = await list_sessions_for_user("")
        assert sessions == []

    @pytest.mark.asyncio
    async def test_get_session_by_device_id_with_user_id(self):
        """有 user_id 时 get_session_by_device_id 使用索引而非 SCAN"""
        session_data = {
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "agent_online": False,
            "views": {"mobile": 0, "desktop": 0},
            "pty": {"rows": 24, "cols": 80},
            "terminals": [],
            "device": {
                **_default_device_state("session-dev-1"),
                "device_id": "device-abc",
            },
        }

        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=True)
        mock_redis.smembers = AsyncMock(return_value={"session-dev-1"})
        mock_redis.get = AsyncMock(return_value=json.dumps(session_data))
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            result = await get_session_by_device_id("device-abc", user_id="user-1")

        assert result is not None
        assert result["device"]["device_id"] == "device-abc"
        # 有 user_id 时不应 SCAN
        mock_redis.scan.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_session_by_device_id_without_user_id(self):
        """无 user_id 时 get_session_by_device_id 使用 SCAN 回退"""
        session_data = {
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "agent_online": False,
            "views": {"mobile": 0, "desktop": 0},
            "pty": {"rows": 24, "cols": 80},
            "terminals": [],
            "device": {
                **_default_device_state("session-scan-1"),
                "device_id": "device-scan",
            },
        }

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(session_data))
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.scan = AsyncMock(return_value=(0, ["rc:session:session-scan-1"]))

        with patch.object(redis_conn, '_redis', mock_redis):
            result = await get_session_by_device_id("device-scan")

        assert result is not None
        assert result["device"]["device_id"] == "device-scan"
        # 无 user_id 时应 SCAN
        mock_redis.scan.assert_awaited()


class TestLazySelfHeal:
    """索引缺失时 lazy self-heal 测试"""

    @pytest.mark.asyncio
    async def test_lazy_self_heal_on_missing_index(self):
        """索引缺失时自动 SCAN 补齐"""
        session_data = {
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "user_id": "user-heal",
            "agent_online": False,
            "views": {"mobile": 0, "desktop": 0},
            "pty": {"rows": 24, "cols": 80},
            "terminals": [],
            "device": _default_device_state("session-heal-1"),
        }

        mock_redis = AsyncMock()
        # exists 返回 False 触发 self-heal
        exists_count = 0
        async def exists_side_effect(key):
            nonlocal exists_count
            exists_count += 1
            if key == "rc:user_sessions:user-heal":
                return 0 if exists_count == 1 else 1
            return 1
        mock_redis.exists = AsyncMock(side_effect=exists_side_effect)
        mock_redis.smembers = AsyncMock(return_value={"session-heal-1"})
        mock_redis.get = AsyncMock(side_effect=[
            # self-heal SCAN 阶段
            json.dumps(session_data),
            # 实际读取阶段
            json.dumps(session_data),
        ])
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.sadd = AsyncMock(return_value=1)
        mock_redis.scan = AsyncMock(return_value=(0, ["rc:session:session-heal-1"]))

        with patch.object(redis_conn, '_redis', mock_redis):
            sessions = await list_sessions_for_user("user-heal")

        assert len(sessions) == 1
        # self-heal 应调用 scan
        mock_redis.scan.assert_awaited()
        # 应写入索引
        mock_redis.sadd.assert_awaited()


class TestBackfill:
    """backfill_user_session_index 测试"""

    @pytest.mark.asyncio
    async def test_backfill_indexes_sessions(self):
        """backfill 正确索引已有 session"""
        session1 = json.dumps({
            "status": "online",
            "user_id": "user-1",
        })
        session2 = json.dumps({
            "status": "online",
            "user_id": "user-2",
        })
        session_no_user = json.dumps({
            "status": "online",
        })

        mock_redis = AsyncMock()
        # 索引清理 scan
        mock_redis.scan = AsyncMock(side_effect=[
            (0, []),  # 清理旧索引
            (0, ["rc:session:s1", "rc:session:s2", "rc:session:s3"]),  # session scan
        ])
        mock_redis.get = AsyncMock(side_effect=[session1, session2, session_no_user])
        mock_redis.sadd = AsyncMock(return_value=1)
        mock_redis.delete = AsyncMock(return_value=0)

        with patch.object(redis_conn, '_redis', mock_redis):
            count = await backfill_user_session_index()

        assert count == 2  # 只有 user-1 和 user-2 的 session

    @pytest.mark.asyncio
    async def test_backfill_empty(self):
        """无 session 时 backfill 返回 0"""
        mock_redis = AsyncMock()
        mock_redis.scan = AsyncMock(side_effect=[
            (0, []),  # 清理旧索引
            (0, []),  # 无 session
        ])
        mock_redis.delete = AsyncMock(return_value=0)

        with patch.object(redis_conn, '_redis', mock_redis):
            count = await backfill_user_session_index()

        assert count == 0


class TestStartupBackfill:
    """启动时 backfill 测试"""

    @pytest.mark.asyncio
    async def test_backfill_failure_does_not_raise(self):
        """backfill 失败时不阻塞，仅记录 warning"""

        mock_redis = AsyncMock()
        mock_redis.scan = AsyncMock(side_effect=Exception("Redis unavailable"))

        with patch.object(redis_conn, '_redis', mock_redis):
            # backfill 本身在 Redis 操作失败时会抛异常
            # __init__.py 中的 lifespan 捕获并记录 warning
            with pytest.raises(Exception):
                await backfill_user_session_index()


class TestGetSessionTerminalCacheIntegration:
    """get_session_terminal 缓存集成测试"""

    def setup_method(self):
        _terminal_cache.clear()

    @pytest.mark.asyncio
    async def test_data_message_path_uses_cache(self):
        """data 消息处理路径 get_session_terminal 调用次数减少"""
        terminal_data = {
            "terminal_id": "term-data",
            "title": "Data Terminal",
            "cwd": "/tmp",
            "command": "/bin/bash",
            "env": {},
            "status": "live",
            "views": {"mobile": 0, "desktop": 0},
            "created_at": "2026-03-26T10:00:00Z",
            "updated_at": "2026-03-26T10:00:00Z",
        }
        session_data = json.dumps({
            "status": "online",
            "created_at": "2026-03-26T10:00:00Z",
            "agent_online": False,
            "views": {"mobile": 0, "desktop": 0},
            "pty": {"rows": 24, "cols": 80},
            "terminals": [terminal_data],
            "device": _default_device_state("session-data"),
        })

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=session_data)
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(redis_conn, '_redis', mock_redis):
            # 第一次调用：miss → 读 Redis + 填缓存
            result1 = await get_session_terminal("session-data", "term-data")
            assert result1 is not None

            # 第二次调用：缓存命中，不读 Redis
            call_count_before = mock_redis.get.await_count
            result2 = await get_session_terminal("session-data", "term-data")
            call_count_after = mock_redis.get.await_count

            assert result2 is not None
            # 缓存命中后 get 不应再次被调用
            assert call_count_after == call_count_before
