"""
Redis 会话 read-modify-write 原子性测试

验证 per-session asyncio.Lock 确保同一 session 的并发 read-modify-write 操作串行化，
不会丢失数据。
"""
import pytest
import json
import asyncio
from unittest.mock import AsyncMock, patch

from app.store.session import (
    create_session,
    update_session_status,
    update_session_agent_online,
    update_session_view_count,
    update_session_device_heartbeat,
    get_session,
    set_session_online,
    set_session_offline,
    redis_conn,
)


def _make_session_data(session_id: str) -> dict:
    """构造一份标准的 session JSON 数据（模拟 Redis 已有记录）"""
    from app.store.session import _default_device_state
    from datetime import datetime, timezone

    return {
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "name": "",
        "user_id": "test-user",
        "owner": "test-user",
        "agent_online": False,
        "views": {"mobile": 0, "desktop": 0},
        "pty": {"rows": 24, "cols": 80},
        "device": _default_device_state(session_id),
        "terminals": [],
    }


class TestSessionAtomicity:
    """验证 per-session asyncio.Lock 的原子性保证"""

    @pytest.mark.asyncio
    async def test_concurrent_updates_are_serialized(self):
        """
        用 asyncio.gather 并发调用 update_session_status 和 update_session_agent_online，
        验证加锁后最终 Redis 数据同时包含 status="online" 和 agent_online=True。

        加锁后两个 read-modify-write 操作会串行执行，后者的读取能看到前者的写入。
        """
        session_id = "race-test-concurrent"
        initial_data = _make_session_data(session_id)

        # 模拟真实 Redis：用 dict 存储最新数据
        redis_store: dict[str, str] = {}

        async def mock_get(key):
            return redis_store.get(key)

        async def mock_set(key, value, ex=None, **kwargs):
            redis_store[key] = value

        mock_redis = AsyncMock()
        mock_redis.get = mock_get
        mock_redis.set = mock_set

        redis_store[f"rc:session:{session_id}"] = json.dumps(initial_data)

        with patch.object(redis_conn, '_redis', mock_redis):
            await asyncio.gather(
                update_session_status(session_id, "online"),
                update_session_agent_online(session_id, True),
            )
            session = await get_session(session_id)

        assert session["status"] == "online", f"status 应为 online，实际为 {session['status']}"
        assert session["agent_online"] is True, f"agent_online 应为 True，实际为 {session['agent_online']}"

    @pytest.mark.asyncio
    async def test_concurrent_view_count_updates_are_serialized(self):
        """
        同一 session 的多个 client 并发 +1 view_count，
        验证加锁后最终计数准确（每次递增都生效）。
        """
        session_id = "race-test-viewcount"
        initial_data = _make_session_data(session_id)
        initial_data["views"] = {"mobile": 0, "desktop": 0}

        redis_store: dict[str, str] = {}

        async def mock_get(key):
            return redis_store.get(key)

        async def mock_set(key, value, ex=None, **kwargs):
            redis_store[key] = value

        mock_redis = AsyncMock()
        mock_redis.get = mock_get
        mock_redis.set = mock_set

        redis_store[f"rc:session:{session_id}"] = json.dumps(initial_data)

        with patch.object(redis_conn, '_redis', mock_redis):
            await asyncio.gather(
                update_session_view_count(session_id, "mobile", 1),
                update_session_view_count(session_id, "mobile", 1),
            )
            session = await get_session(session_id)

        assert session["views"]["mobile"] == 2, (
            f"mobile view_count 应为 2（两次 +1），实际为 {session['views']['mobile']}"
        )

    @pytest.mark.asyncio
    async def test_concurrent_heartbeat_and_status_are_serialized(self):
        """
        agent 心跳（update_session_device_heartbeat）和
        status 更新（update_session_status）并发执行，
        验证加锁后两个更新都生效，不互相覆盖。
        """
        session_id = "race-test-heartbeat-status"
        initial_data = _make_session_data(session_id)
        initial_data["status"] = "online"
        initial_data["agent_online"] = True

        redis_store: dict[str, str] = {}

        async def mock_get(key):
            return redis_store.get(key)

        async def mock_set(key, value, ex=None, **kwargs):
            redis_store[key] = value

        mock_redis = AsyncMock()
        mock_redis.get = mock_get
        mock_redis.set = mock_set

        redis_store[f"rc:session:{session_id}"] = json.dumps(initial_data)

        with patch.object(redis_conn, '_redis', mock_redis):
            await asyncio.gather(
                update_session_device_heartbeat(session_id, online=True),
                update_session_status(session_id, "offline"),
            )
            session = await get_session(session_id)

        # 心跳更新了 agent_online + last_heartbeat_at，status 更新了 status="offline_expired"
        # 加锁后两者串行执行，最终数据一致
        assert session["status"] == "offline_expired"
        assert session["device"]["last_heartbeat_at"] is not None

    @pytest.mark.asyncio
    async def test_sequential_offline_preserve_both(self):
        """
        顺序调用 update_session_status("offline") 和 update_session_agent_online(False)，
        验证数据一致性。
        """
        session_id = "race-test-offline"
        initial_data = _make_session_data(session_id)
        # 模拟 agent 已在线的状态
        initial_data["status"] = "online"
        initial_data["agent_online"] = True

        redis_store: dict[str, str] = {}

        async def mock_get(key):
            return redis_store.get(key)

        async def mock_set(key, value, ex=None, **kwargs):
            redis_store[key] = value

        mock_redis = AsyncMock()
        mock_redis.get = mock_get
        mock_redis.set = mock_set

        redis_store[f"rc:session:{session_id}"] = json.dumps(initial_data)

        with patch.object(redis_conn, '_redis', mock_redis):
            await update_session_status(session_id, "offline")
            await update_session_agent_online(session_id, False)

            session = await get_session(session_id)

        assert session["status"] == "offline_expired"
        assert session["agent_online"] is False

    @pytest.mark.asyncio
    async def test_sequential_preserves_other_fields(self):
        """
        顺序执行不应丢失其他字段（如 views, device, terminals）。
        """
        session_id = "race-test-fields"
        initial_data = _make_session_data(session_id)
        initial_data["views"] = {"mobile": 2, "desktop": 1}
        initial_data["terminals"] = [
            {"terminal_id": "t1", "status": "attached", "title": "Test"}
        ]

        redis_store: dict[str, str] = {}

        async def mock_get(key):
            return redis_store.get(key)

        async def mock_set(key, value, ex=None, **kwargs):
            redis_store[key] = value

        mock_redis = AsyncMock()
        mock_redis.get = mock_get
        mock_redis.set = mock_set

        redis_store[f"rc:session:{session_id}"] = json.dumps(initial_data)

        with patch.object(redis_conn, '_redis', mock_redis):
            await update_session_status(session_id, "online")
            await update_session_agent_online(session_id, True)

            session = await get_session(session_id)

        assert session["status"] == "online"
        assert session["agent_online"] is True
        assert session["views"] == {"mobile": 2, "desktop": 1}
        assert len(session["terminals"]) == 1
        assert session["terminals"][0]["terminal_id"] == "t1"

    @pytest.mark.asyncio
    async def test_rapid_online_offline_cycle_consistency(self):
        """
        快速 online → offline 循环后，顺序执行应保持最终状态一致。
        模拟 agent 频繁断连重连的场景。
        """
        session_id = "race-test-cycle"

        redis_store: dict[str, str] = {}

        async def mock_get(key):
            return redis_store.get(key)

        async def mock_set(key, value, ex=None, **kwargs):
            redis_store[key] = value

        mock_redis = AsyncMock()
        mock_redis.get = mock_get
        mock_redis.set = mock_set

        initial_data = _make_session_data(session_id)
        redis_store[f"rc:session:{session_id}"] = json.dumps(initial_data)

        with patch.object(redis_conn, '_redis', mock_redis):
            # 模拟 3 轮 online → offline 循环
            for cycle in range(3):
                await update_session_status(session_id, "online")
                await update_session_agent_online(session_id, True)

                session = await get_session(session_id)
                assert session["status"] == "online"
                assert session["agent_online"] is True

                await update_session_status(session_id, "offline")
                await update_session_agent_online(session_id, False)

                session = await get_session(session_id)
                assert session["status"] == "offline_expired"
                assert session["agent_online"] is False

        # 最终状态：offline_expired
        final_data = json.loads(redis_store[f"rc:session:{session_id}"])
        assert final_data["status"] == "offline_expired"
        assert final_data["agent_online"] is False

    @pytest.mark.asyncio
    async def test_different_sessions_not_blocked(self):
        """
        不同 session 的并发更新不应互相阻塞。
        验证 per-session 锁只锁定同一 session，不同 session 可以并行执行。
        """
        session_id_a = "race-test-session-a"
        session_id_b = "race-test-session-b"

        redis_store: dict[str, str] = {}

        async def mock_get(key):
            return redis_store.get(key)

        async def mock_set(key, value, ex=None, **kwargs):
            redis_store[key] = value

        mock_redis = AsyncMock()
        mock_redis.get = mock_get
        mock_redis.set = mock_set

        redis_store[f"rc:session:{session_id_a}"] = json.dumps(_make_session_data(session_id_a))
        redis_store[f"rc:session:{session_id_b}"] = json.dumps(_make_session_data(session_id_b))

        with patch.object(redis_conn, '_redis', mock_redis):
            await asyncio.gather(
                update_session_status(session_id_a, "online"),
                update_session_status(session_id_b, "offline"),
                update_session_agent_online(session_id_a, True),
                update_session_agent_online(session_id_b, False),
            )
            session_a = await get_session(session_id_a)
            session_b = await get_session(session_id_b)

        assert session_a["status"] == "online"
        assert session_a["agent_online"] is True
        assert session_b["status"] == "offline_expired"
        assert session_b["agent_online"] is False

    @pytest.mark.asyncio
    async def test_set_session_online_atomic(self):
        """set_session_online 原子设置 status=online + agent_online=True"""
        session_id = "race-test-set-online"
        initial_data = _make_session_data(session_id)

        redis_store: dict[str, str] = {}

        async def mock_get(key):
            return redis_store.get(key)

        async def mock_set(key, value, ex=None, **kwargs):
            redis_store[key] = value

        mock_redis = AsyncMock()
        mock_redis.get = mock_get
        mock_redis.set = mock_set

        redis_store[f"rc:session:{session_id}"] = json.dumps(initial_data)

        with patch.object(redis_conn, '_redis', mock_redis):
            result = await set_session_online(session_id)

        assert result["status"] == "online"
        assert result["agent_online"] is True

    @pytest.mark.asyncio
    async def test_set_session_offline_atomic(self):
        """set_session_offline 原子设置 status=offline + agent_online=False + close terminals"""
        session_id = "race-test-set-offline"
        initial_data = _make_session_data(session_id)
        initial_data["status"] = "online"
        initial_data["agent_online"] = True
        initial_data["terminals"] = [
            {
                "terminal_id": "t1",
                "status": "attached",
                "views": {"mobile": 1, "desktop": 0},
                "grace_expires_at": None,
            },
            {
                "terminal_id": "t2",
                "status": "detached",
                "views": {"mobile": 0, "desktop": 0},
                "grace_expires_at": "2099-01-01T00:00:00+00:00",
            },
        ]

        redis_store: dict[str, str] = {}

        async def mock_get(key):
            return redis_store.get(key)

        async def mock_set(key, value, ex=None, **kwargs):
            redis_store[key] = value

        mock_redis = AsyncMock()
        mock_redis.get = mock_get
        mock_redis.set = mock_set

        redis_store[f"rc:session:{session_id}"] = json.dumps(initial_data)

        with patch.object(redis_conn, '_redis', mock_redis):
            result = await set_session_offline(session_id, reason="device_offline")

        assert result["status"] == "offline_expired"
        assert result["agent_online"] is False
        # 所有非 closed terminal 都应被关闭
        for terminal in result["terminals"]:
            assert terminal["status"] == "closed"
            assert terminal["disconnect_reason"] == "device_offline"
            assert terminal["views"] == {"mobile": 0, "desktop": 0}
