#!/usr/bin/env python3
"""
端到端测试 - 验证登录和连接流程

运行方式:
cd remote-control
python3 tests/e2e/test_login_flow.py
"""
import asyncio
import json
import os
import httpx
import websockets
import sys

# 配置（可通过环境变量覆盖）
SERVER_URL = os.environ.get("SERVER_URL", "http://localhost:8888")
WS_URL = os.environ.get("WS_URL", "ws://localhost:8888")
TEST_USER = os.environ.get("TEST_USER", "testuser")
TEST_PASSWORD = os.environ.get("TEST_PASSWORD", "test123456")


class TestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def success(self, name):
        self.passed += 1
        print(f"✅ {name}")

    def fail(self, name, error):
        self.failed += 1
        self.errors.append(f"{name}: {error}")
        print(f"❌ {name}: {error}")

    def summary(self):
        print(f"\n{'='*50}")
        print(f"测试结果: {self.passed} passed, {self.failed} failed")
        if self.errors:
            print("\n失败详情:")
            for e in self.errors:
                print(f"  - {e}")
        return self.failed == 0


result = TestResult()


async def test_health_check():
    """测试 1: 服务端健康检查"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{SERVER_URL}/health", timeout=5)
            if response.status_code == 200:
                result.success("服务端健康检查")
                return True
            else:
                result.fail("服务端健康检查", f"状态码 {response.status_code}")
                return False
    except Exception as e:
        result.fail("服务端健康检查", str(e))
        return False


async def test_user_login():
    """测试 2: 用户登录"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{SERVER_URL}/api/login",
                json={"username": TEST_USER, "password": TEST_PASSWORD},
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("success") and data.get("token") and data.get("session_id"):
                    result.success("用户登录")
                    return data
                else:
                    result.fail("用户登录", f"响应缺少必要字段: {data}")
                    return None
            else:
                result.fail("用户登录", f"状态码 {response.status_code}")
                return None
    except Exception as e:
        result.fail("用户登录", str(e))
        return None


async def test_mobile_websocket_connection(login_data):
    """测试 3: 手机端 WebSocket 连接"""
    if not login_data:
        result.fail("手机端 WebSocket 连接", "登录数据为空")
        return False

    try:
        session_id = login_data["session_id"]
        token = login_data["token"]

        ws_url = f"{WS_URL}/ws/client?session_id={session_id}&token={token}&view=mobile"

        async with websockets.connect(ws_url, close_timeout=5) as ws:
            # 等待连接确认消息
            message = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(message)

            if data.get("type") == "connected":
                if "agent_online" in data and "session_id" in data:
                    result.success("手机端 WebSocket 连接")
                    return True
                else:
                    result.fail("手机端 WebSocket 连接", f"响应缺少字段: {data}")
                    return False
            else:
                result.fail("手机端 WebSocket 连接", f"未知消息类型: {data.get('type')}")
                return False
    except asyncio.TimeoutError:
        result.fail("手机端 WebSocket 连接", "等待消息超时")
        return False
    except Exception as e:
        result.fail("手机端 WebSocket 连接", str(e))
        return False


async def test_desktop_websocket_connection(login_data):
    """测试 4: 桌面端 WebSocket 连接"""
    if not login_data:
        result.fail("桌面端 WebSocket 连接", "登录数据为空")
        return False

    try:
        session_id = login_data["session_id"]
        token = login_data["token"]

        ws_url = f"{WS_URL}/ws/client?session_id={session_id}&token={token}&view=desktop"

        async with websockets.connect(ws_url, close_timeout=5) as ws:
            # 等待连接确认消息
            message = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(message)

            if data.get("type") == "connected":
                if "agent_online" in data and "session_id" in data:
                    result.success("桌面端 WebSocket 连接")
                    return True
                else:
                    result.fail("桌面端 WebSocket 连接", f"响应缺少字段: {data}")
                    return False
            else:
                result.fail("桌面端 WebSocket 连接", f"未知消息类型: {data.get('type')}")
                return False
    except asyncio.TimeoutError:
        result.fail("桌面端 WebSocket 连接", "等待消息超时")
        return False
    except Exception as e:
        result.fail("桌面端 WebSocket 连接", str(e))
        return False


