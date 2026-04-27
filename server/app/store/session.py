"""
Redis 会话存储服务
"""
import os
import json
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
import redis.asyncio as aioredis
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

# 配置
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
HISTORY_TTL_DAYS = int(os.getenv("HISTORY_TTL_DAYS", "7"))  # 历史记录保留天数
DEFAULT_MAX_TERMINALS = int(os.getenv("DEFAULT_MAX_TERMINALS", "3"))
MAX_TERMINAL_RECORDS = int(os.getenv("MAX_TERMINAL_RECORDS", "5"))
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", str(24 * 60 * 60)))  # session 默认 24h 过期

SESSION_STATES = {
    "pending",
    "online",
    "offline_recoverable",
    "offline_expired",
}

TERMINAL_STATES = {
    "recovering",
    "live",
    "detached_recoverable",
    "closed",
}

# 键名前缀
KEY_PREFIX = "rc:session"
HISTORY_KEY_PREFIX = "rc:history"


class _SessionLockManager:
    """per-session asyncio.Lock 管理器，确保同一 session 的 read-modify-write 原子化。

    锁对象在无人持有时由 GC 自动回收（WeakValueDictionary）。
    注意：asyncio.Lock 必须在事件循环中创建，不能跨线程共享。
    """

    def __init__(self):
        import weakref
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

    def get_lock(self, session_id: str) -> asyncio.Lock:
        lock = self._locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        return lock


_session_locks = _SessionLockManager()


class RedisConnection:
    """Redis 连接管理"""

    def __init__(self):
        self._pool: Optional[aioredis.Redis] = None
        self._redis: Optional[aioredis.Redis] = None

    async def get_redis(self) -> aioredis.Redis:
        """获取 Redis 连接"""
        if self._redis is None:
            try:
                self._pool = aioredis.ConnectionPool.from_url(
                    REDIS_URL,
                    password=REDIS_PASSWORD,
                    decode_responses=True,
                    max_connections=10,
                )
                self._redis = aioredis.Redis(connection_pool=self._pool)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Redis 连接失败: {e}",
                )
        return self._redis

    async def close(self):
        """关闭连接"""
        if self._pool:
            await self._pool.disconnect()


# 全局连接实例
redis_conn = RedisConnection()


async def get_redis():
    """获取 Redis 连接（模块级函数）"""
    return await redis_conn.get_redis()


def _session_key(session_id: str) -> str:
    """生成 session 存储键"""
    return f"{KEY_PREFIX}:{session_id}"


def _history_key(session_id: str) -> str:
    """生成 history 存储键"""
    return f"{HISTORY_KEY_PREFIX}:{session_id}"


def _default_device_state(session_id: str) -> dict:
    """生成默认 device 状态。"""
    return {
        "device_id": session_id,
        "name": "",
        "platform": "",
        "hostname": "",
        "max_terminals": DEFAULT_MAX_TERMINALS,
        "max_terminals_configured": False,
        "last_heartbeat_at": None,
    }


def _default_terminal_state(
    terminal_id: str,
    *,
    title: str,
    cwd: str,
    command: str,
    env: Optional[dict] = None,
    pty: Optional[dict] = None,
    status: str = "recovering",
) -> dict:
    """生成默认 terminal 状态。"""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "terminal_id": terminal_id,
        "title": title,
        "cwd": cwd,
        "command": command,
        "env": env or {},
        "status": status,
        "disconnect_reason": None,
        "grace_expires_at": None,
        "views": {"mobile": 0, "desktop": 0},
        "geometry_owner_view": None,
        "attach_epoch": 0,
        "recovery_epoch": 0,
        "pty": {
            "rows": max(1, int((pty or {}).get("rows", 24))),
            "cols": max(1, int((pty or {}).get("cols", 80))),
        },
        "created_at": now,
        "updated_at": now,
    }


