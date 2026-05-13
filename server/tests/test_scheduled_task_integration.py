"""
R062 定时任务集成测试

对着本地 Docker 部署的 Server 跑真实 HTTP 请求，不 mock。

前置条件：
  - rc-server Docker 容器运行中（包含定时任务代码）
  - 测试账号 test/test123 可用
  - 至少一个注册设备（Agent 在线/离线均可）

用法:
  pytest server/tests/test_scheduled_task_integration.py --url http://localhost:8880 -v
  pytest server/tests/test_scheduled_task_integration.py --url https://localhost/rc -v

测试场景：
1.  创建一次性任务 → 201 (Agent 在线) / 409 (Agent 离线)
2.  创建每日重复任务 → 201 / 409
3.  查询任务列表（无过滤）→ 200
4.  按 session_id 过滤查询 → 200
5.  按 status 过滤查询 → 200
6.  删除任务 → 204
7.  删除不存在的任务 → 404
8.  过去时间 execute_at → 400
9.  未鉴权 → 401
10. 验证返回的任务字段完整（Agent 在线时）
11. terminal 不存在 → 404
12. session 不存在 → 404
"""
import os
from datetime import datetime, timezone, timedelta

import pytest

try:
    import httpx
except ImportError:
    pytest.skip("httpx not installed", allow_module_level=True)



# ---------------------------------------------------------------------------
# pytest 命令行参数（pytest_addoption 在 conftest.py 中注册）
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def base_url(request):
    return request.config.getoption("--url").rstrip("/")


@pytest.fixture(scope="session")
def http_client(base_url):
    """创建 httpx 同步客户端，自动处理自签证书。"""
    verify = not base_url.startswith("https://localhost")
    with httpx.Client(verify=verify, timeout=10) as client:
        yield client


@pytest.fixture(scope="session")
def token(http_client, base_url):
    """登录获取 token。"""
    resp = http_client.post(f"{base_url}/api/login", json={
        "username": "test",
        "password": "test123",
    })
    assert resp.status_code == 200, f"登录失败: {resp.text}"
    data = resp.json()
    assert data.get("success"), f"登录失败: {data}"
    return data["token"]


@pytest.fixture(scope="session")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def device_info(http_client, base_url, auth_headers):
    """获取设备、session 和终端信息（不强制 Agent 在线）。"""
    # 获取设备列表
    resp = http_client.get(f"{base_url}/api/runtime/devices", headers=auth_headers)
    assert resp.status_code == 200
    devices = resp.json().get("devices", [])
    assert len(devices) > 0, "没有注册设备，请确保至少有一个 Agent 曾连接过"
    device = devices[0]

    # 获取终端列表，优先选择 live 状态的终端
    terminals_resp = http_client.get(
        f"{base_url}/api/runtime/devices/{device['device_id']}/terminals",
        headers=auth_headers,
    )
    assert terminals_resp.status_code == 200
    terminals = terminals_resp.json().get("terminals", [])
    assert len(terminals) > 0, "没有终端，请确保至少创建过一个终端"
    live_terminal = next((t for t in terminals if t["status"] == "live"), None)
    assert live_terminal is not None, "没有 live 状态的终端，请确保 Agent 在线且有活跃终端"
    terminal_id = live_terminal["terminal_id"]

    return {
        "device_id": device["device_id"],
        "session_id": device["device_id"],  # session_id = device_id
        "terminal_id": terminal_id,
        "agent_online": device.get("agent_online", False),
    }


# ---------------------------------------------------------------------------
# 清理 fixture：测试结束后删除所有测试创建的任务
# ---------------------------------------------------------------------------

_created_task_ids: list[int] = []


@pytest.fixture(autouse=True)
def _track_tasks():
    yield
    # 清理在 session 结束时由 cleanup_all_tasks 处理


