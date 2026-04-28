"""
session 子模块 — terminal 关联操作。
"""
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import HTTPException, status

from app.store.session_types import (
    SESSION_TTL_SECONDS,
    KEY_PREFIX,
    _session_key,
    _default_terminal_state,
    _session_locks,
)
from app.store.session_normalize import (
    _normalize_session_data,
    _normalize_session_status,
    _normalize_terminal_status,
    _validate_session_id,
    _validate_terminal_status,
    _reconcile_terminals,
    _trim_terminal_records,
    _clear_terminal_attachment_state,
    _advance_attach_epoch,
    _advance_recovery_epoch,
    _active_terminal_count,
    _resolve_geometry_owner_view,
    is_terminal_recoverable,
)
from app.store.session_redis_conn import redis_conn

logger = logging.getLogger(__name__)


# ─── 内部读写（无锁） ───

async def _get_session_raw(session_id: str) -> dict:
    """内层：不加锁，直接 Redis 读取 + normalize 回写。"""
    redis = await redis_conn.get_redis()
    key = _session_key(session_id)

    data = await redis.get(key)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"会话 {session_id} 不存在",
        )

    raw = json.loads(data)
    session_data = _normalize_session_data(session_id, raw)
    if session_data != raw:
        await redis.set(key, json.dumps(session_data))
    return session_data


async def _save_session(session_id: str, session_data: dict) -> None:
    """内层：直接写入 Redis（调用方需已持有锁）。每次写入自动续期 TTL。"""
    redis = await redis_conn.get_redis()
    await redis.set(_session_key(session_id), json.dumps(session_data), ex=SESSION_TTL_SECONDS)


# ─── terminal CRUD ───

async def list_session_terminals(session_id: str) -> list[dict]:
    """列出 session 下的 terminals（加 per-session 锁）。"""
    _validate_session_id(session_id)
    async with _session_locks.get_lock(session_id):
        session_data = await _get_session_raw(session_id)
        terminals = session_data.get("terminals", [])
        changed = _reconcile_terminals(terminals)
        if changed:
            session_data["updated_at"] = datetime.now(timezone.utc).isoformat()
            await _save_session(session_id, session_data)
        return terminals


async def get_session_terminal(session_id: str, terminal_id: str) -> Optional[dict]:
    """获取 session 下指定 terminal。"""
    terminals = await list_session_terminals(session_id)
    for terminal in terminals:
        if terminal.get("terminal_id") == terminal_id:
            return terminal
    return None


async def list_recoverable_session_terminals(session_id: str) -> list[dict]:
    """列出仍在 grace period 内可恢复的 detached terminals。"""
    terminals = await list_session_terminals(session_id)
    now = datetime.now(timezone.utc)
    return [terminal for terminal in terminals if is_terminal_recoverable(terminal, now=now)]


async def create_session_terminal(
    session_id: str,
    *,
    terminal_id: str,
    title: str,
    cwd: str,
    command: str,
    env: Optional[dict] = None,
    terminal_status: str = "recovering",
) -> dict:
    """在 session 下创建 terminal 记录（加 per-session 锁）。"""
    _validate_session_id(session_id)
    _validate_terminal_status(terminal_status)
    normalized_terminal_status = _normalize_terminal_status(terminal_status)

    async with _session_locks.get_lock(session_id):
        session_data = await _get_session_raw(session_id)
        terminals = session_data["terminals"]
        changed = _reconcile_terminals(terminals)
        if changed:
            session_data["updated_at"] = datetime.now(timezone.utc).isoformat()

        if any(terminal.get("terminal_id") == terminal_id for terminal in terminals):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"terminal {terminal_id} 已存在",
            )

        max_terminals = session_data["device"]["max_terminals"]
        if _active_terminal_count(terminals) >= max_terminals:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="terminal 数量已达上限",
            )

        terminal = _default_terminal_state(
            terminal_id,
            title=title,
            cwd=cwd,
            command=command,
            env=env,
            pty=session_data.get("pty"),
            status=normalized_terminal_status,
        )
        terminals.append(terminal)
        _trim_terminal_records(terminals)
        session_data["updated_at"] = datetime.now(timezone.utc).isoformat()

        await _save_session(session_id, session_data)
        return terminal


async def update_session_terminal_status(
    session_id: str,
    terminal_id: str,
    *,
    terminal_status: str,
    disconnect_reason: Optional[str] = None,
    grace_seconds: Optional[int] = None,
) -> dict:
    """更新指定 terminal 的状态（加 per-session 锁）。"""
    _validate_session_id(session_id)
    _validate_terminal_status(terminal_status)
    normalized_terminal_status = _normalize_terminal_status(terminal_status)

    async with _session_locks.get_lock(session_id):
        session_data = await _get_session_raw(session_id)
        terminals = session_data["terminals"]

        for terminal in terminals:
            if terminal.get("terminal_id") == terminal_id:
                terminal["status"] = normalized_terminal_status
                terminal["disconnect_reason"] = disconnect_reason
                terminal["grace_expires_at"] = (
                    datetime.now(timezone.utc) + timedelta(seconds=grace_seconds)
                ).isoformat() if grace_seconds else None
                if normalized_terminal_status == "closed":
                    _clear_terminal_attachment_state(terminal)
                    terminal["grace_expires_at"] = None
                if normalized_terminal_status == "recovering":
                    _advance_recovery_epoch(terminal)
                terminal["updated_at"] = datetime.now(timezone.utc).isoformat()
                _trim_terminal_records(terminals)
                session_data["updated_at"] = datetime.now(timezone.utc).isoformat()
                await _save_session(session_id, session_data)
                return terminal

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"terminal {terminal_id} 不存在",
        )


