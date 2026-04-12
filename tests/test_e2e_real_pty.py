"""
真实 PTY 端到端测试 — 用真实 PTYWrapper 定位 Agent 断连问题。

测试架构：
  使用 InMemoryWebSocket 桥接 Agent 消息循环，
  但 PTY 使用真实的 PTYWrapper（os.fork + os.execvpe）。

目的：
  之前的 MockPTYWrapper 测试全部通过，但真实环境仍然断连。
  本测试用真实 PTY 复现问题。
"""
import asyncio
import base64
import json
import os
import signal
import pytest
import pytest_asyncio
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agent'))

from app.websocket_client import WebSocketClient, TerminalRuntimeManager, TerminalSpec
from app.pty_wrapper import PTYWrapper


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

    async def get_sent_message(self, timeout: float = 5.0) -> dict:
        """获取 Agent 发出的消息。"""
        raw = await asyncio.wait_for(self._send_queue.get(), timeout=timeout)
        return json.loads(raw)

    async def get_all_sent_messages(self, timeout: float = 3.0) -> list[dict]:
        """获取所有待处理的消息。"""
        messages = []
        while True:
            try:
                raw = await asyncio.wait_for(self._send_queue.get(), timeout=0.5)
                messages.append(json.loads(raw))
            except asyncio.TimeoutError:
                break
        return messages


def create_real_pty_client() -> WebSocketClient:
    """创建使用真实 PTYWrapper 的 WebSocketClient。"""
    client = WebSocketClient(
        server_url="ws://test",
        token="test-token",
        command="/bin/bash",
        auto_reconnect=False,
    )
    client.runtime_manager = TerminalRuntimeManager(pty_factory=PTYWrapper)
    return client


@pytest_asyncio.fixture
async def agent_env_real():
    """创建 client + ws + 运行中的消息循环（使用真实 PTY），测试结束后自动清理。"""
    client = create_real_pty_client()
    ws = InMemoryWebSocket()
    client.ws = ws
    client._connected = True
    client._running = True

    # 启动主 PTY（真实 /bin/bash）
    client.pty = PTYWrapper("/bin/bash")
    assert client.pty.start(), "主 PTY 启动失败"

    loop_task = asyncio.create_task(client._websocket_to_pty())
    await asyncio.sleep(0.1)

    yield client, ws, loop_task

    # 清理
    client._running = False
    loop_task.cancel()
    try:
        await loop_task
    except asyncio.CancelledError:
        pass

    # 清理所有 PTY
    for task in list(client._runtime_tasks.values()):
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    client.runtime_manager.close_all()
    if client.pty:
        client.pty.stop()


