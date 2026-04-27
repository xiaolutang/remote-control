"""
Assistant Plan 辅助函数 — planner 进度报告、trace 构建、command 校验。
"""
import os
from typing import Any, Optional

from fastapi import HTTPException, status
import logging

from app.services.assistant_planner import _is_dangerous_command
from app.store.session import get_redis

logger = logging.getLogger(__name__)


def _assistant_error(
    status_code: int,
    *,
    reason: str,
    message: str,
    headers: Optional[dict[str, str]] = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "reason": reason,
            "message": message,
        },
        headers=headers,
    )


def _progress_status_update(
    *,
    stage: str,
    status: str,
    title: str,
    summary: str,
) -> dict[str, Any]:
    return {
        "type": "status_update",
        "status_update": {
            "stage": stage,
            "status": status,
            "title": title,
            "summary": summary,
        },
    }


def _progress_tool_call(
    *,
    tool_id: str,
    tool_name: str,
    status: str,
    summary: str,
    input_summary: Optional[str] = None,
    output_summary: Optional[str] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "tool_call",
        "tool_call": {
            "id": tool_id,
            "tool_name": tool_name,
            "status": status,
            "summary": summary,
        },
    }
    if input_summary:
        payload["tool_call"]["input_summary"] = input_summary
    if output_summary:
        payload["tool_call"]["output_summary"] = output_summary
    return payload


def _normalize_assistant_message(raw: dict) -> dict[str, str]:
    text = str(raw.get("text", "")).strip()
    if not text:
        text = "已生成可执行命令序列。"
    return {
        "type": str(raw.get("type", "assistant")).strip() or "assistant",
        "text": text,
    }


def _normalize_trace_item(raw: dict) -> dict[str, str]:
    return {
        "stage": str(raw.get("stage", "planner")).strip() or "planner",
        "title": str(raw.get("title", "规划")).strip() or "规划",
        "status": str(raw.get("status", "completed")).strip() or "completed",
        "summary": str(raw.get("summary", "已完成")).strip() or "已完成",
    }


def _ensure_assistant_trace(
    trace: list[dict],
    *,
    matched_candidate,
    memory_hits: int,
) -> list[dict]:
    normalized = [_normalize_trace_item(item) for item in trace if isinstance(item, dict)]
    existing = {item["stage"] for item in normalized}

    context_summary = "已读取当前设备上下文"
    if matched_candidate:
        context_summary = f"命中候选项目 {matched_candidate.label}"
    elif memory_hits > 0:
        context_summary = f"已读取 {memory_hits} 条近期记忆"

    if "context" not in existing:
        normalized.insert(
            0,
            {
                "stage": "context",
                "title": "读取上下文",
                "status": "completed",
                "summary": context_summary,
            },
        )
    if "validation" not in existing:
        normalized.append(
            {
                "stage": "validation",
                "title": "安全校验",
                "status": "completed",
                "summary": "命令结构校验通过",
            }
        )
    return normalized


def _validate_command_sequence(command_sequence: Any) -> dict[str, Any]:
    if not isinstance(command_sequence, dict):
        raise _assistant_error(
            status.HTTP_400_BAD_REQUEST,
            reason="invalid_command_sequence",
            message="command_sequence 必须是对象",
        )

    summary = str(command_sequence.get("summary", "")).strip()
    steps = command_sequence.get("steps")
    if not summary:
        raise _assistant_error(
            status.HTTP_400_BAD_REQUEST,
            reason="invalid_command_sequence",
            message="command_sequence.summary 不能为空",
        )
    if not isinstance(steps, list) or not steps:
        raise _assistant_error(
            status.HTTP_400_BAD_REQUEST,
            reason="invalid_command_sequence",
            message="command_sequence.steps 不能为空",
        )

    normalized_steps: list[dict[str, str]] = []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise _assistant_error(
                status.HTTP_400_BAD_REQUEST,
                reason="invalid_command_sequence",
                message=f"command_sequence.steps[{index - 1}] 非法",
            )
        command = str(step.get("command", "")).strip()
        if not command:
            raise _assistant_error(
                status.HTTP_400_BAD_REQUEST,
                reason="invalid_command_sequence",
                message=f"command_sequence.steps[{index - 1}].command 不能为空",
            )
        if _is_dangerous_command(command):
            raise _assistant_error(
                status.HTTP_400_BAD_REQUEST,
                reason="dangerous_command",
                message=f"第 {index} 步命令存在风险",
            )
        normalized_steps.append(
            {
                "id": str(step.get("id", f"step_{index}")).strip() or f"step_{index}",
                "label": str(step.get("label", f"步骤 {index}")).strip() or f"步骤 {index}",
                "command": command,
            }
        )

    return {
        "summary": summary,
        "provider": str(command_sequence.get("provider", "service_llm")).strip() or "service_llm",
        "source": str(command_sequence.get("source", "intent")).strip() or "intent",
        "need_confirm": bool(command_sequence.get("need_confirm", True)),
        "steps": normalized_steps,
    }


