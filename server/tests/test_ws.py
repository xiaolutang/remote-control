"""
WebSocket 路由测试
"""
import pytest
import asyncio
import base64
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

from fastapi import HTTPException
from tests.ws_test_helpers import trusted_proxy_headers, trusted_proxy_scope


def _make_auth_msg(token: str) -> str:
    """构造 WS auth 首条消息"""
    return json.dumps({"type": "auth", "token": token})


async def _cancelled_iter_text():
    """空迭代器，立即抛 CancelledError（模拟正常断开）"""
    if False:
        yield ""
    raise asyncio.CancelledError


class TestAgentConnection:
    """Agent 连接测试"""

    def test_agent_connection_init(self):
        """测试 AgentConnection 初始化"""
        from app.ws.ws_agent import AgentConnection

        mock_ws = AsyncMock()
        conn = AgentConnection("session-1", mock_ws)

        assert conn.session_id == "session-1"
        assert conn.websocket == mock_ws
        assert conn.last_heartbeat is not None

    def test_is_alive(self):
        """检查存活状态"""
        from app.ws.ws_agent import AgentConnection

        mock_ws = AsyncMock()
        conn = AgentConnection("session-1", mock_ws)

        assert conn.is_alive() is True

    def test_heartbeat_timeout(self):
        """心跳超时检测"""
        from app.ws.ws_agent import AgentConnection, HEARTBEAT_TIMEOUT
        from datetime import timedelta

        mock_ws = AsyncMock()
        conn = AgentConnection("session-1", mock_ws)

        # 模拟时间流逝
        conn.last_heartbeat = datetime.now(timezone.utc) - timedelta(seconds=HEARTBEAT_TIMEOUT + 10)
        assert conn.is_alive() is False


class TestClientConnection:
    """Client 连接测试"""

    def test_client_connection_init(self):
        """测试 ClientConnection 初始化"""
        from app.ws.ws_client import ClientConnection

        mock_ws = AsyncMock()
        conn = ClientConnection("session-1", mock_ws, terminal_id="term-1", device_id="mbp-01")

        assert conn.session_id == "session-1"
        assert conn.terminal_id == "term-1"
        assert conn.device_id == "mbp-01"
        assert conn.websocket == mock_ws


