"""
Redis 会话存储服务 — 协调入口。

从子模块导入并 re-export，保证 ``from app.store.session import X`` 不变。
"""
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import HTTPException, status

# ─── 子模块 re-export ───

# session_types: 常量 + 键名 + 默认状态 + Lock 管理器
from app.store.session_types import (  # noqa: F401
    REDIS_URL,
    REDIS_PASSWORD,
    HISTORY_TTL_DAYS,
    DEFAULT_MAX_TERMINALS,
    MAX_TERMINAL_RECORDS,
    SESSION_TTL_SECONDS,
    SESSION_STATES,
    TERMINAL_STATES,
    KEY_PREFIX,
    HISTORY_KEY_PREFIX,
    _session_key,
    _history_key,
    _default_device_state,
    _default_terminal_state,
    _SessionLockManager,
    _session_locks,
)

# session_redis_conn: Redis 连接
from app.store.session_redis_conn import (  # noqa: F401
    RedisConnection,
    redis_conn,
    get_redis,
)

# session_normalize: 规范化 / 验证 / terminal 辅助
from app.store.session_normalize import (  # noqa: F401
    _normalize_session_status,
    _normalize_terminal_status,
    _validate_terminal_status,
    _validate_session_status,
    _validate_session_id,
    _normalize_session_data,
    _active_terminal_count,
    _terminal_updated_at,
    _trim_terminal_records,
    _close_expired_detached_terminals,
    _backfill_terminal_views,
    _resolve_geometry_owner_view,
    _clear_terminal_attachment_state,
    _advance_attach_epoch,
    _advance_recovery_epoch,
    _reconcile_terminals,
    is_terminal_recoverable,
)

# session_history: output history CRUD
from app.store.session_history import (  # noqa: F401
    append_history,
    get_history,
    get_terminal_output_history,
    get_history_count,
    cleanup_old_history,
)

# session_terminal: terminal 关联操作（含 _get_session_raw / _save_session）
from app.store.session_terminal import (  # noqa: F401
    _get_session_raw,
    _save_session,
    list_session_terminals,
    get_session_terminal,
    list_recoverable_session_terminals,
    create_session_terminal,
    update_session_terminal_status,
    update_session_terminal_views,
    update_session_terminal_pty,
    update_session_terminal_metadata,
    bulk_update_session_terminals,
)

# session_crud: session 级 CRUD
from app.store.session_crud import (  # noqa: F401
    create_session,
    cleanup_user_sessions,
    get_session,
    verify_session_ownership,
    update_session_status,
    update_session_agent_online,
    update_session_view_count,
    update_session_pty_size,
    update_session_device_metadata,
    update_session_device_heartbeat,
)

logger = logging.getLogger(__name__)


# ─── SCAN 查询（需要 KEY_PREFIX / json / normalize 等多项依赖） ───


async def get_session_by_name(name: str) -> Optional[dict]:
    """
    通过名称查找会话

    优先使用反向索引 O(1) 查找，向后兼容 SCAN 回退。
    """
    if not name:
        return None

    redis = await redis_conn.get_redis()

    # 优先使用反向索引（O(1)）
    name_key = f"rc:session_name_idx:{name}"
    session_id_raw = await redis.get(name_key)
    if session_id_raw:
        sid = session_id_raw if isinstance(session_id_raw, str) else session_id_raw.decode()
        try:
            async with _session_locks.get_lock(sid):
                session_data = await _get_session_raw(sid)
            return {"id": sid, **session_data}
        except HTTPException:
            await redis.delete(name_key)

    # 回退：SCAN 遍历（兼容旧 session）
    pattern = f"{KEY_PREFIX}:*"
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match=pattern, count=100)
        for key in keys:
            session_id = key.replace(f"{KEY_PREFIX}:", "")
            async with _session_locks.get_lock(session_id):
                data = await redis.get(key)
                if data:
                    session_data = json.loads(data)
                    if session_data.get("name") == name:
                        return {"id": session_id, **_normalize_session_data(session_id, session_data)}
        if cursor == 0:
            break
    return None


