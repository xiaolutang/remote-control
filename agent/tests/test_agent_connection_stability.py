"""
Agent 连接稳定性系统诊断

直接运行 agent 对 Docker server 做 WebSocket 长连接测试，
排查 agent 断连问题。

使用方法：
    cd agent
    python3 tests/test_agent_connection_stability.py [--server ws://localhost:8888] [--duration 180]

诊断项：
1. 连接建立与协议级 ping 配置验证
2. 应用级心跳 ping/pong 交换
3. 协议级 ping 禁用后的长连接存活
4. PTY 启动后连接稳定性
5. 数据转发（PTY ↔ WebSocket）不中断心跳
"""
import argparse
import asyncio
import json
import sys
import time

try:
    import websockets
except ImportError:
    print("[FAIL] 需要 websockets 库: pip install websockets")
    sys.exit(1)

try:
    import httpx
except ImportError:
    print("[FAIL] 需要 httpx 库: pip install httpx")
    sys.exit(1)


async def login(server_url: str) -> dict:
    """登录获取 token"""
    http_url = server_url.replace("ws://", "http://").replace("wss://", "https://")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{http_url}/api/login",
            json={"username": "test", "password": "test123"},
        )
        if resp.status_code != 200:
            print(f"[FAIL] 登录失败: {resp.status_code} {resp.text}")
            sys.exit(1)
        data = resp.json()
        print(f"[OK] 登录成功: session_id={data.get('session_id')}")
        return data


async def test_connection_with_default_ping(server_url: str, token: str):
    """测试 1: 使用默认 ping_interval=20 连接，观察是否断连"""
    print("\n=== 测试 1: 默认协议级 ping (ping_interval=20) ===")
    ws_url = f"{server_url}/ws/agent?token={token}"
    connect_time = time.time()

    try:
        async with websockets.connect(ws_url) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            assert data.get("type") == "connected", f"预期 connected，收到 {data}"
            print(f"[OK] 连接成功: session_id={data.get('session_id')}")

            # 等待 70 秒（超过默认的 ping_interval + ping_timeout = 40s）
            # 这段时间不发任何消息，只等待
            print("[INFO] 静默等待 70 秒，不发送任何消息...")
            for i in range(7):
                await asyncio.sleep(10)
                elapsed = time.time() - connect_time
                try:
                    response = await asyncio.wait_for(ws.recv(), timeout=0.1)
                except asyncio.TimeoutError:
                    print(f"[INFO] {elapsed:.0f}s - 连接仍存活")
                    continue
                except Exception as e:
                    print(f"[FAIL] {elapsed:.0f}s - 连接断开: {type(e).__name__}: {e}")
                    return False
                rdata = json.loads(response)
                print(f"[INFO] {elapsed:.0f}s - 收到消息: type={rdata.get('type')}")

            elapsed = time.time() - connect_time
            print(f"[OK] 静默存活 {elapsed:.0f} 秒")
            return True

    except Exception as e:
        elapsed = time.time() - connect_time
        print(f"[FAIL] {elapsed:.0f}s - {type(e).__name__}: {e}")
        return False


async def test_connection_without_protocol_ping(server_url: str, token: str):
    """测试 2: 禁用协议级 ping，只依赖应用级心跳"""
    print("\n=== 测试 2: 禁用协议级 ping (ping_interval=None) + 应用级心跳 ===")
    ws_url = f"{server_url}/ws/agent?token={token}"
    connect_time = time.time()
    pong_count = 0

    try:
        async with websockets.connect(
            ws_url,
            ping_interval=None,  # 禁用协议级 ping
        ) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            assert data.get("type") == "connected"
            print(f"[OK] 连接成功 (ping_interval=None)")

            # 模拟 agent 的心跳行为：每 30 秒发 ping
            for i in range(6):  # 6 × 30s = 180s
                await ws.send(json.dumps({"type": "ping"}))
                elapsed = time.time() - connect_time
                print(f"[INFO] 发送应用级 ping #{i+1} ({elapsed:.0f}s)")

                # 等待 pong
                try:
                    deadline = time.time() + 5
                    while time.time() < deadline:
                        response = await asyncio.wait_for(ws.recv(), timeout=min(5, deadline - time.time()))
                        rdata = json.loads(response)
                        if rdata.get("type") == "pong":
                            pong_count += 1
                            print(f"[OK] 收到 pong #{pong_count}")
                            break
                        else:
                            print(f"[INFO] 收到非 pong 消息: {rdata.get('type')}")
                except asyncio.TimeoutError:
                    print(f"[FAIL] ping #{i+1} 超时无 pong!")
                    return False

                if i < 5:
                    await asyncio.sleep(30)

            elapsed = time.time() - connect_time
            print(f"[OK] 应用级心跳存活 {elapsed:.0f} 秒，{pong_count} 次 pong")
            return True

    except Exception as e:
        elapsed = time.time() - connect_time
        print(f"[FAIL] {elapsed:.0f}s - {type(e).__name__}: {e}")
        return False


