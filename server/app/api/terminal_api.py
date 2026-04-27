"""
Terminal REST API — terminal CRUD。
"""
from fastapi import APIRouter, HTTPException, status, Depends
import logging
from typing import Optional

from app.infra.auth import get_current_user_id
from app.api import _deps
from app.api.schemas import (
    RuntimeTerminalItem,
    RuntimeTerminalListResponse,
    CreateTerminalRequest,
    UpdateTerminalRequest,
)
from app.api._helpers import device_online as _device_online

logger = logging.getLogger(__name__)

router = APIRouter()


def _runtime_terminal_item(terminal: dict, *, session_id: str) -> RuntimeTerminalItem:
    views = _deps.get_view_counts(session_id, terminal.get("terminal_id"))
    return RuntimeTerminalItem(
        terminal_id=terminal["terminal_id"],
        title=terminal["title"],
        cwd=terminal["cwd"],
        command=terminal["command"],
        status=terminal["status"],
        updated_at=terminal.get("updated_at"),
        disconnect_reason=terminal.get("disconnect_reason"),
        views=views,
    )


@router.get("/runtime/devices/{device_id}/terminals", response_model=RuntimeTerminalListResponse)
async def list_runtime_terminals(
    device_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """列出 device 下的 terminal。"""
    session = await _deps.get_session_by_device_id(device_id, user_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"device {device_id} 不存在",
        )

    terminals = await _deps.list_session_terminals(session["session_id"])
    return RuntimeTerminalListResponse(
        device_id=device_id,
        device_online=_device_online(session),
        terminals=[_runtime_terminal_item(terminal, session_id=session["session_id"]) for terminal in terminals],
    )


@router.post("/runtime/devices/{device_id}/terminals", response_model=RuntimeTerminalItem)
async def create_runtime_terminal(
    device_id: str,
    request: CreateTerminalRequest,
    user_id: str = Depends(get_current_user_id),
):
    """为在线 device 创建 terminal。"""
    session = await _deps.get_session_by_device_id(device_id, user_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"device {device_id} 不存在",
        )

    if not _device_online(session):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="device offline，当前不可创建 terminal",
        )

    terminal = await _deps.create_session_terminal(
        session["session_id"],
        terminal_id=request.terminal_id,
        title=request.title,
        cwd=request.cwd,
        command=request.command,
        env=request.env,
    )

    try:
        terminal = await _deps.request_agent_create_terminal(
            session["session_id"],
            terminal_id=request.terminal_id,
            title=request.title,
            cwd=request.cwd,
            command=request.command,
            env=request.env,
            rows=(terminal.get("pty") or {}).get("rows", 24),
            cols=(terminal.get("pty") or {}).get("cols", 80),
        )
    except HTTPException as exc:
        reason = "create_failed"
        if exc.status_code == status.HTTP_409_CONFLICT:
            reason = "device_offline"
        elif exc.status_code == status.HTTP_504_GATEWAY_TIMEOUT:
            reason = "create_timeout"
        await _deps.update_session_terminal_status(
            session["session_id"],
            request.terminal_id,
            terminal_status="closed",
            disconnect_reason=reason,
        )
        raise
    except Exception:
        await _deps.update_session_terminal_status(
            session["session_id"],
            request.terminal_id,
            terminal_status="closed",
            disconnect_reason="create_failed",
        )
        raise

    return _runtime_terminal_item(terminal, session_id=session["session_id"])


@router.delete("/runtime/devices/{device_id}/terminals/{terminal_id}", response_model=RuntimeTerminalItem)
async def close_runtime_terminal(
    device_id: str,
    terminal_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """关闭 terminal，等待 agent 确认后再广播。"""
    from app.api.agent_conversation_helpers import _close_terminal_agent_conversation

    session = await _deps.get_session_by_device_id(device_id, user_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"device {device_id} 不存在",
        )

    terminal = await _deps.get_session_terminal(session["session_id"], terminal_id)
    if not terminal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"terminal {terminal_id} 不存在",
        )

    if terminal.get("status") == "closed":
        await _close_terminal_agent_conversation(
            user_id=user_id,
            device_id=device_id,
            terminal_id=terminal_id,
            reason=terminal.get("disconnect_reason") or "terminal_closed",
        )
        return _runtime_terminal_item(terminal, session_id=session["session_id"])

    # 向 Agent 发送关闭请求，等待确认（带超时）
    try:
        await _deps.request_agent_close_terminal_with_ack(
            session["session_id"],
            terminal_id=terminal_id,
            reason="user_request",
            timeout=5.0,
        )
    except HTTPException as exc:
        if exc.status_code in (status.HTTP_409_CONFLICT, status.HTTP_504_GATEWAY_TIMEOUT):
            # Agent 离线或超时，仍然更新状态为关闭
            pass
        else:
            raise

    await _close_terminal_agent_conversation(
        user_id=user_id,
        device_id=device_id,
        terminal_id=terminal_id,
        reason="user_request",
    )

    # 更新数据库状态
    terminal = await _deps.update_session_terminal_status(
        session["session_id"],
        terminal_id,
        terminal_status="closed",
        disconnect_reason="user_request",
    )

    return _runtime_terminal_item(terminal, session_id=session["session_id"])


@router.patch("/runtime/devices/{device_id}/terminals/{terminal_id}", response_model=RuntimeTerminalItem)
async def update_runtime_terminal(
    device_id: str,
    terminal_id: str,
    request: UpdateTerminalRequest,
    user_id: str = Depends(get_current_user_id),
):
    """更新 terminal 元数据。当前仅支持标题。"""
    session = await _deps.get_session_by_device_id(device_id, user_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"device {device_id} 不存在",
        )

    terminal = await _deps.update_session_terminal_metadata(
        session["session_id"],
        terminal_id,
        title=request.title.strip(),
    )

    return _runtime_terminal_item(terminal, session_id=session["session_id"])
