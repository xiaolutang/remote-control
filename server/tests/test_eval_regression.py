"""
B104: 回归检测 + 趋势追踪 + CLI 入口 测试

测试场景：
1. detect_regressions 正确识别回归（baseline pass -> current fail）
2. detect_regressions 识别改进（baseline fail -> current pass）
3. detect_regressions 识别稳定（都 pass / 都 fail）
4. detect_regressions 缺少 baseline/current run 时返回错误
5. query_trend 返回历史趋势
6. query_trend 按 task_id 过滤
7. run_regression_check 完整流程（mock harness）
8. CLI 入口测试（直接调用 async_main）
"""
import json
import pytest
import pytest_asyncio

from evals.db import EvalDatabase
from evals.models import (
    EvalRun,
    EvalTrial,
)
from evals.regression import (
    detect_regressions,
    query_trend,
    run_regression_check,
    _is_trial_passed,
    _compute_task_pass_rate,
)
from evals.harness import EvalHarness


# ── Fixtures ──────────────────────────────────────────────────────────────


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


async def _create_run_with_trials(
    db: EvalDatabase,
    task_results: dict,
) -> str:
    """辅助：创建一个 run 并添加 trials。

    Args:
        db: 数据库
        task_results: {task_id: [pass_count, total_count]}
            pass_count 个 trial 通过，(total - pass_count) 个失败

    Returns:
        run_id
    """
    run = EvalRun(
        total_tasks=len(task_results),
        passed_tasks=sum(
            1 for passes, total in task_results.values() if passes > 0
        ),
    )
    await db.save_run(run)

    for task_id, (pass_count, total_count) in task_results.items():
        for i in range(total_count):
            if i < pass_count:
                agent_result = {"response_type": "command", "summary": "ok"}
            else:
                agent_result = {"response_type": "error", "summary": "fail"}

            trial = EvalTrial(
                task_id=task_id,
                run_id=run.run_id,
                agent_result_json=agent_result,
            )
            await db.save_trial(trial)

    # 更新 run 完成状态
    from datetime import datetime, timezone
    completed_at = datetime.now(timezone.utc).isoformat()
    total = len(task_results)
    passed = sum(
        1 for passes, total_count in task_results.values() if passes > 0
    )
    await db.update_run_completion(run.run_id, completed_at, total, passed)

    return run.run_id


# ── 辅助函数测试 ──────────────────────────────────────────────────────────


class TestHelpers:
    """辅助函数测试"""

    def test_is_trial_passed_normal(self):
        """正常通过的 trial"""
        assert _is_trial_passed({"agent_result_json": {"response_type": "command", "summary": "ok"}})

    def test_is_trial_passed_error(self):
        """error 类型 trial 不通过"""
        assert not _is_trial_passed({"agent_result_json": {"response_type": "error", "summary": "fail"}})

    def test_is_trial_passed_none(self):
        """agent_result_json 为 None 不通过"""
        assert not _is_trial_passed({"agent_result_json": None})

    def test_is_trial_passed_string_json(self):
        """agent_result_json 为 JSON 字符串"""
        assert _is_trial_passed({
            "agent_result_json": json.dumps({"response_type": "command", "summary": "ok"})
        })

    def test_is_trial_passed_invalid_string(self):
        """agent_result_json 为无效字符串"""
        assert not _is_trial_passed({"agent_result_json": "not-json"})

    def test_compute_task_pass_rate(self):
        """计算 pass_rate"""
        trials = [
            {"agent_result_json": {"response_type": "command"}},
            {"agent_result_json": {"response_type": "command"}},
            {"agent_result_json": {"response_type": "error"}},
        ]
        rate = _compute_task_pass_rate(trials)
        assert abs(rate - 2 / 3) < 0.01

    def test_compute_task_pass_rate_empty(self):
        """空 trial 列表 pass_rate 为 0"""
        assert _compute_task_pass_rate([]) == 0.0


# ── 回归检测测试 ──────────────────────────────────────────────────────────