def _normalize_session_data(session_id: str, session_data: dict) -> dict:
    """兼容旧 session 结构，补齐 device 相关字段。"""
    normalized = dict(session_data)
    normalized.setdefault("status", "pending")
    normalized["status"] = _normalize_session_status(normalized["status"])
    normalized.setdefault("agent_online", False)
    normalized.setdefault("views", {"mobile": 0, "desktop": 0})
    normalized.setdefault("pty", {"rows": 24, "cols": 80})
    normalized.setdefault("terminals", [])
    normalized_terminal_pty = {
        "rows": max(1, int(normalized["pty"].get("rows", 24))),
        "cols": max(1, int(normalized["pty"].get("cols", 80))),
    }
    normalized["pty"] = normalized_terminal_pty

    normalized_terminals = []
    for terminal in normalized["terminals"]:
        terminal_copy = dict(terminal)
        terminal_copy["status"] = _normalize_terminal_status(terminal_copy.get("status", "recovering"))
        terminal_copy.setdefault("views", {"mobile": 0, "desktop": 0})
        owner_view = terminal_copy.get("geometry_owner_view")
        terminal_copy["geometry_owner_view"] = (
            owner_view if owner_view in {"mobile", "desktop"} else None
        )
        terminal_copy["attach_epoch"] = max(0, int(terminal_copy.get("attach_epoch", 0) or 0))
        terminal_copy["recovery_epoch"] = max(0, int(terminal_copy.get("recovery_epoch", 0) or 0))
        terminal_copy["pty"] = {
            "rows": max(
                1,
                int((terminal_copy.get("pty") or normalized_terminal_pty).get("rows", 24)),
            ),
            "cols": max(
                1,
                int((terminal_copy.get("pty") or normalized_terminal_pty).get("cols", 80)),
            ),
        }
        normalized_terminals.append(terminal_copy)
    normalized["terminals"] = normalized_terminals

    device = dict(normalized.get("device") or {})
    defaults = _default_device_state(session_id)
    for key, value in defaults.items():
        device.setdefault(key, value)
    if not device.get("max_terminals_configured", False):
        device["max_terminals"] = DEFAULT_MAX_TERMINALS
    normalized["device"] = device

    return normalized


def _normalize_session_status(session_status: str) -> str:
    legacy_map = {
        "offline": "offline_expired",
    }
    return legacy_map.get(session_status, session_status if session_status in SESSION_STATES else "pending")


def _normalize_terminal_status(terminal_status: str) -> str:
    legacy_map = {
        "pending": "recovering",
        "attached": "live",
        "detached": "detached_recoverable",
        "closing": "detached_recoverable",
    }
    normalized = legacy_map.get(terminal_status, terminal_status)
    return normalized if normalized in TERMINAL_STATES else "recovering"


def _validate_terminal_status(terminal_status: str) -> None:
    """验证 terminal 状态。"""
    if terminal_status not in TERMINAL_STATES and terminal_status not in {
        "pending",
        "attached",
        "detached",
        "closing",
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效的 terminal 状态: {terminal_status}",
        )


def _validate_session_status(session_status: str) -> None:
    if session_status not in SESSION_STATES and session_status != "offline":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效状态: {session_status}",
        )


def _active_terminal_count(terminals: list[dict]) -> int:
    """统计占用 terminal 名额的实例数。"""
    return sum(1 for terminal in terminals if terminal.get("status") != "closed")


def _terminal_updated_at(terminal: dict) -> str:
    return terminal.get("updated_at") or terminal.get("created_at") or ""


def _trim_terminal_records(terminals: list[dict], limit: int = MAX_TERMINAL_RECORDS) -> int:
    """只保留最近的少量 terminal 记录，优先保留未关闭终端。"""
    if len(terminals) <= limit:
        return 0

    active = sorted(
        [terminal for terminal in terminals if terminal.get("status") != "closed"],
        key=_terminal_updated_at,
        reverse=True,
    )
    closed = sorted(
        [terminal for terminal in terminals if terminal.get("status") == "closed"],
        key=_terminal_updated_at,
        reverse=True,
    )

    kept = active[:limit]
    if len(kept) < limit:
        kept.extend(closed[: limit - len(kept)])

    kept_ids = {terminal["terminal_id"] for terminal in kept}
    original_len = len(terminals)
    terminals[:] = [terminal for terminal in terminals if terminal["terminal_id"] in kept_ids]
    return original_len - len(terminals)


def _close_expired_detached_terminals(terminals: list[dict], now: Optional[datetime] = None) -> int:
    """关闭超出 grace period 的 detached terminal。"""
    current = now or datetime.now(timezone.utc)
    changed = 0

    for terminal in terminals:
        if _normalize_terminal_status(terminal.get("status", "recovering")) != "detached_recoverable":
            continue
        grace_expires_at = terminal.get("grace_expires_at")
        if not grace_expires_at:
            continue
        if current < datetime.fromisoformat(grace_expires_at):
            continue
        terminal["status"] = "closed"
        terminal["disconnect_reason"] = terminal.get("disconnect_reason") or "grace_expired"
        terminal["grace_expires_at"] = None
        terminal["updated_at"] = current.isoformat()
        changed += 1

    return changed


