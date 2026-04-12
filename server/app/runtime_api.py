"""
多 terminal runtime REST API
"""
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import async_verify_token, TokenVerificationError
from app.session import (
    create_session_terminal,
    get_session,
    get_session_by_device_id,
    get_session_terminal,
    list_session_terminals,
    list_sessions_for_user,
    update_session_device_metadata,
    update_session_terminal_metadata,
    update_session_terminal_status,
)
from app.ws_agent import (
    is_agent_connected,
    request_agent_close_terminal_with_ack,
    request_agent_create_terminal,
)
from app.ws_client import get_view_counts

router = APIRouter()


class RuntimeDeviceItem(BaseModel):
    device_id: str
    name: str
    owner: str
    agent_online: bool
    platform: str = ""
    hostname: str = ""
    last_heartbeat_at: Optional[str] = None
    max_terminals: int
    active_terminals: int


class RuntimeDeviceListResponse(BaseModel):
    devices: list[RuntimeDeviceItem]


class RuntimeTerminalItem(BaseModel):
    terminal_id: str
    title: str
    cwd: str
    command: str
    status: str
    updated_at: Optional[str] = None
    disconnect_reason: Optional[str] = None
    views: dict


def _runtime_terminal_item(terminal: dict, *, session_id: str) -> RuntimeTerminalItem:
    views = get_view_counts(session_id, terminal.get("terminal_id"))
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


def _device_online(session: dict) -> bool:
    session_id = session.get("session_id", "")
    if session_id:
        return is_agent_connected(session_id)
    return bool(session.get("agent_online", False))


class RuntimeTerminalListResponse(BaseModel):
    device_id: str
    device_online: bool
    terminals: list[RuntimeTerminalItem]


class CreateTerminalRequest(BaseModel):
    title: str
    cwd: str
    command: str
    env: dict = Field(default_factory=dict)
    terminal_id: str


class UpdateDeviceRequest(BaseModel):
    name: Optional[str] = None


class UpdateTerminalRequest(BaseModel):
    title: str


async def _get_user_from_authorization(authorization: str) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 Authorization header 格式",
        )

    payload = await async_verify_token(authorization[7:])
    if payload.get("session_id"):
        session = await get_session(payload["session_id"])
        user_id = session.get("owner") or session.get("user_id") or ""
    else:
        user_id = payload.get("sub", "")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 缺少用户身份",
        )
    return user_id


@router.get("/runtime/devices", response_model=RuntimeDeviceListResponse)
async def list_runtime_devices(
    authorization: str = Header(..., alias="Authorization"),
):
    """列出当前用户的 runtime devices。"""
    user_id = await _get_user_from_authorization(authorization)
    sessions = await list_sessions_for_user(user_id)

    devices = []
    for session in sessions:
        device = session.get("device", {})
        terminals = session.get("terminals", [])
        active_terminals = sum(1 for terminal in terminals if terminal.get("status") != "closed")
        devices.append(RuntimeDeviceItem(
            device_id=device.get("device_id", session["session_id"]),
            name=device.get("name", ""),
            owner=session.get("owner", user_id),
            agent_online=_device_online(session),
            platform=device.get("platform", ""),
            hostname=device.get("hostname", ""),
            last_heartbeat_at=device.get("last_heartbeat_at"),
            max_terminals=device.get("max_terminals", 3),
            active_terminals=active_terminals,
        ))

    return RuntimeDeviceListResponse(devices=devices)


