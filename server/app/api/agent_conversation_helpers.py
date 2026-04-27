"""
Agent Conversation 辅助函数 — event 构建、stream 管理、message history。
"""
import asyncio
import json
import logging
from typing import Any, Optional
from uuid import uuid4

from fastapi import HTTPException, status
from pydantic_ai.messages import (
    ModelRequest, ModelResponse, TextPart, UserPromptPart,
    ToolCallPart, ToolReturnPart,
)

from app.api import _deps
from app.store.database import AgentConversationConflict
from app.services.agent_session_manager import (
    AgentSessionManager,
    AgentSessionState,
)
from app.api.schemas import (
    AgentConversationEventItem,
    AgentConversationProjection,
)

logger = logging.getLogger(__name__)

_conversation_stream_subscribers: dict[tuple[str, str, str], set[asyncio.Queue]] = {}


def _conversation_stream_key(user_id: str, device_id: str, terminal_id: str) -> tuple[str, str, str]:
    return (user_id, device_id, terminal_id)


async def _publish_conversation_stream_event(
    user_id: str,
    device_id: str,
    terminal_id: str,
    event: dict,
) -> None:
    subscribers = list(
        _conversation_stream_subscribers.get(
            _conversation_stream_key(user_id, device_id, terminal_id),
            set(),
        )
    )
    for queue in subscribers:
        await queue.put(event)


async def _append_and_publish_conversation_event(
    *,
    user_id: str,
    device_id: str,
    terminal_id: str,
    event_type: str,
    role: str,
    payload: dict,
    session_id: Optional[str] = None,
    question_id: Optional[str] = None,
    client_event_id: Optional[str] = None,
) -> dict:
    event = await _deps.append_agent_conversation_event(
        user_id, device_id, terminal_id,
        event_type=event_type, role=role, payload=payload,
        session_id=session_id, question_id=question_id,
        client_event_id=client_event_id,
    )
    if event:
        await _publish_conversation_stream_event(user_id, device_id, terminal_id, event)
    return event


async def _close_terminal_agent_conversation(
    *,
    user_id: str,
    device_id: str,
    terminal_id: str,
    reason: str,
) -> None:
    try:
        conversation = await _deps.get_agent_conversation(user_id, device_id, terminal_id)
        if conversation is None or conversation.get("status") != "active":
            return
        closed_event = await _deps.close_agent_conversation(
            user_id, device_id, terminal_id, payload={"reason": reason},
        )
        if closed_event:
            await _publish_conversation_stream_event(user_id, device_id, terminal_id, closed_event)
        active_session = _deps.get_agent_session_manager().get_active_terminal_session(
            user_id=user_id, device_id=device_id, terminal_id=terminal_id,
            conversation_id=conversation["conversation_id"],
        )
        if active_session:
            await _deps.get_agent_session_manager().cancel(active_session.id)
    except Exception:
        logger.warning(
            "Failed to close terminal Agent conversation: user=%s device=%s terminal=%s",
            user_id, device_id, terminal_id, exc_info=True,
        )


async def _get_owned_active_terminal(
    device_id: str,
    terminal_id: str,
    user_id: str,
) -> tuple[dict, dict]:
    session = await _deps.get_session_by_device_id(device_id, user_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"device {device_id} 不存在")
    terminal = await _deps.get_session_terminal(session["session_id"], terminal_id)
    if not terminal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"terminal {terminal_id} 不存在")
    if terminal.get("status") == "closed":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"reason": "closed_terminal", "message": "terminal 已关闭，Agent conversation 不可继续"},
        )
    return session, terminal


def _raise_agent_conversation_conflict(exc: AgentConversationConflict) -> None:
    if exc.code == "closed_terminal":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"reason": "closed_terminal", "message": "terminal 已关闭，Agent conversation 不可继续"},
        )
    if exc.code == "question_already_answered":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "question_already_answered", "message": "该问题已被回答"},
        )
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"reason": exc.code, "message": "Agent conversation 写入冲突"},
    )


def _session_matches_terminal(
    agent_session,
    *,
    user_id: str,
    device_id: str,
    terminal_id: str,
    conversation_id: str,
) -> bool:
    return (
        agent_session is not None
        and agent_session.user_id == user_id
        and agent_session.device_id == device_id
        and agent_session.terminal_id == terminal_id
        and agent_session.conversation_id == conversation_id
    )


async def _find_conversation_event_by_client_event_id(
    *,
    user_id: str,
    device_id: str,
    terminal_id: str,
    client_event_id: str,
) -> Optional[dict]:
    events = await _deps.list_agent_conversation_events(user_id, device_id, terminal_id)
    for event in events:
        if event.get("client_event_id") == client_event_id:
            return event
    return None


def _agent_conversation_event_item(event: dict) -> AgentConversationEventItem:
    return AgentConversationEventItem(
        event_index=int(event.get("event_index", 0)),
        event_id=event.get("event_id", ""),
        type=event.get("event_type") or event.get("type") or "",
        role=event.get("role", ""),
        session_id=event.get("session_id"),
        question_id=event.get("question_id"),
        client_event_id=event.get("client_event_id"),
        payload=event.get("payload") or {},
        created_at=event.get("created_at"),
    )


