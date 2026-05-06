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


@pytest.fixture(autouse=True)
def _clear_projection_cache():
    """每个测试前后清空 SSE 全量投影缓存，防止跨测试泄露。"""
    from app.api.agent_conversation_helpers import _projection_cache
    _projection_cache.clear()
    yield
    _projection_cache.clear()
