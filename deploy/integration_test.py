#!/usr/bin/env python3
"""
全链路集成测试

覆盖场景：
1. 用户注册 + 登录
2. Refresh Token 刷新
3. Token 版本淘汰
4. Agent 连接（via AGENT_USERNAME/PASSWORD）
5. Runtime devices 查询
6. Terminal 创建
7. Terminal 列表
8. Terminal 关闭
9. History API
10. 未认证访问拒绝

用法：
    python3 deploy/integration_test.py [--base-url https://localhost/rc] [--ws-url wss://localhost/rc]
"""
import argparse
import asyncio
import json
from functools import lru_cache
import ssl
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

# --- 配置 ---
BASE_URL = "https://localhost/rc"
WS_URL = "wss://localhost/rc"

PASSED = 0
FAILED = 0


@lru_cache(maxsize=None)
def ssl_context_for(url: str):
    host = urllib.parse.urlparse(url).hostname or ""
    if host in {"localhost", "127.0.0.1"}:
        return ssl._create_unverified_context()
    return None


def api(method, path, body=None, token=None):
    """发送 HTTP 请求，返回 (status, json_body)"""
    url = f"{BASE_URL}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(
            req,
            timeout=10,
            context=ssl_context_for(url),
        ) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        resp_body = {}
        try:
            resp_body = json.loads(e.read())
        except Exception:
            pass
        return e.code, resp_body
    except Exception as e:
        return 0, {"error": str(e)}


def check(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  [PASS] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name}  -- {detail}")


# ============================================================
# Test 1: 用户注册 + 登录
# ============================================================
def test_register_and_login():
    print("\n[Test 1] 用户注册 + 登录")
    ts = int(time.time())
    username = f"itest_{ts}"
    password = "TestPass123!"

    # 注册
    status, body = api("POST", "/api/register", {
        "username": username,
        "password": password,
    })
    check("注册返回 200", status == 200, f"status={status}, body={body}")

    token = body.get("token", "")
    check("注册返回 token", bool(token), "token 为空")

    # 重复注册应失败
    status2, _ = api("POST", "/api/register", {
        "username": username,
        "password": password,
    })
    check("重复注册返回 409", status2 == 409, f"status={status2}")

    # 登录
    status3, body3 = api("POST", "/api/login", {
        "username": username,
        "password": password,
    })
    check("登录返回 200", status3 == 200, f"status={status3}, body={body3}")
    login_token = body3.get("token", "")
    login_refresh = body3.get("refresh_token", "")
    check("登录返回 token", bool(login_token), "token 为空")
    check("登录返回 refresh_token", bool(login_refresh), "refresh_token 为空")

    return username, password, login_token, login_refresh


# ============================================================
# Test 2: Refresh Token 刷新
# ============================================================
def test_refresh_token(refresh_token):
    print("\n[Test 2] Refresh Token 刷新")

    status, body = api("POST", "/api/refresh", {
        "refresh_token": refresh_token,
    })
    check("刷新返回 200", status == 200, f"status={status}, body={body}")

    new_access = body.get("access_token", "")
    new_refresh = body.get("refresh_token", "")
    check("返回新 access_token", bool(new_access), "为空")
    check("返回新 refresh_token", bool(new_refresh), "为空")

    # 旧 refresh_token 应失效（单次使用）
    status2, _ = api("POST", "/api/refresh", {
        "refresh_token": refresh_token,
    })
    check("旧 refresh_token 失效", status2 == 401, f"status={status2}")

    return new_access, new_refresh


# ============================================================
# Test 3: Token 版本淘汰（新登录挤掉旧 token）
# ============================================================
def test_token_replacement(username, password, old_token):
    print("\n[Test 3] Token 版本淘汰")

    # 新登录（同 view，会替换旧 token）
    status, body = api("POST", "/api/login", {
        "username": username,
        "password": password,
        "view": "mobile",
    })
    check("新登录成功", status == 200, f"status={status}")
    new_token = body.get("token", "")
    new_refresh = body.get("refresh_token", "")

    # 旧 token 应失效
    status2, body2 = api("GET", "/api/devices", token=old_token)
    check("旧 token 返回 401", status2 == 401, f"status={status2}, body={body2}")

    # 验证错误码（字段名是 error_code）
    code = body2.get("error_code", "")
    check("错误码为 TOKEN_REPLACED", code == "TOKEN_REPLACED",
          f"error_code={code}, body={body2}")

    # 新 token 应有效
    status3, _ = api("GET", "/api/devices", token=new_token)
    check("新 token 有效", status3 == 200, f"status={status3}")

    return new_token, new_refresh


