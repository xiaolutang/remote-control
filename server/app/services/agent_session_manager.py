"""
B080: Agent 会话管理 & SSE 流式 API — 协调入口（R048 B205 拆分）。

管理 Agent 会话的完整生命周期：创建、运行、暂停/唤醒、超时、取消。
通过 SSE (Server-Sent Events) 实时推送 Agent 循环事件。

拆分说明：
- agent_session_types.py — 常量/枚举/异常/辅助函数
- agent_session.py — AgentSession 数据类
- agent_session_runner.py — _run_agent_loop 核心循环
- 本文件 — AgentSessionManager 类 + re-export 协调入口
"""

import asyncio
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from app.store.database import save_agent_usage  # noqa: F401 — re-export for test patch compatibility
from app.infra.event_bus import publish_conversation_stream_event

# 从子模块导入类型与辅助（本模块直接使用 + re-export 保证外部导入不变）
from app.services.agent_session_types import (  # noqa: F401 — 部分 re-export
    SSE_EVENT_TYPES, TOOL_STEP_STATUSES,
    PHASE_THINKING, PHASE_EXPLORING, PHASE_ANALYZING, PHASE_CONFIRMING, PHASE_RESPONDING, PHASE_RESULT,
    _PHASE_DESCRIPTIONS, _MAX_TOOL_STEP_PREVIEW, _MAX_TOOL_STEP_ERROR_PREVIEW,
    SESSION_TIMEOUT_SECONDS, SSE_KEEPALIVE_SECONDS, MAX_CACHED_EVENTS, CLEANUP_INTERVAL_SECONDS,
    USER_SESSION_RATE_LIMIT, USER_SESSION_RATE_WINDOW,
    ErrorCode, AgentSessionState, QuestionEvent, ResultEvent, ErrorEventData,
    _phase_change_event, _streaming_text_event, _tool_step_event, _error_event_dict,
    AgentSessionExpired, AgentSessionCancelled, AgentSessionRateLimited,
)

from app.services.agent_session import AgentSession

logger = logging.getLogger(__name__)


def generate_terminal_session_id(terminal_id: str) -> str:
    """基于 terminal_id 生成确定性 session_id。

    格式: ts-{terminal_id[:16]}
    B051 不变量 #64: session 与 terminal 是 1:1 关系。
    """
    prefix = terminal_id[:16] if len(terminal_id) >= 16 else terminal_id
    return f"ts-{prefix}"


# AgentSessionManager

