"""
端到端系统测试：复现 agent 断连问题

启动真实 agent 进程 → 连真实 Docker server → 监控连接是否断开

使用方法：
    cd remote-control
    python3 tests/test_e2e_agent_connection.py

前置条件：
    1. Docker server 已启动 (docker compose up -d)
    2. agent 依赖已安装 (cd agent && pip install -e .)

诊断项：
    T1: Agent 进程启动并连接 server
    T2: Agent 保持连接 3 分钟不断开
    T3: Client 连接/断开后 Agent 仍存活
    T4: 模拟移动端后台（Client 反复连接断开）后 Agent 仍存活
    T5: 创建终端后 Agent 仍存活
    T6: 全链路：Agent 连接 → Client 连接 → 创建终端 → 收发数据 → Agent 仍存活
"""
import asyncio
import json
import os
import signal
import subprocess
import sys
import threading
import time
import traceback

import httpx

# ─── 基础工具 ───


async def login(server_url: str, username: str = "test") -> dict:
    """登录获取 token"""
    http_url = server_url.replace("ws://", "http://").replace("wss://", "https://")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{http_url}/api/login",
            json={"username": username, "password": "test123"},
        )
        assert resp.status_code == 200, f"登录失败: {resp.status_code} {resp.text}"
        data = resp.json()
        print(f"  [OK] 登录成功: session_id={data.get('session_id')}")
        return data


async def get_server_status(server_url: str, session_id: str) -> dict:
    """从服务端 API 获取 session 状态"""
    http_url = server_url.replace("ws://", "http://").replace("wss://", "https://")
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{http_url}/api/sessions/{session_id}")
        if resp.status_code == 200:
            return resp.json()
        return {}


async def check_agent_online_via_ws(server_url: str, session_id: str) -> bool:
    """通过 Client WebSocket 连接检查 agent 是否在线"""
    try:
        import websockets
    except ImportError:
        return False

    login_data = await login(server_url)
    token = login_data["token"]
    ws_url = f"{server_url}/ws/client?session_id={session_id}&token={token}&view=mobile"

    try:
        async with websockets.connect(ws_url) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(msg)
            return data.get("agent_online", False)
    except Exception:
        return False


async def check_agent_online_via_http(server_url: str, session_id: str) -> bool:
    """通过 HTTP API 检查 agent 是否在线（读 Redis 数据）"""
    http_url = server_url.replace("ws://", "http://").replace("wss://", "https://")
    try:
        async with httpx.AsyncClient() as client:
            # 登录获取 token
            login_data = await login(server_url)
            token = login_data["token"]

            resp = await client.get(
                f"{http_url}/api/runtime/devices",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
            if resp.status_code != 200:
                return False
            data = resp.json()
            devices = data.get("devices", [])
            for device in devices:
                # runtime_api 的 _device_online 优先查内存 active_agents，
                # 所以这里的 agent_online 反映了 server 的真实判断
                if device.get("device_id") == session_id:
                    return device.get("agent_online", False)
            return False
    except Exception:
        return False


# ─── Agent 进程管理 ───


class AgentProcess:
    """管理真实 agent 子进程"""

    def __init__(self, server_url: str, token: str, workdir: str):
        self.server_url = server_url
        self.token = token
        self.workdir = workdir
        self.process: subprocess.Popen | None = None
        self.log_lines: list[str] = []
        self._connected_event = asyncio.Event()
        self._reader_thread: threading.Thread | None = None

    def start(self):
        """启动 agent 进程（模拟 Flutter 的 Process.start）"""
        cmd = [
            sys.executable, "-m", "app.cli",
            "start",
            "--server", self.server_url,
            "--token", self.token,
            "--command", "/bin/bash",
            "--no-reconnect",
        ]

        print(f"  [INFO] 启动 agent 进程: {' '.join(cmd)}")
        print(f"  [INFO] 工作目录: {self.workdir}")

        self.process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=self.workdir,
        )
        self._start_time = time.time()

        # 后台线程持续读取输出
        def _reader():
            while True:
                line = self.process.stdout.readline()
                if not line:
                    break
                self.log_lines.append(line.decode("utf-8", errors="replace"))

        self._reader_thread = threading.Thread(target=_reader, daemon=True)
        self._reader_thread.start()
        print(f"  [OK] Agent 进程已启动: PID={self.process.pid}")

    async def wait_for_connected(self, timeout: float = 15) -> bool:
        """等待 agent 输出 "已连接到服务器" 或 "会话已建立" """
        deadline = time.time() + timeout
        while time.time() < deadline:
            for line in self.log_lines:
                if "会话已建立" in line or ("已连接到服务器" in line and "[Agent]" in line):
                    print(f"  [OK] Agent 已连接: {line.strip()}")
                    return True
                if "运行错误" in line or "连接错误" in line:
                    print(f"  [FAIL] Agent 连接错误: {line.strip()}")
                    return False
            await asyncio.sleep(0.5)

        print(f"  [FAIL] Agent 连接超时 ({timeout}s)，最近日志:")
        for line in self.log_lines[-15:]:
            print(f"    {line.rstrip()}")
        return False

    def _read_output(self):
        """已由后台线程持续读取，此方法保留兼容"""
        pass

    def is_alive(self) -> bool:
        """检查 agent 进程是否存活"""
        if not self.process:
            return False
        return self.process.poll() is None

    @property
    def uptime(self) -> float:
        """进程运行时长（秒）"""
        return time.time() - self._start_time

    def recent_logs(self, count: int = 20) -> list[str]:
        """最近的日志"""
        self._read_output()
        return self.log_lines[-count:]

    def stop(self):
        """停止 agent 进程"""
        if self.process and self.is_alive():
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
            print(f"  [INFO] Agent 进程已停止 (运行了 {self.uptime:.0f} 秒)")


