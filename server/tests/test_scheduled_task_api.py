"""
B002 测试: 定时任务 REST API 单元测试

POST /api/scheduled-tasks 测试:
- [happy] 创建成功 → 201
- [validation] execute_at 在过去 → 400
- [auth] session 不存在 → 404
- [auth] 非本人 session_id → 403
- [validation] terminal 不存在 → 404
- [conflict] Agent 离线 → 409

GET /api/scheduled-tasks 测试:
- [filter] 按 session_id 过滤
- [filter] 按 status 过滤
- [filter] session_id + status 组合过滤

DELETE /api/scheduled-tasks/{task_id} 测试:
- [happy] 删除成功 → 204
- [auth] 删除他人任务 → 403
- [not_found] 删除不存在 → 404

通用:
- [auth] 未鉴权 → 401
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.infra.auth import generate_token


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """创建 TestClient，复用 app 实例。"""
    from app import app
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """生成有效 JWT token 的 Authorization headers。"""
    token = generate_token("test-session-st", token_version=1, view_type="mobile")
    return {"Authorization": f"Bearer {token}"}


MOCK_SESSION = {
    "id": "sess-1",
    "user_id": "testuser",
    "owner": "testuser",
    "created_at": "2026-04-12T10:00:00Z",
}

MOCK_SESSION_OTHER = {
    "id": "sess-other",
    "user_id": "other-user",
    "owner": "other-user",
    "created_at": "2026-04-12T10:00:00Z",
}

MOCK_TERMINALS = [
    {"terminal_id": "term-1", "title": "Terminal 1", "status": "live"},
]

MOCK_TASK = {
    "id": 1,
    "user_id": "testuser",
    "session_id": "sess-1",
    "terminal_id": "term-1",
    "text_content": "echo hello",
    "execute_at": "2026-12-31T00:00:00+00:00",
    "repeat_type": "once",
    "status": "pending",
    "created_at": "2026-05-12T10:00:00+00:00",
    "executed_at": None,
}

FUTURE_TIME = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()


def _patch_auth():
    """Mock auth 依赖: get_session + get_token_version。"""
    return [
        patch("app.store.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION),
        patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=1),
    ]


_SENTINEL = object()


def _patch_store(create_return=1, get_return=_SENTINEL, list_return=None, delete_return=None, duplicate_return=None):
    """Mock ScheduledTaskStore 实例化及其方法。"""
    store_instance = MagicMock()
    store_instance.create = AsyncMock(return_value=create_return)
    # 使用 _SENTINEL 区分"未传参"和"显式传 None"
    if get_return is _SENTINEL:
        store_instance.get_by_id = AsyncMock(return_value=MOCK_TASK)
    else:
        store_instance.get_by_id = AsyncMock(return_value=get_return)
    store_instance.list_by_user = AsyncMock(return_value=list_return or [])
    store_instance.list_by_session = AsyncMock(return_value=list_return or [])
    store_instance.delete = AsyncMock(return_value=delete_return)
    store_instance.find_pending_duplicate = AsyncMock(return_value=duplicate_return)

    return patch(
        "app.api.scheduled_task_api._get_scheduled_task_store",
        return_value=store_instance,
    ), store_instance


def _patch_deps(*, verify_return=None, terminals=None, agent_online=True):
    """Mock _deps 中 scheduled_task_api 使用的函数。"""
    if verify_return is None:
        verify_return = MOCK_SESSION
    return [
        patch("app.api._deps.verify_session_ownership", new_callable=AsyncMock, return_value=verify_return),
        patch("app.api._deps.list_session_terminals", new_callable=AsyncMock, return_value=terminals or MOCK_TERMINALS),
        patch("app.api._deps.is_agent_connected", return_value=agent_online),
    ]


# ---------------------------------------------------------------------------
# POST /api/scheduled-tasks — 创建定时任务
# ---------------------------------------------------------------------------

class TestCreateScheduledTask:

    def test_create_success(self, client, auth_headers):
        """创建成功: mock Agent 在线 → 201"""
        import contextlib
        auth_patches = _patch_auth()
        dep_patches = _patch_deps()
        store_patch, store = _patch_store()

        with contextlib.ExitStack() as stack:
            for p in auth_patches:
                stack.enter_context(p)
            for p in dep_patches:
                stack.enter_context(p)
            stack.enter_context(store_patch)

            resp = client.post(
                "/api/scheduled-tasks",
                json={
                    "session_id": "sess-1",
                    "terminal_id": "term-1",
                    "text_content": "echo hello",
                    "execute_at": FUTURE_TIME,
                    "repeat_type": "once",
                },
                headers=auth_headers,
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == 1
        assert data["session_id"] == "sess-1"
        assert data["status"] == "pending"

    def test_create_agent_offline(self, client, auth_headers):
        """创建 Agent 离线 → 409"""
        import contextlib
        auth_patches = _patch_auth()
        dep_patches = _patch_deps(agent_online=False)
        store_patch, _ = _patch_store()

        with contextlib.ExitStack() as stack:
            for p in auth_patches:
                stack.enter_context(p)
            for p in dep_patches:
                stack.enter_context(p)
            stack.enter_context(store_patch)

            resp = client.post(
                "/api/scheduled-tasks",
                json={
                    "session_id": "sess-1",
                    "terminal_id": "term-1",
                    "text_content": "echo hello",
                    "execute_at": FUTURE_TIME,
                },
                headers=auth_headers,
            )

        assert resp.status_code == 409
        assert "Agent" in resp.json()["detail"]

    def test_create_session_not_found(self, client, auth_headers):
        """创建 session 不存在 → 404"""
        import contextlib
        auth_patches = _patch_auth()
        # verify_session_ownership 返回空 session（无 user_id）
        dep_patches = _patch_deps(verify_return={"id": "sess-x", "user_id": ""})
        store_patch, _ = _patch_store()

        with contextlib.ExitStack() as stack:
            for p in auth_patches:
                stack.enter_context(p)
            for p in dep_patches:
                stack.enter_context(p)
            stack.enter_context(store_patch)

            resp = client.post(
                "/api/scheduled-tasks",
                json={
                    "session_id": "sess-x",
                    "terminal_id": "term-1",
                    "text_content": "echo hello",
                    "execute_at": FUTURE_TIME,
                },
                headers=auth_headers,
            )

        assert resp.status_code == 404
        assert "Session" in resp.json()["detail"]

    def test_create_terminal_not_found(self, client, auth_headers):
        """创建 terminal 不存在 → 404"""
        import contextlib
        auth_patches = _patch_auth()
        dep_patches = _patch_deps(terminals=[])
        store_patch, _ = _patch_store()

        with contextlib.ExitStack() as stack:
            for p in auth_patches:
                stack.enter_context(p)
            for p in dep_patches:
                stack.enter_context(p)
            stack.enter_context(store_patch)

            resp = client.post(
                "/api/scheduled-tasks",
                json={
                    "session_id": "sess-1",
                    "terminal_id": "term-missing",
                    "text_content": "echo hello",
                    "execute_at": FUTURE_TIME,
                },
                headers=auth_headers,
            )

        assert resp.status_code == 404
        assert "Terminal" in resp.json()["detail"]

    def test_create_other_user_session(self, client, auth_headers):
        """创建非本人 session_id → 403"""
        import contextlib
        from fastapi import HTTPException, status as st

        auth_patches = _patch_auth()
        # verify_session_ownership 会抛 403
        dep_patches = [
            patch(
                "app.api._deps.verify_session_ownership",
                new_callable=AsyncMock,
                side_effect=HTTPException(
                    status_code=st.HTTP_403_FORBIDDEN,
                    detail="无权访问此 Session",
                ),
            ),
        ]
        store_patch, _ = _patch_store()

        with contextlib.ExitStack() as stack:
            for p in auth_patches:
                stack.enter_context(p)
            for p in dep_patches:
                stack.enter_context(p)
            stack.enter_context(store_patch)

            resp = client.post(
                "/api/scheduled-tasks",
                json={
                    "session_id": "sess-other",
                    "terminal_id": "term-1",
                    "text_content": "echo hello",
                    "execute_at": FUTURE_TIME,
                },
                headers=auth_headers,
            )

        assert resp.status_code == 403

    def test_create_past_execute_at(self, client, auth_headers):
        """创建 execute_at 在过去 → 400"""
        import contextlib
        past_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        auth_patches = _patch_auth()
        store_patch, _ = _patch_store()

        with contextlib.ExitStack() as stack:
            for p in auth_patches:
                stack.enter_context(p)
            stack.enter_context(store_patch)

            resp = client.post(
                "/api/scheduled-tasks",
                json={
                    "session_id": "sess-1",
                    "terminal_id": "term-1",
                    "text_content": "echo hello",
                    "execute_at": past_time,
                },
                headers=auth_headers,
            )

        assert resp.status_code == 400
        assert "未来" in resp.json()["detail"] or "past" in resp.json()["detail"].lower() or "过去" in resp.json()["detail"]

    def test_create_duplicate_returns_existing(self, client, auth_headers):
        """创建重复任务返回已有任务（幂等）→ 201"""
        import contextlib
        auth_patches = _patch_auth()
        dep_patches = _patch_deps()
        store_patch, store = _patch_store(duplicate_return=MOCK_TASK)

        with contextlib.ExitStack() as stack:
            for p in auth_patches:
                stack.enter_context(p)
            for p in dep_patches:
                stack.enter_context(p)
            stack.enter_context(store_patch)

            resp = client.post(
                "/api/scheduled-tasks",
                json={
                    "session_id": "sess-1",
                    "terminal_id": "term-1",
                    "text_content": "echo hello",
                    "execute_at": FUTURE_TIME,
                    "repeat_type": "once",
                },
                headers=auth_headers,
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == 1
        # 不应调用 create
        store.create.assert_not_called()


# ---------------------------------------------------------------------------
# GET /api/scheduled-tasks — 查询定时任务列表
# ---------------------------------------------------------------------------

class TestListScheduledTasks:

    def test_list_by_session_id(self, client, auth_headers):
        """列表按 session_id 过滤"""
        import contextlib
        auth_patches = _patch_auth()
        dep_patches = _patch_deps()
        store_patch, store = _patch_store(
            list_return=[MOCK_TASK],
        )

        with contextlib.ExitStack() as stack:
            for p in auth_patches:
                stack.enter_context(p)
            for p in dep_patches:
                stack.enter_context(p)
            stack.enter_context(store_patch)

            resp = client.get(
                "/api/scheduled-tasks?session_id=sess-1",
                headers=auth_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tasks"]) == 1
        store.list_by_session.assert_called_once_with("sess-1", status=None)

    def test_list_by_status(self, client, auth_headers):
        """列表按 status 过滤"""
        import contextlib
        auth_patches = _patch_auth()
        store_patch, store = _patch_store(
            list_return=[MOCK_TASK],
        )

        with contextlib.ExitStack() as stack:
            for p in auth_patches:
                stack.enter_context(p)
            stack.enter_context(store_patch)

            resp = client.get(
                "/api/scheduled-tasks?status=pending",
                headers=auth_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tasks"]) == 1
        store.list_by_user.assert_called_once_with("testuser", status="pending")

    def test_list_session_id_and_status(self, client, auth_headers):
        """列表 session_id + status 组合过滤"""
        import contextlib
        auth_patches = _patch_auth()
        dep_patches = _patch_deps()
        store_patch, store = _patch_store(
            list_return=[MOCK_TASK],
        )

        with contextlib.ExitStack() as stack:
            for p in auth_patches:
                stack.enter_context(p)
            for p in dep_patches:
                stack.enter_context(p)
            stack.enter_context(store_patch)

            resp = client.get(
                "/api/scheduled-tasks?session_id=sess-1&status=pending",
                headers=auth_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tasks"]) == 1
        store.list_by_session.assert_called_once_with("sess-1", status="pending")


# ---------------------------------------------------------------------------
# DELETE /api/scheduled-tasks/{task_id} — 删除定时任务
# ---------------------------------------------------------------------------

class TestDeleteScheduledTask:

    def test_delete_success(self, client, auth_headers):
        """删除成功 → 204"""
        import contextlib
        auth_patches = _patch_auth()
        store_patch, store = _patch_store(get_return=MOCK_TASK)

        with contextlib.ExitStack() as stack:
            for p in auth_patches:
                stack.enter_context(p)
            stack.enter_context(store_patch)

            resp = client.delete(
                "/api/scheduled-tasks/1",
                headers=auth_headers,
            )

        assert resp.status_code == 204
        store.delete.assert_called_once_with(1)

    def test_delete_other_user_task(self, client, auth_headers):
        """删除他人任务 → 403"""
        import contextlib
        auth_patches = _patch_auth()
        other_task = {**MOCK_TASK, "user_id": "other-user"}
        store_patch, store = _patch_store(get_return=other_task)

        with contextlib.ExitStack() as stack:
            for p in auth_patches:
                stack.enter_context(p)
            stack.enter_context(store_patch)

            resp = client.delete(
                "/api/scheduled-tasks/1",
                headers=auth_headers,
            )

        assert resp.status_code == 403
        store.delete.assert_not_called()

    def test_delete_not_found(self, client, auth_headers):
        """删除不存在 → 404"""
        import contextlib
        auth_patches = _patch_auth()
        store_patch, store = _patch_store(get_return=None)

        with contextlib.ExitStack() as stack:
            for p in auth_patches:
                stack.enter_context(p)
            stack.enter_context(store_patch)

            resp = client.delete(
                "/api/scheduled-tasks/999",
                headers=auth_headers,
            )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 鉴权测试
# ---------------------------------------------------------------------------

class TestAuth:

    def test_unauthorized_no_token(self, client):
        """未鉴权 → 403（FastAPI HTTPBearer 默认行为）"""
        resp = client.post(
            "/api/scheduled-tasks",
            json={
                "session_id": "sess-1",
                "terminal_id": "term-1",
                "text_content": "echo hello",
                "execute_at": FUTURE_TIME,
            },
        )
        assert resp.status_code in (401, 403)

        resp = client.get("/api/scheduled-tasks")
        assert resp.status_code in (401, 403)

        resp = client.delete("/api/scheduled-tasks/1")
        assert resp.status_code in (401, 403)
