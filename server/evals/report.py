"""
B053: Eval HTML 报告生成器

生成自包含 HTML 报告，包含：
- 总览：pass rate、总 task 数、passed/failed 分布
- 按 category 分类：每个 category 的 pass rate
- 历史趋势：最近 N 次 run 的 pass rate 变化（CSS 柱状图）
- Task 详情表：每个 task 的结果，可展开查看 transcript

颜色编码：退化→红色、改进→绿色、持平→灰色

特性：
- 无外部依赖，纯内联 CSS + JS
- Transcript 脱敏（不含 raw prompt、CoT、敏感工具返回）
- HTML 转义特殊字符
"""
from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from evals.db import EvalDatabase
from evals.regression import _get_run_task_results, _is_trial_passed

logger = logging.getLogger(__name__)

# ── Transcript 脱敏 ──────────────────────────────────────────────────────

# 需要过滤的敏感角色
_SENSITIVE_ROLES = {"system", "tool"}

# 需要过滤的内容关键词
_SENSITIVE_CONTENT_PATTERNS = [
    re.compile(r"<raw_prompt>.*?</raw_prompt>", re.DOTALL),
    re.compile(r"<cot>.*?</cot>", re.DOTALL),
    re.compile(r"<thinking>.*?</thinking>", re.DOTALL),
    re.compile(r"<scratchpad>.*?</scratchpad>", re.DOTALL),
]

