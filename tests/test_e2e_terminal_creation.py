"""
端到端 mock 测试：终端创建导致 Agent 断连问题。

测试架构：
  使用 InMemoryWebSocket 桥接 Agent 消息循环，验证终端创建失败时
  Agent 不会断开连接，后续消息仍能正常处理。

测试场景：
  A: 正常创建终端 — Agent 保持连接
  B: command 不存在 — Agent 不应断连，返回 terminal_closed
  C: cwd 不存在 — Agent 不应断连，返回 terminal_closed
  D: 连续创建 3 个正常终端 — Agent 保持连接
  E: 混合创建（1好+1坏+1好）— 只有坏的失败，Agent 不断连
  F: data 分支 write 抛 OSError — Agent 不断连
  G: resize 分支 resize 抛 OSError — Agent 不断连
  H: create_terminal 失败 + _send_ws_message 也失败 — Agent 不断连
"""
import asyncio
import base64
import json
import pytest
import pytest_asyncio
import sys
import os

# 添加路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agent'))

from app.websocket_client import WebSocketClient, TerminalRuntimeManager, TerminalSpec


# ─── Mock 组件 ──────────────────────────────────────────

class MockPTYWrapper:
    """模拟 PTYWrapper，根据 command/cwd 决定 start() 成功或失败。"""

    def __init__(self, command: str, args=None, config=None):
        self.command = command
        self.args = args or []
        self.config = config
        self._started = False
        self._stopped = False
        self._running = False
        self._exec_errno = None
        # 异常注入控制
        self.write_should_throw = False
        self.resize_should_throw = False

    @property
    def start_error(self):
        if self._exec_errno:
            return "No such file or directory"
        return None

    def start(self) -> bool:
        """根据 command 和 cwd 判断是否成功启动。"""
        if self.command == "nonexistent_cmd":
            self._exec_errno = 2  # ENOENT
            return False
        if self.config and hasattr(self.config, 'cwd') and self.config.cwd == "/nonexistent/path":
            self._exec_errno = 2  # ENOENT
            return False
        self._started = True
        self._running = True
        return True

    def stop(self):
        self._stopped = True
        self._running = False

    async def read(self):
        return None

    def write(self, data: bytes):
        if self.write_should_throw:
            raise OSError("Bad file descriptor")

    def resize(self, rows: int, cols: int):
        if self.resize_should_throw:
            raise OSError("ioctl failed: bad file descriptor")

    def is_running(self) -> bool:
        return self._running


class InMemoryWebSocket:
    """内存 WebSocket，用队列交叉连接模拟双向通信。"""

    def __init__(self):
        self._recv_queue: asyncio.Queue = asyncio.Queue()
        self._send_queue: asyncio.Queue = asyncio.Queue()
        self._closed = False

    async def send(self, message: str):
        if self._closed:
            raise Exception("WebSocket is closed")
        await self._send_queue.put(message)

    async def recv(self) -> str:
        if self._closed:
            raise Exception("WebSocket is closed")
        return await self._recv_queue.get()

    def close(self):
        self._closed = True

    def feed_message(self, message: dict):
        """向 recv 队列注入消息（模拟 Server 发给 Agent）。"""
        self._recv_queue.put_nowait(json.dumps(message))

    async def get_sent_message(self, timeout: float = 2.0) -> dict:
        """获取 Agent 发出的消息。"""
        raw = await asyncio.wait_for(self._send_queue.get(), timeout=timeout)
        return json.loads(raw)


# ─── 辅助函数 ──────────────────────────────────────────

def create_test_client() -> WebSocketClient:
    """创建测试用 WebSocketClient，注入 MockPTYWrapper。"""
    client = WebSocketClient(
        server_url="ws://test",
        token="test-token",
        command="/bin/bash",
        auto_reconnect=False,
    )
    client.runtime_manager = TerminalRuntimeManager(pty_factory=MockPTYWrapper)
    return client


# ─── Fixtures ──────────────────────────────────────────

