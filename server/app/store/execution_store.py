"""Agent 执行记录实体域 Store Mixin。

提供 Agent 执行结果回写的数据库操作。
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import aiosqlite

logger = logging.getLogger(__name__)


class ExecutionStoreMixin:
    """Agent 执行记录相关数据库操作 Mixin。"""

    async def save_agent_execution_report(
        self,
        session_id: str,
        user_id: str,
        device_id: str,
        *,
        success: bool,
        executed_command: Optional[str] = None,
        failure_step: Optional[str] = None,
        aliases: Optional[Dict[str, str]] = None,
    ) -> bool:
        """保存 Agent 执行结果回写。幂等：已存在则跳过。

        Returns:
            True 如果新建，False 如果已存在（幂等跳过）
        """
        now = datetime.now(timezone.utc).isoformat()
        aliases_json = json.dumps(aliases or {}, ensure_ascii=False)
        try:
            async with self._connect() as db:
                await db.execute(
                    """
                    INSERT INTO agent_execution_reports
                        (session_id, user_id, device_id, success, executed_command,
                         failure_step, aliases_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO NOTHING
                    """,
                    (
                        session_id,
                        user_id,
                        device_id,
                        1 if success else 0,
                        executed_command,
                        failure_step,
                        aliases_json,
                        now,
                    ),
                )
                await db.commit()
                cursor = await db.execute(
                    "SELECT changes()",
                )
                row = await cursor.fetchone()
                return row[0] > 0
        except Exception:
            return False

    async def get_agent_execution_report(
        self,
        session_id: str,
    ) -> Optional[Dict[str, Any]]:
        """查询 Agent 执行结果回写记录。"""
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT * FROM agent_execution_reports
                WHERE session_id = ?
                """,
                (session_id,),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