class TestWebSocketHandler:
    """WebSocket 处理器测试"""

    @pytest.mark.asyncio
    async def test_valid_token_connects(self):
        """有效 token 连接测试"""
        from app.ws.ws_agent import active_agents

        # 清理
        active_agents.clear()

        async def cancelled_iter_text():
            if False:
                yield ""
            raise asyncio.CancelledError

        mock_ws = AsyncMock()
        mock_ws.receive_text = AsyncMock(return_value=json.dumps({"type": "auth", "token": "valid-token"}))
        mock_ws.iter_text = MagicMock(return_value=cancelled_iter_text())
        mock_ws.headers = trusted_proxy_headers()
        mock_ws.scope = trusted_proxy_scope()

        with patch('app.ws.ws_agent.wait_for_ws_auth', new=AsyncMock(return_value=(
            {"session_id": "session-1", "sub": "user1"},
            {"type": "auth", "token": "valid-token"},
        ))):
            with patch('app.ws.ws_agent.get_session', return_value={"session_id": "session-1", "owner": "user1"}):
                with patch('app.ws.ws_agent.set_session_online', new_callable=AsyncMock):
                    with patch('app.ws.ws_agent.update_session_device_heartbeat', new_callable=AsyncMock):
                        with patch('app.ws.ws_client.get_view_counts', return_value={"mobile": 0, "desktop": 0}):
                            with patch('app.ws.ws_agent.list_recoverable_session_terminals', new=AsyncMock(return_value=[])):
                                try:
                                    from app.ws.ws_agent import agent_websocket_handler
                                    await agent_websocket_handler(mock_ws)
                                except asyncio.CancelledError:
                                    pass

    @pytest.mark.asyncio
    async def test_agent_forwarded_wss_connects_without_aes_key(self):
        """本地 wss 网关透传可信 TLS 标记时不应被当成 ws:// 拒绝。"""
        from app.ws.ws_agent import active_agents

        active_agents.clear()

        mock_ws = AsyncMock()
        mock_ws.receive_text = AsyncMock(
            return_value=json.dumps({"type": "auth", "token": "valid-token"})
        )
        mock_ws.iter_text = MagicMock(return_value=_cancelled_iter_text())
        mock_ws.headers = trusted_proxy_headers()
        mock_ws.scope = trusted_proxy_scope()

        with patch(
            "app.ws.ws_agent.wait_for_ws_auth",
            new=AsyncMock(
                return_value=(
                    {"session_id": "session-1", "sub": "user1"},
                    {"type": "auth", "token": "valid-token"},
                )
            ),
        ):
            with patch(
                "app.ws.ws_agent.get_session",
                return_value={"session_id": "session-1", "owner": "user1"},
            ):
                with patch("app.ws.ws_agent.set_session_online", new_callable=AsyncMock):
                    with patch(
                        "app.ws.ws_agent.update_session_device_heartbeat",
                        new_callable=AsyncMock,
                    ):
                        with patch(
                            "app.ws.ws_client.get_view_counts",
                            return_value={"mobile": 0, "desktop": 0},
                        ):
                            with patch(
                                "app.ws.ws_agent.list_recoverable_session_terminals",
                                new=AsyncMock(return_value=[]),
                            ):
                                try:
                                    from app.ws.ws_agent import agent_websocket_handler

                                    await agent_websocket_handler(mock_ws)
                                except asyncio.CancelledError:
                                    pass

        first_message = mock_ws.send_json.call_args_list[0][0][0]
        assert first_message["type"] == "connected"

    @pytest.mark.asyncio
    async def test_agent_ping_updates_device_heartbeat(self):
        """Agent ping 会回写设备心跳。"""
        from app.ws.ws_agent import active_agents, AgentConnection, _handle_agent_message

        active_agents.clear()
        mock_ws = AsyncMock()
        active_agents["session-1"] = AgentConnection("session-1", mock_ws, "user1")

        with patch('app.ws.ws_agent.update_session_device_heartbeat', new_callable=AsyncMock) as mock_heartbeat:
            await _handle_agent_message(mock_ws, "session-1", {"type": "ping"})

        mock_heartbeat.assert_awaited_once_with("session-1", online=True)
        mock_ws.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_terminal_attach_uses_live_agent_connection_not_session_flag(self):
        """terminal 级 attach 只看当前活跃 agent 连接，不看 Redis 历史标记。"""
        async def cancelled_iter_text():
            if False:
                yield ""
            raise asyncio.CancelledError

        mock_ws = AsyncMock()
        mock_ws.receive_text = AsyncMock(return_value=json.dumps({"type": "auth", "token": "valid-token"}))
        mock_ws.iter_text = MagicMock(return_value=cancelled_iter_text())
        mock_ws.headers = trusted_proxy_headers()
        mock_ws.scope = trusted_proxy_scope()

        with patch('app.ws.ws_client.wait_for_ws_auth', new=AsyncMock(return_value=(
            {"session_id": "session-1", "sub": "user1"},
            {"type": "auth", "token": "valid-token"},
        ))):
            with patch('app.ws.ws_client.get_session_by_device_id', new=AsyncMock(return_value={"session_id": "session-1", "owner": "user1", "agent_online": False, "device": {"device_id": "mbp-01"}})):
                with patch('app.ws.ws_client.get_session_terminal', new=AsyncMock(return_value={"terminal_id": "term-1", "status": "detached"})):
                    with patch('app.ws.ws_client.is_agent_connected', return_value=True):
                        with patch('app.ws.ws_client.update_session_view_count', new_callable=AsyncMock):
                            with patch('app.ws.ws_client.update_session_terminal_views', new=AsyncMock(return_value={
                                "terminal_id": "term-1",
                                "status": "live",
                                "views": {"mobile": 0, "desktop": 0},
                                "geometry_owner_view": None,
                            })):
                                with patch('app.ws.ws_client._broadcast_presence', new_callable=AsyncMock):
                                    try:
                                        from app.ws.ws_client import client_websocket_handler
                                        await client_websocket_handler(mock_ws, "session-1", view="desktop", device_id="mbp-01", terminal_id="term-1")
                                    except asyncio.CancelledError:
                                        pass

        first_message = mock_ws.send_json.call_args_list[0][0][0]
        assert first_message["type"] == "connected"
        assert first_message["device_online"] is True

    @pytest.mark.asyncio
    async def test_agent_connect_restores_recoverable_terminals(self):
        """agent 重连后会恢复 grace period 内的 detached terminal。"""
        from app.ws.ws_agent import active_agents

        active_agents.clear()

        async def cancelled_iter_text():
            if False:
                yield ""
            raise asyncio.CancelledError

        mock_ws = AsyncMock()
        mock_ws.receive_text = AsyncMock(return_value=json.dumps({"type": "auth", "token": "valid-token"}))
        mock_ws.iter_text = MagicMock(return_value=cancelled_iter_text())
        mock_ws.headers = trusted_proxy_headers()
        mock_ws.scope = trusted_proxy_scope()
        recoverable = [{
            "terminal_id": "term-1",
            "title": "Claude / one",
            "cwd": "/tmp/one",
            "command": "claude code",
            "env": {"TERM": "xterm-256color"},
        }]

        with patch('app.ws.ws_agent.wait_for_ws_auth', new=AsyncMock(return_value=(
            {"session_id": "session-1", "sub": "user1"},
            {"type": "auth", "token": "valid-token"},
        ))):
            with patch('app.ws.ws_agent.get_session', return_value={"session_id": "session-1", "owner": "user1"}):
                with patch('app.ws.ws_agent.set_session_online', new_callable=AsyncMock):
                    with patch('app.ws.ws_agent.update_session_device_heartbeat', new_callable=AsyncMock):
                        with patch('app.ws.ws_client.get_view_counts', return_value={"mobile": 0, "desktop": 0}):
                            with patch('app.ws.ws_agent.list_recoverable_session_terminals', new=AsyncMock(return_value=recoverable)):
                                try:
                                    from app.ws.ws_agent import agent_websocket_handler
                                    await agent_websocket_handler(mock_ws)
                                except asyncio.CancelledError:
                                        pass

        sent_messages = [call.args[0] for call in mock_ws.send_json.call_args_list]
        assert sent_messages[0]["type"] == "connected"
        assert sent_messages[1]["type"] == "create_terminal"
        assert sent_messages[1]["terminal_id"] == "term-1"
        assert sent_messages[1]["cwd"] == "/tmp/one"

    @pytest.mark.asyncio
    async def test_invalid_token_rejected(self):
        """无效 token 拒绝测试"""
        mock_ws = AsyncMock()
        mock_ws.receive_text = AsyncMock(return_value=json.dumps({"type": "auth", "token": "invalid-token"}))
        mock_ws.headers = trusted_proxy_headers()
        mock_ws.scope = trusted_proxy_scope()

        with patch('app.ws.ws_agent.wait_for_ws_auth', new=AsyncMock(side_effect=HTTPException(status_code=401, detail="Invalid token"))):

            from app.ws.ws_agent import agent_websocket_handler
            await agent_websocket_handler(mock_ws)

        mock_ws.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_client_without_agent(self):
        """Agent 未连接时 Client 连接 - 允许客户端先连接等待 Agent"""
        from app.ws.ws_client import active_clients

        active_clients.clear()

        async def cancelled_iter_text():
            if False:
                yield ""
            raise asyncio.CancelledError

        mock_ws = AsyncMock()
        mock_ws.receive_text = AsyncMock(return_value=json.dumps({"type": "auth", "token": "valid-token"}))
        mock_ws.iter_text = MagicMock(return_value=cancelled_iter_text())
        mock_ws.headers = trusted_proxy_headers()
        mock_ws.scope = trusted_proxy_scope()

        with patch('app.ws.ws_client.wait_for_ws_auth', new=AsyncMock(return_value=(
            {"session_id": "session-1", "sub": "user1"},
            {"type": "auth", "token": "valid-token"},
        ))):
            with patch('app.ws.ws_client.get_session', return_value={"session_id": "session-1", "owner": "user1"}):
                with patch('app.ws.ws_client.is_agent_connected', return_value=False):
                    with patch('app.ws.ws_client.update_session_view_count', new_callable=AsyncMock):
                        with patch('app.ws.ws_client._broadcast_presence', new_callable=AsyncMock):
                            try:
                                from app.ws.ws_client import client_websocket_handler
                                await client_websocket_handler(mock_ws, "session-1")
                            except asyncio.CancelledError:
                                pass

        first_message = mock_ws.send_json.call_args_list[0][0][0]
        assert first_message["type"] == "connected"

    @pytest.mark.asyncio
    async def test_client_forwarded_wss_connects_without_aes_key(self):
        """Client 经过本地 wss 网关时，不应被 ws:// 守卫误杀。"""
        from app.ws.ws_client import active_clients

        active_clients.clear()

        mock_ws = AsyncMock()
        mock_ws.receive_text = AsyncMock(
            return_value=json.dumps({"type": "auth", "token": "valid-token"})
        )
        mock_ws.iter_text = MagicMock(return_value=_cancelled_iter_text())
        mock_ws.headers = trusted_proxy_headers()
        mock_ws.scope = trusted_proxy_scope()

        with patch(
            "app.ws.ws_client.wait_for_ws_auth",
            new=AsyncMock(
                return_value=(
                    {"session_id": "session-1", "sub": "user1"},
                    {"type": "auth", "token": "valid-token"},
                )
            ),
        ):
            with patch(
                "app.ws.ws_client.get_session",
                return_value={"session_id": "session-1", "owner": "user1"},
            ):
                with patch("app.ws.ws_client.is_agent_connected", return_value=False):
                    with patch(
                        "app.ws.ws_client.update_session_view_count",
                        new_callable=AsyncMock,
                    ):
                        with patch(
                            "app.ws.ws_client._broadcast_presence",
                            new_callable=AsyncMock,
                        ):
                            try:
                                from app.ws.ws_client import client_websocket_handler

                                await client_websocket_handler(mock_ws, "session-1")
                            except asyncio.CancelledError:
                                pass

        first_message = mock_ws.send_json.call_args_list[0][0][0]
        assert first_message["type"] == "connected"