async def _check_assistant_plan_rate_limit(user_id: str) -> Optional[int]:
    limit = max(0, int(os.environ.get("ASSISTANT_PLAN_RATE_LIMIT_PER_MINUTE", "12")))
    if limit <= 0:
        return None

    try:
        redis = await get_redis()
        key = f"assistant_plan_rate_limit:{user_id}"
        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, 60)
        if current > limit:
            return 60
    except Exception:
        raise
    return None


def _match_candidate_from_intent(
    intent: str,
    candidates,
) -> Optional:
    normalized_intent = intent.lower().strip()
    if not normalized_intent:
        return None

    for candidate in candidates:
        names = {
            candidate.label.lower().strip(),
            os.path.basename(candidate.cwd.rstrip("/")).lower().strip(),
        }
        for name in names:
            if name and name in normalized_intent:
                return candidate
    return candidates[0] if candidates else None


async def _build_assistant_project_context(
    *,
    session: dict,
    user_id: str,
) -> dict[str, Any]:
    from app.api import _deps
    from app.api.project_context_api import (
        _dedupe_candidates,
        _build_recent_terminal_candidates,
        _build_pinned_project_candidates,
    )
    from app.api._helpers import model_dump as _model_dump

    device_id = session.get("device", {}).get("device_id", session["session_id"])
    terminals = await _deps.list_session_terminals(session["session_id"])
    pinned_projects = await _deps.get_pinned_projects(user_id, device_id)
    scan_roots = await _deps.get_approved_scan_roots(user_id, device_id)

    candidates = _dedupe_candidates(
        _build_recent_terminal_candidates(terminals, device_id=device_id)
        + _build_pinned_project_candidates(pinned_projects, device_id=device_id)
    )
    device = session.get("device", {})
    active_terminals = sum(1 for terminal in terminals if terminal.get("status") != "closed")
    return {
        "device": {
            "device_id": device_id,
            "name": device.get("name", ""),
            "platform": device.get("platform", ""),
            "hostname": device.get("hostname", ""),
            "max_terminals": device.get("max_terminals", 3),
            "active_terminals": active_terminals,
        },
        "recent_terminals": [
            {
                "terminal_id": terminal.get("terminal_id"),
                "title": terminal.get("title", ""),
                "cwd": terminal.get("cwd", ""),
                "command": terminal.get("command", ""),
                "status": terminal.get("status", ""),
                "updated_at": terminal.get("updated_at") or terminal.get("created_at"),
            }
            for terminal in terminals
            if terminal.get("cwd")
        ][:5],
        "candidate_projects": [_model_dump(candidate) for candidate in candidates],
        "approved_scan_roots": [
            {
                "root_path": root.get("root_path", ""),
                "scan_depth": int(root.get("scan_depth", 2) or 2),
                "enabled": bool(root.get("enabled", True)),
            }
            for root in scan_roots
            if root.get("root_path")
        ],
    }


async def _build_assistant_planner_memory(
    *,
    user_id: str,
    device_id: str,
) -> dict[str, list[dict[str, Any]]]:
    from app.api import _deps
    from app.api._helpers import json_loads as _json_loads

    memory: dict[str, list[dict[str, Any]]] = {}
    for memory_type in ("recent_project", "successful_sequence", "recent_failure"):
        rows = await _deps.list_assistant_planner_memory(user_id, device_id, memory_type, limit=5)
        memory[memory_type] = [
            {
                "memory_type": row.get("memory_type"),
                "memory_key": row.get("memory_key"),
                "label": row.get("label"),
                "cwd": row.get("cwd"),
                "summary": row.get("summary"),
                "command_sequence": _json_loads(row.get("command_sequence_json"), None),
                "metadata": _json_loads(row.get("metadata_json"), {}),
                "success_count": int(row.get("success_count", 0) or 0),
                "failure_count": int(row.get("failure_count", 0) or 0),
                "last_status": row.get("last_status"),
                "updated_at": row.get("updated_at"),
            }
            for row in rows
        ]
    return memory
