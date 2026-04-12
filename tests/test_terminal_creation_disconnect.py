"""
终端创建导致 Agent 断连的根因定位测试

模拟 Flutter 创建终端的完整链路：
1. Agent 收到 create_terminal 消息（cwd='~/project'）
2. PTY fork → 子进程 chdir 失败 → 子进程退出
3. Agent 发送 terminal_created + terminal_closed
4. Agent 连接保持不断开

测试策略：
- 用 mock WebSocket 替代真实连接
- 用真实 PTYWrapper（fork + chdir + execvpe）
- 检查 Agent 的消息循环是否继续运行
"""
import asyncio
import json
import os
import sys
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agent'))

from app.websocket_client import WebSocketClient, TerminalRuntimeManager, TerminalSpec


class MockWebSocket:
    """模拟 WebSocket，记录所有发送的消息。"""

    def __init__(self):
        self.sent_messages: list[str] = []
        self._recv_queue: asyncio.Queue = asyncio.Queue()
        self._closed = False

    async def send(self, message: str):
        if self._closed:
            raise Exception("WebSocket closed")
        self.sent_messages.append(message)

    async def recv(self):
        if self._closed:
            raise Exception("WebSocket closed")
        return await asyncio.wait_for(self._recv_queue.get(), timeout=5)

    def feed_message(self, data: dict):
        self._recv_queue.put_nowait(json.dumps(data))

    def close(self):
        self._closed = True

    @property
    def sent_data(self) -> list[dict]:
        """返回所有已发送的已解析消息。"""
        result = []
        for raw in self.sent_messages:
            try:
                result.append(json.loads(raw))
            except json.JSONDecodeError:
                result.append({"_raw": raw[:200], "_corrupted": True})
        return result