def _backfill_terminal_views(terminals: list[dict]) -> int:
    """兼容旧数据：补齐缺失 views 和无效 geometry_owner_view，不做状态推断。"""
    changed = 0

    for terminal in terminals:
        if "views" not in terminal:
            terminal["views"] = {"mobile": 0, "desktop": 0}
            changed += 1
        owner_view = terminal.get("geometry_owner_view")
        if owner_view not in {"mobile", "desktop", None}:
            terminal["geometry_owner_view"] = None
            changed += 1

    return changed


def _resolve_geometry_owner_view(
    terminal: dict,
    views: dict[str, int],
    *,
    preferred_owner_view: Optional[str] = None,
) -> Optional[str]:
    """为 shared terminal 选择唯一的几何 owner。"""
    total_views = views["mobile"] + views["desktop"]
    if total_views <= 0:
        return None

    current_owner_view = terminal.get("geometry_owner_view")
    if current_owner_view in {"mobile", "desktop"} and views.get(current_owner_view, 0) > 0:
        return current_owner_view

    if preferred_owner_view in {"mobile", "desktop"} and views.get(preferred_owner_view, 0) > 0:
        return preferred_owner_view

    if views["mobile"] > 0:
        return "mobile"
    if views["desktop"] > 0:
        return "desktop"
    return None


def _clear_terminal_attachment_state(terminal: dict) -> None:
    terminal["views"] = {"mobile": 0, "desktop": 0}
    terminal["geometry_owner_view"] = None


def _advance_attach_epoch(terminal: dict) -> int:
    terminal["attach_epoch"] = max(0, int(terminal.get("attach_epoch", 0) or 0)) + 1
    return terminal["attach_epoch"]


def _advance_recovery_epoch(terminal: dict) -> int:
    terminal["recovery_epoch"] = max(0, int(terminal.get("recovery_epoch", 0) or 0)) + 1
    return terminal["recovery_epoch"]


def _validate_session_id(session_id: str) -> None:
    """验证 session_id 格式"""
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="session_id 不能为空",
        )

    if len(session_id) > 1024:  # 1KB
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="session_id 过长",
        )


async def create_session(
    session_id: Optional[str] = None,
    name: Optional[str] = None,
    user_id: Optional[str] = None,
    owner: Optional[str] = None,
) -> dict:
    """
    创建会话

    Args:
        session_id: 可选的 session_id，不提供则自动生成
        name: 可选的会话名称
        user_id: 可选的用户 ID，用于用户隔离
        owner: 可选的会话所有者用户名

    Returns:
        包含 session_id, status, created_at 的字典
    """
    from app.infra.auth import generate_session_id

    if not session_id:
        session_id = generate_session_id()

    _validate_session_id(session_id)

    redis = await redis_conn.get_redis()
    key = _session_key(session_id)

    # 检查是否已存在
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

    # 写入 session name 反向索引（O(1) 查找）
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
    """清理用户的所有旧 session（保留 keep_session_id 指定的）。返回删除数量。

    用于登录时确保同一用户名下只有一个活跃 session，防止 stale session
    在设备列表中显示为离线设备。
    """
    if not user_id:
        return 0

    redis = await redis_conn.get_redis()
    sessions = await list_sessions_for_user(user_id)
    deleted = 0

    for session in sessions:
        sid = session.get("session_id") or session.get("id")
        if sid == keep_session_id:
            continue
        # 删除 name 反向索引
        name = session.get("name", "")
        if name:
            await redis.delete(f"rc:session_name_idx:{name}")
        # 删除 session 数据
        await redis.delete(_session_key(sid))
        deleted += 1

    if deleted > 0:
        logger.info("Cleaned up %d stale session(s) for user %s", deleted, user_id)

    return deleted


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


def _reconcile_terminals(terminals: list[dict]) -> int:
    """执行 reconcile + close expired + trim 的标准组合。"""
    changed = _backfill_terminal_views(terminals)
    changed += _close_expired_detached_terminals(terminals)
    changed += _trim_terminal_records(terminals)
    return changed


async def _save_session(session_id: str, session_data: dict) -> None:
    """内层：直接写入 Redis（调用方需已持有锁）。每次写入自动续期 TTL。"""
    redis = await redis_conn.get_redis()
    await redis.set(_session_key(session_id), json.dumps(session_data), ex=SESSION_TTL_SECONDS)


async def get_session(session_id: str) -> dict:
    """
    获取会话信息（公开 API，加 per-session 锁）

    Args:
        session_id: 会话 ID

    Returns:
        会话数据字典

    Raises:
        HTTPException: 会话不存在时抛出 404
    """
    _validate_session_id(session_id)
    async with _session_locks.get_lock(session_id):
        return await _get_session_raw(session_id)


