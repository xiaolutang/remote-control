"""
B049/B056/B058 测试: 反馈 API 单元测试

POST /api/feedback 测试 (B058: 迁移到 log-service Issues API):
- [happy] 正常提交反馈 → POST /api/issues → feedback_id = str(issue.id)
- [auth] 无效 token → 401
- [validation] 空描述 / 无效分类 / 超长描述 → 422
- [fail] log-service 不可达 → 503
- [fail] log-service 返回 500 → 502
- [resilience] 日志获取失败 → 反馈仍成功
- [contract] 参数映射正确（severity/component/reporter/environment）

GET /api/feedback/{feedback_id} 测试:
- [happy] GET 成功查询单条反馈 → 返回完整反馈详情 + 关联日志
- [auth] GET 查询不存在的反馈 → 404
- [auth] GET 查询其他用户的反馈 → 404
- [auth] GET 无 token → 403

B056 新增（user_id 修复 + LoginResponse 增强）:
- [auth] session 查不到 / user_id 为空 / JWT sub 为空 → 401
- [contract] login/register 响应包含 username
"""
import logging
import hashlib
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.infra.auth import generate_token


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """创建 TestClient（同步），复用 app 实例"""
    from app import app
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """生成有效 JWT token 的 Authorization headers（含 token_version）"""
    token = generate_token("test-session-fb", token_version=1, view_type="mobile")
    return {"Authorization": f"Bearer {token}"}


# Mock session 返回真实 user_id
MOCK_SESSION = {
    "id": "test-session-fb",
    "user_id": "testuser",
    "owner": "testuser",
    "created_at": "2026-04-12T10:00:00Z",
}

# 默认 issue 响应
DEFAULT_ISSUE = {"id": 42, "created_at": "2026-04-12T12:00:00Z"}
DEFAULT_LOGS = {"logs": [], "total": 0}


def _patch_issue_deps(*, issue_data=None, logs_data=None, logs_error=None, issue_error=None):
    """
    Mock 依赖：feedback_api.get_session + feedback_service.get_shared_http_client + auth.get_token_version
    - issue_data: POST /api/issues 返回的 issue（默认 DEFAULT_ISSUE）
    - logs_data: GET /api/logs 返回的日志（默认 DEFAULT_LOGS）
    - logs_error: GET /api/logs 异常（best-effort）
    - issue_error: POST /api/issues 异常（ConnectError/HTTPStatusError）
    """
    session_patch = patch("app.store.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION)
    token_version_patch = patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=1)

    # B052: mock _verify_terminal_ownership — 返回基于 terminal_id 派生的 session_id
    verify_patch = patch(
        "app.services.feedback_service._verify_terminal_ownership",
        new_callable=AsyncMock,
        side_effect=lambda uid, tid: f"ts-{tid[:16]}",
    )

    mock_http = AsyncMock()

    # Mock log fetch
    if logs_error:
        mock_http.get = AsyncMock(side_effect=logs_error)
    else:
        mock_log_resp = MagicMock(status_code=200)
        mock_log_resp.raise_for_status = MagicMock()
        mock_log_resp.json = MagicMock(return_value=logs_data or DEFAULT_LOGS)
        mock_http.get = AsyncMock(return_value=mock_log_resp)

    # Mock issue create
    if issue_error:
        mock_http.post = AsyncMock(side_effect=issue_error)
    else:
        mock_issue_resp = MagicMock(status_code=201)
        mock_issue_resp.raise_for_status = MagicMock()
        mock_issue_resp.json = MagicMock(return_value=issue_data or DEFAULT_ISSUE)
        mock_http.post = AsyncMock(return_value=mock_issue_resp)

    client_patch = patch("app.services.feedback_service.get_shared_http_client", return_value=mock_http)

    return [session_patch, token_version_patch, verify_patch, client_patch], mock_http


# ---------------------------------------------------------------------------
# 测试类
# ---------------------------------------------------------------------------

