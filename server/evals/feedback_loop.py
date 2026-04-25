"""
B103: 反馈闭环 — 用户反馈 → Eval Task 自动转换。

流程：
1. 反馈提交后，异步触发脱敏分析
2. LLM 只接收脱敏摘要（category + 简短描述），判断是否为 Agent 质量问题
3. 如果是，生成 candidate eval task 并写入 eval_task_candidates
4. 人工审核 API 支持 list/approve/reject

架构约束：
- LLM 不接收原始反馈文本，只接收脱敏摘要
- source_feedback_id 仅存引用 ID，不存原始内容
- EVAL_FEEDBACK_MODEL 未配置时跳过自动转换，反馈正常保存
- 分析失败不阻塞反馈 API 响应
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from evals.db import EvalDatabase
from evals.harness import LLMCallError, call_llm
from evals.models import CandidateStatus, EvalTaskCandidate

logger = logging.getLogger(__name__)

# ── 脱敏分析 prompt ─────────────────────────────────────────────────────

FEEDBACK_ANALYSIS_SYSTEM_PROMPT = """你是一个反馈分类助手。你会收到一条脱敏的用户反馈摘要（仅含类别和简短描述）。

你的任务：
1. 判断这条反馈是否与 AI 智能助手的回答质量相关
2. 如果是，生成一个候选评估任务，包含：
   - suggested_intent: 模拟用户意图（脱敏）
   - suggested_category: 评估类别（intent_classification / command_generation / knowledge_retrieval / safety）
   - suggested_expected: 期望结果（acceptable_types / must_contain / must_not_contain）

如果反馈与 AI 助手质量无关（如网络问题、UI 问题、崩溃），返回 {"is_agent_quality": false}。

必须以 JSON 格式回复，不要有其他文字。"""

FEEDBACK_ANALYSIS_USER_TEMPLATE = """反馈类别: {category}
反馈描述（脱敏摘要）: {description}

