"""
Agent 断连清理 — stale 管理 + 资源回收 + TTL 检查

所有依赖直接从源模块导入，不再通过 ws_agent 中转。
"""
import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

from app.store.session import (
    get_session,
    set_session_offline,
    set_session_offline_recoverable,
    list_recoverable_session_terminals,
)
from app.ws.agent_connection import (
    AgentConnection,
    active_agents,
)
from app.infra.message_types import MessageType
from app.ws.agent_request import (
    pending_terminal_creates,
    pending_terminal_closes,
    pending_terminal_snapshots,
    pending_execute_commands,
    pending_lookup_knowledge,
    pending_tool_calls,
    pending_registry,
    _cleanup_execute_command_futures,
    _cleanup_pending_futures_by_id,
    _execute_command_rate_tracker,
)

logger = logging.getLogger(__name__)

# Stale TTL 配置
STALE_TTL_SECONDS = int(os.getenv("STALE_TTL_SECONDS", "90"))  # Agent 断开后等待的秒数
STALE_CHECK_INTERVAL = int(os.getenv("STALE_CHECK_INTERVAL", "10"))  # TTL 检查间隔（秒）

CLEANUP_REASON_AGENT_SHUTDOWN = "agent_shutdown"
CLEANUP_REASON_NETWORK_LOST = "network_lost"
CLEANUP_REASON_DEVICE_OFFLINE = "device_offline"

# Stale Agent 追踪（TTL 机制）
# session_id -> 过期时间（datetime）
stale_agents: dict[str, datetime] = {}


def _cleanup_pending_futures(
    pending_dict: dict[tuple[str, str], asyncio.Future],
    session_id: str,
    reason: str,
) -> None:
    """清理指定 session 的所有 pending futures。"""
    for key, future in list(pending_dict.items()):
        pending_session_id, _ = key
        if pending_session_id != session_id:
            continue
        pending_dict.pop(key, None)
        if not future.done():
            future.set_exception(RuntimeError(f"agent disconnected: {reason}"))


async def _close_agent_conversation_for_terminal(
    session_id: str,
    terminal_id: str,
    reason: str,
) -> None:
    """Best-effort cleanup for terminal-bound Agent conversation on Agent close events."""
    try:
        session = await get_session(session_id)
        user_id = session.get("owner", "")
        device_id = (session.get("device") or {}).get("device_id", "")
        if not user_id or not device_id:
            return

        from app.services.agent_session_manager import get_agent_session_manager
        from app.store.database import close_agent_conversation, get_agent_conversation

        conversation = await get_agent_conversation(user_id, device_id, terminal_id)
        if conversation is None or conversation.get("status") != "active":
            return
        await close_agent_conversation(
            user_id,
            device_id,
            terminal_id,
            payload={"reason": reason},
        )
        active_session = get_agent_session_manager().get_active_terminal_session(
            user_id=user_id,
            device_id=device_id,
            terminal_id=terminal_id,
            conversation_id=conversation["conversation_id"],
        )
        if active_session:
            await get_agent_session_manager().cancel(active_session.id)
    except Exception:
        logger.warning(
            "Failed to close terminal-bound Agent conversation: session_id=%s terminal_id=%s",
            session_id,
            terminal_id,
            exc_info=True,
        )


async def _close_agent_conversations_for_session(session_id: str, reason: str) -> None:
    """Best-effort cleanup for all terminal-bound Agent conversations in a session."""
    try:
        session = await get_session(session_id)
    except Exception:
        logger.warning("Failed to load session for Agent conversation cleanup: %s", session_id, exc_info=True)
        return

    for terminal in session.get("terminals", []) or []:
        terminal_id = terminal.get("terminal_id")
        if terminal_id and terminal.get("status") != "closed":
            await _close_agent_conversation_for_terminal(session_id, terminal_id, reason)


def _mark_agent_stale(session_id: str):
    """
    将 Agent 标记为 stale 状态

    Args:
        session_id: 会话 ID
    """
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=STALE_TTL_SECONDS)
    stale_agents[session_id] = expires_at
    logger.info("Agent marked stale: session_id=%s expires_at=%s", session_id, expires_at.isoformat())


def _is_agent_stale(session_id: str) -> bool:
    """
    检查 Agent 是否处于 stale 状态

    Args:
        session_id: 会话 ID

    Returns:
        是否为 stale 状态
    """
    return session_id in stale_agents


def _clear_agent_stale(session_id: str):
    """
    清除 Agent 的 stale 状态

    Args:
        session_id: 会话 ID
    """
    if session_id in stale_agents:
        del stale_agents[session_id]
        logger.debug("Agent stale cleared: session_id=%s", session_id)


def _uses_immediate_offline_cleanup(reason: str) -> bool:
    return reason == CLEANUP_REASON_AGENT_SHUTDOWN


