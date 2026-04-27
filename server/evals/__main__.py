"""
B104: Eval CLI 入口

用法：
    python -m evals run --mode unit --tasks server/evals/tasks --trials 1
    python -m evals run --mode integration --tasks server/evals/tasks --trials 1
    python -m evals regression --baseline <run_id> --tasks server/evals/tasks --trials 1
    python -m evals trend [--task-id <id>] [--limit 20]

子命令：
    run        运行所有 tasks，保存结果到 evals.db
    regression 运行 + 与 baseline 对比
    trend      查询历史 pass_rate 趋势

模式：
    unit        直接调 LLM（默认），快速迭代
    integration Docker 构建 + 真实 HTTP API 调用，完整链路测试

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

    # ── 共享参数（run + regression）────────────────────────────────────
    _shared_mode_args = {
        "dest": "mode",
        "default": "unit",
        "choices": ["unit", "integration"],
        "help": "运行模式: unit=直接调 LLM（默认）, integration=Docker+真实 HTTP API",
    }

    _shared_integration_args = [
        (("--base-url",), {
            "default": "http://localhost:8880",
            "help": "integration 模式服务地址（默认 http://localhost:8880）",
        }),
        (("--skip-build",), {
            "action": "store_true",
            "default": False,
            "help": "跳过 Docker 构建，使用已有镜像",
        }),
        (("--health-timeout",), {
            "type": int,
            "default": 90,
            "help": "integration 模式健康检查超时秒数（默认 90）",
        }),
    ]

    # ── run 子命令 ─────────────────────────────────────────────────────
    run_parser = subparsers.add_parser("run", help="运行所有 tasks，保存结果")
    run_parser.add_argument("--tasks", required=True, help="YAML task 目录路径")
    run_parser.add_argument(
        "--mode", **_shared_mode_args,
    )
    run_parser.add_argument(
        "--trials",
        type=int,
        default=1,
        help="每个 task 的 trial 数（默认 1）",
    )
    run_parser.add_argument(
        "--db",
        default="/data/evals.db",
        help="evals.db 路径（默认 evals.db）",
    )
    for arg_names, kwargs in _shared_integration_args:
        run_parser.add_argument(*arg_names, **kwargs)

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
        "--mode", **_shared_mode_args,
    )
    reg_parser.add_argument(
        "--trials",
        type=int,
        default=1,
        help="每个 task 的 trial 数（默认 1）",
    )
    reg_parser.add_argument(
        "--db",
        default="/data/evals.db",
        help="evals.db 路径（默认 evals.db）",
    )
    for arg_names, kwargs in _shared_integration_args:
        reg_parser.add_argument(*arg_names, **kwargs)

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
        default="/data/evals.db",
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
    mode = getattr(args, "mode", "unit")

    if mode == "integration":
        return await _cmd_run_integration(args)

    # ── unit 模式（原有逻辑不变） ──────────────────────────────────────
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


async def _cmd_run_integration(args: argparse.Namespace) -> int:
    """执行 run 子命令的 integration 模式。

    流程：
    1. Docker 构建 + 部署
    2. 等待服务就绪
    3. 通过真实 HTTP API 执行 eval task
    4. Tear down
    """
    from evals.integration import (
        IntegrationRunner,
        IntegrationEvalClient,
        run_integration_task,
        DockerBuildError,
        HealthCheckTimeout,
    )
    from evals.harness import EvalHarness
    from evals.models import EvalTrial, EvalRun

    # 加载 tasks
    tasks = load_yaml_tasks(args.tasks)
    if not tasks:
        print("WARNING: No tasks loaded from", args.tasks)
        return 1

    print(f"[integration] Loaded {len(tasks)} tasks from {args.tasks}")

    # 初始化 DB
    db = EvalDatabase(args.db)
    await db.init_db()

    # 创建 eval client
    base_url = getattr(args, "base_url", "http://localhost:8880")
    skip_build = getattr(args, "skip_build", False)
    health_timeout = getattr(args, "health_timeout", 90)

    eval_client = IntegrationEvalClient(base_url=base_url)

    # 创建 IntegrationRunner（上下文管理器保证 tear down）
    runner = IntegrationRunner(
        base_url=base_url,
        health_timeout=health_timeout,
        skip_build=skip_build,
    )

    try:
        # 1. 构建 + 部署
        print("[integration] 开始 Docker 构建和部署 ...")
        runner.build_and_deploy()

        # 2. 等待服务就绪
        print("[integration] 等待服务就绪 ...")
        runner.wait_for_healthy()

        # 3. 注册测试用户
        await eval_client.setup()

        # 4. 获取设备（需要 Agent WS 连接）
        device_id = await eval_client.get_or_create_device()
        terminal_id = ""
        if device_id:
            terminals = await eval_client.list_terminals(device_id)
            if terminals:
                terminal_id = terminals[0].get("terminal_id", "")

        # 5. 创建 EvalRun
        run_record = EvalRun(
            total_tasks=len(tasks),
            config_json={
                "mode": "integration",
                "base_url": base_url,
                "num_trials": args.trials,
            },
        )
        await db.save_run(run_record)

        # 6. 执行 tasks
        task_results: dict = {}
        passed_tasks = 0

        for task in tasks:
            try:
                # 保存 task def
                await db.save_task_def(task)

                trial_results = []
                for trial_idx in range(args.trials):
                    try:
                        integ_result = await run_integration_task(
                            task_def=task,
                            eval_client=eval_client,
                            device_id=device_id,
                            terminal_id=terminal_id,
                        )

                        agent_result = integ_result["agent_result"]
                        duration_ms = integ_result["duration_ms"]

                        # 使用 EvalHarness 的评估逻辑
                        harness = EvalHarness(db, num_trials=1)
                        success = harness._evaluate_trial(task, agent_result)

                        # 保存 trial
                        trial = EvalTrial(
                            task_id=task.id,
                            run_id=run_record.run_id,
                            transcript_json=integ_result["transcript"],
                            agent_result_json=agent_result,
                            duration_ms=duration_ms,
                            token_usage_json={},
                        )
                        await db.save_trial(trial)

                        trial_results.append({
                            "trial_id": trial.trial_id,
                            "success": success,
                            "duration_ms": duration_ms,
                        })

                    except Exception as e:
                        logger.warning(
                            "[integration] Task %s trial %d 异常: %s",
                            task.id, trial_idx, e,
                        )
                        error_trial = EvalTrial(
                            task_id=task.id,
                            run_id=run_record.run_id,
                            transcript_json=[{"role": "error", "content": str(e)}],
                            agent_result_json={
                                "response_type": "error",
                                "summary": str(e),
                            },
                            duration_ms=0,
                            token_usage_json={},
                        )
                        await db.save_trial(error_trial)
                        trial_results.append({
                            "trial_id": error_trial.trial_id,
                            "success": False,
                            "error": str(e),
                            "duration_ms": 0,
                        })

                task_results[task.id] = {"trials": trial_results}
                if any(t["success"] for t in trial_results):
                    passed_tasks += 1

                status_str = "PASS" if any(t["success"] for t in trial_results) else "FAIL"
                print(f"  [{status_str}] {task.id}")

            except Exception as e:
                logger.error("[integration] Task %s 执行异常: %s", task.id, e)
                task_results[task.id] = {
                    "error": str(e),
                    "trials": [],
                }

        # 更新 run
        completed_at = datetime.now(timezone.utc).isoformat()
        await db.update_run_completion(
            run_record.run_id, completed_at, len(tasks), passed_tasks,
        )

        result = {
            "run_id": run_record.run_id,
            "mode": "integration",
            "total_tasks": len(tasks),
            "passed_tasks": passed_tasks,
            "task_results": task_results,
        }

        _print_summary(result)
        print(f"\nJSON output:")
        print(json.dumps(result, indent=2, default=str))

        return 0

    except DockerBuildError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1
    except HealthCheckTimeout as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        logger.error("[integration] 未预期的错误: %s", e, exc_info=True)
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1
    finally:
        # 确保 tear down
        runner.tear_down()
        await eval_client.close()


async def _cmd_regression(args: argparse.Namespace) -> int:
    """执行 regression 子命令"""
    mode = getattr(args, "mode", "unit")

    if mode == "integration":
        # integration 模式不支持 regression（构建太重）
        print("ERROR: integration 模式暂不支持 regression 子命令", file=sys.stderr)
        return 1

    # ── unit 模式（原有逻辑不变） ──────────────────────────────────────
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