# ─── 测试用例 ───


async def test_t1_agent_starts_and_connects(server_url: str):
    """T1: Agent 进程启动并连接 server"""
    print("\n" + "=" * 60)
    print("T1: Agent 进程启动并连接 server")
    print("=" * 60)

    login_data = await login(server_url)
    token = login_data["token"]
    session_id = login_data["session_id"]

    agent_dir = os.path.join(os.path.dirname(__file__), "..", "agent")
    agent = AgentProcess(server_url, token, agent_dir)

    try:
        agent.start()
        connected = await agent.wait_for_connected(timeout=15)

        if not connected:
            print("  [FAIL] Agent 未能连接")
            return False, agent

        # 验证服务端也认为 agent 在线
        await asyncio.sleep(1)
        online_ws = await check_agent_online_via_ws(server_url, session_id)
        online_http = await check_agent_online_via_http(server_url, session_id)
        print(f"  [{'OK' if online_ws else 'FAIL'}] WebSocket agent_online={online_ws}")
        print(f"  [{'OK' if online_http else 'FAIL'}] HTTP API agent_online={online_http}")

        return online_ws and online_http, agent

    except Exception as e:
        print(f"  [FAIL] 异常: {e}")
        traceback.print_exc()
        return False, agent


async def test_t2_agent_stays_connected(server_url: str, agent: AgentProcess,
                                        session_id: str, duration: float = 180):
    """T2: Agent 保持连接 N 秒不断开"""
    print(f"\n{'=' * 60}")
    print(f"T2: Agent 保持连接 {duration} 秒不断开")
    print("=" * 60)

    start = time.time()
    check_interval = 10

    while time.time() - start < duration:
        await asyncio.sleep(check_interval)
        elapsed = time.time() - start

        # 检查进程是否存活
        alive = agent.is_alive()
        # 检查服务端是否认为在线
        online = await check_agent_online_via_ws(server_url, session_id)

        status = "OK" if alive and online else "FAIL"
        print(f"  [{status}] {elapsed:.0f}s — 进程存活={alive} 服务端在线={online}")

        if not alive:
            logs = agent.recent_logs(10)
            print("  [FAIL] Agent 进程已退出，最近日志:")
            for log in logs:
                print(f"    {log.rstrip()}")
            return False

        if not online:
            logs = agent.recent_logs(10)
            print("  [FAIL] 服务端认为 agent 离线，最近日志:")
            for log in logs:
                print(f"    {log.rstrip()}")
            return False

    print(f"  [OK] Agent 稳定存活 {duration} 秒")
    return True


