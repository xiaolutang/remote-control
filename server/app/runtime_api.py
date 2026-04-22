"""
多 terminal runtime REST API
"""
import hashlib
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field

from app.auth import get_current_user_id
from app.database import (
    get_approved_scan_roots,
    get_pinned_projects,
    get_planner_config,
    save_planner_config,
    replace_approved_scan_roots,
    replace_pinned_projects,
)
from app.session import (
    create_session_terminal,
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


class ProjectContextCandidate(BaseModel):
    candidate_id: str
    device_id: str
    label: str
    cwd: str
    source: str
    tool_hints: list[str] = Field(default_factory=list)
    last_used_at: Optional[str] = None
    updated_at: Optional[str] = None
    requires_confirmation: bool = False


class DeviceProjectContextSnapshot(BaseModel):
    device_id: str
    generated_at: str
    candidates: list[ProjectContextCandidate]


class PinnedProjectItem(BaseModel):
    label: str
    cwd: str


class ApprovedScanRootItem(BaseModel):
    root_path: str
    scan_depth: int = 2
    enabled: bool = True


class PlannerRuntimeConfig(BaseModel):
    provider: str = "local_rules"
    llm_enabled: bool = False
    endpoint_profile: str = "openai_compatible"
    credentials_mode: str = "client_secure_storage"
    requires_explicit_opt_in: bool = True


class ProjectContextSettingsResponse(BaseModel):
    device_id: str
    pinned_projects: list[PinnedProjectItem] = Field(default_factory=list)
    approved_scan_roots: list[ApprovedScanRootItem] = Field(default_factory=list)
    planner_config: PlannerRuntimeConfig = Field(default_factory=PlannerRuntimeConfig)


class UpdateProjectContextSettingsRequest(BaseModel):
    pinned_projects: list[PinnedProjectItem] = Field(default_factory=list)
    approved_scan_roots: list[ApprovedScanRootItem] = Field(default_factory=list)
    planner_config: PlannerRuntimeConfig = Field(default_factory=PlannerRuntimeConfig)


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


def _candidate_sort_key(candidate: ProjectContextCandidate) -> tuple[float, str]:
    timestamp = candidate.updated_at or candidate.last_used_at
    if not timestamp:
        return (float("-inf"), candidate.cwd)
    try:
        normalized = timestamp.replace("Z", "+00:00")
        return (datetime.fromisoformat(normalized).timestamp(), candidate.cwd)
    except ValueError:
        return (float("-inf"), candidate.cwd)


def _build_candidate_id(source: str, cwd: str) -> str:
    digest = hashlib.sha1(f"{source}:{cwd}".encode("utf-8")).hexdigest()[:12]
    return f"cand_{digest}"


def _label_from_path(cwd: str, fallback: str = "") -> str:
    normalized = (cwd or "").rstrip("/").strip()
    if not normalized:
        return fallback or "Unnamed Project"
    return os.path.basename(normalized) or normalized or fallback or "Unnamed Project"


def _infer_tool_hints(*texts: str) -> list[str]:
    combined = " ".join(text.lower() for text in texts if text).strip()
    hints: list[str] = []
    if "claude" in combined:
        hints.append("claude_code")
    if "codex" in combined:
        hints.append("codex")
    if "shell" not in hints:
        hints.append("shell")
    return hints


def _build_recent_terminal_candidates(
    terminals: list[dict],
    *,
    device_id: str,
) -> list[ProjectContextCandidate]:
    sorted_terminals = sorted(
        [terminal for terminal in terminals if terminal.get("cwd")],
        key=lambda terminal: terminal.get("updated_at") or terminal.get("created_at") or "",
        reverse=True,
    )
    return [
        ProjectContextCandidate(
            candidate_id=_build_candidate_id("recent_terminal", terminal["cwd"]),
            device_id=device_id,
            label=_label_from_path(terminal["cwd"], terminal.get("title", "")),
            cwd=terminal["cwd"],
            source="recent_terminal",
            tool_hints=_infer_tool_hints(terminal.get("title", ""), terminal.get("command", "")),
            last_used_at=terminal.get("updated_at") or terminal.get("created_at"),
            updated_at=terminal.get("updated_at") or terminal.get("created_at"),
            requires_confirmation=False,
        )
        for terminal in sorted_terminals
    ]


def _build_pinned_project_candidates(
    projects: list[dict],
    *,
    device_id: str,
) -> list[ProjectContextCandidate]:
    sorted_projects = sorted(
        [project for project in projects if project.get("cwd")],
        key=lambda project: project.get("updated_at") or project.get("created_at") or "",
        reverse=True,
    )
    return [
        ProjectContextCandidate(
            candidate_id=_build_candidate_id("pinned_project", project["cwd"]),
            device_id=device_id,
            label=(project.get("label") or _label_from_path(project["cwd"])).strip(),
            cwd=project["cwd"],
            source="pinned_project",
            tool_hints=_infer_tool_hints(project.get("label", "")),
            last_used_at=project.get("updated_at") or project.get("created_at"),
            updated_at=project.get("updated_at") or project.get("created_at"),
            requires_confirmation=False,
        )
        for project in sorted_projects
    ]


def _dedupe_candidates(candidates: list[ProjectContextCandidate]) -> list[ProjectContextCandidate]:
    deduped: list[ProjectContextCandidate] = []
    seen_cwds: set[str] = set()
    for candidate in candidates:
        cwd = candidate.cwd.strip()
        if not cwd or cwd in seen_cwds:
            continue
        seen_cwds.add(cwd)
        deduped.append(candidate)
    deduped.sort(key=_candidate_sort_key, reverse=True)
    return deduped


async def _build_project_context_snapshot(
    *,
    session: dict,
    user_id: str,
) -> DeviceProjectContextSnapshot:
    device_id = session.get("device", {}).get("device_id", session["session_id"])
    terminals = await list_session_terminals(session["session_id"])
    pinned_projects = await get_pinned_projects(user_id, device_id)
    await get_approved_scan_roots(user_id, device_id)

    candidates = _dedupe_candidates(
        _build_recent_terminal_candidates(terminals, device_id=device_id)
        + _build_pinned_project_candidates(pinned_projects, device_id=device_id)
    )
    return DeviceProjectContextSnapshot(
        device_id=device_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        candidates=candidates,
    )


def _default_planner_config() -> PlannerRuntimeConfig:
    return PlannerRuntimeConfig()


async def _build_project_context_settings(
    *,
    session: dict,
    user_id: str,
) -> ProjectContextSettingsResponse:
    device_id = session.get("device", {}).get("device_id", session["session_id"])
    pinned_projects = await get_pinned_projects(user_id, device_id)
    scan_roots = await get_approved_scan_roots(user_id, device_id)
    planner_config = await get_planner_config(user_id, device_id)

    return ProjectContextSettingsResponse(
        device_id=device_id,
        pinned_projects=[
            PinnedProjectItem(
                label=project.get("label", ""),
                cwd=project.get("cwd", ""),
            )
            for project in pinned_projects
            if project.get("cwd")
        ],
        approved_scan_roots=[
            ApprovedScanRootItem(
                root_path=root.get("root_path", ""),
                scan_depth=int(root.get("scan_depth", 2) or 2),
                enabled=bool(root.get("enabled", True)),
            )
            for root in scan_roots
            if root.get("root_path")
        ],
        planner_config=PlannerRuntimeConfig(**planner_config)
        if planner_config
        else _default_planner_config(),
    )


@router.get("/runtime/devices", response_model=RuntimeDeviceListResponse)
async def list_runtime_devices(
    user_id: str = Depends(get_current_user_id),
):
    """列出当前用户的 runtime devices。"""
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
    user_id: str = Depends(get_current_user_id),
):
    """列出 device 下的 terminal。"""
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


