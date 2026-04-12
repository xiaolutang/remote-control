"""
SQLite 数据库层 - 用户持久化存储

使用 aiosqlite 异步库管理用户数据。
数据库文件路径由环境变量 DATABASE_PATH 指定，默认为 /data/users.db。
"""
import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator, Optional, Dict, List, Any

import aiosqlite

logger = logging.getLogger(__name__)

DATABASE_PATH = os.environ.get("DATABASE_PATH", "/data/users.db")


async def init_db() -> None:
    """初始化数据库，创建表（如果不存在）。在 FastAPI startup event 中调用。"""
    try:
        db_dir = os.path.dirname(DATABASE_PATH)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            logger.info(f"Created database directory: {db_dir}")

        async with aiosqlite.connect(DATABASE_PATH) as db:
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
                    username TEXT NOT NULL,
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
            logger.info(f"Database initialized: {DATABASE_PATH}")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    """获取数据库连接的异步上下文管理器。"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


# ==================== 用户数据操作 ====================

async def get_user(username: str) -> Optional[Dict[str, Any]]:
    """获取用户信息，不存在返回 None。"""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def save_user(username: str, password_hash: str) -> None:
    """保存新用户。"""
    async with get_db() as db:
        await db.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, password_hash, datetime.now(timezone.utc).isoformat())
        )
        await db.commit()


async def get_user_devices(username: str) -> List[Dict[str, Any]]:
    """获取用户绑定的设备列表。"""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM user_devices WHERE username = ?", (username,)
        )
        return [dict(row) for row in await cursor.fetchall()]


async def add_user_device(username: str, device_info: Dict[str, Any]) -> None:
    """添加用户设备。"""
    async with get_db() as db:
        await db.execute(
            """INSERT INTO user_devices (username, device_name, device_type, bound_at)
               VALUES (?, ?, ?, ?)""",
            (username, device_info["device_name"], device_info["device_type"], device_info["bound_at"])
        )
        await db.commit()