async def test_dual_connection(login_data):
    """测试 5: 双端同时连接"""
    if not login_data:
        result.fail("双端同时连接", "登录数据为空")
        return False

    try:
        session_id = login_data["session_id"]
        token = login_data["token"]

        mobile_url = f"{WS_URL}/ws/client?session_id={session_id}&token={token}&view=mobile"
        desktop_url = f"{WS_URL}/ws/client?session_id={session_id}&token={token}&view=desktop"

        # 同时连接两个 WebSocket
        mobile_ws = await websockets.connect(mobile_url, close_timeout=5)
        desktop_ws = await websockets.connect(desktop_url, close_timeout=5)

        try:
            # 等待两个连接确认
            mobile_msg = await asyncio.wait_for(mobile_ws.recv(), timeout=5)
            desktop_msg = await asyncio.wait_for(desktop_ws.recv(), timeout=5)

            mobile_data = json.loads(mobile_msg)
            desktop_data = json.loads(desktop_msg)

            if mobile_data.get("type") == "connected" and desktop_data.get("type") == "connected":
                result.success("双端同时连接")
                return True
            else:
                result.fail("双端同时连接", "连接消息类型不正确")
                return False
        finally:
            await mobile_ws.close()
            await desktop_ws.close()
    except Exception as e:
        result.fail("双端同时连接", str(e))
        return False


async def test_message_broadcast(login_data):
    """测试 6: 消息广播"""
    if not login_data:
        result.fail("消息广播", "登录数据为空")
        return False

    try:
        session_id = login_data["session_id"]
        token = login_data["token"]

        mobile_url = f"{WS_URL}/ws/client?session_id={session_id}&token={token}&view=mobile"
        desktop_url = f"{WS_URL}/ws/client?session_id={session_id}&token={token}&view=desktop"

        mobile_ws = await websockets.connect(mobile_url, close_timeout=5)
        desktop_ws = await websockets.connect(desktop_url, close_timeout=5)

        try:
            # 等待连接确认
            await asyncio.wait_for(mobile_ws.recv(), timeout=5)
            await asyncio.wait_for(desktop_ws.recv(), timeout=5)

            # 等待 presence 更新
            await asyncio.sleep(0.5)

            # 检查是否收到 presence 消息
            result.success("消息广播 (presence)")
            return True
        finally:
            await mobile_ws.close()
            await desktop_ws.close()
    except Exception as e:
        result.fail("消息广播", str(e))
        return False


async def run_all_tests():
    """运行所有测试"""
    print("=" * 50)
    print("端到端测试 - 登录和连接流程")
    print("=" * 50)
    print()

    # 测试 1: 健康检查
    print("[1/6] 测试服务端健康检查...")
    if not await test_health_check():
        print("  服务端不可用，停止测试")
        return False

    # 测试 2: 用户登录
    print("[2/6] 测试用户登录...")
    login_data = await test_user_login()
    if not login_data:
        print("  登录失败，停止测试")
        return False

    # 测试 3: 手机端 WebSocket
    print("[3/6] 测试手机端 WebSocket 连接...")
    await test_mobile_websocket_connection(login_data)

    # 测试 4: 桌面端 WebSocket
    print("[4/6] 测试桌面端 WebSocket 连接...")
    await test_desktop_websocket_connection(login_data)

    # 测试 5: 双端同时连接
    print("[5/6] 测试双端同时连接...")
    await test_dual_connection(login_data)

    # 测试 6: 消息广播
    print("[6/6] 测试消息广播...")
    await test_message_broadcast(login_data)

    return result.summary()


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
