"""
WebSocket 消息污染复现测试

目标：用真实 websockets 15.0.1 库 + 真实服务器，
模拟 Agent 发送 PTY 输出 + terminal 事件的场景，
检查是否出现消息污染。

测试策略：
1. Test A: 无 Lock，并发 send → 检查是否有污染
2. Test B: 有 Lock，并发 send → 检查是否无污染
3. Test C: 有 Lock 但心跳绕过 Lock → 检查是否有污染
4. Test D: 模拟真实场景（PTY 输出 + terminal 创建失败）
"""
import asyncio
import json
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agent'))

import websockets
from websockets import serve


def make_large_payload(size: int = 50000) -> str:
    """生成大 payload 模拟 PTY 输出。"""
    import base64
    return base64.b64encode(b"X" * size).decode()


async def run_corruption_test(
    use_lock: bool,
    bypass_lock_for_heartbeat: bool = False,
    num_data_messages: int = 30,
    num_json_messages: int = 5,
    payload_size: int = 50000,
) -> dict:
    """
    运行污染测试，返回统计结果。

    Args:
        use_lock: 是否用 asyncio.Lock 保护 send
        bypass_lock_for_heartbeat: 是否模拟心跳绕过 Lock
        num_data_messages: 大数据消息数
        num_json_messages: JSON 消息数
        payload_size: payload 大小

    Returns:
        {"total": int, "corrupted": int, "corrupted_samples": list[str]}
    """
    received_messages: list[str] = []

    async def server_handler(ws):
        async for message in ws:
            received_messages.append(message)

    async with serve(server_handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]

        async with websockets.connect(
            f"ws://127.0.0.1:{port}",
            ping_interval=None,  # 禁用协议级 ping
            compression=None,    # 先禁用压缩排除干扰
        ) as client:
            lock = asyncio.Lock() if use_lock else None

            async def locked_send(msg: str):
                if lock:
                    async with lock:
                        await client.send(msg)
                else:
                    await client.send(msg)

            async def direct_send(msg: str):
                """绕过 Lock 直接发送（模拟心跳）。"""
                await client.send(msg)

            large_payload = make_large_payload(payload_size)

            async def send_data_messages():
                for i in range(num_data_messages):
                    msg = json.dumps({
                        "type": "data",
                        "payload": large_payload,
                        "index": i,
                    })
                    await locked_send(msg)
                    await asyncio.sleep(0)  # 让出控制权

            async def send_json_messages():
                for i in range(num_json_messages):
                    await asyncio.sleep(0.002)  # 等数据发送先跑
                    msg = json.dumps({
                        "type": "terminal_created",
                        "terminal_id": f"term-{i}",
                        "index": i,
                    })
                    if bypass_lock_for_heartbeat and i == 2:
                        # 第 3 条消息绕过 Lock（模拟心跳）
                        await direct_send(msg)
                    else:
                        await locked_send(msg)

            await asyncio.gather(send_data_messages(), send_json_messages())
            # 等待所有消息被接收
            await asyncio.sleep(0.5)

    # 分析结果
    corrupted = 0
    corrupted_samples = []
    for msg in received_messages:
        try:
            json.loads(msg)
        except json.JSONDecodeError:
            corrupted += 1
            corrupted_samples.append(msg[:200])

    return {
        "total": len(received_messages),
        "corrupted": corrupted,
        "corrupted_samples": corrupted_samples,
    }


@pytest.mark.asyncio
async def test_A_no_lock_detects_race_condition():
    """测试 A：无 Lock，并发 send。检查消息污染。"""
    result = await run_corruption_test(use_lock=False)
    print(f"\n[TEST A] 无 Lock: {result['total']} messages, {result['corrupted']} corrupted")
    if result['corrupted'] > 0:
        print(f"  样本: {result['corrupted_samples'][:3]}")
    # 无 Lock 时可能（但不保证）出现污染
    # 这个测试主要是为了对比


@pytest.mark.asyncio
async def test_B_with_lock_no_corruption():
    """测试 B：有 Lock，所有 send 都经过 Lock。不应该有污染。"""
    result = await run_corruption_test(use_lock=True, bypass_lock_for_heartbeat=False)
    print(f"\n[TEST B] 有 Lock: {result['total']} messages, {result['corrupted']} corrupted")
    assert result['corrupted'] == 0, (
        f"Lock 应该防止污染，但出现了 {result['corrupted']} 条损坏消息: "
        f"{result['corrupted_samples'][:3]}"
    )


@pytest.mark.asyncio
async def test_C_lock_bypass_heartbeat():
    """测试 C：有 Lock 但心跳绕过 Lock。检查是否有污染。"""
    result = await run_corruption_test(use_lock=True, bypass_lock_for_heartbeat=True)
    print(f"\n[TEST C] Lock + 心跳绕过: {result['total']} messages, {result['corrupted']} corrupted")
    if result['corrupted'] > 0:
        print(f"  样本: {result['corrupted_samples'][:3]}")