async def verify_session_ownership(session_id: str, user_id: str) -> dict:
    """
    验证 Session 归属

    Args:
        session_id: 会话 ID
        user_id: 用户 ID

    Returns:
        会话数据字典

    Raises:
        HTTPException: Session 不存在或不属于该用户时抛出 403/404
    """
    session = await get_session(session_id)

    # 如果 session 没有绑定用户，允许访问（向后兼容）
    if not session.get("user_id"):
        return session

    # 验证归属
    if session.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问此 Session",
        )

    return session


async def update_session_status(
    session_id: str,
    new_status: str,
) -> dict:
    """
    更新会话状态（加 per-session 锁）

    Args:
        session_id: 会话 ID
        new_status: 新状态 (pending, online, offline)

    Returns:
        更新后的会话数据
    """
    _validate_session_id(session_id)
    _validate_session_status(new_status)

    async with _session_locks.get_lock(session_id):
        session_data = await _get_session_raw(session_id)
        session_data["status"] = _normalize_session_status(new_status)
        session_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        await _save_session(session_id, session_data)
        return session_data


async def append_history(
    session_id: str,
    data: str,
    direction: str = "output",
    terminal_id: Optional[str] = None,
) -> dict:
    """
    追加历史记录

    Args:
        session_id: 会话 ID
        data: 终端输出数据
        direction: 方向 (input/output)

    Returns:
        包含 timestamp 和 index 的字典
    """
    _validate_session_id(session_id)

    redis = await redis_conn.get_redis()
    history_key = _history_key(session_id)

    now = datetime.now(timezone.utc)
    record = {
        "timestamp": now.isoformat(),
        "direction": direction,
        "data": data,
        "terminal_id": terminal_id,
    }

    # 使用 LPUSH 添加到列表末尾
    index = await redis.rpush(history_key, json.dumps(record))

    # 设置过期时间
    ttl_seconds = HISTORY_TTL_DAYS * 24 * 60 * 60
    await redis.expire(history_key, ttl_seconds)

    return {
        "timestamp": record["timestamp"],
        "index": index - 1,  # LPUSH 返回的是列表长度，index 从 0 开始
    }


async def get_history(
    session_id: str,
    offset: int = 0,
    limit: int = 100,
    *,
    terminal_id: Optional[str] = None,
    direction: Optional[str] = None,
) -> List[dict]:
    """
    分页获取历史记录

    Args:
        session_id: 会话 ID
        offset: 偏移量
        limit: 限制数量 (最大 1000)

    Returns:
        历史记录列表
    """
    _validate_session_id(session_id)

    if offset < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="offset 不能为负数",
        )

    if limit <= 0 or limit > 1000:
        limit = min(max(limit, 1), 1000)

    redis = await redis_conn.get_redis()
    history_key = _history_key(session_id)

    # 检查会话是否存在
    session_key = _session_key(session_id)
    if not await redis.exists(session_key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"会话 {session_id} 不存在",
        )

    total = await redis.llen(history_key)
    if total == 0:
        return []

    # 降级兜底路径，限制最大扫描量防止长 session 内存膨胀
    max_scan = min(total, 5000)
    records = [json.loads(r) for r in await redis.lrange(history_key, total - max_scan, total - 1)]

    if terminal_id is not None:
        records = [
            record for record in records if record.get("terminal_id") == terminal_id
        ]

    if direction is not None:
        records = [
            record for record in records if record.get("direction") == direction
        ]

    if offset >= len(records):
        return []

    end = min(offset + limit, len(records))
    return records[offset:end]


async def get_terminal_output_history(
    session_id: str,
    terminal_id: str,
    *,
    limit: int = 2000,
) -> List[dict]:
    """获取指定 terminal 的输出历史，用于诊断/降级兜底。"""
    return await get_history(
        session_id,
        offset=0,
        limit=limit,
        terminal_id=terminal_id,
        direction="output",
    )


async def get_history_count(session_id: str) -> int:
    """
    获取历史记录总数

    Args:
        session_id: 会话 ID

    Returns:
        历史记录数量
    """
    _validate_session_id(session_id)

    redis = await redis_conn.get_redis()
    history_key = _history_key(session_id)

    return await redis.llen(history_key)