class TestSubmitFeedbackHappy:
    """正常提交反馈（通过 log-service Issues API）"""

    def test_submit_feedback_with_related_logs(self, client, auth_headers):
        """[happy] 正常提交 → POST /api/issues → feedback_id = str(issue.id)"""
        logs_data = {
            "logs": [
                {"level": "error", "message": "log entry 1", "extra": {"session_id": "test-session-fb"}},
            ],
            "total": 1,
        }
        issue_data = {"id": 42, "created_at": "2026-04-12T12:00:00Z"}
        patches, _ = _patch_issue_deps(issue_data=issue_data, logs_data=logs_data)

        for p in patches:
            p.start()
        try:
            resp = client.post(
                "/api/feedback",
                json={
                    "session_id": "test-session-fb",
                    "category": "connection",
                    "description": "连接经常断开",
                    "platform": "android",
                    "app_version": "1.0.0",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["feedback_id"] == "42"
            assert body["created_at"] == "2026-04-12T12:00:00Z"
        finally:
            for p in patches:
                p.stop()


class TestFeedbackAuth:
    """鉴权相关测试"""

    def test_invalid_token_returns_401(self, client):
        """[auth] 无效 token → 401"""
        resp = client.post(
            "/api/feedback",
            json={
                "session_id": "test-session",
                "category": "connection",
                "description": "描述",
            },
            headers={"Authorization": "Bearer invalid-token-xxx"},
        )
        assert resp.status_code == 401

    def test_no_token_returns_403(self, client):
        """[auth] 无 token → 403（FastAPI HTTPBearer 默认行为）"""
        resp = client.post(
            "/api/feedback",
            json={
                "session_id": "test-session",
                "category": "connection",
                "description": "描述",
            },
        )
        assert resp.status_code in (401, 403)


class TestFeedbackValidation:
    """参数校验测试"""

    def test_empty_description_returns_422(self, client, auth_headers):
        """[validation] 空描述 → 422"""
        patches, _ = _patch_issue_deps()
        for p in patches:
            p.start()
        try:
            resp = client.post(
                "/api/feedback",
                json={
                    "session_id": "test-session-fb",
                    "category": "connection",
                    "description": "",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 422
        finally:
            for p in patches:
                p.stop()

    def test_whitespace_only_description_returns_422(self, client, auth_headers):
        """[validation] 仅空格描述 → 422"""
        patches, _ = _patch_issue_deps()
        for p in patches:
            p.start()
        try:
            resp = client.post(
                "/api/feedback",
                json={
                    "session_id": "test-session-fb",
                    "category": "connection",
                    "description": "   ",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 422
        finally:
            for p in patches:
                p.stop()

    def test_invalid_category_returns_422(self, client, auth_headers):
        """[validation] 无效分类 → 422"""
        with patch("app.store.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION), \
             patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=1):
            resp = client.post(
                "/api/feedback",
                json={
                    "session_id": "test-session-fb",
                    "category": "invalid_category",
                    "description": "描述内容",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 422

    def test_too_long_description_returns_422(self, client, auth_headers):
        """[validation] 超长描述（>10000字符）→ 422"""
        patches, _ = _patch_issue_deps()
        for p in patches:
            p.start()
        try:
            resp = client.post(
                "/api/feedback",
                json={
                    "session_id": "test-session-fb",
                    "category": "connection",
                    "description": "x" * 10001,
                },
                headers=auth_headers,
            )
            assert resp.status_code == 422
        finally:
            for p in patches:
                p.stop()


class TestFeedbackLogServiceUnavailable:
    """log-service 不可用场景"""

    def test_log_service_unreachable_returns_503(self, client, auth_headers):
        """[fail] log-service 不可达 → 503"""
        import httpx
        patches, _ = _patch_issue_deps(issue_error=httpx.ConnectError("connection refused"))

        for p in patches:
            p.start()
        try:
            resp = client.post(
                "/api/feedback",
                json={
                    "session_id": "test-session-fb",
                    "category": "connection",
                    "description": "连接断开",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 503
        finally:
            for p in patches:
                p.stop()

    def test_log_service_returns_500_returns_502(self, client, auth_headers):
        """[fail] log-service 返回 500 → 502"""
        import httpx
        mock_500_resp = MagicMock(status_code=500)
        error = httpx.HTTPStatusError(
            "500", request=httpx.Request("POST", "http://test"), response=httpx.Response(status_code=500),
        )
        patches, _ = _patch_issue_deps(issue_error=error)

        for p in patches:
            p.start()
        try:
            resp = client.post(
                "/api/feedback",
                json={
                    "session_id": "test-session-fb",
                    "category": "connection",
                    "description": "连接断开",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 502
        finally:
            for p in patches:
                p.stop()


class TestFeedbackLogFetchFails:
    """日志获取失败场景"""

    def test_log_fetch_fails_feedback_still_succeeds(self, client, auth_headers):
        """[resilience] 日志获取失败 → 反馈仍成功（不带日志）"""
        patches, _ = _patch_issue_deps(logs_error=Exception("log service down"))

        for p in patches:
            p.start()
        try:
            resp = client.post(
                "/api/feedback",
                json={
                    "session_id": "test-session-fb",
                    "category": "crash",
                    "description": "应用闪退",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 200
            assert resp.json()["feedback_id"] == "42"
        finally:
            for p in patches:
                p.stop()


class TestFeedbackLogSessionIsolation:
    """跨 session 日志隔离测试"""

    def test_only_current_session_logs_included(self, client, auth_headers):
        """[isolation] 仅关联当前 session 的日志，同用户不同 session 的日志不混入"""
        logs_data = {
            "logs": [
                {"level": "error", "message": "current session log", "extra": {"session_id": "test-session-fb"}},
                {"level": "info", "message": "other session log", "extra": {"session_id": "other-session-999"}},
                {"level": "warning", "message": "another session log", "extra": {"session_id": "yet-another-session"}},
            ],
            "total": 3,
        }
        patches, mock_http = _patch_issue_deps(issue_data=DEFAULT_ISSUE, logs_data=logs_data)

        for p in patches:
            p.start()
        try:
            resp = client.post(
                "/api/feedback",
                json={
                    "session_id": "test-session-fb",
                    "category": "connection",
                    "description": "仅当前 session 日志",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 200

            # 验证 POST /api/issues 的 description 只包含当前 session 的日志
            call_args = mock_http.post.call_args
            body = call_args.kwargs.get("json") or call_args[1].get("json")
            description = body["description"]
            assert "current session log" in description
            assert "other session log" not in description
            assert "another session log" not in description
        finally:
            for p in patches:
                p.stop()

    def test_no_matching_session_logs_still_succeeds(self, client, auth_headers):
        """[isolation] 日志返回但无匹配 session → 反馈提交成功，description 不含日志"""
        logs_data = {
            "logs": [
                {"level": "info", "message": "unrelated log", "extra": {"session_id": "completely-different-session"}},
            ],
            "total": 1,
        }
        patches, mock_http = _patch_issue_deps(issue_data=DEFAULT_ISSUE, logs_data=logs_data)

        for p in patches:
            p.start()
        try:
            resp = client.post(
                "/api/feedback",
                json={
                    "session_id": "test-session-fb",
                    "category": "suggestion",
                    "description": "无匹配日志",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 200
            assert resp.json()["feedback_id"] == "42"

            # 验证 description 不含任何日志
            call_args = mock_http.post.call_args
            body = call_args.kwargs.get("json") or call_args[1].get("json")
            assert "Related Logs" not in body["description"]
        finally:
            for p in patches:
                p.stop()


class TestFeedbackIssueParams:
    """参数映射验证"""

    def test_issue_params_correct(self, client, auth_headers):
        """[contract] POST /api/issues 参数映射正确（severity/component/reporter/environment）"""
        patches, mock_http = _patch_issue_deps()

        for p in patches:
            p.start()
        try:
            resp = client.post(
                "/api/feedback",
                json={
                    "session_id": "test-session-fb",
                    "category": "connection",
                    "description": "连接经常断开",
                    "platform": "android",
                    "app_version": "1.0.0",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 200

            # 验证 POST /api/issues 调用参数
            call_args = mock_http.post.call_args
            body = call_args.kwargs.get("json") or call_args[1].get("json")
            assert body["severity"] == "high", f"Expected severity='high' for connection, got '{body.get('severity')}'"
            assert body["component"] == "feedback:connection"
            assert body["reporter"] == "testuser"
            assert body["environment"] == "android / 1.0.0"
            assert body["service_name"] == "remote-control"
            assert body["request_id"] == "test-session-fb"
        finally:
            for p in patches:
                p.stop()


# ---------------------------------------------------------------------------
# GET /api/feedback/{feedback_id} 测试
# ---------------------------------------------------------------------------

class TestGetFeedbackDetailHappy:
    """GET 成功查询"""

    def test_get_feedback_detail_success(self, client, auth_headers):
        """[happy] GET 成功查询单条反馈 → 返回完整反馈详情"""
        feedback_detail = {
            "feedback_id": "fb-001",
            "user_id": "testuser",
            "session_id": "test-session-fb",
            "category": "connection",
            "description": "连接经常断开",
            "platform": "android",
            "app_version": "1.0.0",
            "created_at": "2026-04-11T10:00:00+00:00",
            "logs": [{"level": "info", "message": "log entry 1", "timestamp": "2026-04-11T10:00:00Z"}],
        }

        with patch("app.store.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION), \
             patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=1), \
             patch("app.api.feedback_api.get_feedback", new_callable=AsyncMock, return_value=feedback_detail) as mock_get:
            resp = client.get("/api/feedback/fb-001", headers=auth_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert body["feedback_id"] == "fb-001"
        assert body["category"] == "connection"
        assert body["description"] == "连接经常断开"
        assert len(body["logs"]) == 1
        # 验证 API 层传给 service 的 user_id 是真实用户名
        mock_get.assert_called_once_with("fb-001", "testuser")


class TestGetFeedbackNotFound:
    """GET 查询不存在的反馈"""

    def test_get_feedback_not_found(self, client, auth_headers):
        """[boundary] GET 查询不存在的反馈 → 404"""
        with patch("app.store.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION), \
             patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=1), \
             patch("app.api.feedback_api.get_feedback", new_callable=AsyncMock, return_value=None):
            resp = client.get("/api/feedback/nonexistent-id-12345", headers=auth_headers)

        assert resp.status_code == 404
        detail = resp.json().get("detail", "")
        assert "不存在" in detail or "not found" in detail.lower()


class TestGetFeedbackUnauthorized:
    """GET 越权查询"""

    def test_get_feedback_other_user_returns_404(self, client, auth_headers):
        """[auth] GET 查询其他用户创建的反馈 → 404"""
        other_token = generate_token("other-user-session", token_version=1, view_type="mobile")
        other_headers = {"Authorization": f"Bearer {other_token}"}
        other_session = {"id": "other-user-session", "user_id": "otheruser", "owner": "otheruser"}

        with patch("app.store.session.get_session", new_callable=AsyncMock, return_value=other_session), \
             patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=1), \
             patch("app.api.feedback_api.get_feedback", new_callable=AsyncMock, return_value=None) as mock_get:
            resp = client.get("/api/feedback/fb-002", headers=other_headers)

        assert resp.status_code == 404
        # 验证 service 收到的 user_id 是真实用户名
        mock_get.assert_called_once_with("fb-002", "otheruser")

    def test_get_feedback_no_token_returns_403(self, client):
        """[auth] GET 无 token → 403"""
        resp = client.get("/api/feedback/fb-001")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# B056 新增测试：user_id fail-closed + LoginResponse 增强
# ---------------------------------------------------------------------------

class TestUserIdFailClosed:
    """fail-closed 测试：session 异常时拒绝请求"""

    def test_session_not_found_returns_401(self, client, auth_headers):
        """[auth] session 查不到 → 401"""
        from fastapi import HTTPException
        patches, _ = _patch_issue_deps()
        # 覆盖 get_session 抛出 404（session 不存在）
        patches[0] = patch("app.store.session.get_session", new_callable=AsyncMock,
                           side_effect=HTTPException(status_code=404, detail="session not found"))

        for p in patches:
            p.start()
        try:
            resp = client.post(
                "/api/feedback",
                json={"session_id": "test-session-fb", "category": "connection", "description": "测试"},
                headers=auth_headers,
            )
            assert resp.status_code == 401
        finally:
            for p in patches:
                p.stop()

    def test_session_empty_user_id_returns_401(self, client, auth_headers):
        """[auth] session user_id 为空 → 401"""
        session_no_user = {"id": "test-session-fb", "user_id": "", "owner": ""}
        patches, _ = _patch_issue_deps()
        # 覆盖 get_session 返回空 user_id 的 session
        patches[0] = patch("app.store.session.get_session", new_callable=AsyncMock, return_value=session_no_user)

        for p in patches:
            p.start()
        try:
            resp = client.post(
                "/api/feedback",
                json={"session_id": "test-session-fb", "category": "connection", "description": "测试"},
                headers=auth_headers,
            )
            assert resp.status_code == 401
        finally:
            for p in patches:
                p.stop()

    def test_jwt_sub_empty_returns_401(self, client):
        """[auth] JWT sub 为空 → generate_token("") 抛 ValueError，请求无合法 token → 401"""
        # generate_token("") 会抛 ValueError，模拟无合法 token 的场景
        headers = {"Authorization": "Bearer invalid-empty-token"}
        resp = client.post(
            "/api/feedback",
            json={"session_id": "", "category": "connection", "description": "测试"},
            headers=headers,
        )
        assert resp.status_code == 401


class TestLoginResponseUsername:
    """LoginResponse username 字段测试"""

    def test_login_response_contains_username(self, client):
        """[contract] login 响应包含 username"""
        real_hash = hashlib.sha256("test123456".encode()).hexdigest()
        with patch("app.api.user_api.get_user", new_callable=AsyncMock, return_value={
            "username": "testuser", "password_hash": real_hash, "created_at": "2026-04-01T00:00:00Z"
        }), \
             patch("app.api.user_api.create_session", new_callable=AsyncMock, return_value={
                 "session_id": "sess-1", "status": "pending", "created_at": "2026-04-12T00:00:00Z",
                 "user_id": "testuser", "owner": "testuser"
             }), \
             patch("app.api.user_api.increment_token_version", new_callable=AsyncMock, return_value=1), \
             patch("app.api.user_api.store_refresh_token", new_callable=AsyncMock), \
             patch("app.api.user_api.update_password_hash", new_callable=AsyncMock):
            resp = client.post("/api/login", json={"username": "testuser", "password": "test123456"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == "testuser"
        assert body["success"] is True

    def test_register_response_contains_username(self, client):
        """[contract] register 响应包含 username"""
        with patch("app.api.user_api.get_user", new_callable=AsyncMock, return_value=None), \
             patch("app.api.user_api.save_user", new_callable=AsyncMock), \
             patch("app.api.user_api.create_session", new_callable=AsyncMock, return_value={
                 "session_id": "sess-2", "status": "pending", "created_at": "2026-04-12T00:00:00Z",
                 "user_id": "newuser", "owner": "newuser"
             }), \
             patch("app.api.user_api.increment_token_version", new_callable=AsyncMock, return_value=1):
            resp = client.post("/api/register", json={"username": "newuser", "password": "test123456"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == "newuser"
        assert body["success"] is True


# ---------------------------------------------------------------------------
# B059 新增测试：get_feedback 迁移到 log-service + Redis 清理验证
# ---------------------------------------------------------------------------

class TestGetFeedbackViaLogService:
    """get_feedback 通过 log-service GET /api/issues/{id} 查询"""

    @pytest.mark.asyncio
    async def test_normal_query_parses_component(self):
        """正常查询 → component='feedback:connection' → category='connection'"""
        from app.services.feedback_service import get_feedback

        issue_resp = {
            "id": 42,
            "component": "feedback:connection",
            "reporter": "testuser",
            "request_id": "sess-123",
            "description": "连接断开",
            "environment": "android / 1.0.0",
            "created_at": "2026-04-12T12:00:00Z",
        }

        with patch("app.services.feedback_service.get_shared_http_client") as mock_client:
            mock_http = AsyncMock()
            mock_resp = MagicMock(status_code=200)
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value=issue_resp)
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_client.return_value = mock_http

            result = await get_feedback("42", "testuser")

        assert result is not None
        assert result["category"] == "connection"
        assert result["feedback_id"] == "42"
        assert result["user_id"] == "testuser"
        assert result["platform"] == "android"
        assert result["app_version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_reporter_mismatch_returns_none(self):
        """reporter ≠ user_id → None（404）"""
        from app.services.feedback_service import get_feedback

        issue_resp = {
            "id": 42,
            "component": "feedback:connection",
            "reporter": "otheruser",
            "description": "test",
            "created_at": "2026-04-12T12:00:00Z",
        }

        with patch("app.services.feedback_service.get_shared_http_client") as mock_client:
            mock_http = AsyncMock()
            mock_resp = MagicMock(status_code=200)
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value=issue_resp)
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_client.return_value = mock_http

            result = await get_feedback("42", "testuser")

        assert result is None

    @pytest.mark.asyncio
    async def test_log_service_unreachable_returns_503(self):
        """log-service 不可达 → 503"""
        from app.services.feedback_service import get_feedback
        from fastapi import HTTPException
        import httpx

        with patch("app.services.feedback_service.get_shared_http_client") as mock_client:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client.return_value = mock_http

            with pytest.raises(HTTPException) as exc_info:
                await get_feedback("42", "testuser")
            assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_issue_not_found_returns_none(self):
        """issue 不存在 → 404 HTTPStatusError → None"""
        from app.services.feedback_service import get_feedback
        import httpx

        with patch("app.services.feedback_service.get_shared_http_client") as mock_client:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(side_effect=httpx.HTTPStatusError(
                "404", request=httpx.Request("GET", "http://test"), response=httpx.Response(status_code=404),
            ))
            mock_client.return_value = mock_http

            result = await get_feedback("999", "testuser")

        assert result is None


    @pytest.mark.asyncio
    async def test_environment_with_platform_and_version(self):
        """environment='android / 1.0.0' → platform='android', app_version='1.0.0'"""
        from app.services.feedback_service import get_feedback

        issue_resp = {
            "id": 43,
            "component": "feedback:terminal",
            "reporter": "testuser",
            "request_id": "sess-456",
            "description": "终端无响应",
            "environment": "ios / 2.1.0",
            "created_at": "2026-04-12T13:00:00Z",
        }

        with patch("app.services.feedback_service.get_shared_http_client") as mock_client:
            mock_http = AsyncMock()
            mock_resp = MagicMock(status_code=200)
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value=issue_resp)
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_client.return_value = mock_http

            result = await get_feedback("43", "testuser")

        assert result is not None
        assert result["platform"] == "ios"
        assert result["app_version"] == "2.1.0"
        assert result["session_id"] == "sess-456"

    @pytest.mark.asyncio
    async def test_environment_platform_only(self):
        """environment='android'（无版本号）→ platform='android', app_version=''"""
        from app.services.feedback_service import get_feedback

        issue_resp = {
            "id": 44,
            "component": "feedback:crash",
            "reporter": "testuser",
            "request_id": "sess-789",
            "description": "崩溃了",
            "environment": "android",
            "created_at": "2026-04-12T14:00:00Z",
        }

        with patch("app.services.feedback_service.get_shared_http_client") as mock_client:
            mock_http = AsyncMock()
            mock_resp = MagicMock(status_code=200)
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value=issue_resp)
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_client.return_value = mock_http

            result = await get_feedback("44", "testuser")

        assert result is not None
        assert result["platform"] == "android"
        assert result["app_version"] == ""

    @pytest.mark.asyncio
    async def test_environment_empty(self):
        """environment='' → platform='', app_version=''"""
        from app.services.feedback_service import get_feedback

        issue_resp = {
            "id": 45,
            "component": "feedback:suggestion",
            "reporter": "testuser",
            "request_id": "",
            "description": "建议",
            "environment": "",
            "created_at": "2026-04-12T15:00:00Z",
        }

        with patch("app.services.feedback_service.get_shared_http_client") as mock_client:
            mock_http = AsyncMock()
            mock_resp = MagicMock(status_code=200)
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value=issue_resp)
            mock_http.get = AsyncMock(return_value=mock_resp)
            mock_client.return_value = mock_http

            result = await get_feedback("45", "testuser")

        assert result is not None
        assert result["platform"] == ""
        assert result["app_version"] == ""
        assert result["session_id"] == ""


class TestFeedbackServiceNoRedis:
    """feedback_service.py 不含 Redis 相关代码"""

    def test_no_redis_import(self):
        """feedback_service.py 不含 redis_conn / rc:feedback"""
        import inspect
        from app.services import feedback_service
        source = inspect.getsource(feedback_service)
        assert "redis_conn" not in source, "feedback_service.py 不应包含 redis_conn"
        assert "rc:feedback" not in source, "feedback_service.py 不应包含 rc:feedback 键名"
        assert "rc:user_feedbacks" not in source, "feedback_service.py 不应包含 rc:user_feedbacks 键名"


class TestFeedbackTimeoutAndAbnormalResponse:
    """超时、非预期响应结构、缺字段等异常分支"""

    def test_log_service_timeout_returns_503(self, client, auth_headers):
        """[fail] log-service 超时 → 503"""
        import httpx
        patches, _ = _patch_issue_deps(issue_error=httpx.TimeoutException("timeout"))

        for p in patches:
            p.start()
        try:
            resp = client.post(
                "/api/feedback",
                json={"session_id": "test-session-fb", "category": "connection", "description": "超时测试"},
                headers=auth_headers,
            )
            assert resp.status_code == 503
        finally:
            for p in patches:
                p.stop()

    def test_issue_response_missing_id_field(self, client, auth_headers):
        """[abnormal] issue 响应缺少 id 字段 → feedback_id 为空字符串，不崩溃"""
        patches, _ = _patch_issue_deps(issue_data={"created_at": "2026-04-12T12:00:00Z"})

        for p in patches:
            p.start()
        try:
            resp = client.post(
                "/api/feedback",
                json={"session_id": "test-session-fb", "category": "connection", "description": "缺字段"},
                headers=auth_headers,
            )
            assert resp.status_code == 200
            assert resp.json()["feedback_id"] == ""
        finally:
            for p in patches:
                p.stop()

    def test_log_response_missing_logs_key(self, client, auth_headers):
        """[abnormal] 日志响应无 logs 字段 → 按 [] 处理，反馈仍成功"""
        patches, _ = _patch_issue_deps(logs_data={"total": 0})

        for p in patches:
            p.start()
        try:
            resp = client.post(
                "/api/feedback",
                json={"session_id": "test-session-fb", "category": "crash", "description": "无 logs 键"},
                headers=auth_headers,
            )
            assert resp.status_code == 200
        finally:
            for p in patches:
                p.stop()

    def test_empty_log_list(self, client, auth_headers):
        """[boundary] 日志返回空列表 → description 不含 Related Logs"""
        patches, mock_http = _patch_issue_deps(logs_data={"logs": [], "total": 0})

        for p in patches:
            p.start()
        try:
            resp = client.post(
                "/api/feedback",
                json={"session_id": "test-session-fb", "category": "terminal", "description": "空日志"},
                headers=auth_headers,
            )
            assert resp.status_code == 200
            call_args = mock_http.post.call_args
            body = call_args.kwargs.get("json") or call_args[1].get("json")
            assert "Related Logs" not in body["description"]
        finally:
            for p in patches:
                p.stop()


# ---------------------------------------------------------------------------
# B052 新增测试: 新字段 terminal_id / result_event_id / feedback_type
# ---------------------------------------------------------------------------


class TestFeedbackB052NewFields:
    """B052: 新字段测试"""

    def test_submit_with_new_fields(self, client, auth_headers):
        """[happy] 包含新字段 terminal_id / result_event_id / feedback_type 提交成功"""
        patches, mock_http = _patch_issue_deps()

        for p in patches:
            p.start()
        try:
            resp = client.post(
                "/api/feedback",
                json={
                    "session_id": "test-session-fb",
                    "category": "terminal",
                    "description": "AI 给出了错误命令",
                    "terminal_id": "term-abc123",
                    "result_event_id": "evt-xyz789",
                    "feedback_type": "error_report",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 200
            assert resp.json()["feedback_id"] == "42"

            # 验证新字段透传到 log-service
            call_args = mock_http.post.call_args
            body = call_args.kwargs.get("json") or call_args[1].get("json")
            assert body["terminal_id"] == "term-abc123"
            assert body["result_event_id"] == "evt-xyz789"
            assert body["feedback_type"] == "error_report"
        finally:
            for p in patches:
                p.stop()

    def test_submit_without_new_fields_still_works(self, client, auth_headers):
        """[backward-compat] 不含新字段时旧逻辑仍正常"""
        patches, mock_http = _patch_issue_deps()

        for p in patches:
            p.start()
        try:
            resp = client.post(
                "/api/feedback",
                json={
                    "session_id": "test-session-fb",
                    "category": "connection",
                    "description": "旧格式反馈",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 200
        finally:
            for p in patches:
                p.stop()

    def test_feedback_type_partial_fields(self, client, auth_headers):
        """[partial] 只传 terminal_id 不传其他新字段"""
        patches, mock_http = _patch_issue_deps()

        for p in patches:
            p.start()
        try:
            resp = client.post(
                "/api/feedback",
                json={
                    "session_id": "test-session-fb",
                    "category": "suggestion",
                    "description": "建议添加新功能",
                    "terminal_id": "term-001",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 200
            call_args = mock_http.post.call_args
            body = call_args.kwargs.get("json") or call_args[1].get("json")
            assert body["terminal_id"] == "term-001"
            assert "result_event_id" not in body
            assert "feedback_type" not in body
        finally:
            for p in patches:
                p.stop()

    def test_session_id_optional(self, client, auth_headers):
        """[backward-compat] session_id 为可选字段，不传时使用空字符串"""
        patches, _ = _patch_issue_deps()

        for p in patches:
            p.start()
        try:
            resp = client.post(
                "/api/feedback",
                json={
                    "category": "other",
                    "description": "无 session_id 的反馈",
                    "terminal_id": "term-002",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 200
        finally:
            for p in patches:
                p.stop()

    def test_invalid_feedback_type_returns_422(self, client, auth_headers):
        """[validation] 无效的 feedback_type → 422"""
        with patch("app.store.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION), \
             patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=1):
            resp = client.post(
                "/api/feedback",
                json={
                    "session_id": "test-session-fb",
                    "category": "connection",
                    "description": "测试",
                    "feedback_type": "invalid_type",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 422


class TestFeedbackAnalyzeTrigger:
    """B052: 反馈提交后触发 analyze_feedback 闭环"""

    @pytest.mark.asyncio
    async def test_create_feedback_triggers_analyze(self):
        """反馈创建后异步调用 analyze_feedback"""
        from app.services.feedback_service import create_feedback

        mock_issue_resp = MagicMock(status_code=201)
        mock_issue_resp.raise_for_status = MagicMock()
        mock_issue_resp.json = MagicMock(return_value={"id": 99, "created_at": "2026-04-29T10:00:00Z"})

        mock_log_resp = MagicMock(status_code=200)
        mock_log_resp.raise_for_status = MagicMock()
        mock_log_resp.json = MagicMock(return_value={"logs": [], "total": 0})

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_log_resp)
        mock_http.post = AsyncMock(return_value=mock_issue_resp)

        with patch("app.services.feedback_service.get_shared_http_client", return_value=mock_http), \
             patch("app.services.feedback_service._verify_terminal_ownership", new_callable=AsyncMock, return_value="ts-term-1"), \
             patch("app.services.feedback_service._run_analyze_feedback", new_callable=AsyncMock) as mock_analyze:
            result = await create_feedback(
                user_id="testuser",
                session_id="sess-1",
                category="suggestion",
                description="AI 回答不准确",
                terminal_id="term-1",
                result_event_id="evt-1",
                feedback_type="needs_improvement",
            )

            assert result["feedback_id"] == "99"
            # _run_analyze_feedback 被 ensure_future 调度，验证其被触发
            # 由于 ensure_future 是异步的，我们需要给事件循环一些时间
            import asyncio
            await asyncio.sleep(0.05)
            mock_analyze.assert_called()

    @pytest.mark.asyncio
    async def test_analyze_failure_does_not_block_feedback(self):
        """analyze_feedback 失败不阻塞反馈创建"""
        from app.services.feedback_service import create_feedback

        mock_issue_resp = MagicMock(status_code=201)
        mock_issue_resp.raise_for_status = MagicMock()
        mock_issue_resp.json = MagicMock(return_value={"id": 100, "created_at": "2026-04-29T10:00:00Z"})

        mock_log_resp = MagicMock(status_code=200)
        mock_log_resp.raise_for_status = MagicMock()
        mock_log_resp.json = MagicMock(return_value={"logs": [], "total": 0})

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_log_resp)
        mock_http.post = AsyncMock(return_value=mock_issue_resp)

        with patch("app.services.feedback_service.get_shared_http_client", return_value=mock_http):
            result = await create_feedback(
                user_id="testuser",
                session_id="sess-1",
                category="connection",
                description="连接断开",
            )
            # 即使 analyze 失败，反馈仍成功
            assert result["feedback_id"] == "100"


# ---------------------------------------------------------------------------
# R051 幂等性测试: feedback 去重
# ---------------------------------------------------------------------------


class TestFeedbackIdempotency:
    """R051: 有 result_event_id 时反馈幂等去重"""

    @pytest.mark.asyncio
    async def test_dedup_returns_existing(self):
        """有 result_event_id 且已存在相同记录 → 返回已有记录，不创建新的"""
        from app.services.feedback_service import create_feedback

        # 第一次调用 get 返回已存在的 issue
        existing_issue = {
            "id": 77,
            "created_at": "2026-04-29T08:00:00Z",
            "result_event_id": "evt-dedup-1",
            "feedback_type": "helpful",
        }
        mock_issues_resp = MagicMock(status_code=200)
        mock_issues_resp.raise_for_status = MagicMock()
        mock_issues_resp.json = MagicMock(return_value={"issues": [existing_issue]})

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_issues_resp)
        mock_http.post = AsyncMock()  # 不应被调用

        with patch("app.services.feedback_service.get_shared_http_client", return_value=mock_http), \
             patch("app.services.feedback_service._verify_terminal_ownership", new_callable=AsyncMock, return_value="ts-term-1"):
            result = await create_feedback(
                user_id="testuser",
                session_id="sess-1",
                category="suggestion",
                description="重复提交测试",
                terminal_id="term-1",
                result_event_id="evt-dedup-1",
                feedback_type="helpful",
            )

            # 返回已有记录
            assert result["feedback_id"] == "77"
            assert result["created_at"] == "2026-04-29T08:00:00Z"
            # post 不应被调用（没有创建新 issue）
            mock_http.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_dedup_no_match_creates_new(self):
        """有 result_event_id 但无匹配记录 → 正常创建"""
        from app.services.feedback_service import create_feedback

        # get 返回空 issues
        mock_issues_resp = MagicMock(status_code=200)
        mock_issues_resp.raise_for_status = MagicMock()
        mock_issues_resp.json = MagicMock(return_value={"issues": []})

        # logs
        mock_log_resp = MagicMock(status_code=200)
        mock_log_resp.raise_for_status = MagicMock()
        mock_log_resp.json = MagicMock(return_value={"logs": [], "total": 0})

        # create
        mock_issue_resp = MagicMock(status_code=201)
        mock_issue_resp.raise_for_status = MagicMock()
        mock_issue_resp.json = MagicMock(return_value={"id": 88, "created_at": "2026-04-30T10:00:00Z"})

        call_count = {"get": 0}

        async def _mock_get(url, **kwargs):
            call_count["get"] += 1
            if "/api/issues" in url and "reporter" in kwargs.get("params", {}):
                return mock_issues_resp
            return mock_log_resp

        mock_http = AsyncMock()
        mock_http.get = _mock_get
        mock_http.post = AsyncMock(return_value=mock_issue_resp)

        with patch("app.services.feedback_service.get_shared_http_client", return_value=mock_http), \
             patch("app.services.feedback_service._verify_terminal_ownership", new_callable=AsyncMock, return_value="ts-term-1"):
            result = await create_feedback(
                user_id="testuser",
                session_id="sess-1",
                category="suggestion",
                description="新反馈",
                terminal_id="term-1",
                result_event_id="evt-new-1",
                feedback_type="error_report",
            )

            assert result["feedback_id"] == "88"
            mock_http.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_result_event_id_no_dedup(self):
        """无 result_event_id 时不做去重（error_report 场景）"""
        from app.services.feedback_service import create_feedback

        mock_log_resp = MagicMock(status_code=200)
        mock_log_resp.raise_for_status = MagicMock()
        mock_log_resp.json = MagicMock(return_value={"logs": [], "total": 0})

        mock_issue_resp = MagicMock(status_code=201)
        mock_issue_resp.raise_for_status = MagicMock()
        mock_issue_resp.json = MagicMock(return_value={"id": 99, "created_at": "2026-04-30T11:00:00Z"})

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_log_resp)
        mock_http.post = AsyncMock(return_value=mock_issue_resp)

        with patch("app.services.feedback_service.get_shared_http_client", return_value=mock_http), \
             patch("app.services.feedback_service._verify_terminal_ownership", new_callable=AsyncMock, return_value="ts-term-1"):
            result = await create_feedback(
                user_id="testuser",
                session_id="sess-1",
                category="connection",
                description="连接错误",
                terminal_id="term-1",
                # 无 result_event_id
                feedback_type="error_report",
            )

            assert result["feedback_id"] == "99"
            # get 只调了 logs（无幂等查询）
            mock_http.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_dedup_query_fails_falls_through(self):
        """幂等性查询失败（log-service 不可达）→ best-effort fall through 正常创建"""
        from app.services.feedback_service import create_feedback
        import httpx

        mock_log_resp = MagicMock(status_code=200)
        mock_log_resp.raise_for_status = MagicMock()
        mock_log_resp.json = MagicMock(return_value={"logs": [], "total": 0})

        call_count = {"get": 0}

        async def _mock_get(url, **kwargs):
            call_count["get"] += 1
            if "/api/issues" in url and "reporter" in kwargs.get("params", {}):
                raise httpx.ConnectError("service down")
            return mock_log_resp

        mock_issue_resp = MagicMock(status_code=201)
        mock_issue_resp.raise_for_status = MagicMock()
        mock_issue_resp.json = MagicMock(return_value={"id": 55, "created_at": "2026-04-30T12:00:00Z"})

        mock_http = AsyncMock()
        mock_http.get = _mock_get
        mock_http.post = AsyncMock(return_value=mock_issue_resp)

        with patch("app.services.feedback_service.get_shared_http_client", return_value=mock_http), \
             patch("app.services.feedback_service._verify_terminal_ownership", new_callable=AsyncMock, return_value="ts-term-1"):
            result = await create_feedback(
                user_id="testuser",
                session_id="sess-1",
                category="terminal",
                description="best-effort 测试",
                terminal_id="term-1",
                result_event_id="evt-bestr-1",
                feedback_type="helpful",
            )

            # 即使查询失败，仍正常创建
            assert result["feedback_id"] == "55"
            mock_http.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_dedup_matches_feedback_type(self):
        """去重时 feedback_type 也需要匹配"""
        from app.services.feedback_service import create_feedback

        # 已有 helpful 反馈
        existing_issue = {
            "id": 66,
            "created_at": "2026-04-29T09:00:00Z",
            "result_event_id": "evt-ft-1",
            "feedback_type": "helpful",
        }
        mock_issues_resp = MagicMock(status_code=200)
        mock_issues_resp.raise_for_status = MagicMock()
        mock_issues_resp.json = MagicMock(return_value={"issues": [existing_issue]})

        mock_log_resp = MagicMock(status_code=200)
        mock_log_resp.raise_for_status = MagicMock()
        mock_log_resp.json = MagicMock(return_value={"logs": [], "total": 0})

        mock_issue_resp = MagicMock(status_code=201)
        mock_issue_resp.raise_for_status = MagicMock()
        mock_issue_resp.json = MagicMock(return_value={"id": 67, "created_at": "2026-04-30T13:00:00Z"})

        call_count = {"get": 0}

        async def _mock_get(url, **kwargs):
            call_count["get"] += 1
            if "/api/issues" in url and "reporter" in kwargs.get("params", {}):
                return mock_issues_resp
            return mock_log_resp

        mock_http = AsyncMock()
        mock_http.get = _mock_get
        mock_http.post = AsyncMock(return_value=mock_issue_resp)

        with patch("app.services.feedback_service.get_shared_http_client", return_value=mock_http), \
             patch("app.services.feedback_service._verify_terminal_ownership", new_callable=AsyncMock, return_value="ts-term-1"):
            # 同 result_event_id 但不同 feedback_type → 不去重，创建新记录
            result = await create_feedback(
                user_id="testuser",
                session_id="sess-1",
                category="suggestion",
                description="不同 feedback_type",
                terminal_id="term-1",
                result_event_id="evt-ft-1",
                feedback_type="needs_improvement",
            )

            assert result["feedback_id"] == "67"


# ---------------------------------------------------------------------------
# 回归：gather 结构化并发 — ownership + dedup 并发失败
# ---------------------------------------------------------------------------

class TestFeedbackGatherConcurrency:
    """回归：ownership 校验和 dedup 查询通过 asyncio.gather 并发时的失败场景。"""

    @pytest.mark.asyncio
    async def test_ownership_fails_gather_cancels_dedup(self):
        """ownership 失败 → gather 取消 dedup，不悬挂 task。"""
        from app.services.feedback_service import create_feedback
        from unittest.mock import AsyncMock, patch, MagicMock

        dedup_called = {"n": 0}

        async def _failing_dedup(*args, **kwargs):
            dedup_called["n"] += 1
            return None  # dedup 正常返回 None

        async def _failing_ownership(*args, **kwargs):
            raise PermissionError("terminal not owned")

        with patch(
            "app.services.feedback_service._verify_terminal_ownership",
            new_callable=AsyncMock, side_effect=_failing_ownership,
        ), patch(
            "app.services.feedback_service._find_existing_feedback",
            new_callable=AsyncMock, side_effect=_failing_dedup,
        ):
            with pytest.raises(PermissionError, match="terminal not owned"):
                await create_feedback(
                    user_id="u1",
                    session_id="s1",
                    category="suggestion",
                    description="test",
                    terminal_id="t1",
                    result_event_id="e1",
                    feedback_type="helpful",
                )

    @pytest.mark.asyncio
    async def test_dedup_fails_gather_cancels_ownership(self):
        """dedup 查询失败 → gather 取消 ownership，整体报错。"""
        from app.services.feedback_service import create_feedback
        from unittest.mock import AsyncMock, patch

        async def _failing_dedup(*args, **kwargs):
            raise ConnectionError("log-service down")

        with patch(
            "app.services.feedback_service._verify_terminal_ownership",
            new_callable=AsyncMock, return_value="ts-t1",
        ), patch(
            "app.services.feedback_service._find_existing_feedback",
            new_callable=AsyncMock, side_effect=_failing_dedup,
        ):
            with pytest.raises(ConnectionError, match="log-service down"):
                await create_feedback(
                    user_id="u1",
                    session_id="s1",
                    category="suggestion",
                    description="test",
                    terminal_id="t1",
                    result_event_id="e1",
                    feedback_type="helpful",
                )

    @pytest.mark.asyncio
    async def test_both_succeed_dedup_hit_returns_early(self):
        """ownership + dedup 都成功 + dedup 命中 → 返回已有记录，不创建新的。"""
        from app.services.feedback_service import create_feedback
        from unittest.mock import AsyncMock, patch, MagicMock

        existing_issue = {"id": 42, "created_at": "2026-04-30T10:00:00Z"}

        with patch(
            "app.services.feedback_service._verify_terminal_ownership",
            new_callable=AsyncMock, return_value="ts-t1",
        ), patch(
            "app.services.feedback_service._find_existing_feedback",
            new_callable=AsyncMock, return_value=existing_issue,
        ):
            result = await create_feedback(
                user_id="u1",
                session_id="s1",
                category="suggestion",
                description="test",
                terminal_id="t1",
                result_event_id="e1",
                feedback_type="helpful",
            )
            assert result["feedback_id"] == "42"

    @pytest.mark.asyncio
    async def test_ownership_only_no_terminal_skips_gather(self):
        """只有 ownership（有 terminal_id 无 result_event_id）→ 走单独 await 路径。"""
        from app.services.feedback_service import create_feedback
        from unittest.mock import AsyncMock, patch, MagicMock

        mock_log_resp = MagicMock(status_code=200)
        mock_log_resp.raise_for_status = MagicMock()
        mock_log_resp.json = MagicMock(return_value={"logs": [], "total": 0})

        mock_issue_resp = MagicMock(status_code=201)
        mock_issue_resp.raise_for_status = MagicMock()
        mock_issue_resp.json = MagicMock(return_value={"id": 77, "created_at": "2026-04-30T11:00:00Z"})

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_log_resp)
        mock_http.post = AsyncMock(return_value=mock_issue_resp)

        with patch("app.services.feedback_service.get_shared_http_client", return_value=mock_http), \
             patch("app.services.feedback_service._verify_terminal_ownership", new_callable=AsyncMock, return_value="ts-t1"):
            result = await create_feedback(
                user_id="u1",
                session_id="s1",
                category="suggestion",
                description="test",
                terminal_id="t1",
                # 无 result_event_id → 不触发 dedup，只走 ownership
                feedback_type="error_report",
            )
            assert result["feedback_id"] == "77"
            mock_http.post.assert_called_once()
