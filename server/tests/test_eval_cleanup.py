"""
S051: Eval cleanup 测试

覆盖：
1. IntegrationRunner 信号处理器（SIGINT/SIGTERM → tear_down）
2. cleanup_old_runs 保留最近 N 次 run
3. cleanup_old_runs 清理旧 run 及关联数据
4. cleanup_old_runs 保护活跃 run
"""
from __future__ import annotations

import asyncio
import os
import signal
import tempfile
from datetime import datetime, timezone, timedelta
from typing import List
from unittest.mock import patch, MagicMock

import pytest

from evals.db import EvalDatabase
from evals.models import EvalRun, EvalTrial, EvalGraderResult, QualityMetric


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def eval_db(tmp_path):
    """创建临时 evals.db"""
    db_path = str(tmp_path / "test_evals.db")
    db = EvalDatabase(db_path)
    return db


async def _init_and_seed(eval_db: EvalDatabase):
    """初始化 DB 并插入测试数据。"""
    await eval_db.init_db()


def _make_run(completed_at: str | None, started_at_offset_hours: int = 0) -> EvalRun:
    """创建测试 EvalRun。"""
    started = (datetime.now(timezone.utc) - timedelta(hours=started_at_offset_hours)).isoformat()
    return EvalRun(
        started_at=started,
        completed_at=completed_at,
        total_tasks=2,
        passed_tasks=1,
        config_json={"mode": "unit"},
    )


async def _seed_runs_with_trials(eval_db: EvalDatabase, n_completed: int, n_active: int = 0):
    """插入 n_completed 个已完成 run + n_active 个活跃 run，每个 run 带 trial 和 grader_result。"""
    runs: List[EvalRun] = []
    for i in range(n_completed):
        offset = (n_completed - i) * 10
        completed = (datetime.now(timezone.utc) - timedelta(hours=offset - 1)).isoformat()
        run = _make_run(completed, started_at_offset_hours=offset)
        await eval_db.save_run(run)
        runs.append(run)

        # 添加 trial
        trial = EvalTrial(
            task_id="test_task_1",
            run_id=run.run_id,
            agent_result_json={"response_type": "command"},
        )
        await eval_db.save_trial(trial)

        # 添加 grader_result
        grader = EvalGraderResult(
            trial_id=trial.trial_id,
            grader_type="exact_match",
            passed=True,
            score=1.0,
        )
        await eval_db.save_grader_result(grader)

        # 添加 quality_metric
        metric = QualityMetric(
            session_id=run.run_id,
            metric_name="pass_rate",
            value=1.0,
            source="integration",
        )
        await eval_db.save_quality_metric(metric)

    for i in range(n_active):
        run = _make_run(None, started_at_offset_hours=1)
        await eval_db.save_run(run)
        runs.append(run)

        trial = EvalTrial(
            task_id="test_task_1",
            run_id=run.run_id,
            agent_result_json={"response_type": "command"},
        )
        await eval_db.save_trial(trial)

    return runs


# ── 信号处理器测试 ────────────────────────────────────────────────────


class TestSignalHandler:
    """IntegrationRunner 信号处理器测试。"""

    def test_signal_handler_cleanup_sigint(self):
        """SIGINT 信号触发 tear_down。"""
        from evals.integration import IntegrationRunner

        runner = IntegrationRunner(skip_build=True)
        runner._deployed = False  # 不实际部署

        # 安装信号处理器
        runner.install_signal_handlers()

        # mock tear_down 验证被调用
        with patch.object(runner, "tear_down", wraps=runner.tear_down) as mock_td:
            # 模拟 SIGINT 处理器被直接调用
            handler = signal.getsignal(signal.SIGINT)
            with pytest.raises(KeyboardInterrupt):
                handler(signal.SIGINT, None)
            mock_td.assert_called_once()

        # 恢复信号处理器
        runner.restore_signal_handlers()

    def test_signal_handler_cleanup_sigterm(self):
        """SIGTERM 信号触发 tear_down。"""
        from evals.integration import IntegrationRunner

        runner = IntegrationRunner(skip_build=True)
        runner._deployed = False

        runner.install_signal_handlers()

        with patch.object(runner, "tear_down", wraps=runner.tear_down) as mock_td:
            handler = signal.getsignal(signal.SIGTERM)
            with pytest.raises(KeyboardInterrupt):
                handler(signal.SIGTERM, None)
            mock_td.assert_called_once()

        runner.restore_signal_handlers()

    def test_signal_handler_restore(self):
        """restore_signal_handlers 恢复原始处理器。"""
        from evals.integration import IntegrationRunner

        runner = IntegrationRunner(skip_build=True)
        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)

        runner.install_signal_handlers()

        # 安装后处理器应该不同
        assert signal.getsignal(signal.SIGINT) is not original_sigint
        assert signal.getsignal(signal.SIGTERM) is not original_sigterm

        runner.restore_signal_handlers()

        # 恢复后应该一致
        assert signal.getsignal(signal.SIGINT) is original_sigint
        assert signal.getsignal(signal.SIGTERM) is original_sigterm


