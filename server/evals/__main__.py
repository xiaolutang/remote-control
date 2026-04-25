"""
B104: Eval CLI 入口

用法：
    python -m evals run --tasks server/evals/tasks --trials 1
    python -m evals regression --baseline <run_id> --tasks server/evals/tasks --trials 1
    python -m evals trend [--task-id <id>] [--limit 20]

子命令：
    run        运行所有 tasks，保存结果到 evals.db
    regression 运行 + 与 baseline 对比
    trend      查询历史 pass_rate 趋势

配置缺失时（EVAL_AGENT_MODEL 等），CLI 报错退出并提示需要设置的环境变量。
输出 JSON + 人类可读 summary。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from typing import List

from evals.db import EvalConfigError, EvalDatabase, get_eval_agent_config
from evals.harness import EvalHarness, load_yaml_tasks
from evals.regression import detect_regressions, query_trend, run_regression_check

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器"""
    parser = argparse.ArgumentParser(
        prog="evals",
        description="Eval Framework CLI - 评估运行、回归检测、趋势追踪",
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # ── run 子命令 ─────────────────────────────────────────────────────
    run_parser = subparsers.add_parser("run", help="运行所有 tasks，保存结果")
    run_parser.add_argument(
        "--tasks",
        required=True,
        help="YAML task 目录路径",
    )
    run_parser.add_argument(
        "--trials",
        type=int,
        default=1,
        help="每个 task 的 trial 数（默认 1）",
    )
    run_parser.add_argument(
        "--db",
        default="evals.db",
        help="evals.db 路径（默认 evals.db）",
    )

    # ── regression 子命令 ──────────────────────────────────────────────
    reg_parser = subparsers.add_parser(
        "regression", help="运行 tasks 并与 baseline 对比"
    )
    reg_parser.add_argument(
        "--baseline",
        required=True,
        help="Baseline run ID",
    )
    reg_parser.add_argument(
        "--tasks",
        required=True,
        help="YAML task 目录路径",
    )
    reg_parser.add_argument(
        "--trials",
        type=int,
        default=1,
        help="每个 task 的 trial 数（默认 1）",
    )
    reg_parser.add_argument(
        "--db",
        default="evals.db",
        help="evals.db 路径（默认 evals.db）",
    )

    # ── trend 子命令 ──────────────────────────────────────────────────
    trend_parser = subparsers.add_parser("trend", help="查询历史 pass_rate 趋势")
    trend_parser.add_argument(
        "--task-id",
        default=None,
        help="按 task_id 过滤趋势",
    )
    trend_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="返回记录数量（默认 20）",
    )
    trend_parser.add_argument(
        "--db",
        default="evals.db",
        help="evals.db 路径（默认 evals.db）",
    )

    return parser


def _check_config() -> None:
    """检查评估配置，缺失时打印错误并退出。

    Raises EvalConfigError 时 exit(1)。
    """
    try:
        get_eval_agent_config()
    except EvalConfigError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print(
            "请设置以下环境变量：\n"
            "  EVAL_AGENT_MODEL     - 模型名称\n"
            "  EVAL_AGENT_BASE_URL  - API 地址\n"
            "  EVAL_AGENT_API_KEY   - API 密钥",
            file=sys.stderr,
        )
        sys.exit(1)


def _print_summary(result: dict) -> None:
    """打印人类可读的 summary"""
    if "run_id" in result and result["run_id"]:
        run_id = result["run_id"]
        total = result.get("total_tasks", 0)
        passed = result.get("passed_tasks", 0)
        rate = passed / total if total > 0 else 0.0
        print(f"\n--- Run Summary ---")
        print(f"Run ID:      {run_id}")
        print(f"Tasks:       {passed}/{total} passed ({rate:.0%})")

    if "regressions" in result:
        regressions = result["regressions"]
        improvements = result.get("improvements", [])
        print(f"\n--- Regression Check ---")
        print(f"Regressions:  {len(regressions)}")
        if regressions:
            for r in regressions:
                print(
                    f"  - {r['task_id']}: "
                    f"{r['baseline_pass_rate']:.0%} -> {r['current_pass_rate']:.0%}"
                )
        print(f"Improvements: {len(improvements)}")
        if improvements:
            for i in improvements:
                print(
                    f"  + {i['task_id']}: "
                    f"{i['baseline_pass_rate']:.0%} -> {i['current_pass_rate']:.0%}"
                )


