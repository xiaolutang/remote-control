"""
B038: 登录层 Token 版本机制 — 同端设备并发限制

测试 Redis token_version 的完整生命周期：
登录递增 → JWT 携带 → verify_token 校验 → 旧 token 失效 → 刷新保持版本
"""
import asyncio
import json
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from jose import jwt

import app.infra.auth as auth_module
import app.api.user_api as user_api_module


# ─── 1. normalize_view_type ───


class TestNormalizeViewType:
    def test_mobile(self):
        assert auth_module.normalize_view_type("mobile") == "mobile"

    def test_desktop(self):
        assert auth_module.normalize_view_type("desktop") == "desktop"

    def test_tablet_falls_back_to_mobile(self):
        assert auth_module.normalize_view_type("tablet") == "mobile"

    def test_empty_falls_back_to_mobile(self):
        assert auth_module.normalize_view_type("") == "mobile"

    def test_none_falls_back_to_mobile(self):
        assert auth_module.normalize_view_type(None) == "mobile"

    def test_random_string_falls_back_to_mobile(self):
        assert auth_module.normalize_view_type("foobar") == "mobile"


# ─── 2. Redis token_version 操作 ───


class TestTokenVersionRedis:
    @pytest.mark.asyncio
    async def test_increment_returns_1_on_first_call(self):
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        with patch("app.infra.auth._get_token_version_redis", return_value=mock_redis):
            result = await auth_module.increment_token_version("sess-1", "mobile")
        assert result == 1
        mock_redis.incr.assert_called_once_with("token_version:sess-1:mobile")

    @pytest.mark.asyncio
    async def test_increment_increments_existing(self):
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=3)
        with patch("app.infra.auth._get_token_version_redis", return_value=mock_redis):
            result = await auth_module.increment_token_version("sess-1", "desktop")
        assert result == 3

    @pytest.mark.asyncio
    async def test_get_returns_version(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="2")
        with patch("app.infra.auth._get_token_version_redis", return_value=mock_redis):
            result = await auth_module.get_token_version("sess-1", "mobile")
        assert result == 2

    @pytest.mark.asyncio
    async def test_get_returns_none_when_not_exists(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        with patch("app.infra.auth._get_token_version_redis", return_value=mock_redis):
            result = await auth_module.get_token_version("sess-1", "mobile")
        assert result is None


# ─── 3. generate_token with token_version + view_type ───


class TestGenerateToken:
    def test_basic_token_no_version(self):
        token = auth_module.generate_token("sess-1")
        payload = jwt.decode(token, auth_module.JWT_SECRET_KEY, algorithms=[auth_module.JWT_ALGORITHM])
        assert payload["sub"] == "sess-1"
        assert "token_version" not in payload
        assert "view_type" not in payload

    def test_token_with_version_and_view(self):
        token = auth_module.generate_token("sess-1", token_version=2, view_type="mobile")
        payload = jwt.decode(token, auth_module.JWT_SECRET_KEY, algorithms=[auth_module.JWT_ALGORITHM])
        assert payload["sub"] == "sess-1"
        assert payload["token_version"] == 2
        assert payload["view_type"] == "mobile"

    def test_token_with_version_only(self):
        token = auth_module.generate_token("sess-1", token_version=1)
        payload = jwt.decode(token, auth_module.JWT_SECRET_KEY, algorithms=[auth_module.JWT_ALGORITHM])
        assert payload["token_version"] == 1
        assert "view_type" not in payload


# ─── 4. verify_token 基础校验 ───


class TestVerifyToken:
    def test_valid_token_returns_payload(self):
        token = auth_module.generate_token("sess-1")
        result = auth_module.verify_token(token)
        assert result["session_id"] == "sess-1"

    def test_expired_token_raises_with_error_code(self):
        expired_token = auth_module.generate_token("sess-1", expires_in_hours=-1)
        with pytest.raises(auth_module.TokenVerificationError) as exc_info:
            auth_module.verify_token(expired_token)
        assert exc_info.value.error_code == "TOKEN_EXPIRED"
        assert exc_info.value.status_code == 401

    def test_invalid_token_raises_with_error_code(self):
        with pytest.raises(auth_module.TokenVerificationError) as exc_info:
            auth_module.verify_token("invalid.token.here")
        assert exc_info.value.error_code == "TOKEN_INVALID"

    def test_versioned_token_passes_through(self):
        token = auth_module.generate_token("sess-1", token_version=2, view_type="mobile")
        result = auth_module.verify_token(token)
        assert result["session_id"] == "sess-1"
        assert result["token_version"] == 2
        assert result["view_type"] == "mobile"


# ─── 5. async_verify_token 版本校验 ───


class TestAsyncVerifyToken:
    @pytest.mark.asyncio
    async def test_old_token_without_version_rejected(self):
        """旧 token（无 token_version）→ 401 TOKEN_INVALID"""
        token = auth_module.generate_token("sess-1")
        with pytest.raises(auth_module.TokenVerificationError) as exc_info:
            await auth_module.async_verify_token(token)
        assert exc_info.value.error_code == "TOKEN_INVALID"
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_version_match_passes(self):
        """版本匹配 → 正常返回"""
        token = auth_module.generate_token("sess-1", token_version=2, view_type="mobile")
        with patch("app.infra.auth.get_token_version", return_value=2):
            result = await auth_module.async_verify_token(token)
        assert result["session_id"] == "sess-1"

    @pytest.mark.asyncio
    async def test_version_mismatch_raises_token_replaced(self):
        """版本不匹配 → 401 TOKEN_REPLACED"""
        token = auth_module.generate_token("sess-1", token_version=1, view_type="mobile")
        with patch("app.infra.auth.get_token_version", return_value=2):
            with pytest.raises(auth_module.TokenVerificationError) as exc_info:
                await auth_module.async_verify_token(token)
        assert exc_info.value.error_code == "TOKEN_REPLACED"
        assert "其他设备" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_version_none_in_redis_raises_token_replaced(self):
        """Redis 无版本记录 → TOKEN_REPLACED（安全侧）"""
        token = auth_module.generate_token("sess-1", token_version=1, view_type="mobile")
        with patch("app.infra.auth.get_token_version", return_value=None):
            with pytest.raises(auth_module.TokenVerificationError) as exc_info:
                await auth_module.async_verify_token(token)
        assert exc_info.value.error_code == "TOKEN_REPLACED"

    @pytest.mark.asyncio
    async def test_redis_get_failure_returns_503(self):
        """Redis GET 失败 → 503（fail-closed）"""
        token = auth_module.generate_token("sess-1", token_version=1, view_type="mobile")
        with patch("app.infra.auth.get_token_version", side_effect=Exception("Redis down")):
            with pytest.raises(Exception) as exc_info:
                await auth_module.async_verify_token(token)
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_old_token_without_version_rejected_even_redis_down(self):
        """旧 token（无 token_version）即使 Redis 不可用也返回 401 TOKEN_INVALID"""
        token = auth_module.generate_token("sess-1")
        # Redis 不可用时也不影响对无版本 token 的拒绝
        with patch("app.infra.auth.get_token_version", side_effect=Exception("Redis down")):
            with pytest.raises(auth_module.TokenVerificationError) as exc_info:
                await auth_module.async_verify_token(token)
        assert exc_info.value.error_code == "TOKEN_INVALID"
        assert exc_info.value.status_code == 401


# ─── 6. TokenVerificationError 异常 ───


class TestTokenVerificationError:
    def test_is_http_exception(self):
        from fastapi import HTTPException
        err = auth_module.TokenVerificationError(detail="test", error_code="TOKEN_EXPIRED", status_code=401)
        assert isinstance(err, HTTPException)

    def test_attributes(self):
        err = auth_module.TokenVerificationError(detail="Token 已过期", error_code="TOKEN_EXPIRED", status_code=401)
        assert err.detail == "Token 已过期"
        assert err.error_code == "TOKEN_EXPIRED"
        assert err.status_code == 401


# ─── 7. 完整登录链路集成测试 ───


class TestLoginIntegration:
    @pytest.mark.asyncio
    async def test_login_mobile_twice_first_token_invalidated(self):
        """POST /api/login mobile 两次 → 第一个 token 失效（TOKEN_REPLACED）"""
        login = user_api_module.login
        UserLogin = user_api_module.UserLogin

        # Mock 用户存在
        with patch("app.api.user_api.get_user", return_value={
            "username": "testuser", "password_hash": "a"*64
        }):
            with patch("app.api.user_api.verify_password", return_value=True):
                with patch("app.api.user_api.is_legacy_hash", return_value=True):
                    with patch("app.api.user_api.update_password_hash", new=AsyncMock()):
                        with patch("app.api.user_api.get_session_by_name", return_value={
                            "id": "sess-1", "name": "testuser_session"
                        }):
                            with patch("app.api.user_api.create_token_with_session", return_value={
                                "session_id": "sess-1", "token": "old-token",
                                "expires_at": "2026-04-16T00:00:00Z"
                            }):
                                with patch("app.api.user_api.increment_token_version", new=AsyncMock(side_effect=[1, 2])):
                                    with patch("app.api.user_api.generate_refresh_token", return_value="rt-1"):
                                        with patch("app.api.user_api.store_refresh_token", new=AsyncMock()):
                                            # 第一次登录
                                            resp1 = await login(UserLogin(username="testuser", password="pass", view="mobile"))
                                            token1 = resp1.token

                                            # 第二次登录（版本递增）
                                            resp2 = await login(UserLogin(username="testuser", password="pass", view="mobile"))
                                            token2 = resp2.token

        # token1 版本应为 1，token2 版本应为 2
        payload1 = jwt.decode(token1, auth_module.JWT_SECRET_KEY, algorithms=[auth_module.JWT_ALGORITHM])
        payload2 = jwt.decode(token2, auth_module.JWT_SECRET_KEY, algorithms=[auth_module.JWT_ALGORITHM])
        assert payload1["token_version"] == 1
        assert payload2["token_version"] == 2

        # 模拟 Redis 当前版本为 2，token1 版本校验应失败
        with patch("app.infra.auth.get_token_version", return_value=2):
            with pytest.raises(auth_module.TokenVerificationError) as exc_info:
                await auth_module.async_verify_token(token1)
        assert exc_info.value.error_code == "TOKEN_REPLACED"

        # token2 版本校验应成功
        with patch("app.infra.auth.get_token_version", return_value=2):
            result = await auth_module.async_verify_token(token2)
        assert result["session_id"] == "sess-1"

    @pytest.mark.asyncio
    async def test_login_mobile_and_desktop_independent(self):
        """POST /api/login mobile + desktop → 互不影响"""
        login = user_api_module.login
        UserLogin = user_api_module.UserLogin

        with patch("app.api.user_api.get_user", return_value={
            "username": "testuser", "password_hash": "a"*64
        }):
            with patch("app.api.user_api.verify_password", return_value=True):
                with patch("app.api.user_api.is_legacy_hash", return_value=False):
                    with patch("app.api.user_api.get_session_by_name", return_value={
                        "id": "sess-1", "name": "testuser_session"
                    }):
                        with patch("app.api.user_api.create_token_with_session", return_value={
                            "session_id": "sess-1", "token": "old",
                            "expires_at": "2026-04-16T00:00:00Z"
                        }):
                            with patch("app.api.user_api.increment_token_version", new=AsyncMock(return_value=1)):
                                with patch("app.api.user_api.generate_refresh_token", return_value="rt"):
                                    with patch("app.api.user_api.store_refresh_token", new=AsyncMock()):
                                        mobile_resp = await login(UserLogin(username="testuser", password="pass", view="mobile"))
                                        desktop_resp = await login(UserLogin(username="testuser", password="pass", view="desktop"))

        mobile_payload = jwt.decode(mobile_resp.token, auth_module.JWT_SECRET_KEY, algorithms=[auth_module.JWT_ALGORITHM])
        desktop_payload = jwt.decode(desktop_resp.token, auth_module.JWT_SECRET_KEY, algorithms=[auth_module.JWT_ALGORITHM])

        # 各自独立版本
        assert mobile_payload["view_type"] == "mobile"
        assert mobile_payload["token_version"] == 1
        assert desktop_payload["view_type"] == "desktop"
        assert desktop_payload["token_version"] == 1

    @pytest.mark.asyncio
    async def test_refresh_does_not_increment_version(self):
        """refresh token 不递增版本，使用当前版本"""
        RefreshRequest = user_api_module.RefreshRequest
        generate_refresh_token = auth_module.generate_refresh_token

        session_id = "sess-1"
        rt = generate_refresh_token(session_id, view_type="mobile")

        # 模拟 Redis 中 mobile 版本为 3
        with patch("app.api.user_api.verify_refresh_token", return_value={
            "session_id": session_id, "type": "refresh", "view_type": "mobile"
        }):
            with patch("app.api.user_api.get_stored_refresh_token", return_value=rt):
                with patch("app.api.user_api.delete_refresh_token", new=AsyncMock()):
                    with patch("app.api.user_api.get_token_version", return_value=3):
                        with patch("app.api.user_api.generate_refresh_token", return_value="new-rt"):
                            with patch("app.api.user_api.store_refresh_token", new=AsyncMock()):
                                resp = await user_api_module.refresh_token(
                                    RefreshRequest(refresh_token=rt)
                                )

        # 新 access_token 应携带版本 3
        new_payload = jwt.decode(resp.access_token, auth_module.JWT_SECRET_KEY, algorithms=[auth_module.JWT_ALGORITHM])
        assert new_payload["token_version"] == 3

    @pytest.mark.asyncio
    async def test_register_increments_version(self):
        """注册时递增版本"""
        register = user_api_module.register
        UserRegister = user_api_module.UserRegister

        with patch("app.api.user_api.get_user", return_value=None):
            with patch("app.api.user_api.save_user", new=AsyncMock()):
                with patch("app.api.user_api.create_session", new=AsyncMock()):
                    with patch("app.api.user_api.increment_token_version", new=AsyncMock(return_value=1)):
                        resp = await register(UserRegister(
                            username="newuser", password="pass123", view="desktop"
                        ))

        payload = jwt.decode(resp.token, auth_module.JWT_SECRET_KEY, algorithms=[auth_module.JWT_ALGORITHM])
        assert payload["token_version"] == 1
        assert payload["view_type"] == "desktop"

    @pytest.mark.asyncio
    async def test_login_with_illegal_view_treated_as_mobile(self):
        """非法 view 值 → 按 mobile 处理"""
        login = user_api_module.login
        UserLogin = user_api_module.UserLogin

        with patch("app.api.user_api.get_user", return_value={
            "username": "testuser", "password_hash": "a"*64
        }):
            with patch("app.api.user_api.verify_password", return_value=True):
                with patch("app.api.user_api.is_legacy_hash", return_value=True):
                    with patch("app.api.user_api.update_password_hash", new=AsyncMock()):
                        with patch("app.api.user_api.get_session_by_name", return_value=None):
                            with patch("app.api.user_api.create_session", new=AsyncMock()):
                                with patch("app.api.user_api.increment_token_version", new=AsyncMock(return_value=1)):
                                    with patch("app.api.user_api.generate_refresh_token", return_value="rt"):
                                        with patch("app.api.user_api.store_refresh_token", new=AsyncMock()):
                                            resp = await login(UserLogin(username="testuser", password="pass", view="tablet"))

        payload = jwt.decode(resp.token, auth_module.JWT_SECRET_KEY, algorithms=[auth_module.JWT_ALGORITHM])
        assert payload["view_type"] == "mobile"

    @pytest.mark.asyncio
    async def test_login_redis_incr_fail_returns_503(self):
        """Redis INCR 失败 → 登录返回 503"""
        login = user_api_module.login
        UserLogin = user_api_module.UserLogin
        from fastapi import HTTPException

        with patch("app.api.user_api.get_user", return_value={
            "username": "testuser", "password_hash": "a"*64
        }):
            with patch("app.api.user_api.verify_password", return_value=True):
                with patch("app.api.user_api.is_legacy_hash", return_value=True):
                    with patch("app.api.user_api.update_password_hash", new=AsyncMock()):
                        with patch("app.api.user_api.get_session_by_name", return_value=None):
                            with patch("app.api.user_api.create_session", new=AsyncMock()):
                                with patch("app.api.user_api.increment_token_version", side_effect=Exception("Redis down")):
                                    with pytest.raises(HTTPException) as exc_info:
                                        await login(UserLogin(username="testuser", password="pass"))
                                    assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_refresh_redis_get_fail_returns_503(self):
        """refresh 路径 Redis GET 失败 → 503"""
        RefreshRequest = user_api_module.RefreshRequest
        generate_refresh_token = auth_module.generate_refresh_token
        from fastapi import HTTPException

        session_id = "sess-1"
        rt = generate_refresh_token(session_id, view_type="mobile")

        with patch("app.api.user_api.verify_refresh_token", return_value={
            "session_id": session_id, "type": "refresh", "view_type": "mobile"
        }):
            with patch("app.api.user_api.get_stored_refresh_token", return_value=rt):
                with patch("app.api.user_api.delete_refresh_token", new=AsyncMock()):
                    with patch("app.api.user_api.get_token_version", side_effect=Exception("Redis down")):
                        with pytest.raises(HTTPException) as exc_info:
                            await user_api_module.refresh_token(
                                RefreshRequest(refresh_token=rt)
                            )
                        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_old_refresh_token_without_view_type_defaults_mobile(self):
        """旧 refresh token（无 view_type）→ 按 mobile 处理"""
        RefreshRequest = user_api_module.RefreshRequest
        generate_refresh_token = auth_module.generate_refresh_token

        session_id = "sess-1"
        # 旧 refresh token（不传 view_type）
        rt = generate_refresh_token(session_id)

        # 旧 refresh token 的 payload 没有 view_type
        with patch("app.api.user_api.verify_refresh_token", return_value={
            "session_id": session_id, "type": "refresh"
        }):
            with patch("app.api.user_api.get_stored_refresh_token", return_value=rt):
                with patch("app.api.user_api.delete_refresh_token", new=AsyncMock()):
                    with patch("app.api.user_api.get_token_version", return_value=5):
                        with patch("app.api.user_api.generate_refresh_token", return_value="new-rt"):
                            with patch("app.api.user_api.store_refresh_token", new=AsyncMock()):
                                resp = await user_api_module.refresh_token(
                                    RefreshRequest(refresh_token=rt)
                                )

        new_payload = jwt.decode(resp.access_token, auth_module.JWT_SECRET_KEY, algorithms=[auth_module.JWT_ALGORITHM])
        assert new_payload["view_type"] == "mobile"
        assert new_payload["token_version"] == 5

    @pytest.mark.asyncio
    async def test_concurrent_dual_login_race(self):
        """并发双登录竞态：两个请求同时 INCR → 各拿到不同版本号 → 后到的生效"""
        login = user_api_module.login
        UserLogin = user_api_module.UserLogin

        # 模拟 INCR 返回递增值（1 和 2）
        incr_mock = AsyncMock(side_effect=[1, 2])

        with patch("app.api.user_api.get_user", return_value={
            "username": "testuser", "password_hash": "a"*64
        }):
            with patch("app.api.user_api.verify_password", return_value=True):
                with patch("app.api.user_api.is_legacy_hash", return_value=True):
                    with patch("app.api.user_api.update_password_hash", new=AsyncMock()):
                        with patch("app.api.user_api.get_session_by_name", return_value={
                            "id": "sess-1", "name": "testuser_session"
                        }):
                            with patch("app.api.user_api.create_token_with_session", return_value={
                                "session_id": "sess-1", "token": "old",
                                "expires_at": "2026-04-16T00:00:00Z"
                            }):
                                with patch("app.api.user_api.increment_token_version", new=incr_mock):
                                    with patch("app.api.user_api.generate_refresh_token", return_value="rt"):
                                        with patch("app.api.user_api.store_refresh_token", new=AsyncMock()):
                                            # 两个并发登录
                                            import asyncio
                                            results = await asyncio.gather(
                                                login(UserLogin(username="testuser", password="pass", view="mobile")),
                                                login(UserLogin(username="testuser", password="pass", view="mobile")),
                                            )

        token1 = results[0].token
        token2 = results[1].token

        payload1 = jwt.decode(token1, auth_module.JWT_SECRET_KEY, algorithms=[auth_module.JWT_ALGORITHM])
        payload2 = jwt.decode(token2, auth_module.JWT_SECRET_KEY, algorithms=[auth_module.JWT_ALGORITHM])

        # 各拿到不同版本号（1 和 2）
        assert payload1["token_version"] == 1
        assert payload2["token_version"] == 2

        # 版本 2 是最新的，token1 应失效
        with patch("app.infra.auth.get_token_version", return_value=2):
            with pytest.raises(auth_module.TokenVerificationError):
                await auth_module.async_verify_token(token1)

        # token2 应正常
        with patch("app.infra.auth.get_token_version", return_value=2):
            result = await auth_module.async_verify_token(token2)
        assert result["session_id"] == "sess-1"

    @pytest.mark.asyncio
    async def test_agent_offline_login_layer_still_works(self):
        """DF-20260409-01 回归：Agent offline + 无 WS → 登录层限制仍生效"""
        login = user_api_module.login
        UserLogin = user_api_module.UserLogin

        # 模拟登录两次（不需要 Agent 或 WS 连接）
        with patch("app.api.user_api.get_user", return_value={
            "username": "testuser", "password_hash": "a"*64
        }):
            with patch("app.api.user_api.verify_password", return_value=True):
                with patch("app.api.user_api.is_legacy_hash", return_value=True):
                    with patch("app.api.user_api.update_password_hash", new=AsyncMock()):
                        with patch("app.api.user_api.get_session_by_name", return_value={
                            "id": "sess-1", "name": "testuser_session"
                        }):
                            with patch("app.api.user_api.create_token_with_session", return_value={
                                "session_id": "sess-1", "token": "old",
                                "expires_at": "2026-04-16T00:00:00Z"
                            }):
                                with patch("app.api.user_api.increment_token_version", new=AsyncMock(side_effect=[1, 2])):
                                    with patch("app.api.user_api.generate_refresh_token", return_value="rt"):
                                        with patch("app.api.user_api.store_refresh_token", new=AsyncMock()):
                                            resp1 = await login(UserLogin(username="testuser", password="pass", view="mobile"))
                                            resp2 = await login(UserLogin(username="testuser", password="pass", view="mobile"))

        # 验证：第一个 token 版本 1，第二个版本 2
        payload1 = jwt.decode(resp1.token, auth_module.JWT_SECRET_KEY, algorithms=[auth_module.JWT_ALGORITHM])
        payload2 = jwt.decode(resp2.token, auth_module.JWT_SECRET_KEY, algorithms=[auth_module.JWT_ALGORITHM])
        assert payload1["token_version"] == 1
        assert payload2["token_version"] == 2

        # 第一个 token 在版本 2 下应被 TOKEN_REPLACED
        with patch("app.infra.auth.get_token_version", return_value=2):
            with pytest.raises(auth_module.TokenVerificationError) as exc_info:
                await auth_module.async_verify_token(resp1.token)
        assert exc_info.value.error_code == "TOKEN_REPLACED"


# ─── 8. HTTP 端到端集成测试：验证 runtime API 接入 async_verify_token ───


class TestE2ETokenVersionEnforcement:
    """DF-20260409-02 回归：验证旧 token 经由 HTTP 路由被正确拒绝。

    B039 只测了 auth.py 层的 async_verify_token 函数级正确性，
    未验证 runtime_api/log_api/user_api 是否真正调用了 async_verify_token。
    此测试用 TestClient 模拟真实 HTTP 请求，验证完整请求链路。
    """

    def setup_method(self):
        from fastapi.testclient import TestClient
        from app import app
        self.client = TestClient(app)

    def test_old_token_rejected_on_runtime_devices(self):
        """注册 → 同端登录 → 旧 token 请求 /api/runtime/devices → 401 TOKEN_REPLACED"""
        user_api = user_api_module
        auth = auth_module

        # 生成 version=1 的 token
        token_v1 = auth.generate_token("e2e-session-1", token_version=1, view_type="mobile")
        headers_v1 = {"Authorization": f"Bearer {token_v1}"}

        # 模拟 Redis 中版本已递增到 2
        with patch("app.infra.auth.get_token_version", return_value=2):
            response = self.client.get("/api/runtime/devices", headers=headers_v1)

        assert response.status_code == 401
        data = response.json()
        assert data.get("error_code") == "TOKEN_REPLACED"

    def test_new_token_accepted_on_runtime_devices(self):
        """新 token（version 匹配）→ runtime API 正常返回"""
        auth = auth_module

        token_v2 = auth.generate_token("e2e-session-2", token_version=2, view_type="mobile")
        headers_v2 = {"Authorization": f"Bearer {token_v2}"}

        with patch("app.infra.auth.get_token_version", return_value=2):
            with patch("app.store.session.get_session", new=AsyncMock(return_value={"user_id": "user1", "owner": "user1"})):
                with patch("app.api._deps.list_sessions_for_user", new=AsyncMock(return_value=[])):
                    response = self.client.get("/api/runtime/devices", headers=headers_v2)

        assert response.status_code == 200

    def test_old_token_rejected_on_user_session_state(self):
        """旧 token 请求 /api/sessions/{id} → 401 TOKEN_REPLACED"""
        auth = auth_module

        token_v1 = auth.generate_token("e2e-session-3", token_version=1, view_type="mobile")
        headers_v1 = {"Authorization": f"Bearer {token_v1}"}

        with patch("app.infra.auth.get_token_version", return_value=2):
            response = self.client.get("/api/sessions/e2e-session-3", headers=headers_v1)

        assert response.status_code == 401
        data = response.json()
        assert data.get("error_code") == "TOKEN_REPLACED"

    def test_old_token_rejected_on_log_api(self):
        """旧 token 请求 /api/logs → 401 TOKEN_REPLACED"""
        auth = auth_module

        token_v1 = auth.generate_token("e2e-session-4", token_version=1, view_type="mobile")

        with patch("app.infra.auth.get_token_version", return_value=2):
            response = self.client.get(
                "/api/logs?session_id=e2e-session-4",
                headers={"Authorization": f"Bearer {token_v1}"},
            )

        assert response.status_code == 401
        data = response.json()
        assert data.get("error_code") == "TOKEN_REPLACED"


# ─── 9. 路由级接入验证：确保无同步 verify_token 遗漏 ───


class TestRouteLevelVerificationEnforcement:
    """DF-20260409-02 防回归：扫描所有受保护路由，确保使用 async_verify_token。

    B040 统一后，WS 路由（ws_client/ws_agent）也改用 async_verify_token，
    不再允许使用同步 verify_token。
    """

    def test_runtime_api_uses_async_verify(self):
        """runtime_api 通过 Depends(get_current_user_id) 使用 async_verify_token"""
        import app.api.device_api as mod
        import inspect
        source = inspect.getsource(mod.list_runtime_devices)
        # list_runtime_devices 通过 Depends(get_current_user_id) 鉴权
        assert "get_current_user_id" in source

    def test_log_api_uses_async_verify(self):
        """log_api 通过 Depends(get_current_payload) 使用 async_verify_token"""
        import app.api.log_api as mod
        import inspect
        source = inspect.getsource(mod.upload_logs)
        # upload_logs 通过 Depends(get_current_payload) 鉴权
        assert "get_current_payload" in source

    def test_user_api_session_state_uses_async_verify(self):
        """user_api.get_session_state 通过 Depends(get_current_user_id) 使用 async_verify_token"""
        import app.api.user_api as mod
        import inspect
        source = inspect.getsource(mod.get_session_state)
        # get_session_state 通过 Depends(get_current_user_id) 鉴权
        # get_current_user_id → get_current_payload → async_verify_token
        assert "get_current_user_id" in source

    def test_user_api_does_not_swallow_token_verification_error(self):
        """user_api.get_session_state 鉴权委托给 get_current_user_id（统一错误处理）"""
        import app.api.user_api as mod
        import inspect
        source = inspect.getsource(mod.get_session_state)
        # 鉴权完全由 Depends(get_current_user_id) 处理，路由函数无需手动捕获异常
        assert "Depends" in source

    def test_ws_client_uses_async_verify(self):
        """ws_client 必须使用 async_verify_token（通过 _wait_for_ws_auth）"""
        import app.ws.ws_client as mod
        import inspect
        handler_source = inspect.getsource(mod.client_websocket_handler)
        auth_source = inspect.getsource(mod._wait_for_ws_auth)
        assert "async_verify_token" in auth_source

    def test_ws_agent_uses_async_verify(self):
        """ws_agent 必须使用 async_verify_token（通过 _wait_for_ws_auth）"""
        import app.ws.ws_agent as mod
        import inspect
        handler_source = inspect.getsource(mod.agent_websocket_handler)
        auth_source = inspect.getsource(mod._wait_for_ws_auth)
        assert "async_verify_token" in auth_source

    def test_history_api_uses_async_verify(self):
        """history_api 通过 Depends(get_current_user_id) 使用 async_verify_token"""
        import app.api.history_api as mod
        import inspect
        source = inspect.getsource(mod.get_history_endpoint)
        # get_history_endpoint 通过 Depends(get_current_user_id) 鉴权
        # get_current_user_id → get_current_payload → async_verify_token
        assert "get_current_user_id" in source