async def test_t3_client_connect_disconnect(server_url: str, session_id: str):
    """T3: Client 连接/断开后 Agent 仍存活"""
    print(f"\n{'=' * 60}")
    print("T3: Client 连接/断开 3 轮，检查 Agent 是否存活")
    print("=" * 60)

    login_data = await login(server_url)
    token = login_data["token"]

    try:
        import websockets
    except ImportError:
        print("  [SKIP] websockets 库未安装")
        return True

    for i in range(3):
        ws_url = f"{server_url}/ws/client?session_id={session_id}&token={token}&view=mobile"
        try:
            async with websockets.connect(ws_url) as ws:
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                data = json.loads(msg)
                online = data.get("agent_online", False)
                print(f"  [OK] Client 第 {i+1} 次连接: agent_online={online}")
                await asyncio.sleep(2)
            print(f"  [OK] Client 第 {i+1} 次断开")
            await asyncio.sleep(1)
        except Exception as e:
            print(f"  [WARN] Client 第 {i+1} 次操作异常: {e}")

    return True


async def test_t4_simulate_mobile_background(server_url: str, session_id: str):
    """T4: 模拟移动端后台（Client 反复连接-断开）后 Agent 仍存活"""
    print(f"\n{'=' * 60}")
    print("T4: 模拟移动端后台行为 — 快速连接断开 10 次")
    print("=" * 60)

    try:
        import websockets
    except ImportError:
        print("  [SKIP] websockets 库未安装")
        return True

    for i in range(10):
        login_data = await login(server_url)
        token = login_data["token"]
        ws_url = f"{server_url}/ws/client?session_id={session_id}&token={token}&view=mobile"
        try:
            async with websockets.connect(ws_url) as ws:
                msg = await asyncio.wait_for(ws.recv(), timeout=3)
                data = json.loads(msg)
        except Exception as e:
            print(f"  [WARN] 第 {i+1} 次连接异常: {e}")
        # 不等待，模拟 app 切到后台立刻断开
        await asyncio.sleep(0.5)

    print("  [OK] 10 次快速连接断开完成")
    return True


async def test_t5_create_terminal(server_url: str, session_id: str):
    """T5: 创建终端后 Agent 仍存活"""
    print(f"\n{'=' * 60}")
    print("T5: 创建终端 — 检查 Agent 是否存活")
    print("=" * 60)

    login_data = await login(server_url)
    token = login_data["token"]
    http_url = server_url.replace("ws://", "http://").replace("wss://", "https://")

    terminal_id = f"e2e-test-{int(time.time())}"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{http_url}/api/sessions/{session_id}/terminals",
            json={"terminal_id": terminal_id, "title": "E2E Test"},
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code in (200, 201):
            print(f"  [OK] 终端创建成功: {terminal_id}")
        else:
            print(f"  [INFO] 终端创建响应: {resp.status_code} {resp.text[:200]}")

    return True


