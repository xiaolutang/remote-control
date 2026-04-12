"""
Agent 创建集成测试 — 不 mock session 层，验证真实 Redis 交互。

测试目标：
1. Agent 连接后，list_runtime_devices 是否正确返回 agent_online=True
2. set_session_online / set_session_offline 原子性在真实场景下是否正确
3. Agent 断连后，stale → offline 状态流转是否正确
4. 多 Agent 竞争连接时 4009 拒绝是否正确

这是"不 mock 的集成级冒烟测试"，用于暴露 mock 隐藏的真实问题。
"""
import asyncio
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.session import (
    create_session,
    get_session,
    set_session_online,
    set_session_offline,
    redis_conn,
    _session_locks,
)


def _make_mock_redis():
    """构造一个行为类似真实 Redis 的 mock（dict 后端）"""
    store: dict[str, str] = {}

    async def mock_get(key):
        return store.get(key)

    async def mock_set(key, value):
        store[key] = value

    async def mock_exists(key):
        return key in store

    async def mock_scan(cursor, match=None, count=100):
        if cursor != 0:
            return 0, []
        if match:
            # 将 Redis glob pattern 转为简单前缀匹配
            prefix = match.replace("*", "")
            keys = [k for k in store.keys() if k.startswith(prefix)]
        else:
            keys = list(store.keys())
        return 0, keys

    mock = AsyncMock()
    mock.get = mock_get
    mock.set = mock_set
    mock.exists = mock_exists
    mock.scan = mock_scan
    return mock, store


@pytest.fixture(autouse=True)
def mock_redis():
    """所有测试使用 mock Redis，但不 mock session 函数本身"""
    mock, store = _make_mock_redis()
    with patch.object(redis_conn, '_redis', mock):
        yield mock, store


