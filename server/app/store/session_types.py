"""
session 子模块 — 数据类型、常量与键名辅助。
"""
import os
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ─── 配置 ───

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
HISTORY_TTL_DAYS = int(os.getenv("HISTORY_TTL_DAYS", "7"))  # 历史记录保留天数
DEFAULT_MAX_TERMINALS = int(os.getenv("DEFAULT_MAX_TERMINALS", "3"))
MAX_TERMINAL_RECORDS = int(os.getenv("MAX_TERMINAL_RECORDS", "5"))
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", str(24 * 60 * 60)))  # session 默认 24h 过期

# ─── 状态集合 ───

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

# ─── 键名前缀 ───

KEY_PREFIX = "rc:session"
HISTORY_KEY_PREFIX = "rc:history"


# ─── 键名辅助 ───

def _session_key(session_id: str) -> str:
    """生成 session 存储键"""
    return f"{KEY_PREFIX}:{session_id}"


def _history_key(session_id: str) -> str:
    """生成 history 存储键"""
    return f"{HISTORY_KEY_PREFIX}:{session_id}"


# ─── 默认状态工厂 ───

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
    from datetime import datetime, timezone
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


# ─── per-session Lock 管理器 ───

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