async def _cleanup_agent(
    session_id: str,
    reason: str = CLEANUP_REASON_AGENT_SHUTDOWN,
):
    """
    清理 Agent 连接

    network_lost 等异常断连进入 stale；agent_shutdown 等显式停止直接 offline。

    Args:
        session_id: 会话 ID
        reason: 断开原因
    """
    if session_id in active_agents:
        del active_agents[session_id]

    _cleanup_pending_futures(pending_terminal_creates, session_id, reason)
    _cleanup_pending_futures(pending_terminal_closes, session_id, reason)
    _cleanup_pending_futures(pending_terminal_snapshots, session_id, reason)
    _cleanup_execute_command_futures(session_id, reason)
    _cleanup_pending_futures_by_id(pending_lookup_knowledge, session_id, reason)
    _cleanup_pending_futures_by_id(pending_tool_calls, session_id, reason)

    # B056: 清理 registry 内部时间戳追踪（dict/future 已由上面旧函数清理）
    pending_registry.clear_timestamps_by_session(session_id)

    # 清理频率限制追踪
    _execute_command_rate_tracker.pop(session_id, None)

    # 主动关闭 Agent（例如桌面端正常退出）不应保留可恢复 terminal。
    if _uses_immediate_offline_cleanup(reason):
        await _set_session_offline_immediately(session_id, reason=reason)
        return

    # 先进入 recoverable offline，再等待 TTL 过期
    try:
        await set_session_offline_recoverable(
            session_id,
            reason=reason,
            grace_seconds=STALE_TTL_SECONDS,
        )
    except Exception as exc:
        logger.error("Failed to mark session offline_recoverable: session_id=%s error=%s", session_id, exc)

    # 将 Agent 标记为 stale（等待 TTL 过期后再真正 offline_expired）
    _mark_agent_stale(session_id)


async def _expire_stale_agent(session_id: str):
    """
    过期 stale Agent，将其真正设为 offline

    Args:
        session_id: 会话 ID
    """
    if session_id in stale_agents:
        del stale_agents[session_id]

    # 原子更新：status=offline + agent_online=False + bulk close terminals
    try:
        await _close_agent_conversations_for_session(session_id, CLEANUP_REASON_DEVICE_OFFLINE)
        await set_session_offline(session_id, reason=CLEANUP_REASON_DEVICE_OFFLINE)
        logger.info("Agent expired from stale to offline_expired: session_id=%s", session_id)
    except Exception as e:
        logger.error("Failed to expire stale agent: session_id=%s error=%s", session_id, e)


async def _stale_agent_ttl_checker():
    """
    Stale Agent TTL 检查器

    定期检查 stale_agents 中的 Agent 是否过期，过期则设为 offline
    """
    while True:
        await asyncio.sleep(STALE_CHECK_INTERVAL)

        now = datetime.now(timezone.utc)
        expired_sessions = []

        for session_id, expires_at in stale_agents.items():
            if now >= expires_at:
                expired_sessions.append(session_id)

        for session_id in expired_sessions:
            await _expire_stale_agent(session_id)


async def _cleanup_agent_immediately(session_id: str):
    """
    立即清理 Agent（不经过 stale 状态）

    用于显式停止等场景。

    Args:
        session_id: 会话 ID
    """
    await _set_session_offline_immediately(
        session_id,
        reason=CLEANUP_REASON_AGENT_SHUTDOWN,
    )


async def _set_session_offline_immediately(
    session_id: str,
    *,
    reason: str,
) -> None:
    """清除 stale 状态并立即把 session/terminals 收口到 offline_expired。"""
    _clear_agent_stale(session_id)
    try:
        await _close_agent_conversations_for_session(session_id, reason)
        await set_session_offline(session_id, reason=reason)
    except Exception as exc:
        logger.error(
            "Failed to mark session offline_expired: session_id=%s reason=%s error=%s",
            session_id,
            reason,
            exc,
        )


async def _restore_recoverable_terminals(session_id: str, agent_conn: AgentConnection):
    """在 agent 重连后恢复 grace period 内的 detached terminals。"""
    try:
        terminals = await list_recoverable_session_terminals(session_id)
    except Exception:
        logger.error(
            "Failed to restore recoverable terminals: session_id=%s",
            session_id,
            exc_info=True,
        )
        return

    for terminal in terminals:
        await agent_conn.send({
            "type": MessageType.CREATE_TERMINAL,
            "terminal_id": terminal["terminal_id"],
            "title": terminal.get("title", terminal["terminal_id"]),
            "cwd": terminal.get("cwd", ""),
            "command": terminal.get("command", "/bin/bash"),
            "env": terminal.get("env", {}) or {},
            "rows": (terminal.get("pty") or {}).get("rows", 24),
            "cols": (terminal.get("pty") or {}).get("cols", 80),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
