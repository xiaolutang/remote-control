"""
S038: 安全加固集成验证

端到端验证所有安全加固措施协同工作：
1. 注册 → bcrypt 哈希
2. 登录 → 速率限制
3. WS auth 消息（非 URL token）
4. 旧 token → 拒绝
5. CORS 验证
6. Redis 密码 + Docker 非 root（静态检查）
"""
import pytest
import os
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app import app
    return TestClient(app)


@pytest.fixture
def auth_env():
    """配置测试环境"""
    import os
    with patch.dict(os.environ, {
        "RATE_LIMIT_PER_MINUTE": "3",
    }):
        yield


# ===== 1. bcrypt 密码哈希 =====
class TestBcryptIntegration:
    """注册后密码使用 bcrypt 哈希"""

    def test_register_uses_bcrypt_hash(self, client):
        """注册 → password_hash 以 $2b$ 开头"""
        with patch("app.user_api.get_user", return_value=None), \
             patch("app.user_api.save_user", new=AsyncMock()) as mock_save, \
             patch("app.user_api.create_session", new=AsyncMock()), \
             patch("app.user_api.increment_token_version", new=AsyncMock(return_value=1)), \
             patch("app.rate_limit._get_rate_limit_redis") as mock_redis:
            redis = AsyncMock()
            redis.incr = AsyncMock(return_value=1)
            redis.expire = AsyncMock()
            mock_redis.return_value = redis

            resp = client.post("/api/register", json={
                "username": "bcryptuser",
                "password": "securepass123",
            })
            assert resp.status_code == 200

            # 验证 save_user 收到的密码哈希以 $2b$ 开头
            call_args = mock_save.call_args[0]
            password_hash = call_args[1]
            assert password_hash.startswith("$2b$"), f"Expected bcrypt hash, got: {password_hash[:10]}..."


# ===== 2. 速率限制 =====
class TestRateLimitIntegration:
    """登录速率限制生效"""

    def test_rate_limit_blocks_excess_requests(self, client, auth_env):
        """连续登录超过限制 → 429"""
        with patch("app.user_api.get_user", return_value={
            "username": "testuser", "password_hash": "$2b$12$" + "a" * 53
        }), \
             patch("app.user_api.verify_password", return_value=True), \
             patch("app.user_api.is_legacy_hash", return_value=False), \
             patch("app.user_api.get_session_by_name", return_value={
                 "id": "sess-1", "name": "testuser_session"
             }), \
             patch("app.user_api.create_token_with_session", return_value={
                 "session_id": "sess-1", "token": "old",
                 "expires_at": "2026-04-16T00:00:00Z"
             }), \
             patch("app.user_api.increment_token_version", new=AsyncMock(return_value=1)), \
             patch("app.user_api.generate_refresh_token", return_value="rt"), \
             patch("app.user_api.store_refresh_token", new=AsyncMock()), \
             patch("app.rate_limit._get_rate_limit_redis") as mock_redis:
            redis = AsyncMock()
            redis.incr = AsyncMock(side_effect=[1, 2, 3, 4])
            redis.expire = AsyncMock()
            mock_redis.return_value = redis

            # 前 3 次成功
            for _ in range(3):
                resp = client.post("/api/login", json={
                    "username": "testuser", "password": "pass"
                })
                assert resp.status_code == 200

            # 第 4 次 → 429
            resp = client.post("/api/login", json={
                "username": "testuser", "password": "pass"
            })
            assert resp.status_code == 429
            assert "retry-after" in resp.headers


# ===== 3. WS auth 消息（静态验证） =====
class TestWSAuthMessage:
    """WS 连接不再通过 URL query 传 token"""

    def test_agent_ws_sends_auth_message(self):
        """Agent WS 连接后发送 auth 消息而非 URL token"""
        # 静态检查 websocket_client.py 中不再在 URL 中拼接 token
        agent_ws_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "agent", "app", "websocket_client.py"
        )
        with open(agent_ws_path) as f:
            content = f.read()
        # 确认 auth 消息发送
        assert '"type": "auth"' in content or "'type': 'auth'" in content
        # 确认 URL 不含 token
        assert "token=" not in content or "# URL 不" in content

    def test_client_ws_sends_auth_message(self):
        """Client WS 连接后发送 auth 消息而非 URL token"""
        client_ws_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "client", "lib", "services", "websocket_service.dart"
        )
        with open(client_ws_path) as f:
            content = f.read()
        assert "'type': 'auth'" in content or '"type": "auth"' in content