@pytest.mark.asyncio
async def test_D_compression_enabled():
    """测试 D：启用压缩（默认配置），检查是否有压缩相关的消息污染。"""
    received_messages: list[str] = []

    async def server_handler(ws):
        async for message in ws:
            received_messages.append(message)

    async with serve(server_handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]

        # 使用默认压缩（permessage-deflate）
        async with websockets.connect(
            f"ws://127.0.0.1:{port}",
            ping_interval=None,
            # 不禁用压缩 — 使用默认配置
        ) as client:
            lock = asyncio.Lock()
            large_payload = make_large_payload(50000)

            async def send_data():
                for i in range(30):
                    msg = json.dumps({
                        "type": "data",
                        "payload": large_payload,
                        "index": i,
                    })
                    async with lock:
                        await client.send(msg)
                    await asyncio.sleep(0)

            async def send_terminal():
                for i in range(5):
                    await asyncio.sleep(0.002)
                    msg = json.dumps({
                        "type": "terminal_created",
                        "terminal_id": f"term-{i}",
                    })
                    async with lock:
                        await client.send(msg)

            await asyncio.gather(send_data(), send_terminal())
            await asyncio.sleep(0.5)

    corrupted = 0
    corrupted_samples = []
    for msg in received_messages:
        try:
            json.loads(msg)
        except json.JSONDecodeError:
            corrupted += 1
            corrupted_samples.append(msg[:200])

    print(f"\n[TEST D] 有压缩 + Lock: {len(received_messages)} messages, {corrupted} corrupted")
    if corrupted > 0:
        print(f"  样本: {corrupted_samples[:3]}")
    assert corrupted == 0, f"压缩 + Lock 不应该有污染: {corrupted_samples[:3]}"


@pytest.mark.asyncio
async def test_E_real_websockets_client_class():
    """测试 E：使用真实的 WebSocketClient 类（含心跳绕过）。"""
    from app.websocket_client import WebSocketClient, TerminalRuntimeManager

    received_messages: list[str] = []

    async def server_handler(ws):
        # 先发送 connected 消息
        await ws.send(json.dumps({
            "type": "connected",
            "session_id": "test-session",
            "owner": "test",
            "views": 0,
            "timestamp": "2026-01-01T00:00:00Z",
        }))
        async for message in ws:
            received_messages.append(message)
            # 如果收到 terminal_created，立即发送 create_terminal
            try:
                data = json.loads(message)
                if data.get("type") == "terminal_created":
                    # 模拟后续操作
                    pass
            except:
                pass

    async with serve(server_handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]

        # 用最小 MockPTY
        class MockPTY:
            def __init__(self, cmd, **kwargs):
                self._output = [b"test output data\n"] * 20
                self._idx = 0
                self._running = True

            def start(self):
                return True

            def stop(self):
                self._running = False

            async def read(self):
                if self._idx >= len(self._output):
                    self._running = False
                    return None
                chunk = self._output[self._idx]
                self._idx += 1
                return chunk

            def write(self, data):
                pass

            def resize(self, r, c):
                pass

            def is_running(self):
                return self._running

        # 替换 PTY 工厂
        client = WebSocketClient(
            server_url=f"ws://127.0.0.1:{port}",
            token="fake-token-for-test",
            command="/bin/bash",
            auto_reconnect=False,
        )
        # 替换 PTY
        client.runtime_manager = TerminalRuntimeManager(pty_factory=MockPTY)

        # 直接模拟 _connect_and_run 的关键部分
        # （跳过 accept 和 handshake，直接连接）
        ws_url = f"ws://127.0.0.1:{port}/ws/agent?token=fake-token-for-test"

        async with websockets.connect(ws_url, ping_interval=None) as ws:
            client.ws = ws
            client._connected = True
            client._running = True

            # 等待 connected 消息
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(msg)
            assert data.get("type") == "connected"
            client._session_id = data["session_id"]

            # 启动主 PTY 输出任务（使用 MockPTY）
            mock_pty = MockPTY("/bin/bash")

            async def pty_to_ws():
                """模拟 _pty_to_websocket"""
                while client._running and client._connected:
                    data = await mock_pty.read()
                    if data is None:
                        if not mock_pty.is_running():
                            break
                        await asyncio.sleep(0.01)
                        continue
                    import base64
                    payload = base64.b64encode(data).decode("utf-8")
                    await client._send_ws_message({
                        "type": "data",
                        "payload": payload,
                        "direction": "output",
                    })

            async def create_terminal():
                """模拟创建终端。"""
                await asyncio.sleep(0.01)
                try:
                    from app.websocket_client import TerminalSpec
                    spec = TerminalSpec(
                        terminal_id="test-term-1",
                        command="/bin/bash",
                        title="Test",
                        cwd="/tmp",
                    )
                    runtime = client.runtime_manager.create_terminal(spec)
                    await client._send_ws_message(
                        client.runtime_manager.build_terminal_created_event("test-term-1")
                    )
                except Exception as e:
                    print(f"  Terminal create error: {e}")

            # 运行
            tasks = [
                asyncio.create_task(pty_to_ws()),
                asyncio.create_task(create_terminal()),
            ]

            # 等待完成
            await asyncio.gather(*tasks)

            client._connected = False
            client._running = False

    # 分析
    corrupted = 0
    corrupted_samples = []
    for msg in received_messages:
        try:
            json.loads(msg)
        except json.JSONDecodeError:
            corrupted += 1
            corrupted_samples.append(msg[:200])

    print(f"\n[TEST E] WebSocketClient 真实类: {len(received_messages)} messages, {corrupted} corrupted")
    if corrupted > 0:
        print(f"  样本: {corrupted_samples[:3]}")

    # 检查心跳是否绕过 Lock
    # 心跳任务在这个测试中没有启动，所以不会有绕过
    assert corrupted == 0, f"不应该有污染: {corrupted_samples[:3]}"
