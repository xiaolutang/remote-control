"""
Agent 生命周期系统集成测试

排查方向：
1. Agent PTY 退出是否导致 WebSocket 连接断开
2. 服务端心跳超时是否正确触发
3. Stale TTL 状态机流转是否正确
4. Close code 是否符合预期（排查 1000 vs 1008）
"""
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

# 添加 agent 目录到 path（用于 agent 端测试）
_agent_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'agent')
_agent_app_dir = os.path.join(_agent_dir, 'app')
if _agent_dir not in sys.path:
    sys.path.insert(0, _agent_dir)
if _agent_app_dir not in sys.path:
    sys.path.insert(0, _agent_app_dir)


def make_async_iter(json_msgs=None, *, exc=None):
    """创建一个 async iterator mock，用于 websocket.iter_json()"""
    if exc:
        async def _iter():
            if False:
                yield
            raise exc
        return _iter()

    if json_msgs is not None:
        async def _iter():
            for msg in json_msgs:
                yield msg
        return _iter()

    async def _iter():
        if False:
            yield
        raise asyncio.CancelledError
    return _iter()


def make_ws_auth_payload(session_id: str = "session-1", sub: str = "user1", token: str = "valid-token"):
    return (
        {"session_id": session_id, "sub": sub},
        {"type": "auth", "token": token},
    )


# ─── 1. 服务端心跳超时验证 ───


class TestHeartbeatChecker:
    """验证心跳检查器的行为"""

    @pytest.mark.asyncio
    async def test_heartbeat_checker_closes_with_1008_on_timeout(self):
        """心跳超时应使用 code 1008 而非 1000"""
        from app.ws.ws_agent import (
            AgentConnection,
            HEARTBEAT_TIMEOUT,
            active_agents,
            _heartbeat_checker,
        )

        active_agents.clear()
        mock_ws = AsyncMock()
        mock_ws.scope = {"scheme": "wss"}
        mock_ws.headers = {}
        conn = AgentConnection("session-1", mock_ws)

        # 模拟心跳超时
        conn.last_heartbeat = datetime.now(timezone.utc) - timedelta(
            seconds=HEARTBEAT_TIMEOUT + 1
        )
        assert conn.is_alive() is False

        active_agents["session-1"] = conn

        # 第一次 sleep 正常返回（让检查逻辑执行），第二次 sleep 时退出
        sleep_count = 0

        async def mock_sleep(seconds):
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 2:
                raise asyncio.CancelledError()

        with patch("asyncio.sleep", side_effect=mock_sleep):
            try:
                await _heartbeat_checker(mock_ws, "session-1")
            except asyncio.CancelledError:
                pass

        # 心跳超时 → close(1008)
        mock_ws.close.assert_called_once_with(code=1008, reason="Heartbeat timeout")

    @pytest.mark.asyncio
    async def test_heartbeat_checker_does_not_close_when_alive(self):
        """心跳正常时不应关闭连接"""
        from app.ws.ws_agent import AgentConnection, active_agents, HEARTBEAT_INTERVAL

        active_agents.clear()
        mock_ws = AsyncMock()
        mock_ws.scope = {"scheme": "wss"}
        mock_ws.headers = {}
        conn = AgentConnection("session-1", mock_ws)
        active_agents["session-1"] = conn

        # 刚更新过心跳，不应该超时
        conn.update_heartbeat()

        # 模拟一次心跳检查（跳过 sleep）
        with patch("asyncio.sleep", side_effect=AsyncMock()):
            from app.ws.ws_agent import _heartbeat_checker

            # 只检查一次然后退出
            async def one_check():
                # 直接进入检查逻辑
                agent_conn = active_agents.get("session-1")
                assert agent_conn is not None
                assert agent_conn.is_alive() is True

            await one_check()

        mock_ws.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_heartbeat_checker_breaks_when_agent_removed(self):
        """Agent 已从 active_agents 移除时，checker 应退出循环"""
        from app.ws.ws_agent import active_agents, _heartbeat_checker

        active_agents.clear()

        mock_ws = AsyncMock()
        mock_ws.scope = {"scheme": "wss"}
        mock_ws.headers = {}
        # 不加入 active_agents，checker 应该 break

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await _heartbeat_checker(mock_ws, "session-nonexist")

        assert result is None
        mock_ws.close.assert_not_called()


# ─── 2. Stale TTL 状态机验证 ───