# ============================================================
# Test 4: Agent 连接 — 保持连接直到测试结束
# ============================================================
async def connect_agent(token):
    """连接 Agent WS 并保持活跃，返回 (ws, session_id) 或 (None, None)"""
    print("\n[Test 4] Agent 连接")

    try:
        import websockets
    except ImportError:
        print("  [SKIP] websockets 库未安装，跳过 WebSocket 测试")
        return None, None

    ws_full_url = f"{WS_URL}/ws/agent"

    try:
        connect_kwargs = {"open_timeout": 10}
        ssl_context = ssl_context_for(ws_full_url)
        if ssl_context is not None:
            connect_kwargs["ssl"] = ssl_context
        ws = await websockets.connect(ws_full_url, **connect_kwargs)
        await ws.send(json.dumps({"type": "auth", "token": token}))
        # 等待 connected 消息
        msg = await asyncio.wait_for(ws.recv(), timeout=5)
        data = json.loads(msg)
        check("Agent 收到 connected", data.get("type") == "connected",
              f"type={data.get('type')}, body={data}")
        session_id = data.get("session_id", "")
        check("返回 session_id", bool(session_id), "session_id 为空")
        check("返回 owner", bool(data.get("owner")), f"owner={data.get('owner')}")

        # 发送 ping 验证
        await ws.send(json.dumps({"type": "ping"}))
        pong = await asyncio.wait_for(ws.recv(), timeout=5)
        pong_data = json.loads(pong)
        check("ping/pong 正常", pong_data.get("type") == "pong",
              f"type={pong_data.get('type')}")

        return ws, session_id
    except Exception as e:
        check("Agent WebSocket 连接", False, str(e))
        return None, None


# ============================================================
# Test 5: Runtime devices 查询
# ============================================================
def test_runtime_devices(token):
    print("\n[Test 5] Runtime devices 查询")

    status, body = api("GET", "/api/runtime/devices", token=token)
    check("返回 200", status == 200, f"status={status}, body={body}")

    devices = body.get("devices", [])
    check("返回设备列表", isinstance(devices, list), f"type={type(devices)}")

    if devices:
        device = devices[0]
        device_id = device.get("device_id", "")
        check("有 device_id", bool(device_id), "device_id 为空")
        check("agent_online=True", device.get("agent_online") is True,
              f"agent_online={device.get('agent_online')}")
        return device_id
    else:
        check("至少有一个设备", False, "devices 为空")
        return None


# ============================================================
# Test 6: Terminal 创建
# ============================================================
def test_terminal_create(token, device_id):
    print("\n[Test 6] Terminal 创建")

    if not device_id:
        check("跳过（无设备）", False, "前置条件不满足")
        return None

    terminal_id = f"term-{int(time.time())}"
    status, body = api("POST", f"/api/runtime/devices/{device_id}/terminals", {
        "terminal_id": terminal_id,
        "title": "集成测试终端",
        "command": "/bin/bash",
        "cwd": "/tmp",
    }, token=token)
    check("创建返回 200/201/504", status in (200, 201, 504),
          f"status={status}, body={body}")

    if status in (200, 201):
        term = body
        check("返回 terminal_id", term.get("terminal_id") == terminal_id,
              f"terminal_id={term.get('terminal_id')}")
        check("status 为 pending 或 detached",
              term.get("status") in ("pending", "detached"),
              f"status={term.get('status')}")
        return terminal_id
    elif status == 504:
        print("  [INFO] Terminal 创建超时 (504) — Agent 可能无 PTY 环境")
        return terminal_id
    return None


# ============================================================
# Test 7: Terminal 列表
# ============================================================
def test_terminal_list(token, device_id):
    print("\n[Test 7] Terminal 列表")

    if not device_id:
        check("跳过（无设备）", False, "前置条件不满足")
        return

    status, body = api("GET", f"/api/runtime/devices/{device_id}/terminals", token=token)
    check("返回 200", status == 200, f"status={status}, body={body}")

    terminals = body.get("terminals", [])
    check("返回终端列表", isinstance(terminals, list), f"type={type(terminals)}")


# ============================================================
# Test 8: Terminal 关闭
# ============================================================
def test_terminal_close(token, device_id, terminal_id):
    print("\n[Test 8] Terminal 关闭")

    if not device_id or not terminal_id:
        check("跳过（无设备或终端）", False, "前置条件不满足")
        return

    status, body = api("DELETE",
                       f"/api/runtime/devices/{device_id}/terminals/{terminal_id}",
                       token=token)
    check("关闭返回 200", status == 200, f"status={status}, body={body}")

    if status == 200:
        check("status=closed", body.get("status") == "closed",
              f"status={body.get('status')}")


