"""
B001: 定时任务持久化存储。

支持终端定时执行命令的 CRUD 操作。
表结构定义在 _schema.py，由 Database.init_db() 自动创建。
"""
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

import aiosqlite

logger = logging.getLogger(__name__)


class ScheduledTaskStore:
    """定时任务持久化存储，委托到 Database 的 SQLite 连接。"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def _connect(self):
        """内部连接管理器。"""
        return aiosqlite.connect(self.db_path)

    async def _query(
        self,
        where_clause: str,
        params: tuple,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """通用查询：按 WHERE 条件 + 可选 status 过滤查询任务列表。"""
        if status is not None:
            where = f"{where_clause} AND status = ?"
            params = params + (status,)
        else:
            where = where_clause
        async with await self._connect() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                f"SELECT * FROM scheduled_tasks WHERE {where} ORDER BY execute_at ASC",
                params,
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def create(
        self,
        user_id: str,
        session_id: str,
        terminal_id: str,
        text_content: str,
        execute_at: str,
        repeat_type: str = "once",
    ) -> int:
        """创建定时任务。

        Args:
            user_id: 用户 ID
            session_id: 会话 ID
            terminal_id: 终端 ID
            text_content: 要执行的文本内容
            execute_at: 执行时间（ISO 格式字符串）
            repeat_type: 重复类型，默认 'none'

        Returns:
            新建任务的 ID
        """
        now = datetime.now(timezone.utc).isoformat()
        async with await self._connect() as db:
            cursor = await db.execute(
                """
                INSERT INTO scheduled_tasks
                    (user_id, session_id, terminal_id, text_content, execute_at, repeat_type, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (user_id, session_id, terminal_id, text_content, execute_at, repeat_type, now),
            )
            await db.commit()
            return cursor.lastrowid

    async def list_by_user(
        self,
        user_id: str,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """按 user_id 查询定时任务。"""
        return await self._query("user_id = ?", (user_id,), status)

    async def list_by_session(
        self,
        session_id: str,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """按 session_id 查询定时任务。"""
        return await self._query("session_id = ?", (session_id,), status)

    async def list_by_session_and_terminal(
        self,
        session_id: str,
        terminal_id: str,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """按 session_id + terminal_id 查询定时任务（terminal 级查询）。"""
        return await self._query(
            "session_id = ? AND terminal_id = ?", (session_id, terminal_id), status
        )

    async def get_by_id(self, task_id: int) -> Optional[Dict[str, Any]]:
        """按 ID 查询定时任务。

        Args:
            task_id: 任务 ID

        Returns:
            任务字典，不存在返回 None
        """
        async with await self._connect() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM scheduled_tasks WHERE id = ?",
                (task_id,),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def update_status(
        self,
        task_id: int,
        status: str,
        executed_at: Optional[str] = None,
    ) -> None:
        """更新任务状态。

        Args:
            task_id: 任务 ID
            status: 新状态
            executed_at: 执行时间（ISO 格式字符串），可选
        """
        async with await self._connect() as db:
            await db.execute(
                """
                UPDATE scheduled_tasks
                SET status = ?, executed_at = ?
                WHERE id = ?
                """,
                (status, executed_at, task_id),
            )
            await db.commit()

    async def list_pending_due(self, now_iso: str) -> List[Dict[str, Any]]:
        """查询所有 status='pending' 且 execute_at <= now 的到期任务。

        Args:
            now_iso: 当前时间的 ISO 格式字符串

        Returns:
            到期的 pending 任务列表
        """
        async with await self._connect() as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM scheduled_tasks
                WHERE status = 'pending' AND execute_at <= ?
                ORDER BY execute_at ASC
                """,
                (now_iso,),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def update_execute_at(self, task_id: int, new_execute_at: str) -> None:
        """更新任务的 execute_at 时间（用于每日任务推到次日）。

        Args:
            task_id: 任务 ID
            new_execute_at: 新的执行时间（ISO 格式字符串）
        """
        async with await self._connect() as db:
            await db.execute(
                """
                UPDATE scheduled_tasks
                SET execute_at = ?
                WHERE id = ?
                """,
                (new_execute_at, task_id),
            )
            await db.commit()

    async def delete(self, task_id: int) -> None:
        """删除定时任务。

        Args:
            task_id: 任务 ID
        """
        async with await self._connect() as db:
            await db.execute(
                "DELETE FROM scheduled_tasks WHERE id = ?",
                (task_id,),
            )
            await db.commit()

    async def cancel_by_terminal(self, session_id: str, terminal_id: str) -> int:
        """将指定终端的所有 pending 任务标记为 cancelled。

        Args:
            session_id: 会话 ID
            terminal_id: 终端 ID

        Returns:
            取消的任务数
        """
        async with await self._connect() as db:
            cursor = await db.execute(
                """
                UPDATE scheduled_tasks
                SET status = 'cancelled'
                WHERE session_id = ? AND terminal_id = ? AND status = 'pending'
                """,
                (session_id, terminal_id),
            )
            await db.commit()
            return cursor.rowcount
