"""
B103 测试: 用户反馈 → Eval Task 自动转换

覆盖：
- 反馈→candidate 流程（analyze_feedback）
- 未配置降级（EVAL_FEEDBACK_MODEL 未设置时跳过）
- 审核 API CRUD（list/approve/reject）
- 异步分析超时/LLM 5xx 降级
- LLM 畸形响应处理
- 脱敏摘要构建（不传原始内容）
- source_feedback_id 仅存引用 ID
"""
import json
import os
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.auth import generate_token
from evals.db import EvalDatabase
from evals.models import CandidateStatus, EvalTaskCandidate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """创建 TestClient"""
    from app import app
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """生成有效 JWT token"""
    token = generate_token("test-session-feedback", token_version=1, view_type="mobile")
    return {"Authorization": f"Bearer {token}"}


MOCK_SESSION = {
    "id": "test-session-feedback",
    "user_id": "testuser",
    "owner": "testuser",
    "created_at": "2026-04-25T10:00:00Z",
}


def _mock_eval_db(tmp_path):
    """创建临时 evals.db"""
    db_path = str(tmp_path / "test_evals.db")
    db = EvalDatabase(db_path)
    return db


# ---------------------------------------------------------------------------
# feedback_loop 核心逻辑测试
# ---------------------------------------------------------------------------


class TestGetFeedbackConfig:
    """测试配置检查逻辑"""

    def test_no_model_returns_none(self):
        """EVAL_FEEDBACK_MODEL 未配置时返回 None"""
        with patch.dict(os.environ, {}, clear=True):
            from evals.feedback_loop import get_feedback_config
            assert get_feedback_config() is None

    def test_model_configured_returns_config(self):
        """EVAL_FEEDBACK_MODEL 已配置时返回 config dict"""
        env = {
            "EVAL_FEEDBACK_MODEL": "test-model",
            "EVAL_FEEDBACK_BASE_URL": "http://test",
            "EVAL_FEEDBACK_API_KEY": "test-key",
        }
        with patch.dict(os.environ, env, clear=True):
            from evals.feedback_loop import get_feedback_config
            config = get_feedback_config()
            assert config is not None
            assert config["model"] == "test-model"
            assert config["base_url"] == "http://test"

    def test_model_without_base_url_falls_back_to_eval_agent(self):
        """EVAL_FEEDBACK_BASE_URL 未配置时复用 EVAL_AGENT_BASE_URL"""
        env = {
            "EVAL_FEEDBACK_MODEL": "test-model",
            "EVAL_AGENT_BASE_URL": "http://eval-agent",
            "EVAL_AGENT_API_KEY": "eval-key",
        }
        with patch.dict(os.environ, env, clear=True):
            from evals.feedback_loop import get_feedback_config
            config = get_feedback_config()
            assert config is not None
            assert config["base_url"] == "http://eval-agent"

    def test_model_without_any_base_url_returns_none(self):
        """model 有但 base_url 和 fallback 都没有时返回 None"""
        env = {"EVAL_FEEDBACK_MODEL": "test-model"}
        with patch.dict(os.environ, env, clear=True):
            from evals.feedback_loop import get_feedback_config
            assert get_feedback_config() is None


class TestBuildDesensitizedDescription:
    """测试脱敏摘要构建"""

    def test_short_description(self):
        from evals.feedback_loop import _build_desensitized_description
        result = _build_desensitized_description("connection", "short desc")
        assert "connection" in result
        assert "short desc" in result

    def test_long_description_truncated(self):
        from evals.feedback_loop import _build_desensitized_description
        long_desc = "x" * 500
        result = _build_desensitized_description("suggestion", long_desc)
        # 最多 200 字符
        assert "x" * 200 in result
        assert "x" * 201 not in result