@pytest_asyncio.fixture
async def agent_env():
    """创建 client + ws + 运行中的消息循环，测试结束后自动清理。"""
    client = create_test_client()
    ws = InMemoryWebSocket()
    client.ws = ws
    client._connected = True
    client._running = True
    loop_task = asyncio.create_task(client._websocket_to_pty())
    await asyncio.sleep(0.05)

    yield client, ws, loop_task

    client._running = False
    loop_task.cancel()
    try:
        await loop_task
    except asyncio.CancelledError:
        pass


# ─── 测试场景 ──────────────────────────────────────────

class TestTerminalCreationE2E:
    """端到端终端创建测试。"""

    @pytest.mark.asyncio
    async def test_scenario_a_normal_create(self, agent_env):
        """场景 A: 正常创建终端 — Agent 保持连接。"""
        client, ws, loop_task = agent_env

        ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-normal",
            "command": "/bin/bash",
            "cwd": "/tmp",
            "title": "Normal Terminal",
        })

        response = await ws.get_sent_message()
        assert response["type"] == "terminal_created"
        assert response["terminal_id"] == "term-normal"

        await asyncio.sleep(0.1)
        assert client._connected is True
        assert not loop_task.done()

    @pytest.mark.asyncio
    async def test_scenario_b_invalid_command(self, agent_env):
        """场景 B: command 不存在 — Agent 不应断连，返回 terminal_closed。"""
        client, ws, loop_task = agent_env

        ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-bad-cmd",
            "command": "nonexistent_cmd",
            "cwd": "/tmp",
            "title": "Bad Command",
        })

        response = await ws.get_sent_message(timeout=2.0)
        assert response["type"] == "terminal_closed"
        assert response["terminal_id"] == "term-bad-cmd"
        assert response["reason"] == "create_failed"

        # Agent 仍然连接
        await asyncio.sleep(0.1)
        assert client._connected is True
        assert not loop_task.done()

        # 后续消息正常处理
        ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-after-fail",
            "command": "/bin/bash",
            "cwd": "/tmp",
            "title": "After Fail",
        })
        response2 = await ws.get_sent_message(timeout=2.0)
        assert response2["type"] == "terminal_created"
        assert response2["terminal_id"] == "term-after-fail"

    @pytest.mark.asyncio
    async def test_scenario_c_invalid_cwd(self, agent_env):
        """场景 C: cwd 不存在 — Agent 不应断连，返回 terminal_closed。"""
        client, ws, loop_task = agent_env

        ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-bad-cwd",
            "command": "/bin/bash",
            "cwd": "/nonexistent/path",
            "title": "Bad CWD",
        })

        response = await ws.get_sent_message(timeout=2.0)
        assert response["type"] == "terminal_closed"
        assert response["terminal_id"] == "term-bad-cwd"

        await asyncio.sleep(0.1)
        assert client._connected is True
        assert not loop_task.done()

    @pytest.mark.asyncio
    async def test_scenario_d_multiple_creates(self, agent_env):
        """场景 D: 连续创建 3 个正常终端。"""
        client, ws, loop_task = agent_env

        for i in range(3):
            ws.feed_message({
                "type": "create_terminal",
                "terminal_id": f"term-{i}",
                "command": "/bin/bash",
                "cwd": "/tmp",
                "title": f"Terminal {i}",
            })

        for i in range(3):
            response = await ws.get_sent_message(timeout=2.0)
            assert response["type"] == "terminal_created"
            assert response["terminal_id"] == f"term-{i}"

        await asyncio.sleep(0.1)
        assert client._connected is True
        assert not loop_task.done()
        assert len(client.runtime_manager.list_terminals()) == 3

    @pytest.mark.asyncio
    async def test_scenario_e_mixed_good_bad_good(self, agent_env):
        """场景 E: 混合创建（1好+1坏+1好）— 只有坏的失败，Agent 不断连。"""
        client, ws, loop_task = agent_env

        # 1. 好的终端
        ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-good-1",
            "command": "/bin/bash",
            "cwd": "/tmp",
            "title": "Good 1",
        })
        resp1 = await ws.get_sent_message(timeout=2.0)
        assert resp1["type"] == "terminal_created"

        # 2. 坏的终端
        ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-bad",
            "command": "nonexistent_cmd",
            "cwd": "/tmp",
            "title": "Bad",
        })
        resp2 = await ws.get_sent_message(timeout=2.0)
        assert resp2["type"] == "terminal_closed"
        assert resp2["terminal_id"] == "term-bad"

        # 3. 再创建好的 — 关键验证
        ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-good-2",
            "command": "/bin/bash",
            "cwd": "/tmp",
            "title": "Good 2",
        })
        resp3 = await ws.get_sent_message(timeout=2.0)
        assert resp3["type"] == "terminal_created"

        await asyncio.sleep(0.1)
        assert client._connected is True
        assert not loop_task.done()

        terminals = client.runtime_manager.list_terminals()
        terminal_ids = [t.terminal_id for t in terminals]
        assert "term-good-1" in terminal_ids
        assert "term-good-2" in terminal_ids
        assert "term-bad" not in terminal_ids

    @pytest.mark.asyncio
    async def test_scenario_f_data_write_throws_oserror(self, agent_env):
        """场景 F: data 分支 write() 抛 OSError — Agent 不断连。"""
        client, ws, loop_task = agent_env

        # 先创建终端
        ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-write-fail",
            "command": "/bin/bash",
            "cwd": "/tmp",
            "title": "Write Fail",
        })
        resp = await ws.get_sent_message(timeout=2.0)
        assert resp["type"] == "terminal_created"

        # 注入 write 异常
        runtime = client.runtime_manager.get_terminal("term-write-fail")
        runtime.write_should_throw = True

        # 发送 data 消息
        payload = base64.b64encode(b"test input").decode("utf-8")
        ws.feed_message({
            "type": "data",
            "terminal_id": "term-write-fail",
            "payload": payload,
        })
        await asyncio.sleep(0.2)

        assert client._connected is True
        assert not loop_task.done()

        # 后续消息正常
        ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-after-write-fail",
            "command": "/bin/bash",
            "cwd": "/tmp",
            "title": "After Write Fail",
        })
        resp2 = await ws.get_sent_message(timeout=2.0)
        assert resp2["type"] == "terminal_created"

    @pytest.mark.asyncio
    async def test_scenario_g_resize_throws_oserror(self, agent_env):
        """场景 G: resize 分支 resize() 抛 OSError — Agent 不断连。"""
        client, ws, loop_task = agent_env

        ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-resize-fail",
            "command": "/bin/bash",
            "cwd": "/tmp",
            "title": "Resize Fail",
        })
        resp = await ws.get_sent_message(timeout=2.0)
        assert resp["type"] == "terminal_created"

        runtime = client.runtime_manager.get_terminal("term-resize-fail")
        runtime.resize_should_throw = True

        ws.feed_message({
            "type": "resize",
            "terminal_id": "term-resize-fail",
            "rows": 40,
            "cols": 120,
        })
        await asyncio.sleep(0.2)

        assert client._connected is True
        assert not loop_task.done()

        ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-after-resize-fail",
            "command": "/bin/bash",
            "cwd": "/tmp",
            "title": "After Resize Fail",
        })
        resp2 = await ws.get_sent_message(timeout=2.0)
        assert resp2["type"] == "terminal_created"

    @pytest.mark.asyncio
    async def test_scenario_h_create_fails_and_send_also_fails(self, agent_env):
        """场景 H: create_terminal 失败 + _send_ws_message 也失败 — Agent 不断连。"""
        client, ws, loop_task = agent_env

        # 只模拟 send 方向失败，recv 保持正常
        original_send = ws.send

        async def failing_send(message: str):
            raise OSError("Broken pipe")

        ws.send = failing_send

        ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-double-fail",
            "command": "nonexistent_cmd",
            "cwd": "/tmp",
            "title": "Double Fail",
        })
        await asyncio.sleep(0.3)

        # 恢复 send
        ws.send = original_send

        ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-after-double-fail",
            "command": "/bin/bash",
            "cwd": "/tmp",
            "title": "After Double Fail",
        })
        resp = await ws.get_sent_message(timeout=2.0)
        assert resp["type"] == "terminal_created"

        assert client._connected is True
        assert not loop_task.done()
