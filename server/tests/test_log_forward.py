"""
B046 测试: Server 转发 Client 日志到 log-service

测试项:
- [happy] Client 上报日志 → Redis 存储成功 + 转发到 log-service
- [fail] log-service 不可达 → Redis 正常存储，API 正常响应，本地 warning
- [boundary] 批量上报时转发正常
- [fail] log-service 响应超时时 Redis 正常存储
"""
import logging
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.infra.auth import generate_token


@pytest.fixture
def client():
    from app import app
    return TestClient(app)


@pytest.fixture
def auth_headers():
    token = generate_token("test-session-fwd", token_version=1, view_type="mobile")
    return {"Authorization": f"Bearer {token}"}


def _with_auth_mock():
    """公共 mock：get_token_version 返回匹配值"""
    return patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=1)


class TestLogForwarding:
    """日志代理转发测试"""

    def test_upload_logs_stores_and_forwards(self, client, auth_headers):
        """[happy] Client 上报日志 → Redis 存储成功 + 转发到 log-service"""
        with _with_auth_mock(), \
             patch("app.api.log_api._forward_to_log_service", new_callable=AsyncMock) as mock_fwd, \
             patch("app.api.log_api.append_logs_batch", new_callable=AsyncMock, return_value={"received": 2}):
            resp = client.post(
                "/api/logs",
                json={
                    "session_id": "test-session-fwd",
                    "logs": [
                        {"level": "info", "message": "test log 1"},
                        {"level": "error", "message": "test log 2"},
                    ],
                },
                headers=auth_headers,
            )
            assert resp.status_code == 200
            assert resp.json()["received"] == 2
            mock_fwd.assert_called_once()

    def test_upload_logs_redis_ok_forward_fails(self, client, auth_headers, caplog):
        """[fail] log-service 不可达 → Redis 正常存储，API 正常响应"""
        with _with_auth_mock(), \
             patch("app.api.log_api.append_logs_batch", new_callable=AsyncMock, return_value={"received": 1}), \
             patch("app.api.log_api.get_shared_http_client") as mock_client:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(side_effect=ConnectionError("log-service unreachable"))
            mock_client.return_value = mock_http

            with caplog.at_level(logging.WARNING, logger="app.api.log_api"):
                resp = client.post(
                    "/api/logs",
                    json={
                        "session_id": "test-session-fwd",
                        "logs": [{"level": "info", "message": "test"}],
                    },
                    headers=auth_headers,
                )
                assert resp.status_code == 200
                assert resp.json()["received"] == 1

        # 应有 warning 日志
        warning_logs = [r for r in caplog.records if r.name == "app.api.log_api" and r.levelno >= logging.WARNING and "best-effort" in r.message]
        assert len(warning_logs) >= 1

    def test_batch_forward_normal(self, client, auth_headers):
        """[boundary] 批量上报（10+ 条）时转发正常"""
        logs = [{"level": "info", "message": f"log {i}"} for i in range(15)]

        with _with_auth_mock(), \
             patch("app.api.log_api._forward_to_log_service", new_callable=AsyncMock) as mock_fwd, \
             patch("app.api.log_api.append_logs_batch", new_callable=AsyncMock, return_value={"received": 15}):
            resp = client.post(
                "/api/logs",
                json={"session_id": "test-session-fwd", "logs": logs},
                headers=auth_headers,
            )
            assert resp.status_code == 200
            assert resp.json()["received"] == 15
            mock_fwd.assert_called_once()

    def test_get_logs_unaffected(self, client, auth_headers):
        """[happy] GET /api/logs Redis 查询正常返回"""
        with _with_auth_mock(), \
             patch("app.store.session.get_session", new_callable=AsyncMock, return_value={
                 "id": "test-session-fwd", "user_id": "test-session-fwd", "owner": "test-session-fwd",
             }), \
             patch("app.api.log_api._verify_session_ownership", new_callable=AsyncMock), \
             patch("app.api.log_api.get_logs", new_callable=AsyncMock, return_value={
            "session_id": "test-session-fwd",
            "total": 0,
            "offset": 0,
            "limit": 100,
            "logs": [],
        }):
            resp = client.get(
                "/api/logs?session_id=test-session-fwd",
                headers=auth_headers,
            )
            assert resp.status_code == 200
            assert resp.json()["total"] == 0