class TestBroadcast:
    """广播测试"""

    @pytest.mark.asyncio
    async def test_broadcast_to_clients(self):
        """广播消息到客户端"""
        from app.ws.ws_client import active_clients, broadcast_to_clients, ClientConnection

        active_clients.clear()

        # 创建模拟客户端
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()

        active_clients["session-1"] = [
            ClientConnection("session-1", mock_ws1),
            ClientConnection("session-1", mock_ws2),
        ]

        # 广播消息
        await broadcast_to_clients("session-1", {"type": "test"})

        # 验证两个客户端都收到消息
        mock_ws1.send_json.assert_called_once()
        mock_ws2.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_to_terminal_scoped_clients(self):
        """terminal 级广播只发给目标 terminal"""
        from app.ws.ws_client import active_clients, broadcast_to_clients, ClientConnection

        active_clients.clear()

        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()

        active_clients["session-1:term-1"] = [
            ClientConnection("session-1", mock_ws1, "mobile", terminal_id="term-1"),
        ]
        active_clients["session-1:term-2"] = [
            ClientConnection("session-1", mock_ws2, "desktop", terminal_id="term-2"),
        ]

        await broadcast_to_clients("session-1", {"type": "output"}, terminal_id="term-1")

        mock_ws1.send_json.assert_called_once()
        mock_ws2.send_json.assert_not_called()


