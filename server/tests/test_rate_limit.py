"""
B067: 登录/注册速率限制测试

基于 Redis 的 IP 速率限制，验证 429 返回和 fail-open 行为。
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app import app
    return TestClient(app)


@pytest.fixture
def auth_env():
    """配置速率限制环境"""
    import os
    with patch.dict(os.environ, {"RATE_LIMIT_PER_MINUTE": "3"}):
        yield


class TestRateLimitLogin:
    """登录速率限制"""

    def test_under_limit_succeeds(self, client, auth_env):
        """限速内 → 全部成功"""
        from app.infra.auth import generate_token

        with patch("app.api.user_api.get_user", return_value={
            "username": "testuser", "password_hash": "$2b$12$" + "a" * 53
        }), \
             patch("app.api.user_api.verify_password", return_value=True), \
             patch("app.api.user_api.is_legacy_hash", return_value=False), \
             patch("app.api.user_api.get_session_by_name", return_value={
                 "id": "sess-1", "name": "testuser_session"
             }), \
             patch("app.api.user_api.create_token_with_session", return_value={
                 "session_id": "sess-1", "token": "old",
                 "expires_at": "2026-04-16T00:00:00Z"
             }), \
             patch("app.api.user_api.increment_token_version", new=AsyncMock(return_value=1)), \
             patch("app.api.user_api.generate_refresh_token", return_value="rt"), \
             patch("app.api.user_api.store_refresh_token", new=AsyncMock()), \
             patch("app.infra.rate_limit._get_rate_limit_redis") as mock_redis:
            # 模拟 Redis 返回递增计数
            redis = AsyncMock()
            redis.incr = AsyncMock(side_effect=[1, 2, 3])
            redis.expire = AsyncMock()
            mock_redis.return_value = redis

            for _ in range(3):
                resp = client.post("/api/login", json={"username": "testuser", "password": "pass"})
                assert resp.status_code == 200

    def test_over_limit_returns_429(self, client, auth_env):
        """超限 → 429 + Retry-After"""
        with patch("app.api.user_api.get_user", return_value={
            "username": "testuser", "password_hash": "$2b$12$" + "a" * 53
        }), \
             patch("app.api.user_api.verify_password", return_value=True), \
             patch("app.api.user_api.is_legacy_hash", return_value=False), \
             patch("app.api.user_api.get_session_by_name", return_value={
                 "id": "sess-1", "name": "testuser_session"
             }), \
             patch("app.api.user_api.create_token_with_session", return_value={
                 "session_id": "sess-1", "token": "old",
                 "expires_at": "2026-04-16T00:00:00Z"
             }), \
             patch("app.api.user_api.increment_token_version", new=AsyncMock(return_value=1)), \
             patch("app.api.user_api.generate_refresh_token", return_value="rt"), \
             patch("app.api.user_api.store_refresh_token", new=AsyncMock()), \
             patch("app.infra.rate_limit._get_rate_limit_redis") as mock_redis:
            redis = AsyncMock()
            redis.incr = AsyncMock(side_effect=[1, 2, 3, 4])
            redis.expire = AsyncMock()
            mock_redis.return_value = redis

            # 前 3 次成功
            for _ in range(3):
                resp = client.post("/api/login", json={"username": "testuser", "password": "pass"})
                assert resp.status_code == 200

            # 第 4 次 → 429
            resp = client.post("/api/login", json={"username": "testuser", "password": "pass"})
            assert resp.status_code == 429
            assert "retry-after" in resp.headers

    def test_redis_down_fail_open(self, client, auth_env):
        """Redis 不可用 → fail-open，不限速"""
        with patch("app.api.user_api.get_user", return_value={
            "username": "testuser", "password_hash": "$2b$12$" + "a" * 53
        }), \
             patch("app.api.user_api.verify_password", return_value=True), \
             patch("app.api.user_api.is_legacy_hash", return_value=False), \
             patch("app.api.user_api.get_session_by_name", return_value={
                 "id": "sess-1", "name": "testuser_session"
             }), \
             patch("app.api.user_api.create_token_with_session", return_value={
                 "session_id": "sess-1", "token": "old",
                 "expires_at": "2026-04-16T00:00:00Z"
             }), \
             patch("app.api.user_api.increment_token_version", new=AsyncMock(return_value=1)), \
             patch("app.api.user_api.generate_refresh_token", return_value="rt"), \
             patch("app.api.user_api.store_refresh_token", new=AsyncMock()), \
             patch("app.infra.rate_limit._get_rate_limit_redis", side_effect=Exception("Redis down")):
            # Redis 挂了，不应返回 429
            resp = client.post("/api/login", json={"username": "testuser", "password": "pass"})
            assert resp.status_code == 200


class TestRateLimitRegister:
    """注册速率限制"""

    def test_over_limit_returns_429(self, client, auth_env):
        """注册超限 → 429"""
        with patch("app.api.user_api.get_user", return_value=None), \
             patch("app.api.user_api.save_user", new=AsyncMock()), \
             patch("app.api.user_api.create_session", new=AsyncMock()), \
             patch("app.api.user_api.increment_token_version", new=AsyncMock(return_value=1)), \
             patch("app.infra.rate_limit._get_rate_limit_redis") as mock_redis:
            redis = AsyncMock()
            redis.incr = AsyncMock(return_value=4)
            redis.expire = AsyncMock()
            mock_redis.return_value = redis

            resp = client.post("/api/register", json={"username": "newuser", "password": "pass123"})
            assert resp.status_code == 429
            assert "retry-after" in resp.headers


class TestRateLimitUnit:
    """check_rate_limit 单元测试"""

    @pytest.mark.asyncio
    async def test_under_limit_returns_none(self):
        from app.infra.rate_limit import check_rate_limit
        with patch("app.infra.rate_limit._get_rate_limit_redis") as mock_redis:
            redis = AsyncMock()
            redis.incr = AsyncMock(return_value=5)
            redis.expire = AsyncMock()
            mock_redis.return_value = redis
            result = await check_rate_limit("1.2.3.4")
            assert result is None

    @pytest.mark.asyncio
    async def test_over_limit_returns_retry(self):
        from app.infra.rate_limit import check_rate_limit
        with patch("app.infra.rate_limit._get_rate_limit_redis") as mock_redis:
            redis = AsyncMock()
            redis.incr = AsyncMock(return_value=11)
            redis.expire = AsyncMock()
            mock_redis.return_value = redis
            result = await check_rate_limit("1.2.3.4")
            assert result == 60

    @pytest.mark.asyncio
    async def test_redis_error_returns_none(self):
        from app.infra.rate_limit import check_rate_limit
        with patch("app.infra.rate_limit._get_rate_limit_redis", side_effect=Exception("down")):
            result = await check_rate_limit("1.2.3.4")
            assert result is None

    @pytest.mark.asyncio
    async def test_first_request_sets_ttl(self):
        from app.infra.rate_limit import check_rate_limit
        with patch("app.infra.rate_limit._get_rate_limit_redis") as mock_redis:
            redis = AsyncMock()
            redis.incr = AsyncMock(return_value=1)
            redis.expire = AsyncMock()
            mock_redis.return_value = redis
            await check_rate_limit("1.2.3.4")
            redis.expire.assert_called_once()