class TestRealPTYTerminalCreation:
    """使用真实 PTYWrapper 的端到端测试。"""

    @pytest.mark.asyncio
    async def test_real_bash_terminal_create(self, agent_env_real):
        """真实场景：创建 /bin/bash 终端 — 验证 Agent 不断连。"""
        client, ws, loop_task = agent_env_real

        ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-real-bash",
            "command": "/bin/bash",
            "cwd": "/tmp",
            "title": "Real Bash",
        })

        # 等待响应
        response = await ws.get_sent_message(timeout=5.0)
        print(f"[TEST] Got response: {response}")
        assert response["type"] == "terminal_created"
        assert response["terminal_id"] == "term-real-bash"

        # 验证 Agent 仍然连接
        await asyncio.sleep(0.5)
        assert client._connected is True, "Agent 不应该断连！"
        assert not loop_task.done(), f"消息循环不应结束！state={loop_task}"

        # 清理终端
        ws.feed_message({
            "type": "close_terminal",
            "terminal_id": "term-real-bash",
        })

    @pytest.mark.asyncio
    async def test_real_tilde_cwd_terminal(self, agent_env_real):
        """真实场景：cwd 使用 ~/project（波浪号未展开）— 这可能是真实用户场景。"""
        client, ws, loop_task = agent_env_real

        ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-tilde-cwd",
            "command": "/bin/bash",
            "cwd": "~/project",
            "title": "Tilde CWD",
        })

        # 收集所有响应
        messages = await ws.get_all_sent_messages(timeout=5.0)
        print(f"[TEST] Got messages ({len(messages)}):")
        for msg in messages:
            print(f"  {msg.get('type')}: terminal_id={msg.get('terminal_id', 'N/A')}")

        # 验证 Agent 仍然连接
        await asyncio.sleep(1.0)
        assert client._connected is True, f"Agent 不应该断连！messages={messages}"
        assert not loop_task.done(), f"消息循环不应结束！"

    @pytest.mark.asyncio
    async def test_real_nonexistent_command(self, agent_env_real):
        """真实场景：command 不存在 — PTYWrapper.start() 的真实行为。"""
        client, ws, loop_task = agent_env_real

        ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-no-cmd",
            "command": "nonexistent_cmd_12345",
            "cwd": "/tmp",
            "title": "No Command",
        })

        # 收集所有响应
        messages = await ws.get_all_sent_messages(timeout=5.0)
        print(f"[TEST] Got messages ({len(messages)}):")
        for msg in messages:
            print(f"  {msg.get('type')}: terminal_id={msg.get('terminal_id', 'N/A')}")

        # 真实 PTYWrapper.start() 中 fork 总是成功，所以 terminal_created 会被发送
        # 但子进程会立即退出（execvpe 失败）
        has_created = any(m["type"] == "terminal_created" for m in messages)
        has_closed = any(m["type"] == "terminal_closed" and m.get("terminal_id") == "term-no-cmd" for m in messages)

        print(f"[TEST] has_created={has_created}, has_closed={has_closed}")

        # 验证 Agent 仍然连接
        await asyncio.sleep(1.0)
        assert client._connected is True, f"Agent 不应该断连！messages={messages}"
        assert not loop_task.done(), f"消息循环不应结束！"

    @pytest.mark.asyncio
    async def test_real_nonexistent_cwd(self, agent_env_real):
        """真实场景：cwd 不存在 — os.chdir() 在子进程中失败。"""
        client, ws, loop_task = agent_env_real

        ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-no-cwd",
            "command": "/bin/bash",
            "cwd": "/nonexistent/path/12345",
            "title": "No CWD",
        })

        messages = await ws.get_all_sent_messages(timeout=5.0)
        print(f"[TEST] Got messages ({len(messages)}):")
        for msg in messages:
            print(f"  {msg.get('type')}: terminal_id={msg.get('terminal_id', 'N/A')}")

        await asyncio.sleep(1.0)
        assert client._connected is True, f"Agent 不应该断连！messages={messages}"
        assert not loop_task.done(), f"消息循环不应结束！"

    @pytest.mark.asyncio
    async def test_real_mixed_create(self, agent_env_real):
        """真实场景：连续创建 1 个正常 + 1 个异常 + 1 个正常。"""
        client, ws, loop_task = agent_env_real

        # 1. 正常终端
        ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-good-1",
            "command": "/bin/bash",
            "cwd": "/tmp",
            "title": "Good 1",
        })

        await asyncio.sleep(1.0)
        messages_1 = await ws.get_all_sent_messages(timeout=3.0)
        print(f"[TEST] After good-1: {len(messages_1)} messages")
        for msg in messages_1:
            print(f"  {msg.get('type')}: terminal_id={msg.get('terminal_id', 'N/A')}")

        assert client._connected is True, "Agent 在第一个终端后断连了！"

        # 2. 异常终端（波浪号 cwd）
        ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-bad-tilde",
            "command": "/bin/bash",
            "cwd": "~/nonexistent_dir",
            "title": "Bad Tilde",
        })

        await asyncio.sleep(1.0)
        messages_2 = await ws.get_all_sent_messages(timeout=3.0)
        print(f"[TEST] After bad-tilde: {len(messages_2)} messages")
        for msg in messages_2:
            print(f"  {msg.get('type')}: terminal_id={msg.get('terminal_id', 'N/A')}")

        assert client._connected is True, "Agent 在异常终端后断连了！"

        # 3. 再创建正常终端 — 关键验证
        ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-good-2",
            "command": "/bin/bash",
            "cwd": "/tmp",
            "title": "Good 2",
        })

        await asyncio.sleep(1.0)
        messages_3 = await ws.get_all_sent_messages(timeout=3.0)
        print(f"[TEST] After good-2: {len(messages_3)} messages")
        for msg in messages_3:
            print(f"  {msg.get('type')}: terminal_id={msg.get('terminal_id', 'N/A')}")

        assert client._connected is True, "Agent 在第三个终端后断连了！"
        assert not loop_task.done(), "消息循环不应结束！"

        has_good2_created = any(
            m["type"] == "terminal_created" and m.get("terminal_id") == "term-good-2"
            for m in messages_3
        )
        assert has_good2_created, f"第三个终端应该创建成功！messages_3={messages_3}"

    @pytest.mark.asyncio
    async def test_real_data_write_after_create(self, agent_env_real):
        """真实场景：创建终端后发送输入数据 — 验证 data 分支正常。"""
        client, ws, loop_task = agent_env_real

        ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-data-test",
            "command": "/bin/bash",
            "cwd": "/tmp",
            "title": "Data Test",
        })

        await asyncio.sleep(0.5)
        messages = await ws.get_all_sent_messages(timeout=2.0)
        assert any(m["type"] == "terminal_created" for m in messages), f"terminal_created not found in {messages}"

        # 发送数据
        payload = base64.b64encode(b"echo hello\n").decode("utf-8")
        ws.feed_message({
            "type": "data",
            "terminal_id": "term-data-test",
            "payload": payload,
        })

        await asyncio.sleep(1.0)
        # Agent 应该仍然连接
        assert client._connected is True, "Agent 在发送数据后断连了！"
        assert not loop_task.done(), "消息循环不应结束！"

    @pytest.mark.asyncio
    async def test_real_resize_after_create(self, agent_env_real):
        """真实场景：创建终端后调整大小 — 验证 resize 分支正常。"""
        client, ws, loop_task = agent_env_real

        ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-resize-test",
            "command": "/bin/bash",
            "cwd": "/tmp",
            "title": "Resize Test",
        })

        await asyncio.sleep(0.5)
        messages = await ws.get_all_sent_messages(timeout=2.0)
        assert any(m["type"] == "terminal_created" for m in messages)

        ws.feed_message({
            "type": "resize",
            "terminal_id": "term-resize-test",
            "rows": 40,
            "cols": 120,
        })

        await asyncio.sleep(0.5)
        assert client._connected is True, "Agent 在 resize 后断连了！"
        assert not loop_task.done(), "消息循环不应结束！"
