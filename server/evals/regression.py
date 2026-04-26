"""
B104: 回归检测 + 趋势追踪

与指定 baseline run 对比，输出 regression 列表（之前通过现在失败的 task）。
按时间窗口返回 pass_rate 变化趋势。

关键约束：
- 回归检测只比较 pass_rate，不比较详细 transcript
- trend 数据来自已保存的 eval_runs，不重新执行
- 不依赖外部服务
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from evals.db import EvalDatabase
from evals.harness import EvalHarness
from evals.models import EvalTaskDef

logger = logging.getLogger(__name__)


# ── 回归检测 ──────────────────────────────────────────────────────────────


def _compute_task_pass_rate(
    trials: List[Dict[str, Any]],
) -> float:
    """从 trial 列表计算 pass_rate。

    Args:
        trials: trial 记录列表，每个包含 agent_result_json

    Returns:
        通过率 [0.0, 1.0]
    """
    if not trials:
        return 0.0
    passed = sum(1 for t in trials if _is_trial_passed(t))
    return passed / len(trials)


def _is_trial_passed(trial: Dict[str, Any]) -> bool:
    """判断单个 trial 是否通过。

    通过 trial 的 agent_result_json 来判断：
    - response_type != "error"
    - 非空
    """
    agent_result = trial.get("agent_result_json")
    if agent_result is None:
        return False
    if isinstance(agent_result, str):
        import json
        try:
            agent_result = json.loads(agent_result)
        except (json.JSONDecodeError, TypeError):
            return False
    if not isinstance(agent_result, dict):
        return False
    if agent_result.get("response_type") == "error":
        return False
    return True


def _pass_threshold(pass_rate: float, threshold: float = 0.0) -> bool:
    """判断 pass_rate 是否达到阈值（默认 > 0 即算通过）"""
    return pass_rate > threshold


async def _get_run_task_results(
    db: EvalDatabase, run_id: str
) -> Dict[str, Dict[str, Any]]:
    """获取指定 run 的所有 task 结果。

    通过 list_trials_by_run 获取所有 trials，按 task_id 聚合。

    Returns:
        {task_id: {"pass_rate": float, "trials_count": int, "pass_count": int}}
    """
    trials = await db.list_trials_by_run(run_id)

    # 按 task_id 聚合
    task_trials: Dict[str, List[Dict[str, Any]]] = {}
    for trial in trials:
        task_id = trial.task_id
        if task_id not in task_trials:
            task_trials[task_id] = []
        # 将 EvalTrial 转换为 dict 用于 pass_rate 计算
        task_trials[task_id].append({
            "agent_result_json": trial.agent_result_json,
        })

    results: Dict[str, Dict[str, Any]] = {}
    for task_id, trial_list in task_trials.items():
        pass_count = sum(1 for t in trial_list if _is_trial_passed(t))
        trials_count = len(trial_list)
        pass_rate = pass_count / trials_count if trials_count > 0 else 0.0
        results[task_id] = {
            "pass_rate": pass_rate,
            "trials_count": trials_count,
            "pass_count": pass_count,
        }

    return results


async def detect_regressions(
    db: EvalDatabase,
    baseline_run_id: str,
    current_run_id: str,
) -> Dict[str, Any]:
    """对比两次 eval run，检测回归。

    逻辑：
    - baseline pass 且 current fail 的 task → regression
    - baseline fail 且 current pass 的 task → improvement
    - 其他 → stable

    Args:
        db: 评估数据库
        baseline_run_id: 基线运行 ID
        current_run_id: 当前运行 ID

    Returns:
        {
            "regressions": [{"task_id", "baseline_pass_rate", "current_pass_rate"}],
            "improvements": [{"task_id", "baseline_pass_rate", "current_pass_rate"}],
            "stable": [{"task_id", "baseline_pass_rate", "current_pass_rate"}],
            "baseline_run_id": str,
            "current_run_id": str,
        }
        如果 baseline 或 current run 不存在，返回 error。
    """
    # 加载两个 run
    baseline_run = await db.get_run(baseline_run_id)
    current_run = await db.get_run(current_run_id)

    if baseline_run is None:
        return {
            "error": f"Baseline run not found: {baseline_run_id}",
            "baseline_run_id": baseline_run_id,
            "current_run_id": current_run_id,
            "regressions": [],
            "improvements": [],
            "stable": [],
        }

    if current_run is None:
        return {
            "error": f"Current run not found: {current_run_id}",
            "baseline_run_id": baseline_run_id,
            "current_run_id": current_run_id,
            "regressions": [],
            "improvements": [],
            "stable": [],
        }

    # 获取两次 run 的 task 结果
    baseline_results = await _get_run_task_results(db, baseline_run_id)
    current_results = await _get_run_task_results(db, current_run_id)

    # 收集所有 task_id（两次 run 的并集）
    all_task_ids = set(baseline_results.keys()) | set(current_results.keys())

    regressions: List[Dict[str, Any]] = []
    improvements: List[Dict[str, Any]] = []
    stable: List[Dict[str, Any]] = []

    for task_id in sorted(all_task_ids):
        b = baseline_results.get(task_id, {"pass_rate": 0.0})
        c = current_results.get(task_id, {"pass_rate": 0.0})

        b_pass_rate = b["pass_rate"]
        c_pass_rate = c["pass_rate"]

        entry = {
            "task_id": task_id,
            "baseline_pass_rate": b_pass_rate,
            "current_pass_rate": c_pass_rate,
        }

        b_passed = _pass_threshold(b_pass_rate)
        c_passed = _pass_threshold(c_pass_rate)

        if b_passed and not c_passed:
            regressions.append(entry)
        elif not b_passed and c_passed:
            improvements.append(entry)
        else:
            stable.append(entry)

    return {
        "regressions": regressions,
        "improvements": improvements,
        "stable": stable,
        "baseline_run_id": baseline_run_id,
        "current_run_id": current_run_id,
    }


# ── 趋势追踪 ──────────────────────────────────────────────────────────────


async def query_trend(
    db: EvalDatabase,
    *,
    task_id: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """查询 eval pass_rate 历史趋势。

    从 eval_runs 表按时间查历史运行，计算每次 run 的 pass_rate。
    可选按 task_id 过滤（只看该 task 的通过率趋势）。

    Args:
        db: 评估数据库
        task_id: 可选，按 task 过滤
        limit: 返回记录数量限制

    Returns:
        [{run_id, started_at, pass_rate, total_tasks, passed_tasks}]
        如果指定了 task_id，则 total_tasks 和 passed_tasks 是该 task 的 trial 维度
    """
    if task_id is not None:
        # 使用聚合查询避免 N+1
        return await db.query_task_trend(task_id, limit)

    runs = await db.list_runs(limit=limit)

    trend: List[Dict[str, Any]] = []

    for run in runs:
        # 整体 pass_rate
        total = run.total_tasks
        passed = run.passed_tasks
        pass_rate = passed / total if total > 0 else 0.0

        trend.append({
            "run_id": run.run_id,
            "started_at": run.started_at,
            "pass_rate": pass_rate,
            "total_tasks": total,
            "passed_tasks": passed,
        })

    return trend


# ── 完整回归检查流程 ──────────────────────────────────────────────────────


async def run_regression_check(
    db: EvalDatabase,
    harness: EvalHarness,
    tasks: List[EvalTaskDef],
    baseline_run_id: str,
    n_trials: int = 1,
) -> Dict[str, Any]:
    """运行全部 tasks 并与 baseline 对比。

    流程：
    1. 运行全部 tasks → 保存为 current_run
    2. 调用 detect_regressions 对比 baseline 和 current
    3. 返回结果

    Args:
        db: 评估数据库
        harness: 评估执行器
        tasks: 要运行的 task 列表
        baseline_run_id: 基线运行 ID
        n_trials: 每个 task 的 trial 数

    Returns:
        {
            "current_run_id": str,
            "baseline_run_id": str,
            "regressions": [...],
            "improvements": [...],
            "stable": [...],
            "summary": {"total", "regressions", "improvements"},
        }
    """
    # 运行全部 tasks
    run_result = await harness.run(tasks)

    current_run_id = run_result.get("run_id")
    if current_run_id is None:
        return {
            "error": "Run produced no run_id (possibly empty tasks)",
            "baseline_run_id": baseline_run_id,
            "current_run_id": None,
            "regressions": [],
            "improvements": [],
            "stable": [],
            "summary": {
                "total": 0,
                "regressions": 0,
                "improvements": 0,
            },
        }

    # 检测回归
    comparison = await detect_regressions(db, baseline_run_id, current_run_id)

    regressions = comparison.get("regressions", [])
    improvements = comparison.get("improvements", [])

    summary = {
        "total": run_result.get("total_tasks", 0),
        "regressions": len(regressions),
        "improvements": len(improvements),
    }

    return {
        "current_run_id": current_run_id,
        "baseline_run_id": baseline_run_id,
        "regressions": regressions,
        "improvements": improvements,
        "stable": comparison.get("stable", []),
        "summary": summary,
    }
