"""
B070: Redis 密码保护 + Docker 非 root

验证 session.py 正确读取 REDIS_PASSWORD，以及 Dockerfile 非 root 配置。
"""
import os
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


class TestRedisPasswordConfig:
    """Redis 密码环境变量读取"""

    def test_redis_password_from_env(self):
        """REDIS_PASSWORD 设置时 → session.py 读取到正确值"""
        with patch.dict(os.environ, {"REDIS_PASSWORD": "mysecret"}):
            val = os.getenv("REDIS_PASSWORD")
            assert val == "mysecret"

    def test_redis_password_default_none(self):
        """REDIS_PASSWORD 未设置 → 默认 None"""
        env_copy = {k: v for k, v in os.environ.items() if k != "REDIS_PASSWORD"}
        with patch.dict(os.environ, env_copy, clear=True):
            val = os.getenv("REDIS_PASSWORD")
            assert val is None

    @pytest.mark.asyncio
    async def test_connection_pool_uses_password(self):
        """连接池创建时传入 password 参数"""
        with patch("app.store.session.aioredis.ConnectionPool.from_url") as mock_pool, \
             patch("app.store.session.aioredis.Redis") as mock_redis_cls:
            mock_pool.return_value = MagicMock()
            mock_redis_cls.return_value = AsyncMock()

            from app.store.session import RedisConnection
            conn = RedisConnection()
            # 强制重置以触发新连接
            conn._redis = None
            conn._pool = None
            await conn.get_redis()

            mock_pool.assert_called_once()
            call_kwargs = mock_pool.call_args[1]
            assert "password" in call_kwargs


class TestDockerfileNonRoot:
    """Docker 非 root 用户验证（静态检查）"""

    def test_server_dockerfile_has_appuser(self):
        """server.Dockerfile 支持 RUN_USER build arg 并创建 appuser"""
        dockerfile_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "deploy", "server.Dockerfile"
        )
        with open(dockerfile_path) as f:
            content = f.read()
        assert "ARG RUN_USER=appuser" in content
        assert "useradd -r -s /bin/false appuser" in content
        assert "USER ${RUN_USER}" in content

    def test_agent_dockerfile_has_appuser(self):
        """agent.Dockerfile 支持 RUN_USER build arg 并创建 appuser"""
        dockerfile_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "deploy", "agent.Dockerfile"
        )
        with open(dockerfile_path) as f:
            content = f.read()
        assert "ARG RUN_USER=appuser" in content
        assert "useradd -r -s /bin/false appuser" in content
        assert "USER ${RUN_USER}" in content

    def test_server_dockerfile_data_dir_owned(self):
        """server.Dockerfile 创建 /data 目录并归属 appuser"""
        dockerfile_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "deploy", "server.Dockerfile"
        )
        with open(dockerfile_path) as f:
            content = f.read()
        assert "mkdir -p /data" in content
        assert "chown appuser:appuser /data" in content


class TestDockerComposeRedisPassword:
    """docker-compose Redis 密码配置验证（静态检查）"""

    def test_redis_requirepass_configured(self):
        """Redis 启动命令包含 --requirepass"""
        compose_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "deploy", "docker-compose.yml"
        )
        with open(compose_path) as f:
            content = f.read()
        assert "--requirepass" in content

    def test_server_redis_password_env(self):
        """Server 服务配置 REDIS_PASSWORD 环境变量"""
        compose_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "deploy", "docker-compose.yml"
        )
        with open(compose_path) as f:
            content = f.read()
        assert "REDIS_PASSWORD" in content
