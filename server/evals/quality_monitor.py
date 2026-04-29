"""
B101: 质量指标提取器 — 从已完成 Agent session 的 conversation_events 中提取 5 类指标。

指标定义：
1. response_type_accuracy  — 实际响应类型与意图匹配度
2. tool_usage_efficiency   — 工具调用次数 / 解决问题所需轮数
3. command_safety_rate     — 生成命令通过安全检查的比例
4. ask_user_frequency      — ask_user 工具调用次数 / 总轮数
5. token_efficiency        — total_tokens / 任务复杂度（按 category 分桶）

CONTRACT-052 约束：
- quality_monitor 只读 agent_conversation_events 元数据
  （event_type / tool_name / response_type / token_usage）
- 不读对话文本内容
- 指标只写 evals.db，不写 app.db

S111: 适配新事件模型 — 识别 tool_step（替代旧 trace）、phase_change、streaming_text。
     向后兼容：仍识别旧 trace 事件类型（payload.tool → payload.tool_name）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from evals.db import EvalDatabase
from evals.models import QualityMetric

logger = logging.getLogger(__name__)

# ── 5 类指标名称 ──────────────────────────────────────────────────────────────

METRIC_RESPONSE_TYPE_ACCURACY = "response_type_accuracy"
METRIC_TOOL_USAGE_EFFICIENCY = "tool_usage_efficiency"
METRIC_COMMAND_SAFETY_RATE = "command_safety_rate"
METRIC_ASK_USER_FREQUENCY = "ask_user_frequency"
METRIC_TOKEN_EFFICIENCY = "token_efficiency"

# B055: 效率指标
METRIC_N_TURNS = "n_turns"
METRIC_N_TOOLCALLS = "n_toolcalls"
METRIC_TIME_TO_FIRST_TOKEN = "time_to_first_token"
METRIC_OUTPUT_TOKENS_PER_SEC = "output_tokens_per_sec"
METRIC_TIME_TO_LAST_TOKEN = "time_to_last_token"

ALL_METRIC_NAMES = [
    METRIC_RESPONSE_TYPE_ACCURACY,
    METRIC_TOOL_USAGE_EFFICIENCY,
    METRIC_COMMAND_SAFETY_RATE,
    METRIC_ASK_USER_FREQUENCY,
    METRIC_TOKEN_EFFICIENCY,
    METRIC_N_TURNS,
    METRIC_N_TOOLCALLS,
    METRIC_TIME_TO_FIRST_TOKEN,
    METRIC_OUTPUT_TOKENS_PER_SEC,
    METRIC_TIME_TO_LAST_TOKEN,
]

# ── 任务复杂度分桶基准（token 效率用）─────────────────────────────────────────
# 按轮数划分：<=3 easy, 4-8 medium, >8 hard
# 基准值 = 该复杂度下"合理"的 token 消耗
COMPLEXITY_BASELINE_TOKENS = {
    "easy": 500,       # <=3 轮
    "medium": 1500,    # 4-8 轮
    "hard": 3000,      # >8 轮
}

# ── 意图 → 预期 response_type 映射 ────────────────────────────────────────────
# 简化版映射：基于意图关键词推断预期响应类型
INTENT_RESPONSE_TYPE_MAP = {
    "command": ["command_sequence", "command"],
    "execute": ["command_sequence", "command"],
    "run": ["command_sequence", "command"],
    "install": ["command_sequence", "command"],
    "deploy": ["command_sequence", "command"],
    "start": ["command_sequence", "command"],
    "stop": ["command_sequence", "command"],
    "restart": ["command_sequence", "command"],
    "kill": ["command_sequence", "command"],
    "clean": ["command_sequence", "command"],
    "remove": ["command_sequence", "command"],
    "delete": ["command_sequence", "command"],
    "fix": ["command_sequence", "explanation"],
    "debug": ["explanation", "command_sequence"],
    "explain": ["explanation", "info"],
    "what": ["explanation", "info"],
    "how": ["explanation", "info"],
    "why": ["explanation", "info"],
    "show": ["info", "explanation"],
    "list": ["info", "explanation"],
    "check": ["info", "command_sequence"],
    "status": ["info", "explanation"],
    "find": ["info", "explanation"],
    "search": ["info", "explanation"],
}


# ── 数据类 ──────────────────────────────────────────────────────────────────


@dataclass
class SessionEventData:
    """从 agent_conversation_events 提取的聚合数据。"""
    session_id: str
    user_id: str = ""
    device_id: str = ""

    # 事件分类计数
    total_events: int = 0
    tool_step_events: int = 0   # B106: 替代旧 trace（向后兼容旧 trace）
    phase_change_events: int = 0
    streaming_text_events: int = 0
    question_events: int = 0
    answer_events: int = 0
    result_events: int = 0
    error_events: int = 0

    # tool_step 细分
    execute_command_count: int = 0
    ask_user_count: int = 0
    lookup_knowledge_count: int = 0
    dynamic_tool_calls: int = 0

    # 结果信息
    response_type: str = ""
    has_result: bool = False

    # 安全检查相关（从 tool_step result_summary 中提取）
    safety_checked_commands: int = 0
    safety_passed_commands: int = 0

    # Token 用量
    total_tokens: int = 0
    output_tokens: int = 0       # B055: completion tokens

    # B055: 时间戳相关（ISO 格式字符串）
    first_event_time: str = ""                # 第一个事件的时间
    last_event_time: str = ""                 # 最后一个事件的时间
    thinking_phase_time: str = ""             # phase_change(thinking) 的时间
    first_streaming_text_time: str = ""       # 第一个 streaming_text 事件的时间
    last_streaming_text_time: str = ""        # 最后一个 streaming_text 事件的时间
    result_or_error_time: str = ""            # result 或 error 事件的时间

    # 意图（从 conversation metadata 或推算）
    intent: str = ""


# ── 核心提取函数 ────────────────────────────────────────────────────────────


def _classify_complexity(turns: int) -> str:
    """根据交互轮数分类任务复杂度。"""
    if turns <= 3:
        return "easy"
    elif turns <= 8:
        return "medium"
    return "hard"


def _infer_expected_response_types(intent: str) -> List[str]:
    """从意图关键词推断预期响应类型。"""
    if not intent:
        return []
    intent_lower = intent.lower()
    for keyword, types in INTENT_RESPONSE_TYPE_MAP.items():
        if keyword in intent_lower:
            return types
    return []


def extract_session_data(
    events: List[Dict[str, Any]],
    *,
    session_id: str,
    user_id: str = "",
    device_id: str = "",
    intent: str = "",
) -> SessionEventData:
    """从一组 conversation_events 中提取聚合数据。

    只读取元数据（event_type / payload.tool / payload.response_type / payload.usage），
    不读对话文本内容。

    Args:
        events: agent_conversation_events 行列表，每行含 event_type 和 payload_json/payload
        session_id: Agent session ID
        user_id: 用户 ID
        device_id: 设备 ID
        intent: 用户意图

    Returns:
        SessionEventData 聚合数据
    """
    data = SessionEventData(
        session_id=session_id,
        user_id=user_id,
        device_id=device_id,
        intent=intent,
    )

    for event in events:
        # 兼容 payload_json 和 payload 两种字段名
        payload = event.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                payload = {}

        event_type = event.get("event_type", "")
        event_time = event.get("created_at", "") or event.get("timestamp", "")
        data.total_events += 1

        # B055: 记录首/末事件时间
        if event_time:
            if not data.first_event_time:
                data.first_event_time = event_time
            data.last_event_time = event_time

        if event_type in ("trace", "tool_step"):
            # trace: 旧事件类型（向后兼容）
            # tool_step: B106 新事件类型（payload 用 tool_name 替代 tool）
            data.tool_step_events += 1
            tool = payload.get("tool") or payload.get("tool_name", "")

            if tool == "execute_command":
                data.execute_command_count += 1
                # 检查是否有安全检查相关标记
                output = payload.get("output_summary") or payload.get("result_summary", "")
                if "SAFETY_CHECK" in output or "safety_check" in output:
                    data.safety_checked_commands += 1
                    if "BLOCKED" not in output and "blocked" not in output:
                        data.safety_passed_commands += 1

            elif tool == "ask_user":
                data.ask_user_count += 1

            elif tool == "lookup_knowledge":
                data.lookup_knowledge_count += 1

            elif tool.startswith("call_dynamic_tool:"):
                data.dynamic_tool_calls += 1

        elif event_type == "phase_change":
            data.phase_change_events += 1
            # B055: 记录 thinking phase 的时间
            phase = (payload.get("phase") or "").upper()
            if phase == "THINKING" and event_time and not data.thinking_phase_time:
                data.thinking_phase_time = event_time

        elif event_type == "streaming_text":
            data.streaming_text_events += 1
            # B055: 记录首/末 streaming_text 时间
            if event_time:
                if not data.first_streaming_text_time:
                    data.first_streaming_text_time = event_time
                data.last_streaming_text_time = event_time

        elif event_type == "question":
            data.question_events += 1
            # question 事件也计为 ask_user
            data.ask_user_count += 1

        elif event_type == "answer":
            data.answer_events += 1

        elif event_type == "result":
            data.result_events += 1
            data.has_result = True
            data.response_type = payload.get("response_type", "")
            usage = payload.get("usage") or {}
            data.total_tokens = usage.get("total_tokens", 0)
            # B055: 提取 output_tokens
            data.output_tokens = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)
            # B055: 记录 result 时间
            if event_time:
                data.result_or_error_time = event_time

        elif event_type == "error":
            data.error_events += 1
            # B055: 记录 error 时间
            if event_time:
                data.result_or_error_time = event_time

    return data


# ── 指标计算 ────────────────────────────────────────────────────────────────


def compute_response_type_accuracy(data: SessionEventData) -> float:
    """计算 response_type_accuracy：实际响应类型与意图匹配度。

    规则：
    - 无结果 → 0.0
    - 无意图 → 1.0（无法判定时默认给满分）
    - 有预期类型列表且实际匹配 → 1.0
    - 有预期类型列表但实际不匹配 → 0.0
    - 无法推断预期类型 → 0.8（保守给分）
    """
    if not data.has_result:
        return 0.0
    if not data.response_type:
        return 0.0
    if not data.intent:
        return 1.0

    expected_types = _infer_expected_response_types(data.intent)
    if not expected_types:
        return 0.8

    if data.response_type in expected_types:
        return 1.0
    return 0.0


def compute_tool_usage_efficiency(data: SessionEventData) -> float:
    """计算 tool_usage_efficiency：工具调用次数 / 解决问题所需轮数。

    轮数 = tool_step_events（工具调用是探索的主要度量）
    效率 = 1.0 / (1 + |tool_calls - optimal|)

    optimal 取 1（最理想一次解决）。

    Returns:
        0.0 ~ 1.0 之间的效率值
    """
    tool_calls = data.execute_command_count + data.dynamic_tool_calls

    if tool_calls == 0:
        return 1.0 if data.has_result else 0.0

    # 没有结果说明任务失败，工具调用都是浪费
    if not data.has_result:
        return 0.0

    # 越少工具调用完成越好，最少 1 次
    # efficiency = 1 / tool_calls, cap at 1.0
    efficiency = 1.0 / tool_calls
    return min(1.0, efficiency)


def compute_command_safety_rate(data: SessionEventData) -> float:
    """计算 command_safety_rate：生成命令通过安全检查的比例。

    如果没有安全检查记录，默认 1.0（安全检查未启用时不惩罚）。
    """
    if data.safety_checked_commands == 0:
        return 1.0
    return data.safety_passed_commands / data.safety_checked_commands


def compute_ask_user_frequency(data: SessionEventData) -> float:
    """计算 ask_user_frequency：ask_user 调用次数 / 总轮数。

    总轮数 = total_events（所有事件的计数）
    如果总事件为 0，返回 0.0。
    """
    if data.total_events == 0:
        return 0.0
    return data.ask_user_count / data.total_events


def compute_token_efficiency(data: SessionEventData) -> float:
    """计算 token_efficiency：基准 token / 实际 token。

    按任务复杂度分桶，用基准值做归一化。
    效率 = baseline_tokens / max(total_tokens, 1)，cap at 1.0。

    如果没有 token 数据，返回 0.0。
    """
    if data.total_tokens == 0:
        return 0.0

    # 用 (tool_step + question + answer) 作为交互轮数
    turns = data.tool_step_events + data.question_events + data.answer_events
    complexity = _classify_complexity(turns)
    baseline = COMPLEXITY_BASELINE_TOKENS[complexity]

    efficiency = baseline / data.total_tokens
    return min(1.0, efficiency)


# ── B055: 效率指标计算 ────────────────────────────────────────────────────


def _parse_iso_time(ts: str) -> Optional[float]:
    """解析 ISO 格式时间戳为 epoch 秒数。

    支持多种 ISO 8601 变体（带/不带时区、带/不带微秒）。
    返回 None 表示解析失败。
    """
    if not ts:
        return None
    try:
        # 尝试直接解析 ISO 格式
        dt = datetime.fromisoformat(ts)
        return dt.timestamp()
    except (ValueError, TypeError):
        pass
    return None


def compute_n_turns(data: SessionEventData) -> float:
    """B055: 计算轮次数量（phase_change 事件计数）。

    phase_change 代表 agent 循环的一次迭代（thinking/acting/reflecting）。
    返回整数值的 float（保持与其他指标一致的类型）。
    """
    return float(data.phase_change_events)


def compute_n_toolcalls(data: SessionEventData) -> float:
    """B055: 计算工具调用次数（tool_step 事件计数）。

    返回整数值的 float。
    """
    return float(data.tool_step_events)


def compute_time_to_first_token(data: SessionEventData) -> float:
    """B055: 首 token 延迟（秒）。

    从 phase_change(thinking) 到第一个 streaming_text 事件的时间差。
    无法计算时返回 -1.0。
    """
    thinking_ts = _parse_iso_time(data.thinking_phase_time)
    first_stream_ts = _parse_iso_time(data.first_streaming_text_time)

    if thinking_ts is not None and first_stream_ts is not None:
        return round(max(0.0, first_stream_ts - thinking_ts), 4)
    return -1.0


def compute_output_tokens_per_sec(data: SessionEventData) -> float:
    """B055: 输出速率（output_tokens / streaming_duration）。

    streaming_duration = 最后一个 streaming_text - 第一个 streaming_text 的时间差。
    如果 duration <= 0 或无 output_tokens，返回 -1.0。
    """
    if data.output_tokens <= 0:
        return -1.0

    first_ts = _parse_iso_time(data.first_streaming_text_time)
    last_ts = _parse_iso_time(data.last_streaming_text_time)

    if first_ts is not None and last_ts is not None:
        duration = last_ts - first_ts
        if duration > 0:
            return round(data.output_tokens / duration, 4)

    return -1.0


def compute_time_to_last_token(data: SessionEventData) -> float:
    """B055: 总延迟（秒）。

    从第一个事件到 result/error 事件的时间差。
    无法计算时返回 -1.0。
    """
    first_ts = _parse_iso_time(data.first_event_time)
    end_ts = _parse_iso_time(data.result_or_error_time)

    if first_ts is not None and end_ts is not None:
        return round(max(0.0, end_ts - first_ts), 4)
    return -1.0


# ── 指标计算入口 ────────────────────────────────────────────────────────────


def compute_all_metrics(
    data: SessionEventData,
    *,
    source: str = "production",
    result_event_id: str = "",
    terminal_id: str = "",
) -> List[QualityMetric]:
    """计算全部 5 类指标，返回 QualityMetric 列表。"""
    now = datetime.now(timezone.utc).isoformat()

    computations = [
        (METRIC_RESPONSE_TYPE_ACCURACY, compute_response_type_accuracy),
        (METRIC_TOOL_USAGE_EFFICIENCY, compute_tool_usage_efficiency),
        (METRIC_COMMAND_SAFETY_RATE, compute_command_safety_rate),
        (METRIC_ASK_USER_FREQUENCY, compute_ask_user_frequency),
        (METRIC_TOKEN_EFFICIENCY, compute_token_efficiency),
        # B055: 效率指标
        (METRIC_N_TURNS, compute_n_turns),
        (METRIC_N_TOOLCALLS, compute_n_toolcalls),
        (METRIC_TIME_TO_FIRST_TOKEN, compute_time_to_first_token),
        (METRIC_OUTPUT_TOKENS_PER_SEC, compute_output_tokens_per_sec),
        (METRIC_TIME_TO_LAST_TOKEN, compute_time_to_last_token),
    ]

    metrics: List[QualityMetric] = []
    for name, fn in computations:
        value = fn(data)
        metrics.append(QualityMetric(
            session_id=data.session_id,
            user_id=data.user_id,
            device_id=data.device_id,
            metric_name=name,
            value=round(value, 4),
            computed_at=now,
            source=source,
            result_event_id=result_event_id,
            terminal_id=terminal_id,
        ))
    return metrics


# ── 持久化入口 ──────────────────────────────────────────────────────────────


async def extract_and_store_metrics(
    eval_db: EvalDatabase,
    events: List[Dict[str, Any]],
    *,
    session_id: str,
    user_id: str = "",
    device_id: str = "",
    intent: str = "",
    source: str = "production",
    result_event_id: str = "",
    terminal_id: str = "",
) -> List[QualityMetric]:
    """从 events 提取指标并持久化到 evals.db。

    Args:
        eval_db: EvalDatabase 实例
        events: agent_conversation_events 行列表
        session_id: Agent session ID
        user_id: 用户 ID
        device_id: 设备 ID
        intent: 用户意图
        source: 来源（production/integration）
        result_event_id: 关联的 result 事件 ID
        terminal_id: 关联的 terminal ID

    Returns:
        计算并持久化的 QualityMetric 列表
    """
    data = extract_session_data(
        events,
        session_id=session_id,
        user_id=user_id,
        device_id=device_id,
        intent=intent,
    )
    metrics = compute_all_metrics(
        data,
        source=source,
        result_event_id=result_event_id,
        terminal_id=terminal_id,
    )

    for metric in metrics:
        await eval_db.save_quality_metric(metric)

    logger.info(
        "Quality metrics stored: session_id=%s metrics=%d",
        session_id,
        len(metrics),
    )
    return metrics


# ── Batch 提取入口（可回溯历史 session）──────────────────────────────────────


def _batch_read_app_db(
    app_db_path: str,
    session_ids: Optional[List[str]] = None,
    limit: int = 100,
) -> List[Tuple[str, str, str, str, List[Dict[str, Any]]]]:
    """同步读取 app.db（在 worker thread 中执行）。

    返回 List[Tuple(session_id, user_id, device_id, intent, events_list)]。
    """
    session_data_list: List[Tuple[str, str, str, str, List[Dict[str, Any]]]] = []

    conn = sqlite3.connect(app_db_path)
    conn.row_factory = sqlite3.Row
    try:
        # 查找已完成（有 result 事件）的 session
        if session_ids:
            placeholders = ",".join("?" for _ in session_ids)
            cursor = conn.execute(
                f"""
                SELECT DISTINCT session_id
                FROM agent_conversation_events
                WHERE session_id IN ({placeholders})
                  AND event_type = 'result'
                  AND session_id IS NOT NULL
                ORDER BY session_id
                LIMIT ?
                """,
                (*session_ids, limit),
            )
        else:
            cursor = conn.execute(
                """
                SELECT DISTINCT session_id
                FROM agent_conversation_events
                WHERE event_type = 'result'
                  AND session_id IS NOT NULL
                ORDER BY session_id
                LIMIT ?
                """,
                (limit,),
            )

        target_sessions = [row["session_id"] for row in cursor.fetchall()]

        for sid in target_sessions:
            # 查询该 session 的所有 events
            cursor = conn.execute(
                """
                SELECT e.event_type, e.role, e.session_id, e.payload_json,
                       c.user_id, c.device_id
                FROM agent_conversation_events e
                JOIN agent_conversations c ON e.conversation_id = c.conversation_id
                WHERE e.session_id = ?
                ORDER BY e.event_index ASC
                """,
                (sid,),
            )
            rows = cursor.fetchall()
            if not rows:
                continue

            events: List[Dict[str, Any]] = []
            user_id = ""
            device_id = ""
            intent = ""

            for row in rows:
                user_id = row["user_id"] or ""
                device_id = row["device_id"] or ""
                payload_json = row["payload_json"] or "{}"
                try:
                    payload = json.loads(payload_json)
                except (json.JSONDecodeError, TypeError):
                    payload = {}

                events.append({
                    "event_type": row["event_type"],
                    "role": row["role"],
                    "payload": payload,
                })


            session_data_list.append((sid, user_id, device_id, intent, events))

    finally:
        conn.close()

    return session_data_list


async def batch_extract_metrics(
    eval_db: EvalDatabase,
    app_db_path: str,
    *,
    session_ids: Optional[List[str]] = None,
    limit: int = 100,
) -> Dict[str, List[QualityMetric]]:
    """批量提取历史 session 的质量指标。

    将 app.db 的同步读取移到 worker thread 中执行，避免阻塞事件循环。
    然后用 extract_and_store_metrics 异步写入 evals.db。

    Args:
        eval_db: EvalDatabase 实例
        app_db_path: app.db 文件路径
        session_ids: 指定要处理的 session_id 列表，None 则处理所有有 result 的
        limit: 最大处理数量

    Returns:
        session_id -> QualityMetric 列表的映射
    """
    results: Dict[str, List[QualityMetric]] = {}

    # 在 worker thread 中执行同步 sqlite3 读取
    loop = asyncio.get_event_loop()
    session_data_list = await loop.run_in_executor(
        None, _batch_read_app_db, app_db_path, session_ids, limit
    )

    for sid, user_id, device_id, intent, events in session_data_list:
        metrics = await extract_and_store_metrics(
            eval_db,
            events,
            session_id=sid,
            user_id=user_id,
            device_id=device_id,
            intent=intent,
        )
        results[sid] = metrics

    logger.info(
        "Batch quality metrics extracted: sessions=%d total_metrics=%d",
        len(results),
        sum(len(m) for m in results.values()),
    )
    return results
