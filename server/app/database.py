"""
SQLite 数据库层 - 用户持久化存储

使用 aiosqlite 异步库管理用户数据。
通过 Database 类封装连接和路径管理，支持依赖注入。
模块级便捷函数委托到默认实例，保持向后兼容。
"""
import logging
import os
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Optional, Dict, List, Any
from uuid import uuid4

import aiosqlite

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "/data/users.db"


class AgentConversationConflict(Exception):
    """Raised when a terminal conversation write conflicts with existing state."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


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
            await db.execute("""
                CREATE TABLE IF NOT EXISTS project_source_pinned_projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL REFERENCES users(username),
                    device_id TEXT NOT NULL,
                    label TEXT NOT NULL,
                    cwd TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(username, device_id, cwd)
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_pinned_projects_scope
                ON project_source_pinned_projects(username, device_id)
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS project_source_scan_roots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL REFERENCES users(username),
                    device_id TEXT NOT NULL,
                    root_path TEXT NOT NULL,
                    scan_depth INTEGER NOT NULL DEFAULT 2,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(username, device_id, root_path)
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_scan_roots_scope
                ON project_source_scan_roots(username, device_id)
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS project_source_planner_configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL REFERENCES users(username),
                    device_id TEXT NOT NULL,
                    provider TEXT NOT NULL DEFAULT 'claude_cli',
                    llm_enabled INTEGER NOT NULL DEFAULT 1,
                    endpoint_profile TEXT NOT NULL DEFAULT 'openai_compatible',
                    credentials_mode TEXT NOT NULL DEFAULT 'client_secure_storage',
                    requires_explicit_opt_in INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(username, device_id)
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_planner_configs_scope
                ON project_source_planner_configs(username, device_id)
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS assistant_planner_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL REFERENCES users(username),
                    device_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    fallback_used INTEGER NOT NULL DEFAULT 0,
                    fallback_reason TEXT,
                    matched_candidate_id TEXT,
                    matched_cwd TEXT,
                    matched_label TEXT,
                    assistant_messages_json TEXT NOT NULL DEFAULT '[]',
                    trace_json TEXT NOT NULL DEFAULT '[]',
                    command_sequence_json TEXT,
                    evaluation_context_json TEXT NOT NULL DEFAULT '{}',
                    execution_status TEXT NOT NULL DEFAULT 'planned',
                    terminal_id TEXT,
                    failed_step_id TEXT,
                    output_summary TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(username, device_id, conversation_id, message_id)
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_assistant_runs_scope
                ON assistant_planner_runs(username, device_id, created_at DESC)
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS assistant_planner_memory_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL REFERENCES users(username),
                    device_id TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    memory_key TEXT NOT NULL,
                    label TEXT,
                    cwd TEXT,
                    summary TEXT,
                    command_sequence_json TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    last_status TEXT NOT NULL DEFAULT 'unknown',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(username, device_id, memory_type, memory_key)
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_assistant_memory_scope
                ON assistant_planner_memory_entries(username, device_id, memory_type, updated_at DESC)
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS project_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    alias TEXT NOT NULL,
                    path TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    UNIQUE(user_id, device_id, alias)
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_project_aliases_user_device
                ON project_aliases(user_id, device_id)
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS agent_execution_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    executed_command TEXT,
                    failure_step TEXT,
                    aliases_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    UNIQUE(session_id)
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_execution_reports_user_device
                ON agent_execution_reports(user_id, device_id, created_at DESC)
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS agent_usage_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    requests INTEGER NOT NULL DEFAULT 0,
                    model_name TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_usage_records_user_device
                ON agent_usage_records(user_id, device_id, created_at DESC)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_usage_records_user_created_at
                ON agent_usage_records(user_id, created_at DESC, id DESC)
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS agent_conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT UNIQUE NOT NULL,
                    user_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    terminal_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    tombstone_until TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, device_id, terminal_id)
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_conversations_scope
                ON agent_conversations(user_id, device_id, terminal_id)
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS agent_conversation_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL REFERENCES agent_conversations(conversation_id) ON DELETE CASCADE,
                    event_index INTEGER NOT NULL,
                    event_id TEXT UNIQUE NOT NULL,
                    event_type TEXT NOT NULL,
                    role TEXT NOT NULL,
                    session_id TEXT,
                    question_id TEXT,
                    client_event_id TEXT,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    UNIQUE(conversation_id, event_index)
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_conversation_events_conversation
                ON agent_conversation_events(conversation_id, event_index)
            """)
            await db.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_conversation_events_client_event
                ON agent_conversation_events(conversation_id, client_event_id)
                WHERE client_event_id IS NOT NULL
            """)
            await db.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_conversation_events_answer_question
                ON agent_conversation_events(conversation_id, question_id)
                WHERE event_type = 'answer' AND question_id IS NOT NULL
            """)
            # 增量迁移：truncation_epoch 用于跨端截断检测
            try:
                await db.execute(
                    "ALTER TABLE agent_conversations "
                    "ADD COLUMN truncation_epoch INTEGER DEFAULT 0"
                )
            except Exception:
                pass  # 列已存在，忽略
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

    async def get_pinned_projects(self, username: str, device_id: str) -> List[Dict[str, Any]]:
        """获取指定用户设备的固定项目列表。"""
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT username, device_id, label, cwd, created_at, updated_at
                FROM project_source_pinned_projects
                WHERE username = ? AND device_id = ?
                ORDER BY updated_at DESC, label ASC
                """,
                (username, device_id),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def replace_pinned_projects(
        self,
        username: str,
        device_id: str,
        projects: List[Dict[str, Any]],
    ) -> None:
        """覆盖指定用户设备的固定项目列表。"""
        now = datetime.now(timezone.utc).isoformat()
        async with self._connect() as db:
            await db.execute(
                """
                DELETE FROM project_source_pinned_projects
                WHERE username = ? AND device_id = ?
                """,
                (username, device_id),
            )
            for project in projects:
                await db.execute(
                    """
                    INSERT INTO project_source_pinned_projects (
                        username, device_id, label, cwd, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        username,
                        device_id,
                        project["label"],
                        project["cwd"],
                        now,
                        now,
                    ),
                )
            await db.commit()

    async def get_approved_scan_roots(self, username: str, device_id: str) -> List[Dict[str, Any]]:
        """获取指定用户设备的扫描根目录配置。"""
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT username, device_id, root_path, scan_depth, enabled, created_at, updated_at
                FROM project_source_scan_roots
                WHERE username = ? AND device_id = ?
                ORDER BY updated_at DESC, root_path ASC
                """,
                (username, device_id),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def replace_approved_scan_roots(
        self,
        username: str,
        device_id: str,
        roots: List[Dict[str, Any]],
    ) -> None:
        """覆盖指定用户设备的扫描根目录配置。"""
        now = datetime.now(timezone.utc).isoformat()
        async with self._connect() as db:
            await db.execute(
                """
                DELETE FROM project_source_scan_roots
                WHERE username = ? AND device_id = ?
                """,
                (username, device_id),
            )
            for root in roots:
                await db.execute(
                    """
                    INSERT INTO project_source_scan_roots (
                        username, device_id, root_path, scan_depth, enabled, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        username,
                        device_id,
                        root["root_path"],
                        int(root.get("scan_depth", 2)),
                        1 if root.get("enabled", True) else 0,
                        now,
                        now,
                    ),
                )
            await db.commit()

    async def get_planner_config(self, username: str, device_id: str) -> Optional[Dict[str, Any]]:
        """获取指定用户设备的 planner 配置。"""
        async with self._connect() as db:
            cursor = await db.execute(
                """
                SELECT username, device_id, provider, llm_enabled, endpoint_profile,
                       credentials_mode, requires_explicit_opt_in, created_at, updated_at
                FROM project_source_planner_configs
                WHERE username = ? AND device_id = ?
                """,
                (username, device_id),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def save_planner_config(
        self,
        username: str,
        device_id: str,
        config: Dict[str, Any],
    ) -> None:
        """保存指定用户设备的 planner 配置。"""
        now = datetime.now(timezone.utc).isoformat()
        async with self._connect() as db:
            await db.execute(
                """
                INSERT INTO project_source_planner_configs (
                    username, device_id, provider, llm_enabled, endpoint_profile,
                    credentials_mode, requires_explicit_opt_in, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(username, device_id) DO UPDATE SET
                    provider = excluded.provider,
                    llm_enabled = excluded.llm_enabled,
                    endpoint_profile = excluded.endpoint_profile,
                    credentials_mode = excluded.credentials_mode,
                    requires_explicit_opt_in = excluded.requires_explicit_opt_in,
                    updated_at = excluded.updated_at
                """,
                (
                    username,
                    device_id,
                    config.get("provider", "local_rules"),
                    1 if config.get("llm_enabled", False) else 0,
                    config.get("endpoint_profile", "openai_compatible"),
                    config.get("credentials_mode", "client_secure_storage"),
                    1 if config.get("requires_explicit_opt_in", True) else 0,
                    now,
                    now,
                ),
            )
            await db.commit()

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


async def get_pinned_projects(username: str, device_id: str) -> List[Dict[str, Any]]:
    return await _get_db().get_pinned_projects(username, device_id)


async def replace_pinned_projects(
    username: str,
    device_id: str,
    projects: List[Dict[str, Any]],
) -> None:
    await _get_db().replace_pinned_projects(username, device_id, projects)


async def get_approved_scan_roots(username: str, device_id: str) -> List[Dict[str, Any]]:
    return await _get_db().get_approved_scan_roots(username, device_id)


async def replace_approved_scan_roots(
    username: str,
    device_id: str,
    roots: List[Dict[str, Any]],
) -> None:
    await _get_db().replace_approved_scan_roots(username, device_id, roots)


async def get_planner_config(username: str, device_id: str) -> Optional[Dict[str, Any]]:
    return await _get_db().get_planner_config(username, device_id)


async def save_planner_config(
    username: str,
    device_id: str,
    config: Dict[str, Any],
) -> None:
    await _get_db().save_planner_config(username, device_id, config)


async def save_assistant_planner_run(
    username: str,
    device_id: str,
    payload: Dict[str, Any],
) -> None:
    await _get_db().save_assistant_planner_run(username, device_id, payload)


async def get_assistant_planner_run(
    username: str,
    device_id: str,
    conversation_id: str,
    message_id: str,
) -> Optional[Dict[str, Any]]:
    return await _get_db().get_assistant_planner_run(
        username,
        device_id,
        conversation_id,
        message_id,
    )


async def list_assistant_planner_memory(
    username: str,
    device_id: str,
    memory_type: str,
    *,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    return await _get_db().list_assistant_planner_memory(
        username,
        device_id,
        memory_type,
        limit=limit,
    )


async def report_assistant_execution(
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
    return await _get_db().report_assistant_execution(
        username,
        device_id,
        conversation_id,
        message_id,
        execution_status=execution_status,
        terminal_id=terminal_id,
        failed_step_id=failed_step_id,
        output_summary=output_summary,
        command_sequence=command_sequence,
    )


async def save_agent_execution_report(
    session_id: str,
    user_id: str,
    device_id: str,
    *,
    success: bool,
    executed_command: Optional[str] = None,
    failure_step: Optional[str] = None,
    aliases: Optional[Dict[str, str]] = None,
) -> bool:
    return await _get_db().save_agent_execution_report(
        session_id,
        user_id,
        device_id,
        success=success,
        executed_command=executed_command,
        failure_step=failure_step,
        aliases=aliases,
    )


async def get_agent_execution_report(session_id: str) -> Optional[Dict[str, Any]]:
    return await _get_db().get_agent_execution_report(session_id)


async def get_or_create_agent_conversation(
    user_id: str,
    device_id: str,
    terminal_id: str,
) -> Dict[str, Any]:
    return await _get_db().get_or_create_agent_conversation(user_id, device_id, terminal_id)


async def get_agent_conversation(
    user_id: str,
    device_id: str,
    terminal_id: str,
) -> Optional[Dict[str, Any]]:
    return await _get_db().get_agent_conversation(user_id, device_id, terminal_id)


async def append_agent_conversation_event(
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
    return await _get_db().append_agent_conversation_event(
        user_id,
        device_id,
        terminal_id,
        event_type=event_type,
        role=role,
        payload=payload,
        session_id=session_id,
        question_id=question_id,
        client_event_id=client_event_id,
    )


async def list_agent_conversation_events(
    user_id: str,
    device_id: str,
    terminal_id: str,
    *,
    after_index: Optional[int] = None,
) -> List[Dict[str, Any]]:
    return await _get_db().list_agent_conversation_events(
        user_id,
        device_id,
        terminal_id,
        after_index=after_index,
    )


async def close_agent_conversation(
    user_id: str,
    device_id: str,
    terminal_id: str,
    *,
    payload: Optional[Dict[str, Any]] = None,
    tombstone_seconds: int = 30,
) -> Optional[Dict[str, Any]]:
    return await _get_db().close_agent_conversation(
        user_id,
        device_id,
        terminal_id,
        payload=payload,
        tombstone_seconds=tombstone_seconds,
    )


async def delete_agent_conversation(
    user_id: str,
    device_id: str,
    terminal_id: str,
) -> bool:
    return await _get_db().delete_agent_conversation(user_id, device_id, terminal_id)


async def truncate_agent_conversation_events(
    user_id: str,
    device_id: str,
    terminal_id: str,
    *,
    after_index: int,
) -> int:
    return await _get_db().truncate_agent_conversation_events(
        user_id, device_id, terminal_id, after_index=after_index,
    )


async def cleanup_agent_conversation_tombstones() -> int:
    return await _get_db().cleanup_agent_conversation_tombstones()


async def save_agent_usage(
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
    return await _get_db().save_agent_usage(
        session_id,
        user_id,
        device_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        requests=requests,
        model_name=model_name,
    )


async def get_usage_summary(
    user_id: str,
    device_id: Optional[str] = None,
) -> Dict[str, Any]:
    return await _get_db().get_usage_summary(user_id, device_id)