@pytest.fixture(scope="session", autouse=True)
def cleanup_all_tasks(http_client, base_url, auth_headers):
    """session 结束后清理所有测试创建的任务。"""
    yield
    for task_id in _created_task_ids:
        try:
            http_client.delete(
                f"{base_url}/api/scheduled-tasks/{task_id}",
                headers=auth_headers,
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------

def _future(hours=1):
    """生成未来时间的 ISO 8601 字符串。"""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


class TestScheduledTaskIntegration:

    def test_01_create_one_time_task(self, http_client, base_url, auth_headers, device_info):
        """创建一次性任务 → 201 (Agent 在线) / 409 (Agent 离线)"""
        resp = http_client.post(f"{base_url}/api/scheduled-tasks", headers=auth_headers, json={
            "session_id": device_info["session_id"],
            "terminal_id": device_info["terminal_id"],
            "text_content": "echo integration-test",
            "execute_at": _future(1),
            "repeat_type": "once",
        })
        if device_info["agent_online"]:
            assert resp.status_code == 201, f"创建失败: {resp.text}"
            data = resp.json()
            assert "id" in data, f"返回数据缺少 id: {data}"
            assert isinstance(data["id"], int)
            _created_task_ids.append(data["id"])
        else:
            assert resp.status_code == 409, f"Agent 离线应返回 409: {resp.status_code} {resp.text}"

    def test_02_create_daily_task(self, http_client, base_url, auth_headers, device_info):
        """创建每日重复任务 → 201 / 409"""
        resp = http_client.post(f"{base_url}/api/scheduled-tasks", headers=auth_headers, json={
            "session_id": device_info["session_id"],
            "terminal_id": device_info["terminal_id"],
            "text_content": "git pull",
            "execute_at": _future(2),
            "repeat_type": "daily",
        })
        if device_info["agent_online"]:
            assert resp.status_code == 201, f"创建失败: {resp.text}"
            data = resp.json()
            _created_task_ids.append(data["id"])
        else:
            assert resp.status_code == 409, f"Agent 离线应返回 409: {resp.status_code} {resp.text}"

    def test_03_list_all_tasks(self, http_client, base_url, auth_headers):
        """查询任务列表（无过滤）→ 200"""
        resp = http_client.get(f"{base_url}/api/scheduled-tasks", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "tasks" in data
        assert isinstance(data["tasks"], list)

    def test_04_list_by_session(self, http_client, base_url, auth_headers, device_info):
        """按 session_id 过滤查询 → 200"""
        resp = http_client.get(
            f"{base_url}/api/scheduled-tasks",
            params={"session_id": device_info["session_id"]},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        for task in data["tasks"]:
            assert task["session_id"] == device_info["session_id"]

    def test_05_list_by_status(self, http_client, base_url, auth_headers):
        """按 status=pending 过滤查询 → 200"""
        resp = http_client.get(
            f"{base_url}/api/scheduled-tasks",
            params={"status": "pending"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        for task in data["tasks"]:
            assert task["status"] == "pending"

    def test_06_list_session_and_status(self, http_client, base_url, auth_headers, device_info):
        """按 session_id + status 组合过滤 → 200"""
        resp = http_client.get(
            f"{base_url}/api/scheduled-tasks",
            params={
                "session_id": device_info["session_id"],
                "status": "pending",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        for task in data["tasks"]:
            assert task["session_id"] == device_info["session_id"]
            assert task["status"] == "pending"

    def test_07_delete_nonexistent_task(self, http_client, base_url, auth_headers):
        """删除不存在的任务 → 404"""
        resp = http_client.delete(
            f"{base_url}/api/scheduled-tasks/999999",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_08_past_execute_at_rejected(self, http_client, base_url, auth_headers, device_info):
        """过去时间 execute_at → 400（在 Agent 检查之前）"""
        past_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        resp = http_client.post(f"{base_url}/api/scheduled-tasks", headers=auth_headers, json={
            "session_id": device_info["session_id"],
            "terminal_id": device_info["terminal_id"],
            "text_content": "past task",
            "execute_at": past_time,
            "repeat_type": "once",
        })
        assert resp.status_code == 400, f"应返回 400: {resp.status_code} {resp.text}"

    def test_09_unauthorized(self, http_client, base_url):
        """未鉴权 → 401"""
        resp = http_client.get(f"{base_url}/api/scheduled-tasks")
        assert resp.status_code in (401, 403), f"应返回 401/403: {resp.status_code}"

    def test_10_task_fields_complete(self, http_client, base_url, auth_headers, device_info):
        """验证返回的任务字段完整（需要 Agent 在线创建任务）"""
        if not device_info["agent_online"]:
            pytest.skip("需要 Agent 在线才能创建任务验证字段")

        execute_at = _future(1)
        create_resp = http_client.post(f"{base_url}/api/scheduled-tasks", headers=auth_headers, json={
            "session_id": device_info["session_id"],
            "terminal_id": device_info["terminal_id"],
            "text_content": "field-check",
            "execute_at": execute_at,
            "repeat_type": "once",
        })
        assert create_resp.status_code == 201
        task_id = create_resp.json()["id"]
        _created_task_ids.append(task_id)

        # 通过列表查询找到这个任务
        resp = http_client.get(
            f"{base_url}/api/scheduled-tasks",
            params={"session_id": device_info["session_id"]},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        tasks = resp.json()["tasks"]
        task = next(t for t in tasks if t["id"] == task_id)

        # 验证字段
        assert task["id"] == task_id
        assert task["session_id"] == device_info["session_id"]
        assert task["terminal_id"] == device_info["terminal_id"]
        assert task["text_content"] == "field-check"
        assert task["execute_at"] is not None
        assert task["repeat_type"] in ("once", "daily")
        assert task["status"] == "pending"
        assert task["created_at"] is not None
        assert task.get("executed_at") is None

    def test_11_nonexistent_terminal(self, http_client, base_url, auth_headers, device_info):
        """terminal 不存在 → 404"""
        resp = http_client.post(f"{base_url}/api/scheduled-tasks", headers=auth_headers, json={
            "session_id": device_info["session_id"],
            "terminal_id": "nonexistent-terminal-404",
            "text_content": "test",
            "execute_at": _future(1),
            "repeat_type": "once",
        })
        assert resp.status_code == 404, f"应返回 404: {resp.status_code} {resp.text}"

    def test_12_nonexistent_session(self, http_client, base_url, auth_headers):
        """session 不存在 → 404"""
        resp = http_client.post(f"{base_url}/api/scheduled-tasks", headers=auth_headers, json={
            "session_id": "nonexistent-session-404",
            "terminal_id": "some-terminal",
            "text_content": "test",
            "execute_at": _future(1),
            "repeat_type": "once",
        })
        assert resp.status_code == 404, f"应返回 404: {resp.status_code} {resp.text}"

    def test_13_delete_task_full_flow(self, http_client, base_url, auth_headers, device_info):
        """创建 → 删除 → 再删返回 404（需要 Agent 在线）"""
        if not device_info["agent_online"]:
            pytest.skip("需要 Agent 在线才能创建任务")

        create_resp = http_client.post(f"{base_url}/api/scheduled-tasks", headers=auth_headers, json={
            "session_id": device_info["session_id"],
            "terminal_id": device_info["terminal_id"],
            "text_content": "to-be-deleted",
            "execute_at": _future(1),
            "repeat_type": "once",
        })
        assert create_resp.status_code == 201
        task_id = create_resp.json()["id"]

        # 删除
        resp = http_client.delete(
            f"{base_url}/api/scheduled-tasks/{task_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 204, f"删除失败: {resp.text}"

        # 再删除一次 → 404
        resp2 = http_client.delete(
            f"{base_url}/api/scheduled-tasks/{task_id}",
            headers=auth_headers,
        )
        assert resp2.status_code == 404

    def test_14_close_terminal_cancels_scheduled_tasks(self, http_client, base_url, auth_headers, device_info):
        """关闭终端后，该终端的 pending 定时任务自动变为 cancelled。"""
        if not device_info["agent_online"]:
            pytest.skip("需要 Agent 在线才能创建任务")

        # 0. 创建专用终端（不影响 fixture 终端）
        import time as _time
        test_terminal_id = f"cancel-test-{int(_time.time())}"
        create_term_resp = http_client.post(
            f"{base_url}/api/runtime/devices/{device_info['device_id']}/terminals",
            headers=auth_headers,
            json={"title": "cancel-test", "cwd": "~", "command": "/bin/bash", "terminal_id": test_terminal_id},
        )
        assert create_term_resp.status_code in (200, 201), f"创建测试终端失败: {create_term_resp.text}"

        # 等待终端变为 live（最多 10 秒）
        terminal_live = False
        for _ in range(10):
            _time.sleep(1)
            t_resp = http_client.get(
                f"{base_url}/api/runtime/devices/{device_info['device_id']}/terminals",
                headers=auth_headers,
            )
            t = next((t for t in t_resp.json()["terminals"] if t["terminal_id"] == test_terminal_id), None)
            if t and t["status"] == "live":
                terminal_live = True
                break
        if not terminal_live:
            pytest.skip("测试终端未变为 live，跳过")

        # 1. 创建定时任务
        create_resp = http_client.post(f"{base_url}/api/scheduled-tasks", headers=auth_headers, json={
            "session_id": device_info["session_id"],
            "terminal_id": test_terminal_id,
            "text_content": "should-be-cancelled",
            "execute_at": _future(3),
            "repeat_type": "once",
        })
        assert create_resp.status_code == 201
        task_id = create_resp.json()["id"]
        _created_task_ids.append(task_id)

        # 2. 确认任务为 pending
        list_resp = http_client.get(
            f"{base_url}/api/scheduled-tasks",
            params={"session_id": device_info["session_id"], "status": "pending"},
            headers=auth_headers,
        )
        assert list_resp.status_code == 200
        pending_tasks = [t for t in list_resp.json()["tasks"] if t["id"] == task_id]
        assert len(pending_tasks) == 1
        assert pending_tasks[0]["status"] == "pending"

        # 3. 关闭测试终端（不影响 fixture 终端）
        close_resp = http_client.delete(
            f"{base_url}/api/runtime/devices/{device_info['device_id']}/terminals/{test_terminal_id}",
            headers=auth_headers,
        )
        assert close_resp.status_code == 200, f"关闭终端失败: {close_resp.text}"

        # 4. 查询 cancelled 任务，确认任务已被取消
        cancelled_resp = http_client.get(
            f"{base_url}/api/scheduled-tasks",
            params={"session_id": device_info["session_id"], "status": "cancelled"},
            headers=auth_headers,
        )
        assert cancelled_resp.status_code == 200
        cancelled_tasks = [t for t in cancelled_resp.json()["tasks"] if t["id"] == task_id]
        assert len(cancelled_tasks) == 1, "关闭终端后定时任务应变为 cancelled"
        assert cancelled_tasks[0]["status"] == "cancelled"