async def cleanup_old_history(session_id: str, max_records: int = 100000) -> int:
    """
    清理旧的历史记录

    Args:
        session_id: 会话 ID
        max_records: 最大保留记录数

    Returns:
        删除的记录数
    """
    _validate_session_id(session_id)

    redis = await redis_conn.get_redis()
    history_key = _history_key(session_id)

    total = await redis.llen(history_key)
    if total <= max_records:
        return 0

    # 保留最新的 max_records 条
    # 使用 LTRIM 保留指定范围
    await redis.ltrim(history_key, -max_records, -1)

    return total - max_records


async def update_session_agent_online(
    session_id: str,
    online: bool,
    pty_rows: Optional[int] = None,
    pty_cols: Optional[int] = None,
) -> dict:
    """
    更新会话的 agent_online 状态（加 per-session 锁）

    Args:
        session_id: 会话 ID
        online: Agent 是否在线
        pty_rows: PTY 行数（可选）
        pty_cols: PTY 列数（可选）

    Returns:
        更新后的会话数据
    """
    _validate_session_id(session_id)

    async with _session_locks.get_lock(session_id):
        session_data = await _get_session_raw(session_id)
        session_data["agent_online"] = online
        session_data["updated_at"] = datetime.now(timezone.utc).isoformat()

        # 更新 PTY 尺寸
        if pty_rows is not None and pty_cols is not None:
            session_data["pty"] = {"rows": pty_rows, "cols": pty_cols}

        await _save_session(session_id, session_data)
        return session_data


async def update_session_view_count(
    session_id: str,
    view_type: str,
    delta: int,
) -> dict:
    """
    更新会话的视图连接数（加 per-session 锁）

    Args:
        session_id: 会话 ID
        view_type: 视图类型 (mobile/desktop)
        delta: 变化量 (+1 或 -1)

    Returns:
        更新后的会话数据
    """
    _validate_session_id(session_id)

    if view_type not in ["mobile", "desktop"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效的视图类型: {view_type}",
        )

    async with _session_locks.get_lock(session_id):
        session_data = await _get_session_raw(session_id)

        # 确保 views 字段存在
        if "views" not in session_data:
            session_data["views"] = {"mobile": 0, "desktop": 0}

        # 更新计数
        session_data["views"][view_type] = max(0, session_data["views"].get(view_type, 0) + delta)
        session_data["updated_at"] = datetime.now(timezone.utc).isoformat()

        await _save_session(session_id, session_data)
        return session_data


async def update_session_pty_size(
    session_id: str,
    rows: int,
    cols: int,
) -> dict:
    """
    更新会话的 PTY 尺寸（加 per-session 锁）

    Args:
        session_id: 会话 ID
        rows: 行数
        cols: 列数

    Returns:
        更新后的会话数据
    """
    _validate_session_id(session_id)

    async with _session_locks.get_lock(session_id):
        session_data = await _get_session_raw(session_id)
        session_data["pty"] = {"rows": rows, "cols": cols}
        session_data["updated_at"] = datetime.now(timezone.utc).isoformat()

        await _save_session(session_id, session_data)
        return session_data


async def get_session_by_name(name: str) -> Optional[dict]:
    """
    通过名称查找会话

    优先使用反向索引 O(1) 查找，向后兼容 SCAN 回退。

    Args:
        name: 会话名称

    Returns:
        会话数据字典，包含 id 和会话信息；未找到返回 None
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
            # _get_session_raw 已 normalize，无需重复
            return {
                "id": sid,
                **session_data,
            }
        except HTTPException:
            # 索引过期（session 已删除），清理过期索引并回退到 SCAN
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
                        return {
                            "id": session_id,
                            **_normalize_session_data(session_id, session_data),
                        }
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
                    sessions.append({
                        "session_id": session_id,
                        **session_data,
                    })
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
                    return {
                        "session_id": session_id,
                        **session_data,
                    }
        if cursor == 0:
            break

    return None


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

        # 续期 name 反向索引 TTL（与 session 同步）
        name = session_data.get("name", "")
        if name:
            redis = await redis_conn.get_redis()
            await redis.expire(f"rc:session_name_idx:{name}", SESSION_TTL_SECONDS)

        return session_data


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


def is_terminal_recoverable(terminal: dict, now: Optional[datetime] = None) -> bool:
    """terminal 是否仍处于可恢复窗口。"""
    if _normalize_terminal_status(terminal.get("status", "recovering")) != "detached_recoverable":
        return False
    grace_expires_at = terminal.get("grace_expires_at")
    if not grace_expires_at:
        return False
    current = now or datetime.now(timezone.utc)
    return current < datetime.fromisoformat(grace_expires_at)