async def test_t6_full_flow(server_url: str):
    """T6: 全链路 — Agent → Client → 终端 → 数据 → 存活"""
    print(f"\n{'=' * 60}")
    print("T6: 全链路 — Agent 连接 → Client 连接 → 终端 → 数据 → 存活")
    print("=" * 60)

    try:
        import websockets
    except ImportError:
        print("  [SKIP] websockets 库未安装")
        return True

    login_data = await login(server_url)
    token = login_data["token"]
    session_id = login_data["session_id"]

    # 1. Client 连接
    ws_url = f"{server_url}/ws/client?session_id={session_id}&token={token}&view=desktop"
    try:
        async with websockets.connect(ws_url) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(msg)
            agent_online = data.get("agent_online", False)
            print(f"  [{'OK' if agent_online else 'WARN'}] Client 连接: agent_online={agent_online}")

            if not agent_online:
                print("  [WARN] Agent 不在线，跳过终端测试")
                return True

            # 2. 创建终端
            terminal_id = f"e2e-flow-{int(time.time())}"
            await ws.send(json.dumps({
                "type": "create_terminal",
                "terminal_id": terminal_id,
                "title": "E2E Full Flow",
            }))

            # 等待终端创建响应
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=10)
                rdata = json.loads(response)
                print(f"  [INFO] 终端响应: type={rdata.get('type')}")

                if rdata.get("type") == "terminal_created":
                    # 3. 发送数据
                    import base64
                    await ws.send(json.dumps({
                        "type": "data",
                        "terminal_id": terminal_id,
                        "payload": base64.b64encode(b"echo hello\n").decode(),
                    }))
                    print(f"  [OK] 已发送测试数据")

                    # 等待输出
                    try:
                        response = await asyncio.wait_for(ws.recv(), timeout=5)
                        rdata2 = json.loads(response)
                        print(f"  [OK] 收到输出: type={rdata2.get('type')}")
                    except asyncio.TimeoutError:
                        print(f"  [INFO] 等待输出超时（可能终端响应慢）")
            except asyncio.TimeoutError:
                print(f"  [WARN] 终端创建超时")

            # 4. 保持连接 30 秒
            print("  [INFO] 保持 Client 连接 30 秒...")
            await asyncio.sleep(30)
            print("  [OK] 30 秒后 Client 仍连接")

    except Exception as e:
        print(f"  [WARN] 全链路测试异常: {type(e).__name__}: {e}")

    return True


# ─── 主流程 ───


async def main():
    server_url = "ws://localhost:8888"

    print("=" * 60)
    print("端到端系统测试 — 复现 Agent 断连问题")
    print(f"服务器: {server_url}")
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 前置检查
    http_url = server_url.replace("ws://", "http://")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{http_url}/health", timeout=5)
            if resp.status_code != 200:
                print(f"[FAIL] Server 健康检查失败: {resp.status_code}")
                return 1
            print(f"[OK] Server 健康检查通过")
    except Exception as e:
        print(f"[FAIL] Server 不可达: {e}")
        print("请先启动 Docker: docker compose up -d")
        return 1

    results = {}
    agent = None
    session_id = None

    # T1: 启动 agent 并连接
    passed, agent = await test_t1_agent_starts_and_connects(server_url)
    results["T1_agent_connects"] = passed

    if not passed:
        print("\n[ABORT] Agent 无法连接，终止测试")
        if agent:
            print("\nAgent 日志:")
            for log in agent.recent_logs(30):
                print(f"  {log.rstrip()}")
            agent.stop()
        _print_summary(results)
        return 1

    # 获取 session_id（从 agent 日志中提取）
    for line in agent.log_lines:
        if "session_id" in line:
            try:
                # 尝试从日志中提取 session_id
                import re
                match = re.search(r'session_id[=:]\s*"?([a-f0-9-]+)"?', line)
                if match:
                    session_id = match.group(1)
                    break
            except Exception:
                pass

    if not session_id:
        # 用 agent 的 token 登录来获取 session_id
        login_data = await login(server_url)
        session_id = login_data["session_id"]

    print(f"\n[INFO] 使用 session_id={session_id}")

    # T2: 保持连接 180 秒（3 分钟）
    passed = await test_t2_agent_stays_connected(server_url, agent, session_id, duration=180)
    results["T2_agent_stable_3min"] = passed

    if not passed:
        print("\n[FOUND] T2 失败 — Agent 在 3 分钟内断连！")
        print("Agent 最后 20 条日志:")
        for log in agent.recent_logs(20):
            print(f"  {log.rstrip()}")
        agent.stop()
        _print_summary(results)
        return 1

    # T3: Client 连接/断开
    passed = await test_t3_client_connect_disconnect(server_url, session_id)
    # T3 后检查 agent 是否存活
    if agent and agent.is_alive():
        online = await check_agent_online_via_ws(server_url, session_id)
        passed = passed and online
        print(f"  [{'OK' if online else 'FAIL'}] T3 后 agent 状态: 进程存活={agent.is_alive()} 在线={online}")
    else:
        passed = False
        print("  [FAIL] T3 后 agent 进程已退出")
    results["T3_client_connect_disconnect"] = passed

    # T4: 模拟移动端后台
    passed = await test_t4_simulate_mobile_background(server_url, session_id)
    if agent and agent.is_alive():
        online = await check_agent_online_via_ws(server_url, session_id)
        passed = passed and online
        print(f"  [{'OK' if online else 'FAIL'}] T4 后 agent 状态: 进程存活={agent.is_alive()} 在线={online}")
    else:
        passed = False
        print("  [FAIL] T4 后 agent 进程已退出")
    results["T4_mobile_background"] = passed

    # T5: 创建终端
    passed = await test_t5_create_terminal(server_url, session_id)
    if agent and agent.is_alive():
        online = await check_agent_online_via_ws(server_url, session_id)
        passed = passed and online
        print(f"  [{'OK' if online else 'FAIL'}] T5 后 agent 状态: 进程存活={agent.is_alive()} 在线={online}")
    else:
        passed = False
        print("  [FAIL] T5 后 agent 进程已退出")
    results["T5_create_terminal"] = passed

    # T6: 全链路
    passed = await test_t6_full_flow(server_url)
    if agent and agent.is_alive():
        online = await check_agent_online_via_ws(server_url, session_id)
        passed = passed and online
        print(f"  [{'OK' if online else 'FAIL'}] T6 后 agent 状态: 进程存活={agent.is_alive()} 在线={online}")
    else:
        passed = False
        print("  [FAIL] T6 后 agent 进程已退出")
    results["T6_full_flow"] = passed

    # 最终检查：agent 是否一直存活
    print(f"\n{'=' * 60}")
    print("最终检查 — Agent 状态")
    print("=" * 60)

    if agent:
        alive = agent.is_alive()
        online = await check_agent_online_via_ws(server_url, session_id)
        uptime = agent.uptime
        print(f"  进程存活: {alive}")
        print(f"  服务端在线: {online}")
        print(f"  运行时长: {uptime:.0f} 秒")
        results["final_agent_alive"] = alive and online

        if not alive or not online:
            print("\n  Agent 最后 30 条日志:")
            for log in agent.recent_logs(30):
                print(f"    {log.rstrip()}")

        agent.stop()

    _print_summary(results)
    return 0 if all(results.values()) else 1


