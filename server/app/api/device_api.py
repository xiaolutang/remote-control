"""
Device REST API — 设备列表、设备更新。
"""
from fastapi import APIRouter, HTTPException, status, Depends
import logging
from typing import Optional

from app.infra.auth import get_current_user_id
from app.api import _deps
from app.api.schemas import (
    RuntimeDeviceItem,
    RuntimeDeviceListResponse,
    UpdateDeviceRequest,
)
from app.api._helpers import device_online as _device_online

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/runtime/devices", response_model=RuntimeDeviceListResponse)
async def list_runtime_devices(
    user_id: str = Depends(get_current_user_id),
):
    """列出当前用户的 runtime devices。"""
    sessions = await _deps.list_sessions_for_user(user_id)

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

    # 排序：online 优先，然后按最近活跃时间降序
    devices.sort(key=lambda d: (not d.agent_online, d.last_heartbeat_at or ""), reverse=False)

    return RuntimeDeviceListResponse(devices=devices)


@router.patch("/runtime/devices/{device_id}", response_model=RuntimeDeviceItem)
async def update_runtime_device(
    device_id: str,
    request: UpdateDeviceRequest,
    user_id: str = Depends(get_current_user_id),
):
    """更新 device 元数据。"""
    session = await _deps.get_session_by_device_id(device_id, user_id)
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

    updated = await _deps.update_session_device_metadata(
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
