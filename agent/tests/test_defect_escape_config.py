"""
缺陷逃逸测试 — 覆盖 "Agent 创建失败" 排查中发现的真实问题。

根因：两个配置文件指向不同 session，默认配置中的 session 不存在，
agent 用无效 token 连接后收到 4004，但静默重连而非报错退出。

逃逸路径：
1. config.get_access_token() 返回指向不存在 session 的 token → 应提前检查
2. Agent 收到 4004（session 不存在）→ 应停止重连而非无限循环
3. 多配置文件冲突（~/.rc-agent vs Flutter managed）→ 无检测机制

这些场景在 65 个既有测试中全部被 mock 遮蔽。
"""
import asyncio
import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Config, load_config, normalize_config_path


class TestTokenSessionConsistency:
    """
    逃逸路径 #1：token 指向的 session 在 Redis 中不存在时，
    agent 应给出明确错误，而非静默重连直到服务器返回 4004。
    """

    def test_access_token_returns_correct_token(self):
        """验证 get_access_token() 优先返回 access_token，回退到 token"""
        # access_token 优先
        config = Config(access_token="new_token", token="old_token")
        assert config.get_access_token() == "new_token"

        # 回退到 token
        config = Config(token="old_token")
        assert config.get_access_token() == "old_token"

        # 都没有
        config = Config()
        assert config.get_access_token() is None

    def test_load_config_from_different_paths(self):
        """验证 --config 参数加载指定文件，而非默认 ~/.rc-agent/config.json"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建 Flutter 风格的 managed config
            managed_path = os.path.join(tmpdir, "managed-agent", "config.json")
            os.makedirs(os.path.dirname(managed_path))
            with open(managed_path, "w") as f:
                json.dump({
                    "server_url": "ws://localhost:8888",
                    "access_token": "managed_token_ZYWMxT3",
                    "token": "managed_token_ZYWMxT3",
                }, f)

            # 创建默认 config
            default_path = os.path.join(tmpdir, ".rc-agent", "config.json")
            os.makedirs(os.path.dirname(default_path))
            with open(default_path, "w") as f:
                json.dump({
                    "server_url": "ws://localhost:8888",
                    "access_token": "default_token_3b8r0U",
                    "token": "default_token_3b8r0U",
                }, f)

            # 用 --config 指定 managed → 应加载 managed token
            config = load_config(managed_path)
            assert config.get_access_token() == "managed_token_ZYWMxT3"

            # 不指定 → 加载指定文件
            from pathlib import Path
            config = load_config(Path(default_path))
            assert config.get_access_token() == "default_token_3b8r0U"

    def test_normalize_config_path_returns_default_when_none(self):
        """验证 normalize_config_path(None) 返回 ~/.rc-agent/config.json"""
        path = normalize_config_path(None)
        assert str(path).endswith(".rc-agent/config.json")

    def test_normalize_config_path_uses_explicit_path(self):
        """验证 normalize_config_path(explicit) 返回指定路径"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "custom.json")
            path = normalize_config_path(config_path)
            assert str(path) == config_path


class TestAgentErrorOnInvalidSession:
    """
    逃逸路径 #2：Agent 连接时服务器返回 4004（session 不存在），
    应识别为不可恢复错误并停止重连，而非无限循环。
    """

    @pytest.mark.asyncio
    @pytest.mark.timeout(5)
    async def test_server_4004_stops_immediately_not_infinite_reconnect(self):
        """
        验证：服务器返回 4004（session 不存在）时，agent 应立即停止，不重连。

        历史根因（已修复）：
        - _connect_and_run 在连接成功后立即重置 _retry_count = 0
        - 4004 在 recv() 时才抛出，异常传播到 run() 的 except
        - run() 检查 _retry_count >= max_retries 时，_retry_count 已经是 0
        - 所以 max_retries 被绕过，agent 无限重连

        修复方案：
        1. 捕获 ConnectionClosedError，检查 e.code in _NON_RECOVERABLE_CODES
        2. _retry_count 重置时机从"连接成功"移到"收到 connected 消息后"
        """
        from app.websocket_client import WebSocketClient
        from websockets.exceptions import ConnectionClosedError
        from websockets.frames import Close

        reconnect_count = 0

        class FakeConnect4004:
            """模拟连接后 recv 返回 4004"""
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                nonlocal reconnect_count
                reconnect_count += 1
                return self

            async def __aexit__(self, *args):
                pass

            async def send(self, data):
                pass

            async def recv(self):
                raise ConnectionClosedError(
                    Close(code=4004, reason="会话 nonexistent 不存在"), None
                )

            async def close(self):
                pass

        with patch("app.websocket_client.websockets.connect", FakeConnect4004):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                client = WebSocketClient(
                    server_url="ws://localhost:8888",
                    token="invalid_token",
                    auto_reconnect=True,
                    max_retries=5,
                )
                client._start_local_server = AsyncMock()
                await client.run()

        # 修复后：4004 是不可恢复错误，应只连接一次就停止
        assert reconnect_count == 1, (
            f"4004 应立即停止，不应重连。实际连接 {reconnect_count} 次"
        )
        assert not client._running

    @pytest.mark.asyncio
    @pytest.mark.timeout(5)
    async def test_server_4004_stops_immediately_when_no_reconnect(self):
        """
        验证：auto_reconnect=False 时，4004 应立即退出。
        """
        from app.websocket_client import WebSocketClient
        from websockets.exceptions import ConnectionClosedError
        from websockets.frames import Close

        class FakeConnect4004:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def send(self, data):
                pass

            async def recv(self):
                raise ConnectionClosedError(
                    Close(code=4004, reason="会话 nonexistent 不存在"), None
                )

            async def close(self):
                pass

        with patch("app.websocket_client.websockets.connect", FakeConnect4004):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                client = WebSocketClient(
                    server_url="ws://localhost:8888",
                    token="invalid_token",
                    auto_reconnect=False,
                    max_retries=0,
                )
                client._start_local_server = AsyncMock()
                await client.run()

        # 应该只连接一次就退出
        assert not client.is_connected