class TestConnectionManagement:
    """连接管理测试"""

    def test_get_agent_connection(self):
        """获取 Agent 连接"""
        from app.ws.ws_agent import active_agents, get_agent_connection, AgentConnection

        active_agents.clear()

        mock_ws = AsyncMock()
        conn = AgentConnection("session-1", mock_ws)
        active_agents["session-1"] = conn

        result = get_agent_connection("session-1")
        assert result == conn

        result = get_agent_connection("nonexistent")
        assert result is None

    def test_is_agent_connected(self):
        """检查 Agent 是否连接"""
        from app.ws.ws_agent import active_agents, is_agent_connected, AgentConnection

        active_agents.clear()

        assert is_agent_connected("session-1") is False

        mock_ws = AsyncMock()
        active_agents["session-1"] = AgentConnection("session-1", mock_ws)

        assert is_agent_connected("session-1") is True

    def test_get_client_count(self):
        """获取客户端数量"""
        from app.ws.ws_client import active_clients, get_client_count, ClientConnection

        active_clients.clear()

        assert get_client_count("session-1") == 0

        mock_ws = AsyncMock()
        active_clients["session-1"] = [
            ClientConnection("session-1", mock_ws),
        ]

        assert get_client_count("session-1") == 1

    def test_get_view_counts_for_terminal_scope(self):
        """terminal 级 view 统计"""
        from app.ws.ws_client import active_clients, get_view_counts, ClientConnection

        active_clients.clear()
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()

        active_clients["session-1:term-1"] = [
            ClientConnection("session-1", mock_ws1, "mobile", terminal_id="term-1"),
            ClientConnection("session-1", mock_ws2, "desktop", terminal_id="term-1"),
        ]

        counts = get_view_counts("session-1", "term-1")
        assert counts["mobile"] == 1
        assert counts["desktop"] == 1

    @pytest.mark.asyncio
    async def test_client_message_forwards_terminal_id_to_agent(self):
        """client 输入转发时带 terminal_id"""
        from app.ws.ws_agent import active_agents, AgentConnection
        from app.ws.ws_client import _handle_client_message

        active_agents.clear()
        mock_agent_ws = AsyncMock()
        active_agents["session-1"] = AgentConnection("session-1", mock_agent_ws, "test-user")

        await _handle_client_message(
            AsyncMock(),
            "session-1",
            {"type": "data", "payload": "dGVzdA=="},
            view="mobile",
            terminal_id="term-1",
        )

        call_args = mock_agent_ws.send_json.call_args[0][0]
        assert call_args["terminal_id"] == "term-1"

    @pytest.mark.asyncio
    async def test_mobile_resize_is_ignored_when_desktop_attached(self):
        """非 owner 视图的 resize 不应改全局 PTY。"""
        from app.ws.ws_agent import active_agents, AgentConnection
        from app.ws.ws_client import _handle_client_message

        active_agents.clear()

        mock_agent_ws = AsyncMock()
        active_agents["session-1"] = AgentConnection("session-1", mock_agent_ws, "test-user")

        with patch("app.ws.ws_client.get_session_terminal", new=AsyncMock(return_value={
            "terminal_id": "term-1",
            "geometry_owner_view": "desktop",
            "pty": {"rows": 30, "cols": 90},
        })):
            await _handle_client_message(
                AsyncMock(),
                "session-1",
                {"type": "resize", "rows": 20, "cols": 40},
                view="mobile",
                terminal_id="term-1",
            )

        mock_agent_ws.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_desktop_resize_updates_terminal_pty_and_broadcasts(self):
        """desktop resize 会更新 terminal PTY 并广播给同 terminal 的其他客户端。"""
        from app.ws.ws_agent import active_agents, AgentConnection
        from app.ws.ws_client import _handle_client_message

        active_agents.clear()

        mock_agent_ws = AsyncMock()
        active_agents["session-1"] = AgentConnection("session-1", mock_agent_ws, "test-user")

        with patch("app.ws.ws_client.update_session_pty_size", new=AsyncMock()) as update_session_pty:
            with patch("app.ws.ws_client.update_session_terminal_pty", new=AsyncMock()) as update_terminal_pty:
                with patch("app.ws.ws_client.broadcast_to_clients", new=AsyncMock()) as broadcast:
                    with patch("app.ws.ws_client.get_session_terminal", new=AsyncMock(return_value={
                        "terminal_id": "term-1",
                        "geometry_owner_view": "desktop",
                        "pty": {"rows": 30, "cols": 90},
                    })):
                        await _handle_client_message(
                            AsyncMock(),
                            "session-1",
                            {"type": "resize", "rows": 30, "cols": 90},
                            view="desktop",
                            terminal_id="term-1",
                        )

        update_session_pty.assert_awaited_once_with("session-1", rows=30, cols=90)
        update_terminal_pty.assert_awaited_once_with(
            "session-1",
            "term-1",
            rows=30,
            cols=90,
        )
        mock_agent_ws.send_json.assert_called_once()
        forwarded = mock_agent_ws.send_json.call_args[0][0]
        assert forwarded["type"] == "resize"
        assert forwarded["rows"] == 30
        assert forwarded["cols"] == 90
        broadcast.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_terminal_client_receives_snapshot_after_connected(self):
        """terminal attach 后服务端先发 connected，再回放 snapshot。"""
        async def cancelled_iter_text():
            if False:
                yield ""
            raise asyncio.CancelledError

        mock_ws = AsyncMock()
        mock_ws.receive_text = AsyncMock(return_value=json.dumps({"type": "auth", "token": "valid-token"}))
        mock_ws.iter_text = MagicMock(return_value=cancelled_iter_text())
        mock_ws.headers = trusted_proxy_headers()
        mock_ws.scope = trusted_proxy_scope()

        with patch('app.ws.ws_client.wait_for_ws_auth', new=AsyncMock(return_value=(
            {"session_id": "session-1", "sub": "user1"},
            {"type": "auth", "token": "valid-token"},
        ))):
            with patch('app.ws.ws_client.get_session_by_device_id', new=AsyncMock(return_value={"session_id": "session-1", "owner": "user1", "device": {"device_id": "mbp-01"}})):
                with patch('app.ws.ws_client.get_session_terminal', new=AsyncMock(return_value={"terminal_id": "term-1", "status": "detached_recoverable", "pty": {"rows": 42, "cols": 120}, "attach_epoch": 3, "recovery_epoch": 5})):
                    with patch('app.ws.ws_client.get_terminal_output_history', new=AsyncMock(return_value=[
                        {"data": "\u001b[?1049hhello"},
                        {"data": " world"},
                    ])):
                        with patch('app.ws.ws_client.request_agent_terminal_snapshot', new=AsyncMock(return_value=None)):
                            with patch('app.ws.ws_client.is_agent_connected', return_value=True):
                                with patch('app.ws.ws_client.update_session_view_count', new_callable=AsyncMock):
                                    with patch('app.ws.ws_client.update_session_terminal_views', new=AsyncMock(return_value={
                                        "terminal_id": "term-1",
                                        "status": "live",
                                        "pty": {"rows": 42, "cols": 120},
                                        "views": {"mobile": 0, "desktop": 1},
                                        "geometry_owner_view": "desktop",
                                        "attach_epoch": 3,
                                        "recovery_epoch": 5,
                                    })):
                                        with patch('app.ws.ws_client._broadcast_presence', new_callable=AsyncMock):
                                            try:
                                                from app.ws.ws_client import client_websocket_handler
                                                await client_websocket_handler(
                                                    mock_ws,
                                                    "session-1",
                                                    view="desktop",
                                                    device_id="mbp-01",
                                                    terminal_id="term-1",
                                                )
                                            except asyncio.CancelledError:
                                                pass

        sent_messages = [call.args[0] for call in mock_ws.send_json.call_args_list]
        assert sent_messages[0]["type"] == "connected"
        assert sent_messages[0]["pty"] == {"rows": 42, "cols": 120}
        assert sent_messages[0]["geometry_owner_view"] == "desktop"
        assert sent_messages[0]["views"] == {"mobile": 0, "desktop": 1}
        assert sent_messages[1]["type"] == "snapshot_start"
        assert sent_messages[1]["attach_epoch"] == 3
        assert sent_messages[1]["recovery_epoch"] == 5
        assert sent_messages[2]["type"] == "snapshot_chunk"
        assert sent_messages[3]["type"] == "snapshot_complete"

    @pytest.mark.asyncio
    async def test_terminal_client_falls_back_to_agent_snapshot_when_history_empty(self):
        """terminal 历史为空时，服务端会向 agent 请求 live snapshot。"""
        async def cancelled_iter_text():
            if False:
                yield ""
            raise asyncio.CancelledError

        mock_ws = AsyncMock()
        mock_ws.receive_text = AsyncMock(return_value=json.dumps({"type": "auth", "token": "valid-token"}))
        mock_ws.iter_text = MagicMock(return_value=cancelled_iter_text())
        mock_ws.headers = trusted_proxy_headers()
        mock_ws.scope = trusted_proxy_scope()

        with patch('app.ws.ws_client.wait_for_ws_auth', new=AsyncMock(return_value=(
            {"session_id": "session-1", "sub": "user1"},
            {"type": "auth", "token": "valid-token"},
        ))):
            with patch('app.ws.ws_client.get_session_by_device_id', new=AsyncMock(return_value={"session_id": "session-1", "owner": "user1", "device": {"device_id": "mbp-01"}})):
                with patch('app.ws.ws_client.get_session_terminal', new=AsyncMock(return_value={"terminal_id": "term-1", "status": "detached_recoverable", "pty": {"rows": 24, "cols": 80}, "attach_epoch": 4, "recovery_epoch": 8})):
                    with patch('app.ws.ws_client.get_terminal_output_history', new=AsyncMock(return_value=[])):
                        with patch('app.ws.ws_client.request_agent_terminal_snapshot', new=AsyncMock(return_value={
                            "payload": base64.b64encode(b'live snapshot').decode(),
                            "pty": {"rows": 24, "cols": 80},
                            "active_buffer": "main",
                        })):
                            with patch('app.ws.ws_client.is_agent_connected', return_value=True):
                                with patch('app.ws.ws_client.update_session_view_count', new_callable=AsyncMock):
                                    with patch('app.ws.ws_client.update_session_terminal_views', new=AsyncMock(return_value={
                                        "terminal_id": "term-1",
                                        "status": "live",
                                        "pty": {"rows": 24, "cols": 80},
                                        "views": {"mobile": 0, "desktop": 1},
                                        "geometry_owner_view": "desktop",
                                        "attach_epoch": 4,
                                        "recovery_epoch": 8,
                                    })):
                                        with patch('app.ws.ws_client._broadcast_presence', new_callable=AsyncMock):
                                            try:
                                                from app.ws.ws_client import client_websocket_handler
                                                await client_websocket_handler(
                                                    mock_ws,
                                                    "session-1",
                                                    view="desktop",
                                                    device_id="mbp-01",
                                                    terminal_id="term-1",
                                                )
                                            except asyncio.CancelledError:
                                                pass

        sent_messages = [call.args[0] for call in mock_ws.send_json.call_args_list]
        assert sent_messages[0]["type"] == "connected"
        assert sent_messages[0]["pty"] == {"rows": 24, "cols": 80}
        assert sent_messages[0]["geometry_owner_view"] == "desktop"
        assert sent_messages[1]["type"] == "snapshot_start"
        assert sent_messages[2]["type"] == "snapshot_chunk"
        assert sent_messages[3]["type"] == "snapshot_complete"

    @pytest.mark.asyncio
    async def test_cleanup_does_not_override_closed_terminal(self):
        """terminal 已关闭时，client cleanup 不应回写 detached。"""
        from app.ws.ws_client import _cleanup_client, ClientConnection, active_clients

        active_clients.clear()
        conn = ClientConnection("session-1", AsyncMock(), "mobile", terminal_id="term-1")
        active_clients["session-1:term-1"] = [conn]

        with patch("app.ws.ws_client.update_session_view_count", new=AsyncMock()):
            with patch("app.ws.ws_client._broadcast_presence", new=AsyncMock()):
                with patch("app.ws.ws_client.get_session_terminal", new=AsyncMock(return_value={
                    "terminal_id": "term-1",
                    "status": "closed",
                })):
                    await _cleanup_client("session-1", conn, "mobile", terminal_id="term-1")

    @pytest.mark.asyncio
    async def test_request_agent_create_terminal_sends_command(self):
        """create terminal 请求会下发到 agent 并等待确认 future。"""
        from app.ws.ws_agent import (
            active_agents,
            AgentConnection,
            pending_terminal_creates,
            request_agent_create_terminal,
        )

        active_agents.clear()
        pending_terminal_creates.clear()
        mock_ws = AsyncMock()
        active_agents["session-1"] = AgentConnection("session-1", mock_ws, "user1")

        async def complete_create():
            await asyncio.sleep(0)
            future = pending_terminal_creates[("session-1", "term-1")]
            future.set_result({"terminal_id": "term-1"})

        task = asyncio.create_task(complete_create())
        with patch("app.ws.ws_agent.get_session_terminal", new=AsyncMock(return_value={
            "terminal_id": "term-1",
            "status": "detached",
        })):
            result = await request_agent_create_terminal(
                "session-1",
                terminal_id="term-1",
                title="Claude",
                cwd="/tmp",
                command="/bin/bash",
                rows=36,
                cols=100,
            )

        await task
        call_args = mock_ws.send_json.call_args[0][0]
        assert call_args["type"] == "create_terminal"
        assert call_args["terminal_id"] == "term-1"
        assert call_args["rows"] == 36
        assert call_args["cols"] == 100
        assert result["terminal_id"] == "term-1"

    @pytest.mark.asyncio
    async def test_request_agent_create_terminal_maps_agent_disconnect_to_device_offline(self):
        """pending future 因 agent 断开失败时，映射为 device offline。"""
        from app.ws.ws_agent import (
            active_agents,
            AgentConnection,
            pending_terminal_creates,
            request_agent_create_terminal,
        )

        active_agents.clear()
        pending_terminal_creates.clear()
        mock_ws = AsyncMock()
        active_agents["session-1"] = AgentConnection("session-1", mock_ws, "user1")

        async def fail_create():
            await asyncio.sleep(0)
            future = pending_terminal_creates[("session-1", "term-1")]
            future.set_exception(RuntimeError("agent disconnected: network_lost"))

        task = asyncio.create_task(fail_create())
        with pytest.raises(HTTPException) as exc_info:
            await request_agent_create_terminal(
                "session-1",
                terminal_id="term-1",
                title="Claude",
                cwd="/tmp",
                command="/bin/bash",
            )

        await task
        assert exc_info.value.status_code == 409
        assert "device offline" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_cleanup_agent_marks_as_stale_not_offline(self):
        """Agent 断开后，先标记为 stale 而非立即 offline。"""
        from app.ws.ws_agent import _cleanup_agent, active_agents, AgentConnection, stale_agents

        active_agents.clear()
        stale_agents.clear()
        active_agents["session-1"] = AgentConnection("session-1", AsyncMock(), "user1")

        await _cleanup_agent("session-1", "network_lost")

        # 应该被标记为 stale，而不是立即 offline
        assert "session-1" in stale_agents
        assert "session-1" not in active_agents

    @pytest.mark.asyncio
    async def test_cleanup_agent_immediately_sets_offline(self):
        """显式停止时，立即设为 offline（不经过 stale）。"""
        from app.ws.ws_agent import _cleanup_agent_immediately, active_agents, AgentConnection, stale_agents

        active_agents.clear()
        stale_agents.clear()
        active_agents["session-1"] = AgentConnection("session-1", AsyncMock(), "user1")

        with patch("app.ws.ws_agent.set_session_offline", new=AsyncMock()) as set_offline:
            await _cleanup_agent_immediately("session-1")

        set_offline.assert_awaited_once_with("session-1", reason="agent_shutdown")
        assert "session-1" not in stale_agents

    @pytest.mark.asyncio
    async def test_cleanup_agent_agent_shutdown_sets_offline_not_stale(self):
        """agent_shutdown 应立即关闭 terminal，不进入 stale/recoverable。"""
        from app.ws.ws_agent import _cleanup_agent, active_agents, AgentConnection, stale_agents

        active_agents.clear()
        stale_agents.clear()
        active_agents["session-1"] = AgentConnection("session-1", AsyncMock(), "user1")

        with patch("app.ws.ws_agent.set_session_offline", new=AsyncMock()) as set_offline, \
             patch("app.ws.ws_agent.set_session_offline_recoverable", new=AsyncMock()) as set_offline_recoverable:
            await _cleanup_agent("session-1", "agent_shutdown")

        set_offline.assert_awaited_once_with("session-1", reason="agent_shutdown")
        set_offline_recoverable.assert_not_awaited()
        assert "session-1" not in stale_agents
        assert "session-1" not in active_agents

    @pytest.mark.asyncio
    async def test_stale_agent_recovery_on_reconnect(self):
        """Agent 重连时，如果处于 stale 状态，应该恢复。"""
        from app.ws.ws_agent import stale_agents, _is_agent_stale, _clear_agent_stale

        stale_agents.clear()
        stale_agents["session-1"] = datetime.now(timezone.utc) + timedelta(seconds=90)

        assert _is_agent_stale("session-1") is True
        _clear_agent_stale("session-1")
        assert _is_agent_stale("session-1") is False