# ANSI 转义序列
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _sanitize_transcript(
    transcript_json: List[Dict[str, Any]],
    agent_result_json: Optional[Dict[str, Any]] = None,
    grader_results: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """脱敏 transcript，只保留安全摘要信息。

    返回：
        {
            "agent_result_summary": str,
            "grader_verdict": str,
            "interaction_count": int,
            "sanitized_turns": [{"role": str, "summary": str}]
        }
    """
    sanitized_turns: List[Dict[str, str]] = []
    interaction_count = 0

    for turn in transcript_json:
        if not isinstance(turn, dict):
            continue
        role = turn.get("role", "unknown")
        content = turn.get("content", "")

        # 跳过系统提示和工具返回（可能含文件内容等敏感信息）
        if role in _SENSITIVE_ROLES:
            interaction_count += 1
            continue

        # 清理内容
        if isinstance(content, str):
            # 移除敏感标记
            for pattern in _SENSITIVE_CONTENT_PATTERNS:
                content = pattern.sub("[filtered]", content)
            # 移除 ANSI 转义
            content = _ANSI_ESCAPE_RE.sub("", content)
            # 截断过长内容
            if len(content) > 500:
                content = content[:500] + "..."
        else:
            content = str(content)[:500]

        sanitized_turns.append({
            "role": role,
            "summary": content,
        })
        interaction_count += 1

    # Agent result 摘要
    agent_summary = ""
    if agent_result_json and isinstance(agent_result_json, dict):
        resp_type = agent_result_json.get("response_type", "unknown")
        if resp_type == "error":
            agent_summary = f"Error: {agent_result_json.get('summary', 'unknown error')}"
        else:
            agent_summary = f"Type: {resp_type}"
            if "summary" in agent_result_json:
                agent_summary += f" | {agent_result_json['summary']}"
            if "command" in agent_result_json:
                agent_summary += f" | Command: {agent_result_json['command']}"
            agent_summary = agent_summary[:300]

    # Grader 判定
    grader_verdict = ""
    if grader_results:
        verdicts = []
        for g in grader_results:
            gtype = g.get("grader_type", "?")
            passed = g.get("passed", False)
            verdicts.append(f"{gtype}: {'PASS' if passed else 'FAIL'}")
        grader_verdict = " | ".join(verdicts)

    return {
        "agent_result_summary": agent_summary,
        "grader_verdict": grader_verdict,
        "interaction_count": interaction_count,
        "sanitized_turns": sanitized_turns,
    }


def _html_escape(text: str) -> str:
    """HTML 转义，防止 XSS。"""
    if not isinstance(text, str):
        text = str(text)
    return html.escape(text, quote=True)


# ── 报告生成 ──────────────────────────────────────────────────────────────


def _generate_css() -> str:
    """返回内联 CSS。"""
    return """
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
           background: #f5f5f5; color: #333; padding: 20px; line-height: 1.6; }
    .container { max-width: 1200px; margin: 0 auto; }
    h1 { font-size: 24px; margin-bottom: 20px; color: #1a1a1a; }
    h2 { font-size: 18px; margin: 20px 0 10px; color: #2c3e50; border-bottom: 2px solid #ddd;
         padding-bottom: 5px; }
    h3 { font-size: 15px; margin: 10px 0 5px; color: #34495e; }

    .summary-cards { display: flex; gap: 15px; flex-wrap: wrap; margin-bottom: 20px; }
    .card { background: white; border-radius: 8px; padding: 15px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            flex: 1; min-width: 150px; }
    .card .label { font-size: 12px; color: #888; text-transform: uppercase; }
    .card .value { font-size: 28px; font-weight: bold; margin-top: 5px; }
    .card.pass .value { color: #27ae60; }
    .card.fail .value { color: #e74c3c; }
    .card.total .value { color: #2c3e50; }
    .card.rate .value { color: #3498db; }

    .trend-chart { display: flex; align-items: flex-end; gap: 6px; height: 180px;
                   background: white; border-radius: 8px; padding: 15px;
                   box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow-x: auto; }
    .bar-group { display: flex; flex-direction: column; align-items: center; min-width: 40px; }
    .bar { width: 30px; border-radius: 3px 3px 0 0; transition: opacity 0.2s; }
    .bar:hover { opacity: 0.8; }
    .bar-label { font-size: 10px; margin-top: 4px; color: #888; max-width: 60px;
                 overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .bar-value { font-size: 10px; margin-bottom: 2px; color: #555; }

    table { width: 100%; border-collapse: collapse; background: white;
            border-radius: 8px; overflow: hidden;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 20px; }
    th { background: #2c3e50; color: white; padding: 10px 12px; text-align: left; font-size: 13px; }
    td { padding: 8px 12px; border-bottom: 1px solid #eee; font-size: 13px; vertical-align: top; }
    tr:hover { background: #f8f9fa; }

    .badge { display: inline-block; padding: 2px 8px; border-radius: 10px;
             font-size: 11px; font-weight: 600; }
    .badge-pass { background: #d4edda; color: #155724; }
    .badge-fail { background: #f8d7da; color: #721c24; }
    .badge-regression { background: #e74c3c; color: white; }
    .badge-improvement { background: #27ae60; color: white; }
    .badge-stable { background: #95a5a6; color: white; }

    .detail-row { display: none; }
    .detail-row.expanded { display: table-row; }
    .detail-content { background: #f8f9fa; padding: 15px; font-size: 12px; }
    .detail-content pre { background: #2c3e50; color: #ecf0f1; padding: 10px;
                          border-radius: 4px; overflow-x: auto; font-size: 11px;
                          max-height: 300px; overflow-y: auto; }

    .category-row td { background: #ecf0f1; font-weight: 600; }

    .toggle-btn { cursor: pointer; color: #3498db; text-decoration: underline;
                  border: none; background: none; font-size: 12px; padding: 0; }

    .empty-state { text-align: center; padding: 40px; color: #888; font-size: 16px; }
    .error-msg { background: #f8d7da; color: #721c24; padding: 10px 15px;
                 border-radius: 8px; margin-bottom: 15px; }
    """


def _generate_js() -> str:
    """返回内联 JS。"""
    return """
    function toggleDetail(id) {
        var row = document.getElementById(id);
        if (row) {
            row.classList.toggle('expanded');
        }
    }
    """


def _render_bar(value: float, color: str, label: str) -> str:
    """渲染柱状图单个柱子。"""
    height = max(2, int(value * 150))
    pct = f"{value:.0%}"
    return (
        f'<div class="bar-group">'
        f'<div class="bar-value">{_html_escape(pct)}</div>'
        f'<div class="bar" style="height:{height}px;background:{color}" '
        f'title="{_html_escape(label)}: {_html_escape(pct)}"></div>'
        f'<div class="bar-label" title="{_html_escape(label)}">'
        f'{_html_escape(label[:12])}</div>'
        f'</div>'
    )


def _bar_color(pass_rate: float) -> str:
    """根据 pass_rate 返回柱子颜色。"""
    if pass_rate >= 0.8:
        return "#27ae60"
    elif pass_rate >= 0.5:
        return "#f39c12"
    else:
        return "#e74c3c"


def _render_overview(run_data: Dict[str, Any]) -> str:
    """渲染总览卡片。"""
    total = run_data.get("total_tasks", 0)
    passed = run_data.get("passed_tasks", 0)
    failed = total - passed
    rate = passed / total if total > 0 else 0.0

    return (
        f'<div class="summary-cards">'
        f'<div class="card total"><div class="label">Total Tasks</div>'
        f'<div class="value">{total}</div></div>'
        f'<div class="card pass"><div class="label">Passed</div>'
        f'<div class="value">{passed}</div></div>'
        f'<div class="card fail"><div class="label">Failed</div>'
        f'<div class="value">{failed}</div></div>'
        f'<div class="card rate"><div class="label">Pass Rate</div>'
        f'<div class="value">{rate:.0%}</div></div>'
        f'</div>'
    )


def _render_categories(categories: Dict[str, Dict[str, Any]]) -> str:
    """渲染按 category 分类的表格。"""
    if not categories:
        return ""

    rows = ""
    for cat, data in sorted(categories.items()):
        total = data.get("total", 0)
        passed = data.get("passed", 0)
        rate = passed / total if total > 0 else 0.0
        badge_cls = "badge-pass" if rate >= 0.8 else "badge-fail"

        rows += (
            f'<tr>'
            f'<td>{_html_escape(cat)}</td>'
            f'<td>{total}</td>'
            f'<td>{passed}</td>'
            f'<td>{total - passed}</td>'
            f'<td><span class="badge {badge_cls}">{rate:.0%}</span></td>'
            f'</tr>'
        )

    return (
        f'<h2>Category Breakdown</h2>'
        f'<table><tr><th>Category</th><th>Total</th><th>Passed</th><th>Failed</th>'
        f'<th>Pass Rate</th></tr>{rows}</table>'
    )


def _render_trend(trend: List[Dict[str, Any]]) -> str:
    """渲染历史趋势柱状图。"""
    if not trend:
        return ""

    bars = ""
    # 趋势是按时间倒序，柱状图从左到右按时间正序
    for entry in reversed(trend):
        run_id = entry.get("run_id", "?")[:8]
        rate = entry.get("pass_rate", 0.0)
        color = _bar_color(rate)
        bars += _render_bar(rate, color, run_id)

    return (
        f'<h2>Pass Rate Trend</h2>'
        f'<div class="trend-chart">{bars}</div>'
    )


def _render_task_table(
    task_rows: List[Dict[str, Any]],
    comparison_data: Optional[Dict[str, Any]] = None,
) -> str:
    """渲染 Task 详情表。

    task_rows: [{task_id, category, description, passed, agent_summary, grader_verdict,
                 sanitized_turns, duration_ms}]
    comparison_data: 可选的对比数据 {task_id: {change: "regression"|"improvement"|"stable"}}
    """
    if not task_rows:
        return ""

    rows_html = ""
    for idx, row in enumerate(task_rows):
        task_id = row.get("task_id", "?")
        category = row.get("category", "")
        desc = row.get("description", "")[:80]
        passed = row.get("passed", False)
        duration = row.get("duration_ms", 0)
        agent_summary = row.get("agent_summary", "")
        grader_verdict = row.get("grader_verdict", "")
        turns = row.get("sanitized_turns", [])

        # 状态标记
        if comparison_data and task_id in comparison_data:
            change = comparison_data[task_id].get("change", "stable")
            if change == "regression":
                badge = '<span class="badge badge-regression">REGRESSION</span>'
            elif change == "improvement":
                badge = '<span class="badge badge-improvement">IMPROVEMENT</span>'
            else:
                badge = '<span class="badge badge-stable">STABLE</span>'
        elif passed:
            badge = '<span class="badge badge-pass">PASS</span>'
        else:
            badge = '<span class="badge badge-fail">FAIL</span>'

        # 展开详情
        detail_id = f"detail-{idx}"
        detail_lines = []
        if agent_summary:
            detail_lines.append(f"<b>Agent Result:</b> {_html_escape(agent_summary)}")
        if grader_verdict:
            detail_lines.append(f"<b>Grader:</b> {_html_escape(grader_verdict)}")
        if duration:
            detail_lines.append(f"<b>Duration:</b> {duration}ms")
        if turns:
            turns_text = "\n".join(
                f"[{_html_escape(t['role'])}] {_html_escape(t['summary'])}"
                for t in turns[:20]
            )
            detail_lines.append(f"<b>Transcript (sanitized):</b>\n<pre>{turns_text}</pre>")
        detail_html = "<br>".join(detail_lines) if detail_lines else "No details available."

        rows_html += (
            f'<tr>'
            f'<td>{_html_escape(task_id)}</td>'
            f'<td>{_html_escape(category)}</td>'
            f'<td>{_html_escape(desc)}</td>'
            f'<td>{badge}</td>'
            f'<td><button class="toggle-btn" onclick="toggleDetail(\'{detail_id}\')">'
            f'Show Detail</button></td>'
            f'</tr>'
            f'<tr id="{detail_id}" class="detail-row">'
            f'<td colspan="5" class="detail-content">{detail_html}</td>'
            f'</tr>'
        )

    return (
        f'<h2>Task Details</h2>'
        f'<table><tr>'
        f'<th>Task ID</th><th>Category</th><th>Description</th>'
        f'<th>Status</th><th>Detail</th></tr>'
        f'{rows_html}</table>'
    )


async def generate_report(
    eval_db: EvalDatabase,
    *,
    compare_run_ids: Optional[List[str]] = None,
    regression_only: bool = False,
    output_path: str = "eval_report.html",
) -> str:
    """生成 eval HTML 报告。

    Args:
        eval_db: 评估数据库实例
        compare_run_ids: 对比两次 run 的 ID 列表 [baseline, current]
        regression_only: 只输出退化项
        output_path: 输出文件路径

    Returns:
        生成的 HTML 文件路径
    """
    body_content = ""
    errors: List[str] = []

    if compare_run_ids and len(compare_run_ids) >= 2:
        # 对比模式
        baseline_id = compare_run_ids[0]
        current_id = compare_run_ids[1]
        body_content, errors = await _generate_compare_report(
            eval_db, baseline_id, current_id, regression_only
        )
    else:
        # 单次报告模式（最近一次 run）
        body_content, errors = await _generate_single_report(
            eval_db, regression_only
        )

    # 错误信息
    error_html = ""
    for err in errors:
        error_html += f'<div class="error-msg">{_html_escape(err)}</div>'

    # 组装完整 HTML
    full_html = (
        f'<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        f'<meta charset="UTF-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'<title>Eval Report</title>\n'
        f'<style>{_generate_css()}</style>\n'
        f'</head>\n<body>\n'
        f'<div class="container">\n'
        f'<h1>Eval Report</h1>\n'
        f'<p>Generated: {_html_escape(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))}</p>\n'
        f'{error_html}'
        f'{body_content}'
        f'</div>\n'
        f'<script>{_generate_js()}</script>\n'
        f'</body>\n</html>'
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_html)

    return output_path


async def _build_task_rows(
    eval_db: EvalDatabase,
    trials: list,
    task_defs: dict,
    *,
    comparison_data: Optional[Dict[str, Dict[str, str]]] = None,
    regression_only: bool = False,
) -> tuple:
    """从 trials 构建 task_rows 和 categories 聚合。

    Returns:
        (task_rows, categories) 元组
    """
    categories: Dict[str, Dict[str, int]] = {}
    task_rows: List[Dict[str, Any]] = []

    for trial in trials:
        task_id = trial.task_id
        task_def = task_defs.get(task_id)
        category = task_def.category.value if task_def else "unknown"
        description = task_def.description if task_def else ""
        passed = _is_trial_passed({"agent_result_json": trial.agent_result_json})

        # 对比模式：regression_only 过滤
        if comparison_data is not None:
            change = comparison_data.get(task_id, {}).get("change", "stable")
            if regression_only and change != "regression":
                continue

        # Category 聚合
        if category not in categories:
            categories[category] = {"total": 0, "passed": 0}
        categories[category]["total"] += 1
        if passed:
            categories[category]["passed"] += 1

        # 获取 grader results
        grader_results_raw = await eval_db.get_grader_results_by_trial(trial.trial_id)
        grader_results = [{"grader_type": g.grader_type, "passed": g.passed} for g in grader_results_raw]

        # 脱敏 transcript
        sanitized = _sanitize_transcript(
            trial.transcript_json,
            agent_result_json=trial.agent_result_json,
            grader_results=grader_results,
        )

        task_rows.append({
            "task_id": task_id,
            "category": category,
            "description": description,
            "passed": passed,
            "agent_summary": sanitized["agent_result_summary"],
            "grader_verdict": sanitized["grader_verdict"],
            "sanitized_turns": sanitized["sanitized_turns"],
            "duration_ms": trial.duration_ms,
        })

    return task_rows, categories


async def _generate_single_report(
    eval_db: EvalDatabase,
    regression_only: bool,
) -> tuple:
    """生成单次 run 的报告（最近一次）。"""
    errors: List[str] = []
    parts: List[str] = []

    runs = await eval_db.list_runs(limit=1)
    if not runs:
        return '<div class="empty-state">No eval runs found in database.</div>', errors

    latest_run = runs[0]

    run_data = {
        "total_tasks": latest_run.total_tasks,
        "passed_tasks": latest_run.passed_tasks,
    }
    parts.append(_render_overview(run_data))

    trials = await eval_db.list_trials_by_run(latest_run.run_id)
    task_defs = {td.id: td for td in await eval_db.list_task_defs()}

    task_rows, categories = await _build_task_rows(eval_db, trials, task_defs)

    parts.append(_render_categories(categories))
    trend = await _generate_trend_data(eval_db)
    parts.append(_render_trend(trend))
    parts.append(_render_task_table(task_rows))

    return "".join(parts), errors


async def _generate_compare_report(
    eval_db: EvalDatabase,
    baseline_id: str,
    current_id: str,
    regression_only: bool,
) -> tuple:
    """生成对比报告。"""
    errors: List[str] = []
    parts: List[str] = []

    baseline_run = await eval_db.get_run(baseline_id)
    current_run = await eval_db.get_run(current_id)

    if baseline_run is None:
        errors.append(f"Baseline run not found: {baseline_id}")
    if current_run is None:
        errors.append(f"Current run not found: {current_id}")

    if baseline_run is None or current_run is None:
        return (
            '<div class="empty-state">One or both runs not found.</div>',
            errors,
        )

    parts.append(f'<h2>Compare: {_html_escape(baseline_id[:12])} vs {_html_escape(current_id[:12])}</h2>')
    run_data = {
        "total_tasks": current_run.total_tasks,
        "passed_tasks": current_run.passed_tasks,
    }
    parts.append(_render_overview(run_data))

    from evals.regression import detect_regressions
    comparison = await detect_regressions(eval_db, baseline_id, current_id)

    regressions = comparison.get("regressions", [])
    improvements = comparison.get("improvements", [])
    stable = comparison.get("stable", [])

    parts.append(
        f'<div class="summary-cards">'
        f'<div class="card fail"><div class="label">Regressions</div>'
        f'<div class="value">{len(regressions)}</div></div>'
        f'<div class="card pass"><div class="label">Improvements</div>'
        f'<div class="value">{len(improvements)}</div></div>'
        f'<div class="card total"><div class="label">Stable</div>'
        f'<div class="value">{len(stable)}</div></div>'
        f'</div>'
    )

    trials = await eval_db.list_trials_by_run(current_id)
    task_defs = {td.id: td for td in await eval_db.list_task_defs()}

    comparison_data: Dict[str, Dict[str, str]] = {}
    for r in regressions:
        comparison_data[r["task_id"]] = {"change": "regression"}
    for i in improvements:
        comparison_data[i["task_id"]] = {"change": "improvement"}
    for s in stable:
        comparison_data[s["task_id"]] = {"change": "stable"}

    task_rows, categories = await _build_task_rows(
        eval_db, trials, task_defs,
        comparison_data=comparison_data,
        regression_only=regression_only,
    )

    parts.append(_render_categories(categories))
    trend = await _generate_trend_data(eval_db)
    parts.append(_render_trend(trend))
    parts.append(_render_task_table(task_rows, comparison_data=comparison_data))

    return "".join(parts), errors


async def _generate_trend_data(
    eval_db: EvalDatabase,
    limit: int = 15,
) -> List[Dict[str, Any]]:
    """生成趋势数据。"""
    from evals.regression import query_trend
    return await query_trend(eval_db, limit=limit)