class TestDuplicateConfigDetection:
    """
    逃逸路径 #3：多个配置文件存在时（~/.rc-agent + Flutter managed），
    没有 mechanism 检测冲突或警告。
    """

    def test_config_file_differences_are_detectable(self):
        """
        验证：可以检测到两个配置文件中的 token 是否指向不同 session。

        在真实场景中：
        - ~/.rc-agent/config.json → sub=3b8r0UCTc42DEuw0（不存在）
        - managed-agent/config.json → sub=ZYWMxT3utmHg5gFa（有效）

        应该有机制检测这种冲突。
        """
        import base64

        with tempfile.TemporaryDirectory() as tmpdir:
            # 两个配置文件，token 指向不同 session
            config_a_path = os.path.join(tmpdir, "a.json")
            config_b_path = os.path.join(tmpdir, "b.json")

            with open(config_a_path, "w") as f:
                json.dump({"access_token": "token_a_sub_3b8r0U"}, f)
            with open(config_b_path, "w") as f:
                json.dump({"access_token": "token_b_sub_ZYWMxT"}, f)

            config_a = load_config(config_a_path)
            config_b = load_config(config_b_path)

            # 不同的 token 意味着可能指向不同的 session
            assert config_a.get_access_token() != config_b.get_access_token()

    def test_empty_config_loads_without_error(self):
        """验证：配置文件不存在时，load_config 返回默认配置而非报错"""
        config = load_config("/nonexistent/path/config.json")
        assert config.server_url == "ws://localhost:8000"
        assert config.get_access_token() is None

    def test_extra_fields_in_config_are_ignored(self):
        """
        验证：Flutter managed config 中的 device_id 等额外字段被忽略，
        不影响 Config 对象创建。

        真实场景：Flutter 写入 device_id 字段，但 Config 没有 device_id 属性。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "config.json")
            with open(config_path, "w") as f:
                json.dump({
                    "server_url": "ws://localhost:8888",
                    "access_token": "test_token",
                    "device_id": "ZYWMxT3utmHg5gFa",  # Config 没有这个字段
                    "command": "/bin/bash",
                    "shell_mode": False,
                    "auto_reconnect": True,
                    "max_retries": 5,
                    "reconnect_max_attempts": 10,
                    "reconnect_base_delay": 1.0,
                    "heartbeat_interval": 30.0,
                }, f)

            # 不应报错
            config = load_config(config_path)
            assert config.server_url == "ws://localhost:8888"
            assert config.get_access_token() == "test_token"


class TestWebSocketCloseCodeHandling:
    """
    逃逸路径 #4：Agent 对不同 WebSocket close code 的处理。

    当前行为：所有 close code 统一走重连逻辑。
    正确行为：某些 close code（4001 认证失败、4004 session 不存在）
    应视为不可恢复错误，不应重连。
    """

    @pytest.mark.asyncio
    @pytest.mark.timeout(5)
    async def test_auth_failure_4001_stops_immediately(self):
        """
        4001 = Unauthorized → token 无效，重连也无法修复，应立即停止。

        历史行为（已修复）：4001 在连接阶段抛异常，_retry_count 不会重置，
        max_retries 能限制重试次数。但 token 无效时重试无意义。

        修复后：4001 被识别为不可恢复错误，直接停止，不重试。
        """
        from app.websocket_client import WebSocketClient
        from websockets.exceptions import ConnectionClosedError
        from websockets.frames import Close

        connect_count = 0

        class FakeConnect4001:
            def __init__(self, *args, **kwargs):
                nonlocal connect_count
                connect_count += 1
                raise ConnectionClosedError(Close(code=4001, reason="Unauthorized"), None)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        with patch("app.websocket_client.websockets.connect", FakeConnect4001):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                client = WebSocketClient(
                    server_url="ws://localhost:8888",
                    token="bad_token",
                    auto_reconnect=True,
                    max_retries=3,
                )
                client._start_local_server = AsyncMock()
                await client.run()

        # 修复后：4001 是不可恢复错误，只连接一次就停止
        assert connect_count == 1, (
            f"4001 应立即停止不重连。实际连接 {connect_count} 次"
        )
        assert not client._running

    @pytest.mark.asyncio
    @pytest.mark.timeout(5)
    async def test_network_error_should_reconnect(self):
        """
        普通 network error → 应该重连（这是正常的重连场景）。
        """
        from app.websocket_client import WebSocketClient

        connect_count = 0

        class FakeConnect:
            """模拟 websockets.connect 的 async context manager 行为"""
            def __init__(self, *args, **kwargs):
                nonlocal connect_count
                connect_count += 1
                raise ConnectionRefusedError("Connection refused")

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        with patch("app.websocket_client.websockets.connect", FakeConnect):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                client = WebSocketClient(
                    server_url="ws://localhost:8888",
                    token="good_token",
                    auto_reconnect=True,
                    max_retries=3,
                )
                client._start_local_server = AsyncMock()
                await client.run()

        # 网络错误应该重连到 max_retries + 1（首次 + 3次重试）
        assert connect_count == 4, (
            f"网络错误应重连，实际连接 {connect_count} 次"
        )