class TestForwardFormat:
    """转发格式映射测试"""

    @pytest.mark.asyncio
    async def test_log_format_mapping(self):
        """日志格式映射正确"""
        from app.api.log_api import _forward_to_log_service

        with patch("app.api.log_api.get_shared_http_client") as mock_client:
            mock_http = AsyncMock()
            mock_http.post = AsyncMock(return_value=MagicMock(status_code=200))
            mock_client.return_value = mock_http

            logs = [
                {"level": "error", "message": "test msg", "timestamp": "2026-04-10T10:00:00Z", "metadata": {"key": "val"}},
            ]
            await _forward_to_log_service("sess-123", logs)

            # 验证调用参数
            call_args = mock_http.post.call_args
            assert call_args is not None
            body = call_args.kwargs.get("json") or call_args[1].get("json")
            assert body is not None
            entries = body["entries"]
            assert len(entries) == 1
            assert entries[0]["level"] == "error"
            assert entries[0]["message"] == "test msg"
            assert entries[0]["timestamp"] == "2026-04-10T10:00:00Z"
            assert entries[0]["service_name"] == "remote-control"
            assert entries[0]["component"] == "client"
            assert entries[0]["extra"]["session_id"] == "sess-123"
            assert entries[0]["extra"]["key"] == "val"

    @pytest.mark.asyncio
    async def test_forward_uses_correct_url(self):
        """[escape] 转发 URL 必须是 /api/logs/ingest（不是 /api/ingest）"""
        from app.api.log_api import _forward_to_log_service

        with patch("app.api.log_api.get_shared_http_client") as mock_client:
            mock_http = AsyncMock()
            mock_response = MagicMock(status_code=200)
            mock_response.raise_for_status = MagicMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_http

            await _forward_to_log_service("sess-123", [{"level": "info", "message": "test"}])

            call_args = mock_http.post.call_args
            url = call_args[0][0] if call_args[0] else call_args.kwargs.get("url", "")
            assert url.endswith("/api/logs/ingest"), f"Expected /api/logs/ingest, got {url}"

    @pytest.mark.asyncio
    async def test_forward_404_triggers_warning(self, caplog):
        """[escape] log-service 返回 404 时 raise_for_status 抛异常 → warning 日志"""
        from app.api.log_api import _forward_to_log_service
        from httpx import HTTPStatusError, Request, Response

        with patch("app.api.log_api.get_shared_http_client") as mock_client:
            mock_http = AsyncMock()
            mock_response = MagicMock(status_code=404)
            mock_response.raise_for_status = MagicMock(
                side_effect=HTTPStatusError("404", request=Request("POST", "http://test"), response=Response(status_code=404))
            )
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_http

            with caplog.at_level(logging.WARNING, logger="app.api.log_api"):
                await _forward_to_log_service("sess-123", [{"level": "info", "message": "test"}])

            warning_logs = [r for r in caplog.records if r.name == "app.api.log_api" and "best-effort" in r.message]
            assert len(warning_logs) >= 1, "404 应触发 warning 日志"


class TestForwardUid:
    """uid 字段透传测试"""

    @pytest.mark.asyncio
    async def test_forward_entry_contains_uid(self):
        """转发 entry 包含 uid 字段且值与客户端传来的一致"""
        from app.api.log_api import _forward_to_log_service

        with patch("app.api.log_api.get_shared_http_client") as mock_client:
            mock_http = AsyncMock()
            mock_response = MagicMock(status_code=200)
            mock_response.raise_for_status = MagicMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_http

            await _forward_to_log_service("sess-uid-test", [{"level": "info", "message": "test"}], uid="alice")

            call_args = mock_http.post.call_args
            body = call_args.kwargs.get("json") or call_args[1].get("json")
            entries = body["entries"]
            assert entries[0]["uid"] == "alice", f"Expected uid='alice', got '{entries[0].get('uid')}'"

    @pytest.mark.asyncio
    async def test_forward_entry_uid_empty_when_not_provided(self):
        """请求 body 无 uid → uid 为空字符串（不阻塞转发）"""
        from app.api.log_api import _forward_to_log_service

        with patch("app.api.log_api.get_shared_http_client") as mock_client:
            mock_http = AsyncMock()
            mock_response = MagicMock(status_code=200)
            mock_response.raise_for_status = MagicMock()
            mock_http.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_http

            await _forward_to_log_service("sess-no-uid", [{"level": "info", "message": "test"}])

            call_args = mock_http.post.call_args
            body = call_args.kwargs.get("json") or call_args[1].get("json")
            entries = body["entries"]
            assert entries[0]["uid"] == "", f"Expected uid='', got '{entries[0].get('uid')}'"
