"""
SQLite 数据库层 - 用户持久化存储

使用 aiosqlite 异步库管理用户数据。
通过 Database 类封装连接和路径管理，支持依赖注入。
模块级便捷函数委托到默认实例，保持向后兼容。

实体域操作按 Mixin 拆分到各 store 模块：
  - user_store.py         用户 CRUD + 设备管理
  - project_store.py      固定项目 / 扫描根 / Planner 配置
  - planner_store.py      Assistant Planner 运行记录 / Memory
  - execution_store.py    Agent 执行回写
  - conversation_store.py Agent 对话事件 CRUD
  - usage_store.py        使用量统计
"""
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional, Dict, List, Any

import aiosqlite

from ._schema import SCHEMA_STATEMENTS, MIGRATION_STATEMENTS
from .user_store import UserStoreMixin
from .project_store import ProjectStoreMixin
from .planner_store import PlannerStoreMixin
from .execution_store import ExecutionStoreMixin
from .conversation_store import ConversationStoreMixin
from .usage_store import UsageStoreMixin

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "/data/users.db"


class AgentConversationConflict(Exception):
    """Raised when a terminal conversation write conflicts with existing state."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class Database(
    UserStoreMixin,
    ProjectStoreMixin,
    PlannerStoreMixin,
    ExecutionStoreMixin,
    ConversationStoreMixin,
    UsageStoreMixin,
):
    """SQLite 数据库管理器，封装路径、连接和 CRUD 操作。"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init_db(self) -> None:
        """初始化数据库，创建表（如果不存在）。"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        async with self._connect() as db:
            for stmt in SCHEMA_STATEMENTS:
                await db.execute(stmt)
            # 增量迁移
            for stmt in MIGRATION_STATEMENTS:
                try:
                    await db.execute(stmt)
                except Exception:
                    pass  # 已存在则忽略
            await db.commit()
            logger.info(f"Database initialized: {self.db_path}")

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        """内部连接管理器，启用 FK 约束。"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys = ON")
            yield db


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
    event_types: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    return await _get_db().list_agent_conversation_events(
        user_id,
        device_id,
        terminal_id,
        after_index=after_index,
        event_types=event_types,
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
    terminal_id: Optional[str] = None,
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
        terminal_id=terminal_id,
    )


async def get_usage_summary(
    user_id: str,
    device_id: Optional[str] = None,
    terminal_id: Optional[str] = None,
) -> Dict[str, Any]:
    return await _get_db().get_usage_summary(user_id, device_id, terminal_id=terminal_id)