def _print_summary(results: dict):
    print(f"\n{'=' * 60}")
    print("测试结果汇总:")
    print("=" * 60)
    all_passed = True
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    if all_passed:
        print("\n全部通过! Agent 连接稳定，未复现断连。")
    else:
        print("\n存在失败项，已定位到断连场景。")
        # 输出诊断建议
        if not results.get("T1_agent_connects", True):
            print("\n诊断建议: Agent 无法启动或连接。检查:")
            print("  1. agent 目录依赖是否完整 (pip install -e .)")
            print("  2. server URL 是否可达")
            print("  3. agent 进程日志中的错误信息")
        elif not results.get("T2_agent_stable_3min", True):
            print("\n诊断建议: Agent 在 3 分钟内断连。检查:")
            print("  1. websockets 库版本和 ping_interval 配置")
            print("  2. server 心跳检查器是否误判超时")
            print("  3. Docker 网络连接是否稳定")
        elif not results.get("T3_client_connect_disconnect", True):
            print("\n诊断建议: Client 连接/断开导致 Agent 断连。检查:")
            print("  1. server _cleanup_client 是否误清理 agent")
            print("  2. broadcast 操作是否阻塞 agent 消息循环")
        elif not results.get("T4_mobile_background", True):
            print("\n诊断建议: 模拟移动端后台导致 Agent 断连。检查:")
            print("  1. 多次快速 client 连接断开是否触发 server 竞态")
            print("  2. session 状态更新是否与 agent 心跳冲突")
        elif not results.get("T5_create_terminal", True) or not results.get("T6_full_flow", True):
            print("\n诊断建议: 终端操作导致 Agent 断连。检查:")
            print("  1. terminal_created 广播是否影响 agent 消息处理")
            print("  2. PTY 启动是否阻塞 agent 的心跳循环")


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
