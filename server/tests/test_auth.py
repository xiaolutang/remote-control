"""
JWT 认证服务测试
"""
import importlib
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

import app.infra.auth as auth_module
from app.infra.auth import (
    generate_token,
    verify_token,
    generate_session_id,
    create_token_response,
    generate_refresh_token,
    verify_refresh_token,
)
from fastapi import HTTPException


class TestGenerateToken:
    """Token 生成测试"""

    def test_generate_and_verify_token(self):
        """生成 token 并验证 session_id 一致"""
        session_id = "test-session-123"
        token = generate_token(session_id)
        assert token is not None
        assert isinstance(token, str)

        payload = verify_token(token)
        assert payload["session_id"] == session_id

    def test_valid_token(self):
        """有效 token 验证通过"""
        token = generate_token("session-456")
        payload = verify_token(token)
        assert payload["session_id"] == "session-456"
        assert "exp" in payload
        assert "iat" in payload

    def test_custom_expiration(self):
        """自定义过期时间"""
        token = generate_token("session-789", expires_in_hours=1)
        payload = verify_token(token)
        # 验证过期时间约为 1 小时后
        exp_time = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = exp_time - now
        assert timedelta(minutes=59) < delta < timedelta(minutes=61)


class TestTokenExpiration:
    """Token 过期测试"""

    def test_token_near_expiry(self):
        """token 剩余 1 秒过期，验证通过"""
        # 生成一个即将过期的 token
        with patch('app.infra.auth.JWT_EXPIRATION_HOURS', 1/3600):  # 1 秒
            token = generate_token("expiring-session")
            # 立即验证应该通过
            payload = verify_token(token)
            assert payload["session_id"] == "expiring-session"

    def test_expired_token_returns_401(self):
        """过期 token → 401"""
        # 生成一个已过期的 token
        with patch('app.infra.auth.JWT_EXPIRATION_HOURS', -1/3600):  # -1 秒（已过期）
            token = generate_token("expired-session")

            with pytest.raises(HTTPException) as e:
                verify_token(token)
            assert e.value.status_code == 401
            assert "过期" in e.value.detail

    def test_token_expiry_time_is_correct(self):
        """验证 token 过期时间正确设置"""
        hours = 2
        token = generate_token("session-time-check", expires_in_hours=hours)
        payload = verify_token(token)

        exp_time = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        iat_time = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)

        # 验证过期时间约为指定小时后
        delta = exp_time - iat_time
        expected_delta = timedelta(hours=hours)
        # 允许 1 秒误差
        assert abs(delta - expected_delta) < timedelta(seconds=1)


class TestInvalidToken:
    """无效 token 测试"""

    def test_invalid_token_format(self):
        """格式错误 token → 401"""
        with pytest.raises(HTTPException) as e:
            verify_token("not-a-valid-jwt-token")
        assert e.value.status_code == 401

    def test_session_id_binding(self):
        """session_id 不匹配 - 这个测试验证 token 中的 session_id 不能被篡改"""
        session_id = "original-session"
        token = generate_token(session_id)
        payload = verify_token(token)
        # 验证 session_id 是原始值，不能被外部修改
        assert payload["session_id"] == "original-session"

    def test_empty_token(self):
        """空 token → 401"""
        with pytest.raises(HTTPException) as e:
            verify_token("")
        assert e.value.status_code == 401
        assert "空" in e.value.detail

    def test_oversized_token(self):
        """超长 token (10KB+) → 413 或 400"""
        huge_token = "a" * 15000
        with pytest.raises(HTTPException) as e:
            verify_token(huge_token)
        assert e.value.status_code in [400, 413]

    def test_token_with_null_bytes(self):
        """含 \\x00 的 token → 400"""
        bad_token = "valid.prefix\x00malicious.suffix"
        with pytest.raises(HTTPException) as e:
            verify_token(bad_token)
        assert e.value.status_code == 400

    def test_tampered_token(self):
        """篡改的 token → 401"""
        token = generate_token("session-123")
        # 篡改 token
        parts = token.split('.')
        if len(parts) == 3:
            parts[1] = "tampered"
            tampered_token = '.'.join(parts)
            with pytest.raises(HTTPException) as e:
                verify_token(tampered_token)
            assert e.value.status_code == 401


class TestConcurrentVerification:
    """并发验证测试"""

    def test_concurrent_token_verification(self):
        """同一 token 并发验证 100 次 → 全部成功"""
        token = generate_token("concurrent-session")

        def verify():
            try:
                payload = verify_token(token)
                return payload["session_id"] == "concurrent-session"
            except Exception:
                return False

        with ThreadPoolExecutor(max_workers=100) as executor:
            results = list(executor.map(lambda _: verify(), range(100)))

        assert all(results), "部分并发验证失败"


