"""
Assistant REST API — 智能规划（plan / plan/stream）。
"""
import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status, Depends, Request as FastAPIRequest
from fastapi.responses import StreamingResponse
import logging

from app.services.assistant_planner import (
    AssistantPlannerRateLimited,
    AssistantPlannerTimeout,
    AssistantPlannerUnavailable,
    plan_with_service_llm,
    planner_timeout_ms,
)
from app.infra.auth import get_current_user_id
from app.api import _deps
from app.api.schemas import (
    AssistantCommandSequence,
    AssistantMessageItem,
    AssistantPlanLimits,
    AssistantPlanRequest,
    AssistantPlanResponse,
    AssistantTraceItem,
    ProjectContextCandidate,
)
from app.api.project_context_api import _normalize_planner_config
from app.api._helpers import model_dump as _model_dump, device_online as _device_online
from app.api.assistant_plan_helpers import (
    _assistant_error,
    _progress_status_update,
    _progress_tool_call,
    _normalize_assistant_message,
    _ensure_assistant_trace,
    _validate_command_sequence,
    _match_candidate_from_intent,
    _build_assistant_project_context,
    _build_assistant_planner_memory,
)
from app.api import assistant_plan_helpers as _plan_helpers

logger = logging.getLogger(__name__)

router = APIRouter()

AssistantPlanProgressReporter = Optional[Callable[[dict[str, Any]], Awaitable[None]]]


