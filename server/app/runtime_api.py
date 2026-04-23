"""
多 terminal runtime REST API
"""
import asyncio
import hashlib
import json
import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status, Depends, Request as FastAPIRequest
from pydantic import BaseModel, Field
from fastapi.responses import StreamingResponse

from app.assistant_planner import (
    AssistantPlannerRateLimited,
    AssistantPlannerTimeout,
    AssistantPlannerUnavailable,
    _is_dangerous_command,
    plan_with_service_llm,
    planner_timeout_ms,
)
from app.auth import get_current_user_id
from app.database import (
    get_assistant_planner_run,
    get_approved_scan_roots,
    list_assistant_planner_memory,
    get_pinned_projects,
    get_planner_config,
    report_assistant_execution,
    save_planner_config,
    save_assistant_planner_run,
    replace_approved_scan_roots,
    replace_pinned_projects,
)
from app.session import (
    create_session_terminal,
    get_redis,
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
    provider: str = "claude_cli"
    llm_enabled: bool = True
    endpoint_profile: str = "openai_compatible"
    credentials_mode: str = "client_secure_storage"
    requires_explicit_opt_in: bool = False


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


class AssistantFallbackPolicy(BaseModel):
    allow_claude_cli: bool = True
    allow_local_rules: bool = True


class AssistantPlanRequest(BaseModel):
    intent: str
    conversation_id: str
    message_id: str
    fallback_policy: AssistantFallbackPolicy = Field(default_factory=AssistantFallbackPolicy)


class AssistantMessageItem(BaseModel):
    type: str = "assistant"
    text: str


class AssistantTraceItem(BaseModel):
    stage: str
    title: str
    status: str
    summary: str


class AssistantCommandStep(BaseModel):
    id: str
    label: str
    command: str


class AssistantCommandSequence(BaseModel):
    summary: str
    provider: str
    source: str
    need_confirm: bool = True
    steps: list[AssistantCommandStep]


class AssistantPlanLimits(BaseModel):
    rate_limited: bool = False
    budget_blocked: bool = False
    provider_timeout_ms: int
    retry_after: Optional[int] = None


class AssistantPlanResponse(BaseModel):
    conversation_id: str
    message_id: str
    assistant_messages: list[AssistantMessageItem] = Field(default_factory=list)
    trace: list[AssistantTraceItem] = Field(default_factory=list)
    command_sequence: AssistantCommandSequence
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    limits: AssistantPlanLimits
    evaluation_context: dict = Field(default_factory=dict)


class AssistantExecutionReportRequest(BaseModel):
    conversation_id: str
    message_id: str
    terminal_id: Optional[str] = None
    execution_status: str
    failed_step_id: Optional[str] = None
    output_summary: Optional[str] = None
    command_sequence: dict


class AssistantExecutionReportResponse(BaseModel):
    acknowledged: bool
    memory_updated: bool
    evaluation_recorded: bool


AssistantPlanProgressReporter = Optional[Callable[[dict[str, Any]], Awaitable[None]]]


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


def _normalize_planner_config(config: Optional[dict]) -> PlannerRuntimeConfig:
    if not config:
        return _default_planner_config()

    provider = config.get("provider")
    llm_enabled = bool(config.get("llm_enabled", False))
    endpoint_profile = config.get("endpoint_profile", "openai_compatible")
    credentials_mode = config.get(
        "credentials_mode", "client_secure_storage"
    )
    requires_explicit_opt_in = bool(
        config.get("requires_explicit_opt_in", True)
    )

    # 升级旧版本默认值：此前默认关闭智能规划，这会让“一句话创建”看起来始终像规则兜底。
    if (
        provider == "local_rules"
        and not llm_enabled
        and endpoint_profile == "openai_compatible"
        and credentials_mode == "client_secure_storage"
        and requires_explicit_opt_in
    ):
        return _default_planner_config()

    return PlannerRuntimeConfig(**config)


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
        planner_config=_normalize_planner_config(planner_config),
    )


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


def _model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value


def _json_loads(value: Any, default: Any) -> Any:
    if not value:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


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


def _ensure_assistant_trace(
    trace: list[dict],
    *,
    matched_candidate: Optional[ProjectContextCandidate],
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
    candidates: list[ProjectContextCandidate],
) -> Optional[ProjectContextCandidate]:
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
    device_id = session.get("device", {}).get("device_id", session["session_id"])
    terminals = await list_session_terminals(session["session_id"])
    pinned_projects = await get_pinned_projects(user_id, device_id)
    scan_roots = await get_approved_scan_roots(user_id, device_id)

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
    memory: dict[str, list[dict[str, Any]]] = {}
    for memory_type in ("recent_project", "successful_sequence", "recent_failure"):
        rows = await list_assistant_planner_memory(user_id, device_id, memory_type, limit=5)
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