@router.patch("/runtime/devices/{device_id}", response_model=RuntimeDeviceItem)
async def update_runtime_device(
    device_id: str,
    request: UpdateDeviceRequest,
    authorization: str = Header(..., alias="Authorization"),
):
    """更新 device 元数据。"""
    user_id = await _get_user_from_authorization(authorization)
    session = await get_session_by_device_id(device_id, user_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"device {device_id} 不存在",
        )
    if request.name is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="至少需要提供一个可更新字段",
        )

    updated = await update_session_device_metadata(
        session["session_id"],
        name=request.name.strip() if request.name is not None else None,
    )
    terminals = updated.get("terminals", [])
    active_terminals = sum(1 for terminal in terminals if terminal.get("status") != "closed")

    return RuntimeDeviceItem(
        device_id=updated["device"].get("device_id", session["session_id"]),
        name=updated["device"].get("name", ""),
        owner=updated.get("owner", user_id),
        agent_online=_device_online(updated),
        platform=updated["device"].get("platform", ""),
        hostname=updated["device"].get("hostname", ""),
        last_heartbeat_at=updated["device"].get("last_heartbeat_at"),
        max_terminals=updated["device"].get("max_terminals", 3),
        active_terminals=active_terminals,
    )


@router.get("/runtime/devices/{device_id}/terminals", response_model=RuntimeTerminalListResponse)
async def list_runtime_terminals(
    device_id: str,
    authorization: str = Header(..., alias="Authorization"),
):
    """列出 device 下的 terminal。"""
    user_id = await _get_user_from_authorization(authorization)
    session = await get_session_by_device_id(device_id, user_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"device {device_id} 不存在",
        )

    terminals = await list_session_terminals(session["session_id"])
    return RuntimeTerminalListResponse(
        device_id=device_id,
        device_online=_device_online(session),
        terminals=[_runtime_terminal_item(terminal, session_id=session["session_id"]) for terminal in terminals],
    )


@router.post("/runtime/devices/{device_id}/terminals", response_model=RuntimeTerminalItem)
async def create_runtime_terminal(
    device_id: str,
    request: CreateTerminalRequest,
    authorization: str = Header(..., alias="Authorization"),
):
    """为在线 device 创建 terminal。"""
    user_id = await _get_user_from_authorization(authorization)
    session = await get_session_by_device_id(device_id, user_id)
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

    terminal = await create_session_terminal(
        session["session_id"],
        terminal_id=request.terminal_id,
        title=request.title,
        cwd=request.cwd,
        command=request.command,
        env=request.env,
    )

    try:
        terminal = await request_agent_create_terminal(
            session["session_id"],
            terminal_id=request.terminal_id,
            title=request.title,
            cwd=request.cwd,
            command=request.command,
            env=request.env,
        )
    except HTTPException as exc:
        reason = "create_failed"
        if exc.status_code == status.HTTP_409_CONFLICT:
            reason = "device_offline"
        elif exc.status_code == status.HTTP_504_GATEWAY_TIMEOUT:
            reason = "create_timeout"
        await update_session_terminal_status(
            session["session_id"],
            request.terminal_id,
            terminal_status="closed",
            disconnect_reason=reason,
        )
        raise
    except Exception:
        await update_session_terminal_status(
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
    authorization: str = Header(..., alias="Authorization"),
):
    """关闭 terminal，等待 agent 确认后再广播。"""
    user_id = await _get_user_from_authorization(authorization)
    session = await get_session_by_device_id(device_id, user_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"device {device_id} 不存在",
        )

    terminal = await get_session_terminal(session["session_id"], terminal_id)
    if not terminal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"terminal {terminal_id} 不存在",
        )

    if terminal.get("status") == "closed":
        return _runtime_terminal_item(terminal, session_id=session["session_id"])

    # 向 Agent 发送关闭请求，等待确认（带超时）
    try:
        await request_agent_close_terminal_with_ack(
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

    # 更新数据库状态
    terminal = await update_session_terminal_status(
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
    authorization: str = Header(..., alias="Authorization"),
):
    """更新 terminal 元数据。当前仅支持标题。"""
    user_id = await _get_user_from_authorization(authorization)
    session = await get_session_by_device_id(device_id, user_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"device {device_id} 不存在",
        )

    terminal = await update_session_terminal_metadata(
        session["session_id"],
        terminal_id,
        title=request.title.strip(),
    )

    return _runtime_terminal_item(terminal, session_id=session["session_id"])
