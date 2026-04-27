"""
Project Context REST API — 项目上下文候选、设置 CRUD。
"""
import hashlib
import os
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status, Depends
import logging

from app.infra.auth import get_current_user_id
from app.api import _deps
from app.api._helpers import model_dump as _model_dump, json_loads as _json_loads
from app.api.schemas import (
    ApprovedScanRootItem,
    DeviceProjectContextSnapshot,
    PinnedProjectItem,
    PlannerRuntimeConfig,
    ProjectContextCandidate,
    ProjectContextSettingsResponse,
    UpdateProjectContextSettingsRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


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
    terminals = await _deps.list_session_terminals(session["session_id"])
    pinned_projects = await _deps.get_pinned_projects(user_id, device_id)
    await _deps.get_approved_scan_roots(user_id, device_id)

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

    # 升级旧版本默认值：此前默认关闭智能规划，这会让"一句话创建"看起来始终像规则兜底。
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
    pinned_projects = await _deps.get_pinned_projects(user_id, device_id)
    scan_roots = await _deps.get_approved_scan_roots(user_id, device_id)
    planner_config = await _deps.get_planner_config(user_id, device_id)

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


async def _get_or_refresh_project_context(
    device_id: str,
    user_id: str,
) -> DeviceProjectContextSnapshot:
    """获取/刷新项目候选摘要快照的共享实现。"""
    session = await _deps.get_session_by_device_id(device_id, user_id)
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
    session = await _deps.get_session_by_device_id(device_id, user_id)
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
    session = await _deps.get_session_by_device_id(device_id, user_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"device {device_id} 不存在",
        )

    await _deps.replace_pinned_projects(
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
    await _deps.replace_approved_scan_roots(
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
    await _deps.save_planner_config(
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
