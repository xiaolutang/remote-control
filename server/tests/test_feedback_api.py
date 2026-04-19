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

from app.auth import generate_token


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
    session_patch = patch("app.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION)
    token_version_patch = patch("app.auth.get_token_version", new_callable=AsyncMock, return_value=1)

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

    client_patch = patch("app.feedback_service.get_shared_http_client", return_value=mock_http)

    return [session_patch, token_version_patch, client_patch], mock_http


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
        with patch("app.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION), \
             patch("app.auth.get_token_version", new_callable=AsyncMock, return_value=1):
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

        with patch("app.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION), \
             patch("app.auth.get_token_version", new_callable=AsyncMock, return_value=1), \
             patch("app.feedback_api.get_feedback", new_callable=AsyncMock, return_value=feedback_detail) as mock_get:
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
        with patch("app.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION), \
             patch("app.auth.get_token_version", new_callable=AsyncMock, return_value=1), \
             patch("app.feedback_api.get_feedback", new_callable=AsyncMock, return_value=None):
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

        with patch("app.session.get_session", new_callable=AsyncMock, return_value=other_session), \
             patch("app.auth.get_token_version", new_callable=AsyncMock, return_value=1), \
             patch("app.feedback_api.get_feedback", new_callable=AsyncMock, return_value=None) as mock_get:
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
        patches[0] = patch("app.session.get_session", new_callable=AsyncMock,
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
        patches[0] = patch("app.session.get_session", new_callable=AsyncMock, return_value=session_no_user)

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
        with patch("app.user_api.get_user", new_callable=AsyncMock, return_value={
            "username": "testuser", "password_hash": real_hash, "created_at": "2026-04-01T00:00:00Z"
        }), \
             patch("app.user_api.create_session", new_callable=AsyncMock, return_value={
                 "session_id": "sess-1", "status": "pending", "created_at": "2026-04-12T00:00:00Z",
                 "user_id": "testuser", "owner": "testuser"
             }), \
             patch("app.user_api.increment_token_version", new_callable=AsyncMock, return_value=1), \
             patch("app.user_api.store_refresh_token", new_callable=AsyncMock), \
             patch("app.user_api.update_password_hash", new_callable=AsyncMock):
            resp = client.post("/api/login", json={"username": "testuser", "password": "test123456"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == "testuser"
        assert body["success"] is True

    def test_register_response_contains_username(self, client):
        """[contract] register 响应包含 username"""
        with patch("app.user_api.get_user", new_callable=AsyncMock, return_value=None), \
             patch("app.user_api.save_user", new_callable=AsyncMock), \
             patch("app.user_api.create_session", new_callable=AsyncMock, return_value={
                 "session_id": "sess-2", "status": "pending", "created_at": "2026-04-12T00:00:00Z",
                 "user_id": "newuser", "owner": "newuser"
             }), \
             patch("app.user_api.increment_token_version", new_callable=AsyncMock, return_value=1):
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
        from app.feedback_service import get_feedback

        issue_resp = {
            "id": 42,
            "component": "feedback:connection",
            "reporter": "testuser",
            "request_id": "sess-123",
            "description": "连接断开",
            "environment": "android / 1.0.0",
            "created_at": "2026-04-12T12:00:00Z",
        }

        with patch("app.feedback_service.get_shared_http_client") as mock_client:
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
        from app.feedback_service import get_feedback

        issue_resp = {
            "id": 42,
            "component": "feedback:connection",
            "reporter": "otheruser",
            "description": "test",
            "created_at": "2026-04-12T12:00:00Z",
        }

        with patch("app.feedback_service.get_shared_http_client") as mock_client:
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
        from app.feedback_service import get_feedback
        from fastapi import HTTPException
        import httpx

        with patch("app.feedback_service.get_shared_http_client") as mock_client:
            mock_http = AsyncMock()
            mock_http.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client.return_value = mock_http

            with pytest.raises(HTTPException) as exc_info:
                await get_feedback("42", "testuser")
            assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_issue_not_found_returns_none(self):
        """issue 不存在 → 404 HTTPStatusError → None"""
        from app.feedback_service import get_feedback
        import httpx

        with patch("app.feedback_service.get_shared_http_client") as mock_client:
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
        from app.feedback_service import get_feedback

        issue_resp = {
            "id": 43,
            "component": "feedback:terminal",
            "reporter": "testuser",
            "request_id": "sess-456",
            "description": "终端无响应",
            "environment": "ios / 2.1.0",
            "created_at": "2026-04-12T13:00:00Z",
        }

        with patch("app.feedback_service.get_shared_http_client") as mock_client:
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
        from app.feedback_service import get_feedback

        issue_resp = {
            "id": 44,
            "component": "feedback:crash",
            "reporter": "testuser",
            "request_id": "sess-789",
            "description": "崩溃了",
            "environment": "android",
            "created_at": "2026-04-12T14:00:00Z",
        }

        with patch("app.feedback_service.get_shared_http_client") as mock_client:
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
        from app.feedback_service import get_feedback

        issue_resp = {
            "id": 45,
            "component": "feedback:suggestion",
            "reporter": "testuser",
            "request_id": "",
            "description": "建议",
            "environment": "",
            "created_at": "2026-04-12T15:00:00Z",
        }

        with patch("app.feedback_service.get_shared_http_client") as mock_client:
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
        from app import feedback_service
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
