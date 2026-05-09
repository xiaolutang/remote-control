"""
S521: Agent _handle_reconnect 重连逻辑测试。

覆盖 S507 的重连逻辑：指数退避、耗尽判定、auto_reconnect 关闭等场景。
"""
import asyncio

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.transport.websocket_client import WebSocketClient, ReconnectExhausted


def _make_client(**overrides):
    """创建测试用 WebSocketClient 实例，默认 _running=True"""
    defaults = dict(
        server_url="wss://test.example.com",
        token="test-token",
        command="/bin/bash",
        auto_reconnect=True,
        max_retries=5,
        retry_delay=1.0,
    )
    defaults.update(overrides)
    client = WebSocketClient(**defaults)
    client._running = True  # 模拟运行状态
    return client


class TestHandleReconnectAutoReconnectDisabled:
    """auto_reconnect=False 或 _running=False 时直接返回 None"""

    @pytest.mark.asyncio
    async def test_returns_none_when_disabled(self):
        client = _make_client(auto_reconnect=False)
        result = await client._handle_reconnect()
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_not_running(self):
        client = _make_client()
        client._running = False
        result = await client._handle_reconnect()
        assert result is None


class TestHandleReconnectExhausted:
    """重连次数耗尽时返回 True 并清理"""

    @pytest.mark.asyncio
    async def test_returns_true_when_exhausted(self):
        client = _make_client(max_retries=3)
        client._retry_count = 3  # 等于 max_retries
        with patch.object(client, '_cleanup', new_callable=AsyncMock):
            result = await client._handle_reconnect()
        assert result is True

    @pytest.mark.asyncio
    async def test_calls_cleanup_with_network_lost(self):
        client = _make_client(max_retries=2)
        client._retry_count = 2
        with patch.object(client, '_cleanup', new_callable=AsyncMock) as mock_cleanup:
            result = await client._handle_reconnect()
        mock_cleanup.assert_called_once_with(network_lost=True)
        assert result is True

    @pytest.mark.asyncio
    async def test_exceeds_max_retries(self):
        client = _make_client(max_retries=3)
        client._retry_count = 10  # 远超 max_retries
        with patch.object(client, '_cleanup', new_callable=AsyncMock):
            result = await client._handle_reconnect()
        assert result is True


class TestHandleReconnectBackoff:
    """重连时指数退避 + 计数递增"""

    @pytest.mark.asyncio
    async def test_returns_none_and_increments(self):
        """正常重连返回 None，retry_count 递增"""
        client = _make_client(retry_delay=0.01)
        assert client._retry_count == 0
        with patch('app.transport.websocket_client.asyncio.sleep', new_callable=AsyncMock):
            result = await client._handle_reconnect()
        assert result is None
        assert client._retry_count == 1

    @pytest.mark.asyncio
    async def test_multiple_calls_increment_counter(self):
        """连续调用多次，计数持续递增"""
        client = _make_client(retry_delay=0.01, max_retries=10)
        with patch('app.transport.websocket_client.asyncio.sleep', new_callable=AsyncMock):
            for _ in range(5):
                await client._handle_reconnect()
        assert client._retry_count == 5

    @pytest.mark.asyncio
    async def test_delay_capped_at_max(self):
        """退避延迟不超过 _MAX_RETRY_DELAY (60s)"""
        import app.transport.websocket_client as ws_mod
        client = _make_client(retry_delay=1.0, max_retries=100)
        client._retry_count = 50  # 2^50 极大，应被 cap
        with patch('app.transport.websocket_client.asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            await client._handle_reconnect()
        actual_delay = mock_sleep.call_args[0][0]
        assert actual_delay <= ws_mod._MAX_RETRY_DELAY


class TestHandleReconnectBoundary:
    """边界：retry_count == max_retries - 1 时仍可重连"""

    @pytest.mark.asyncio
    async def test_one_retry_remaining(self):
        client = _make_client(max_retries=3, retry_delay=0.01)
        client._retry_count = 2  # 还剩 1 次
        with patch('app.transport.websocket_client.asyncio.sleep', new_callable=AsyncMock):
            result = await client._handle_reconnect()
        assert result is None  # 还能重连
        assert client._retry_count == 3

    @pytest.mark.asyncio
    async def test_exactly_at_max_returns_true(self):
        """retry_count 达到 max_retries 时返回 True"""
        client = _make_client(max_retries=3)
        client._retry_count = 3
        with patch.object(client, '_cleanup', new_callable=AsyncMock):
            result = await client._handle_reconnect()
        assert result is True


class TestHandleReconnectIntegration:
    """run() 方法集成：重连耗尽时抛出 ReconnectExhausted"""

    @pytest.mark.asyncio
    async def test_run_raises_exhausted_after_retries(self):
        """run() 在重连耗尽后抛出 ReconnectExhausted"""
        client = _make_client(max_retries=1, retry_delay=0.01)

        call_count = 0

        async def mock_connect_and_run():
            nonlocal call_count
            call_count += 1
            raise Exception("connection failed")

        client._connect_and_run = mock_connect_and_run
        client._start_local_server = AsyncMock()
        client._cleanup = AsyncMock()

        with patch('app.transport.websocket_client.asyncio.sleep', new_callable=AsyncMock):
            with pytest.raises(ReconnectExhausted) as exc_info:
                await client.run()

        assert exc_info.value.retry_count >= 1
        assert call_count >= 1
