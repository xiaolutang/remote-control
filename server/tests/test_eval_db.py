"""
Eval 数据库层测试 - SQLite CRUD + 配置检查
"""
import json
import os
import pytest
import pytest_asyncio
import tempfile

from evals.db import EvalDatabase, EvalConfigError, get_eval_agent_config
from evals.models import (
    EvalTaskDef,
    EvalTaskInput,
    EvalTaskExpected,
    EvalTaskMetadata,
    EvalTrial,
    EvalGraderResult,
    EvalRun,
    QualityMetric,
    EvalTaskCandidate,
    CandidateStatus,
)


@pytest.fixture
def db_path(tmp_path):
    """创建临时数据库路径"""
    return str(tmp_path / "test_evals.db")


@pytest_asyncio.fixture
async def db(db_path):
    """创建并初始化测试数据库"""
    database = EvalDatabase(db_path)
    await database.init_db()
    return database


# ── 配置检查测试 ──────────────────────────────────────────────────────────


class TestEvalConfig:
    """评估配置检查测试"""

    def test_missing_model_raises(self):
        """缺少 EVAL_AGENT_MODEL 报错"""
        env = {
            "EVAL_AGENT_BASE_URL": "http://localhost:8000",
            "EVAL_AGENT_API_KEY": "test-key",
        }
        with pytest.MonkeyPatch.context() as m:
            for k, v in env.items():
                m.setenv(k, v)
            m.delenv("EVAL_AGENT_MODEL", raising=False)
            with pytest.raises(EvalConfigError, match="EVAL_AGENT_MODEL"):
                get_eval_agent_config()

    def test_missing_base_url_raises(self):
        """缺少 EVAL_AGENT_BASE_URL 报错"""
        env = {
            "EVAL_AGENT_MODEL": "gpt-4",
            "EVAL_AGENT_API_KEY": "test-key",
        }
        with pytest.MonkeyPatch.context() as m:
            for k, v in env.items():
                m.setenv(k, v)
            m.delenv("EVAL_AGENT_BASE_URL", raising=False)
            with pytest.raises(EvalConfigError, match="EVAL_AGENT_BASE_URL"):
                get_eval_agent_config()

    def test_missing_api_key_raises(self):
        """缺少 EVAL_AGENT_API_KEY 报错"""
        env = {
            "EVAL_AGENT_MODEL": "gpt-4",
            "EVAL_AGENT_BASE_URL": "http://localhost:8000",
        }
        with pytest.MonkeyPatch.context() as m:
            for k, v in env.items():
                m.setenv(k, v)
            m.delenv("EVAL_AGENT_API_KEY", raising=False)
            with pytest.raises(EvalConfigError, match="EVAL_AGENT_API_KEY"):
                get_eval_agent_config()

    def test_all_missing_raises(self):
        """全部缺失报错"""
        with pytest.MonkeyPatch.context() as m:
            m.delenv("EVAL_AGENT_MODEL", raising=False)
            m.delenv("EVAL_AGENT_BASE_URL", raising=False)
            m.delenv("EVAL_AGENT_API_KEY", raising=False)
            with pytest.raises(EvalConfigError, match="EVAL_AGENT_MODEL.*EVAL_AGENT_BASE_URL.*EVAL_AGENT_API_KEY"):
                get_eval_agent_config()

    def test_valid_config(self):
        """有效配置返回正确值"""
        with pytest.MonkeyPatch.context() as m:
            m.setenv("EVAL_AGENT_MODEL", "gpt-4")
            m.setenv("EVAL_AGENT_BASE_URL", "http://localhost:8000")
            m.setenv("EVAL_AGENT_API_KEY", "sk-test")
            m.delenv("EVAL_JUDGE_MODEL", raising=False)
            m.delenv("EVAL_JUDGE_BASE_URL", raising=False)
            m.delenv("EVAL_JUDGE_API_KEY", raising=False)

            config = get_eval_agent_config()
            assert config["model"] == "gpt-4"
            assert config["base_url"] == "http://localhost:8000"
            assert config["api_key"] == "sk-test"
            # Judge 默认值
            assert config["judge_base_url"] == "http://localhost:8000"
            assert config["judge_api_key"] == "sk-test"
            assert config["judge_model"] == "gpt-5.4"

    def test_judge_config_override(self):
        """Judge 配置覆盖"""
        with pytest.MonkeyPatch.context() as m:
            m.setenv("EVAL_AGENT_MODEL", "gpt-4")
            m.setenv("EVAL_AGENT_BASE_URL", "http://localhost:8000")
            m.setenv("EVAL_AGENT_API_KEY", "sk-test")
            m.setenv("EVAL_JUDGE_MODEL", "gpt-4o")
            m.setenv("EVAL_JUDGE_BASE_URL", "http://judge:8000")
            m.setenv("EVAL_JUDGE_API_KEY", "sk-judge")

            config = get_eval_agent_config()
            assert config["judge_model"] == "gpt-4o"
            assert config["judge_base_url"] == "http://judge:8000"
            assert config["judge_api_key"] == "sk-judge"

    def test_error_message_mentions_no_business_vars(self):
        """错误信息提示设置正确的环境变量"""
        with pytest.MonkeyPatch.context() as m:
            m.delenv("EVAL_AGENT_MODEL", raising=False)
            m.delenv("EVAL_AGENT_BASE_URL", raising=False)
            m.delenv("EVAL_AGENT_API_KEY", raising=False)
            m.delenv("LLM_MODEL", raising=False)
            m.delenv("LLM_BASE_URL", raising=False)
            m.delenv("LLM_API_KEY", raising=False)
            with pytest.raises(EvalConfigError, match="LLM_MODEL"):
                get_eval_agent_config()