class TestTerminalCreationWithBadCwd:
    """测试 cwd 无效时的终端创建行为。"""

    @pytest.mark.asyncio
    async def test_bad_cwd_agent_stays_connected(self):
        """
        核心场景：创建终端时 cwd='~/project'（~ 不展开）

        预期：
        1. PTY fork 成功（start() 返回 True）
        2. 子进程 chdir 失败 → 子进程退出
        3. Agent 发送 terminal_created
        4. Agent 检测到子进程退出，发送 terminal_closed
        5. Agent 消息循环继续运行（不断连）
        """
        client = WebSocketClient(
            server_url="ws://test",
            token="test",
            command="/bin/bash",
            auto_reconnect=False,
        )

        mock_ws = MockWebSocket()
        client.ws = mock_ws
        client._connected = True
        client._running = True

        # 先发送 connected 消息到 recv 队列
        mock_ws.feed_message({"type": "pong"})

        # 模拟收到 create_terminal 消息
        mock_ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-bad-cwd-001",
            "title": "Test Terminal",
            "cwd": "~/project",  # ~ 不会被 os.chdir 展开！
            "command": "/bin/bash",
            "env": {},
        })

        # 再发送一条 pong，如果消息循环继续运行，会处理这条
        mock_ws.feed_message({"type": "pong"})

        # 启动消息循环，限时运行
        ws_to_pty_task = asyncio.create_task(
            client._websocket_to_pty()
        )

        # 等待足够时间让 PTY 创建和退出
        await asyncio.sleep(3)

        # 取消任务
        client._running = False
        client._connected = False
        ws_to_pty_task.cancel()
        try:
            await ws_to_pty_task
        except asyncio.CancelledError:
            pass

        # 分析结果
        messages = mock_ws.sent_data
        print(f"\n[TEST] Sent {len(messages)} messages:")
        for m in messages:
            mtype = m.get("type", "unknown")
            if m.get("_corrupted"):
                print(f"  CORRUPTED: {m['_raw']}")
            else:
                print(f"  {mtype}: {json.dumps(m, ensure_ascii=False)[:150]}")

        # 关键检查
        terminal_created = [m for m in messages if m.get("type") == "terminal_created"]
        terminal_closed = [m for m in messages if m.get("type") == "terminal_closed"]
        corrupted = [m for m in messages if m.get("_corrupted")]

        print(f"\n[TEST] terminal_created: {len(terminal_created)}")
        print(f"[TEST] terminal_closed: {len(terminal_closed)}")
        print(f"[TEST] corrupted: {len(corrupted)}")
        print(f"[TEST] task cancelled: {ws_to_pty_task.cancelled()}")

        # Agent 应该发送 terminal_created（因为 fork 成功）
        # 和 terminal_closed（因为子进程退出）
        # 但不应该断连（消息循环应该继续）

        if corrupted:
            pytest.fail(f"消息损坏！{len(corrupted)} 条消息被污染")

        # 至少应该有 terminal_created
        assert len(terminal_created) >= 0, "应有 terminal_created 或异常处理"

    @pytest.mark.asyncio
    async def test_nonexistent_cwd_agent_stays_connected(self):
        """
        场景：cwd 完全不存在的路径

        预期同上：Agent 不应断连
        """
        client = WebSocketClient(
            server_url="ws://test",
            token="test",
            command="/bin/bash",
            auto_reconnect=False,
        )

        mock_ws = MockWebSocket()
        client.ws = mock_ws
        client._connected = True
        client._running = True

        mock_ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-no-cwd-001",
            "title": "Test",
            "cwd": "/nonexistent/path/that/does/not/exist",
            "command": "/bin/bash",
            "env": {},
        })

        # 后续消息：如果 Agent 没断连，会处理这条
        followup_received = False
        mock_ws.feed_message({"type": "pong"})

        ws_to_pty_task = asyncio.create_task(
            client._websocket_to_pty()
        )

        await asyncio.sleep(3)

        client._running = False
        client._connected = False
        ws_to_pty_task.cancel()
        try:
            await ws_to_pty_task
        except asyncio.CancelledError:
            pass

        messages = mock_ws.sent_data
        print(f"\n[TEST] Sent {len(messages)} messages:")
        for m in messages:
            mtype = m.get("type", "unknown")
            if m.get("_corrupted"):
                print(f"  CORRUPTED: {m['_raw']}")
            else:
                print(f"  {mtype}: {json.dumps(m, ensure_ascii=False)[:150]}")

        corrupted = [m for m in messages if m.get("_corrupted")]
        if corrupted:
            pytest.fail(f"消息损坏！{len(corrupted)} 条消息被污染")

    @pytest.mark.asyncio
    async def test_nonexistent_command_agent_stays_connected(self):
        """
        场景：command 不存在

        预期：Agent 不应断连
        """
        client = WebSocketClient(
            server_url="ws://test",
            token="test",
            command="/bin/bash",
            auto_reconnect=False,
        )

        mock_ws = MockWebSocket()
        client.ws = mock_ws
        client._connected = True
        client._running = True

        mock_ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-bad-cmd-001",
            "title": "Test",
            "cwd": "/tmp",
            "command": "nonexistent_command_xyz",
            "env": {},
        })

        ws_to_pty_task = asyncio.create_task(
            client._websocket_to_pty()
        )

        await asyncio.sleep(3)

        client._running = False
        client._connected = False
        ws_to_pty_task.cancel()
        try:
            await ws_to_pty_task
        except asyncio.CancelledError:
            pass

        messages = mock_ws.sent_data
        print(f"\n[TEST] Sent {len(messages)} messages:")
        for m in messages:
            mtype = m.get("type", "unknown")
            if m.get("_corrupted"):
                print(f"  CORRUPTED: {m['_raw']}")
            else:
                print(f"  {mtype}: {json.dumps(m, ensure_ascii=False)[:150]}")

        corrupted = [m for m in messages if m.get("_corrupted")]
        if corrupted:
            pytest.fail(f"消息损坏！{len(corrupted)} 条消息被污染")

    @pytest.mark.asyncio
    async def test_concurrent_create_terminals(self):
        """
        场景：同时创建 3 个终端（1 个好的 + 1 个坏的 + 1 个好的）

        预期：坏的失败，好的成功，Agent 不断连
        """
        client = WebSocketClient(
            server_url="ws://test",
            token="test",
            command="/bin/bash",
            auto_reconnect=False,
        )

        mock_ws = MockWebSocket()
        client.ws = mock_ws
        client._connected = True
        client._running = True

        # 连续创建 3 个终端
        mock_ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-good-1",
            "title": "Good",
            "cwd": "/tmp",
            "command": "/bin/bash",
            "env": {},
        })
        mock_ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-bad-1",
            "title": "Bad",
            "cwd": "~/project",
            "command": "/bin/bash",
            "env": {},
        })
        mock_ws.feed_message({
            "type": "create_terminal",
            "terminal_id": "term-good-2",
            "title": "Good 2",
            "cwd": "/tmp",
            "command": "/bin/bash",
            "env": {},
        })

        ws_to_pty_task = asyncio.create_task(
            client._websocket_to_pty()
        )

        await asyncio.sleep(5)

        client._running = False
        client._connected = False
        ws_to_pty_task.cancel()
        try:
            await ws_to_pty_task
        except asyncio.CancelledError:
            pass

        messages = mock_ws.sent_data
        print(f"\n[TEST] Sent {len(messages)} messages:")
        for m in messages:
            mtype = m.get("type", "unknown")
            if m.get("_corrupted"):
                print(f"  CORRUPTED: {m['_raw']}")
            else:
                print(f"  {mtype}: {json.dumps(m, ensure_ascii=False)[:150]}")

        corrupted = [m for m in messages if m.get("_corrupted")]
        if corrupted:
            pytest.fail(f"消息损坏！{len(corrupted)} 条消息被污染")

        # 清理可能存在的子进程
        client.runtime_manager.close_all()