class TestParseAnalysisResponse:
    """测试 LLM 响应解析"""

    def test_valid_json(self):
        from evals.feedback_loop import _parse_analysis_response
        response = {
            "choices": [{"message": {"content": json.dumps({
                "is_agent_quality": True,
                "suggested_intent": "打开项目",
                "suggested_category": "command_generation",
            })}}]
        }
        result = _parse_analysis_response(response)
        assert result is not None
        assert result["is_agent_quality"] is True
        assert result["suggested_intent"] == "打开项目"

    def test_not_agent_quality(self):
        from evals.feedback_loop import _parse_analysis_response
        response = {
            "choices": [{"message": {"content": json.dumps({
                "is_agent_quality": False,
            })}}]
        }
        result = _parse_analysis_response(response)
        assert result is not None
        assert result["is_agent_quality"] is False

    def test_markdown_code_block(self):
        from evals.feedback_loop import _parse_analysis_response
        response = {
            "choices": [{"message": {"content": "```json\n" + json.dumps({
                "is_agent_quality": True,
                "suggested_intent": "test",
                "suggested_category": "intent_classification",
            }) + "\n```"}}]
        }
        result = _parse_analysis_response(response)
        assert result is not None
        assert result["is_agent_quality"] is True

    def test_malformed_response(self):
        from evals.feedback_loop import _parse_analysis_response
        response = {"choices": [{"message": {"content": "not json"}}]}
        result = _parse_analysis_response(response)
        assert result is None

    def test_missing_choices(self):
        from evals.feedback_loop import _parse_analysis_response
        result = _parse_analysis_response({})
        assert result is None

    def test_missing_is_agent_quality(self):
        from evals.feedback_loop import _parse_analysis_response
        response = {
            "choices": [{"message": {"content": json.dumps({"suggested_intent": "test"})}}]
        }
        result = _parse_analysis_response(response)
        assert result is None


class TestAnalyzeFeedback:
    """测试完整分析流程"""

    @pytest.mark.asyncio
    async def test_unconfigured_skips(self, tmp_path):
        """EVAL_FEEDBACK_MODEL 未配置时跳过"""
        db = _mock_eval_db(tmp_path)
        await db.init_db()

        with patch.dict(os.environ, {}, clear=True):
            from evals.feedback_loop import analyze_feedback
            result = await analyze_feedback(
                db,
                feedback_id="fb-123",
                category="suggestion",
                description="test",
            )
            assert result is None

    @pytest.mark.asyncio
    async def test_llm_says_not_agent_quality(self, tmp_path):
        """LLM 判断不是 Agent 质量问题"""
        db = _mock_eval_db(tmp_path)
        await db.init_db()

        env = {
            "EVAL_FEEDBACK_MODEL": "test",
            "EVAL_FEEDBACK_BASE_URL": "http://test",
            "EVAL_FEEDBACK_API_KEY": "key",
        }
        mock_response = {
            "choices": [{"message": {"content": json.dumps({
                "is_agent_quality": False,
            })}}]
        }

        with patch.dict(os.environ, env, clear=True):
            from evals.feedback_loop import analyze_feedback
            with patch("evals.feedback_loop.call_llm", new_callable=AsyncMock, return_value=mock_response):
                result = await analyze_feedback(
                    db,
                    feedback_id="fb-123",
                    category="connection",
                    description="网络连接问题",
                )
                assert result is None

    @pytest.mark.asyncio
    async def test_llm_error_skips(self, tmp_path):
        """LLM 调用失败时跳过"""
        db = _mock_eval_db(tmp_path)
        await db.init_db()

        env = {
            "EVAL_FEEDBACK_MODEL": "test",
            "EVAL_FEEDBACK_BASE_URL": "http://test",
            "EVAL_FEEDBACK_API_KEY": "key",
        }

        with patch.dict(os.environ, env, clear=True):
            from evals.feedback_loop import analyze_feedback
            from evals.harness import LLMCallError
            with patch("evals.feedback_loop.call_llm", new_callable=AsyncMock, side_effect=LLMCallError("timeout")):
                result = await analyze_feedback(
                    db,
                    feedback_id="fb-123",
                    category="suggestion",
                    description="AI 回答不好",
                )
                assert result is None

    @pytest.mark.asyncio
    async def test_llm_malformed_response_skips(self, tmp_path):
        """LLM 畸形响应时跳过"""
        db = _mock_eval_db(tmp_path)
        await db.init_db()

        env = {
            "EVAL_FEEDBACK_MODEL": "test",
            "EVAL_FEEDBACK_BASE_URL": "http://test",
            "EVAL_FEEDBACK_API_KEY": "key",
        }

        with patch.dict(os.environ, env, clear=True):
            from evals.feedback_loop import analyze_feedback
            with patch("evals.feedback_loop.call_llm", new_callable=AsyncMock, return_value={"choices": []}):
                result = await analyze_feedback(
                    db,
                    feedback_id="fb-123",
                    category="suggestion",
                    description="AI 回答不好",
                )
                assert result is None

    @pytest.mark.asyncio
    async def test_creates_candidate_on_agent_quality(self, tmp_path):
        """LLM 判断为 Agent 质量问题时生成 candidate"""
        db = _mock_eval_db(tmp_path)
        await db.init_db()

        env = {
            "EVAL_FEEDBACK_MODEL": "test",
            "EVAL_FEEDBACK_BASE_URL": "http://test",
            "EVAL_FEEDBACK_API_KEY": "key",
        }
        mock_response = {
            "choices": [{"message": {"content": json.dumps({
                "is_agent_quality": True,
                "suggested_intent": "帮我启动 Redis",
                "suggested_category": "command_generation",
                "suggested_expected": {
                    "acceptable_types": ["command_sequence"],
                    "must_contain": ["redis"],
                },
            })}}]
        }

        with patch.dict(os.environ, env, clear=True):
            from evals.feedback_loop import analyze_feedback
            with patch("evals.feedback_loop.call_llm", new_callable=AsyncMock, return_value=mock_response):
                candidate_id = await analyze_feedback(
                    db,
                    feedback_id="fb-456",
                    category="suggestion",
                    description="AI 回答错误，没有生成正确的命令",
                )
                assert candidate_id is not None

                # 验证 candidate 已写入
                candidate = await db.get_task_candidate(candidate_id)
                assert candidate is not None
                assert candidate.source_feedback_id == "fb-456"  # 仅引用 ID
                assert candidate.suggested_intent == "帮我启动 Redis"
                assert candidate.suggested_category == "command_generation"
                assert candidate.status == CandidateStatus.PENDING

    @pytest.mark.asyncio
    async def test_missing_suggested_intent_skips(self, tmp_path):
        """LLM 返回缺少 suggested_intent 时跳过"""
        db = _mock_eval_db(tmp_path)
        await db.init_db()

        env = {
            "EVAL_FEEDBACK_MODEL": "test",
            "EVAL_FEEDBACK_BASE_URL": "http://test",
            "EVAL_FEEDBACK_API_KEY": "key",
        }
        mock_response = {
            "choices": [{"message": {"content": json.dumps({
                "is_agent_quality": True,
                "suggested_category": "command_generation",
            })}}]
        }

        with patch.dict(os.environ, env, clear=True):
            from evals.feedback_loop import analyze_feedback
            with patch("evals.feedback_loop.call_llm", new_callable=AsyncMock, return_value=mock_response):
                result = await analyze_feedback(
                    db,
                    feedback_id="fb-789",
                    category="suggestion",
                    description="test",
                )
                assert result is None


