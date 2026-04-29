"""
Assistant Execution Report + Agent Usage Summary REST API。
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, status, Depends
import logging

from app.infra.auth import get_current_user_id
from app.api import _deps
from app.api.schemas import (
    AgentUsageSummaryResponse,
    AgentUsageSummaryScope,
    AssistantExecutionReportResponse,
    AssistantExecutionReportRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _empty_agent_usage_summary_scope() -> AgentUsageSummaryScope:
    return AgentUsageSummaryScope()


@router.post(
    "/runtime/devices/{device_id}/assistant/executions/report",
    response_model=AssistantExecutionReportResponse,
)
async def create_assistant_execution_report(
    device_id: str,
    request: AssistantExecutionReportRequest,
    user_id: str = Depends(get_current_user_id),
):
    """回写聊天式智能终端计划的最终执行结果。"""
    from app.api.assistant_plan_helpers import _assistant_error, _validate_command_sequence

    execution_status = request.execution_status.strip().lower()
    if execution_status not in {"succeeded", "failed", "cancelled"}:
        raise _assistant_error(
            status.HTTP_400_BAD_REQUEST,
            reason="invalid_execution_status",
            message="execution_status 仅支持 succeeded / failed / cancelled",
        )

    session = await _deps.get_session_by_device_id(device_id, user_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"device {device_id} 不存在",
        )

    command_sequence = _validate_command_sequence(request.command_sequence)
    existing = await _deps.get_assistant_planner_run(
        user_id,
        device_id,
        request.conversation_id,
        request.message_id,
    )
    if not existing:
        raise _assistant_error(
            status.HTTP_404_NOT_FOUND,
            reason="assistant_plan_not_found",
            message="找不到对应的智能规划记录",
        )

    existing_status = str(existing.get("execution_status", "")).strip().lower()
    if existing_status in {"succeeded", "failed", "cancelled"}:
        return AssistantExecutionReportResponse(
            acknowledged=True,
            memory_updated=False,
            evaluation_recorded=True,
        )

    updated = await _deps.report_assistant_execution(
        user_id,
        device_id,
        request.conversation_id,
        request.message_id,
        execution_status=execution_status,
        terminal_id=request.terminal_id,
        failed_step_id=request.failed_step_id,
        output_summary=request.output_summary,
        command_sequence=command_sequence,
    )
    if not updated:
        raise _assistant_error(
            status.HTTP_404_NOT_FOUND,
            reason="assistant_plan_not_found",
            message="找不到对应的智能规划记录",
        )

    return AssistantExecutionReportResponse(
        acknowledged=True,
        memory_updated=True,
        evaluation_recorded=True,
    )


@router.get("/agent/usage/summary", response_model=AgentUsageSummaryResponse)
async def get_agent_usage_summary_api(
    device_id: Optional[str] = None,
    terminal_id: Optional[str] = None,
    user_id: str = Depends(get_current_user_id),
):
    """返回当前用户的 Agent usage 汇总。

    B051: 支持 terminal_id 参数实现 per-terminal usage。
    """
    if not device_id or not device_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="device_id is required",
        )

    normalized_device_id = device_id.strip()
    session = await _deps.get_session_by_device_id(normalized_device_id, user_id)

    device_scope = _empty_agent_usage_summary_scope()
    terminal_scope = None

    if session:
        # 并发执行 3 个独立的 usage 查询
        device_task = asyncio.create_task(
            _deps.get_usage_summary(user_id, normalized_device_id),
        )
        terminal_task = (
            asyncio.create_task(
                _deps.get_usage_summary(
                    user_id, normalized_device_id, terminal_id=terminal_id.strip(),
                ),
            ) if terminal_id and terminal_id.strip() else None
        )
        user_task = asyncio.create_task(
            _deps.get_usage_summary(user_id, None),
        )

        device_summary = await device_task
        device_scope = AgentUsageSummaryScope(**device_summary)
        if terminal_task:
            terminal_summary = await terminal_task
            terminal_scope = AgentUsageSummaryScope(**terminal_summary)
        user_summary = await user_task
    else:
        user_summary = await _deps.get_usage_summary(user_id, None)

    return AgentUsageSummaryResponse(
        device=device_scope,
        terminal=terminal_scope,
        user=AgentUsageSummaryScope(**user_summary),
    )