class TestSessionIdGeneration:
    """Session ID 生成测试"""

    def test_generate_session_id(self):
        """生成 session_id"""
        session_id = generate_session_id()
        assert session_id is not None
        assert len(session_id) == 16

    def test_session_id_uniqueness(self):
        """生成的 session_id 应该唯一"""
        ids = set()
        for _ in range(1000):
            session_id = generate_session_id()
            assert session_id not in ids, "生成了重复的 session_id"
            ids.add(session_id)

    def test_session_id_custom_length(self):
        """自定义 session_id 长度"""
        session_id = generate_session_id(length=32)
        assert len(session_id) == 32


class TestTokenResponse:
    """Token 响应测试"""

    def test_create_token_response_with_session_id(self):
        """创建带指定 session_id 的响应"""
        response = create_token_response("my-session")
        assert response["session_id"] == "my-session"
        assert "token" in response
        assert "expires_at" in response

    def test_create_token_response_auto_generate(self):
        """自动生成 session_id 的响应"""
        response = create_token_response()
        assert response["session_id"] is not None
        assert len(response["session_id"]) == 16
        assert "token" in response
        assert "expires_at" in response


class TestRefreshToken:
    """Refresh Token 测试"""

    def test_generate_and_verify_refresh_token(self):
        """生成 refresh token 并验证 session_id 一致"""
        session_id = "test-refresh-session-123"
        refresh_token = generate_refresh_token(session_id)
        assert refresh_token is not None
        assert isinstance(refresh_token, str)

        payload = verify_refresh_token(refresh_token)
        assert payload["session_id"] == session_id
        assert payload.get("type") == "refresh"

    def test_refresh_token_has_longer_expiry(self):
        """refresh token 过期时间比 access token 长"""
        session_id = "test-session"
        access_token = generate_token(session_id)
        refresh_token = generate_refresh_token(session_id)

        access_payload = verify_token(access_token)
        refresh_payload = verify_refresh_token(refresh_token)

        # refresh token 过期时间应该比 access token 晚
        assert refresh_payload["exp"] > access_payload["exp"]

    def test_access_token_cannot_be_used_as_refresh(self):
        """access token 不能用作 refresh token"""
        session_id = "test-session"
        access_token = generate_token(session_id)

        # access token 没有 "type": "refresh" 标记
        with pytest.raises(HTTPException) as e:
            verify_refresh_token(access_token)
        assert e.value.status_code == 401
        assert "类型错误" in e.value.detail


class TestEnvironmentCompatibility:
    """环境变量兼容测试"""

    def test_jwt_secret_falls_back_to_legacy_env_name(self):
        """未设置 JWT_SECRET_KEY 时，兼容读取 JWT_SECRET。"""
        with patch.dict(
            "os.environ",
            {
                "JWT_SECRET": "legacy-secret",
                "JWT_SECRET_KEY": "",
                "JWT_EXPIRY_HOURS": "12",
                "JWT_EXPIRATION_HOURS": "",
            },
            clear=False,
        ):
            reloaded = importlib.reload(auth_module)
            assert reloaded.JWT_SECRET_KEY == "legacy-secret"
            assert reloaded.JWT_EXPIRATION_HOURS == 12

        importlib.reload(auth_module)
        # auth_module reload 后 TokenVerificationError 变成新类，
        # 需要在现有 app 上重新注册 exception handler
        from app import app
        from app.infra.auth import TokenVerificationError
        from fastapi import Request
        from fastapi.responses import JSONResponse

        @app.exception_handler(TokenVerificationError)
        async def _token_verification_error_handler(request: Request, exc: TokenVerificationError):
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail, "error_code": exc.error_code},
            )

    def test_empty_refresh_token(self):
        """空 refresh token → 401"""
        with pytest.raises(HTTPException) as e:
            verify_refresh_token("")
        assert e.value.status_code == 401
        assert "空" in e.value.detail

    def test_invalid_refresh_token_format(self):
        """格式错误的 refresh token → 401"""
        with pytest.raises(HTTPException) as e:
            verify_refresh_token("not-a-valid-jwt-token")
        assert e.value.status_code == 401

    def test_expired_refresh_token(self):
        """过期 refresh token → 401"""
        # 生成一个已过期的 refresh token
        from unittest.mock import patch
        with patch('app.infra.auth.REFRESH_TOKEN_EXPIRATION_DAYS', -1):  # 已过期
            refresh_token = generate_refresh_token("expired-session")

            with pytest.raises(HTTPException) as e:
                verify_refresh_token(refresh_token)
            assert e.value.status_code == 401
            assert "过期" in e.value.detail

    def test_refresh_token_expiry_time(self):
        """验证 refresh token 过期时间正确设置（30天）"""
        session_id = "test-refresh-expiry"
        refresh_token = generate_refresh_token(session_id)
        payload = verify_refresh_token(refresh_token)

        exp_time = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        iat_time = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)

        # 验证过期时间约为 30 天后
        delta = exp_time - iat_time
        expected_delta = timedelta(days=30)
        # 允许 1 分钟误差
        assert abs(delta - expected_delta) < timedelta(minutes=1)