# ---------------------------------------------------------------------------
# 审核 helper 测试
# ---------------------------------------------------------------------------


class TestReviewHelpers:
    """测试 list/approve/reject helper"""

    @pytest.mark.asyncio
    async def test_list_candidates_empty(self, tmp_path):
        db = _mock_eval_db(tmp_path)
        await db.init_db()

        from evals.feedback_loop import list_candidates
        result = await list_candidates(db)
        assert result == []

    @pytest.mark.asyncio
    async def test_list_candidates_with_data(self, tmp_path):
        db = _mock_eval_db(tmp_path)
        await db.init_db()

        candidate = EvalTaskCandidate(
            source_feedback_id="fb-1",
            suggested_intent="test intent",
            suggested_category="intent_classification",
        )
        await db.save_task_candidate(candidate)

        from evals.feedback_loop import list_candidates
        result = await list_candidates(db)
        assert len(result) == 1
        assert result[0]["suggested_intent"] == "test intent"

    @pytest.mark.asyncio
    async def test_approve_candidate(self, tmp_path):
        db = _mock_eval_db(tmp_path)
        await db.init_db()

        candidate = EvalTaskCandidate(
            source_feedback_id="fb-1",
            suggested_intent="test intent",
        )
        await db.save_task_candidate(candidate)

        from evals.feedback_loop import approve_candidate
        result = await approve_candidate(db, candidate.candidate_id, reviewer="admin")
        assert result is not None
        assert result["status"] == "approved"
        assert result["reviewed_by"] == "admin"

    @pytest.mark.asyncio
    async def test_approve_nonexistent_returns_none(self, tmp_path):
        db = _mock_eval_db(tmp_path)
        await db.init_db()

        from evals.feedback_loop import approve_candidate
        result = await approve_candidate(db, "nonexistent", reviewer="admin")
        assert result is None

    @pytest.mark.asyncio
    async def test_approve_already_approved_returns_error(self, tmp_path):
        db = _mock_eval_db(tmp_path)
        await db.init_db()

        candidate = EvalTaskCandidate(
            source_feedback_id="fb-1",
            suggested_intent="test intent",
        )
        await db.save_task_candidate(candidate)

        from evals.feedback_loop import approve_candidate
        # First approve
        await approve_candidate(db, candidate.candidate_id, reviewer="admin")
        # Second approve should return error
        result = await approve_candidate(db, candidate.candidate_id, reviewer="admin2")
        assert result is not None
        assert "error" in result

    @pytest.mark.asyncio
    async def test_reject_candidate(self, tmp_path):
        db = _mock_eval_db(tmp_path)
        await db.init_db()

        candidate = EvalTaskCandidate(
            source_feedback_id="fb-1",
            suggested_intent="test intent",
        )
        await db.save_task_candidate(candidate)

        from evals.feedback_loop import reject_candidate
        result = await reject_candidate(db, candidate.candidate_id, reviewer="admin")
        assert result is not None
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_reject_nonexistent_returns_none(self, tmp_path):
        db = _mock_eval_db(tmp_path)
        await db.init_db()

        from evals.feedback_loop import reject_candidate
        result = await reject_candidate(db, "nonexistent", reviewer="admin")
        assert result is None