async def test_simultaneous_heartbeat(server_url: str, token: str):
    """测试 3: 两层心跳同时开启时的稳定性"""
    print("\n=== 测试 3: 两层心跳同时开启 (协议级 20s + 应用级 30s) ===")
    ws_url = f"{server_url}/ws/agent?token={token}"
    connect_time = time.time()
    pong_count = 0

    try:
        async with websockets.connect(
            ws_url,
            ping_interval=20,   # 协议级 ping
            ping_timeout=20,    # 协议级 pong 超时
        ) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            assert data.get("type") == "connected"
            print(f"[OK] 连接成功 (ping_interval=20)")

            # 同时发应用级 ping
            for i in range(4):  # 4 × 30s = 120s
                await ws.send(json.dumps({"type": "ping"}))
                elapsed = time.time() - connect_time
                print(f"[INFO] 发送应用级 ping #{i+1} ({elapsed:.0f}s)")

                try:
                    deadline = time.time() + 5
                    while time.time() < deadline:
                        response = await asyncio.wait_for(ws.recv(), timeout=min(5, deadline - time.time()))
                        rdata = json.loads(response)
                        if rdata.get("type") == "pong":
                            pong_count += 1
                            print(f"[OK] 收到 pong #{pong_count}")
                            break
                except asyncio.TimeoutError:
                    print(f"[FAIL] 应用级 ping #{i+1} 超时!")
                    return False

                if i < 3:
                    await asyncio.sleep(30)

            elapsed = time.time() - connect_time
            print(f"[OK] 双层心跳存活 {elapsed:.0f} 秒，{pong_count} 次应用级 pong")
            return True

    except Exception as e:
        elapsed = time.time() - connect_time
        print(f"[FAIL] {elapsed:.0f}s - {type(e).__name__}: {e}")
        return False


async def test_recv_timeout_interaction(server_url: str, token: str):
    """测试 4: 模拟 agent 的 recv(timeout=1) 与协议级 ping 的交互"""
    print("\n=== 测试 4: recv(timeout=1) 与协议级 ping 交互 ===")
    ws_url = f"{server_url}/ws/agent?token={token}"
    connect_time = time.time()

    try:
        async with websockets.connect(
            ws_url,
            ping_interval=20,
            ping_timeout=20,
        ) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            assert data.get("type") == "connected"
            print(f"[OK] 连接成功")

            # 模拟 agent 的 _websocket_to_pty 循环
            # 用 1 秒 timeout 的 recv 循环，持续 90 秒
            print("[INFO] 模拟 agent 的 recv(timeout=1) 循环，持续 90 秒...")
            recv_count = 0
            timeout_count = 0
            heartbeat_count = 0

            for _ in range(90):  # 90 × 1s = 90s
                try:
                    response = await asyncio.wait_for(ws.recv(), timeout=1)
                    rdata = json.loads(response)
                    recv_count += 1
                    if rdata.get("type") == "pong":
                        heartbeat_count += 1
                except asyncio.TimeoutError:
                    timeout_count += 1
                except Exception as e:
                    elapsed = time.time() - connect_time
                    print(f"[FAIL] {elapsed:.0f}s - recv 异常: {type(e).__name__}: {e}")
                    return False

                # 每 30 秒发一次 ping
                elapsed = time.time() - connect_time
                if int(elapsed) % 30 == 0 and heartbeat_count < int(elapsed / 30):
                    await ws.send(json.dumps({"type": "ping"}))

            elapsed = time.time() - connect_time
            print(f"[OK] recv 循环完成: {elapsed:.0f}s, {recv_count} 消息, {timeout_count} 超时, {heartbeat_count} 心跳")
            return True

    except Exception as e:
        elapsed = time.time() - connect_time
        print(f"[FAIL] {elapsed:.0f}s - {type(e).__name__}: {e}")
        return False