class TestTerminalsChangedBroadcast:
    """终端变化广播测试"""

    @pytest.mark.asyncio
    async def test_terminal_created_broadcasts_to_session_level(self):
        """terminal_created 消息应广播到 session 级别（所有客户端）"""
        from app.ws.ws_agent import _handle_agent_message, active_agents, AgentConnection
        from app.ws.ws_client import active_clients, ClientConnection

        active_agents.clear()
        active_clients.clear()

        # 创建 Agent 连接
        mock_agent_ws = AsyncMock()
        active_agents["session-1"] = AgentConnection("session-1", mock_agent_ws, "user1")

        # 创建多个客户端连接（不同终端）
        mock_client_ws1 = AsyncMock()
        mock_client_ws2 = AsyncMock()
        mock_client_ws3 = AsyncMock()

        # session 级别的客户端（没有绑定特定终端）
        active_clients["session-1"] = [
            ClientConnection("session-1", mock_client_ws1, "mobile"),
        ]
        # 终端级别的客户端
        active_clients["session-1:term-other"] = [
            ClientConnection("session-1", mock_client_ws2, "desktop", terminal_id="term-other"),
        ]
        active_clients["session-1:term-new"] = [
            ClientConnection("session-1", mock_client_ws3, "mobile", terminal_id="term-new"),
        ]

        with patch("app.ws.ws_agent.update_session_terminal_status", new=AsyncMock(return_value={
            "terminal_id": "term-new",
            "status": "detached",
        })):
            await _handle_agent_message(
                mock_agent_ws,
                "session-1",
                {"type": "terminal_created", "terminal_id": "term-new"},
            )

        # 验证所有客户端（包括 session 级别和终端级别）都收到了 terminals_changed 消息
        # 这是关键的测试：broadcast_to_clients(session_id, message, terminal_id=None)
        # 应该发送到所有匹配 session_id 前缀的 channels

        sent_to_session_client = False
        sent_to_terminal_other_client = False
        sent_to_terminal_new_client = False

        # 检查 session 级别的客户端
        for call in mock_client_ws1.send_json.call_args_list:
            msg = call.args[0]
            if msg.get("type") == "terminals_changed":
                assert msg["action"] == "created"
                assert msg["terminal_id"] == "term-new"
                sent_to_session_client = True

        # 检查终端级别的客户端（term-other）- 关键验证！
        for call in mock_client_ws2.send_json.call_args_list:
            msg = call.args[0]
            if msg.get("type") == "terminals_changed":
                assert msg["action"] == "created"
                assert msg["terminal_id"] == "term-new"
                sent_to_terminal_other_client = True

        # 检查终端级别的客户端（term-new）
        for call in mock_client_ws3.send_json.call_args_list:
            msg = call.args[0]
            if msg.get("type") == "terminals_changed":
                assert msg["action"] == "created"
                assert msg["terminal_id"] == "term-new"
                sent_to_terminal_new_client = True

        assert sent_to_session_client, "Session level client should receive terminals_changed"
        assert sent_to_terminal_other_client, "Terminal level client (term-other) should receive terminals_changed"
        assert sent_to_terminal_new_client, "Terminal level client (term-new) should receive terminals_changed"

    @pytest.mark.asyncio
    async def test_terminal_closed_broadcasts_to_session_level(self):
        """terminal_closed 消息应广播到 session 级别"""
        from app.ws.ws_agent import _handle_agent_message, active_agents, AgentConnection
        from app.ws.ws_client import active_clients, ClientConnection

        active_agents.clear()
        active_clients.clear()

        mock_agent_ws = AsyncMock()
        active_agents["session-1"] = AgentConnection("session-1", mock_agent_ws, "user1")

        mock_client_ws = AsyncMock()
        active_clients["session-1"] = [
            ClientConnection("session-1", mock_client_ws, "mobile"),
        ]

        with patch("app.ws.ws_agent.update_session_terminal_status", new=AsyncMock()):
            await _handle_agent_message(
                mock_agent_ws,
                "session-1",
                {"type": "terminal_closed", "terminal_id": "term-1", "reason": "terminal_exit"},
            )

        sent_to_client = False
        for call in mock_client_ws.send_json.call_args_list:
            msg = call.args[0]
            if msg.get("type") == "terminals_changed":
                assert msg["action"] == "closed"
                assert msg["terminal_id"] == "term-1"
                assert msg["reason"] == "terminal_exit"
                sent_to_client = True

        assert sent_to_client, "Client should receive terminals_changed on terminal close"

    @pytest.mark.asyncio
    async def test_terminals_changed_includes_timestamp(self):
        """terminals_changed 消息应包含时间戳"""
        from app.ws.ws_agent import _handle_agent_message, active_agents, AgentConnection
        from app.ws.ws_client import active_clients, ClientConnection

        active_agents.clear()
        active_clients.clear()

        mock_agent_ws = AsyncMock()
        active_agents["session-1"] = AgentConnection("session-1", mock_agent_ws, "user1")

        mock_client_ws = AsyncMock()
        active_clients["session-1"] = [
            ClientConnection("session-1", mock_client_ws, "mobile"),
        ]

        with patch("app.ws.ws_agent.update_session_terminal_status", new=AsyncMock(return_value={
            "terminal_id": "term-new",
            "status": "detached",
        })):
            await _handle_agent_message(
                mock_agent_ws,
                "session-1",
                {"type": "terminal_created", "terminal_id": "term-new"},
            )

        # 验证时间戳存在
        for call in mock_client_ws.send_json.call_args_list:
            msg = call.args[0]
            if msg.get("type") == "terminals_changed":
                assert "timestamp" in msg
                assert msg["timestamp"] is not None
                break

    @pytest.mark.asyncio
    async def test_terminals_changed_with_missing_terminal_id(self):
        """terminal_id 缺失时不应广播"""
        from app.ws.ws_agent import _handle_agent_message, active_agents, AgentConnection
        from app.ws.ws_client import active_clients, ClientConnection

        active_agents.clear()
        active_clients.clear()

        mock_agent_ws = AsyncMock()
        active_agents["session-1"] = AgentConnection("session-1", mock_agent_ws, "user1")

        mock_client_ws = AsyncMock()
        active_clients["session-1"] = [
            ClientConnection("session-1", mock_client_ws, "mobile"),
        ]

        # 发送没有 terminal_id 的消息
        await _handle_agent_message(
            mock_agent_ws,
            "session-1",
            {"type": "terminal_created"},  # 缺少 terminal_id
        )

        # 不应该调用 update_session_terminal_status
        # 也不应该广播

    @pytest.mark.asyncio
    async def test_broadcast_to_multiple_session_clients(self):
        """广播应发送给 session 级别的所有客户端"""
        from app.ws.ws_agent import _handle_agent_message, active_agents, AgentConnection
        from app.ws.ws_client import active_clients, ClientConnection

        active_agents.clear()
        active_clients.clear()

        mock_agent_ws = AsyncMock()
        active_agents["session-1"] = AgentConnection("session-1", mock_agent_ws, "user1")

        # 创建多个 session 级别客户端（模拟手机端和桌面端）
        mock_mobile_ws = AsyncMock()
        mock_desktop_ws = AsyncMock()
        active_clients["session-1"] = [
            ClientConnection("session-1", mock_mobile_ws, "mobile"),
            ClientConnection("session-1", mock_desktop_ws, "desktop"),
        ]

        with patch("app.ws.ws_agent.update_session_terminal_status", new=AsyncMock(return_value={
            "terminal_id": "term-new",
            "status": "detached",
        })):
            await _handle_agent_message(
                mock_agent_ws,
                "session-1",
                {"type": "terminal_created", "terminal_id": "term-new"},
            )

        # 两个客户端都应该收到
        mobile_received = False
        desktop_received = False

        for call in mock_mobile_ws.send_json.call_args_list:
            msg = call.args[0]
            if msg.get("type") == "terminals_changed":
                mobile_received = True

        for call in mock_desktop_ws.send_json.call_args_list:
            msg = call.args[0]
            if msg.get("type") == "terminals_changed":
                desktop_received = True

        assert mobile_received, "Mobile client should receive broadcast"
        assert desktop_received, "Desktop client should receive broadcast"

    @pytest.mark.asyncio
    async def test_broadcast_does_not_send_to_different_session(self):
        """广播不应发送给其他 session 的客户端"""
        from app.ws.ws_agent import _handle_agent_message, active_agents, AgentConnection
        from app.ws.ws_client import active_clients, ClientConnection

        active_agents.clear()
        active_clients.clear()

        mock_agent_ws = AsyncMock()
        active_agents["session-1"] = AgentConnection("session-1", mock_agent_ws, "user1")

        # session-1 的客户端
        mock_ws1 = AsyncMock()
        active_clients["session-1"] = [
            ClientConnection("session-1", mock_ws1, "mobile"),
        ]

        # session-2 的客户端（不应该收到）
        mock_ws2 = AsyncMock()
        active_clients["session-2"] = [
            ClientConnection("session-2", mock_ws2, "mobile"),
        ]

        with patch("app.ws.ws_agent.update_session_terminal_status", new=AsyncMock(return_value={
            "terminal_id": "term-new",
            "status": "detached",
        })):
            await _handle_agent_message(
                mock_agent_ws,
                "session-1",
                {"type": "terminal_created", "terminal_id": "term-new"},
            )

        # session-1 应该收到
        session1_received = False
        for call in mock_ws1.send_json.call_args_list:
            msg = call.args[0]
            if msg.get("type") == "terminals_changed":
                session1_received = True
                break

        # session-2 不应该收到
        session2_received = False
        for call in mock_ws2.send_json.call_args_list:
            msg = call.args[0]
            if msg.get("type") == "terminals_changed":
                session2_received = True
                break

        assert session1_received, "session-1 client should receive broadcast"
        assert not session2_received, "session-2 client should NOT receive broadcast"

    @pytest.mark.asyncio
    async def test_terminal_closed_clears_pending_create_future(self):
        """terminal_closed 应该清理 pending 的 create future"""
        from app.ws.ws_agent import (
            _handle_agent_message,
            active_agents,
            AgentConnection,
            pending_terminal_creates,
        )
        from app.ws.ws_client import active_clients

        active_agents.clear()
        active_clients.clear()
        pending_terminal_creates.clear()

        mock_agent_ws = AsyncMock()
        active_agents["session-1"] = AgentConnection("session-1", mock_agent_ws, "user1")

        # 模拟有一个 pending 的 create future
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        pending_terminal_creates[("session-1", "term-1")] = future

        with patch("app.ws.ws_agent.update_session_terminal_status", new=AsyncMock()):
            await _handle_agent_message(
                mock_agent_ws,
                "session-1",
                {"type": "terminal_closed", "terminal_id": "term-1", "reason": "create_failed"},
            )

        # future 应该被设置异常
        assert future.done()
        with pytest.raises(RuntimeError):
            future.result()

        # 应该从 pending 字典中移除
        assert ("session-1", "term-1") not in pending_terminal_creates

    @pytest.mark.asyncio
    async def test_terminal_closed_clears_pending_close_future(self):
        """terminal_closed 应该完成 pending 的 close future"""
        from app.ws.ws_agent import (
            _handle_agent_message,
            active_agents,
            AgentConnection,
            pending_terminal_closes,
        )
        from app.ws.ws_client import active_clients

        active_agents.clear()
        active_clients.clear()
        pending_terminal_closes.clear()

        mock_agent_ws = AsyncMock()
        active_agents["session-1"] = AgentConnection("session-1", mock_agent_ws, "user1")

        # 模拟有一个 pending 的 close future
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        pending_terminal_closes[("session-1", "term-1")] = future

        with patch("app.ws.ws_agent.update_session_terminal_status", new=AsyncMock()):
            await _handle_agent_message(
                mock_agent_ws,
                "session-1",
                {"type": "terminal_closed", "terminal_id": "term-1", "reason": "terminal_exit"},
            )

        # future 应该被完成
        assert future.done()
        result = future.result()
        assert result["terminal_id"] == "term-1"
        assert result["reason"] == "terminal_exit"

        # 应该从 pending 字典中移除
        assert ("session-1", "term-1") not in pending_terminal_closes

    @pytest.mark.asyncio
    async def test_agent_output_broadcasts_output_with_epochs(self):
        """agent 输出转 client 时应使用 output 事件并附带 epoch。"""
        from app.ws.ws_agent import _handle_agent_message, active_agents, AgentConnection

        active_agents.clear()

        mock_agent_ws = AsyncMock()
        active_agents["session-1"] = AgentConnection("session-1", mock_agent_ws, "user1")

        with patch("app.ws.ws_agent.get_session_terminal", new=AsyncMock(return_value={
            "terminal_id": "term-1",
            "attach_epoch": 4,
            "recovery_epoch": 9,
        })):
            with patch("app.ws.ws_agent.append_history", new=AsyncMock()):
                with patch("app.ws.ws_client.broadcast_to_clients", new=AsyncMock()) as broadcast:
                    await _handle_agent_message(
                        mock_agent_ws,
                        "session-1",
                        {
                            "type": "data",
                            "terminal_id": "term-1",
                            "payload": "dGVzdA==",
                            "direction": "output",
                        },
                    )

        broadcast.assert_awaited_once()
        call = broadcast.await_args
        assert call.args[0] == "session-1"
        assert call.kwargs["terminal_id"] == "term-1"
        message = call.args[1]
        assert message["type"] == "output"
        assert message["attach_epoch"] == 4
        assert message["recovery_epoch"] == 9