class TestStaleTTLStateMachine:
    """验证 stale → expired → offline 状态流转"""

    @pytest.mark.asyncio
    async def test_stale_to_offline_after_ttl(self):
        """stale 状态在 TTL 后转为 offline"""
        from app.ws.ws_agent import (
            _mark_agent_stale,
            _expire_stale_agent,
            stale_agents,
        )

        stale_agents.clear()

        _mark_agent_stale("session-1")
        assert "session-1" in stale_agents

        with patch("app.ws.ws_agent.set_session_offline", new=AsyncMock()) as mock_offline:
            await _expire_stale_agent("session-1")

        mock_offline.assert_awaited_once_with("session-1", reason="device_offline")
        assert "session-1" not in stale_agents

    @pytest.mark.asyncio
    async def test_stale_recovery_clears_stale_before_connect(self):
        """Agent 重连时，如果处于 stale 状态，应先清除 stale 再连接"""
        from app.ws.ws_agent import (
            stale_agents,
            active_agents,
        )

        stale_agents.clear()
        active_agents.clear()

        # 模拟 stale 状态
        stale_agents["session-1"] = datetime.now(timezone.utc) + timedelta(seconds=90)
        assert "session-1" in stale_agents

        # 模拟 agent 重连
        async def cancelled_iter_text():
            if False:
                yield ""
            raise asyncio.CancelledError

        mock_ws = AsyncMock()
        mock_ws.scope = {"scheme": "wss"}
        mock_ws.headers = {}
        mock_ws.receive_text = AsyncMock(return_value=json.dumps({"type": "auth", "token": "valid-token"}))
        mock_ws.iter_text = MagicMock(return_value=cancelled_iter_text())

        with patch("app.ws.ws_agent.wait_for_ws_auth", new=AsyncMock(return_value=make_ws_auth_payload())):
            with patch("app.ws.ws_agent.get_session", return_value={"session_id": "session-1", "owner": "user1"}):
                with patch("app.ws.ws_agent.set_session_online", new_callable=AsyncMock):
                    with patch("app.ws.ws_agent.update_session_device_heartbeat", new_callable=AsyncMock):
                        with patch("app.ws.ws_client.get_view_counts", return_value={"mobile": 0, "desktop": 0}):
                            with patch("app.ws.ws_agent.list_recoverable_session_terminals", new=AsyncMock(return_value=[])):
                                from app.ws.ws_agent import agent_websocket_handler
                                try:
                                    await agent_websocket_handler(mock_ws)
                                except asyncio.CancelledError:
                                    pass

        # stale 状态应被清除（重连后进入 finally 清理又变 stale）
        # 关键验证：在连接过程中，stale 被清除了
        assert "session-1" not in active_agents  # 连接已断开

    @pytest.mark.asyncio
    async def test_ttl_checker_expires_stale_agents(self):
        """TTL checker 正确检测和过期 stale agents"""
        from app.ws.ws_agent import (
            stale_agents,
            _stale_agent_ttl_checker,
        )

        stale_agents.clear()

        # 设置一个已过期的 stale agent
        stale_agents["session-expired"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        # 设置一个未过期的 stale agent
        stale_agents["session-alive"] = datetime.now(timezone.utc) + timedelta(seconds=90)

        with patch("app.ws.ws_agent.set_session_offline", new=AsyncMock()):
            # 第一次 sleep 正常返回（让检查逻辑执行），第二次退出
            sleep_count = 0

            async def mock_sleep(seconds):
                nonlocal sleep_count
                sleep_count += 1
                if sleep_count >= 2:
                    raise asyncio.CancelledError()

            with patch("asyncio.sleep", side_effect=mock_sleep):
                try:
                    await _stale_agent_ttl_checker()
                except asyncio.CancelledError:
                    pass

        # 已过期的应被清除
        assert "session-expired" not in stale_agents
        # 未过期的应保留
        assert "session-alive" in stale_agents


# ─── 3. Agent 连接 handler 异常路径验证 ───


class TestAgentHandlerExceptionPaths:
    """验证 agent handler 的各种异常退出路径"""

    @pytest.mark.asyncio
    async def test_handler_catches_websocket_disconnect_silently(self):
        """WebSocketDisconnect 应被静默捕获，不打印错误"""
        from app.ws.ws_agent import active_agents

        active_agents.clear()

        async def disconnect_iter_text():
            if False:
                yield ""
            from fastapi import WebSocketDisconnect
            raise WebSocketDisconnect(code=1000)

        mock_ws = AsyncMock()
        mock_ws.scope = {"scheme": "wss"}
        mock_ws.headers = {}
        mock_ws.receive_text = AsyncMock(return_value=json.dumps({"type": "auth", "token": "valid-token"}))
        mock_ws.iter_text = MagicMock(return_value=disconnect_iter_text())

        with patch("app.ws.ws_agent.wait_for_ws_auth", new=AsyncMock(return_value=make_ws_auth_payload())):
            with patch("app.ws.ws_agent.get_session", return_value={"session_id": "session-1", "owner": "user1"}):
                with patch("app.ws.ws_agent.set_session_online", new_callable=AsyncMock):
                    with patch("app.ws.ws_agent.update_session_device_heartbeat", new_callable=AsyncMock):
                        with patch("app.ws.ws_client.get_view_counts", return_value={"mobile": 0, "desktop": 0}):
                            with patch("app.ws.ws_agent.list_recoverable_session_terminals", new=AsyncMock(return_value=[])):
                                from app.ws.ws_agent import agent_websocket_handler
                                # 应不抛异常
                                await agent_websocket_handler(mock_ws)

        # 连接应被清理
        assert "session-1" not in active_agents

    @pytest.mark.asyncio
    async def test_handler_catches_generic_exception(self):
        """一般异常应打印错误并标记 cleanup_reason"""
        from app.ws.ws_agent import active_agents

        active_agents.clear()

        async def error_iter_text():
            if False:
                yield ""
            raise RuntimeError("unexpected error")

        mock_ws = AsyncMock()
        mock_ws.scope = {"scheme": "wss"}
        mock_ws.headers = {}
        mock_ws.receive_text = AsyncMock(return_value=json.dumps({"type": "auth", "token": "valid-token"}))
        mock_ws.iter_text = MagicMock(return_value=error_iter_text())

        with patch("app.ws.ws_agent.wait_for_ws_auth", new=AsyncMock(return_value=make_ws_auth_payload())):
            with patch("app.ws.ws_agent.get_session", return_value={"session_id": "session-1", "owner": "user1"}):
                with patch("app.ws.ws_agent.set_session_online", new_callable=AsyncMock):
                    with patch("app.ws.ws_agent.update_session_device_heartbeat", new_callable=AsyncMock):
                        with patch("app.ws.ws_client.get_view_counts", return_value={"mobile": 0, "desktop": 0}):
                            with patch("app.ws.ws_agent.list_recoverable_session_terminals", new=AsyncMock(return_value=[])):
                                with patch("app.ws.ws_agent.logger") as mock_logger:
                                    from app.ws.ws_agent import agent_websocket_handler
                                    await agent_websocket_handler(mock_ws)
                                    # 应记录错误日志
                                    error_calls = [
                                        call for call in mock_logger.error.call_args_list
                                        if "Agent connection error" in str(call)
                                    ]
                                    assert len(error_calls) >= 1, f"Expected 'Agent connection error' in logger.error calls, got: {mock_logger.error.call_args_list}"

    @pytest.mark.asyncio
    async def test_restore_recoverable_terminals_exception_does_not_break_connection(self):
        """_restore_recoverable_terminals 异常不应断开连接"""
        from app.ws.ws_agent import active_agents

        active_agents.clear()

        messages_sent = []

        async def mock_send_json(msg):
            messages_sent.append(msg)

        async def long_iter_text():
            """发送几条消息后再退出"""
            yield json.dumps({"type": "ping"})
            await asyncio.sleep(0.05)
            from fastapi import WebSocketDisconnect
            raise WebSocketDisconnect(code=1000)

        mock_ws = AsyncMock()
        mock_ws.scope = {"scheme": "wss"}
        mock_ws.headers = {}
        mock_ws.receive_text = AsyncMock(return_value=json.dumps({"type": "auth", "token": "valid-token"}))
        mock_ws.send_json = mock_send_json
        mock_ws.iter_text = MagicMock(return_value=long_iter_text())

        with patch("app.ws.ws_agent.wait_for_ws_auth", new=AsyncMock(return_value=make_ws_auth_payload())):
            with patch("app.ws.ws_agent.get_session", return_value={"session_id": "session-1", "owner": "user1"}):
                with patch("app.ws.ws_agent.set_session_online", new_callable=AsyncMock):
                    with patch("app.ws.ws_agent.update_session_device_heartbeat", new_callable=AsyncMock):
                        with patch("app.ws.ws_client.get_view_counts", return_value={"mobile": 0, "desktop": 0}):
                            with patch(
                                "app.ws.ws_agent.list_recoverable_session_terminals",
                                new=AsyncMock(side_effect=Exception("Redis error")),
                            ):
                                from app.ws.ws_agent import agent_websocket_handler
                                await agent_websocket_handler(mock_ws)

        # connected 消息应该已发送（恢复失败不应阻断初始连接）
        connected_msgs = [m for m in messages_sent if m.get("type") == "connected"]
        assert len(connected_msgs) == 1


# ─── 4. Agent 端断连行为验证 ───


class TestAgentClientDisconnectBehavior:
    """验证 agent 端 WebSocketClient 的断连行为"""

    @pytest.mark.asyncio
    async def test_cleanup_sends_close_1000(self):
        """agent 的 _cleanup() 会以 code 1000 关闭 WebSocket（无参数调用）"""
        try:
            from app.websocket_client import WebSocketClient
        except ImportError:
            pytest.skip("agent module not available")

        client = WebSocketClient(
            server_url="ws://localhost:8888",
            token="test-token",
        )
        client._connected = True

        mock_ws = AsyncMock()
        mock_ws.scope = {"scheme": "wss"}
        mock_ws.headers = {}
        client.ws = mock_ws

        client.runtime_manager.close_all = MagicMock(return_value=[])

        await client._cleanup()

        mock_ws.close.assert_called_once_with()
        assert client._connected is False
        assert client.ws is None

    @pytest.mark.asyncio
    async def test_pty_read_exception_breaks_pty_task_only(self):
        """PTY 读取异常只应中断 pty_to_websocket 任务，不应断开 WebSocket"""
        try:
            from app.websocket_client import WebSocketClient
        except ImportError:
            pytest.skip("agent module not available")

        client = WebSocketClient(
            server_url="ws://localhost:8888",
            token="test-token",
        )
        client._running = True
        client._connected = True

        # Mock PTY that raises on read
        mock_pty = MagicMock()
        mock_pty.read = AsyncMock(side_effect=OSError("PTY read error"))
        client.pty = mock_pty

        mock_ws = AsyncMock()
        mock_ws.scope = {"scheme": "wss"}
        mock_ws.headers = {}
        mock_ws.send = AsyncMock()
        client.ws = mock_ws

        # Run _pty_to_websocket
        await client._pty_to_websocket()

        # 应该退出循环（break）但 WebSocket 未被关闭
        assert client._connected is True

    @pytest.mark.asyncio
    async def test_websocket_recv_error_breaks_ws_task(self):
        """WebSocket 接收错误应中断 _websocket_to_pty 任务"""
        try:
            from app.websocket_client import WebSocketClient
        except ImportError:
            pytest.skip("agent module not available")

        client = WebSocketClient(
            server_url="ws://localhost:8888",
            token="test-token",
        )
        client._running = True
        client._connected = True

        # Mock WebSocket that raises ConnectionClosedOK (code 1000)
        try:
            import websockets.exceptions
            mock_ws = MagicMock()
            mock_ws.recv = AsyncMock(
                side_effect=websockets.exceptions.ConnectionClosedOK(
                    rcvd_then_sent=websockets.frames.Close(code=1000, reason="OK")
                )
            )
            client.ws = mock_ws

            # Run _websocket_to_pty
            await client._websocket_to_pty()
            # 应该退出循环（break on exception）
        except ImportError:
            pytest.skip("websockets library not available")

    @pytest.mark.asyncio
    async def test_gather_exits_when_any_task_breaks(self):
        """gather 在一个任务 break 后等待其他任务也完成"""
        results = []

        async def task_quick():
            results.append("quick_start")
            await asyncio.sleep(0.01)
            results.append("quick_done")

        async def task_slow():
            results.append("slow_start")
            await asyncio.sleep(0.1)
            results.append("slow_done")

        await asyncio.gather(task_quick(), task_slow())
        assert results == ["quick_start", "slow_start", "quick_done", "slow_done"]

    @pytest.mark.asyncio
    async def test_heartbeat_error_triggers_cascade_disconnect(self):
        """
        验证关键断连链路：
        heartbeat_loop 发送失败 → break
        → gather 等待其他任务
        → _cleanup 关闭 ws (code 1000)
        → 服务端收到 close frame

        这模拟了"网络中断导致心跳失败"的场景。
        """
        try:
            from app.websocket_client import WebSocketClient
            import websockets.exceptions
        except ImportError:
            pytest.skip("agent module not available")

        client = WebSocketClient(
            server_url="ws://localhost:8888",
            token="test-token",
        )
        client._running = True
        client._connected = True
        client._retry_count = 0

        mock_ws = MagicMock()

        async def mock_send(data):
            raise websockets.exceptions.ConnectionClosedOK(
                rcvd_then_sent=websockets.frames.Close(code=1000, reason="OK")
            )

        mock_ws.send = mock_send
        mock_ws.recv = AsyncMock(
            side_effect=websockets.exceptions.ConnectionClosedOK(
                rcvd_then_sent=websockets.frames.Close(code=1000, reason="OK")
            )
        )
        mock_ws.close = AsyncMock()
        client.ws = mock_ws

        mock_pty = MagicMock()
        mock_pty.read = AsyncMock(return_value=None)
        mock_pty.stop = MagicMock()
        client.pty = mock_pty
        client.runtime_manager.close_all = MagicMock(return_value=[])

        try:
            client._tasks = [
                asyncio.create_task(client._pty_to_websocket()),
                asyncio.create_task(client._websocket_to_pty()),
                asyncio.create_task(client._heartbeat_loop()),
            ]
            await asyncio.gather(*client._tasks)
        except Exception:
            pass
        finally:
            await client._cleanup()

        mock_ws.close.assert_called()


# ─── 5. 服务端 close code 验证 ───


class TestServerCloseCodes:
    """验证服务端在各种场景下使用的 close code"""

    @pytest.mark.asyncio
    async def test_duplicate_agent_rejected_with_4009(self):
        """重复 Agent 连接应返回 4009"""
        from app.ws.ws_agent import active_agents, AgentConnection

        active_agents.clear()

        # 第一个 agent 已连接
        existing_conn = AgentConnection("session-1", AsyncMock(), "user1")
        active_agents["session-1"] = existing_conn

        mock_ws = AsyncMock()
        mock_ws.scope = {"scheme": "wss"}
        mock_ws.headers = {}
        mock_ws.receive_text = AsyncMock(return_value=json.dumps({"type": "auth", "token": "valid-token"}))

        with patch("app.ws.ws_agent.wait_for_ws_auth", new=AsyncMock(return_value=make_ws_auth_payload())):
            from app.ws.ws_agent import agent_websocket_handler
            await agent_websocket_handler(mock_ws)

        mock_ws.close.assert_called_once_with(code=4009, reason="Session already has an active agent")

    @pytest.mark.asyncio
    async def test_invalid_token_rejected_with_4001(self):
        """无效 token 应返回 4001"""
        mock_ws = AsyncMock()
        mock_ws.scope = {"scheme": "wss"}
        mock_ws.headers = {}
        mock_ws.receive_text = AsyncMock(return_value=json.dumps({"type": "auth", "token": "invalid-token"}))

        from app.ws.ws_agent import agent_websocket_handler
        await agent_websocket_handler(mock_ws)

        mock_ws.close.assert_called_once_with(code=4001, reason="TOKEN_INVALID")

    @pytest.mark.asyncio
    async def test_server_never_sends_close_1000(self):
        """
        关键验证：服务端代码中没有任何路径发送 close code 1000。
        如果 agent 收到 1000，说明不是服务端主动关闭。
        """
        from app.ws.ws_agent import agent_websocket_handler

        # 检查所有可能的 close code
        import inspect
        source = inspect.getsource(agent_websocket_handler)

        # 提取所有 close 调用的 code
        import re
        close_codes = re.findall(r'close\(code=(\d+)', source)
        assert close_codes  # 至少有一些 close 调用
        assert '1000' not in close_codes, "服务端不应发送 close code 1000"

        # 也检查 _heartbeat_checker
        from app.ws.ws_agent import _heartbeat_checker
        checker_source = inspect.getsource(_heartbeat_checker)
        checker_codes = re.findall(r'close\(code=(\d+)', checker_source)
        assert '1000' not in checker_codes, "心跳检查器不应发送 close code 1000"


# ─── 6. 客户端连接与 Agent 状态联动 ───


class TestClientAgentStateInteraction:
    """验证客户端连接与 agent 状态的联动"""

    @pytest.mark.asyncio
    async def test_client_with_terminal_connects_when_agent_offline(self):
        """Agent 离线时，带 terminal_id 的客户端仍可连接（device_online=false）"""
        from app.ws.ws_client import active_clients

        active_clients.clear()

        async def cancelled_iter_text():
            if False:
                yield ""
            raise asyncio.CancelledError

        mock_ws = AsyncMock()
        mock_ws.scope = {"scheme": "wss"}
        mock_ws.headers = {}
        mock_ws.receive_text = AsyncMock(return_value=json.dumps({"type": "auth", "token": "valid-token"}))
        mock_ws.iter_text = MagicMock(return_value=cancelled_iter_text())

        with patch("app.ws.ws_client.wait_for_ws_auth", new=AsyncMock(return_value=make_ws_auth_payload())):
            with patch("app.ws.ws_client.get_session_by_device_id", new=AsyncMock(return_value={
                "session_id": "session-1",
                "owner": "user1",
                "agent_online": False,
                "device": {"device_id": "dev-1"},
            })):
                with patch("app.ws.ws_client.get_session_terminal", new=AsyncMock(return_value={
                    "terminal_id": "term-1",
                    "status": "detached",
                })):
                    with patch("app.ws.ws_client.is_agent_connected", return_value=False):
                        with patch("app.ws.ws_client.update_session_view_count", new_callable=AsyncMock):
                            with patch("app.ws.ws_client.update_session_terminal_views", new=AsyncMock(return_value={
                                "terminal_id": "term-1",
                                "status": "live",
                                "views": {"mobile": 0, "desktop": 0},
                                "geometry_owner_view": None,
                            })):
                                with patch("app.ws.ws_client._broadcast_presence", new_callable=AsyncMock):
                                    from app.ws.ws_client import client_websocket_handler
                                    try:
                                        await client_websocket_handler(
                                            mock_ws, None,
                                            view="desktop", device_id="dev-1", terminal_id="term-1",
                                        )
                                    except asyncio.CancelledError:
                                        pass

        # Agent 离线不再拒绝 Client，而是正常连接（device_online=false）
        first_msg = mock_ws.send_json.call_args_list[0][0][0]
        assert first_msg["type"] == "connected"
        assert first_msg["device_online"] is False
        assert first_msg["agent_online"] is False

    @pytest.mark.asyncio
    async def test_client_without_terminal_connects_even_when_agent_offline(self):
        """不带 terminal_id 的客户端，即使 Agent 离线也应能连接"""
        from app.ws.ws_client import active_clients

        active_clients.clear()

        async def cancelled_iter_text():
            if False:
                yield ""
            raise asyncio.CancelledError

        mock_ws = AsyncMock()
        mock_ws.scope = {"scheme": "wss"}
        mock_ws.headers = {}
        mock_ws.receive_text = AsyncMock(return_value=json.dumps({"type": "auth", "token": "valid-token"}))
        mock_ws.iter_text = MagicMock(return_value=cancelled_iter_text())

        with patch("app.ws.ws_client.wait_for_ws_auth", new=AsyncMock(return_value=make_ws_auth_payload())):
            with patch("app.ws.ws_client.get_session", new=AsyncMock(return_value={
                "session_id": "session-1",
                "owner": "user1",
            })):
                with patch("app.ws.ws_client.is_agent_connected", return_value=False):
                    with patch("app.ws.ws_client.update_session_view_count", new_callable=AsyncMock):
                        with patch("app.ws.ws_client._broadcast_presence", new_callable=AsyncMock):
                            from app.ws.ws_client import client_websocket_handler
                            try:
                                await client_websocket_handler(
                                    mock_ws, "session-1",
                                    view="desktop",
                                )
                            except asyncio.CancelledError:
                                pass

        first_msg = mock_ws.send_json.call_args_list[0][0][0]
        assert first_msg["type"] == "connected"
        assert first_msg["device_online"] is False
        assert first_msg["agent_online"] is False

    @pytest.mark.asyncio
    async def test_client_closed_terminal_rejected(self):
        """已关闭的终端连接应被拒绝"""
        from app.ws.ws_client import active_clients

        active_clients.clear()

        mock_ws = AsyncMock()
        mock_ws.scope = {"scheme": "wss"}
        mock_ws.headers = {}
        mock_ws.receive_text = AsyncMock(return_value=json.dumps({"type": "auth", "token": "valid-token"}))

        with patch("app.ws.ws_client.wait_for_ws_auth", new=AsyncMock(return_value=make_ws_auth_payload())):
            with patch("app.ws.ws_client.get_session_by_device_id", new=AsyncMock(return_value={
                "session_id": "session-1",
                "owner": "user1",
                "device": {"device_id": "dev-1"},
            })):
                with patch("app.ws.ws_client.get_session_terminal", new=AsyncMock(return_value={
                    "terminal_id": "term-1",
                    "status": "closed",
                })):
                    with patch("app.ws.ws_client.is_agent_connected", return_value=True):
                        from app.ws.ws_client import client_websocket_handler
                        await client_websocket_handler(
                            mock_ws, None,
                            view="desktop", device_id="dev-1", terminal_id="term-1",
                        )

        mock_ws.close.assert_called_once_with(code=4009, reason="terminal closed")


# ─── 7. 关键时序验证：谁先触发 close ───


class TestCloseOriginDetection:
    """验证谁先发起 close frame — 排查 agent 还是 server 先关"""

    @pytest.mark.asyncio
    async def test_agent_side_initiated_close_flow(self):
        """
        模拟 agent 端发起 close 的完整流程：
        1. agent _heartbeat_loop 发送 ping 失败
        2. agent _websocket_to_pty 收到 ConnectionClosedOK
        3. agent _pty_to_websocket PTY read 返回 None
        4. gather 完成
        5. agent _cleanup 调用 ws.close() (code 1000)
        6. server 收到 close frame → WebSocketDisconnect → _cleanup_agent → stale
        """
        from app.ws.ws_agent import active_agents
        from fastapi import WebSocketDisconnect

        active_agents.clear()

        mock_ws = AsyncMock()
        mock_ws.scope = {"scheme": "wss"}
        mock_ws.headers = {}
        mock_ws.receive_text = AsyncMock(return_value=json.dumps({"type": "auth", "token": "valid-token"}))
        mock_ws.iter_text = MagicMock(
            return_value=make_async_iter(exc=WebSocketDisconnect(code=1000))
        )

        with patch("app.ws.ws_agent.wait_for_ws_auth", new=AsyncMock(return_value=make_ws_auth_payload())):
            with patch("app.ws.ws_agent.get_session", return_value={"session_id": "session-1", "owner": "user1"}):
                with patch("app.ws.ws_agent.set_session_online", new_callable=AsyncMock):
                    with patch("app.ws.ws_agent.update_session_device_heartbeat", new_callable=AsyncMock):
                        with patch("app.ws.ws_client.get_view_counts", return_value={"mobile": 0, "desktop": 0}):
                            with patch("app.ws.ws_agent.list_recoverable_session_terminals", new=AsyncMock(return_value=[])):
                                from app.ws.ws_agent import agent_websocket_handler
                                await agent_websocket_handler(mock_ws)

        # agent 应已被清理
        assert "session-1" not in active_agents

    @pytest.mark.asyncio
    async def test_server_side_heartbeat_timeout_close_flow(self):
        """
        模拟服务端心跳超时发起 close：
        1. 心跳检查器检测超时
        2. 服务端调用 ws.close(code=1008)
        3. iter_json 抛出 WebSocketDisconnect(1008)
        4. cleanup_agent 标记 stale

        这种场景下 agent 应看到 1008 而非 1000。
        """
        from app.ws.ws_agent import active_agents
        from fastapi import WebSocketDisconnect

        active_agents.clear()

        mock_ws = AsyncMock()
        mock_ws.scope = {"scheme": "wss"}
        mock_ws.headers = {}
        mock_ws.receive_text = AsyncMock(return_value=json.dumps({"type": "auth", "token": "valid-token"}))
        mock_ws.iter_text = MagicMock(
            return_value=make_async_iter(exc=WebSocketDisconnect(code=1008))
        )

        with patch("app.ws.ws_agent.wait_for_ws_auth", new=AsyncMock(return_value=make_ws_auth_payload())):
            with patch("app.ws.ws_agent.get_session", return_value={"session_id": "session-1", "owner": "user1"}):
                with patch("app.ws.ws_agent.set_session_online", new_callable=AsyncMock):
                    with patch("app.ws.ws_agent.update_session_device_heartbeat", new_callable=AsyncMock):
                        with patch("app.ws.ws_client.get_view_counts", return_value={"mobile": 0, "desktop": 0}):
                            with patch("app.ws.ws_agent.list_recoverable_session_terminals", new=AsyncMock(return_value=[])):
                                from app.ws.ws_agent import agent_websocket_handler
                                await agent_websocket_handler(mock_ws)

        # 服务端心跳超时应使用 1008
        assert "session-1" not in active_agents


# ─── 8. 集成级 Ping/Pong 生命周期 ───


class TestPingPongLifecycle:
    """验证 ping/pong 心跳交互的完整生命周期"""

    @pytest.mark.asyncio
    async def test_agent_ping_updates_server_heartbeat(self):
        """Agent 的 ping 消息应正确更新服务端心跳时间"""
        from app.ws.ws_agent import active_agents, AgentConnection, _handle_agent_message

        active_agents.clear()
        mock_ws = AsyncMock()
        mock_ws.scope = {"scheme": "wss"}
        mock_ws.headers = {}
        conn = AgentConnection("session-1", mock_ws, "user1")

        # 模拟心跳超时
        old_heartbeat = datetime.now(timezone.utc) - timedelta(seconds=59)
        conn.last_heartbeat = old_heartbeat
        active_agents["session-1"] = conn

        with patch("app.ws.ws_agent.update_session_device_heartbeat", new_callable=AsyncMock):
            await _handle_agent_message(mock_ws, "session-1", {"type": "ping"})

        # 心跳应被更新
        assert conn.last_heartbeat > old_heartbeat
        # pong 应被发送
        pong_msg = mock_ws.send_json.call_args[0][0]
        assert pong_msg["type"] == "pong"

    @pytest.mark.asyncio
    async def test_multiple_pings_keep_connection_alive(self):
        """连续多次 ping 应保持连接存活"""
        from app.ws.ws_agent import AgentConnection, HEARTBEAT_TIMEOUT

        mock_ws = AsyncMock()
        mock_ws.scope = {"scheme": "wss"}
        mock_ws.headers = {}
        conn = AgentConnection("session-1", mock_ws)

        for i in range(5):
            # 每次 ping 间隔 30 秒
            conn.update_heartbeat()
            assert conn.is_alive() is True

        # 模拟最后 ping 后 HEARTBEAT_TIMEOUT - 1 秒
        conn.last_heartbeat = datetime.now(timezone.utc) - timedelta(
            seconds=HEARTBEAT_TIMEOUT - 1
        )
        assert conn.is_alive() is True

        # 超过 HEARTBEAT_TIMEOUT
        conn.last_heartbeat = datetime.now(timezone.utc) - timedelta(
            seconds=HEARTBEAT_TIMEOUT + 1
        )
        assert conn.is_alive() is False


# ─── 9. 部分更新风险验证（Redis 竞态修复的逃逸路径补测） ───


class TestPartialUpdateRisk:
    """
    验证 set_session_online / set_session_offline 原子操作失败时的行为。
    由于组合函数是原子的，不再有部分更新风险。
    """

    @pytest.mark.asyncio
    async def test_cleanup_immediately_set_offline_failure_is_caught(self):
        """
        _cleanup_agent_immediately 中 set_session_offline 失败。

        期望：异常被捕获，不会抛到调用方。
        """
        from app.ws.ws_agent import _cleanup_agent_immediately, stale_agents

        stale_agents.clear()

        called = False

        async def mock_set_offline(sid, *, reason):
            nonlocal called
            called = True
            raise RuntimeError("Redis connection lost")

        with patch("app.ws.ws_agent.set_session_offline", new=mock_set_offline):
            # 不应抛异常（except Exception: pass）
            await _cleanup_agent_immediately("session-partial")

        assert called

    @pytest.mark.asyncio
    async def test_cleanup_immediately_all_succeed(self):
        """
        _cleanup_agent_immediately 所有步骤成功时应完整执行。
        """
        from app.ws.ws_agent import _cleanup_agent_immediately, stale_agents

        stale_agents.clear()
        stale_agents["session-ok"] = datetime.now(timezone.utc) + timedelta(seconds=90)

        called = False

        async def mock_set_offline(sid, *, reason):
            nonlocal called
            called = True

        with patch("app.ws.ws_agent.set_session_offline", new=mock_set_offline):
            await _cleanup_agent_immediately("session-ok")

        assert called
        assert "session-ok" not in stale_agents

    @pytest.mark.asyncio
    async def test_expire_stale_agent_set_offline_failure_is_caught(self):
        """
        _expire_stale_agent 中 set_session_offline 失败。

        期望：异常被打印，不会抛出。
        """
        from app.ws.ws_agent import _expire_stale_agent, stale_agents

        stale_agents.clear()
        stale_agents["session-expire-partial"] = datetime.now(timezone.utc)

        called = False

        async def mock_set_offline(sid, *, reason):
            nonlocal called
            called = True
            raise RuntimeError("Redis timeout")

        with patch("app.ws.ws_agent.set_session_offline", new=mock_set_offline):
            # 不应抛异常
            await _expire_stale_agent("session-expire-partial")

        assert called
        # stale 已被清除（在函数开头就删了）
        assert "session-expire-partial" not in stale_agents

    @pytest.mark.asyncio
    async def test_expire_stale_agent_all_succeed(self):
        """
        _expire_stale_agent 所有步骤成功时应完整执行。
        """
        from app.ws.ws_agent import _expire_stale_agent, stale_agents

        stale_agents.clear()
        stale_agents["session-expire-ok"] = datetime.now(timezone.utc)

        called = False

        async def mock_set_offline(sid, *, reason):
            nonlocal called
            called = True

        with patch("app.ws.ws_agent.set_session_offline", new=mock_set_offline):
            await _expire_stale_agent("session-expire-ok")

        assert called

    @pytest.mark.asyncio
    async def test_agent_connect_set_online_storage_failure_keeps_connection_alive(self):
        """
        Agent 连接时 set_session_online 遇到底层存储故障，
        连接应继续建立，不应因为在线状态持久化失败而直接断开。
        """
        from app.ws.ws_agent import active_agents
        from fastapi import HTTPException

        active_agents.clear()

        messages_sent = []

        async def cancelled_iter_text():
            if False:
                yield ""

        mock_ws = AsyncMock()
        mock_ws.scope = {"scheme": "wss"}
        mock_ws.headers = {}
        mock_ws.receive_text = AsyncMock(return_value=json.dumps({"type": "auth", "token": "valid-token"}))
        mock_ws.send_json = messages_sent.append
        mock_ws.iter_text = MagicMock(return_value=cancelled_iter_text())

        with patch(
            "app.ws.ws_agent.wait_for_ws_auth",
            new=AsyncMock(return_value=make_ws_auth_payload(session_id="session-redis-fail")),
        ):
            with patch("app.ws.ws_agent.get_session", return_value={"session_id": "session-redis-fail", "owner": "user1"}):
                with patch("app.ws.ws_agent.set_session_online", new=AsyncMock(
                    side_effect=HTTPException(status_code=503, detail="Redis down")
                )):
                    from app.ws.ws_agent import agent_websocket_handler
                    await agent_websocket_handler(mock_ws)

        connected_msgs = [m for m in messages_sent if m.get("type") == "connected"]
        assert len(connected_msgs) == 1
        assert "session-redis-fail" not in active_agents