def _build_agent_message_history_from_events(events: list[dict]) -> list:
    history: list = []
    tc_counter = 0
    pending_question_id: str | None = None
    pending_tool_step_id: str | None = None

    for event in events:
        event_type = event.get("event_type")
        payload = event.get("payload") or {}

        if event_type == "user_intent":
            text = payload.get("text")
            if text:
                history.append(ModelRequest(parts=[UserPromptPart(content=text)]))
            continue

        if event_type == "question":
            question = payload.get("question") or payload.get("text")
            if question:
                tc_counter += 1
                pending_question_id = f"tc_{tc_counter}"
                history.append(ModelResponse(parts=[
                    ToolCallPart(tool_name="ask_user", args={"question": question}, tool_call_id=pending_question_id)
                ]))
            continue

        if event_type == "answer":
            text = payload.get("text")
            if text:
                if pending_question_id:
                    history.append(ModelRequest(parts=[
                        ToolReturnPart(tool_name="ask_user", content=text, tool_call_id=pending_question_id)
                    ]))
                    pending_question_id = None
                else:
                    history.append(ModelRequest(parts=[UserPromptPart(content=text)]))
            continue

        if event_type == "tool_step" and payload.get("status") == "running":
            tc_counter += 1
            pending_tool_step_id = f"tc_{tc_counter}"
            tool_name = payload.get("tool_name", "tool")
            args = _extract_tool_args_from_event(tool_name, payload)
            history.append(ModelResponse(parts=[
                ToolCallPart(tool_name=tool_name, args=args, tool_call_id=pending_tool_step_id)
            ]))
            continue

        if event_type == "tool_step" and payload.get("status") in ("done", "error"):
            result_summary = payload.get("result_summary", "")
            tool_name = payload.get("tool_name", "tool")
            content = result_summary if result_summary else "(no output)"
            tc_id = pending_tool_step_id or f"tc_{tc_counter}"
            history.append(ModelRequest(parts=[
                ToolReturnPart(tool_name=tool_name, content=content, tool_call_id=tc_id)
            ]))
            pending_tool_step_id = None
            continue

        if event_type == "result":
            summary = payload.get("summary")
            if summary:
                history.append(ModelResponse(parts=[TextPart(content=summary)]))
            continue

    return history


def _extract_tool_args_from_event(tool_name: str, payload: dict) -> dict:
    if tool_name == "execute_command":
        cmd = payload.get("command", "")
        if not cmd:
            description = payload.get("description", "")
            if description:
                for sep in ("：", ": "):
                    if sep in description:
                        cmd = description.split(sep, 1)[1].strip()
                        break
                if not cmd:
                    cmd = description.strip()
        return {"command": cmd} if cmd else {}
    return {"description": payload.get("description", "")}


async def _build_agent_conversation_projection(
    *,
    user_id: str,
    device_id: str,
    terminal_id: str,
    after_index: Optional[int] = None,
) -> AgentConversationProjection:
    conversation = await _deps.get_agent_conversation(user_id, device_id, terminal_id)
    if conversation is None:
        return AgentConversationProjection(
            conversation_id=None, device_id=device_id, terminal_id=terminal_id,
            status="empty", next_event_index=0, active_session_id=None, events=[],
        )
    if conversation["status"] != "active":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"reason": "closed_terminal", "message": "terminal 已关闭，Agent conversation 不可继续"},
        )

    events = await _deps.list_agent_conversation_events(user_id, device_id, terminal_id, after_index=after_index)
    event_items = [_agent_conversation_event_item(event) for event in events]
    if after_index is None:
        next_event_index = max((e.event_index for e in event_items), default=-1) + 1
    else:
        next_event_index = max([after_index + 1, *[e.event_index + 1 for e in event_items]])

    active_session = _deps.get_agent_session_manager().get_active_terminal_session(
        user_id=user_id, device_id=device_id, terminal_id=terminal_id,
        conversation_id=conversation["conversation_id"],
    )
    return AgentConversationProjection(
        conversation_id=conversation["conversation_id"],
        device_id=device_id, terminal_id=terminal_id,
        status=conversation["status"],
        next_event_index=next_event_index,
        truncation_epoch=conversation.get("truncation_epoch", 0) or 0,
        active_session_id=active_session.id if active_session else None,
        events=event_items,
    )


async def _agent_sse_response_wrapper(manager: AgentSessionManager, agent_session):
    """包装 SSE 流，在结束时清理会话。"""
    created_payload = {"session_id": agent_session.id}
    if agent_session.conversation_id:
        created_payload["conversation_id"] = agent_session.conversation_id
    if agent_session.terminal_id:
        created_payload["terminal_id"] = agent_session.terminal_id
    yield f"event: session_created\ndata: {json.dumps(created_payload, ensure_ascii=False)}\n\n"
    try:
        async for chunk in manager.sse_stream(agent_session):
            yield chunk
    finally:
        if agent_session.state in (AgentSessionState.EXPLORING, AgentSessionState.ASKING):
            logger.info(
                "SSE client disconnected, session still active: session_id=%s state=%s",
                agent_session.id, agent_session.state,
            )