# ── 数据库初始化测试 ──────────────────────────────────────────────────────


class TestEvalDatabaseInit:
    """数据库初始化测试"""

    @pytest.mark.asyncio
    async def test_init_creates_all_tables(self, db, db_path):
        """初始化创建 6 张表"""
        import aiosqlite

        async with aiosqlite.connect(db_path) as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [row[0] for row in await cursor.fetchall()]

        expected_tables = [
            "eval_grader_results",
            "eval_runs",
            "eval_task_candidates",
            "eval_task_defs",
            "eval_trials",
            "quality_metrics",
        ]
        for table in expected_tables:
            assert table in tables, f"表 {table} 未创建"

    @pytest.mark.asyncio
    async def test_idempotent_init(self, db, db_path):
        """重复初始化不会报错"""
        await db.init_db()
        await db.init_db()


# ── EvalTaskDef CRUD 测试 ─────────────────────────────────────────────────


class TestEvalTaskDefCRUD:
    """评估任务定义 CRUD 测试"""

    @pytest.mark.asyncio
    async def test_save_and_get(self, db):
        """保存并获取"""
        task = EvalTaskDef(
            id="crud-001",
            category="command_generation",
            description="测试 CRUD",
            input=EvalTaskInput(intent="ls -la"),
            expected=EvalTaskExpected(
                response_type=["command"],
                steps_contain=["ls -la"],
            ),
            graders=["exact_match"],
            metadata=EvalTaskMetadata(source="yaml", difficulty="easy"),
        )
        await db.save_task_def(task)

        fetched = await db.get_task_def("crud-001")
        assert fetched is not None
        assert fetched.id == "crud-001"
        assert fetched.category.value == "command_generation"
        assert fetched.input.intent == "ls -la"
        assert fetched.expected.steps_contain == ["ls -la"]

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, db):
        """获取不存在的任务"""
        result = await db.get_task_def("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_upsert(self, db):
        """更新已有记录"""
        task = EvalTaskDef(
            id="upsert-001",
            category="safety",
            input=EvalTaskInput(intent="test"),
        )
        await db.save_task_def(task)

        updated = EvalTaskDef(
            id="upsert-001",
            category="safety",
            description="updated",
            input=EvalTaskInput(intent="test updated"),
        )
        await db.save_task_def(updated)

        fetched = await db.get_task_def("upsert-001")
        assert fetched.description == "updated"
        assert fetched.input.intent == "test updated"

    @pytest.mark.asyncio
    async def test_list_all(self, db):
        """列出所有任务"""
        for i in range(5):
            task = EvalTaskDef(
                id=f"list-{i:03d}",
                category="command_generation",
                input=EvalTaskInput(intent=f"cmd-{i}"),
            )
            await db.save_task_def(task)

        tasks = await db.list_task_defs()
        assert len(tasks) == 5

    @pytest.mark.asyncio
    async def test_list_by_category(self, db):
        """按类别筛选"""
        task1 = EvalTaskDef(
            id="cat-001",
            category="safety",
            input=EvalTaskInput(intent="test"),
        )
        task2 = EvalTaskDef(
            id="cat-002",
            category="command_generation",
            input=EvalTaskInput(intent="test"),
        )
        await db.save_task_def(task1)
        await db.save_task_def(task2)

        safety_tasks = await db.list_task_defs(category="safety")
        assert len(safety_tasks) == 1
        assert safety_tasks[0].id == "cat-001"

    @pytest.mark.asyncio
    async def test_list_by_source(self, db):
        """按来源筛选"""
        task1 = EvalTaskDef(
            id="src-001",
            category="safety",
            input=EvalTaskInput(intent="test"),
            metadata=EvalTaskMetadata(source="yaml"),
        )
        task2 = EvalTaskDef(
            id="src-002",
            category="safety",
            input=EvalTaskInput(intent="test"),
            metadata=EvalTaskMetadata(source="candidate"),
        )
        await db.save_task_def(task1)
        await db.save_task_def(task2)

        yaml_tasks = await db.list_task_defs(source="yaml")
        assert len(yaml_tasks) == 1
        assert yaml_tasks[0].id == "src-001"

    @pytest.mark.asyncio
    async def test_delete(self, db):
        """删除任务"""
        task = EvalTaskDef(
            id="del-001",
            category="safety",
            input=EvalTaskInput(intent="test"),
        )
        await db.save_task_def(task)
        assert await db.get_task_def("del-001") is not None

        result = await db.delete_task_def("del-001")
        assert result is True
        assert await db.get_task_def("del-001") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, db):
        """删除不存在的任务"""
        result = await db.delete_task_def("nonexistent")
        assert result is False


