"""
pytest 配置
"""
import pytest
import sys
import os

# 添加项目根目录到 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# JWT_SECRET 必填，测试环境使用固定值
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-pytest")
os.environ.setdefault("TRUSTED_PROXY_TLS_TOKEN", "trusted-proxy-token-for-pytest")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key-for-pytest")

# macOS 根目录只读，设置可写的数据库路径
_db_dir = os.path.join(os.path.dirname(__file__), ".test_data")
os.makedirs(_db_dir, exist_ok=True)
os.environ.setdefault("DATABASE_PATH", os.path.join(_db_dir, "test_users.db"))


def pytest_addoption(parser):
    parser.addoption("--url", default="http://localhost:8880",
                     help="Server base URL for integration tests (default: http://localhost:8880)")


@pytest.fixture(autouse=True)
def _clear_projection_cache():
    """每个测试前后清空 SSE 全量投影缓存，防止跨测试泄露。"""
    from app.api.agent_conversation_helpers import _projection_cache
    _projection_cache.clear()
    yield
    _projection_cache.clear()


@pytest.fixture(autouse=True)
def _reset_redis_connection():
    """每个测试后重置 Redis 连接池，防止跨测试 event loop 泄露。

    redis.asyncio 连接池在 event loop 关闭后尝试 disconnect 时会触发
    RuntimeError: Event loop is closed。通过重置连接池避免此问题。

    跳过已被测试 mock 的连接（如 test_agent_creation_integration 中的 mock Redis）。
    """
    yield
    from app.store.session_redis_conn import redis_conn
    # 只重置真实连接池，不破坏测试注入的 mock（duck typing：mock 有 _mock_name 属性）
    _redis = redis_conn._redis
    if _redis is not None and not hasattr(_redis, '_mock_name'):
        redis_conn._redis = None
        redis_conn._pool = None