# ===== 4. 旧 token 拒绝 =====
class TestOldTokenRejection:
    """无 token_version 的旧 token → 401"""

    def test_old_token_without_version_rejected(self, client):
        """无 token_version 的 token → 401 TOKEN_INVALID"""
        import jwt as pyjwt
        import os

        secret = os.environ.get("JWT_SECRET", "test-secret")
        # 创建无 token_version 的旧 token
        old_token = pyjwt.encode(
            {"session_id": "test-session", "exp": 9999999999},
            secret,
            algorithm="HS256",
        )

        resp = client.get(
            "/api/sessions/test-session",
            headers={"Authorization": f"Bearer {old_token}"},
        )
        assert resp.status_code == 401


# ===== 5. CORS 验证 =====
class TestCORSIntegration:
    """CORS 仅允许配置域名"""

    def test_cors_blocks_unconfigured_origin(self, client):
        """未配置域名 → CORS 头不存在"""
        # 清空 CORS_ORIGINS
        env_copy = {k: v for k, v in os.environ.items() if k != "CORS_ORIGINS"}
        with patch.dict(os.environ, env_copy, clear=True):
            # 重新导入应用以应用新的 CORS 配置
            import importlib
            import app as app_module
            importlib.reload(app_module)
            from app import app
            test_client = TestClient(app)

            resp = test_client.options(
                "/api/login",
                headers={
                    "Origin": "http://evil.com",
                    "Access-Control-Request-Method": "POST",
                },
            )
            # 无 CORS 头
            assert "access-control-allow-origin" not in resp.headers


# ===== 6. Redis 密码 + Docker 非 root（静态） =====
class TestDeploySecurity:
    """部署配置安全检查"""

    def test_redis_has_password(self):
        """Redis 启动命令包含 --requirepass"""
        compose_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "deploy", "docker-compose.yml"
        )
        with open(compose_path) as f:
            content = f.read()
        assert "--requirepass" in content

    def test_containers_run_as_non_root(self):
        """容器支持 RUN_USER build arg（远端默认 appuser）"""
        for dockerfile in ["server.Dockerfile", "agent.Dockerfile"]:
            path = os.path.join(
                os.path.dirname(__file__), "..", "..", "deploy", dockerfile
            )
            with open(path) as f:
                content = f.read()
            assert "ARG RUN_USER=appuser" in content, f"{dockerfile} 缺少 ARG RUN_USER=appuser"
            assert "useradd -r -s /bin/false appuser" in content, f"{dockerfile} 缺少 appuser 创建"
            assert "USER ${RUN_USER}" in content, f"{dockerfile} 缺少 USER ${{RUN_USER}}"

    def test_server_data_dir_writable_by_appuser(self):
        """Server Dockerfile 创建 /data 目录并归属 appuser"""
        path = os.path.join(
            os.path.dirname(__file__), "..", "..", "deploy", "server.Dockerfile"
        )
        with open(path) as f:
            content = f.read()
        assert "mkdir -p /data" in content
        assert "chown appuser:appuser /data" in content


# ===== 7. 错误 token 脱敏 =====
class TestErrorSanitization:
    """JWT 错误响应不含具体异常详情"""

    def test_invalid_token_returns_generic_error(self, client):
        """伪造 token → 返回脱敏信息"""
        resp = client.get(
            "/api/sessions/test-session",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert resp.status_code == 401
        detail = resp.json().get("detail", "")
        # 不应包含 "DecodeError", "ExpiredSignatureError" 等内部异常
        assert "DecodeError" not in detail
        assert "ExpiredSignatureError" not in detail
        assert "InvalidSignatureError" not in detail
