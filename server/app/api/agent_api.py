"""
Agent REST API — Agent SSE 会话（run / respond / cancel / resume / conversation）。
"""
import asyncio
import logging
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status, Depends, Request as FastAPIRequest
from fastapi.responses import StreamingResponse

from app.infra.auth import get_current_user_id
from app.api import _deps
from app.store.database import (
    AgentConversationConflict,
    truncate_agent_conversation_events,
)
from app.services.agent_session_manager import (
    AgentSessionRateLimited,
    AgentSessionState,
    generate_terminal_session_id,
)
from app.api.schemas import (
    AgentRespondRequest,
    AgentRunRequest,
)
from app.api._helpers import device_online as _device_online
from app.api.agent_conversation_helpers import (
    _agent_conversation_event_item,
    _agent_sse_response_wrapper,
    _append_and_publish_conversation_event,
    _build_agent_conversation_projection,
    _build_agent_message_history_from_events,
    _conversation_stream_key,
    _conversation_stream_subscribers,
    _find_conversation_event_by_client_event_id,
    _get_owned_active_terminal,
    _publish_conversation_stream_event,
    _raise_agent_conversation_conflict,
    _session_matches_terminal,
    _close_terminal_agent_conversation,
    HISTORY_EVENT_TYPES,
    _truncate_events_by_token_budget,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _terminal_id_required_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "reason": "terminal_id_required",
            "message": "Agent API 已绑定 terminal，请使用 /runtime/devices/{device_id}/terminals/{terminal_id}/assistant/agent/... 路径",
        },
    )


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("/runtime/devices/{device_id}/terminals/{terminal_id}/assistant/conversation", response_model=None)
async def get_terminal_agent_conversation(device_id: str, terminal_id: str, user_id: str = Depends(get_current_user_id)):
    """Return the server-authoritative Agent conversation projection for a terminal."""
    from app.api.schemas import AgentConversationProjection
    await _get_owned_active_terminal(device_id, terminal_id, user_id)
    return await _build_agent_conversation_projection(
        user_id=user_id, device_id=device_id, terminal_id=terminal_id,
    )


@router.get("/runtime/devices/{device_id}/terminals/{terminal_id}/assistant/conversation/stream")
async def stream_terminal_agent_conversation(
    device_id: str,
    terminal_id: str,
    http_request: FastAPIRequest,
    after_index: int = -1,
    user_id: str = Depends(get_current_user_id),
):
    """Poll-backed SSE stream for terminal conversation events after `after_index`."""
    await _get_owned_active_terminal(device_id, terminal_id, user_id)

    async def _event_stream():
        stream_key = _conversation_stream_key(user_id, device_id, terminal_id)
        queue: asyncio.Queue = asyncio.Queue()
        _conversation_stream_subscribers.setdefault(stream_key, set()).add(queue)
        last_index = int(after_index)
        last_epoch: Optional[int] = None
        try:
            while True:
                if await http_request.is_disconnected():
                    break
                projection = await _build_agent_conversation_projection(
                    user_id=user_id, device_id=device_id, terminal_id=terminal_id,
                    after_index=last_index,
                )

                current_epoch = projection.truncation_epoch
                if last_epoch is not None and current_epoch != last_epoch:
                    reset_event = {
                        "event_index": -1,
                        "event_id": f"reset-{uuid4().hex[:8]}",
                        "event_type": "conversation_reset",
                        "role": "system",
                        "payload": {},
                    }
                    yield (
                        "event: conversation_event\n"
                        f"data: {_agent_conversation_event_item(reset_event).model_dump_json()}\n\n"
                    )
                    full_projection = await _build_agent_conversation_projection(
                        user_id=user_id, device_id=device_id, terminal_id=terminal_id,
                    )
                    for event in full_projection.events:
                        last_index = max(last_index, event.event_index)
                        yield (
                            "event: conversation_event\n"
                            f"data: {event.model_dump_json()}\n\n"
                        )
                    last_epoch = current_epoch
                    continue

                if last_epoch is None:
                    last_epoch = current_epoch

                if projection.events:
                    for event in projection.events:
                        last_index = max(last_index, event.event_index)
                        yield (
                            "event: conversation_event\n"
                            f"data: {event.model_dump_json()}\n\n"
                        )
                    continue
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                event_item = _agent_conversation_event_item(event)
                last_index = max(last_index, event_item.event_index)
                yield (
                    "event: conversation_event\n"
                    f"data: {event_item.model_dump_json()}\n\n"
                )
                if event_item.type == "closed":
                    break
        finally:
            subscribers = _conversation_stream_subscribers.get(stream_key)
            if subscribers is not None:
                subscribers.discard(queue)
                if not subscribers:
                    _conversation_stream_subscribers.pop(stream_key, None)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/runtime/devices/{device_id}/terminals/{terminal_id}/assistant/agent/run")