class AgentSessionManager:
    """管理 Agent 会话生命周期。"""

    def __init__(self, alias_store=None):
        self._sessions: dict[str, AgentSession] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        # 用户级频率追踪: user_id -> [timestamp, ...]
        self._user_rate_tracker: dict[str, list[float]] = defaultdict(list)
        # 别名持久化存储（可选，由外部注入）
        self._alias_store = alias_store

    async def start_cleanup_loop(self) -> None:
        """启动超时清理后台任务。"""
        if self._cleanup_task and not self._cleanup_task.done():
            return
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop_cleanup_loop(self) -> None:
        """停止超时清理后台任务。"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

    async def _cleanup_loop(self) -> None:
        """定期清理超时会话。"""
        while True:
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
            try:
                await self.cleanup_expired()
            except Exception as e:
                logger.error("Cleanup loop error: %s", e, exc_info=True)

    async def cleanup_expired(self) -> list[str]:
        """清理超时会话（10 分钟无交互），返回过期 session_id 列表。"""
        now = datetime.now(timezone.utc)
        expired_ids: list[str] = []

        for session_id, session in list(self._sessions.items()):
            elapsed = (now - session.last_active_at).total_seconds()
            if elapsed >= SESSION_TIMEOUT_SECONDS:
                # 只有 EXPLORING / ASKING 状态需要自动过期
                if session.state in (AgentSessionState.EXPLORING, AgentSessionState.ASKING):
                    expired_ids.append(session_id)

        for session_id in expired_ids:
            session = self._sessions.get(session_id)
            if session is None:
                continue

            session.state = AgentSessionState.EXPIRED
            session.pending_question_id = None
            # 如果有等待中的 ask_user Future，取消它
            if session._pending_question_future and not session._pending_question_future.done():
                session._pending_question_future.set_exception(AgentSessionExpired())

            # 推送超时错误事件
            await self._emit_session_event(
                session,
                "error",
                _error_event_dict(ErrorCode.SESSION_EXPIRED, "会话已超时（10 分钟无交互）"),
            )
            # 发送结束信号
            await session.event_queue.put(None)

            # 取消运行中的 Agent task
            if session._agent_task and not session._agent_task.done():
                session._agent_task.cancel()

            logger.info("Session expired: session_id=%s user=%s", session_id, session.user_id)

        return expired_ids

    def check_user_rate_limit(self, user_id: str) -> bool:
        """检查用户级频率限制。返回 True 允许，False 超频。"""
        now = time.time()
        timestamps = self._user_rate_tracker[user_id]
        cutoff = now - USER_SESSION_RATE_WINDOW
        self._user_rate_tracker[user_id] = [t for t in timestamps if t > cutoff]

        # 计算当前活跃会话数（EXPLORING/ASKING 状态）
        active_count = sum(
            1 for s in self._sessions.values()
            if s.user_id == user_id and s.state in (AgentSessionState.EXPLORING, AgentSessionState.ASKING)
        )

        if active_count >= USER_SESSION_RATE_LIMIT:
            return False

        self._user_rate_tracker[user_id].append(now)
        return True

    async def create_session(
        self,
        intent: str,
        device_id: str,
        user_id: str,
        session_id: Optional[str] = None,
        terminal_id: Optional[str] = None,
        terminal_cwd: Optional[str] = None,
        conversation_id: Optional[str] = None,
        message_history: Optional[list[Any]] = None,
        check_rate_limit: bool = True,
    ) -> AgentSession:
        """创建新的 Agent 会话。超频时抛出 AgentSessionRateLimited。"""
        if check_rate_limit and not self.check_user_rate_limit(user_id):
            raise AgentSessionRateLimited(retry_after=USER_SESSION_RATE_WINDOW)

        sid = session_id or uuid4().hex
        now = datetime.now(timezone.utc)

        session = AgentSession(
            id=sid,
            intent=intent,
            device_id=device_id,
            user_id=user_id,
            state=AgentSessionState.EXPLORING,
            created_at=now,
            last_active_at=now,
            terminal_id=terminal_id,
            terminal_cwd=terminal_cwd,
            conversation_id=conversation_id,
            message_history=message_history,
        )
        self._sessions[sid] = session
        logger.info("Session created: session_id=%s user=%s device=%s", sid, user_id, device_id)
        return session

    async def start_agent(
        self,
        session: AgentSession,
        execute_command_fn,
        ask_user_fn_override=None,
        lookup_knowledge_fn=None,
        tool_call_fn=None,
        dynamic_tools=None,
        include_lookup_knowledge=True,
    ) -> None:
        """启动 Agent 运行循环。"""
        task = asyncio.create_task(
            self._run_agent_loop(
                session, execute_command_fn, ask_user_fn_override,
                lookup_knowledge_fn, tool_call_fn, dynamic_tools,
                include_lookup_knowledge,
            )
        )
        session._agent_task = task

    async def _record_conversation_event(
        self,
        session: AgentSession,
        *,
        event_type: str,
        role: str,
        payload: dict[str, Any],
        question_id: Optional[str] = None,
        client_event_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """持久化终端绑定会话的 conversation event，非绑定返回 None。"""
        if not session.terminal_id or not session.conversation_id:
            return None
        try:
            from app.store.database import append_agent_conversation_event

            return await append_agent_conversation_event(
                session.user_id,
                session.device_id,
                session.terminal_id,
                event_type=event_type,
                role=role,
                payload=payload,
                session_id=session.id,
                question_id=question_id,
                client_event_id=client_event_id,
            )
        except Exception:
            logger.warning(
                "Failed to persist agent conversation event: session_id=%s type=%s",
                session.id,
                event_type,
                exc_info=True,
            )
            if event_type != "error":
                raise
            return None

    async def _emit_session_event(
        self,
        session: AgentSession,
        event_type: str,
        event_data: dict[str, Any],
        *,
        role: str = "assistant",
        question_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        event_record = await self._record_conversation_event(
            session,
            event_type=event_type,
            role=role,
            payload=event_data,
            question_id=question_id,
        )
        await session.event_queue.put((event_type, event_data))
        # Notify conversation stream subscribers (e.g. mobile SSE)
        if event_record and session.terminal_id:
            try:
                await publish_conversation_stream_event(
                    session.user_id,
                    session.device_id,
                    session.terminal_id,
                    event_record,
                )
            except Exception:
                logger.debug(
                    "Failed to publish conversation stream event: session_id=%s type=%s",
                    session.id,
                    event_type,
                    exc_info=True,
                )
        return event_record

    async def _run_agent_loop(
        self,
        session: AgentSession,
        execute_command_fn,
        ask_user_fn_override=None,
        lookup_knowledge_fn=None,
        tool_call_fn=None,
        dynamic_tools=None,
        include_lookup_knowledge=True,
    ) -> None:
        """运行 Agent 主循环——委托给 agent_session_runner.run_agent_loop。"""
        from app.services.agent_session_runner import run_agent_loop as _run_agent_loop

        await _run_agent_loop(
            self,
            session,
            execute_command_fn,
            ask_user_fn_override,
            lookup_knowledge_fn,
            tool_call_fn,
            dynamic_tools,
            include_lookup_knowledge,
        )

    async def respond(
        self,
        session_id: str,
        answer: str,
        *,
        question_id: Optional[str] = None,
    ) -> bool:
        """用户回复 ask_user 问题。返回 True 成功，False 无效。"""
        session = self._sessions.get(session_id)
        if session is None:
            return False
        if session.state != AgentSessionState.ASKING:
            return False
        if question_id is not None and session.pending_question_id != question_id:
            return False
        if session._pending_question_future is None:
            return False
        if session._pending_question_future.done():
            return False

        session._pending_question_future.set_result(answer)
        session._pending_question_future = None
        session.pending_question_id = None
        session.last_active_at = datetime.now(timezone.utc)
        return True

    async def cancel(self, session_id: str) -> bool:
        """取消会话。返回 True 成功，False 会话不存在或已结束。"""
        session = self._sessions.get(session_id)
        if session is None:
            return False
        if session.state in (AgentSessionState.COMPLETED, AgentSessionState.ERROR,
                             AgentSessionState.EXPIRED, AgentSessionState.CANCELLED):
            return False

        session.state = AgentSessionState.CANCELLED
        session.pending_question_id = None
        session.last_active_at = datetime.now(timezone.utc)

        # 取消等待中的 ask_user Future
        if session._pending_question_future and not session._pending_question_future.done():
            session._pending_question_future.set_exception(AgentSessionCancelled())

        # 取消 Agent 运行 task
        if session._agent_task and not session._agent_task.done():
            session._agent_task.cancel()

        # 推送取消事件（如果队列还在消费中）
        await self._emit_session_event(
            session,
            "error",
            _error_event_dict(ErrorCode.SESSION_CANCELLED, "会话已被用户取消"),
        )
        await session.event_queue.put(None)

        logger.info("Session cancelled: session_id=%s", session_id)
        return True

    async def get_session(self, session_id: str) -> Optional[AgentSession]:
        """获取会话。"""
        return self._sessions.get(session_id)

    def get_active_terminal_session(
        self,
        *,
        user_id: str,
        device_id: str,
        terminal_id: str,
        conversation_id: str,
    ) -> Optional[AgentSession]:
        """Return the active in-memory Agent session for a terminal conversation."""
        for session in self._sessions.values():
            if (
                session.user_id == user_id
                and session.device_id == device_id
                and session.terminal_id == terminal_id
                and session.conversation_id == conversation_id
                and session.state in (AgentSessionState.EXPLORING, AgentSessionState.ASKING)
            ):
                return session
        return None

    async def remove_session(self, session_id: str) -> None:
        """移除已结束的会话。"""
        session = self._sessions.pop(session_id, None)
        if session and session._agent_task and not session._agent_task.done():
            session._agent_task.cancel()

    # B051: per-terminal session 生命周期方法

    def get_terminal_session(
        self,
        *,
        user_id: str,
        device_id: str,
        terminal_id: str,
    ) -> Optional[AgentSession]:
        """查找该 terminal 的任意状态 session（不限于 active）。

        用于 per-terminal session_id 复用。
        """
        for session in self._sessions.values():
            if (
                session.user_id == user_id
                and session.device_id == device_id
                and session.terminal_id == terminal_id
            ):
                return session
        return None

    async def reuse_or_create_session(
        self,
        intent: str,
        device_id: str,
        user_id: str,
        *,
        terminal_id: Optional[str] = None,
        terminal_cwd: Optional[str] = None,
        conversation_id: Optional[str] = None,
        message_history: Optional[list[Any]] = None,
        check_rate_limit: bool = True,
    ) -> AgentSession:
        """复用已有 terminal session 或创建新 session。

        B051 不变量 #64: session 与 terminal 是 1:1 关系。
        - 如果该 terminal 有 ACTIVE session（EXPLORING/ASKING）→ 直接返回
        - 如果该 terminal 有 INACTIVE session → 重置状态、递增 run_count
        - 如果该 terminal 有 ended session（COMPLETED/ERROR/EXPIRED/CANCELLED）→ 重置状态
        - 如果无 session → 创建新 session
        """
        existing = self.get_terminal_session(
            user_id=user_id, device_id=device_id, terminal_id=terminal_id,
        ) if terminal_id else None

        if existing:
            # Active session → 直接返回（不新增 run）
            if existing.state in (AgentSessionState.EXPLORING, AgentSessionState.ASKING):
                return existing

            # Inactive/ended session → 重置状态
            existing.state = AgentSessionState.EXPLORING
            existing.intent = intent
            existing.run_count += 1
            existing.is_first_run = False
            existing.current_run_id = uuid4().hex
            existing.last_active_at = datetime.now(timezone.utc)
            existing.pending_question_id = None
            existing.result = None
            existing.message_history = message_history
            if terminal_cwd is not None:
                existing.terminal_cwd = terminal_cwd
            # 重建 event_queue（清空旧事件）
            existing.event_queue = asyncio.Queue()
            existing._last_events = []
            existing._stream_ref_count = 0
            # 取消残留的 agent task
            if existing._agent_task and not existing._agent_task.done():
                existing._agent_task.cancel()
            existing._agent_task = None
            existing._pending_question_future = None

            logger.info(
                "Session reused: session_id=%s run_count=%d terminal=%s",
                existing.id, existing.run_count, terminal_id,
            )
            return existing

        # 无现有 session → 创建新 session
        return await self.create_session(
            intent=intent,
            device_id=device_id,
            user_id=user_id,
            terminal_id=terminal_id,
            terminal_cwd=terminal_cwd,
            conversation_id=conversation_id,
            message_history=message_history,
            check_rate_limit=check_rate_limit,
        )

    async def remove_terminal_sessions(
        self,
        device_id: str,
        terminal_id: str,
    ) -> list[str]:
        """删除该 terminal 的所有 session（终端删除时调用）。

        返回被移除的 session_id 列表。
        """
        removed = []
        for sid, session in list(self._sessions.items()):
            if session.device_id == device_id and session.terminal_id == terminal_id:
                if session._agent_task and not session._agent_task.done():
                    session._agent_task.cancel()
                del self._sessions[sid]
                removed.append(sid)
        return removed

    async def mark_session_inactive(self, session_id: str) -> None:
        """将 session 标记为 inactive（终端非删除关闭时调用）。"""
        session = self._sessions.get(session_id)
        if session is None:
            return
        # 取消运行中的 agent task
        if session._agent_task and not session._agent_task.done():
            session._agent_task.cancel()
        # 取消等待中的 future
        if session._pending_question_future and not session._pending_question_future.done():
            session._pending_question_future.set_exception(AgentSessionCancelled())
        session.state = AgentSessionState.INACTIVE
        session.pending_question_id = None
        session._pending_question_future = None
        logger.info("Session marked inactive: session_id=%s", session_id)

    def get_session_count(self) -> int:
        """获取当前活跃会话数。"""
        return len(self._sessions)

    # SSE 流生成

    async def sse_stream(self, session: AgentSession) -> None:
        """生成 SSE 事件流（async generator）。不变量 #60: 7 种合法事件类型。"""
        session._stream_ref_count += 1
        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        session.event_queue.get(),
                        timeout=SSE_KEEPALIVE_SECONDS,
                    )
                except asyncio.TimeoutError:
                    # keepalive 注释帧
                    yield ": keepalive\n\n"
                    continue

                if event is None:
                    # 结束信号
                    break

                event_type, event_data = event
                data_json = json.dumps(event_data, ensure_ascii=False)
                yield f"event: {event_type}\ndata: {data_json}\n\n"

                # 缓存最近事件用于断连恢复
                session._last_events.append(event)
                if len(session._last_events) > session.max_cached_events:
                    session._last_events = session._last_events[-session.max_cached_events:]
        finally:
            session._stream_ref_count -= 1

    async def resume_stream(self, session: AgentSession, *, after_index: int = 0) -> None:
        """断连恢复：先回放缓存事件，再继续实时流。"""
        # 先回放缓存的事件
        cached = session._last_events[after_index:]
        for event in cached:
            if event is None:
                break
            event_type, event_data = event
            data_json = json.dumps(event_data, ensure_ascii=False)
            yield f"event: {event_type}\ndata: {data_json}\n\n"

        # 如果会话已经结束（已有结束信号），不再进入实时流
        if session.state in (AgentSessionState.COMPLETED, AgentSessionState.ERROR,
                             AgentSessionState.EXPIRED, AgentSessionState.CANCELLED):
            return

        # 继续实时流
        async for chunk in self.sse_stream(session):
            yield chunk

