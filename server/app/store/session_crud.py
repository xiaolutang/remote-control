"""
session 子模块 — session 级 CRUD 操作（创建、更新、清理）。
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status

from app.store.session_types import (
    SESSION_TTL_SECONDS,
    _session_key,
    _default_device_state,
    _session_locks,
)
from app.store.session_normalize import (
    _normalize_session_status,
    _validate_session_status,
    _validate_session_id,
)
from app.store.session_redis_conn import redis_conn
from app.store.session_terminal import _get_session_raw, _save_session

logger = logging.getLogger(__name__)


async def create_session(
    session_id: Optional[str] = None,
    name: Optional[str] = None,
    user_id: Optional[str] = None,
    owner: Optional[str] = None,
) -> dict:
    """创建会话。"""
    from app.infra.auth import generate_session_id

    if not session_id:
        session_id = generate_session_id()

    _validate_session_id(session_id)

    redis = await redis_conn.get_redis()
    key = _session_key(session_id)

    existing = await redis.exists(key)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"会话 {session_id} 已存在",
        )

    now = datetime.now(timezone.utc)
    session_data = {
        "status": "pending",
        "created_at": now.isoformat(),
        "name": name or "",
        "user_id": user_id or "",
        "owner": owner or user_id or "",
        "agent_online": False,
        "views": {"mobile": 0, "desktop": 0},
        "pty": {"rows": 24, "cols": 80},
        "device": _default_device_state(session_id),
    }

    await redis.set(key, json.dumps(session_data), ex=SESSION_TTL_SECONDS)

    if name:
        name_key = f"rc:session_name_idx:{name}"
        await redis.set(name_key, session_id, ex=SESSION_TTL_SECONDS)

    logger.info("Session created: session_id=%s owner=%s", session_id, owner or user_id)

    return {
        "session_id": session_id,
        "status": "pending",
        "created_at": session_data["created_at"],
        "user_id": user_id,
        "owner": session_data["owner"],
    }


async def cleanup_user_sessions(user_id: str, keep_session_id: Optional[str] = None) -> int:
    """清理用户的所有旧 session（保留 keep_session_id 指定的）。返回删除数量。"""
    if not user_id:
        return 0

    from app.store.session import list_sessions_for_user

    redis = await redis_conn.get_redis()
    sessions = await list_sessions_for_user(user_id)
    deleted = 0

    for session in sessions:
        sid = session.get("session_id") or session.get("id")
        if sid == keep_session_id:
            continue
        name = session.get("name", "")
        if name:
            await redis.delete(f"rc:session_name_idx:{name}")
        await redis.delete(_session_key(sid))
        deleted += 1

    if deleted > 0:
        logger.info("Cleaned up %d stale session(s) for user %s", deleted, user_id)

    return deleted


async def get_session(session_id: str) -> dict:
    """获取会话信息（公开 API，加 per-session 锁）。"""
    _validate_session_id(session_id)
    async with _session_locks.get_lock(session_id):
        return await _get_session_raw(session_id)


async def verify_session_ownership(session_id: str, user_id: str) -> dict:
    """验证 Session 归属。"""
    session = await get_session(session_id)
    if not session.get("user_id"):
        return session
    if session.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问此 Session",
        )
    return session


async def update_session_status(session_id: str, new_status: str) -> dict:
    """更新会话状态（加 per-session 锁）。"""
    _validate_session_id(session_id)
    _validate_session_status(new_status)

    async with _session_locks.get_lock(session_id):
        session_data = await _get_session_raw(session_id)
        session_data["status"] = _normalize_session_status(new_status)
        session_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        await _save_session(session_id, session_data)
        return session_data


async def update_session_agent_online(
    session_id: str,
    online: bool,
    pty_rows: Optional[int] = None,
    pty_cols: Optional[int] = None,
) -> dict:
    """更新会话的 agent_online 状态（加 per-session 锁）。"""
    _validate_session_id(session_id)

    async with _session_locks.get_lock(session_id):
        session_data = await _get_session_raw(session_id)
        session_data["agent_online"] = online
        session_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        if pty_rows is not None and pty_cols is not None:
            session_data["pty"] = {"rows": pty_rows, "cols": pty_cols}
        await _save_session(session_id, session_data)
        return session_data


async def update_session_view_count(session_id: str, view_type: str, delta: int) -> dict:
    """更新会话的视图连接数（加 per-session 锁）。"""
    _validate_session_id(session_id)

    if view_type not in ["mobile", "desktop"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效的视图类型: {view_type}",
        )

    async with _session_locks.get_lock(session_id):
        session_data = await _get_session_raw(session_id)
        if "views" not in session_data:
            session_data["views"] = {"mobile": 0, "desktop": 0}
        session_data["views"][view_type] = max(0, session_data["views"].get(view_type, 0) + delta)
        session_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        await _save_session(session_id, session_data)
        return session_data


async def update_session_pty_size(session_id: str, rows: int, cols: int) -> dict:
    """更新会话的 PTY 尺寸（加 per-session 锁）。"""
    _validate_session_id(session_id)

    async with _session_locks.get_lock(session_id):
        session_data = await _get_session_raw(session_id)
        session_data["pty"] = {"rows": rows, "cols": cols}
        session_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        await _save_session(session_id, session_data)
        return session_data


async def update_session_device_metadata(
    session_id: str,
    *,
    device_id: Optional[str] = None,
    name: Optional[str] = None,
    platform: Optional[str] = None,
    hostname: Optional[str] = None,
    max_terminals: Optional[int] = None,
    online: Optional[bool] = None,
) -> dict:
    """更新 session 下的 device 元数据（加 per-session 锁）。"""
    _validate_session_id(session_id)
    if max_terminals is not None and max_terminals <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="max_terminals 必须大于 0",
        )

    async with _session_locks.get_lock(session_id):
        session_data = await _get_session_raw(session_id)
        device = session_data["device"]

        if device_id is not None:
            device["device_id"] = device_id
        if name is not None:
            device["name"] = name
        if platform is not None:
            device["platform"] = platform
        if hostname is not None:
            device["hostname"] = hostname
        if max_terminals is not None:
            device["max_terminals"] = max_terminals
            device["max_terminals_configured"] = True
        if online is not None:
            session_data["agent_online"] = online

        session_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        await _save_session(session_id, session_data)
        return session_data


async def update_session_device_heartbeat(
    session_id: str,
    *,
    online: bool = True,
) -> dict:
    """更新 device 心跳时间与在线状态（加 per-session 锁）。"""
    _validate_session_id(session_id)

    async with _session_locks.get_lock(session_id):
        session_data = await _get_session_raw(session_id)
        session_data["agent_online"] = online
        session_data["device"]["last_heartbeat_at"] = datetime.now(timezone.utc).isoformat()
        session_data["updated_at"] = datetime.now(timezone.utc).isoformat()

        await _save_session(session_id, session_data)

        name = session_data.get("name", "")
        if name:
            redis = await redis_conn.get_redis()
            await redis.expire(f"rc:session_name_idx:{name}", SESSION_TTL_SECONDS)

        return session_data
