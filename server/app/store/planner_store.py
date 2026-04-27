"""Assistant Planner 实体域 Store Mixin。

提供智能规划运行记录、memory 管理和执行回写的数据库操作。
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiosqlite

logger = logging.getLogger(__name__)


class PlannerStoreMixin:
    """Assistant Planner 相关数据库操作 Mixin。"""

    async def save_assistant_planner_run(
        self,
        username: str,
        device_id: str,
        payload: Dict[str, Any],
    ) -> None:
        """保存或更新单次智能规划记录。"""
        now = datetime.now(timezone.utc).isoformat()
        evaluation_context = payload.get("evaluation_context") or {}
        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO assistant_planner_runs (
                    username, device_id, conversation_id, message_id, intent, provider,
                    fallback_used, fallback_reason, matched_candidate_id, matched_cwd, matched_label,
                    assistant_messages_json, trace_json, command_sequence_json, evaluation_context_json,
                    execution_status, terminal_id, failed_step_id, output_summary, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(username, device_id, conversation_id, message_id) DO UPDATE SET
                    provider = excluded.provider,
                    fallback_used = excluded.fallback_used,
                    fallback_reason = excluded.fallback_reason,
                    matched_candidate_id = excluded.matched_candidate_id,
                    matched_cwd = excluded.matched_cwd,
                    matched_label = excluded.matched_label,
                    assistant_messages_json = excluded.assistant_messages_json,
                    trace_json = excluded.trace_json,
                    command_sequence_json = excluded.command_sequence_json,
                    evaluation_context_json = excluded.evaluation_context_json,
                    execution_status = excluded.execution_status,
                    terminal_id = COALESCE(excluded.terminal_id, assistant_planner_runs.terminal_id),
                    failed_step_id = COALESCE(excluded.failed_step_id, assistant_planner_runs.failed_step_id),
                    output_summary = COALESCE(excluded.output_summary, assistant_planner_runs.output_summary),
                    updated_at = excluded.updated_at
                """,
                (
                    username,
                    device_id,
                    payload["conversation_id"],
                    payload["message_id"],
                    payload["intent"],
                    payload["provider"],
                    1 if payload.get("fallback_used", False) else 0,
                    payload.get("fallback_reason"),
                    evaluation_context.get("matched_candidate_id"),
                    evaluation_context.get("matched_cwd"),
                    evaluation_context.get("matched_label"),
                    json.dumps(payload.get("assistant_messages", []), ensure_ascii=False),
                    json.dumps(payload.get("trace", []), ensure_ascii=False),
                    json.dumps(payload.get("command_sequence"), ensure_ascii=False)
                    if payload.get("command_sequence") is not None
                    else None,
                    json.dumps(evaluation_context, ensure_ascii=False),
                    payload.get("execution_status", "planned"),
                    payload.get("terminal_id"),
                    payload.get("failed_step_id"),
                    payload.get("output_summary"),
                    now,
                    now,
                ),
            )
            await db.commit()

    async def get_assistant_planner_run(
        self,
        username: str,
        device_id: str,
        conversation_id: str,
        message_id: str,
    ) -> Optional[Dict[str, Any]]:
        """读取单次智能规划记录。"""
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT *
                FROM assistant_planner_runs
                WHERE username = ? AND device_id = ? AND conversation_id = ? AND message_id = ?
                """,
                (username, device_id, conversation_id, message_id),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def list_assistant_planner_memory(
        self,
        username: str,
        device_id: str,
        memory_type: str,
        *,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """按类型读取最近的 planner memory。"""
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT *
                FROM assistant_planner_memory_entries
                WHERE username = ? AND device_id = ? AND memory_type = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (username, device_id, memory_type, limit),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def report_assistant_execution(
        self,
        username: str,
        device_id: str,
        conversation_id: str,
        message_id: str,
        *,
        execution_status: str,
        terminal_id: Optional[str],
        failed_step_id: Optional[str],
        output_summary: Optional[str],
        command_sequence: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """回写单次执行结果，并更新 planner memory。"""
        now = datetime.now(timezone.utc).isoformat()
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT *
                FROM assistant_planner_runs
                WHERE username = ? AND device_id = ? AND conversation_id = ? AND message_id = ?
                """,
                (username, device_id, conversation_id, message_id),
            )
            row = await cursor.fetchone()
            if not row:
                return None

            existing = dict(row)
            if existing.get("execution_status") in {"succeeded", "failed"}:
                return existing

            await db.execute(
                """
                UPDATE assistant_planner_runs
                SET execution_status = ?,
                    terminal_id = ?,
                    failed_step_id = ?,
                    output_summary = ?,
                    command_sequence_json = ?,
                    updated_at = ?
                WHERE username = ? AND device_id = ? AND conversation_id = ? AND message_id = ?
                """,
                (
                    execution_status,
                    terminal_id,
                    failed_step_id,
                    output_summary,
                    json.dumps(command_sequence, ensure_ascii=False),
                    now,
                    username,
                    device_id,
                    conversation_id,
                    message_id,
                ),
            )

            matched_cwd = existing.get("matched_cwd") or ""
            matched_label = existing.get("matched_label") or ""
            matched_candidate_id = existing.get("matched_candidate_id") or ""

            async def upsert_memory(
                memory_type: str,
                memory_key: str,
                *,
                label: str,
                cwd: str,
                summary: str,
                metadata: Dict[str, Any],
                succeeded: bool,
            ) -> None:
                if not memory_key:
                    return
                await db.execute(
                    """
                    INSERT INTO assistant_planner_memory_entries (
                        username, device_id, memory_type, memory_key, label, cwd, summary,
                        command_sequence_json, metadata_json, success_count, failure_count,
                        last_status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(username, device_id, memory_type, memory_key) DO UPDATE SET
                        label = excluded.label,
                        cwd = excluded.cwd,
                        summary = excluded.summary,
                        command_sequence_json = excluded.command_sequence_json,
                        metadata_json = excluded.metadata_json,
                        success_count = assistant_planner_memory_entries.success_count + excluded.success_count,
                        failure_count = assistant_planner_memory_entries.failure_count + excluded.failure_count,
                        last_status = excluded.last_status,
                        updated_at = excluded.updated_at
                    """,
                    (
                        username,
                        device_id,
                        memory_type,
                        memory_key,
                        label,
                        cwd,
                        summary,
                        json.dumps(command_sequence, ensure_ascii=False),
                        json.dumps(metadata, ensure_ascii=False),
                        1 if succeeded else 0,
                        0 if succeeded else 1,
                        execution_status,
                        now,
                        now,
                    ),
                )

            metadata = {
                "conversation_id": conversation_id,
                "message_id": message_id,
                "matched_candidate_id": matched_candidate_id,
                "failed_step_id": failed_step_id,
            }

            if execution_status == "succeeded":
                await upsert_memory(
                    "recent_project",
                    matched_cwd or f"{conversation_id}:{message_id}",
                    label=matched_label,
                    cwd=matched_cwd,
                    summary=command_sequence.get("summary", ""),
                    metadata=metadata,
                    succeeded=True,
                )
                await upsert_memory(
                    "successful_sequence",
                    matched_cwd or f"{conversation_id}:{message_id}",
                    label=matched_label,
                    cwd=matched_cwd,
                    summary=command_sequence.get("summary", ""),
                    metadata=metadata,
                    succeeded=True,
                )
            else:
                await upsert_memory(
                    "recent_failure",
                    f"{conversation_id}:{message_id}",
                    label=matched_label,
                    cwd=matched_cwd,
                    summary=output_summary or command_sequence.get("summary", ""),
                    metadata=metadata,
                    succeeded=False,
                )

            await db.commit()

        return await self.get_assistant_planner_run(
            username,
            device_id,
            conversation_id,
            message_id,
        )