async def _create_assistant_plan_impl(
    *,
    device_id: str,
    request: AssistantPlanRequest,
    http_request: FastAPIRequest,
    user_id: str,
    progress_reporter: AssistantPlanProgressReporter = None,
) -> AssistantPlanResponse:
    """为当前在线设备生成聊天式终端执行计划。"""
    del http_request  # 预留给后续请求级追踪与审计

    async def report_progress(payload: dict[str, Any]) -> None:
        if progress_reporter is not None:
            await progress_reporter(payload)

    intent = request.intent.strip()
    if not intent:
        raise _assistant_error(
            status.HTTP_400_BAD_REQUEST,
            reason="invalid_intent",
            message="intent 不能为空",
        )
    import os
    max_length = max(32, int(os.environ.get("ASSISTANT_PLAN_INTENT_MAX_LENGTH", "500")))
    if len(intent) > max_length:
        raise _assistant_error(
            status.HTTP_400_BAD_REQUEST,
            reason="invalid_intent",
            message=f"intent 长度不能超过 {max_length} 个字符",
        )

    session = await _deps.get_session_by_device_id(device_id, user_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"device {device_id} 不存在",
        )
    if not _device_online(session):
        raise _assistant_error(
            status.HTTP_409_CONFLICT,
            reason="device_offline",
            message="当前设备未在线，无法生成终端方案",
        )

    retry_after = await _plan_helpers._check_assistant_plan_rate_limit(user_id)
    if retry_after is not None:
        raise _assistant_error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            reason="assistant_plan_rate_limited",
            message="智能规划请求过于频繁，请稍后重试",
            headers={"Retry-After": str(retry_after)},
        )

    planner_config = _normalize_planner_config(await _deps.get_planner_config(user_id, device_id))
    project_context = await _build_assistant_project_context(session=session, user_id=user_id)
    planner_memory = await _build_assistant_planner_memory(user_id=user_id, device_id=device_id)
    candidate_models = [
        ProjectContextCandidate(**candidate)
        for candidate in project_context.get("candidate_projects", [])
        if candidate.get("cwd")
    ]
    matched_candidate = _match_candidate_from_intent(intent, candidate_models)
    memory_hits = sum(len(items) for items in planner_memory.values())

    await report_progress(
        _progress_status_update(stage="context", status="running", title="读取上下文",
                                summary="正在整理当前设备、候选项目和活跃终端信息。")
    )
    await report_progress(
        _progress_tool_call(tool_id="collect_project_context", tool_name="collect_project_context",
                            status="completed", summary="已完成设备项目上下文整理。",
                            output_summary=f"候选项目 {len(candidate_models)} 个")
    )
    await report_progress(
        {"type": "assistant_message", "assistant_message": {
            "type": "assistant", "text": "我先读取当前设备上下文，再生成一组可确认的终端命令。"}}
    )
    await report_progress(
        {"type": "trace", "trace_item": {
            "stage": "context", "title": "读取上下文", "status": "completed",
            "summary": f"已整理 {len(candidate_models)} 个候选项目，准备匹配目标路径。"}}
    )
    await report_progress(
        _progress_status_update(stage="memory", status="running", title="读取历史记忆",
                                summary="正在检索最近规划和执行记录。")
    )
    await report_progress(
        _progress_tool_call(tool_id="load_planner_memory", tool_name="load_planner_memory",
                            status="completed", summary="已读取历史规划记忆。",
                            output_summary=f"命中 {memory_hits} 条记录")
    )
    await report_progress(
        {"type": "trace", "trace_item": {
            "stage": "memory", "title": "读取历史记忆", "status": "completed",
            "summary": f"已命中 {memory_hits} 条历史规划或执行记录。"}}
    )
    await report_progress(
        _progress_status_update(stage="planner", status="running", title="生成命令序列",
                                summary="正在调用服务端 LLM 生成可确认的命令序列。")
    )
    await report_progress(
        _progress_tool_call(tool_id="plan_with_service_llm", tool_name="plan_with_service_llm",
                            status="running", summary="服务端 LLM 正在分析意图并生成命令。",
                            input_summary=f"intent={intent[:48]}")
    )
    await report_progress(
        {"type": "trace", "trace_item": {
            "stage": "planner", "title": "生成命令序列", "status": "running",
            "summary": "正在调用服务端 LLM 生成可确认的命令序列。"}}
    )

    try:
        result = await _deps.plan_with_service_llm(
            intent=intent,
            device_id=device_id,
            project_context=project_context,
            planner_memory=planner_memory,
            planner_config=_model_dump(planner_config),
            conversation_id=request.conversation_id,
            message_id=request.message_id,
        )
    except AssistantPlannerRateLimited as exc:
        raise _assistant_error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            reason=exc.reason, message=exc.detail,
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except AssistantPlannerTimeout as exc:
        raise _assistant_error(
            status.HTTP_504_GATEWAY_TIMEOUT, reason=exc.reason, message=exc.detail,
        ) from exc
    except AssistantPlannerUnavailable as exc:
        status_code = (
            status.HTTP_422_UNPROCESSABLE_ENTITY
            if exc.reason == "service_llm_invalid"
            else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        raise _assistant_error(status_code, reason=exc.reason, message=exc.detail) from exc

    command_sequence = _validate_command_sequence(result.get("command_sequence"))
    evaluation_context = dict(result.get("evaluation_context") or {})
    if matched_candidate:
        evaluation_context["matched_candidate_id"] = matched_candidate.candidate_id
        evaluation_context["matched_cwd"] = matched_candidate.cwd
        evaluation_context["matched_label"] = matched_candidate.label
    evaluation_context["memory_hits"] = max(
        int(evaluation_context.get("memory_hits", 0) or 0), memory_hits,
    )
    evaluation_context.setdefault("tool_calls", 2 if memory_hits > 0 else 1)
    evaluation_context["fallback_policy"] = _model_dump(request.fallback_policy)

    assistant_messages = [
        _normalize_assistant_message(item)
        for item in (result.get("assistant_messages") or []) if isinstance(item, dict)
    ]
    if not assistant_messages:
        assistant_messages = [{"type": "assistant", "text": "我先读取当前设备上下文，再生成一组可确认的终端命令。"}]

    trace = _ensure_assistant_trace(
        [item for item in (result.get("trace") or []) if isinstance(item, dict)],
        matched_candidate=matched_candidate, memory_hits=memory_hits,
    )

    fallback_used = bool(result.get("fallback_used", False))
    fallback_reason = result.get("fallback_reason")
    provider = str(command_sequence.get("provider", "service_llm")).strip() or "service_llm"
    limits = {
        "rate_limited": False,
        "budget_blocked": fallback_reason == "service_llm_budget_blocked",
        "provider_timeout_ms": planner_timeout_ms(),
        "retry_after": None,
    }

    # --- progress: completion events ---
    await report_progress(
        _progress_tool_call(tool_id="plan_with_service_llm", tool_name="plan_with_service_llm",
                            status="completed", summary="服务端 LLM 已返回最终命令序列。",
                            output_summary=f"生成 {len(command_sequence['steps'])} 步命令")
    )
    await report_progress(
        _progress_status_update(stage="planner", status="completed", title="生成命令序列",
                                summary=f"已生成 {len(command_sequence['steps'])} 步命令，可交给用户确认。")
    )
    await report_progress(
        {"type": "trace", "trace_item": {
            "stage": "planner", "title": "生成命令序列", "status": "completed",
            "summary": f"已生成 {len(command_sequence['steps'])} 步命令，可交给用户确认。"}}
    )
    if matched_candidate:
        await report_progress(
            {"type": "trace", "trace_item": {
                "stage": "context", "title": "匹配项目", "status": "completed",
                "summary": f"本轮命中项目 {matched_candidate.label}，目录为 {matched_candidate.cwd}。"}}
        )
    await report_progress(
        _progress_status_update(stage="validation", status="completed", title="整理执行方案",
                                summary=f"已整理终端标题、工作目录和 {len(command_sequence['steps'])} 条执行命令。")
    )
    await report_progress(
        {"type": "trace", "trace_item": {
            "stage": "validation", "title": "整理执行方案", "status": "completed",
            "summary": f"已整理终端标题、工作目录和 {len(command_sequence['steps'])} 条执行命令。"}}
    )
    for message in assistant_messages:
        await report_progress({"type": "assistant_message", "assistant_message": message})
    for item in trace:
        await report_progress({"type": "trace", "trace_item": item})

    await _deps.save_assistant_planner_run(
        user_id, device_id,
        {
            "conversation_id": request.conversation_id,
            "message_id": request.message_id,
            "intent": intent, "provider": provider,
            "fallback_used": fallback_used, "fallback_reason": fallback_reason,
            "assistant_messages": assistant_messages, "trace": trace,
            "command_sequence": command_sequence,
            "evaluation_context": evaluation_context,
            "execution_status": "planned",
        },
    )

    return AssistantPlanResponse(
        conversation_id=request.conversation_id,
        message_id=request.message_id,
        assistant_messages=[AssistantMessageItem(**item) for item in assistant_messages],
        trace=[AssistantTraceItem(**item) for item in trace],
        command_sequence=AssistantCommandSequence(**command_sequence),
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        limits=AssistantPlanLimits(**limits),
        evaluation_context=evaluation_context,
    )


@router.post(
    "/runtime/devices/{device_id}/assistant/plan",
    response_model=AssistantPlanResponse,
)
async def create_assistant_plan(
    device_id: str,
    request: AssistantPlanRequest,
    http_request: FastAPIRequest,
    user_id: str = Depends(get_current_user_id),
):
    return await _create_assistant_plan_impl(
        device_id=device_id, request=request,
        http_request=http_request, user_id=user_id,
    )


@router.post("/runtime/devices/{device_id}/assistant/plan/stream")
async def create_assistant_plan_stream(
    device_id: str,
    request: AssistantPlanRequest,
    http_request: FastAPIRequest,
    user_id: str = Depends(get_current_user_id),
):
    async def event_stream():
        queue: asyncio.Queue[Optional[dict[str, Any]]] = asyncio.Queue()

        async def report_progress(payload: dict[str, Any]) -> None:
            await queue.put(payload)

        async def run_plan() -> None:
            try:
                result = await _create_assistant_plan_impl(
                    device_id=device_id, request=request,
                    http_request=http_request, user_id=user_id,
                    progress_reporter=report_progress,
                )
                await queue.put({"type": "result", "plan": _model_dump(result)})
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, dict) else {}
                await queue.put({
                    "type": "error",
                    "reason": detail.get("reason", "assistant_plan_failed"),
                    "message": detail.get("message", "智能规划失败"),
                    "retry_after": int((exc.headers or {}).get("Retry-After", "0") or 0) or None,
                })
            except Exception:
                await queue.put(
                    {"type": "error", "reason": "assistant_plan_failed", "message": "智能规划执行失败"})
            finally:
                await queue.put(None)

        task = asyncio.create_task(run_plan())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield json.dumps(item, ensure_ascii=False) + "\n"
        finally:
            await task

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")