@router.get(
    "/runtime/devices/{device_id}/project-context",
    response_model=DeviceProjectContextSnapshot,
)
async def get_runtime_project_context(
    device_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """返回当前设备的项目候选摘要快照。"""
    session = await get_session_by_device_id(device_id, user_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"device {device_id} 不存在",
        )
    return await _build_project_context_snapshot(session=session, user_id=user_id)


@router.post(
    "/runtime/devices/{device_id}/project-context:refresh",
    response_model=DeviceProjectContextSnapshot,
)
async def refresh_runtime_project_context(
    device_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """主动刷新当前设备的项目候选摘要快照。"""
    session = await get_session_by_device_id(device_id, user_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"device {device_id} 不存在",
    )
    return await _build_project_context_snapshot(session=session, user_id=user_id)


@router.get(
    "/runtime/devices/{device_id}/project-context/settings",
    response_model=ProjectContextSettingsResponse,
)
async def get_runtime_project_context_settings(
    device_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """读取当前设备的项目来源与 planner 配置。"""
    session = await get_session_by_device_id(device_id, user_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"device {device_id} 不存在",
        )
    return await _build_project_context_settings(session=session, user_id=user_id)


@router.put(
    "/runtime/devices/{device_id}/project-context/settings",
    response_model=ProjectContextSettingsResponse,
)
async def update_runtime_project_context_settings(
    device_id: str,
    request: UpdateProjectContextSettingsRequest,
    user_id: str = Depends(get_current_user_id),
):
    """保存当前设备的项目来源与 planner 配置。"""
    session = await get_session_by_device_id(device_id, user_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"device {device_id} 不存在",
        )

    await replace_pinned_projects(
        user_id,
        device_id,
        [
            {
                "label": item.label.strip(),
                "cwd": item.cwd.strip(),
            }
            for item in request.pinned_projects
            if item.cwd.strip()
        ],
    )
    await replace_approved_scan_roots(
        user_id,
        device_id,
        [
            {
                "root_path": item.root_path.strip(),
                "scan_depth": max(1, item.scan_depth),
                "enabled": item.enabled,
            }
            for item in request.approved_scan_roots
            if item.root_path.strip()
        ],
    )
    await save_planner_config(
        user_id,
        device_id,
        {
            "provider": request.planner_config.provider,
            "llm_enabled": request.planner_config.llm_enabled,
            "endpoint_profile": request.planner_config.endpoint_profile,
            "credentials_mode": request.planner_config.credentials_mode,
            "requires_explicit_opt_in": request.planner_config.requires_explicit_opt_in,
        },
    )
    return await _build_project_context_settings(session=session, user_id=user_id)


@router.post("/runtime/devices/{device_id}/terminals", response_model=RuntimeTerminalItem)
async def create_runtime_terminal(
    device_id: str,
    request: CreateTerminalRequest,
    user_id: str = Depends(get_current_user_id),
):
    """为在线 device 创建 terminal。"""
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
            rows=(terminal.get("pty") or {}).get("rows", 24),
            cols=(terminal.get("pty") or {}).get("cols", 80),
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
    user_id: str = Depends(get_current_user_id),
):
    """关闭 terminal，等待 agent 确认后再广播。"""
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
    user_id: str = Depends(get_current_user_id),
):
    """更新 terminal 元数据。当前仅支持标题。"""
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
