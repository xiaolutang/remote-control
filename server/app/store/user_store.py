"""用户实体域 Store Mixin。

提供用户 CRUD + 设备管理的数据库操作。
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiosqlite

logger = logging.getLogger(__name__)


class UserStoreMixin:
    """用户相关数据库操作 Mixin。"""

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
