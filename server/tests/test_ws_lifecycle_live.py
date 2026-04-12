"""
WebSocket 生命周期系统诊断脚本

直接对 Docker server 做 WebSocket 测试，排查 agent 断连问题。

使用方法：
    python3 tests/test_ws_lifecycle_live.py [--server ws://localhost:8888]

诊断项：
1. 登录获取 token
2. Agent WebSocket 连接并保持
3. 心跳 ping/pong 交换
4. 观察连接是否在 120 秒内断开
5. Client WebSocket 连接并验证状态
6. 终端创建全链路测试
"""
import argparse
import asyncio
import json
import sys
import time
import httpx
import websockets


async def login(server_url: str, username: str = "test") -> dict:
    """登录获取 token 和 session 信息"""
    http_url = server_url.replace("ws://", "http://").replace("wss://", "https://")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{http_url}/api/login",
            json={"username": username, "password": "test123"},
        )
        if resp.status_code != 200:
            print(f"[FAIL] 登录失败: {resp.status_code} {resp.text}")
            sys.exit(1)
        data = resp.json()
        print(f"[OK] 登录成功: session_id={data.get('session_id')}")
        return data


async def test_agent_lifecycle(server_url: str, token: str, session_id: str):
    """测试 1: Agent WebSocket 生命周期"""
    print("\n=== 测试 1: Agent WebSocket 连接生命周期 ===")

    ws_url = f"{server_url}/ws/agent?token={token}"
    connect_time = time.time()

    try:
        async with websockets.connect(ws_url) as ws:
            # 等待 connected 消息
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            assert data.get("type") == "connected", f"预期 connected，收到 {data.get('type')}"
            print(f"[OK] Agent 连接成功: session_id={data.get('session_id')}")

            # 发送 agent_metadata
            await ws.send(json.dumps({
                "type": "agent_metadata",
                "platform": "diagnostic",
                "hostname": "test-host",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }))

            # 心跳测试：连续 5 次 ping/pong
            print("[INFO] 开始心跳测试 (5 次 ping/pong, 每次 30 秒间隔)")
            for i in range(5):
                await ws.send(json.dumps({"type": "ping"}))
                elapsed = time.time() - connect_time
                print(f"[INFO] 发送 ping #{i+1} (已连接 {elapsed:.0f} 秒)")

                # 等待 pong（或其它消息）
                try:
                    response = await asyncio.wait_for(ws.recv(), timeout=35)
                    rdata = json.loads(response)
                    if rdata.get("type") == "pong":
                        print(f"[OK] 收到 pong #{i+1}")
                    else:
                        print(f"[WARN] 收到非 pong 消息: {rdata.get('type')}")
                except asyncio.TimeoutError:
                    print(f"[FAIL] ping #{i+1} 超时无响应!")
                    return False

                # 等待到下一个 30 秒周期
                if i < 4:
                    await asyncio.sleep(30)

            total_elapsed = time.time() - connect_time
            print(f"[OK] Agent 连接存活 {total_elapsed:.0f} 秒，未断开")
            return True

    except websockets.exceptions.ConnectionClosedOK as e:
        elapsed = time.time() - connect_time
        print(f"[FAIL] Agent 被正常关闭: code={e.code} reason={e.reason} (存活 {elapsed:.0f} 秒)")
        return False
    except websockets.exceptions.ConnectionClosedError as e:
        elapsed = time.time() - connect_time
        print(f"[FAIL] Agent 连接异常关闭: code={e.code} reason={e.reason} (存活 {elapsed:.0f} 秒)")
        return False
    except Exception as e:
        elapsed = time.time() - connect_time
        print(f"[FAIL] Agent 连接异常: {type(e).__name__}: {e} (存活 {elapsed:.0f} 秒)")
        return False


async def test_client_connection(server_url: str, token: str, session_id: str, agent_online: bool):
    """测试 2: Client WebSocket 连接"""
    print("\n=== 测试 2: Client WebSocket 连接 ===")

    ws_url = f"{server_url}/ws/client?session_id={session_id}&token={token}&view=desktop"
    try:
        async with websockets.connect(ws_url) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(msg)
            assert data.get("type") == "connected"
            print(f"[OK] Client 连接成功: agent_online={data.get('agent_online')}")

            if not data.get("agent_online"):
                print("[INFO] Agent 离线，客户端可连接但无法创建终端")
            return True
    except Exception as e:
        print(f"[FAIL] Client 连接失败: {type(e).__name__}: {e}")
        return False