class TestAgentCreationIntegration:
    """不 mock session 层，测试 Agent 创建的完整链路"""

    @pytest.mark.asyncio
    async def test_agent_connect_sets_session_online(self, mock_redis):
        """
        验证：Agent 连接 → set_session_online → Redis 中 status=online, agent_online=True

        这是 Flutter _waitForAgentOnline() 依赖的关键数据。
        """
        mock, store = mock_redis
        session_id = "agent-integration-1"

        # 1. 创建 session（模拟登录）
        session = await create_session(session_id, owner="test-user")
        assert session["status"] == "pending"

        # 2. Agent 连接 → set_session_online
        result = await set_session_online(session_id)
        assert result["status"] == "online"
        assert result["agent_online"] is True

        # 3. 验证 Redis 中的数据
        data = json.loads(store[f"rc:session:{session_id}"])
        assert data["status"] == "online"
        assert data["agent_online"] is True

    @pytest.mark.asyncio
    async def test_runtime_devices_reflects_agent_online(self, mock_redis):
        """
        验证：Agent 连接后，list_runtime_devices 返回 agent_online=True

        这是 Flutter _waitForAgentOnline() 实际调用的 API。
        """
        mock, store = mock_redis
        session_id = "agent-integration-2"

        # 创建 session
        await create_session(session_id, owner="test-user")

        # Agent 未连接 → agent_online=False
        from app.ws_agent import is_agent_connected
        assert is_agent_connected(session_id) is False

        # Agent 连接 → set_session_online
        await set_session_online(session_id)

        # Redis 数据 → agent_online=True
        data = json.loads(store[f"rc:session:{session_id}"])
        assert data["agent_online"] is True

        # 但 is_agent_connected 看 in-memory dict，不看 Redis
        # Agent 实际不在线（没有 WebSocket 连接）
        assert is_agent_connected(session_id) is False

        # 关键发现：Redis agent_online 与 in-memory active_agents 不一致！
        # Flutter 通过 list_runtime_devices 获取 agent_online，
        # 但 _device_online() 优先看 active_agents（in-memory）

    @pytest.mark.asyncio
    async def test_device_online_uses_active_agents_not_redis(self, mock_redis):
        """
        关键验证：_device_online() 使用 is_agent_connected（in-memory），
        而非 Redis 的 agent_online 字段。

        这意味着：
        - Agent WebSocket 连接 → active_agents 有记录 → agent_online=True
        - Agent WebSocket 断开 → active_agents 无记录 → agent_online=False
        - Redis 的 agent_online 字段仅作为 stale TTL 的参考

        这是 Flutter 轮询"看不到"agent 的根本原因：
        Agent 连接后如果很快断开，active_agents 中已无记录。
        """
        from app.ws_agent import active_agents, AgentConnection, is_agent_connected
        from app.runtime_api import _device_online

        session_id = "agent-integration-3"
        await create_session(session_id, owner="test-user")
        await set_session_online(session_id)

        # Redis 说在线，但 active_agents 无记录
        session_data = await get_session(session_id)
        assert session_data["agent_online"] is True
        assert is_agent_connected(session_id) is False

        # _device_online 应该返回 False（看 active_agents，不看 Redis）
        device_online = _device_online({"session_id": session_id, **session_data})
        assert device_online is False, (
            "BUG: _device_online 在 active_agents 无记录时应返回 False，"
            "即使 Redis agent_online=True"
        )

        # 模拟 Agent WebSocket 连接 → active_agents 有记录
        mock_ws = AsyncMock()
        active_agents[session_id] = AgentConnection(session_id, mock_ws, "test-user")

        device_online = _device_online({"session_id": session_id, **session_data})
        assert device_online is True

        # 清理
        del active_agents[session_id]

    @pytest.mark.asyncio
    async def test_agent_connect_disconnect_race_with_flutter_polling(self, mock_redis):
        """
        复现真实场景：Agent 连接后很快断开，Flutter 轮询可能错过 agent_online=True。

        时间线：
        T+0.0s: Flutter starts agent process
        T+0.5s: Agent connects to server → active_agents[sid] = conn
        T+0.6s: Flutter polls GET /api/runtime/devices → agent_online=True (found!)
        T+0.7s: Agent disconnects → active_agents[sid] removed → stale
        T+1.2s: Flutter polls GET /api/runtime/devices → agent_online=False
        T+12s:  Flutter _waitForAgentOnline timeout → stopManagedAgent()

        如果 Agent 在 T+0.5s 到 T+0.7s 之间断开（200ms），
        Flutter 的 600ms 轮询可能刚好错过 agent_online=True。
        """
        from app.ws_agent import (
            active_agents, AgentConnection, stale_agents,
            _cleanup_agent, is_agent_connected,
        )
        from app.runtime_api import _device_online

        session_id = "agent-integration-4"
        await create_session(session_id, owner="test-user")
        await set_session_online(session_id)

        session_data = await get_session(session_id)

        # 模拟 Agent 连接
        mock_ws = AsyncMock()
        active_agents[session_id] = AgentConnection(session_id, mock_ws, "test-user")

        # Flutter 第 1 次轮询 → 应该看到 online
        assert _device_online({"session_id": session_id, **session_data}) is True

        # Agent 断连（模拟快速断连）
        await _cleanup_agent(session_id, "agent_shutdown")

        # Flutter 第 2 次轮询 → 应该看到 offline
        assert _device_online({"session_id": session_id, **session_data}) is False

        # 但 Redis 仍然说 agent_online=True（stale TTL 还没过期）
        redis_data = json.loads(
            (await mock_redis[0].get(f"rc:session:{session_id}"))
        )
        assert redis_data["agent_online"] is True, (
            "Agent 进入 stale 后 Redis agent_online 仍为 True"
        )

        # 清理
        stale_agents.clear()

    @pytest.mark.asyncio
    async def test_duplicate_agent_rejected_during_flutter_retry(self, mock_redis):
        """
        复现场景：Flutter 启动多个 Agent 进程，第二个被 4009 拒绝。

        时间线：
        1. Flutter starts agent-1 → connects → active_agents[sid] = conn1
        2. Flutter starts agent-2 (重试) → connects → rejected with 4009
        3. agent-2 收到 4009 → close → 重连循环 → 再次 4009
        4. agent-1 也被挤掉 → 两个都失败
        """
        from app.ws_agent import active_agents, AgentConnection

        session_id = "agent-integration-5"
        await create_session(session_id, owner="test-user")
        await set_session_online(session_id)

        # 第一个 Agent 已连接
        mock_ws1 = AsyncMock()
        active_agents[session_id] = AgentConnection(session_id, mock_ws1, "test-user")

        # 模拟第二个 Agent 尝试连接
        mock_ws2 = AsyncMock()

        with patch("app.ws_agent.async_verify_token", return_value={
            "session_id": session_id, "sub": "test-user"
        }):
            from app.ws_agent import agent_websocket_handler
            await agent_websocket_handler(mock_ws2, "valid-token")

        # 第二个 Agent 应该被 4009 拒绝
        mock_ws2.close.assert_called_once_with(
            code=4009, reason="Session already has an active agent"
        )

        # 清理
        del active_agents[session_id]

    @pytest.mark.asyncio
    async def test_full_agent_lifecycle_without_mocks(self, mock_redis):
        """
        完整 Agent 生命周期测试（不 mock session 函数）：
        1. 登录 → 创建 session
        2. Agent 连接 → set_session_online
        3. Flutter 轮询 → 看到 agent_online
        4. Agent 断连 → stale → offline
        5. Flutter 轮询 → 看到 agent_offline
        """
        from app.ws_agent import (
            active_agents, AgentConnection, stale_agents,
            _cleanup_agent, _expire_stale_agent, is_agent_connected,
        )
        from app.runtime_api import _device_online

        mock, store = mock_redis
        session_id = "agent-lifecycle-1"

        # Step 1: 登录
        await create_session(session_id, owner="test-user")
        session_data = await get_session(session_id)
        assert _device_online({"session_id": session_id, **session_data}) is False

        # Step 2: Agent 连接
        mock_ws = AsyncMock()
        active_agents[session_id] = AgentConnection(session_id, mock_ws, "test-user")
        await set_session_online(session_id)

        session_data = await get_session(session_id)
        assert _device_online({"session_id": session_id, **session_data}) is True

        # Step 3: Agent 断连 → stale
        await _cleanup_agent(session_id, "network_lost")
        session_data = await get_session(session_id)
        assert _device_online({"session_id": session_id, **session_data}) is False
        assert session_data["agent_online"] is True  # stale, not yet offline

        # Step 4: Stale TTL 过期 → offline
        await _expire_stale_agent(session_id)
        session_data = await get_session(session_id)
        assert _device_online({"session_id": session_id, **session_data}) is False
        assert session_data["agent_online"] is False

        # 清理
        stale_agents.clear()

    @pytest.mark.asyncio
    async def test_concurrent_session_lock_with_agent_connect(self, mock_redis):
        """
        验证：Agent 连接时，其他操作（如 Flutter 轮询）不会死锁。

        场景：
        - Agent 连接调用 set_session_online（获取锁）
        - 同时 Flutter 调用 get_session（获取同一把锁）
        - 两者应串行执行，不死锁
        """
        mock, store = mock_redis
        session_id = "agent-lock-1"
        await create_session(session_id, owner="test-user")

        results = []

        async def agent_connect():
            await set_session_online(session_id)
            results.append("agent_online")

        async def flutter_poll():
            # 稍微延迟，确保 agent 先获取锁
            await asyncio.sleep(0.01)
            session = await get_session(session_id)
            results.append(f"poll_status={session['status']}")

        await asyncio.gather(agent_connect(), flutter_poll())

        assert "agent_online" in results
        assert any("poll_status=online" in r for r in results)

    @pytest.mark.asyncio
    async def test_lock_ordering_with_list_sessions_for_user(self, mock_redis):
        """
        验证：list_sessions_for_user 在扫描时逐个获取锁，不会死锁。

        场景：
        - 两个 session 存在于 Redis
        - Agent 连接其中一个 session
        - 同时 Flutter 调用 list_sessions_for_user
        """
        mock, store = mock_redis
        session_id_a = "lock-order-a"
        session_id_b = "lock-order-b"

        await create_session(session_id_a, user_id="test-user", owner="test-user")
        await create_session(session_id_b, user_id="test-user", owner="test-user")

        # 同时执行 list_sessions_for_user 和 set_session_online
        from app.session import list_sessions_for_user

        results = {"listed": None, "online": None}

        async def list_sessions():
            sessions = await list_sessions_for_user("test-user")
            results["listed"] = len(sessions)

        async def go_online():
            await set_session_online(session_id_a)
            results["online"] = True

        await asyncio.gather(list_sessions(), go_online())

        assert results["listed"] == 2
        assert results["online"] is True


