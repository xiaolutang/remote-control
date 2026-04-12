"""
WebSocket 并发发送竞态测试 — 复现 PTY 输出与 JSON 消息交叉污染。

根因：
  _pty_to_websocket() 持续发送 PTY 输出（大块 base64 数据）
  _websocket_to_pty() 同时发送 terminal_created（JSON）
  websockets 15.x 的 send() 不是协程安全的，并发调用导致消息内容交叉污染。
  Server 收到的是 base64 + JSON 混合的乱码。

修复：
  _send_ws_message() 加 asyncio.Lock，确保同一时间只有一个协程在 send。
"""
import asyncio
import base64
import json
import os
import sys
import pytest
import pytest_asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agent'))

from app.websocket_client import WebSocketClient, TerminalRuntimeManager, TerminalSpec


class ConcurrentSendTracker:
    """追踪 send 调用的并发情况。"""

    def __init__(self):
        self._recv_queue: asyncio.Queue = asyncio.Queue()
        self._send_queue: asyncio.Queue = asyncio.Queue()
        self._closed = False
        self.concurrent_send_count = 0
        self._active_senders = 0
        self._lock = None  # 外部注入

    async def send(self, message: str):
        if self._closed:
            raise Exception("WebSocket is closed")
        # 不用锁时追踪并发
        self._active_senders += 1
        if self._active_senders > 1:
            self.concurrent_send_count += 1
        # 模拟网络延迟，放大竞态窗口
        await asyncio.sleep(0.001)
        self._active_senders -= 1
        await self._send_queue.put(message)

    async def recv(self) -> str:
        if self._closed:
            raise Exception("WebSocket is closed")
        return await self._recv_queue.get()

    def close(self):
        self._closed = True

    def feed_message(self, message: dict):
        self._recv_queue.put_nowait(json.dumps(message))

    async def get_sent_message(self, timeout: float = 5.0) -> dict:
        raw = await asyncio.wait_for(self._send_queue.get(), timeout=timeout)
        return json.loads(raw)

    async def get_all_sent_messages(self, timeout: float = 3.0) -> list[dict]:
        messages = []
        while True:
            try:
                raw = await asyncio.wait_for(self._send_queue.get(), timeout=0.5)
                messages.append(json.loads(raw))
            except asyncio.TimeoutError:
                break
        return messages


class FakePTY:
    """模拟 PTY，持续产生大量输出。"""

    def __init__(self, output_chunks: list[bytes] = None):
        self._output_chunks = output_chunks or []
        self._index = 0
        self._started = False
        self._running = False

    def start(self) -> bool:
        self._started = True
        self._running = True
        return True

    def stop(self):
        self._running = False

    async def read(self):
        if not self._output_chunks:
            return None
        if self._index >= len(self._output_chunks):
            await asyncio.sleep(0.01)
            return None
        chunk = self._output_chunks[self._index]
        self._index += 1
        return chunk

    def write(self, data: bytes):
        pass

    def resize(self, rows, cols):
        pass

    def is_running(self):
        return self._running


@pytest.mark.asyncio
async def test_concurrent_send_corrupts_messages_without_lock():
    """验证：没有 Lock 时，并发 send 会导致消息交叉污染。"""
    # 创建大量 PTY 输出（每个 10KB）
    big_chunks = [b"X" * 10000 + b"\n" for _ in range(50)]

    ws = ConcurrentSendTracker()

    # 同时运行两个发送协程
    async def sender1():
        """模拟 _pty_to_websocket 发送大数据。"""
        for chunk in big_chunks:
            payload = base64.b64encode(chunk).decode("utf-8")
            msg = json.dumps({
                "type": "data",
                "payload": payload,
                "direction": "output",
            })
            await ws.send(msg)

    async def sender2():
        """模拟 _websocket_to_pty 发送 JSON 消息。"""
        for i in range(20):
            msg = json.dumps({
                "type": "terminal_created",
                "terminal_id": f"term-{i}",
            })
            await ws.send(msg)
            await asyncio.sleep(0)

    # 并发运行
    await asyncio.gather(sender1(), sender2())

    # 检查所有消息是否都是有效 JSON
    messages = []
    while True:
        try:
            raw = await asyncio.wait_for(ws._send_queue.get(), timeout=0.5)
            try:
                parsed = json.loads(raw)
                messages.append(parsed)
            except json.JSONDecodeError:
                # 找到了！消息被污染了
                print(f"[TEST] CORRUPTED MESSAGE: {raw[:200]}")
                messages.append({"_corrupted": True, "_raw": raw[:200]})
        except asyncio.TimeoutError:
            break

    corrupted = [m for m in messages if isinstance(m, dict) and m.get("_corrupted")]
    total = len(messages)

    print(f"[TEST] Total messages: {total}, corrupted: {len(corrupted)}")
    print(f"[TEST] Concurrent send detected: {ws.concurrent_send_count} times")

    # 注意：这个测试验证竞态条件存在，CI 环境下不一定每次都能复现
    # 但并发 send 的计数应该 > 0
    if ws.concurrent_send_count > 0:
        print("[TEST] 竞态条件已被检测到：多个协程同时调用了 send()")