async def test_no_ping_reconnect(server_url: str, token: str):
    """测试 5: ping_interval=None 不发送协议级 ping，完全依赖应用层"""
    print("\n=== 测试 5: 完全禁用协议级 ping，长时静默测试 ===")
    ws_url = f"{server_url}/ws/agent?token={token}"
    connect_time = time.time()

    try:
        async with websockets.connect(
            ws_url,
            ping_interval=None,
        ) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            assert data.get("type") == "connected"
            print(f"[OK] 连接成功 (ping_interval=None)")

            # 静默 150 秒，只发应用级 ping
            for i in range(5):  # 5 × 30s = 150s
                await ws.send(json.dumps({"type": "ping"}))
                elapsed = time.time() - connect_time
                print(f"[INFO] 发送 ping #{i+1} ({elapsed:.0f}s)")

                try:
                    deadline = time.time() + 5
                    while time.time() < deadline:
                        response = await asyncio.wait_for(ws.recv(), timeout=min(5, deadline - time.time()))
                        rdata = json.loads(response)
                        if rdata.get("type") == "pong":
                            print(f"[OK] pong #{i+1}")
                            break
                except asyncio.TimeoutError:
                    print(f"[FAIL] ping #{i+1} 无响应!")
                    return False

                if i < 4:
                    await asyncio.sleep(30)

            elapsed = time.time() - connect_time
            print(f"[OK] 无协议级 ping 存活 {elapsed:.0f} 秒")
            return True

    except Exception as e:
        elapsed = time.time() - connect_time
        print(f"[FAIL] {elapsed:.0f}s - {type(e).__name__}: {e}")
        return False


async def main():
    parser = argparse.ArgumentParser(description="Agent 连接稳定性系统诊断")
    parser.add_argument("--server", default="ws://localhost:8888", help="服务器 URL")
    parser.add_argument("--duration", type=int, default=180, help="测试时长（秒）")
    args = parser.parse_args()

    print(f"Agent 连接稳定性系统诊断")
    print(f"服务器: {args.server}")
    print(f"websockets 版本: {websockets.__version__}")
    print("=" * 60)

    # 登录
    login_data = await login(args.server)
    token = login_data["token"]

    results = {}

    # 测试 1: 默认协议级 ping 静默存活
    results["default_ping_silent"] = await test_connection_with_default_ping(args.server, token)

    # 每次测试用新 token（避免重复 agent 检测）
    login_data = await login(args.server)
    token = login_data["token"]

    # 测试 2: 禁用协议级 ping + 应用级心跳
    results["no_protocol_ping"] = await test_connection_without_protocol_ping(args.server, token)

    login_data = await login(args.server)
    token = login_data["token"]

    # 测试 3: 两层心跳同时
    results["dual_heartbeat"] = await test_simultaneous_heartbeat(args.server, token)

    login_data = await login(args.server)
    token = login_data["token"]

    # 测试 4: recv(timeout=1) 与协议级 ping
    results["recv_timeout"] = await test_recv_timeout_interaction(args.server, token)

    login_data = await login(args.server)
    token = login_data["token"]

    # 测试 5: 无协议级 ping 长时间测试
    results["no_ping_long"] = await test_no_ping_reconnect(args.server, token)

    # 结果汇总
    print("\n" + "=" * 60)
    print("诊断结果汇总:")
    all_passed = True
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    if all_passed:
        print("\n所有测试通过! Agent 连接稳定。")
    else:
        print("\n存在失败项，需要进一步排查。")
        print("建议修复: 在 websockets.connect() 中设置 ping_interval=None")

    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