class TestDetectRegressions:
    """回归检测测试"""

    @pytest.mark.asyncio
    async def test_regression_detected(self, db):
        """baseline pass -> current fail = regression"""
        baseline_id = await _create_run_with_trials(db, {
            "task_a": (2, 2),  # 全部通过
            "task_b": (1, 1),  # 全部通过
        })
        current_id = await _create_run_with_trials(db, {
            "task_a": (0, 2),  # 全部失败 -> regression!
            "task_b": (1, 1),  # 仍然通过 -> stable
        })

        result = await detect_regressions(db, baseline_id, current_id)

        assert len(result["regressions"]) == 1
        assert result["regressions"][0]["task_id"] == "task_a"
        assert result["regressions"][0]["baseline_pass_rate"] == 1.0
        assert result["regressions"][0]["current_pass_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_improvement_detected(self, db):
        """baseline fail -> current pass = improvement"""
        baseline_id = await _create_run_with_trials(db, {
            "task_a": (0, 2),  # 全部失败
            "task_b": (1, 1),  # 通过
        })
        current_id = await _create_run_with_trials(db, {
            "task_a": (2, 2),  # 全部通过 -> improvement!
            "task_b": (1, 1),  # 仍然通过 -> stable
        })

        result = await detect_regressions(db, baseline_id, current_id)

        assert len(result["improvements"]) == 1
        assert result["improvements"][0]["task_id"] == "task_a"
        assert result["improvements"][0]["baseline_pass_rate"] == 0.0
        assert result["improvements"][0]["current_pass_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_stable_both_pass(self, db):
        """都 pass -> stable"""
        baseline_id = await _create_run_with_trials(db, {
            "task_a": (1, 1),
            "task_b": (1, 1),
        })
        current_id = await _create_run_with_trials(db, {
            "task_a": (1, 1),
            "task_b": (1, 1),
        })

        result = await detect_regressions(db, baseline_id, current_id)

        assert len(result["regressions"]) == 0
        assert len(result["improvements"]) == 0
        assert len(result["stable"]) == 2

    @pytest.mark.asyncio
    async def test_stable_both_fail(self, db):
        """都 fail -> stable"""
        baseline_id = await _create_run_with_trials(db, {
            "task_a": (0, 1),
        })
        current_id = await _create_run_with_trials(db, {
            "task_a": (0, 1),
        })

        result = await detect_regressions(db, baseline_id, current_id)

        assert len(result["regressions"]) == 0
        assert len(result["improvements"]) == 0
        assert len(result["stable"]) == 1

    @pytest.mark.asyncio
    async def test_missing_baseline_run(self, db):
        """baseline run 不存在时返回错误"""
        fake_run_id = "nonexistent123456"
        current_id = await _create_run_with_trials(db, {
            "task_a": (1, 1),
        })

        result = await detect_regressions(db, fake_run_id, current_id)

        assert "error" in result
        assert "not found" in result["error"].lower()
        assert result["regressions"] == []

    @pytest.mark.asyncio
    async def test_missing_current_run(self, db):
        """current run 不存在时返回错误"""
        baseline_id = await _create_run_with_trials(db, {
            "task_a": (1, 1),
        })
        fake_run_id = "nonexistent123456"

        result = await detect_regressions(db, baseline_id, fake_run_id)

        assert "error" in result
        assert "not found" in result["error"].lower()
        assert result["regressions"] == []

    @pytest.mark.asyncio
    async def test_mixed_results(self, db):
        """混合场景：有回归、改进、稳定"""
        baseline_id = await _create_run_with_trials(db, {
            "task_pass_to_fail": (1, 1),   # pass -> regression
            "task_fail_to_pass": (0, 1),   # fail -> improvement
            "task_stable_pass": (1, 1),    # pass -> stable
            "task_stable_fail": (0, 1),    # fail -> stable
        })
        current_id = await _create_run_with_trials(db, {
            "task_pass_to_fail": (0, 1),   # fail
            "task_fail_to_pass": (1, 1),   # pass
            "task_stable_pass": (1, 1),    # pass
            "task_stable_fail": (0, 1),    # fail
        })

        result = await detect_regressions(db, baseline_id, current_id)

        assert len(result["regressions"]) == 1
        assert result["regressions"][0]["task_id"] == "task_pass_to_fail"
        assert len(result["improvements"]) == 1
        assert result["improvements"][0]["task_id"] == "task_fail_to_pass"
        assert len(result["stable"]) == 2

    @pytest.mark.asyncio
    async def test_task_only_in_baseline(self, db):
        """task 只在 baseline 中出现，current 中没有"""
        baseline_id = await _create_run_with_trials(db, {
            "task_a": (1, 1),
        })
        current_id = await _create_run_with_trials(db, {
            "task_b": (1, 1),
        })

        result = await detect_regressions(db, baseline_id, current_id)

        # task_a: baseline pass, current 不存在(pass_rate=0.0) -> regression
        assert len(result["regressions"]) == 1
        assert result["regressions"][0]["task_id"] == "task_a"

    @pytest.mark.asyncio
    async def test_task_only_in_current(self, db):
        """task 只在 current 中出现，baseline 中没有"""
        baseline_id = await _create_run_with_trials(db, {
            "task_a": (1, 1),
        })
        current_id = await _create_run_with_trials(db, {
            "task_a": (1, 1),
            "task_b": (1, 1),
        })

        result = await detect_regressions(db, baseline_id, current_id)

        # task_b: baseline 不存在(pass_rate=0.0), current pass -> improvement
        assert len(result["improvements"]) == 1
        assert result["improvements"][0]["task_id"] == "task_b"


# ── 趋势追踪测试 ──────────────────────────────────────────────────────────


class TestQueryTrend:
    """趋势查询测试"""

    @pytest.mark.asyncio
    async def test_trend_returns_history(self, db):
        """查询历史趋势"""
        # 创建 3 个 run
        await _create_run_with_trials(db, {"task_a": (1, 1)})
        await _create_run_with_trials(db, {"task_a": (0, 1)})
        await _create_run_with_trials(db, {"task_a": (1, 1)})

        trend = await query_trend(db, limit=10)

        assert len(trend) == 3
        # 最新排最前
        assert trend[0]["pass_rate"] == 1.0
        assert trend[1]["pass_rate"] == 0.0
        assert trend[2]["pass_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_trend_with_task_id_filter(self, db):
        """按 task_id 过滤趋势"""
        await _create_run_with_trials(db, {
            "task_a": (1, 1),
            "task_b": (0, 1),
        })
        await _create_run_with_trials(db, {
            "task_a": (0, 1),
            "task_b": (1, 1),
        })

        trend = await query_trend(db, task_id="task_a", limit=10)

        assert len(trend) == 2
        assert trend[0]["pass_rate"] == 0.0  # 最新 run task_a 失败
        assert trend[1]["pass_rate"] == 1.0  # 之前 run task_a 通过

    @pytest.mark.asyncio
    async def test_trend_task_not_found(self, db):
        """task_id 过滤时无匹配结果"""
        await _create_run_with_trials(db, {"task_a": (1, 1)})

        trend = await query_trend(db, task_id="nonexistent", limit=10)

        assert len(trend) == 0

    @pytest.mark.asyncio
    async def test_trend_empty_db(self, db):
        """空数据库返回空列表"""
        trend = await query_trend(db, limit=10)

        assert trend == []

    @pytest.mark.asyncio
    async def test_trend_limit(self, db):
        """limit 限制返回数量"""
        for i in range(5):
            await _create_run_with_trials(db, {"task_a": (1, 1)})

        trend = await query_trend(db, limit=3)

        assert len(trend) == 3

    @pytest.mark.asyncio
    async def test_trend_overall_pass_rate(self, db):
        """整体 pass_rate 计算"""
        await _create_run_with_trials(db, {
            "task_a": (1, 1),
            "task_b": (0, 1),
        })

        trend = await query_trend(db, limit=1)

        assert len(trend) == 1
        # 2 tasks, 1 passed (task_a)
        assert trend[0]["total_tasks"] == 2
        assert trend[0]["passed_tasks"] == 1
        assert abs(trend[0]["pass_rate"] - 0.5) < 0.01


# ── run_regression_check 完整流程测试 ──────────────────────────────────────


class TestRunRegressionCheck:
    """完整回归检查流程测试（mock harness）"""

    @pytest.mark.asyncio
    async def test_full_regression_check(self, db):
        """完整回归检查流程"""
        # 先创建一个 baseline run
        baseline_id = await _create_run_with_trials(db, {
            "task_a": (1, 1),
            "task_b": (1, 1),
        })

        # Mock harness：运行 task_a 失败、task_b 通过
        class MockHarness:
            def __init__(self, db):
                self.db = db

            async def run(self, tasks):
                from evals.models import EvalRun
                from datetime import datetime, timezone
                run = EvalRun(total_tasks=len(tasks), passed_tasks=1)
                await self.db.save_run(run)

                # task_a 失败
                trial_a = EvalTrial(
                    task_id="task_a",
                    run_id=run.run_id,
                    agent_result_json={"response_type": "error", "summary": "fail"},
                )
                await self.db.save_trial(trial_a)

                # task_b 通过
                trial_b = EvalTrial(
                    task_id="task_b",
                    run_id=run.run_id,
                    agent_result_json={"response_type": "command", "summary": "ok"},
                )
                await self.db.save_trial(trial_b)

                completed_at = datetime.now(timezone.utc).isoformat()
                await self.db.update_run_completion(
                    run.run_id, completed_at, 2, 1
                )

                return {
                    "run_id": run.run_id,
                    "total_tasks": 2,
                    "passed_tasks": 1,
                }

        mock_harness = MockHarness(db)
        from evals.models import EvalTaskDef, EvalTaskInput

        tasks = [
            EvalTaskDef(
                id="task_a",
                category="command_generation",
                input=EvalTaskInput(intent="test a"),
            ),
            EvalTaskDef(
                id="task_b",
                category="command_generation",
                input=EvalTaskInput(intent="test b"),
            ),
        ]

        result = await run_regression_check(
            db, mock_harness, tasks, baseline_id, n_trials=1
        )

        assert result["current_run_id"] is not None
        assert result["baseline_run_id"] == baseline_id
        assert len(result["regressions"]) == 1
        assert result["regressions"][0]["task_id"] == "task_a"
        assert result["summary"]["regressions"] == 1
        assert result["summary"]["total"] == 2

    @pytest.mark.asyncio
    async def test_regression_check_no_regressions(self, db):
        """无回归时的结果"""
        baseline_id = await _create_run_with_trials(db, {
            "task_a": (1, 1),
        })

        class MockHarnessAllPass:
            def __init__(self, db):
                self.db = db

            async def run(self, tasks):
                from evals.models import EvalRun
                from datetime import datetime, timezone
                run = EvalRun(total_tasks=len(tasks), passed_tasks=len(tasks))
                await self.db.save_run(run)

                for task in tasks:
                    trial = EvalTrial(
                        task_id=task.id,
                        run_id=run.run_id,
                        agent_result_json={"response_type": "command", "summary": "ok"},
                    )
                    await self.db.save_trial(trial)

                completed_at = datetime.now(timezone.utc).isoformat()
                await self.db.update_run_completion(
                    run.run_id, completed_at, len(tasks), len(tasks)
                )

                return {
                    "run_id": run.run_id,
                    "total_tasks": len(tasks),
                    "passed_tasks": len(tasks),
                }

        mock_harness = MockHarnessAllPass(db)
        from evals.models import EvalTaskDef, EvalTaskInput

        tasks = [
            EvalTaskDef(
                id="task_a",
                category="command_generation",
                input=EvalTaskInput(intent="test a"),
            ),
        ]

        result = await run_regression_check(
            db, mock_harness, tasks, baseline_id, n_trials=1
        )

        assert len(result["regressions"]) == 0
        assert result["summary"]["regressions"] == 0


# ── CLI 入口测试 ──────────────────────────────────────────────────────────


class TestCLI:
    """CLI 入口测试"""

    @pytest.mark.asyncio
    async def test_cli_no_command(self):
        """无子命令时返回 1"""
        from evals.__main__ import async_main
        exit_code = await async_main([])
        assert exit_code == 1

    @pytest.mark.asyncio
    async def test_cli_trend_empty_db(self, tmp_path):
        """trend 子命令在空数据库上运行"""
        from evals.__main__ import async_main
        db_path = str(tmp_path / "test_evals.db")
        exit_code = await async_main(["trend", "--db", db_path])
        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_cli_trend_with_data(self, tmp_path):
        """trend 子命令有数据时运行"""
        db_path = str(tmp_path / "test_evals.db")
        db = EvalDatabase(db_path)
        await db.init_db()

        await _create_run_with_trials(db, {
            "task_a": (1, 1),
        })

        from evals.__main__ import async_main
        exit_code = await async_main(["trend", "--db", db_path])
        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_cli_trend_with_task_id(self, tmp_path):
        """trend 子命令按 task_id 过滤"""
        db_path = str(tmp_path / "test_evals.db")
        db = EvalDatabase(db_path)
        await db.init_db()

        await _create_run_with_trials(db, {
            "task_a": (1, 1),
            "task_b": (0, 1),
        })

        from evals.__main__ import async_main
        exit_code = await async_main(["trend", "--db", db_path, "--task-id", "task_a"])
        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_cli_run_missing_config(self, tmp_path, monkeypatch):
        """run 子命令配置缺失时 exit(1)"""
        # 清除所有 EVAL_AGENT_* 环境变量
        monkeypatch.delenv("EVAL_AGENT_MODEL", raising=False)
        monkeypatch.delenv("EVAL_AGENT_BASE_URL", raising=False)
        monkeypatch.delenv("EVAL_AGENT_API_KEY", raising=False)

        from evals.__main__ import async_main

        with pytest.raises(SystemExit) as exc_info:
            await async_main([
                "run",
                "--tasks", "server/evals/tasks/intent_classification",
                "--db", str(tmp_path / "test_evals.db"),
            ])
        assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_cli_regression_missing_config(self, tmp_path, monkeypatch):
        """regression 子命令配置缺失时 exit(1)"""
        monkeypatch.delenv("EVAL_AGENT_MODEL", raising=False)
        monkeypatch.delenv("EVAL_AGENT_BASE_URL", raising=False)
        monkeypatch.delenv("EVAL_AGENT_API_KEY", raising=False)

        from evals.__main__ import async_main

        with pytest.raises(SystemExit) as exc_info:
            await async_main([
                "regression",
                "--baseline", "fake_id",
                "--tasks", "server/evals/tasks/intent_classification",
                "--db", str(tmp_path / "test_evals.db"),
            ])
        assert exc_info.value.code == 1