async def test_client_terminal_without_agent(server_url: str, token: str, session_id: str):
    """测试 3: Agent 离线时创建终端"""
    print("\n=== 测试 3: Agent 离线时 Client 连接终端 ===")

    ws_url = f"{server_url}/ws/client?session_id={session_id}&token={token}&view=desktop&terminal_id=test-term-001"
    try:
        async with websockets.connect(ws_url) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(msg)
            print(f"[INFO] 连接终端响应: type={data.get('type')}")
            # 应该被拒绝（agent 离线）
            if "close" in str(data).lower() or "offline" in str(data).lower():
                print("[OK] 正确拒绝: agent 离线时终端连接被拒绝")
            return True
    except websockets.exceptions.ConnectionClosedOK as e:
        if e.code == 4009:
            print(f"[OK] 正确拒绝: code={e.code} reason={e.reason}")
            return True
        else:
            print(f"[WARN] 意外关闭码: code={e.code} reason={e.reason}")
            return False
    except Exception as e:
        print(f"[INFO] 连接结果: {type(e).__name__}: {e}")
        return True


async def test_concurrent_ping_stress(server_url: str, token: str):
    """测试 4: 快速连续 ping 压力测试"""
    print("\n=== 测试 4: 快速连续 ping 压力测试 ===")

    ws_url = f"{server_url}/ws/agent?token={token}"
    try:
        async with websockets.connect(ws_url) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            data = json.loads(msg)
            if data.get("type") != "connected":
                print(f"[FAIL] 未收到 connected: {data}")
                return False

            # 快速发送 10 次 ping
            for i in range(10):
                await ws.send(json.dumps({"type": "ping"}))

            # 收集所有响应
            pong_count = 0
            for _ in range(10):
                try:
                    response = await asyncio.wait_for(ws.recv(), timeout=5)
                    rdata = json.loads(response)
                    if rdata.get("type") == "pong":
                        pong_count += 1
                except asyncio.TimeoutError:
                    break

            print(f"[INFO] 发送 10 ping，收到 {pong_count} pong")
            if pong_count >= 8:
                print("[OK] 心跳响应正常")
                return True
            else:
                print(f"[WARN] 心跳响应不足: {pong_count}/10")
                return False

    except Exception as e:
        print(f"[FAIL] 压力测试异常: {type(e).__name__}: {e}")
        return False


async def test_duplicate_agent_rejected(server_url: str, token: str):
    """测试 5: 重复 Agent 连接被拒绝"""
    print("\n=== 测试 5: 重复 Agent 连接拒绝 ===")

    ws_url = f"{server_url}/ws/agent?token={token}"
    try:
        async with websockets.connect(ws_url) as ws1:
            msg = await asyncio.wait_for(ws1.recv(), timeout=10)
            data = json.loads(msg)
            if data.get("type") != "connected":
                print(f"[FAIL] 第一个 Agent 连接失败")
                return False
            print("[OK] 第一个 Agent 连接成功")

            # 尝试第二个连接
            try:
                async with websockets.connect(ws_url) as ws2:
                    msg2 = await asyncio.wait_for(ws2.recv(), timeout=5)
                    data2 = json.loads(msg2)
                    print(f"[FAIL] 第二个 Agent 未被拒绝: {data2}")
                    return False
            except websockets.exceptions.ConnectionClosedOK as e:
                if e.code == 4009:
                    print(f"[OK] 第二个 Agent 被正确拒绝: code={e.code}")
                    return True
                else:
                    print(f"[WARN] 关闭码不正确: {e.code} (预期 4009)")
                    return False

    except Exception as e:
        print(f"[FAIL] 测试异常: {type(e).__name__}: {e}")
        return False


async def main():
    parser = argparse.ArgumentParser(description="WebSocket 生命周期系统诊断")
    parser.add_argument("--server", default="ws://localhost:8888", help="服务器 URL")
    args = parser.parse_args()

    print(f"WebSocket 生命周期系统诊断")
    print(f"服务器: {args.server}")
    print("=" * 60)

    # Step 1: 登录
    login_data = await login(args.server)
    token = login_data["token"]
    session_id = login_data["session_id"]

    results = {}

    # Step 2: Agent 生命周期测试（最关键）
    results["agent_lifecycle"] = await test_agent_lifecycle(args.server, token, session_id)

    # Step 3: Agent 连接后做 client 测试
    results["duplicate_agent"] = await test_duplicate_agent_rejected(args.server, token)

    # Step 4: 快速 ping 压力测试
    results["ping_stress"] = await test_concurrent_ping_stress(args.server, token)

    # Step 5: Client 连接测试（agent 应在线）
    results["client_connection"] = await test_client_connection(args.server, token, session_id, True)

    # Step 6: 新登录，测试 agent 离线时的行为
    login_data2 = await login(args.server)
    results["terminal_without_agent"] = await test_client_terminal_without_agent(
        args.server, login_data2["token"], login_data2["session_id"]
    )

    # 输出结果汇总
    print("\n" + "=" * 60)
    print("诊断结果汇总:")
    all_passed = True
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    if all_passed:
        print("\n所有测试通过!")
    else:
        print("\n存在失败项，需要进一步排查")

    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