# ── EvalTrial CRUD 测试 ──────────────────────────────────────────────────


class TestEvalTrialCRUD:
    """评估试验 CRUD 测试"""

    @pytest.mark.asyncio
    async def test_save_and_get(self, db):
        """保存并获取"""
        trial = EvalTrial(
            trial_id="trial-001",
            task_id="task-001",
            run_id="run-001",
            transcript_json=[{"role": "user", "content": "ls"}],
            agent_result_json={"response": "ls -la"},
            duration_ms=1500,
            token_usage_json={"input": 100, "output": 50},
        )
        await db.save_trial(trial)

        fetched = await db.get_trial("trial-001")
        assert fetched is not None
        assert fetched.task_id == "task-001"
        assert fetched.transcript_json == [{"role": "user", "content": "ls"}]
        assert fetched.agent_result_json == {"response": "ls -la"}
        assert fetched.duration_ms == 1500
        assert fetched.token_usage_json == {"input": 100, "output": 50}

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, db):
        """获取不存在的试验"""
        result = await db.get_trial("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_by_run(self, db):
        """按运行列出试验"""
        for i in range(3):
            trial = EvalTrial(
                trial_id=f"trial-run-{i}",
                task_id=f"task-{i}",
                run_id="run-001",
            )
            await db.save_trial(trial)

        trials = await db.list_trials_by_run("run-001")
        assert len(trials) == 3

    @pytest.mark.asyncio
    async def test_list_by_task(self, db):
        """按任务列出试验"""
        for i in range(2):
            trial = EvalTrial(
                trial_id=f"trial-task-{i}",
                task_id="task-001",
                run_id=f"run-{i}",
            )
            await db.save_trial(trial)

        trials = await db.list_trials_by_task("task-001")
        assert len(trials) == 2


# ── EvalGraderResult CRUD 测试 ────────────────────────────────────────────


class TestEvalGraderResultCRUD:
    """评分结果 CRUD 测试"""

    @pytest.mark.asyncio
    async def test_save_and_get(self, db):
        """保存并获取"""
        result = EvalGraderResult(
            grader_id="grader-001",
            trial_id="trial-001",
            grader_type="exact_match",
            passed=True,
            score=1.0,
            details_json={"match": "exact"},
        )
        await db.save_grader_result(result)

        results = await db.get_grader_results_by_trial("trial-001")
        assert len(results) == 1
        assert results[0].grader_id == "grader-001"
        assert results[0].passed is True
        assert results[0].score == 1.0
        assert results[0].details_json == {"match": "exact"}

    @pytest.mark.asyncio
    async def test_multiple_graders(self, db):
        """同一 trial 多个评分器"""
        for grader_type in ["exact_match", "llm_judge", "safety_check"]:
            result = EvalGraderResult(
                trial_id="trial-002",
                grader_type=grader_type,
                passed=True,
                score=0.9,
            )
            await db.save_grader_result(result)

        results = await db.get_grader_results_by_trial("trial-002")
        assert len(results) == 3


# ── EvalRun CRUD 测试 ────────────────────────────────────────────────────


class TestEvalRunCRUD:
    """评估运行 CRUD 测试"""

    @pytest.mark.asyncio
    async def test_save_and_get(self, db):
        """保存并获取"""
        run = EvalRun(
            run_id="run-001",
            total_tasks=10,
            passed_tasks=8,
            config_json={"model": "gpt-4"},
        )
        await db.save_run(run)

        fetched = await db.get_run("run-001")
        assert fetched is not None
        assert fetched.run_id == "run-001"
        assert fetched.total_tasks == 10
        assert fetched.passed_tasks == 8
        assert fetched.config_json == {"model": "gpt-4"}

    @pytest.mark.asyncio
    async def test_update_completion(self, db):
        """更新完成状态"""
        run = EvalRun(run_id="run-002")
        await db.save_run(run)

        await db.update_run_completion(
            "run-002",
            completed_at="2024-01-01T00:00:00+00:00",
            total_tasks=5,
            passed_tasks=4,
        )

        fetched = await db.get_run("run-002")
        assert fetched.completed_at == "2024-01-01T00:00:00+00:00"
        assert fetched.total_tasks == 5
        assert fetched.passed_tasks == 4

    @pytest.mark.asyncio
    async def test_list_runs(self, db):
        """列出运行"""
        for i in range(3):
            run = EvalRun(run_id=f"run-list-{i}")
            await db.save_run(run)

        runs = await db.list_runs(limit=2)
        assert len(runs) == 2


# ── QualityMetric CRUD 测试 ───────────────────────────────────────────────


class TestQualityMetricCRUD:
    """质量指标 CRUD 测试"""

    @pytest.mark.asyncio
    async def test_save_and_get_by_session(self, db):
        """保存并按 session 获取"""
        metric = QualityMetric(
            metric_id="qm-001",
            session_id="sess-001",
            user_id="user-001",
            device_id="dev-001",
            metric_name="task_success_rate",
            value=0.85,
        )
        await db.save_quality_metric(metric)

        metrics = await db.get_quality_metrics_by_session("sess-001")
        assert len(metrics) == 1
        assert metrics[0].metric_id == "qm-001"
        assert metrics[0].value == 0.85

    @pytest.mark.asyncio
    async def test_get_by_name(self, db):
        """按名称获取"""
        for i in range(3):
            metric = QualityMetric(
                metric_id=f"qm-name-{i}",
                session_id=f"sess-{i}",
                metric_name="response_time_ms",
                value=100.0 + i,
            )
            await db.save_quality_metric(metric)

        metrics = await db.get_quality_metrics_by_name("response_time_ms")
        assert len(metrics) == 3

    @pytest.mark.asyncio
    async def test_empty_session(self, db):
        """空 session 返回空列表"""
        metrics = await db.get_quality_metrics_by_session("nonexistent")
        assert metrics == []


# ── EvalTaskCandidate CRUD 测试 ───────────────────────────────────────────


class TestEvalTaskCandidateCRUD:
    """候选任务 CRUD 测试"""

    @pytest.mark.asyncio
    async def test_save_and_get(self, db):
        """保存并获取"""
        candidate = EvalTaskCandidate(
            candidate_id="cand-001",
            source_feedback_id="fb-001",
            suggested_intent="列出所有文件",
            suggested_category="command_generation",
            suggested_expected_json={"response_type": ["command"]},
        )
        await db.save_task_candidate(candidate)

        fetched = await db.get_task_candidate("cand-001")
        assert fetched is not None
        assert fetched.candidate_id == "cand-001"
        assert fetched.suggested_intent == "列出所有文件"
        assert fetched.status == CandidateStatus.PENDING

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, db):
        """获取不存在的候选"""
        result = await db.get_task_candidate("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_all(self, db):
        """列出所有候选"""
        for i in range(3):
            candidate = EvalTaskCandidate(
                candidate_id=f"cand-list-{i}",
                suggested_intent=f"intent-{i}",
            )
            await db.save_task_candidate(candidate)

        candidates = await db.list_task_candidates()
        assert len(candidates) == 3

    @pytest.mark.asyncio
    async def test_list_by_status(self, db):
        """按状态筛选"""
        for i, status in enumerate(["pending", "approved", "pending"]):
            candidate = EvalTaskCandidate(
                candidate_id=f"cand-status-{i}",
                suggested_intent=f"intent-{i}",
                status=status,
            )
            await db.save_task_candidate(candidate)

        pending = await db.list_task_candidates(status="pending")
        assert len(pending) == 2

    @pytest.mark.asyncio
    async def test_update_status(self, db):
        """更新审核状态"""
        candidate = EvalTaskCandidate(
            candidate_id="cand-upd-001",
            suggested_intent="test intent",
        )
        await db.save_task_candidate(candidate)

        result = await db.update_candidate_status(
            "cand-upd-001",
            CandidateStatus.APPROVED,
            reviewed_by="admin",
        )
        assert result is True

        fetched = await db.get_task_candidate("cand-upd-001")
        assert fetched.status == CandidateStatus.APPROVED
        assert fetched.reviewed_by == "admin"
        assert fetched.reviewed_at is not None

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, db):
        """更新不存在的候选"""
        result = await db.update_candidate_status(
            "nonexistent",
            CandidateStatus.REJECTED,
            reviewed_by="admin",
        )
        assert result is False