# ── cleanup 测试 ──────────────────────────────────────────────────────


class TestEvalCleanup:
    """cleanup_old_runs 测试。"""

    @pytest.mark.asyncio
    async def test_evals_cleanup_keeps_recent(self, eval_db):
        """保留最近 N 次 run。"""
        await _init_and_seed(eval_db)
        runs = await _seed_runs_with_trials(eval_db, n_completed=15, n_active=0)

        result = await eval_db.cleanup_old_runs(keep_last=10)

        assert result["runs_deleted"] == 5
        # 验证剩余 10 个
        remaining = await eval_db.list_runs(limit=100)
        completed = [r for r in remaining if r.completed_at is not None]
        assert len(completed) == 10

    @pytest.mark.asyncio
    async def test_evals_cleanup_removes_old(self, eval_db):
        """清理旧 run 及关联数据（trials, grader_results, quality_metrics）。"""
        await _init_and_seed(eval_db)
        runs = await _seed_runs_with_trials(eval_db, n_completed=5, n_active=0)

        result = await eval_db.cleanup_old_runs(keep_last=2)

        assert result["runs_deleted"] == 3
        assert result["trials_deleted"] == 3
        assert result["grader_results_deleted"] == 3
        assert result["quality_metrics_deleted"] == 3

    @pytest.mark.asyncio
    async def test_evals_cleanup_active_run_protected(self, eval_db):
        """活跃 run（completed_at 为空）不被清理。"""
        await _init_and_seed(eval_db)
        runs = await _seed_runs_with_trials(eval_db, n_completed=3, n_active=2)

        # 保留最近 1 个已完成 run，活跃 run 应该完全不受影响
        result = await eval_db.cleanup_old_runs(keep_last=1)

        assert result["runs_deleted"] == 2  # 只删除 2 个已完成的旧 run

        # 验证活跃 run 仍然存在
        all_runs = await eval_db.list_runs(limit=100)
        active_runs = [r for r in all_runs if r.completed_at is None]
        assert len(active_runs) == 2

    @pytest.mark.asyncio
    async def test_evals_cleanup_nothing_to_delete(self, eval_db):
        """keep_last 大于已有 run 数量时，不做删除。"""
        await _init_and_seed(eval_db)
        await _seed_runs_with_trials(eval_db, n_completed=3, n_active=0)

        result = await eval_db.cleanup_old_runs(keep_last=10)

        assert result["runs_deleted"] == 0
        assert result["trials_deleted"] == 0

    @pytest.mark.asyncio
    async def test_evals_cleanup_empty_db(self, eval_db):
        """空数据库 cleanup 不报错。"""
        await _init_and_seed(eval_db)

        result = await eval_db.cleanup_old_runs(keep_last=5)

        assert result["runs_deleted"] == 0


# ── CLI cleanup 子命令测试 ────────────────────────────────────────────


class TestCleanupCLI:
    """cleanup CLI 子命令测试。"""

    @pytest.mark.asyncio
    async def test_cleanup_cli(self, tmp_path):
        """cleanup 子命令正常执行。"""
        db_path = str(tmp_path / "cli_test_evals.db")
        db = EvalDatabase(db_path)
        await _init_and_seed(db)
        await _seed_runs_with_trials(db, n_completed=5, n_active=0)

        # 模拟 CLI 调用
        from evals.__main__ import _cmd_cleanup
        import argparse

        args = argparse.Namespace(keep_last=3, db=db_path)
        exit_code = await _cmd_cleanup(args)

        assert exit_code == 0

        # 验证数据被清理
        remaining = await db.list_runs(limit=100)
        assert len(remaining) == 3
