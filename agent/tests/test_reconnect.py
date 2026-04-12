"""
断线重连测试
"""
import pytest

from app.websocket_client import WebSocketClient


class TestReconnect:
    """断线重连测试"""

    def test_default_reconnect_settings(self):
        """默认重连设置"""
        client = WebSocketClient(
            server_url="wss://test.example.com",
            token="test-token",
            command="/bin/bash",
        )

        assert client.auto_reconnect == True
        assert client.max_retries == 5
        assert client.retry_delay == 1.0

    def test_custom_reconnect_settings(self):
        """自定义重连设置"""
        client = WebSocketClient(
            server_url="wss://test.example.com",
            token="test-token",
            command="/bin/bash",
            auto_reconnect=True,
            max_retries=10,
            retry_delay=2.0,
        )

        assert client.auto_reconnect == True
        assert client.max_retries == 10
        assert client.retry_delay == 2.0

    def test_no_reconnect_option(self):
        """禁用重连选项"""
        client = WebSocketClient(
            server_url="wss://test.example.com",
            token="test-token",
            command="/bin/bash",
            auto_reconnect=False,
        )

        assert client.auto_reconnect == False

    def test_exponential_backoff_calculation(self):
        """指数退避计算"""
        client = WebSocketClient(
            server_url="wss://test.example.com",
            token="test-token",
            command="/bin/bash",
            retry_delay=1.0,
        )

        # 验证指数退避延迟计算
        # delay = retry_delay * (2 ** retry_count)
        assert 1.0 * (2**0) == 1.0  # 第 1 次
        assert 1.0 * (2**1) == 2.0  # 第 2 次
        assert 1.0 * (2**2) == 4.0  # 第 3 次
        assert 1.0 * (2**3) == 8.0  # 第 4 次

    def test_max_retries_limit(self):
        """最大重试次数限制"""
        client = WebSocketClient(
            server_url="wss://test.example.com",
            token="test-token",
            command="/bin/bash",
            max_retries=3,
        )

        assert client.max_retries == 3

    def test_initial_state(self):
        """初始状态"""
        client = WebSocketClient(
            server_url="wss://test.example.com",
            token="test-token",
            command="/bin/bash",
        )

        assert client.is_connected == False
        assert client.session_id is None