async def list_sessions_for_user(user_id: str) -> list[dict]:
    """列出某个用户拥有的全部 session。"""
    if not user_id:
        return []

    redis = await redis_conn.get_redis()
    pattern = f"{KEY_PREFIX}:*"
    cursor = 0
    sessions: list[dict] = []

    while True:
        cursor, keys = await redis.scan(cursor, match=pattern, count=100)
        for key in keys:
            session_id = key.replace(f"{KEY_PREFIX}:", "")
            async with _session_locks.get_lock(session_id):
                data = await redis.get(key)
                if not data:
                    continue
                session_data = _normalize_session_data(session_id, json.loads(data))
                changed = _reconcile_terminals(session_data.get("terminals", []))
                if changed:
                    session_data["updated_at"] = datetime.now(timezone.utc).isoformat()
                    await redis.set(key, json.dumps(session_data))
                if session_data.get("user_id") == user_id:
                    sessions.append({"session_id": session_id, **session_data})
        if cursor == 0:
            break
    return sessions


async def get_session_by_device_id(device_id: str, user_id: Optional[str] = None) -> Optional[dict]:
    """通过 device_id 查找 session。"""
    if not device_id:
        return None

    sessions = await list_sessions_for_user(user_id) if user_id else []
    if user_id:
        for session in sessions:
            if session.get("device", {}).get("device_id") == device_id:
                return session
        return None

    redis = await redis_conn.get_redis()
    pattern = f"{KEY_PREFIX}:*"
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match=pattern, count=100)
        for key in keys:
            session_id = key.replace(f"{KEY_PREFIX}:", "")
            async with _session_locks.get_lock(session_id):
                data = await redis.get(key)
                if not data:
                    continue
                session_data = _normalize_session_data(session_id, json.loads(data))
                changed = _reconcile_terminals(session_data.get("terminals", []))
                if changed:
                    session_data["updated_at"] = datetime.now(timezone.utc).isoformat()
                    await redis.set(key, json.dumps(session_data))
                if session_data.get("device", {}).get("device_id") == device_id:
                    return {"session_id": session_id, **session_data}
        if cursor == 0:
            break
    return None


# ─── 组合操作（单次锁内完成多步更新） ───


async def set_session_online(session_id: str) -> dict:
    """原子操作：device_state=online + agent_online=True"""
    _validate_session_id(session_id)
    async with _session_locks.get_lock(session_id):
        session_data = await _get_session_raw(session_id)
        session_data["status"] = "online"
        session_data["agent_online"] = True
        session_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        await _save_session(session_id, session_data)
        logger.info("Session online: session_id=%s", session_id)
        return session_data


async def set_session_offline_recoverable(
    session_id: str,
    *,
    reason: str = "device_offline",
    grace_seconds: int = 90,
) -> dict:
    """原子操作：status=offline_recoverable + agent_online=False + terminals detached_recoverable。"""
    _validate_session_id(session_id)
    async with _session_locks.get_lock(session_id):
        session_data = await _get_session_raw(session_id)
        now = datetime.now(timezone.utc).isoformat()
        session_data["status"] = "offline_recoverable"
        session_data["agent_online"] = False
        for terminal in session_data.get("terminals", []):
            if terminal.get("status") != "closed":
                terminal["status"] = "detached_recoverable"
                terminal["disconnect_reason"] = reason
                _clear_terminal_attachment_state(terminal)
                terminal["grace_expires_at"] = (
                    datetime.now(timezone.utc) + timedelta(seconds=grace_seconds)
                ).isoformat()
                terminal["updated_at"] = now
        session_data["updated_at"] = now
        await _save_session(session_id, session_data)
        logger.info("Session offline_recoverable: session_id=%s reason=%s", session_id, reason)
        return session_data


async def set_session_offline(session_id: str, *, reason: str = "device_offline") -> dict:
    """原子操作：status=offline_expired + agent_online=False + bulk close terminals"""
    _validate_session_id(session_id)
    async with _session_locks.get_lock(session_id):
        session_data = await _get_session_raw(session_id)
        now = datetime.now(timezone.utc).isoformat()
        session_data["status"] = "offline_expired"
        session_data["agent_online"] = False
        for terminal in session_data.get("terminals", []):
            if terminal.get("status") != "closed":
                terminal["status"] = "closed"
                terminal["disconnect_reason"] = reason
                _clear_terminal_attachment_state(terminal)
                terminal["grace_expires_at"] = None
                terminal["updated_at"] = now
        session_data["updated_at"] = now
        await _save_session(session_id, session_data)
        logger.info("Session offline_expired: session_id=%s reason=%s", session_id, reason)
        return session_data
