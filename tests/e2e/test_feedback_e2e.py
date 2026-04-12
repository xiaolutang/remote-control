"""
S030: 反馈功能集成测试

端到端验证完整数据流：
1. POST /api/feedback → 提交反馈
2. GET /api/feedback/{id} → 查询反馈
3. 验证日志已关联

使用 FastAPI TestClient + mock Redis（内存 dict 模拟真实存储），
验证 API → Service → Redis 的完整链路。
"""
import json
import sys
import os
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

# 确保能 import server 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'server'))

from app.auth import generate_token


# ---------------------------------------------------------------------------
# 内存 Redis 模拟 — 让 POST 存储的数据可以被 GET 读回来
# ---------------------------------------------------------------------------

class InMemoryRedis:
    """简易内存 Redis，支持 hset/hgetall/lpush，用于集成测试。"""

    def __init__(self):
        self._store: dict[str, dict[str, str]] = {}
        self._lists: dict[str, list[str]] = {}

    async def hset(self, key: str, *, mapping: dict[str, str]):
        if key not in self._store:
            self._store[key] = {}
        self._store[key].update(mapping)

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self._store.get(key, {}))

    async def lpush(self, key: str, value: str):
        if key not in self._lists:
            self._lists[key] = []
        self._lists[key].insert(0, value)

    def pipeline(self):
        return InMemoryPipeline(self)


class InMemoryPipeline:
    """支持 async with 的 pipeline，延迟执行到 execute()。"""

    def __init__(self, redis: InMemoryRedis):
        self._redis = redis
        self._ops: list[tuple] = []

    def hset(self, key: str, *, mapping: dict):
        self._ops.append(("hset", key, mapping))
        return self

    def lpush(self, key: str, value: str):
        self._ops.append(("lpush", key, value))
        return self

    async def execute(self):
        results = []
        for op in self._ops:
            if op[0] == "hset":
                await self._redis.hset(op[1], mapping=op[2])
                results.append(True)
            elif op[0] == "lpush":
                await self._redis.lpush(op[1], op[2])
                results.append(1)
        return results

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def memory_redis():
    """创建内存 Redis 实例"""
    return InMemoryRedis()


@pytest.fixture
def client(memory_redis):
    """创建 TestClient，注入内存 Redis"""
    from app import app
    from fastapi.testclient import TestClient

    redis_conn_mock = MagicMock()
    redis_conn_mock.get_redis = AsyncMock(return_value=memory_redis)

    with patch("app.feedback_service.redis_conn", redis_conn_mock):
        yield TestClient(app)


@pytest.fixture
def auth_headers():
    """有效 JWT headers"""
    token = generate_token("e2e-test-user")
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 集成测试
# ---------------------------------------------------------------------------

class TestFeedbackE2E:
    """端到端反馈流程"""

    def test_submit_and_query_feedback_with_logs(self, client, auth_headers):
        """完整流程：提交反馈 → 查询反馈 → 验证日志已关联"""
        # mock get_logs 返回关联日志
        related_logs = [
            {"level": "info", "message": "session started", "timestamp": "2026-04-12T10:00:00Z"},
            {"level": "warning", "message": "slow response", "timestamp": "2026-04-12T10:01:00Z"},
        ]

        with patch("app.feedback_service.get_logs", new_callable=AsyncMock,
                    return_value={"logs": related_logs, "total": 2}):
            with patch("app.feedback_api._forward_feedback_to_log_service", new_callable=AsyncMock):
                # Step 1: POST 提交反馈
                resp = client.post(
                    "/api/feedback",
                    json={
                        "session_id": "e2e-test-user",
                        "category": "connection",
                        "description": "连接经常断开，请检查",
                        "platform": "ios",
                        "app_version": "1.0.0",
                    },
                    headers=auth_headers,
                )

        assert resp.status_code == 200, f"POST failed: {resp.json()}"
        body = resp.json()
        feedback_id = body["feedback_id"]
        assert feedback_id, "feedback_id 不应为空"
        assert "created_at" in body

        # Step 2: GET 查询反馈（Redis 数据由内存 mock 保留）
        resp2 = client.get(f"/api/feedback/{feedback_id}", headers=auth_headers)
        assert resp2.status_code == 200, f"GET failed: {resp2.json()}"
        detail = resp2.json()

        # Step 3: 验证数据完整性
        assert detail["feedback_id"] == feedback_id
        assert detail["user_id"] == "e2e-test-user"
        assert detail["session_id"] == "e2e-test-user"
        assert detail["category"] == "connection"
        assert detail["description"] == "连接经常断开，请检查"
        assert detail["platform"] == "ios"
        assert detail["app_version"] == "1.0.0"

        # Step 4: 验证日志已关联
        assert isinstance(detail["logs"], list)
        assert len(detail["logs"]) == 2
        assert detail["logs"][0]["level"] == "info"
        assert detail["logs"][1]["level"] == "warning"

    def test_submit_and_query_feedback_without_logs(self, client, auth_headers):
        """完整流程：无日志时 → 反馈正常存储，logs 为空列表"""
        with patch("app.feedback_service.get_logs", new_callable=AsyncMock,
                    return_value={"logs": [], "total": 0}):
            with patch("app.feedback_api._forward_feedback_to_log_service", new_callable=AsyncMock):
                resp = client.post(
                    "/api/feedback",
                    json={
                        "session_id": "e2e-test-user",
                        "category": "suggestion",
                        "description": "希望增加暗黑模式支持",
                    },
                    headers=auth_headers,
                )

        assert resp.status_code == 200
        feedback_id = resp.json()["feedback_id"]

        # 查询回来验证
        resp2 = client.get(f"/api/feedback/{feedback_id}", headers=auth_headers)
        assert resp2.status_code == 200
        detail = resp2.json()
        assert detail["category"] == "suggestion"
        assert detail["logs"] == []

    def test_submit_then_cross_user_query_returns_404(self, client, auth_headers):
        """提交后其他用户查询 → 404（归属校验）"""
        with patch("app.feedback_service.get_logs", new_callable=AsyncMock,
                    return_value={"logs": [], "total": 0}):
            with patch("app.feedback_api._forward_feedback_to_log_service", new_callable=AsyncMock):
                resp = client.post(
                    "/api/feedback",
                    json={
                        "session_id": "e2e-test-user",
                        "category": "terminal",
                        "description": "终端显示异常",
                    },
                    headers=auth_headers,
                )

        feedback_id = resp.json()["feedback_id"]

        # 其他用户查询
        other_token = generate_token("other-user-session")
        other_headers = {"Authorization": f"Bearer {other_token}"}
        resp2 = client.get(f"/api/feedback/{feedback_id}", headers=other_headers)

        assert resp2.status_code == 404
