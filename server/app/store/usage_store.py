"""Agent 使用量统计实体域 Store Mixin。

提供 usage 记录写入和汇总查询的数据库操作。
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiosqlite

logger = logging.getLogger(__name__)


class UsageStoreMixin:
    """Agent 使用量统计相关数据库操作 Mixin。"""

    async def save_agent_usage(
        self,
        session_id: str,
        user_id: str,
        device_id: str,
        *,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        requests: Optional[int] = None,
        model_name: Optional[str] = None,
    ) -> bool:
        """保存单次 Agent 运行 usage。

        Returns:
            True 表示成功写入/更新，False 表示写入失败。
        """
        now = datetime.now(timezone.utc).isoformat()
        try:
            async with self._connect() as db:
                await db.execute(
                    """
                    INSERT INTO agent_usage_records (
                        session_id, user_id, device_id, input_tokens,
                        output_tokens, total_tokens, requests, model_name, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        user_id = excluded.user_id,
                        device_id = excluded.device_id,
                        input_tokens = excluded.input_tokens,
                        output_tokens = excluded.output_tokens,
                        total_tokens = excluded.total_tokens,
                        requests = excluded.requests,
                        model_name = excluded.model_name,
                        created_at = excluded.created_at
                    """,
                    (
                        session_id,
                        user_id,
                        device_id,
                        int(input_tokens or 0),
                        int(output_tokens or 0),
                        int(total_tokens or 0),
                        int(requests or 0),
                        model_name or "",
                        now,
                    ),
                )
                await db.commit()
                return True
        except Exception:
            logger.warning("Failed to save agent usage: session_id=%s", session_id, exc_info=True)
            return False

    async def get_usage_summary(
        self,
        user_id: str,
        device_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """汇总 Agent usage。

        Args:
            user_id: 当前用户
            device_id: 指定设备；为空时汇总用户全量设备
        """
        where_clause = "WHERE user_id = ?"
        params: list[Any] = [user_id]
        if device_id is not None:
            where_clause += " AND device_id = ?"
            params.append(device_id)

        async with self._connect() as db:
            cursor = await db.execute(
                f"""
                SELECT
                    COUNT(*) AS total_sessions,
                    COALESCE(SUM(input_tokens), 0) AS total_input_tokens,
                    COALESCE(SUM(output_tokens), 0) AS total_output_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(requests), 0) AS total_requests
                FROM agent_usage_records
                {where_clause}
                """,
                params,
            )
            aggregate_row = await cursor.fetchone()

            cursor = await db.execute(
                f"""
                SELECT model_name
                FROM agent_usage_records
                {where_clause}
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                params,
            )
            latest_row = await cursor.fetchone()

        aggregate = dict(aggregate_row) if aggregate_row else {}
        return {
            "total_sessions": int(aggregate.get("total_sessions", 0) or 0),
            "total_input_tokens": int(aggregate.get("total_input_tokens", 0) or 0),
            "total_output_tokens": int(aggregate.get("total_output_tokens", 0) or 0),
            "total_tokens": int(aggregate.get("total_tokens", 0) or 0),
            "total_requests": int(aggregate.get("total_requests", 0) or 0),
            "latest_model_name": (latest_row["model_name"] if latest_row and latest_row["model_name"] else ""),
        }
