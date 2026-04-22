"""
SQLite 数据库层 - 用户持久化存储

使用 aiosqlite 异步库管理用户数据。
通过 Database 类封装连接和路径管理，支持依赖注入。
模块级便捷函数委托到默认实例，保持向后兼容。
"""
import os
import logging
import json
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