# ---------------------------------------------------------------------------
# API 端点测试
# ---------------------------------------------------------------------------


class TestCandidateAPIAuth:
    """认证拦截测试"""

    def test_list_unauthenticated_returns_401(self, client):
        response = client.get("/api/eval/candidates")
        assert response.status_code in (401, 403)

    def test_approve_unauthenticated_returns_401(self, client):
        response = client.post("/api/eval/candidates/c-123/approve")
        assert response.status_code in (401, 403)

    def test_reject_unauthenticated_returns_401(self, client):
        response = client.post("/api/eval/candidates/c-123/reject")
        assert response.status_code in (401, 403)


def _apply_auth_and_db(mock_db):
    """统一 patch 认证 + eval db"""
    return [
        patch("app.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION),
        patch("app.auth.get_token_version", new_callable=AsyncMock, return_value=1),
        patch("app.runtime_api._get_eval_db", return_value=mock_db),
    ]


class TestCandidateAPIHappy:
    """API 正常场景测试"""

    def test_list_returns_200(self, client, auth_headers):
        mock_db = MagicMock()
        mock_db.list_task_candidates = AsyncMock(return_value=[])
        patches = _apply_auth_and_db(mock_db)
        started = [p.start() for p in patches]
        try:
            response = client.get("/api/eval/candidates", headers=auth_headers)
            assert response.status_code == 200
            assert response.json() == []
        finally:
            for p in reversed(started):
                p.stop()

    def test_approve_nonexistent_returns_404(self, client, auth_headers):
        mock_db = MagicMock()
        mock_db.get_task_candidate = AsyncMock(return_value=None)
        patches = _apply_auth_and_db(mock_db)
        started = [p.start() for p in patches]
        try:
            response = client.post(
                "/api/eval/candidates/nonexistent/approve",
                headers=auth_headers,
            )
            assert response.status_code == 404
        finally:
            for p in reversed(started):
                p.stop()

    def test_reject_nonexistent_returns_404(self, client, auth_headers):
        mock_db = MagicMock()
        mock_db.get_task_candidate = AsyncMock(return_value=None)
        patches = _apply_auth_and_db(mock_db)
        started = [p.start() for p in patches]
        try:
            response = client.post(
                "/api/eval/candidates/nonexistent/reject",
                headers=auth_headers,
            )
            assert response.status_code == 404
        finally:
            for p in reversed(started):
                p.stop()

    def test_db_error_returns_500(self, client, auth_headers):
        patches = [
            patch("app.session.get_session", new_callable=AsyncMock, return_value=MOCK_SESSION),
            patch("app.auth.get_token_version", new_callable=AsyncMock, return_value=1),
            patch("app.runtime_api._get_eval_db", side_effect=Exception("db error")),
        ]
        started = [p.start() for p in patches]
        try:
            response = client.get("/api/eval/candidates", headers=auth_headers)
            assert response.status_code == 500
        finally:
            for p in reversed(started):
                p.stop()