请判断这是否与 AI 智能助手回答质量相关，并按 JSON 格式回复。"""


# ── 配置检查 ────────────────────────────────────────────────────────────


def get_feedback_config() -> Optional[Dict[str, str]]:
    """获取反馈分析 LLM 配置。

    使用 EVAL_FEEDBACK_MODEL / EVAL_FEEDBACK_BASE_URL / EVAL_FEEDBACK_API_KEY。
    未配置时返回 None（跳过自动转换）。
    """
    model = os.environ.get("EVAL_FEEDBACK_MODEL")
    if not model:
        return None

    # 默认复用 EVAL_AGENT 的 base_url 和 api_key
    base_url = os.environ.get(
        "EVAL_FEEDBACK_BASE_URL",
        os.environ.get("EVAL_AGENT_BASE_URL", ""),
    )
    api_key = os.environ.get(
        "EVAL_FEEDBACK_API_KEY",
        os.environ.get("EVAL_AGENT_API_KEY", ""),
    )

    if not base_url or not api_key:
        logger.warning(
            "EVAL_FEEDBACK_MODEL 已配置但 base_url/api_key 缺失，跳过自动转换"
        )
        return None

    return {
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
    }


# ── 核心逻辑 ────────────────────────────────────────────────────────────


def _build_desensitized_description(category: str, description: str) -> str:
    """构建脱敏摘要：只保留类别和描述的前 200 字符。"""
    # 截断过长描述，避免传给 LLM 过多信息
    truncated = description[:200] if len(description) > 200 else description
    return FEEDBACK_ANALYSIS_USER_TEMPLATE.format(
        category=category,
        description=truncated,
    )


def _parse_analysis_response(response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """解析 LLM 分析响应，返回结构化结果。

    Returns:
        包含 is_agent_quality 和可选 suggested_* 的 dict，解析失败返回 None
    """
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        logger.warning("LLM 分析响应格式异常")
        return None

    # 尝试从 content 中提取 JSON
    content = content.strip()

    # 去除可能的 markdown code block
    if content.startswith("```"):
        lines = content.split("\n")
        # 去掉首行 ``` 和末行 ```
        lines = [l for l in lines if not l.strip().startswith("```")]
        content = "\n".join(lines)

    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("LLM 分析响应 JSON 解析失败: %s", content[:100])
        return None

    if not isinstance(result, dict):
        logger.warning("LLM 分析响应不是 JSON 对象")
        return None

    # 基本校验
    if "is_agent_quality" not in result:
        logger.warning("LLM 分析响应缺少 is_agent_quality 字段")
        return None

    return result


async def analyze_feedback(
    eval_db: EvalDatabase,
    *,
    feedback_id: str,
    category: str,
    description: str,
) -> Optional[str]:
    """异步分析反馈并生成候选任务。

    Args:
        eval_db: EvalDatabase 实例
        feedback_id: 反馈引用 ID（不传原始内容）
        category: 反馈类别
        description: 反馈描述（用于脱敏摘要）

    Returns:
        candidate_id 如果生成了候选任务，否则 None
    """
    config = get_feedback_config()
    if not config:
        logger.info("EVAL_FEEDBACK_MODEL 未配置，跳过反馈分析")
        return None

    # 构建脱敏摘要
    desensitized = _build_desensitized_description(category, description)

    messages = [
        {"role": "system", "content": FEEDBACK_ANALYSIS_SYSTEM_PROMPT},
        {"role": "user", "content": desensitized},
    ]

    try:
        response = await call_llm(config, messages, timeout=30.0)
    except LLMCallError as e:
        logger.warning("反馈分析 LLM 调用失败: %s", e)
        return None

    result = _parse_analysis_response(response)
    if result is None:
        logger.warning("反馈分析结果解析失败，跳过 candidate 生成")
        return None

    # 不是 Agent 质量问题，跳过
    if not result.get("is_agent_quality", False):
        logger.info("反馈 %s 不属于 Agent 质量问题，跳过", feedback_id)
        return None

    # 生成候选任务
    suggested_intent = result.get("suggested_intent", "")
    suggested_category = result.get("suggested_category", "command_generation")
    suggested_expected = result.get("suggested_expected", {})

    if not suggested_intent:
        logger.warning("LLM 分析结果缺少 suggested_intent，跳过 candidate 生成")
        return None

    candidate = EvalTaskCandidate(
        source_feedback_id=feedback_id,  # 仅存引用 ID
        suggested_intent=suggested_intent,
        suggested_category=suggested_category,
        suggested_expected_json=suggested_expected,
    )

    await eval_db.save_task_candidate(candidate)
    logger.info(
        "反馈 %s → candidate %s (intent=%s, category=%s)",
        feedback_id,
        candidate.candidate_id,
        suggested_intent,
        suggested_category,
    )
    return candidate.candidate_id


# ── 人工审核 API helper ────────────────────────────────────────────────


async def list_candidates(
    eval_db: EvalDatabase,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """列出候选任务"""
    candidates = await eval_db.list_task_candidates(status=status)
    return [c.model_dump() for c in candidates]


async def approve_candidate(
    eval_db: EvalDatabase,
    candidate_id: str,
    reviewer: str,
) -> Optional[Dict[str, Any]]:
    """审核通过候选任务"""
    candidate = await eval_db.get_task_candidate(candidate_id)
    if not candidate:
        return None

    if candidate.status != CandidateStatus.PENDING:
        return {"error": f"候选任务状态为 {candidate.status.value}，无法审核"}

    updated = await eval_db.update_candidate_status(
        candidate_id, CandidateStatus.APPROVED, reviewer
    )
    if not updated:
        return None

    candidate.status = CandidateStatus.APPROVED
    candidate.reviewed_by = reviewer
    return candidate.model_dump()


async def reject_candidate(
    eval_db: EvalDatabase,
    candidate_id: str,
    reviewer: str,
) -> Optional[Dict[str, Any]]:
    """审核拒绝候选任务"""
    candidate = await eval_db.get_task_candidate(candidate_id)
    if not candidate:
        return None

    if candidate.status != CandidateStatus.PENDING:
        return {"error": f"候选任务状态为 {candidate.status.value}，无法审核"}

    updated = await eval_db.update_candidate_status(
        candidate_id, CandidateStatus.REJECTED, reviewer
    )
    if not updated:
        return None

    candidate.status = CandidateStatus.REJECTED
    candidate.reviewed_by = reviewer
    return candidate.model_dump()
