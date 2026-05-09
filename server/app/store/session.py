"""
Redis 会话存储服务 — 协调入口。

从子模块导入并 re-export，保证 ``from app.store.session import X`` 不变。
"""
import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import HTTPException, status
import redis.asyncio as aioredis  # noqa: F401 — 兼容测试 patch("app.store.session.aioredis")

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
    _user_sessions_key,
    _USER_SESSIONS_PREFIX,
    _device_session_key,
    _DEVICE_SESSION_PREFIX,
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


# ─── user_id 反向索引 ───


async def backfill_user_session_index() -> int:
    """启动时遍历全部 session，构建 user_id → session_ids 反向索引。

    返回 backfill 的 session 数量。
    Redis 不可用时抛出 503（fail-closed）。
    """
    redis = await redis_conn.get_redis()
    pattern = f"{KEY_PREFIX}:*"
    cursor = 0
    count = 0

    # 先清理旧索引
    idx_cursor = 0
    while True:
        idx_cursor, idx_keys = await redis.scan(idx_cursor, match=f"{_USER_SESSIONS_PREFIX}*", count=100)
        if idx_keys:
            await redis.delete(*idx_keys)
        if idx_cursor == 0:
            break

    while True:
        cursor, keys = await redis.scan(cursor, match=pattern, count=100)
        for key in keys:
            data = await redis.get(key)
            if not data:
                continue
            session_data = json.loads(data)
            uid = session_data.get("user_id")
            if uid:
                await redis.sadd(_user_sessions_key(uid), key.replace(f"{KEY_PREFIX}:", ""))
                count += 1
        if cursor == 0:
            break

    if count > 0:
        logger.info("User session index backfilled: %d sessions indexed", count)
    return count


async def _ensure_user_index(redis, user_id: str) -> None:
    """lazy self-heal：如果反向索引不存在（空），走 SCAN 补齐后写入索引。"""
    idx_key = _user_sessions_key(user_id)
    exists = await redis.exists(idx_key)
    if exists:
        return

    # index 缺失，走 SCAN 补齐
    pattern = f"{KEY_PREFIX}:*"
    cursor = 0
    session_ids: list[str] = []
    while True:
        cursor, keys = await redis.scan(cursor, match=pattern, count=100)
        for key in keys:
            session_id = key.replace(f"{KEY_PREFIX}:", "")
            data = await redis.get(key)
            if not data:
                continue
            session_data = json.loads(data)
            if session_data.get("user_id") == user_id:
                session_ids.append(session_id)
        if cursor == 0:
            break

    if session_ids:
        await redis.sadd(idx_key, *session_ids)
        logger.info("Lazy self-heal: indexed %d sessions for user %s", len(session_ids), user_id)
    else:
        # 即使没有 session 也标记索引存在，避免反复 SCAN
        await redis.sadd(idx_key, "__empty__")


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
                        normalized, _ = _normalize_session_data(session_id, session_data)
                        return {"id": session_id, **normalized}
        if cursor == 0:
            break
    return None


async def list_sessions_for_user(user_id: str) -> list[dict]:
    """列出某个用户拥有的全部 session。使用 pipeline 批量读取优化 N+1 问题。"""
    if not user_id:
        return []

    redis = await redis_conn.get_redis()

    # lazy self-heal：确保索引存在
    await _ensure_user_index(redis, user_id)

    idx_key = _user_sessions_key(user_id)
    session_ids = await redis.smembers(idx_key)

    # 过滤占位符
    session_ids = {sid for sid in session_ids if sid != "__empty__"}

    if not session_ids:
        return []

    # Pipeline 批量读取所有 session 数据（1 次 Redis 调用）
    keys = [_session_key(sid) for sid in session_ids]
    try:
        pipe = redis.pipeline(transaction=False)
        for key in keys:
            pipe.get(key)
        raw_values = await pipe.execute()
    except (AttributeError, TypeError):
        # fallback：逐个读取（兼容测试 mock 中 pipeline 不可用的情况）
        raw_values = await asyncio.gather(*(redis.get(k) for k in keys))

    sessions: list[dict] = []
    stale_ids: list[str] = []

    for session_id, raw in zip(session_ids, raw_values):
        if raw is None:
            stale_ids.append(session_id)
            continue
        session_data = json.loads(raw)
        changed = _reconcile_terminals(session_data.get("terminals", []))
        if changed:
            session_data["updated_at"] = datetime.now(timezone.utc).isoformat()
            # 批量保存变更的 session
            try:
                async with _session_locks.get_lock(session_id):
                    await _save_session(session_id, session_data)
            except HTTPException:
                stale_ids.append(session_id)
                continue
        sessions.append({"session_id": session_id, **session_data})

    # 清理已删除的 session 索引
    if stale_ids:
        await redis.srem(idx_key, *stale_ids)

    return sessions


async def get_session_by_device_id(device_id: str, user_id: Optional[str] = None) -> Optional[dict]:
    """通过 device_id 查找 session。优先使用 device_id 反向索引 O(1)，未命中时 fallback SCAN。"""
    if not device_id:
        return None

    redis = await redis_conn.get_redis()

    # 优先使用 device_id 反向索引（O(1)）
    idx_key = _device_session_key(device_id)
    session_id_raw = await redis.get(idx_key)
    if session_id_raw:
        sid = session_id_raw if isinstance(session_id_raw, str) else session_id_raw.decode()
        try:
            async with _session_locks.get_lock(sid):
                session_data = await _get_session_raw(sid)
            return {"session_id": sid, **session_data}
        except HTTPException:
            # session 已删除，清理索引
            await redis.delete(idx_key)

    # 有 user_id 时尝试在用户 session 中查找
    if user_id:
        sessions = await list_sessions_for_user(user_id)
        for session in sessions:
            if session.get("device", {}).get("device_id") == device_id:
                # 回填索引
                sid = session.get("session_id") or session.get("id")
                if sid:
                    await redis.set(idx_key, sid, ex=SESSION_TTL_SECONDS)
                return session
        return None

    # Fallback：SCAN 全库（索引缺失且无 user_id）
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
                session_data, norm_changed = _normalize_session_data(session_id, json.loads(data))
                changed = _reconcile_terminals(session_data.get("terminals", []))
                if changed or norm_changed:
                    session_data["updated_at"] = datetime.now(timezone.utc).isoformat()
                    await redis.set(key, json.dumps(session_data))
                if session_data.get("device", {}).get("device_id") == device_id:
                    # 回填索引
                    await redis.set(idx_key, session_id, ex=SESSION_TTL_SECONDS)
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
