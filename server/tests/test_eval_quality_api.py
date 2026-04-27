"""
B102 测试: 质量指标 API + 聚合查询

GET /api/eval/quality/metrics 测试:
- [auth] 未认证请求返回 401
- [happy] 基本查询返回 200 + 空列表
- [filter] 按 metric_name 过滤
- [filter] 按 user_id 过滤
- [filter] 按 start_time/end_time 过滤
- [filter] 按 session_id 过滤
- [limit] limit 参数生效

GET /api/eval/quality/summary 测试:
- [happy] 基本查询返回 200
- [agg] 按日/周/月聚合

异常场景:
- [fail] evals.db 不可达时返回 500
"""
import os
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.infra.auth import generate_token


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """创建 TestClient（同步），复用 app 实例"""
    from app import app
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """生成有效 JWT token 的 Authorization headers"""
    token = generate_token("test-session-eval", token_version=1, view_type="mobile")
    return {"Authorization": f"Bearer {token}"}


# Mock session 返回真实 user_id
MOCK_SESSION = {
    "id": "test-session-eval",
    "user_id": "testuser",
    "owner": "testuser",
    "created_at": "2026-04-25T10:00:00Z",
}


def _make_mock_db():
    """创建 mock EvalDatabase，使用 spec 确保异步方法可 await。"""
    db = MagicMock(spec=["query_quality_metrics", "aggregate_quality_metrics"])
    db.query_quality_metrics = AsyncMock(return_value=[])
    db.aggregate_quality_metrics = AsyncMock(return_value=[])
    return db


def _apply_patches(patches):
    """批量启动 patches 并返回 stop 函数。"""
    started = []
    for p in patches:
        p.start()
        started.append(p)

    def stop():
        for p in reversed(started):
            p.stop()

    return stop


# ---------------------------------------------------------------------------
# GET /api/eval/quality/metrics 测试
# ---------------------------------------------------------------------------

class TestQualityMetricsAuth:
    """鉴权测试"""

    def test_unauthenticated_returns_401(self, client):
        """[auth] 未认证请求返回 401"""
        resp = client.get("/api/eval/quality/metrics")
        assert resp.status_code in (401, 403)


class TestQualityMetricsHappy:
    """基本查询测试"""

    def test_empty_result_returns_200(self, client, auth_headers):
        """[happy] 基本查询返回 200 + 空列表"""
        mock_db = _make_mock_db()
        stop = _apply_patches([
            patch("app.store.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION),
            patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=1),
            patch("app.api.eval_api._ensure_eval_db", new_callable=AsyncMock, return_value=mock_db),
        ])
        try:
            resp = client.get("/api/eval/quality/metrics", headers=auth_headers)
            assert resp.status_code == 200
            body = resp.json()
            assert isinstance(body, list)
            assert len(body) == 0
        finally:
            stop()

    def test_returns_metrics_list(self, client, auth_headers):
        """[happy] 返回指标列表"""
        from evals.models import QualityMetric

        metrics = [
            QualityMetric(
                metric_id="qm-001",
                session_id="sess-001",
                user_id="testuser",
                metric_name="task_success_rate",
                value=0.95,
                computed_at="2026-04-25T10:00:00+00:00",
            ),
        ]
        mock_db = _make_mock_db()
        mock_db.query_quality_metrics = AsyncMock(return_value=metrics)

        stop = _apply_patches([
            patch("app.store.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION),
            patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=1),
            patch("app.api.eval_api._ensure_eval_db", new_callable=AsyncMock, return_value=mock_db),
        ])
        try:
            resp = client.get("/api/eval/quality/metrics", headers=auth_headers)
            assert resp.status_code == 200
            body = resp.json()
            assert len(body) == 1
            assert body[0]["metric_id"] == "qm-001"
            assert body[0]["metric_name"] == "task_success_rate"
            assert body[0]["value"] == 0.95
        finally:
            stop()


