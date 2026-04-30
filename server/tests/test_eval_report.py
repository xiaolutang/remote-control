"""
B053: Eval HTML 报告生成器测试

覆盖：
- report_generation: 有数据时生成有效 HTML
- report_empty_db: 无数据时显示空报告
- report_compare: 对比两次 run 显示差异
- report_regression_only: 只输出退化项
- report_html_valid: HTML 结构校验
- report_transcript_escaping: 特殊内容 HTML 转义
- report_compare_invalid: 无效 run_id 处理
- report_no_raw_leakage: 脱敏验证
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

import pytest
import pytest_asyncio

from evals.db import EvalDatabase
from evals.models import (
    EvalGraderResult,
    EvalRun,
    EvalTaskDef,
    EvalTaskExpected,
    EvalTaskInput,
    EvalTaskMetadata,
    EvalTrial,
)
from evals.report import _sanitize_transcript, _html_escape, generate_report


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path):
    """临时数据库路径。"""
    return str(tmp_path / "test_evals.db")


@pytest_asyncio.fixture
async def eval_db(db_path):
    """初始化的临时数据库。"""
    db = EvalDatabase(db_path)
    await db.init_db()
    return db


async def _seed_run(
    db: EvalDatabase,
    *,
    run_id: str = None,
    total_tasks: int = 3,
    passed_tasks: int = 2,
    tasks: List[Dict[str, Any]] = None,
) -> str:
    """创建一个 run 及其关联数据。

    Args:
        tasks: [{task_id, category, description, passed, transcript, agent_result}]
    """
    if run_id is None:
        run_id = uuid4().hex

    now = datetime.now(timezone.utc).isoformat()

    # 创建 run
    run = EvalRun(
        run_id=run_id,
        started_at=now,
        completed_at=now,
        total_tasks=total_tasks,
        passed_tasks=passed_tasks,
    )
    await db.save_run(run)

    if tasks is None:
        return run_id

    for task_data in tasks:
        task_id = task_data["task_id"]
        category = task_data.get("category", "command_generation")
        desc = task_data.get("description", f"Task {task_id}")
        passed = task_data.get("passed", True)
        transcript = task_data.get("transcript", [])
        agent_result = task_data.get("agent_result", None)

        # 保存 task def
        task_def = EvalTaskDef(
            id=task_id,
            category=category,
            description=desc,
            input=EvalTaskInput(intent=f"Test intent for {task_id}"),
            expected=EvalTaskExpected(),
            graders=["exact_match"],
            metadata=EvalTaskMetadata(),
        )
        await db.save_task_def(task_def)

        # 保存 trial
        if agent_result is None:
            agent_result = (
                {"response_type": "command", "command": f"echo {task_id}"}
                if passed
                else {"response_type": "error", "summary": "Task failed"}
            )

        trial = EvalTrial(
            task_id=task_id,
            run_id=run_id,
            transcript_json=transcript,
            agent_result_json=agent_result,
            duration_ms=100,
        )
        await db.save_trial(trial)

        # 保存 grader result
        grader = EvalGraderResult(
            trial_id=trial.trial_id,
            grader_type="exact_match",
            passed=passed,
            score=1.0 if passed else 0.0,
        )
        await db.save_grader_result(grader)

    return run_id


# ── Tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_report_generation(eval_db, tmp_path):
    """有数据时生成有效 HTML。"""
    output = str(tmp_path / "report.html")
    run_id = await _seed_run(
        eval_db,
        total_tasks=3,
        passed_tasks=2,
        tasks=[
            {"task_id": "task-1", "category": "command_generation", "passed": True,
             "transcript": [{"role": "user", "content": "hello"}]},
            {"task_id": "task-2", "category": "intent_classification", "passed": True,
             "transcript": []},
            {"task_id": "task-3", "category": "safety", "passed": False,
             "transcript": [{"role": "assistant", "content": "response"}]},
        ],
    )

    result = await generate_report(eval_db, output_path=output)
    assert result == output
    assert os.path.exists(output)

    with open(output, "r") as f:
        html_content = f.read()

    # 包含关键内容
    assert "<!DOCTYPE html>" in html_content
    assert "Eval Report" in html_content
    assert "task-1" in html_content
    assert "task-2" in html_content
    assert "task-3" in html_content
    assert "command_generation" in html_content
    assert "intent_classification" in html_content
    assert "Category Breakdown" in html_content
    assert "Task Details" in html_content


@pytest.mark.asyncio
async def test_report_empty_db(eval_db, tmp_path):
    """无数据时显示空报告。"""
    output = str(tmp_path / "empty_report.html")

    result = await generate_report(eval_db, output_path=output)
    assert result == output

    with open(output, "r") as f:
        html_content = f.read()

    assert "No eval runs found" in html_content
    assert "<!DOCTYPE html>" in html_content


@pytest.mark.asyncio
async def test_report_compare(eval_db, tmp_path):
    """对比两次 run 显示差异。"""
    baseline_id = "baseline-run-001"
    current_id = "current-run-002"

    # Baseline run: task-1 pass, task-2 pass
    await _seed_run(
        eval_db,
        run_id=baseline_id,
        total_tasks=2,
        passed_tasks=2,
        tasks=[
            {"task_id": "task-1", "passed": True},
            {"task_id": "task-2", "passed": True},
        ],
    )

    # Current run: task-1 fail (regression), task-2 pass (stable)
    await _seed_run(
        eval_db,
        run_id=current_id,
        total_tasks=2,
        passed_tasks=1,
        tasks=[
            {"task_id": "task-1", "passed": False},
            {"task_id": "task-2", "passed": True},
        ],
    )

    output = str(tmp_path / "compare_report.html")
    result = await generate_report(
        eval_db,
        compare_run_ids=[baseline_id, current_id],
        output_path=output,
    )

    with open(output, "r") as f:
        html_content = f.read()

    # 应包含对比标记
    assert "REGRESSION" in html_content
    assert "task-1" in html_content
    assert "STABLE" in html_content or "IMPROVEMENT" in html_content


@pytest.mark.asyncio
async def test_report_regression_only(eval_db, tmp_path):
    """只输出退化项。"""
    baseline_id = "baseline-reg-001"
    current_id = "current-reg-002"

    # Baseline: task-1 pass, task-2 fail, task-3 pass
    await _seed_run(
        eval_db,
        run_id=baseline_id,
        total_tasks=3,
        passed_tasks=2,
        tasks=[
            {"task_id": "task-reg-1", "passed": True},
            {"task_id": "task-reg-2", "passed": False},
            {"task_id": "task-reg-3", "passed": True},
        ],
    )

    # Current: task-1 fail (regression), task-2 pass (improvement), task-3 pass (stable)
    await _seed_run(
        eval_db,
        run_id=current_id,
        total_tasks=3,
        passed_tasks=2,
        tasks=[
            {"task_id": "task-reg-1", "passed": False},
            {"task_id": "task-reg-2", "passed": True},
            {"task_id": "task-reg-3", "passed": True},
        ],
    )

    output = str(tmp_path / "regression_report.html")
    result = await generate_report(
        eval_db,
        compare_run_ids=[baseline_id, current_id],
        regression_only=True,
        output_path=output,
    )

    with open(output, "r") as f:
        html_content = f.read()

    # 只应有退化的 task-reg-1
    assert "task-reg-1" in html_content
    # task-reg-2 (improvement) 和 task-reg-3 (stable) 不应在详情表中
    # regression_only 过滤后，非退化 task 不出现在 <tr> 行里
    assert "task-reg-2" not in html_content
    assert "task-reg-3" not in html_content
    assert "REGRESSION" in html_content


@pytest.mark.asyncio
async def test_report_html_valid(eval_db, tmp_path):
    """HTML 结构校验。"""
    output = str(tmp_path / "valid_report.html")
    await _seed_run(
        eval_db,
        tasks=[
            {"task_id": "html-test-1", "passed": True, "transcript": []},
        ],
    )

    await generate_report(eval_db, output_path=output)

    with open(output, "r") as f:
        content = f.read()

    # 基本 HTML 结构
    assert content.startswith("<!DOCTYPE html>")
    assert "<html" in content
    assert "</html>" in content
    assert "<head>" in content
    assert "</head>" in content
    assert "<body>" in content
    assert "</body>" in content
    assert '<meta charset="UTF-8">' in content
    assert "<style>" in content
    assert "<script>" in content
    # 自包含：不引用外部 CDN
    assert "cdn" not in content.lower()
    assert "http://" not in content or "localhost" not in content


@pytest.mark.asyncio
async def test_report_transcript_escaping(eval_db, tmp_path):
    """特殊内容 HTML 转义。"""
    output = str(tmp_path / "escape_report.html")

    malicious_content = '<script>alert("xss")</script>'
    ansi_content = "\x1b[31mRed Text\x1b[0m"

    await _seed_run(
        eval_db,
        tasks=[
            {
                "task_id": "escape-task-1",
                "passed": True,
                "transcript": [
                    {"role": "user", "content": malicious_content},
                    {"role": "assistant", "content": ansi_content},
                ],
            },
        ],
    )

    await generate_report(eval_db, output_path=output)

    with open(output, "r") as f:
        content = f.read()

    # script 标签应被转义
    assert "<script>alert" not in content or "&lt;script&gt;" in content
    # ANSI 码应被清理
    assert "\x1b[" not in content


@pytest.mark.asyncio
async def test_report_compare_invalid(eval_db, tmp_path):
    """无效 run_id 处理。"""
    output = str(tmp_path / "invalid_report.html")

    result = await generate_report(
        eval_db,
        compare_run_ids=["nonexistent-1", "nonexistent-2"],
        output_path=output,
    )

    with open(output, "r") as f:
        content = f.read()

    # 应显示错误信息
    assert "not found" in content or "error" in content.lower()
    assert "<!DOCTYPE html>" in content


def test_report_no_raw_leakage():
    """脱敏验证 — 确保不含 raw prompt、CoT 标记、敏感工具返回。"""
    transcript = [
        {"role": "system", "content": "You are a helpful assistant. <raw_prompt>Secret system prompt here</raw_prompt>"},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "<cot>Let me think about this step by step</cot>Here is my answer"},
        {"role": "tool", "content": "File contents: sensitive data here"},
        {"role": "assistant", "content": "<thinking>Internal reasoning</thinking>Final response"},
    ]

    result = _sanitize_transcript(
        transcript,
        agent_result_json={"response_type": "command", "command": "ls -la"},
        grader_results=[{"grader_type": "exact_match", "passed": True}],
    )

    # 不应包含 raw prompt
    assert "Secret system prompt" not in str(result)
    # 不应包含 CoT
    assert "Let me think about this step by step" not in str(result)
    # 不应包含敏感工具返回
    assert "sensitive data here" not in str(result)
    # 不应包含 thinking 标记内容
    assert "Internal reasoning" not in str(result)
    # 应包含 agent result 摘要
    assert "command" in result["agent_result_summary"].lower()
    # 应包含 grader 判定
    assert "PASS" in result["grader_verdict"]
    # 系统提示和工具返回的角色不应出现在 sanitized_turns
    roles = [t["role"] for t in result["sanitized_turns"]]
    assert "system" not in roles
    assert "tool" not in roles


def test_html_escape():
    """测试 HTML 转义函数。"""
    assert _html_escape("<script>") == "&lt;script&gt;"
    assert _html_escape('a="b"') == 'a=&quot;b&quot;'
    assert _html_escape("normal text") == "normal text"
    assert _html_escape("<b>bold</b>") == "&lt;b&gt;bold&lt;/b&gt;"