async def run_terminal_agent_session(
    device_id: str,
    terminal_id: str,
    request: AgentRunRequest,
    http_request: FastAPIRequest,
    user_id: str = Depends(get_current_user_id),
):
    """启动 terminal-bound Agent 会话，返回 SSE 流。"""
    intent = request.intent.strip()
    if not intent:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="intent 不能为空")
    if not request.client_event_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"reason": "client_event_id_required", "message": "client_event_id 不能为空"},
        )

    session, _terminal = await _get_owned_active_terminal(device_id, terminal_id, user_id)
    conversation = await _deps.get_or_create_agent_conversation(user_id, device_id, terminal_id)
    if conversation["status"] != "active":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"reason": "closed_terminal", "message": "terminal 已关闭，Agent conversation 不可继续"},
        )
    conversation_id = conversation["conversation_id"]
    manager = _deps.get_agent_session_manager()

    existing_user_event = await _find_conversation_event_by_client_event_id(
        user_id=user_id, device_id=device_id, terminal_id=terminal_id,
        client_event_id=request.client_event_id,
    )
    if existing_user_event:
        existing_session_id = existing_user_event.get("session_id")
        existing_session = await manager.get_session(existing_session_id) if existing_session_id else None
        if _session_matches_terminal(
            existing_session, user_id=user_id, device_id=device_id,
            terminal_id=terminal_id, conversation_id=conversation_id,
        ):
            return StreamingResponse(
                _agent_sse_response_wrapper(manager, existing_session),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no",
                    "X-Agent-Session-Id": existing_session.id,
                    "X-Agent-Conversation-Id": conversation_id,
                },
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "agent_run_already_submitted", "message": "该 client_event_id 已提交，原 Agent session 不可恢复"},
        )

    if not manager.check_user_rate_limit(user_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"reason": "agent_rate_limited", "message": "Agent 会话请求过于频繁，请稍后重试"},
            headers={"Retry-After": "60"},
        )

    agent_session_id = generate_terminal_session_id(terminal_id)

    if request.truncate_after_index is not None:
        await truncate_agent_conversation_events(
            user_id, device_id, terminal_id, after_index=request.truncate_after_index,
        )

    history_events = await _deps.list_agent_conversation_events(
        user_id, device_id, terminal_id,
        event_types=list(HISTORY_EVENT_TYPES),
    )
    history_events = _truncate_events_by_token_budget(history_events)
    message_history = _build_agent_message_history_from_events(history_events)

    try:
        user_event = await _append_and_publish_conversation_event(
            user_id=user_id, device_id=device_id, terminal_id=terminal_id,
            event_type="user_intent", role="user",
            payload={"text": intent, "client_conversation_id": request.conversation_id},
            session_id=agent_session_id, client_event_id=request.client_event_id,
        )
    except AgentConversationConflict as exc:
        _raise_agent_conversation_conflict(exc)

    if user_event.get("session_id") != agent_session_id:
        existing_session = (
            await manager.get_session(user_event.get("session_id"))
            if user_event.get("session_id") else None
        )
        if _session_matches_terminal(
            existing_session, user_id=user_id, device_id=device_id,
            terminal_id=terminal_id, conversation_id=conversation_id,
        ):
            return StreamingResponse(
                _agent_sse_response_wrapper(manager, existing_session),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no",
                    "X-Agent-Session-Id": existing_session.id,
                    "X-Agent-Conversation-Id": conversation_id,
                },
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "agent_run_already_submitted", "message": "该 client_event_id 已提交，原 Agent session 不可恢复"},
        )

    if not _device_online(session):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "device_offline", "message": "当前桌面设备未在线，无法启动智能交互"},
        )

    try:
        agent_session = await manager.reuse_or_create_session(
            intent=intent, device_id=device_id, user_id=user_id,
            terminal_id=terminal_id,
            terminal_cwd=_terminal.get("cwd"), conversation_id=conversation_id,
            message_history=message_history, check_rate_limit=False,
        )
    except AgentSessionRateLimited as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"reason": "agent_rate_limited", "message": "Agent 会话请求过于频繁，请稍后重试"},
            headers={"Retry-After": str(exc.retry_after)},
        )

    async def _execute_cmd_fn(device_id_inner, command, *, cwd=None):
        return await _deps.send_execute_command(session_id=session["session_id"], command=command, cwd=cwd)

    async def _lookup_knowledge_fn(query):
        return await _deps.send_lookup_knowledge(session_id=session["session_id"], query=query)

    async def _tool_call_fn(tool_name, arguments):
        return await _deps.send_tool_call(session_id=session["session_id"], call_id=uuid4().hex,
                                    tool_name=tool_name, arguments=arguments)

    agent_conn = _deps.get_agent_connection(session["session_id"])
    _all_tools = agent_conn.tool_catalog if agent_conn else []
    _dynamic_tools = [t for t in _all_tools if t.get("kind") == "dynamic"]
    _include_lookup_knowledge = any(
        t.get("name") == "lookup_knowledge" and t.get("kind") == "builtin" for t in _all_tools
    )

    await manager.start_agent(
        agent_session, _execute_cmd_fn,
        lookup_knowledge_fn=_lookup_knowledge_fn if _include_lookup_knowledge else None,
        tool_call_fn=_tool_call_fn,
        dynamic_tools=_dynamic_tools,
        include_lookup_knowledge=_include_lookup_knowledge,
    )

    return StreamingResponse(
        _agent_sse_response_wrapper(manager, agent_session),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no",
            "X-Agent-Session-Id": agent_session.id,
            "X-Agent-Conversation-Id": conversation_id,
        },
    )