# 全局单例
_manager: Optional[AgentSessionManager] = None


def get_agent_session_manager(alias_store=None) -> AgentSessionManager:
    """获取全局 AgentSessionManager 实例。

    Args:
        alias_store: 可选的 ProjectAliasStore 实例，仅在首次创建时生效
    """
    global _manager
    if _manager is None:
        _manager = AgentSessionManager(alias_store=alias_store)
    return _manager


# Re-export：保证 `from app.services.agent_session_manager import X` 不变

__all__ = [
    "SSE_EVENT_TYPES", "TOOL_STEP_STATUSES",
    "PHASE_THINKING", "PHASE_EXPLORING", "PHASE_ANALYZING", "PHASE_CONFIRMING", "PHASE_RESPONDING", "PHASE_RESULT",
    "SESSION_TIMEOUT_SECONDS", "SSE_KEEPALIVE_SECONDS", "MAX_CACHED_EVENTS", "CLEANUP_INTERVAL_SECONDS",
    "USER_SESSION_RATE_LIMIT", "USER_SESSION_RATE_WINDOW",
    "ErrorCode", "AgentSessionState", "AgentSession", "AgentSessionManager",
    "QuestionEvent", "ResultEvent", "ErrorEventData",
    "AgentSessionExpired", "AgentSessionCancelled", "AgentSessionRateLimited",
    "_error_event_dict", "_phase_change_event", "_streaming_text_event", "_tool_step_event",
    "get_agent_session_manager", "generate_terminal_session_id",
]
