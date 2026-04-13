"""
B064: CORS 收紧测试

验证 CORS 中间件从环境变量读取允许域名，未设置时阻止所有跨域。
"""
import os
import pytest
from unittest.mock import patch


class TestCORSTightening:
    """CORS 配置收紧验证"""

    def test_no_cors_origins_env_blocks_cross_origin(self):
        """CORS_ORIGINS 未设置 → 跨域请求无 CORS 头"""
        from fastapi.testclient import TestClient

        # 保留 JWT_SECRET 等必要环境变量，仅移除 CORS_ORIGINS
        env_copy = {k: v for k, v in os.environ.items() if k != "CORS_ORIGINS"}
        with patch.dict(os.environ, env_copy, clear=True):
            import importlib
            import app as app_module
            importlib.reload(app_module)
            client = TestClient(app_module.app)

            response = client.options(
                "/health",
                headers={
                    "Origin": "http://evil.com",
                    "Access-Control-Request-Method": "GET",
                },
            )
            # 非允许域名 → 无 Access-Control-Allow-Origin 头
            assert "access-control-allow-origin" not in response.headers

    def test_configured_origin_allowed(self):
        """CORS_ORIGINS=http://localhost:3000 → 该域名通过"""
        from fastapi.testclient import TestClient

        with patch.dict(os.environ, {"CORS_ORIGINS": "http://localhost:3000"}, clear=False):
            import importlib
            import app as app_module
            importlib.reload(app_module)
            client = TestClient(app_module.app)

            response = client.options(
                "/health",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_non_configured_origin_blocked(self):
        """CORS_ORIGINS=http://a.com → Origin: http://evil.com 被拒"""
        from fastapi.testclient import TestClient

        with patch.dict(os.environ, {"CORS_ORIGINS": "http://a.com"}, clear=False):
            import importlib
            import app as app_module
            importlib.reload(app_module)
            client = TestClient(app_module.app)

            response = client.options(
                "/health",
                headers={
                    "Origin": "http://evil.com",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert "access-control-allow-origin" not in response.headers

    def test_multiple_origins_all_allowed(self):
        """CORS_ORIGINS=http://a.com,http://b.com → 两个域名都通过"""
        from fastapi.testclient import TestClient

        with patch.dict(os.environ, {"CORS_ORIGINS": "http://a.com,http://b.com"}, clear=False):
            import importlib
            import app as app_module
            importlib.reload(app_module)
            client = TestClient(app_module.app)

            for origin in ["http://a.com", "http://b.com"]:
                response = client.options(
                    "/health",
                    headers={
                        "Origin": origin,
                        "Access-Control-Request-Method": "GET",
                    },
                )
                assert response.headers.get("access-control-allow-origin") == origin

    def test_credentials_header_present_for_allowed_origin(self):
        """允许的域名 → Access-Control-Allow-Credentials: true"""
        from fastapi.testclient import TestClient

        with patch.dict(os.environ, {"CORS_ORIGINS": "http://localhost:3000"}, clear=False):
            import importlib
            import app as app_module
            importlib.reload(app_module)
            client = TestClient(app_module.app)

            response = client.options(
                "/health",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert response.headers.get("access-control-allow-credentials") == "true"

    def test_same_origin_request_works_without_cors(self):
        """同源请求（无 Origin 头）→ 正常响应，不受 CORS 限制"""
        from fastapi.testclient import TestClient

        env_copy = {k: v for k, v in os.environ.items() if k != "CORS_ORIGINS"}
        with patch.dict(os.environ, env_copy, clear=True):
            import importlib
            import app as app_module
            importlib.reload(app_module)
            client = TestClient(app_module.app)

            response = client.get("/health")
            assert response.status_code == 200
