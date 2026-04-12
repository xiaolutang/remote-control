"""
真实 WebSocket 传输层端到端测试 — 定位 Agent 断连根因。

测试架构：
  Agent（真实 websockets 库）→ 真实 WebSocket → Server（Docker 中的 uvicorn）

本测试使用真实的 WebSocket 连接，而不是 InMemoryWebSocket。
这样可以捕获 WebSocket 协议层的问题（如 PING/PONG、帧编码等）。

前提条件：
  - Docker Server 运行在 localhost:8888
  - 需要有效的 token（自动获取）
"""
import asyncio
import base64
import json
import os
import sys
import pytest
import pytest_asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agent'))

import websockets
from app.websocket_client import WebSocketClient, TerminalRuntimeManager, TerminalSpec
from app.pty_wrapper import PTYWrapper

SERVER_URL = "ws://localhost:8888"


async def get_test_token() -> str:
    """登录获取测试 token。"""
    import urllib.request
    data = json.dumps({"username": "test", "password": "test"}).encode()
    req = urllib.request.Request(
        f"http://localhost:8888/api/login",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
        return result["access_token"]


@pytest_asyncio.fixture
async def agent_ws():
    """创建真实的 Agent WebSocket 连接到 Server。"""
    token = await get_test_token()
    ws_url = f"{SERVER_URL}/ws/agent?token={token}"

    ws = await websockets.connect(ws_url, ping_interval=None)
    # 等待 connected 消息
    msg = await asyncio.wait_for(ws.recv(), timeout=5)
    data = json.loads(msg)
    assert data["type"] == "connected", f"Expected connected, got {data}"

    # 发送 agent_metadata
    import platform, socket
    from datetime import datetime, timezone
    await ws.send(json.dumps({
        "type": "agent_metadata",
        "platform": platform.system().lower(),
        "hostname": socket.gethostname(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }))

    yield ws, data["session_id"]

    # 清理
    try:
        await ws.close()
    except Exception:
        pass


class TestWSTransport:
    """真实 WebSocket 传输层测试。"""

    @pytest.mark.asyncio
    async def test_agent_stays_connected_after_terminal_create(self, agent_ws):
        """创建终端后 Agent WebSocket 应保持连接。"""
        ws, session_id = agent_ws

        # 创建终端
        terminal_id = f"test-ws-{os.getpid()}"
        await ws.send(json.dumps({
            "type": "create_terminal",
            "terminal_id": terminal_id,
            "command": "/bin/bash",
            "cwd": "/tmp",
            "title": "WS Transport Test",
        }))

        # 收集响应
        messages = []
        for _ in range(10):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                msg = json.loads(raw)
                messages.append(msg)
                print(f"[TEST] Received: type={msg.get('type')} terminal_id={msg.get('terminal_id', 'N/A')}")
                # 如果收到 pong（心跳响应），继续等待
                if msg.get("type") == "pong":
                    continue
            except asyncio.TimeoutError:
                break

        # 验证收到了 terminal_created
        created = any(m["type"] == "terminal_created" and m.get("terminal_id") == terminal_id for m in messages)
        assert created, f"Should receive terminal_created. Got: {messages}"

        # 关键验证：Agent 仍然连接
        await asyncio.sleep(0.5)
        assert ws.state == websockets.State.OPEN, f"WebSocket should be OPEN but is {ws.state}"

        # 再发一条 ping 验证连接还活着
        await ws.send(json.dumps({"type": "ping"}))
        pong = await asyncio.wait_for(ws.recv(), timeout=3.0)
        pong_data = json.loads(pong)
        assert pong_data["type"] == "pong", f"Should get pong, got {pong_data}"

    @pytest.mark.asyncio
    async def test_agent_stays_connected_after_bad_cwd(self, agent_ws):
        """创建终端 cwd 不存在时 Agent 仍保持连接。"""
        ws, session_id = agent_ws

        terminal_id = f"test-bad-cwd-{os.getpid()}"
        await ws.send(json.dumps({
            "type": "create_terminal",
            "terminal_id": terminal_id,
            "command": "/bin/bash",
            "cwd": "/nonexistent/path/xyz123",
            "title": "Bad CWD WS Test",
        }))

        messages = []
        for _ in range(10):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                msg = json.loads(raw)
                messages.append(msg)
                print(f"[TEST] Received: type={msg.get('type')} terminal_id={msg.get('terminal_id', 'N/A')}")
            except asyncio.TimeoutError:
                break

        # 关键验证：Agent 仍然连接
        await asyncio.sleep(0.5)
        assert ws.state == websockets.State.OPEN, f"WebSocket should be OPEN but is {ws.state}"

    @pytest.mark.asyncio
    async def test_agent_stays_connected_after_tilde_cwd(self, agent_ws):
        """创建终端 cwd 使用波浪号时 Agent 仍保持连接。"""
        ws, session_id = agent_ws

        terminal_id = f"test-tilde-{os.getpid()}"
        await ws.send(json.dumps({
            "type": "create_terminal",
            "terminal_id": terminal_id,
            "command": "/bin/bash",
            "cwd": "~/project",
            "title": "Tilde CWD WS Test",
        }))

        messages = []
        for _ in range(15):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                msg = json.loads(raw)
                messages.append(msg)
                print(f"[TEST] Received: type={msg.get('type')} terminal_id={msg.get('terminal_id', 'N/A')}")
                if msg.get("type") == "pong":
                    continue
            except asyncio.TimeoutError:
                break

        # 关键验证：Agent 仍然连接
        await asyncio.sleep(0.5)
        assert ws.state == websockets.State.OPEN, f"WebSocket should be OPEN but is {ws.state}"

        # 再发一条消息验证
        await ws.send(json.dumps({"type": "ping"}))
        pong = await asyncio.wait_for(ws.recv(), timeout=3.0)
        pong_data = json.loads(pong)
        assert pong_data["type"] == "pong"

    @pytest.mark.asyncio
    async def test_agent_full_message_loop_with_real_pty(self):
        """完整端到端：真实 Agent 消息循环 + 真实 WebSocket + 真实 PTY。"""
        token = await get_test_token()
        ws_url = f"{SERVER_URL}/ws/agent?token={token}"

        # 创建 WebSocketClient（完整 Agent）
        client = WebSocketClient(
            server_url="ws://localhost:8888",
            token=token,
            command="/bin/bash",
            auto_reconnect=False,
        )

        # 连接到 Server
        real_ws = await websockets.connect(
            f"{SERVER_URL}/ws/agent?token={token}",
            ping_interval=None,
        )

        # 等待 connected
        msg = await asyncio.wait_for(real_ws.recv(), timeout=5)
        data = json.loads(msg)
        assert data["type"] == "connected"

        # 设置 client 状态
        client.ws = real_ws
        client._connected = True
        client._running = True
        client._session_id = data["session_id"]

        # 发送 metadata
        import platform, socket
        from datetime import datetime, timezone
        await real_ws.send(json.dumps({
            "type": "agent_metadata",
            "platform": platform.system().lower(),
            "hostname": socket.gethostname(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))

        # 启动主 PTY
        client.pty = PTYWrapper("/bin/bash")
        assert client.pty.start()

        # 启动消息循环
        loop_task = asyncio.create_task(client._websocket_to_pty())
        pty_task = asyncio.create_task(client._pty_to_websocket())
        heartbeat_task = asyncio.create_task(client._heartbeat_loop())

        try:
            # 等待初始化
            await asyncio.sleep(0.5)

            # 通过 REST API 创建终端（模拟真实流程）
            import urllib.request
            device_id = "ZYWMxT3utmHg5gFa"
            terminal_id = f"e2e-{os.getpid()}-{int(asyncio.get_event_loop().time())}"
            create_data = json.dumps({
                "title": "E2E Test",
                "cwd": "/tmp",
                "command": "/bin/bash",
                "terminal_id": terminal_id,
            }).encode()
            req = urllib.request.Request(
                f"http://localhost:8888/api/runtime/devices/{device_id}/terminals",
                data=create_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    result = json.loads(resp.read())
                    print(f"[TEST] Terminal created via API: {result.get('terminal_id')}")
            except urllib.error.HTTPError as e:
                body = json.loads(e.read())
                print(f"[TEST] API error: {e.code} {body}")
                # 可能因为 device_id 不匹配而失败，但 Agent WebSocket 应该仍然连接

            # 等待消息处理
            await asyncio.sleep(2.0)

            # 关键验证：Agent 仍然连接
            print(f"[TEST] client._connected={client._connected}")
            print(f"[TEST] loop_task.done={loop_task.done()}")
            print(f"[TEST] ws.state={real_ws.state}")
            assert client._connected is True, "Agent should still be connected!"
            assert not loop_task.done(), "Message loop should still be running!"

        finally:
            # 清理
            client._running = False
            loop_task.cancel()
            pty_task.cancel()
            heartbeat_task.cancel()
            for t in [loop_task, pty_task, heartbeat_task]:
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
            for task in list(client._runtime_tasks.values()):
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            client.runtime_manager.close_all()
            if client.pty:
                client.pty.stop()
            try:
                await real_ws.close()
            except Exception:
                pass