class TestSaveQualityMetricsBatchParity:
    """save_quality_metrics_batch 必须与逐条 save_quality_metric 产出相同行。"""

    @pytest.mark.asyncio
    async def test_batch_equals_per_metric(self, db):
        """批量写入与逐条写入的最终 DB 状态完全一致。"""
        metrics = [
            QualityMetric(
                metric_id=f"qm-batch-{i}",
                session_id="sess-batch",
                user_id="user-batch",
                device_id="dev-batch",
                metric_name="batch_parity_check",
                value=0.1 * i,
                terminal_id=f"term-{i}",
            )
            for i in range(5)
        ]

        # 批量写入
        await db.save_quality_metrics_batch(metrics)

        # 逐条写入到不同 session 做对照组
        for m in metrics:
            m2 = QualityMetric(
                metric_id=m.metric_id + "-ctrl",
                session_id="sess-ctrl",
                user_id=m.user_id,
                device_id=m.device_id,
                metric_name=m.metric_name,
                value=m.value,
                terminal_id=m.terminal_id,
            )
            await db.save_quality_metric(m2)

        batch_rows = await db.get_quality_metrics_by_session("sess-batch")
        ctrl_rows = await db.get_quality_metrics_by_session("sess-ctrl")

        assert len(batch_rows) == len(ctrl_rows) == 5
        for b, c in zip(batch_rows, ctrl_rows):
            assert b.value == c.value
            assert b.metric_name == c.metric_name
            assert b.terminal_id == c.terminal_id

    @pytest.mark.asyncio
    async def test_batch_upsert_replaces(self, db):
        """批量写入 INSERT OR REPLACE 覆盖旧值。"""
        m1 = QualityMetric(
            metric_id="qm-upsert-1",
            session_id="sess-upsert",
            metric_name="upsert_test",
            value=0.5,
        )
        await db.save_quality_metric(m1)

        m1_updated = QualityMetric(
            metric_id="qm-upsert-1",
            session_id="sess-upsert",
            metric_name="upsert_test",
            value=0.9,
        )
        await db.save_quality_metrics_batch([m1_updated])

        rows = await db.get_quality_metrics_by_session("sess-upsert")
        assert len(rows) == 1
        assert rows[0].value == 0.9

    @pytest.mark.asyncio
    async def test_batch_empty_noop(self, db):
        """空列表不报错。"""
        await db.save_quality_metrics_batch([])

    @pytest.mark.asyncio
    async def test_batch_three_metrics_all_persisted(self, db):
        """3 条不同 metric 全部落库。"""
        metrics = [
            QualityMetric(
                metric_id=f"qm-multi-{i}",
                session_id="sess-multi",
                metric_name=f"metric_{i}",
                value=float(i),
            )
            for i in range(3)
        ]
        await db.save_quality_metrics_batch(metrics)

        rows = await db.get_quality_metrics_by_session("sess-multi")
        assert len(rows) == 3
        names = {r.metric_name for r in rows}
        assert names == {"metric_0", "metric_1", "metric_2"}
