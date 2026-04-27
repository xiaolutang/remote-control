"""Agent 对话实体域 Store Mixin。

提供 Agent conversation CRUD、事件追加、截断和墓碑清理的数据库操作。
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

import aiosqlite

logger = logging.getLogger(__name__)


class ConversationStoreMixin:
    """Agent 对话相关数据库操作 Mixin。"""

    async def get_or_create_agent_conversation(
        self,
        user_id: str,
        device_id: str,
        terminal_id: str,
    ) -> Dict[str, Any]:
        """获取或创建 terminal-bound Agent conversation。

        同一 user/device/terminal 只允许一个 conversation。若已有 closed
        tombstone，返回该 closed conversation，不在存储层静默重开。
        """
        now = datetime.now(timezone.utc).isoformat()
        async with self._connect() as db:
            conversation_id = f"conv_{uuid4().hex}"
            await db.execute(
                """
                INSERT OR IGNORE INTO agent_conversations (
                    conversation_id, user_id, device_id, terminal_id,
                    status, tombstone_until, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'active', NULL, ?, ?)
                """,
                (conversation_id, user_id, device_id, terminal_id, now, now),
            )
            await db.commit()

            cursor = await db.execute(
                """
                SELECT *
                FROM agent_conversations
                WHERE user_id = ? AND device_id = ? AND terminal_id = ?
                """,
                (user_id, device_id, terminal_id),
            )
            return dict(await cursor.fetchone())

    async def get_agent_conversation(
        self,
        user_id: str,
        device_id: str,
        terminal_id: str,
    ) -> Optional[Dict[str, Any]]:
        """读取指定 terminal 的 conversation 元数据。"""
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT *
                FROM agent_conversations
                WHERE user_id = ? AND device_id = ? AND terminal_id = ?
                """,
                (user_id, device_id, terminal_id),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def append_agent_conversation_event(
        self,
        user_id: str,
        device_id: str,
        terminal_id: str,
        *,
        event_type: str,
        role: str,
        payload: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        question_id: Optional[str] = None,
        client_event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """向 terminal conversation 追加事件。

        - `client_event_id` 在 conversation 内幂等。
        - 同一个 `question_id` 只能有一个 answer。
        - `event_index` 在事务内分配，避免并发乱序。
        """
        # Deferred import to avoid circular dependency at module level
        from app.store.database import AgentConversationConflict

        now = datetime.now(timezone.utc).isoformat()
        conversation = await self.get_or_create_agent_conversation(user_id, device_id, terminal_id)
        if conversation["status"] != "active":
            raise AgentConversationConflict("closed_terminal")

        conversation_id = conversation["conversation_id"]
        async with self._connect() as db:
            await db.execute("BEGIN IMMEDIATE")

            if client_event_id:
                existing = await self._fetch_agent_conversation_event_by_client_event_id(
                    db,
                    conversation_id,
                    client_event_id,
                )
                if existing is not None:
                    await db.commit()
                    return existing

            if event_type == "answer" and question_id:
                cursor = await db.execute(
                    """
                    SELECT *
                    FROM agent_conversation_events
                    WHERE conversation_id = ? AND event_type = 'answer' AND question_id = ?
                    """,
                    (conversation_id, question_id),
                )
                row = await cursor.fetchone()
                if row:
                    await db.rollback()
                    raise AgentConversationConflict("question_already_answered")

            cursor = await db.execute(
                """
                SELECT COALESCE(MAX(event_index), -1) + 1 AS next_index
                FROM agent_conversation_events
                WHERE conversation_id = ?
                """,
                (conversation_id,),
            )
            next_index_row = await cursor.fetchone()
            event_index = int(next_index_row["next_index"])
            event_id = f"evt_{uuid4().hex}"
            await db.execute(
                """
                INSERT INTO agent_conversation_events (
                    conversation_id, event_index, event_id, event_type, role,
                    session_id, question_id, client_event_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    event_index,
                    event_id,
                    event_type,
                    role,
                    session_id,
                    question_id,
                    client_event_id,
                    json.dumps(payload or {}, ensure_ascii=False),
                    now,
                ),
            )
            await db.execute(
                """
                UPDATE agent_conversations
                SET updated_at = ?
                WHERE conversation_id = ?
                """,
                (now, conversation_id),
            )
            await db.commit()

            cursor = await db.execute(
                """
                SELECT *
                FROM agent_conversation_events
                WHERE conversation_id = ? AND event_index = ?
                """,
                (conversation_id, event_index),
            )
            return self._event_row_to_dict(await cursor.fetchone())

    async def list_agent_conversation_events(
        self,
        user_id: str,
        device_id: str,
        terminal_id: str,
        *,
        after_index: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """读取 conversation events。closed tombstone 不返回历史事件。"""
        conversation = await self.get_agent_conversation(user_id, device_id, terminal_id)
        if conversation is None:
            return []
        if conversation["status"] != "active":
            return []

        where = "conversation_id = ?"
        params: list[Any] = [conversation["conversation_id"]]
        if after_index is not None:
            where += " AND event_index > ?"
            params.append(int(after_index))

        async with self._connect() as db:
            cursor = await db.execute(
                f"""
                SELECT *
                FROM agent_conversation_events
                WHERE {where}
                ORDER BY event_index ASC
                """,
                params,
            )
            return [self._event_row_to_dict(row) for row in await cursor.fetchall()]

    async def truncate_agent_conversation_events(
        self,
        user_id: str,
        device_id: str,
        terminal_id: str,
        *,
        after_index: int,
    ) -> int:
        """删除 event_index > after_index 的所有事件，返回删除行数。同时递增 truncation_epoch。"""
        conversation = await self.get_agent_conversation(user_id, device_id, terminal_id)
        if conversation is None or conversation["status"] != "active":
            return 0
        conversation_id = conversation["conversation_id"]
        async with self._connect() as db:
            cursor = await db.execute(
                """
                DELETE FROM agent_conversation_events
                WHERE conversation_id = ? AND event_index > ?
                """,
                (conversation_id, int(after_index)),
            )
            deleted = cursor.rowcount
            if deleted > 0:
                now = datetime.now(timezone.utc).isoformat()
                await db.execute(
                    """
                    UPDATE agent_conversations
                    SET truncation_epoch = COALESCE(truncation_epoch, 0) + 1,
                        updated_at = ?
                    WHERE conversation_id = ?
                    """,
                    (now, conversation_id),
                )
            await db.commit()
            return deleted

    async def close_agent_conversation(
        self,
        user_id: str,
        device_id: str,
        terminal_id: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
        tombstone_seconds: int = 30,
    ) -> Optional[Dict[str, Any]]:
        """写入 ephemeral closed event，并将 conversation 标记为 closed tombstone."""
        tombstone_until = (
            datetime.now(timezone.utc) + timedelta(seconds=tombstone_seconds)
        ).isoformat()
        now = datetime.now(timezone.utc).isoformat()
        async with self._connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                SELECT *
                FROM agent_conversations
                WHERE user_id = ? AND device_id = ? AND terminal_id = ?
                """,
                (user_id, device_id, terminal_id),
            )
            conversation = await cursor.fetchone()
            if conversation is None or conversation["status"] != "active":
                await db.rollback()
                return None

            conversation_id = conversation["conversation_id"]
            cursor = await db.execute(
                """
                SELECT COALESCE(MAX(event_index), -1) + 1 AS next_index
                FROM agent_conversation_events
                WHERE conversation_id = ?
                """,
                (conversation_id,),
            )
            next_index_row = await cursor.fetchone()
            event_index = int(next_index_row["next_index"])
            event_id = f"evt_{uuid4().hex}"
            await db.execute(
                """
                INSERT INTO agent_conversation_events (
                    conversation_id, event_index, event_id, event_type, role,
                    session_id, question_id, client_event_id, payload_json, created_at
                ) VALUES (?, ?, ?, 'closed', 'system', NULL, NULL, NULL, ?, ?)
                """,
                (
                    conversation_id,
                    event_index,
                    event_id,
                    json.dumps(payload or {"reason": "terminal_closed"}, ensure_ascii=False),
                    now,
                ),
            )
            await db.execute(
                """
                UPDATE agent_conversations
                SET status = 'closed',
                    tombstone_until = ?,
                    updated_at = ?
                WHERE conversation_id = ?
                """,
                (tombstone_until, now, conversation_id),
            )
            await db.commit()
            cursor = await db.execute(
                """
                SELECT *
                FROM agent_conversation_events
                WHERE conversation_id = ? AND event_index = ?
                """,
                (conversation_id, event_index),
            )
            closed_event = self._event_row_to_dict(await cursor.fetchone())
        return closed_event

    async def delete_agent_conversation(
        self,
        user_id: str,
        device_id: str,
        terminal_id: str,
    ) -> bool:
        """物理删除 terminal conversation 及其事件。"""
        async with self._connect() as db:
            await db.execute(
                """
                DELETE FROM agent_conversations
                WHERE user_id = ? AND device_id = ? AND terminal_id = ?
                """,
                (user_id, device_id, terminal_id),
            )
            await db.commit()
            cursor = await db.execute("SELECT changes()")
            row = await cursor.fetchone()
            return row[0] > 0

    async def cleanup_agent_conversation_tombstones(self) -> int:
        """删除已过期的 closed tombstone conversations。"""
        now = datetime.now(timezone.utc).isoformat()
        async with self._connect() as db:
            await db.execute(
                """
                DELETE FROM agent_conversations
                WHERE status = 'closed'
                  AND tombstone_until IS NOT NULL
                  AND tombstone_until <= ?
                """,
                (now,),
            )
            await db.commit()
            cursor = await db.execute("SELECT changes()")
            row = await cursor.fetchone()
            return int(row[0] or 0)

    async def _fetch_agent_conversation_event_by_client_event_id(
        self,
        db: aiosqlite.Connection,
        conversation_id: str,
        client_event_id: str,
    ) -> Optional[Dict[str, Any]]:
        cursor = await db.execute(
            """
            SELECT *
            FROM agent_conversation_events
            WHERE conversation_id = ? AND client_event_id = ?
            """,
            (conversation_id, client_event_id),
        )
        row = await cursor.fetchone()
        return self._event_row_to_dict(row) if row else None

    def _event_row_to_dict(self, row: Optional[Any]) -> Dict[str, Any]:
        if row is None:
            return {}
        event = dict(row)
        try:
            event["payload"] = json.loads(event.pop("payload_json") or "{}")
        except json.JSONDecodeError:
            event["payload"] = {}
        return event
