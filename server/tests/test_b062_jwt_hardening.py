"""
B062 测试: JWT Secret 加固 + 旧 token 拒绝

验收条件:
1. JWT_SECRET/JWT_SECRET_KEY 未设置 → 服务启动失败
2. 无 token_version 的 JWT → 401 TOKEN_INVALID
3. 有 token_version 且匹配 Redis → 正常通过
4. 有 token_version 但不匹配 Redis → 401 TOKEN_REPLACED
5. auth.py 无 secrets.token_hex 回退逻辑
6. auth.py 无向后兼容旧 token 分支
7. JWT 验证错误返回脱敏信息（不暴露异常详情）
"""
import pytest
import os
from unittest.mock import patch, AsyncMock

from app.infra.auth import (
    generate_token,
    verify_token,
    async_verify_token,
)


class TestJWTSecretRequired:
    """JWT_SECRET 必填校验"""

    def test_secret_missing_raises_runtime_error(self):
        """JWT_SECRET 和 JWT_SECRET_KEY 都未设置 → RuntimeError"""
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-c",
             "import os; os.environ.pop('JWT_SECRET', None); "
             "os.environ.pop('JWT_SECRET_KEY', None); import app.infra.auth"],
            capture_output=True, text=True,
            cwd=os.path.join(os.path.dirname(__file__), '..'),
        )
        assert result.returncode != 0, "Expected non-zero exit"
        assert "JWT_SECRET" in result.stderr

    def test_secret_set_module_loads_ok(self):
        """JWT_SECRET 设置 → 模块正常加载"""
        from app.infra.auth import JWT_SECRET_KEY
        assert JWT_SECRET_KEY is not None
        assert len(JWT_SECRET_KEY) > 0


class TestOldTokenRejected:
    """无 token_version 的旧 token 被拒绝"""

    @pytest.mark.asyncio
    async def test_old_token_without_version_rejected(self):
        """无 token_version 的 JWT → 401 TOKEN_INVALID"""
        from app.infra.auth import TokenVerificationError
        token = generate_token("session-no-version")
        try:
            await async_verify_token(token)
            assert False, "Expected TokenVerificationError"
        except TokenVerificationError as e:
            assert e.error_code == "TOKEN_INVALID"
            assert e.status_code == 401

    @pytest.mark.asyncio
    async def test_old_token_without_view_type_rejected(self):
        """有 token_version 但无 view_type → 401 TOKEN_INVALID"""
        from app.infra.auth import TokenVerificationError
        token = generate_token("session-no-viewtype", token_version=1)
        try:
            await async_verify_token(token)
            assert False, "Expected TokenVerificationError"
        except TokenVerificationError as e:
            assert e.error_code == "TOKEN_INVALID"


class TestTokenVersionMatch:
    """token_version 匹配校验"""

    @pytest.mark.asyncio
    async def test_version_matches_redis_passes(self):
        """token_version 匹配 Redis → 正常通过"""
        token = generate_token("session-match", token_version=2, view_type="mobile")
        with patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=2):
            result = await async_verify_token(token)
        assert result["session_id"] == "session-match"
        assert result["token_version"] == 2

    @pytest.mark.asyncio
    async def test_version_mismatch_returns_replaced(self):
        """token_version 不匹配 Redis → 401 TOKEN_REPLACED"""
        from app.infra.auth import TokenVerificationError
        token = generate_token("session-mismatch", token_version=1, view_type="mobile")
        with patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=2):
            try:
                await async_verify_token(token)
                assert False, "Expected TokenVerificationError"
            except TokenVerificationError as e:
                assert e.error_code == "TOKEN_REPLACED"
                assert "其他设备" in e.detail

    @pytest.mark.asyncio
    async def test_version_not_in_redis_returns_replaced(self):
        """Redis 中无版本记录 → TOKEN_REPLACED"""
        from app.infra.auth import TokenVerificationError
        token = generate_token("session-no-redis", token_version=1, view_type="mobile")
        with patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=None):
            try:
                await async_verify_token(token)
                assert False, "Expected TokenVerificationError"
            except TokenVerificationError as e:
                assert e.error_code == "TOKEN_REPLACED"


class TestErrorDesensitization:
    """JWT 错误信息脱敏"""

    def test_invalid_signature_returns_generic_error(self):
        """伪造签名 token → 返回脱敏信息，不含异常详情"""
        from app.infra.auth import TokenVerificationError
        from jose import jwt as jose_jwt
        fake_token = jose_jwt.encode(
            {"sub": "fake", "exp": 9999999999},
            "wrong-secret-key",
            algorithm="HS256",
        )
        try:
            verify_token(fake_token)
            assert False, "Expected TokenVerificationError"
        except TokenVerificationError as e:
            assert e.error_code == "TOKEN_INVALID"
            assert "wrong-secret-key" not in e.detail
            assert "Signature" not in e.detail

    def test_expired_token_returns_generic_error(self):
        """过期 token → 返回脱敏信息"""
        from app.infra.auth import TokenVerificationError
        token = generate_token("expired-session", expires_in_hours=-1)
        try:
            verify_token(token)
            assert False, "Expected TokenVerificationError"
        except TokenVerificationError as e:
            assert e.error_code == "TOKEN_EXPIRED"
            assert "过期" in e.detail


class TestNoFallback:
    """确保回退逻辑已移除"""

    def test_no_token_hex_fallback(self):
        """auth.py 不包含 secrets.token_hex 回退"""
        import inspect
        from app.infra import auth as auth_mod
        source = inspect.getsource(auth_mod)
        assert "secrets.token_hex" not in source
        assert "token_hex(32)" not in source

    def test_no_backward_compat_comment(self):
        """auth.py async_verify_token 不含向后兼容旧 token 注释"""
        import inspect
        source = inspect.getsource(async_verify_token)
        assert "向后兼容" not in source
        assert "直接放行" not in source