async def _get_or_refresh_project_context(
    device_id: str,
    user_id: str,
) -> DeviceProjectContextSnapshot:
    """获取/刷新项目候选摘要快照的共享实现。"""
    session = await get_session_by_device_id(device_id, user_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"device {device_id} 不存在",
        )
    return await _build_project_context_snapshot(session=session, user_id=user_id)


@router.get(
    "/runtime/devices/{device_id}/project-context",
    response_model=DeviceProjectContextSnapshot,
)
async def get_runtime_project_context(
    device_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """返回当前设备的项目候选摘要快照。"""
    return await _get_or_refresh_project_context(device_id, user_id)


@router.post(
    "/runtime/devices/{device_id}/project-context:refresh",
    response_model=DeviceProjectContextSnapshot,
)
async def refresh_runtime_project_context(
    device_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """主动刷新当前设备的项目候选摘要快照。"""
    return await _get_or_refresh_project_context(device_id, user_id)
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
        device_id=device_id,
        request=request,
        http_request=http_request,
        user_id=user_id,
    )


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
    max_length = max(32, int(os.environ.get("ASSISTANT_PLAN_INTENT_MAX_LENGTH", "500")))
    if len(intent) > max_length:
        raise _assistant_error(
            status.HTTP_400_BAD_REQUEST,
            reason="invalid_intent",
            message=f"intent 长度不能超过 {max_length} 个字符",
        )

    session = await get_session_by_device_id(device_id, user_id)
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

    retry_after = await _check_assistant_plan_rate_limit(user_id)
    if retry_after is not None:
        raise _assistant_error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            reason="assistant_plan_rate_limited",
            message="智能规划请求过于频繁，请稍后重试",
            headers={"Retry-After": str(retry_after)},
        )

    planner_config = _normalize_planner_config(await get_planner_config(user_id, device_id))
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
        _progress_status_update(
            stage="context",
            status="running",
            title="读取上下文",
            summary="正在整理当前设备、候选项目和活跃终端信息。",
        )
    )
    await report_progress(
        _progress_tool_call(
            tool_id="collect_project_context",
            tool_name="collect_project_context",
            status="completed",
            summary="已完成设备项目上下文整理。",
            output_summary=f"候选项目 {len(candidate_models)} 个",
        )
    )
    await report_progress(
        {
            "type": "assistant_message",
            "assistant_message": {
                "type": "assistant",
                "text": "我先读取当前设备上下文，再生成一组可确认的终端命令。",
            },
        }
    )
    await report_progress(
        {
            "type": "trace",
            "trace_item": {
                "stage": "context",
                "title": "读取上下文",
                "status": "completed",
                "summary": f"已整理 {len(candidate_models)} 个候选项目，准备匹配目标路径。",
            },
        }
    )
    await report_progress(
        _progress_status_update(
            stage="memory",
            status="running",
            title="读取历史记忆",
            summary="正在检索最近规划和执行记录。",
        )
    )
    await report_progress(
        _progress_tool_call(
            tool_id="load_planner_memory",
            tool_name="load_planner_memory",
            status="completed",
            summary="已读取历史规划记忆。",
            output_summary=f"命中 {memory_hits} 条记录",
        )
    )
    await report_progress(
        {
            "type": "trace",
            "trace_item": {
                "stage": "memory",
                "title": "读取历史记忆",
                "status": "completed",
                "summary": f"已命中 {memory_hits} 条历史规划或执行记录。",
            },
        }
    )
    await report_progress(
        _progress_status_update(
            stage="planner",
            status="running",
            title="生成命令序列",
            summary="正在调用服务端 LLM 生成可确认的命令序列。",
        )
    )
    await report_progress(
        _progress_tool_call(
            tool_id="plan_with_service_llm",
            tool_name="plan_with_service_llm",
            status="running",
            summary="服务端 LLM 正在分析意图并生成命令。",
            input_summary=f"intent={intent[:48]}",
        )
    )
    await report_progress(
        {
            "type": "trace",
            "trace_item": {
                "stage": "planner",
                "title": "生成命令序列",
                "status": "running",
                "summary": "正在调用服务端 LLM 生成可确认的命令序列。",
            },
        }
    )

    try:
        result = await plan_with_service_llm(
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
            reason=exc.reason,
            message=exc.detail,
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except AssistantPlannerTimeout as exc:
        raise _assistant_error(
            status.HTTP_504_GATEWAY_TIMEOUT,
            reason=exc.reason,
            message=exc.detail,
        ) from exc
    except AssistantPlannerUnavailable as exc:
        status_code = (
            status.HTTP_422_UNPROCESSABLE_ENTITY
            if exc.reason == "service_llm_invalid"
            else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        raise _assistant_error(
            status_code,
            reason=exc.reason,
            message=exc.detail,
        ) from exc

    command_sequence = _validate_command_sequence(result.get("command_sequence"))
    evaluation_context = dict(result.get("evaluation_context") or {})
    if matched_candidate:
        evaluation_context["matched_candidate_id"] = matched_candidate.candidate_id
        evaluation_context["matched_cwd"] = matched_candidate.cwd
        evaluation_context["matched_label"] = matched_candidate.label
    evaluation_context["memory_hits"] = max(
        int(evaluation_context.get("memory_hits", 0) or 0),
        memory_hits,
    )
    evaluation_context.setdefault(
        "tool_calls",
        2 if memory_hits > 0 else 1,
    )
    evaluation_context["fallback_policy"] = _model_dump(request.fallback_policy)

    assistant_messages = [
        _normalize_assistant_message(item)
        for item in (result.get("assistant_messages") or [])
        if isinstance(item, dict)
    ]
    if not assistant_messages:
        assistant_messages = [
            {
                "type": "assistant",
                "text": "我先读取当前设备上下文，再生成可确认的终端命令。",
            }
        ]

    trace = _ensure_assistant_trace(
        [item for item in (result.get("trace") or []) if isinstance(item, dict)],
        matched_candidate=matched_candidate,
        memory_hits=memory_hits,
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

    await report_progress(
        _progress_tool_call(
            tool_id="plan_with_service_llm",
            tool_name="plan_with_service_llm",
            status="completed",
            summary="服务端 LLM 已返回最终命令序列。",
            output_summary=f"生成 {len(command_sequence['steps'])} 步命令",
        )
    )
    await report_progress(
        _progress_status_update(
            stage="planner",
            status="completed",
            title="生成命令序列",
            summary=f"已生成 {len(command_sequence['steps'])} 步命令，可交给用户确认。",
        )
    )
    await report_progress(
        {
            "type": "trace",
            "trace_item": {
                "stage": "planner",
                "title": "生成命令序列",
                "status": "completed",
                "summary": f"已生成 {len(command_sequence['steps'])} 步命令，可交给用户确认。",
            },
        }
    )
    if matched_candidate:
        await report_progress(
            {
                "type": "trace",
                "trace_item": {
                    "stage": "context",
                    "title": "匹配项目",
                    "status": "completed",
                    "summary": f"本轮命中项目 {matched_candidate.label}，目录为 {matched_candidate.cwd}。",
                },
            }
        )
    await report_progress(
        _progress_status_update(
            stage="validation",
            status="completed",
            title="整理执行方案",
            summary=f"已整理终端标题、工作目录和 {len(command_sequence['steps'])} 条执行命令。",
        )
    )
    await report_progress(
        {
            "type": "trace",
            "trace_item": {
                "stage": "validation",
                "title": "整理执行方案",
                "status": "completed",
                "summary": f"已整理终端标题、工作目录和 {len(command_sequence['steps'])} 条执行命令。",
            },
        }
    )
    for message in assistant_messages:
        await report_progress(
            {
                "type": "assistant_message",
                "assistant_message": message,
            }
        )
    for item in trace:
        await report_progress(
            {
                "type": "trace",
                "trace_item": item,
            }
        )

    await save_assistant_planner_run(
        user_id,
        device_id,
        {
            "conversation_id": request.conversation_id,
            "message_id": request.message_id,
            "intent": intent,
            "provider": provider,
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "assistant_messages": assistant_messages,
            "trace": trace,
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
                    device_id=device_id,
                    request=request,
                    http_request=http_request,
                    user_id=user_id,
                    progress_reporter=report_progress,
                )
                await queue.put(
                    {
                        "type": "result",
                        "plan": _model_dump(result),
                    }
                )
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, dict) else {}
                await queue.put(
                    {
                        "type": "error",
                        "reason": detail.get("reason", "assistant_plan_failed"),
                        "message": detail.get("message", "智能规划失败"),
                        "retry_after": int((exc.headers or {}).get("Retry-After", "0") or 0)
                        or None,
                    }
                )
            except Exception:
                await queue.put(
                    {
                        "type": "error",
                        "reason": "assistant_plan_failed",
                        "message": "智能规划执行失败",
                    }
                )
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

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
    )


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
    execution_status = request.execution_status.strip().lower()
    if execution_status not in {"succeeded", "failed", "cancelled"}:
        raise _assistant_error(
            status.HTTP_400_BAD_REQUEST,
            reason="invalid_execution_status",
            message="execution_status 仅支持 succeeded / failed / cancelled",
        )

    session = await get_session_by_device_id(device_id, user_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"device {device_id} 不存在",
        )

    command_sequence = _validate_command_sequence(request.command_sequence)
    existing = await get_assistant_planner_run(
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

    updated = await report_assistant_execution(
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