def _print_trend_summary(trend: List[dict]) -> None:
    """打印趋势 summary"""
    if not trend:
        print("No eval runs found.")
        return

    print(f"\n--- Pass Rate Trend ({len(trend)} runs) ---")
    print(f"{'Run ID (short)':<16} {'Started':<26} {'Pass Rate':<12} {'Passed/Total'}")
    print("-" * 70)
    for entry in trend:
        run_short = entry["run_id"][:12]
        started = entry["started_at"][:19]
        rate = entry["pass_rate"]
        total = entry["total_tasks"]
        passed = entry["passed_tasks"]
        print(f"{run_short:<16} {started:<26} {rate:>8.0%}     {passed}/{total}")


async def _cmd_run(args: argparse.Namespace) -> int:
    """执行 run 子命令"""
    _check_config()

    # 加载 tasks
    tasks = load_yaml_tasks(args.tasks)
    if not tasks:
        print("WARNING: No tasks loaded from", args.tasks)
        return 1

    print(f"Loaded {len(tasks)} tasks from {args.tasks}")

    # 初始化 DB
    db = EvalDatabase(args.db)
    await db.init_db()

    # 创建 harness 并运行
    config = get_eval_agent_config()
    harness = EvalHarness(db, config=config, num_trials=args.trials)
    result = await harness.run(tasks)

    # 输出
    _print_summary(result)
    print(f"\nJSON output:")
    print(json.dumps(result, indent=2, default=str))

    return 0


async def _cmd_regression(args: argparse.Namespace) -> int:
    """执行 regression 子命令"""
    _check_config()

    # 加载 tasks
    tasks = load_yaml_tasks(args.tasks)
    if not tasks:
        print("WARNING: No tasks loaded from", args.tasks)
        return 1

    print(f"Loaded {len(tasks)} tasks from {args.tasks}")
    print(f"Baseline run: {args.baseline}")

    # 初始化 DB
    db = EvalDatabase(args.db)
    await db.init_db()

    # 创建 harness 并运行回归检查
    config = get_eval_agent_config()
    harness = EvalHarness(db, config=config, num_trials=args.trials)
    result = await run_regression_check(
        db, harness, tasks, args.baseline, n_trials=args.trials
    )

    # 输出
    _print_summary(result)
    print(f"\nJSON output:")
    print(json.dumps(result, indent=2, default=str))

    # 有回归时返回非零
    if result.get("regressions"):
        return 1
    return 0


async def _cmd_trend(args: argparse.Namespace) -> int:
    """执行 trend 子命令"""
    # trend 不需要 LLM 配置，只查询数据库

    # 初始化 DB
    db = EvalDatabase(args.db)
    await db.init_db()

    # 查询趋势
    trend = await query_trend(
        db, task_id=args.task_id, limit=args.limit
    )

    # 输出
    _print_trend_summary(trend)
    print(f"\nJSON output:")
    print(json.dumps(trend, indent=2, default=str))

    return 0


async def async_main(argv: List[str] | None = None) -> int:
    """异步主入口"""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    # 配置日志
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.command == "run":
        return await _cmd_run(args)
    elif args.command == "regression":
        return await _cmd_regression(args)
    elif args.command == "trend":
        return await _cmd_trend(args)
    else:
        parser.print_help()
        return 1


def main() -> None:
    """同步 CLI 入口"""
    sys.exit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()
