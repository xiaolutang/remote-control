"""
SQLite 数据库层 - 用户持久化存储

使用 aiosqlite 异步库管理用户数据。
通过 Database 类封装连接和路径管理，支持依赖注入。
模块级便捷函数委托到默认实例，保持向后兼容。
"""
import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator, Optional, Dict, List, Any

import aiosqlite

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "/data/users.db"


class Database:
    """SQLite 数据库管理器，封装路径、连接和 CRUD 操作。"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init_db(self) -> None:
        """初始化数据库，创建表（如果不存在）。"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        async with self._connect() as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL REFERENCES users(username),
                    device_name TEXT,
                    device_type TEXT DEFAULT 'mobile',
                    bound_at TEXT
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_devices_username
                ON user_devices(username)
            """)
            await db.commit()
            logger.info(f"Database initialized: {self.db_path}")

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        """内部连接管理器，启用 FK 约束。"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys = ON")
            yield db

    async def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        """获取用户信息，不存在返回 None。"""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def save_user(self, username: str, password_hash: str) -> None:
        """保存新用户。"""
        async with self._connect() as db:
            await db.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, password_hash, datetime.now(timezone.utc).isoformat())
            )
            await db.commit()

    async def update_password_hash(self, username: str, password_hash: str) -> None:
        """更新用户密码哈希（用于旧哈希迁移）。"""
        async with self._connect() as db:
            await db.execute(
                "UPDATE users SET password_hash = ? WHERE username = ?",
                (password_hash, username),
            )
            await db.commit()

    async def get_user_devices(self, username: str) -> List[Dict[str, Any]]:
        """获取用户绑定的设备列表。"""
        async with self._connect() as db:
            cursor = await db.execute(
                "SELECT * FROM user_devices WHERE username = ?", (username,)
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def add_user_device(self, username: str, device_info: Dict[str, Any]) -> None:
        """添加用户设备。"""
        async with self._connect() as db:
            await db.execute(
                """INSERT INTO user_devices (username, device_name, device_type, bound_at)
                   VALUES (?, ?, ?, ?)""",
                (username, device_info["device_name"], device_info["device_type"], device_info["bound_at"])
            )
            await db.commit()


# ============ 默认实例 + 模块级便捷函数 ============

_db: Optional[Database] = None


def configure_database(db_path: str) -> Database:
    """配置数据库实例（用于启动和测试注入）。"""
    global _db
    _db = Database(db_path)
    return _db


def _get_db() -> Database:
    """获取当前数据库实例，未配置时使用环境变量默认值。"""
    global _db
    if _db is None:
        path = os.environ.get("DATABASE_PATH", DEFAULT_DB_PATH)
        _db = Database(path)
    return _db


async def init_db() -> None:
    """初始化默认数据库。"""
    db = _get_db()
    try:
        await db.init_db()
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise


async def get_user(username: str) -> Optional[Dict[str, Any]]:
    return await _get_db().get_user(username)


async def save_user(username: str, password_hash: str) -> None:
    await _get_db().save_user(username, password_hash)


async def update_password_hash(username: str, password_hash: str) -> None:
    await _get_db().update_password_hash(username, password_hash)


async def get_user_devices(username: str) -> List[Dict[str, Any]]:
    return await _get_db().get_user_devices(username)


async def add_user_device(username: str, device_info: Dict[str, Any]) -> None:
    await _get_db().add_user_device(username, device_info)