async def update_session_terminal_views(
    session_id: str,
    terminal_id: str,
    *,
    views: dict[str, int],
    preferred_owner_view: Optional[str] = None,
) -> dict:
    """同步 terminal 级 views，并据此收敛 live/detached_recoverable 状态。"""
    _validate_session_id(session_id)

    normalized_views = {
        "mobile": max(0, int(views.get("mobile", 0))),
        "desktop": max(0, int(views.get("desktop", 0))),
    }
    total_views = normalized_views["mobile"] + normalized_views["desktop"]

    async with _session_locks.get_lock(session_id):
        session_data = await _get_session_raw(session_id)
        terminals = session_data["terminals"]

        for terminal in terminals:
            if terminal.get("terminal_id") != terminal_id:
                continue

            previous_total_views = sum((terminal.get("views") or {}).values())
            terminal["views"] = normalized_views
            terminal["geometry_owner_view"] = _resolve_geometry_owner_view(
                terminal,
                normalized_views,
                preferred_owner_view=preferred_owner_view,
            )
            if terminal.get("status") != "closed":
                terminal["status"] = "live" if total_views > 0 else "detached_recoverable"
                if total_views > 0 and previous_total_views <= 0:
                    _advance_attach_epoch(terminal)
                    _advance_recovery_epoch(terminal)
            if terminal.get("status") == "closed":
                _clear_terminal_attachment_state(terminal)
            terminal["updated_at"] = datetime.now(timezone.utc).isoformat()
            session_data["updated_at"] = datetime.now(timezone.utc).isoformat()
            await _save_session(session_id, session_data)
            return terminal

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"terminal {terminal_id} 不存在",
        )


async def update_session_terminal_pty(
    session_id: str,
    terminal_id: str,
    *,
    rows: int,
    cols: int,
) -> dict:
    """同步 terminal 级 PTY 尺寸。"""
    _validate_session_id(session_id)

    normalized_pty = {
        "rows": max(1, int(rows)),
        "cols": max(1, int(cols)),
    }

    async with _session_locks.get_lock(session_id):
        session_data = await _get_session_raw(session_id)
        terminals = session_data["terminals"]

        for terminal in terminals:
            if terminal.get("terminal_id") != terminal_id:
                continue

            terminal["pty"] = normalized_pty
            terminal["updated_at"] = datetime.now(timezone.utc).isoformat()
            session_data["updated_at"] = datetime.now(timezone.utc).isoformat()
            await _save_session(session_id, session_data)
            return terminal

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"terminal {terminal_id} 不存在",
        )


async def update_session_terminal_metadata(
    session_id: str,
    terminal_id: str,
    *,
    title: Optional[str] = None,
    cwd: Optional[str] = None,
    command: Optional[str] = None,
) -> dict:
    """更新指定 terminal 的元数据（加 per-session 锁）。"""
    _validate_session_id(session_id)

    async with _session_locks.get_lock(session_id):
        session_data = await _get_session_raw(session_id)
        terminals = session_data["terminals"]

        for terminal in terminals:
            if terminal.get("terminal_id") == terminal_id:
                if title is not None:
                    terminal["title"] = title
                if cwd is not None:
                    terminal["cwd"] = cwd
                if command is not None:
                    terminal["command"] = command
                terminal["updated_at"] = datetime.now(timezone.utc).isoformat()
                session_data["updated_at"] = datetime.now(timezone.utc).isoformat()
                await _save_session(session_id, session_data)
                return terminal

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"terminal {terminal_id} 不存在",
        )


async def bulk_update_session_terminals(
    session_id: str,
    *,
    from_statuses: Optional[set[str]] = None,
    to_status: str,
    disconnect_reason: Optional[str] = None,
    grace_seconds: Optional[int] = None,
) -> dict:
    """批量更新 session 下 terminals 的状态（加 per-session 锁）。"""
    _validate_session_id(session_id)
    _validate_terminal_status(to_status)
    normalized_to_status = _normalize_terminal_status(to_status)
    normalized_from_statuses = (
        {_normalize_terminal_status(value) for value in from_statuses}
        if from_statuses is not None
        else None
    )

    async with _session_locks.get_lock(session_id):
        session_data = await _get_session_raw(session_id)
        terminals = session_data["terminals"]
        changed = 0
        now = datetime.now(timezone.utc).isoformat()

        for terminal in terminals:
            current_status = terminal.get("status", "pending")
            current_status = _normalize_terminal_status(current_status)
            if normalized_from_statuses is not None and current_status not in normalized_from_statuses:
                continue
            terminal["status"] = normalized_to_status
            terminal["disconnect_reason"] = disconnect_reason
            terminal["grace_expires_at"] = (
                datetime.now(timezone.utc) + timedelta(seconds=grace_seconds)
            ).isoformat() if grace_seconds else None
            if normalized_to_status == "closed":
                _clear_terminal_attachment_state(terminal)
                terminal["grace_expires_at"] = None
            if normalized_to_status == "recovering":
                _advance_recovery_epoch(terminal)
            terminal["updated_at"] = now
            changed += 1

        session_data["updated_at"] = now
        await _save_session(session_id, session_data)
        return {"changed": changed, "terminals": terminals}