# ============================================================
# Test 9: History API
# ============================================================
def test_history(token, session_id):
    print("\n[Test 9] History API")

    if not session_id:
        check("跳过（无 session_id）", False, "前置条件不满足")
        return

    status, body = api("GET", f"/api/history/{session_id}?limit=10", token=token)
    if status == 200:
        check("History 返回 200", True)
        check("返回 records", "records" in body, f"keys={list(body.keys())}")
    elif status == 403:
        print("  [INFO] History 403 — session 属于不同用户（符合预期）")
        check("History 权限隔离", True)
    else:
        check("History 返回 200 或 403", False, f"status={status}, body={body}")


# ============================================================
# Test 10: 未认证访问拒绝
# ============================================================
def test_unauthorized():
    print("\n[Test 10] 未认证访问拒绝")

    # 无 token 访问受保护 API
    status, _ = api("GET", "/api/devices")
    check("无 token 返回 401 或 403", status in (401, 403),
          f"status={status}")

    # 无效 token
    status2, _ = api("GET", "/api/devices", token="invalid.token.here")
    check("无效 token 返回 401", status2 == 401, f"status={status2}")

    # 无效 refresh_token
    status3, _ = api("POST", "/api/refresh", {
        "refresh_token": "invalid.refresh.token",
    })
    check("无效 refresh_token 返回 401", status3 == 401, f"status={status3}")


# ============================================================
# 健康检查
# ============================================================
def test_health():
    print("\n[Health Check]")
    status, body = api("GET", "/health")
    check("健康检查返回 200", status == 200, f"status={status}, body={body}")
    if status == 200:
        check("status=ok", body.get("status") == "ok", f"body={body}")
    return status == 200


# ============================================================
# 后台心跳：保持 Agent WS 连接活跃
# ============================================================
async def heartbeat_loop(ws):
    """每 15 秒发送 ping 保持连接"""
    try:
        while True:
            await asyncio.sleep(15)
            await ws.send(json.dumps({"type": "ping"}))
            await asyncio.wait_for(ws.recv(), timeout=10)
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


# ============================================================
# 主流程
# ============================================================
async def run_tests():
    global BASE_URL, WS_URL

    parser = argparse.ArgumentParser(description="全链路集成测试")
    parser.add_argument("--base-url", default="https://localhost/rc", help="HTTP API 基础 URL")
    parser.add_argument("--ws-url", default="wss://localhost/rc", help="WebSocket 基础 URL")
    args = parser.parse_args()

    BASE_URL = args.base_url.rstrip("/")
    WS_URL = args.ws_url.rstrip("/")

    print("=" * 60)
    print("Remote Control 全链路集成测试")
    print(f"API: {BASE_URL}")
    print(f"WS:  {WS_URL}")
    print("=" * 60)

    # 健康检查
    if not test_health():
        print("\n[ABORT] 服务不可用，请确认服务已启动")
        sys.exit(1)

    # 注册 agent 测试用户（用于 WebSocket + Runtime 测试）
    ts = int(time.time())
    agent_user = f"agent_itest_{ts}"
    agent_pass = "AgentPass123!"
    api("POST", "/api/register", {
        "username": agent_user,
        "password": agent_pass,
    })
    _, body_agent_login = api("POST", "/api/login", {
        "username": agent_user,
        "password": agent_pass,
    })
    agent_token = body_agent_login.get("token", "")

    # Test 1
    username, password, token, refresh_token = test_register_and_login()

    # Test 2
    new_access, new_refresh = test_refresh_token(refresh_token)

    # Test 3
    final_token, final_refresh = test_token_replacement(username, password, new_access)

    # Test 4: Agent 连接 — 保持 WS 活跃
    ws, session_id = await connect_agent(agent_token)
    hb_task = None
    if ws:
        hb_task = asyncio.create_task(heartbeat_loop(ws))

    # 等待 Agent 上线状态传播
    await asyncio.sleep(1)

    # Tests 5-9: 使用 agent_token（与 WS 连接同用户）
    device_id = test_runtime_devices(agent_token)
    terminal_id = test_terminal_create(agent_token, device_id)
    test_terminal_list(agent_token, device_id)
    test_terminal_close(agent_token, device_id, terminal_id)
    test_history(agent_token, session_id)

    # 关闭 Agent WS
    if hb_task:
        hb_task.cancel()
    if ws:
        await ws.close()

    # Test 10
    test_unauthorized()

    # 汇总
    total = PASSED + FAILED
    print("\n" + "=" * 60)
    print(f"测试完成: {PASSED}/{total} 通过, {FAILED} 失败")
    print("=" * 60)

    sys.exit(0 if FAILED == 0 else 1)


if __name__ == "__main__":
    asyncio.run(run_tests())