class TestQualityMetricsFilters:
    """过滤参数测试"""

    def test_filter_by_metric_name(self, client, auth_headers):
        """[filter] 按 metric_name 过滤"""
        mock_db = _make_mock_db()
        stop = _apply_patches([
            patch("app.store.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION),
            patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=1),
            patch("app.api.eval_api._ensure_eval_db", new_callable=AsyncMock, return_value=mock_db),
        ])
        try:
            resp = client.get(
                "/api/eval/quality/metrics",
                params={"metric_name": "response_time_ms"},
                headers=auth_headers,
            )
            assert resp.status_code == 200
            mock_db.query_quality_metrics.assert_called_once()
            call_kwargs = mock_db.query_quality_metrics.call_args[1]
            assert call_kwargs["metric_name"] == "response_time_ms"
        finally:
            stop()

    def test_filter_by_user_id(self, client, auth_headers):
        """[filter] 按 user_id 过滤"""
        mock_db = _make_mock_db()
        stop = _apply_patches([
            patch("app.store.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION),
            patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=1),
            patch("app.api.eval_api._ensure_eval_db", new_callable=AsyncMock, return_value=mock_db),
        ])
        try:
            resp = client.get(
                "/api/eval/quality/metrics",
                params={"user_id": "testuser"},
                headers=auth_headers,
            )
            assert resp.status_code == 200
            call_kwargs = mock_db.query_quality_metrics.call_args[1]
            assert call_kwargs["user_id"] == "testuser"
        finally:
            stop()

    def test_filter_by_start_end_time(self, client, auth_headers):
        """[filter] 按 start_time/end_time 过滤"""
        mock_db = _make_mock_db()
        stop = _apply_patches([
            patch("app.store.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION),
            patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=1),
            patch("app.api.eval_api._ensure_eval_db", new_callable=AsyncMock, return_value=mock_db),
        ])
        try:
            resp = client.get(
                "/api/eval/quality/metrics",
                params={
                    "start_time": "2026-04-01T00:00:00",
                    "end_time": "2026-04-30T23:59:59",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 200
            call_kwargs = mock_db.query_quality_metrics.call_args[1]
            assert call_kwargs["start_time"] == "2026-04-01T00:00:00"
            assert call_kwargs["end_time"] == "2026-04-30T23:59:59"
        finally:
            stop()

    def test_filter_by_session_id(self, client, auth_headers):
        """[filter] 按 session_id 过滤"""
        mock_db = _make_mock_db()
        stop = _apply_patches([
            patch("app.store.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION),
            patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=1),
            patch("app.api.eval_api._ensure_eval_db", new_callable=AsyncMock, return_value=mock_db),
        ])
        try:
            resp = client.get(
                "/api/eval/quality/metrics",
                params={"session_id": "sess-123"},
                headers=auth_headers,
            )
            assert resp.status_code == 200
            call_kwargs = mock_db.query_quality_metrics.call_args[1]
            assert call_kwargs["session_id"] == "sess-123"
        finally:
            stop()

    def test_limit_parameter(self, client, auth_headers):
        """[limit] limit 参数生效"""
        mock_db = _make_mock_db()
        stop = _apply_patches([
            patch("app.store.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION),
            patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=1),
            patch("app.api.eval_api._ensure_eval_db", new_callable=AsyncMock, return_value=mock_db),
        ])
        try:
            resp = client.get(
                "/api/eval/quality/metrics",
                params={"limit": 50},
                headers=auth_headers,
            )
            assert resp.status_code == 200
            call_kwargs = mock_db.query_quality_metrics.call_args[1]
            assert call_kwargs["limit"] == 50
        finally:
            stop()


# ---------------------------------------------------------------------------
# GET /api/eval/quality/summary 测试
# ---------------------------------------------------------------------------

class TestQualitySummaryHappy:
    """聚合查询基本测试"""

    def test_empty_summary_returns_200(self, client, auth_headers):
        """[happy] 基本查询返回 200"""
        mock_db = _make_mock_db()
        stop = _apply_patches([
            patch("app.store.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION),
            patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=1),
            patch("app.api.eval_api._ensure_eval_db", new_callable=AsyncMock, return_value=mock_db),
        ])
        try:
            resp = client.get("/api/eval/quality/summary", headers=auth_headers)
            assert resp.status_code == 200
            body = resp.json()
            assert isinstance(body, list)
        finally:
            stop()

    def test_summary_with_data(self, client, auth_headers):
        """[happy] 聚合结果包含正确字段"""
        agg_result = [
            {
                "group_key": "2026-04-25",
                "metric_name": "task_success_rate",
                "count": 10,
                "avg_value": 0.92,
                "min_value": 0.8,
                "max_value": 1.0,
            },
        ]
        mock_db = _make_mock_db()
        mock_db.aggregate_quality_metrics = AsyncMock(return_value=agg_result)

        stop = _apply_patches([
            patch("app.store.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION),
            patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=1),
            patch("app.api.eval_api._ensure_eval_db", new_callable=AsyncMock, return_value=mock_db),
        ])
        try:
            resp = client.get("/api/eval/quality/summary", headers=auth_headers)
            assert resp.status_code == 200
            body = resp.json()
            assert len(body) == 1
            assert body[0]["group_key"] == "2026-04-25"
            assert body[0]["metric_name"] == "task_success_rate"
            assert body[0]["count"] == 10
            assert body[0]["avg_value"] == 0.92
        finally:
            stop()


class TestQualitySummaryAggregation:
    """聚合粒度测试"""

    def test_group_by_day(self, client, auth_headers):
        """[agg] 按日聚合"""
        mock_db = _make_mock_db()
        stop = _apply_patches([
            patch("app.store.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION),
            patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=1),
            patch("app.api.eval_api._ensure_eval_db", new_callable=AsyncMock, return_value=mock_db),
        ])
        try:
            resp = client.get(
                "/api/eval/quality/summary",
                params={"group_by": "day"},
                headers=auth_headers,
            )
            assert resp.status_code == 200
            call_kwargs = mock_db.aggregate_quality_metrics.call_args[1]
            assert call_kwargs["group_by"] == "day"
        finally:
            stop()

    def test_group_by_week(self, client, auth_headers):
        """[agg] 按周聚合"""
        mock_db = _make_mock_db()
        stop = _apply_patches([
            patch("app.store.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION),
            patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=1),
            patch("app.api.eval_api._ensure_eval_db", new_callable=AsyncMock, return_value=mock_db),
        ])
        try:
            resp = client.get(
                "/api/eval/quality/summary",
                params={"group_by": "week"},
                headers=auth_headers,
            )
            assert resp.status_code == 200
            call_kwargs = mock_db.aggregate_quality_metrics.call_args[1]
            assert call_kwargs["group_by"] == "week"
        finally:
            stop()

    def test_group_by_month(self, client, auth_headers):
        """[agg] 按月聚合"""
        mock_db = _make_mock_db()
        stop = _apply_patches([
            patch("app.store.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION),
            patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=1),
            patch("app.api.eval_api._ensure_eval_db", new_callable=AsyncMock, return_value=mock_db),
        ])
        try:
            resp = client.get(
                "/api/eval/quality/summary",
                params={"group_by": "month"},
                headers=auth_headers,
            )
            assert resp.status_code == 200
            call_kwargs = mock_db.aggregate_quality_metrics.call_args[1]
            assert call_kwargs["group_by"] == "month"
        finally:
            stop()


# ---------------------------------------------------------------------------
# 异常场景
# ---------------------------------------------------------------------------

class TestQualityMetricsDbError:
    """evals.db 不可达"""

    def test_db_error_returns_500_metrics(self, client, auth_headers):
        """[fail] evals.db 不可达时 metrics 返回 500"""
        mock_db = _make_mock_db()
        mock_db.query_quality_metrics = AsyncMock(side_effect=Exception("db connection failed"))

        stop = _apply_patches([
            patch("app.store.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION),
            patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=1),
            patch("app.api.eval_api._ensure_eval_db", new_callable=AsyncMock, return_value=mock_db),
        ])
        try:
            resp = client.get("/api/eval/quality/metrics", headers=auth_headers)
            assert resp.status_code == 500
        finally:
            stop()

    def test_db_error_returns_500_summary(self, client, auth_headers):
        """[fail] evals.db 不可达时 summary 返回 500"""
        mock_db = _make_mock_db()
        mock_db.aggregate_quality_metrics = AsyncMock(side_effect=Exception("db connection failed"))

        stop = _apply_patches([
            patch("app.store.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION),
            patch("app.infra.auth.get_token_version", new_callable=AsyncMock, return_value=1),
            patch("app.api.eval_api._ensure_eval_db", new_callable=AsyncMock, return_value=mock_db),
        ])
        try:
            resp = client.get("/api/eval/quality/summary", headers=auth_headers)
            assert resp.status_code == 500
        finally:
            stop()


# ---------------------------------------------------------------------------
# 数据库查询方法集成测试（使用临时数据库）
# ---------------------------------------------------------------------------

class TestQueryQualityMetricsIntegration:
    """query_quality_metrics 数据库集成测试"""

    @pytest.mark.asyncio
    async def test_query_with_filters(self, tmp_path):
        """多条件过滤查询"""
        from evals.db import EvalDatabase
        from evals.models import QualityMetric

        db_path = str(tmp_path / "test_evals.db")
        db = EvalDatabase(db_path)
        await db.init_db()

        # 插入测试数据
        metrics = [
            QualityMetric(
                metric_id=f"qm-{i}",
                session_id="sess-001" if i < 3 else "sess-002",
                user_id="user-001" if i < 4 else "user-002",
                device_id="dev-001",
                metric_name="task_success_rate" if i < 3 else "response_time_ms",
                value=0.8 + i * 0.05,
                computed_at=f"2026-04-{10 + i:02d}T10:00:00+00:00",
            )
            for i in range(6)
        ]
        for m in metrics:
            await db.save_quality_metric(m)

        # 按 metric_name 过滤
        result = await db.query_quality_metrics(metric_name="task_success_rate")
        assert len(result) == 3
        assert all(m.metric_name == "task_success_rate" for m in result)

        # 按 user_id 过滤
        result = await db.query_quality_metrics(user_id="user-002")
        assert len(result) == 2

        # 按 session_id 过滤
        result = await db.query_quality_metrics(session_id="sess-002")
        assert len(result) == 3

        # 按时间范围过滤
        result = await db.query_quality_metrics(
            start_time="2026-04-13T00:00:00",
            end_time="2026-04-15T23:59:59",
        )
        assert len(result) == 3  # Apr 13, 14, 15

        # limit
        result = await db.query_quality_metrics(limit=2)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_query_empty(self, tmp_path):
        """无匹配结果返回空列表"""
        from evals.db import EvalDatabase

        db_path = str(tmp_path / "test_evals.db")
        db = EvalDatabase(db_path)
        await db.init_db()

        result = await db.query_quality_metrics(metric_name="nonexistent")
        assert result == []


class TestAggregateQualityMetricsIntegration:
    """aggregate_quality_metrics 数据库集成测试"""

    @pytest.mark.asyncio
    async def test_aggregate_by_day(self, tmp_path):
        """按日聚合"""
        from evals.db import EvalDatabase
        from evals.models import QualityMetric

        db_path = str(tmp_path / "test_evals.db")
        db = EvalDatabase(db_path)
        await db.init_db()

        # 同一天插入多条数据
        for i in range(3):
            await db.save_quality_metric(QualityMetric(
                metric_id=f"qm-day-{i}",
                session_id="sess-001",
                metric_name="response_time_ms",
                value=100.0 + i * 50,
                computed_at=f"2026-04-25T{10 + i}:00:00+00:00",
            ))
        # 另一天
        for i in range(2):
            await db.save_quality_metric(QualityMetric(
                metric_id=f"qm-day2-{i}",
                session_id="sess-001",
                metric_name="response_time_ms",
                value=200.0 + i * 50,
                computed_at=f"2026-04-26T{10 + i}:00:00+00:00",
            ))

        result = await db.aggregate_quality_metrics(group_by="day")
        assert len(result) == 2  # 2 天

        # 验证聚合字段
        day_25 = [r for r in result if r["group_key"] == "2026-04-25"]
        assert len(day_25) == 1
        assert day_25[0]["count"] == 3
        assert day_25[0]["min_value"] == 100.0
        assert day_25[0]["max_value"] == 200.0

    @pytest.mark.asyncio
    async def test_aggregate_by_month(self, tmp_path):
        """按月聚合"""
        from evals.db import EvalDatabase
        from evals.models import QualityMetric

        db_path = str(tmp_path / "test_evals.db")
        db = EvalDatabase(db_path)
        await db.init_db()

        for i in range(3):
            await db.save_quality_metric(QualityMetric(
                metric_id=f"qm-month-{i}",
                session_id="sess-001",
                metric_name="task_success_rate",
                value=0.9,
                computed_at=f"2026-04-{10 + i:02d}T10:00:00+00:00",
            ))

        result = await db.aggregate_quality_metrics(group_by="month")
        assert len(result) == 1
        assert result[0]["group_key"] == "2026-04"
        assert result[0]["count"] == 3

    @pytest.mark.asyncio
    async def test_aggregate_by_week(self, tmp_path):
        """按周聚合"""
        from evals.db import EvalDatabase
        from evals.models import QualityMetric

        db_path = str(tmp_path / "test_evals.db")
        db = EvalDatabase(db_path)
        await db.init_db()

        await db.save_quality_metric(QualityMetric(
            metric_id="qm-week-1",
            session_id="sess-001",
            metric_name="response_time_ms",
            value=150.0,
            computed_at="2026-04-20T10:00:00+00:00",  # Sunday
        ))
        await db.save_quality_metric(QualityMetric(
            metric_id="qm-week-2",
            session_id="sess-001",
            metric_name="response_time_ms",
            value=200.0,
            computed_at="2026-04-22T10:00:00+00:00",  # Tuesday (same week)
        ))

        result = await db.aggregate_quality_metrics(group_by="week")
        assert len(result) == 1
        # SQLite strftime('%W') returns week number
        assert "W" in result[0]["group_key"]

    @pytest.mark.asyncio
    async def test_aggregate_with_filter(self, tmp_path):
        """聚合查询支持过滤"""
        from evals.db import EvalDatabase
        from evals.models import QualityMetric

        db_path = str(tmp_path / "test_evals.db")
        db = EvalDatabase(db_path)
        await db.init_db()

        # user-001 的数据
        await db.save_quality_metric(QualityMetric(
            metric_id="qm-f1",
            session_id="sess-001",
            user_id="user-001",
            metric_name="task_success_rate",
            value=0.95,
            computed_at="2026-04-25T10:00:00+00:00",
        ))
        # user-002 的数据
        await db.save_quality_metric(QualityMetric(
            metric_id="qm-f2",
            session_id="sess-002",
            user_id="user-002",
            metric_name="task_success_rate",
            value=0.80,
            computed_at="2026-04-25T11:00:00+00:00",
        ))

        result = await db.aggregate_quality_metrics(user_id="user-001", group_by="day")
        assert len(result) == 1
        assert result[0]["count"] == 1
        assert result[0]["avg_value"] == 0.95

    @pytest.mark.asyncio
    async def test_aggregate_multiple_metric_names(self, tmp_path):
        """不同 metric_name 分组聚合"""
        from evals.db import EvalDatabase
        from evals.models import QualityMetric

        db_path = str(tmp_path / "test_evals.db")
        db = EvalDatabase(db_path)
        await db.init_db()

        await db.save_quality_metric(QualityMetric(
            metric_id="qm-mn1",
            session_id="sess-001",
            metric_name="task_success_rate",
            value=0.9,
            computed_at="2026-04-25T10:00:00+00:00",
        ))
        await db.save_quality_metric(QualityMetric(
            metric_id="qm-mn2",
            session_id="sess-001",
            metric_name="response_time_ms",
            value=150.0,
            computed_at="2026-04-25T11:00:00+00:00",
        ))

        result = await db.aggregate_quality_metrics(group_by="day")
        assert len(result) == 2  # 2 different metric_name
        names = {r["metric_name"] for r in result}
        assert names == {"task_success_rate", "response_time_ms"}

    @pytest.mark.asyncio
    async def test_aggregate_empty(self, tmp_path):
        """空数据聚合返回空列表"""
        from evals.db import EvalDatabase

        db_path = str(tmp_path / "test_evals.db")
        db = EvalDatabase(db_path)
        await db.init_db()

        result = await db.aggregate_quality_metrics(group_by="day")
        assert result == []