@router.post("/runtime/devices/{device_id}/assistant/agent/run")
async def run_agent_session(device_id: str, request: AgentRunRequest, http_request: FastAPIRequest, user_id: str = Depends(get_current_user_id)):
    raise _terminal_id_required_exception()


@router.post("/runtime/devices/{device_id}/terminals/{terminal_id}/assistant/agent/{session_id}/respond")
async def respond_to_terminal_agent(
    device_id: str,
    terminal_id: str,
    session_id: str,
    request: AgentRespondRequest,
    user_id: str = Depends(get_current_user_id),
):
    """用户回复 terminal-bound Agent 问题。"""

    answer = request.answer.strip()
    if not answer:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="回复内容不能为空")
    if not request.question_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"reason": "question_id_required", "message": "question_id 不能为空"},
        )
    if not request.client_event_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"reason": "client_event_id_required", "message": "client_event_id 不能为空"},
        )

    await _get_owned_active_terminal(device_id, terminal_id, user_id)
    conversation = await _deps.get_or_create_agent_conversation(user_id, device_id, terminal_id)
    if conversation["status"] != "active":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"reason": "closed_terminal", "message": "terminal 已关闭，Agent conversation 不可继续"},
        )

    manager = _deps.get_agent_session_manager()
    agent_session = await manager.get_session(session_id)

    if not _session_matches_terminal(
        agent_session, user_id=user_id, device_id=device_id,
        terminal_id=terminal_id, conversation_id=conversation["conversation_id"],
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"会话 {session_id} 不存在")

    if agent_session.state != AgentSessionState.ASKING:
        existing_event = await _find_conversation_event_by_client_event_id(
            user_id=user_id, device_id=device_id, terminal_id=terminal_id,
            client_event_id=request.client_event_id,
        )
        if (
            existing_event
            and existing_event.get("event_type") == "answer"
            and existing_event.get("question_id") == request.question_id
            and existing_event.get("session_id") == session_id
        ):
            return {
                "status": "ok", "session_id": session_id,
                "conversation_id": conversation["conversation_id"],
                "event": existing_event, "idempotent": True,
            }
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "session_not_asking", "message": f"会话当前状态为 {agent_session.state.value}，不等待回复"},
        )

    if agent_session.pending_question_id != request.question_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "question_mismatch", "message": "question_id 与当前等待的问题不匹配"},
        )

    try:
        answer_event = await _append_and_publish_conversation_event(
            user_id=user_id, device_id=device_id, terminal_id=terminal_id,
            event_type="answer", role="user", payload={"text": answer},
            session_id=session_id, question_id=request.question_id,
            client_event_id=request.client_event_id,
        )
    except AgentConversationConflict as exc:
        _raise_agent_conversation_conflict(exc)

    success = await manager.respond(session_id, answer, question_id=request.question_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="回复失败，会话状态已变更")

    return {
        "status": "ok", "session_id": session_id,
        "conversation_id": conversation["conversation_id"],
        "event": answer_event,
    }