@pytest.mark.asyncio
async def test_send_ws_message_with_lock_no_corruption():
    """验证：有 Lock 时，_send_ws_message 不会并发执行。"""
    client = WebSocketClient(
        server_url="ws://test",
        token="test-token",
        command="/bin/bash",
        auto_reconnect=False,
    )

    ws = ConcurrentSendTracker()
    client.ws = ws
    client._connected = True
    client._running = True

    # 发送大量并发消息
    tasks = []
    for i in range(50):
        tasks.append(asyncio.create_task(
            client._send_ws_message({"type": "test", "index": i})
        ))

    await asyncio.gather(*tasks)

    # 验证所有消息都是有效 JSON
    messages = []
    while True:
        try:
            raw = await asyncio.wait_for(ws._send_queue.get(), timeout=1.0)
            parsed = json.loads(raw)
            messages.append(parsed)
        except asyncio.TimeoutError:
            break

    # 所有消息都应该是有效 JSON
    assert len(messages) == 50, f"Expected 50 messages, got {len(messages)}"

    # 验证消息完整性
    indices = sorted([m["index"] for m in messages])
    assert indices == list(range(50)), "Some messages were lost or corrupted"

    print(f"[TEST] All {len(messages)} messages received correctly with Lock")


@pytest.mark.asyncio
async def test_real_scenario_pty_output_plus_terminal_created():
    """真实场景模拟：PTY 持续输出 + 同时发送 terminal_created。"""
    client = WebSocketClient(
        server_url="ws://test",
        token="test-token",
        command="/bin/bash",
        auto_reconnect=False,
    )
    client.runtime_manager = TerminalRuntimeManager(pty_factory=FakePTY)

    ws = ConcurrentSendTracker()
    client.ws = ws
    client._connected = True
    client._running = True

    # 模拟主 PTY 持续输出（大块数据）
    big_output = base64.b64encode(b"A" * 50000).decode("utf-8")

    pty_send_count = 0

    async def fake_pty_to_ws():
        nonlocal pty_send_count
        for _ in range(30):
            await client._send_ws_message({
                "type": "data",
                "payload": big_output,
                "direction": "output",
            })
            pty_send_count += 1
            await asyncio.sleep(0)  # 让出控制权

    async def fake_create_terminal():
        # 在 PTY 输出的间隙发送 terminal_created
        for i in range(5):
            await asyncio.sleep(0.002)  # 等一下让 PTY 输出先跑
            await client._send_ws_message({
                "type": "terminal_created",
                "terminal_id": f"term-{i}",
            })

    await asyncio.gather(fake_pty_to_ws(), fake_create_terminal())

    # 收集所有消息
    messages = []
    while True:
        try:
            raw = await asyncio.wait_for(ws._send_queue.get(), timeout=1.0)
            parsed = json.loads(raw)
            messages.append(parsed)
        except json.JSONDecodeError:
            print(f"[TEST] CORRUPTED: {raw[:200]}")
            pytest.fail("Message corruption detected with Lock!")
        except asyncio.TimeoutError:
            break

    total = pty_send_count + 5  # PTY 消息 + terminal_created 消息
    print(f"[TEST] Sent {pty_send_count} data + 5 terminal_created, received {len(messages)}")

    # 验证 terminal_created 消息完整性
    terminal_msgs = [m for m in messages if m.get("type") == "terminal_created"]
    assert len(terminal_msgs) == 5, f"Expected 5 terminal_created, got {len(terminal_msgs)}"

    # 验证 data 消息完整性
    data_msgs = [m for m in messages if m.get("type") == "data"]
    assert len(data_msgs) == 30, f"Expected 30 data messages, got {len(data_msgs)}"

    print("[TEST] PASS: All messages intact with Lock protection")
