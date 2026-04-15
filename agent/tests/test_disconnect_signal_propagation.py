"""
断连信号传播测试

验证当任一并行任务检测到连接断开时，会设置 _connected = False，
使其他任务（如 _pty_to_websocket）能退出循环，避免 asyncio.gather 死锁。

关联缺陷: DF-20260416-01 — 服务器重启后 Agent 收到 1012 永久挂起
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import websockets.exceptions

from app.websocket_client import WebSocketClient


def _make_client():
    """创建用于测试的 WebSocketClient"""
    return WebSocketClient(
        server_url="ws://test.example.com",
        token="test-token",
        command="/bin/bash",
    )


class TestDisconnectSignalPropagation:
    """断连信号传播 — 任务退出时设置 _connected=False"""

    @pytest.mark.asyncio
    async def test_websocket_recv_error_sets_connected_false(self):
        """_websocket_to_pty 收到异常后设置 _connected=False"""
        client = _make_client()
        client._running = True
        client._connected = True
        client.ws = MagicMock()
        client.ws.recv = AsyncMock(side_effect=Exception("Connection closed"))

        await client._websocket_to_pty()

        assert client._connected is False

    @pytest.mark.asyncio
    async def test_heartbeat_error_sets_connected_false(self):
        """_heartbeat_loop 发送失败后设置 _connected=False"""
        client = _make_client()
        client._running = True
        client._connected = True
        client.ws = MagicMock()
        client._send_ws_message = AsyncMock(side_effect=Exception("send failed"))

        await client._heartbeat_loop()

        assert client._connected is False

    @pytest.mark.asyncio
    async def test_pty_to_ws_send_failure_propagates_disconnect(self):
        """_pty_to_websocket WS 发送失败时传播断连信号"""
        client = _make_client()
        client._running = True
        client._connected = True
        client.pty = MagicMock()

        async def mock_read():
            return b"test data"

        client.pty.read = mock_read
        # 模拟 WS ConnectionClosed
        closed_err = websockets.exceptions.ConnectionClosedError(
            rcvd=None, sent=None
        )
        client._send_ws_message = AsyncMock(side_effect=closed_err)

        await client._pty_to_websocket()

        assert client._connected is False

    @pytest.mark.asyncio
    async def test_pty_local_error_does_not_propagate_disconnect(self):
        """_pty_to_websocket PTY 本地读取失败时不传播断连信号"""
        client = _make_client()
        client._running = True
        client._connected = True
        client.pty = MagicMock()

        # PTY 读取异常（本地错误，非网络断连）
        client.pty.read = AsyncMock(side_effect=OSError("PTY read error"))

        await client._pty_to_websocket()

        # 本地 PTY 错误不应设置 _connected=False
        assert client._connected is True

    @pytest.mark.asyncio
    async def test_pty_read_exits_when_connected_false(self):
        """_pty_to_websocket 在 _connected=False 后退出循环"""
        client = _make_client()
        client._running = True
        client._connected = True
        client.pty = MagicMock()

        call_count = 0

        async def mock_read():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return b"test data"
            # 模拟断连信号传播：在第二次读取前 _connected 被其他任务设为 False
            client._connected = False
            return None

        client.pty.read = mock_read
        client._send_ws_message = AsyncMock()

        await client._pty_to_websocket()

        # 应该在第二次循环时因 _connected=False 而退出
        assert call_count <= 3  # 不会无限循环

    @pytest.mark.asyncio
    async def test_gather_completes_after_disconnect_signal(self):
        """asyncio.gather 在断连信号传播后能完成（不阻塞）"""
        client = _make_client()
        client._running = True
        client._connected = True
        client.pty = MagicMock()
        client.ws = MagicMock()
        client.local_display = False

        # _websocket_to_pty: 第一次 recv 就失败，设 _connected=False
        client.ws.recv = AsyncMock(side_effect=Exception("Connection closed"))
        client.pty.read = AsyncMock(return_value=None)
        client._send_ws_message = AsyncMock(side_effect=Exception("closed"))

        tasks = [
            asyncio.create_task(client._pty_to_websocket()),
            asyncio.create_task(client._websocket_to_pty()),
            asyncio.create_task(client._heartbeat_loop()),
        ]

        # gather 应该在合理时间内完成（不会因为 PTY 任务阻塞而死锁）
        done, pending = await asyncio.wait(
            tasks, timeout=5.0, return_when=asyncio.ALL_COMPLETED
        )

        # 所有任务应该完成
        for task in tasks:
            assert task.done(), f"Task {task.get_name()} did not complete"

    @pytest.mark.asyncio
    async def test_connect_and_run_gather_unblocks_on_ws_disconnect(self):
        """真实 _connect_and_run() 中 gather 在 WS 断连后解除阻塞"""
        client = _make_client()
        client._running = True
        client.auto_reconnect = True
        client.max_retries = 3
        client.retry_delay = 0.01
        client.local_display = False

        # Mock PTY
        mock_pty = MagicMock()
        mock_pty.read = AsyncMock(return_value=None)
        mock_pty.stop = MagicMock()

        # Mock websockets.connect — 返回 async context manager
        mock_ws = MagicMock()
        mock_ws.close = AsyncMock()

        call_count = 0

        async def recv_with_auth():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return '{"type": "connected", "session_id": "test-session"}'
            raise Exception("Connection closed")

        mock_ws.recv = recv_with_auth
        mock_ws.send = AsyncMock()

        class _FakeConnectCM:
            async def __aenter__(self_inner):
                return mock_ws
            async def __aexit__(self_inner, *a):
                pass

        client._start_local_server = AsyncMock()

        # _send_ws_message: 前 N 次成功（auth + metadata），之后失败（模拟 WS 断连）
        send_count = 0

        async def send_with_eventual_failure(msg):
            nonlocal send_count
            send_count += 1
            # 允许前 5 次发送成功（auth AES key + metadata + pong 等）
            if send_count <= 5:
                return
            raise Exception("Connection closed")

        # 所有 patch 必须在同一 with 块内生效
        p1 = patch('app.websocket_client.websockets.connect', return_value=_FakeConnectCM())
        p2 = patch('app.websocket_client.agent_crypto')
        p3 = patch.object(client, '_send_ws_message', side_effect=send_with_eventual_failure)
        p4 = patch('app.websocket_client.PTYWrapper', return_value=mock_pty)

        with p1, p2 as mock_crypto, p3, p4:
            mock_crypto.has_public_key = True
            mock_crypto.generate_aes_key = MagicMock()
            mock_crypto.get_encrypted_aes_key_b64 = MagicMock(return_value="fake_key")
            mock_crypto.clear_aes_key = MagicMock()

            # Run with timeout — if gather blocks, this will timeout
            await asyncio.wait_for(client._connect_and_run(), timeout=5.0)

        # _connect_and_run should have returned (not hung on gather)
        assert client._connected is False