@router.post("/runtime/devices/{device_id}/assistant/agent/{session_id}/respond")
async def respond_to_agent(device_id: str, session_id: str, request: AgentRespondRequest, user_id: str = Depends(get_current_user_id)):
    raise _terminal_id_required_exception()


@router.post("/runtime/devices/{device_id}/terminals/{terminal_id}/assistant/agent/{session_id}/cancel")
async def cancel_terminal_agent_session(
    device_id: str,
    terminal_id: str,
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    await _get_owned_active_terminal(device_id, terminal_id, user_id)
    conversation = await _deps.get_or_create_agent_conversation(user_id, device_id, terminal_id)
    if conversation["status"] != "active":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"reason": "closed_terminal", "message": "terminal 已关闭，Agent conversation 不可继续"},
        )

    manager = _deps.get_agent_session_manager()
    agent_session = await manager.get_session(session_id)

    if not _session_matches_terminal(
        agent_session, user_id=user_id, device_id=device_id,
        terminal_id=terminal_id, conversation_id=conversation["conversation_id"],
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"会话 {session_id} 不存在")

    success = await manager.cancel(session_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "session_not_cancellable", "message": f"会话当前状态为 {agent_session.state.value}，无法取消"},
        )

    return {"status": "ok", "session_id": session_id}


@router.post("/runtime/devices/{device_id}/assistant/agent/{session_id}/cancel")
async def cancel_agent_session(device_id: str, session_id: str, user_id: str = Depends(get_current_user_id)):
    raise _terminal_id_required_exception()


@router.get("/runtime/devices/{device_id}/terminals/{terminal_id}/assistant/agent/{session_id}/resume")
async def resume_terminal_agent_session(
    device_id: str,
    terminal_id: str,
    session_id: str,
    after_index: int = 0,
    user_id: str = Depends(get_current_user_id),
):
    await _get_owned_active_terminal(device_id, terminal_id, user_id)
    conversation = await _deps.get_or_create_agent_conversation(user_id, device_id, terminal_id)
    if conversation["status"] != "active":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"reason": "closed_terminal", "message": "terminal 已关闭，Agent conversation 不可继续"},
        )

    manager = _deps.get_agent_session_manager()
    agent_session = await manager.get_session(session_id)

    if not _session_matches_terminal(
        agent_session, user_id=user_id, device_id=device_id,
        terminal_id=terminal_id, conversation_id=conversation["conversation_id"],
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"会话 {session_id} 不存在")

    return StreamingResponse(
        manager.resume_stream(agent_session, after_index=after_index),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no",
            "X-Agent-Session-Id": session_id,
        },
    )


@router.get("/runtime/devices/{device_id}/assistant/agent/{session_id}/resume")
async def resume_agent_session(device_id: str, session_id: str, after_index: int = 0, user_id: str = Depends(get_current_user_id)):
    raise _terminal_id_required_exception()
