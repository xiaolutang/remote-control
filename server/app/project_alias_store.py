"""
B081: 项目别名持久化存储。

支持 Agent 探索结果自动学习，将用户设备上的项目别名持久化到 SQLite。
通过 user_id + device_id 隔离，同 alias 幂等覆盖更新。
"""
import logging
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)


class ProjectAliasStore:
    """项目别名持久化存储，委托到 Database 的 SQLite 连接。"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def _connect(self):
        """内部连接管理器。"""
        return aiosqlite.connect(self.db_path)

    async def save(self, user_id: str, device_id: str, alias: str, path: str) -> None:
        """保存/更新别名。INSERT OR REPLACE 幂等。

        Args:
            user_id: 用户 ID
            device_id: 设备 ID
            alias: 项目别名（用户可读名称）
            path: 项目路径
        """
        if not alias or not path:
            return
        now = datetime.now(timezone.utc).isoformat()
        async with await self._connect() as db:
            await db.execute(
                """
                INSERT INTO project_aliases (user_id, device_id, alias, path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, device_id, alias) DO UPDATE SET
                    path = excluded.path,
                    updated_at = excluded.updated_at
                """,
                (user_id, device_id, alias, path, now, now),
            )
            await db.commit()

    async def save_batch(
        self,
        user_id: str,
        device_id: str,
        aliases: dict[str, str],
    ) -> None:
        """批量保存别名。

        Args:
            user_id: 用户 ID
            device_id: 设备 ID
            aliases: 别名映射 {alias: path}
        """
        if not aliases:
            return
        now = datetime.now(timezone.utc).isoformat()
        async with await self._connect() as db:
            for alias, path in aliases.items():
                if not alias or not path:
                    continue
                await db.execute(
                    """
                    INSERT INTO project_aliases (user_id, device_id, alias, path, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, device_id, alias) DO UPDATE SET
                        path = excluded.path,
                        updated_at = excluded.updated_at
                    """,
                    (user_id, device_id, alias, path, now, now),
                )
            await db.commit()

    async def lookup(
        self,
        user_id: str,
        device_id: str,
        alias: str,
    ) -> Optional[str]:
        """按别名查找路径。

        Args:
            user_id: 用户 ID
            device_id: 设备 ID
            alias: 项目别名

        Returns:
            项目路径，不存在返回 None
        """
        async with await self._connect() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT path FROM project_aliases
                WHERE user_id = ? AND device_id = ? AND alias = ?
                """,
                (user_id, device_id, alias),
            )
            row = await cursor.fetchone()
            return row["path"] if row else None

    async def list_all(
        self,
        user_id: str,
        device_id: str,
    ) -> dict[str, str]:
        """返回指定设备的所有别名。

        Args:
            user_id: 用户 ID
            device_id: 设备 ID

        Returns:
            别名映射 {alias: path}
        """
        async with await self._connect() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT alias, path FROM project_aliases
                WHERE user_id = ? AND device_id = ?
                ORDER BY updated_at DESC
                """,
                (user_id, device_id),
            )
            rows = await cursor.fetchall()
            return {row["alias"]: row["path"] for row in rows}

    async def cleanup_stale(self, days: int = 90) -> int:
        """清理超过 N 天未使用的别名。

        Args:
            days: 超过多少天未更新的别名将被清理，默认 90 天

        Returns:
            清理的记录数
        """
        async with await self._connect() as db:
            cursor = await db.execute(
                """
                DELETE FROM project_aliases
                WHERE updated_at < datetime('now', ?)
                """,
                (f"-{days} days",),
            )
            await db.commit()
            return cursor.rowcount