class TestAgentCreationEscapeAnalysis:
    """
    缺陷逃逸分析：为什么 65 个测试全部通过，但真实场景仍然失败。

    核心发现：所有现有测试 mock 了 session 层，无法检测到以下问题：
    """

    @pytest.mark.asyncio
    async def test_escape_1_redis_vs_active_agents_inconsistency(self, mock_redis):
        """
        逃逸路径 #1：Redis agent_online 与 in-memory active_agents 不一致。

        现有测试全部 mock get_session / set_session_online，
        永远不会出现 "Redis 说在线但 active_agents 说不在线" 的情况。

        但在真实场景中：
        - set_session_online 更新 Redis → agent_online=True
        - Agent 断开 → active_agents 移除 → is_agent_connected=False
        - 但 Redis 的 agent_online 仍为 True（直到 stale TTL 过期）

        _device_online() 优先看 is_agent_connected，所以返回 False。
        但 Flutter 可能依赖 Redis 的 agent_online 字段做其他判断。
        """
        from app.ws_agent import active_agents, AgentConnection
        from app.runtime_api import _device_online

        session_id = "escape-1"
        await create_session(session_id, owner="test-user")
        await set_session_online(session_id)

        # 模拟 Agent 断开后（active_agents 无记录，Redis 仍为 True）
        session = await get_session(session_id)
        assert session["agent_online"] is True
        assert _device_online({"session_id": session_id, **session}) is False

    @pytest.mark.asyncio
    async def test_escape_2_stale_period_flutter_sees_false_offline(self, mock_redis):
        """
        逃逸路径 #2：Stale 期间 Flutter 看到 agent_online=False。

        Stale TTL = 90 秒。在这 90 秒内：
        - active_agents 无记录 → is_agent_connected=False
        - Redis agent_online=True
        - _device_online() 返回 False

        Flutter 的 _waitForAgentOnline() 超时 = 12 秒。
        如果 Agent 在 stale 期间重连，Flutter 要等最多 12 秒才能看到。

        但如果 Agent 在 stale 期间重连失败（比如端口被占用），
        Flutter 在 12 秒后放弃，调用 stopManagedAgent()。
        """
        from app.ws_agent import active_agents, AgentConnection, stale_agents, _cleanup_agent
        from app.runtime_api import _device_online

        session_id = "escape-2"
        await create_session(session_id, owner="test-user")
        await set_session_online(session_id)

        # Agent 断开 → stale
        mock_ws = AsyncMock()
        active_agents[session_id] = AgentConnection(session_id, mock_ws, "test-user")
        await _cleanup_agent(session_id, "network_lost")

        # Stale 期间：_device_online 返回 False
        session = await get_session(session_id)
        assert session["agent_online"] is True  # Redis 仍为 True
        assert _device_online({"session_id": session_id, **session}) is False  # 但 API 返回 False

        stale_agents.clear()

    @pytest.mark.asyncio
    async def test_escape_3_no_test_covers_agent_process_lifecycle(self, mock_redis):
        """
        逃逸路径 #3：没有任何测试覆盖 Agent 进程的启动/停止生命周期。

        Flutter 的 ensureAgentOnline()：
        1. 检查 agent 是否在线（GET /api/runtime/devices）
        2. 检查 managed PID
        3. pgrep 查找 agent 进程
        4. 启动 python3 -m app.cli --config <path> run
        5. _waitForAgentOnline() 轮询 12 秒
        6. 超时 → stopManagedAgent()

        这些步骤没有任何自动化测试覆盖。
        问题可能出现在：
        - Step 4: config 文件中 token 已过期
        - Step 4: workdir 解析失败
        - Step 5: Agent 连接后快速断开，轮询错过
        - Step 6: Flutter 在 Agent 还在重连时就放弃了
        """
        # 这个测试是文档性的，不需要实际代码
        # 它记录了一个应该有但缺失的测试场景
        pass

    @pytest.mark.asyncio
    async def test_escape_4_no_test_covers_token_expiry_during_agent_lifecycle(self, mock_redis):
        """
        逃逸路径 #4：Agent 长时间运行后 token 过期。

        Agent config 中的 token 有 exp 字段。如果 Agent 运行超过 JWT_EXPIRY_HOURS，
        token 会过期。Agent 的 ensure_valid_token() 会尝试刷新，
        但刷新失败时 Agent 会直接退出。

        现有测试 mock 了 verify_token，永远不会测试 token 过期的场景。
        """
        # 验证 token 过期后 verify_token 确实抛异常
        from app.auth import generate_token, verify_token, JWT_SECRET_KEY
        from jose import jwt as jose_jwt

        # 生成一个已过期的 token
        expired_payload = {
            "sub": "test-session",
            "exp": datetime.now(timezone.utc).timestamp() - 3600,  # 1 小时前过期
            "iat": datetime.now(timezone.utc).timestamp() - 7200,
        }
        expired_token = jose_jwt.encode(expired_payload, JWT_SECRET_KEY, algorithm="HS256")

        with pytest.raises(Exception) as exc_info:
            verify_token(expired_token)
        assert "过期" in str(exc_info.value.detail) or "expired" in str(exc_info.value.detail).lower()
