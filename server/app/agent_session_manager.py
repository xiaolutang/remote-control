"""
B080: Agent 会话管理 & SSE 流式 API。

管理 Agent 会话的完整生命周期：创建、运行、暂停/唤醒、超时、取消。
通过 SSE (Server-Sent Events) 实时推送 Agent 循环事件。

架构约束：
- 不变量 #43: 产物收口为 CommandSequence（AgentResult）
- 不变量 #50: 不展示模型原始 chain-of-thought。streaming_text 为逐 token 推送
- 不变量 #52: 用户级限流 + provider timeout
- 不变量 #60: Agent SSE 采用阶段驱动模型，6 种事件类型：
  session_created, phase_change, streaming_text, tool_step, question, result, error
- 权威边界: Server Terminal Agent 管理 SSE 流推送
"""

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from app.database import save_agent_usage
from app.terminal_agent import AgentResult, AgentUserFacingError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# B103: SSE 事件类型定义（不变量 #60）
# ---------------------------------------------------------------------------

# 7 种合法 SSE 事件类型
SSE_EVENT_TYPES = frozenset({
    "session_created",   # 由 runtime_api.py SSE 端点产生
    "phase_change",      # 阶段切换（B104 填充）
    "streaming_text",    # 逐 token 文本推送（B105 填充）
    "tool_step",         # 工具调用步骤（B106 填充）
    "question",          # Agent 向用户提问
    "result",            # Agent 最终结果
    "error",             # 错误事件
})

# tool_step 事件中 status 字段的合法值
TOOL_STEP_STATUSES = frozenset({"running", "done", "error"})

# B104: Phase 常量定义
PHASE_THINKING = "THINKING"        # Agent 启动，正在分析意图
PHASE_EXPLORING = "EXPLORING"      # 正在执行工具/命令探索环境
PHASE_ANALYZING = "ANALYZING"      # 正在分析工具执行结果
PHASE_CONFIRMING = "CONFIRMING"    # 等待用户确认（ask_user 工具）
PHASE_RESPONDING = "RESPONDING"    # 正在生成回复（文本输出）
PHASE_RESULT = "RESULT"            # 完成，已交付结果

# Phase 描述映射
_PHASE_DESCRIPTIONS: dict[str, str] = {
    PHASE_THINKING: "正在分析你的意图...",
    PHASE_EXPLORING: "正在探索环境...",
    PHASE_ANALYZING: "正在分析结果...",
    PHASE_CONFIRMING: "等待确认...",
    PHASE_RESPONDING: "正在生成回复...",
    PHASE_RESULT: "完成",
}

# tool_step 事件中命令输出预览的最大字符数
_MAX_TOOL_STEP_PREVIEW = 1000
_MAX_TOOL_STEP_ERROR_PREVIEW = 200

# B105: CoT 检测模式（增量过滤用，不变量 #50 兜底）
_COT_PATTERNS: list[str] = [
    "一步步思考", "推理过程", "思考步骤", "让我想想",
    "step by step", "thinking process", "chain of thought",
    "首先我需要", "接下来我要", "我的分析是",
    "let me think", "let's analyze", "reasoning:",
    "<think", "<thought", "<reasoning",
]


# ---------------------------------------------------------------------------
# 会话超时 & 频率限制常量
# ---------------------------------------------------------------------------

SESSION_TIMEOUT_SECONDS = 600       # 10 分钟无交互超时
SSE_KEEPALIVE_SECONDS = 15          # SSE keepalive 间隔
MAX_CACHED_EVENTS = 100             # 断连恢复缓存最近事件数
CLEANUP_INTERVAL_SECONDS = 30       # 超时清理检查间隔

# 频率限制
USER_SESSION_RATE_LIMIT = 5         # 每用户最多同时进行的会话数
USER_SESSION_RATE_WINDOW = 60       # 频率限制窗口（秒）


# ---------------------------------------------------------------------------
# 错误码定义
# ---------------------------------------------------------------------------

class ErrorCode:
    """6 种明确错误码。"""
    AGENT_OFFLINE = "AGENT_OFFLINE"             # Agent 设备离线
    SESSION_EXPIRED = "SESSION_EXPIRED"         # 会话超时
    SESSION_CANCELLED = "SESSION_CANCELLED"     # 会话被用户取消
    AGENT_ERROR = "AGENT_ERROR"                 # Agent 运行出错
    RATE_LIMITED = "RATE_LIMITED"               # 频率超限
    INTERNAL_ERROR = "INTERNAL_ERROR"           # 内部错误


# ---------------------------------------------------------------------------
# 状态枚举
# ---------------------------------------------------------------------------

class AgentSessionState(str, Enum):
    """Agent 会话状态。"""
    EXPLORING = "exploring"      # Agent 正在执行探索命令
    ASKING = "asking"            # Agent 等待用户回复
    COMPLETED = "completed"      # Agent 完成，有结果
    ERROR = "error"              # Agent 出错
    EXPIRED = "expired"          # 会话超时
    CANCELLED = "cancelled"      # 用户取消


# ---------------------------------------------------------------------------
# SSE 事件数据类
# ---------------------------------------------------------------------------

@dataclass
class QuestionEvent:
    """Agent 向用户提问。"""
    question: str
    options: list[str]
    multi_select: bool


@dataclass
class ResultEvent:
    """Agent 最终结果。"""
    summary: str
    steps: list[dict]       # CommandSequenceStep as dict
    provider: str
    source: str
    need_confirm: bool
    aliases: dict[str, str]
    usage: Optional[dict[str, Any]] = None


@dataclass
class ErrorEventData:
    """错误事件数据。"""
    code: str               # ErrorCode 中的值
    message: str


# ---------------------------------------------------------------------------
# B103: 新 SSE 事件类型辅助函数（框架，具体逻辑由 B104/B105/B106 填充）
# ---------------------------------------------------------------------------

def _phase_change_event(phase: str, description: str = "") -> dict[str, Any]:
    """构造 phase_change 事件数据。"""
    return {"phase": phase, "description": description}


def _streaming_text_event(text_delta: str) -> dict[str, Any]:
    """构造 streaming_text 事件数据。"""
    return {"text_delta": text_delta}


def _tool_step_event(
    tool_name: str,
    description: str = "",
    status: str = "running",
    result_summary: str = "",
) -> dict[str, Any]:
    """构造 tool_step 事件数据。"""
    if status not in TOOL_STEP_STATUSES:
        status = "running"
    return {
        "tool_name": tool_name,
        "description": description,
        "status": status,
        "result_summary": result_summary,
    }


# ---------------------------------------------------------------------------
# AgentSession
# ---------------------------------------------------------------------------

@dataclass
class AgentSession:
    """单个 Agent 会话的完整状态。"""
    id: str
    intent: str
    device_id: str
    user_id: str
    state: AgentSessionState
    created_at: datetime
    last_active_at: datetime
    terminal_id: Optional[str] = None
    terminal_cwd: Optional[str] = None
    conversation_id: Optional[str] = None
    pending_question_id: Optional[str] = None
    message_history: Optional[list[Any]] = None
    result: Optional[AgentResult] = None

    # SSE 事件队列（用于流式推送）
    event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)

    # ask_user 回复 Future
    _pending_question_future: Optional[asyncio.Future] = field(default=None, repr=False)

    # Agent 运行 task
    _agent_task: Optional[asyncio.Task] = field(default=None, repr=False)

    # 断连恢复：缓存最近事件
    _last_events: list = field(default_factory=list)

    # 流引用计数（有多少个 SSE 连接在消费此会话）
    _stream_ref_count: int = field(default=0, repr=False)

    @property
    def max_cached_events(self) -> int:
        return MAX_CACHED_EVENTS


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class AgentSessionExpired(Exception):
    """会话超时异常。"""
    pass


class AgentSessionCancelled(Exception):
    """会话取消异常。"""
    pass


class AgentSessionRateLimited(Exception):
    """频率超限异常。"""
    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(f"Rate limited, retry after {retry_after}s")


# ---------------------------------------------------------------------------
# AgentSessionManager
# ---------------------------------------------------------------------------

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
        """清理超时会话（10 分钟无交互）。

        Returns:
            过期清理的 session_id 列表
        """
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
        """检查用户级频率限制。

        Args:
            user_id: 用户 ID

        Returns:
            True 如果允许，False 如果超频
        """
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
        """创建新的 Agent 会话。

        Args:
            intent: 用户意图
            device_id: 设备 ID
            user_id: 用户 ID
            session_id: 可选的会话 ID（默认自动生成）

        Returns:
            创建的 AgentSession

        Raises:
            AgentSessionRateLimited: 超过频率限制
        """
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
        """启动 Agent 运行循环。

        Args:
            session: AgentSession 实例
            execute_command_fn: (session_id, command, cwd) -> ExecuteCommandResult
            ask_user_fn_override: 可选覆盖 ask_user 回调
            lookup_knowledge_fn: 可选知识检索回调 (query) -> str
            tool_call_fn: 可选动态工具调用回调 (session_id, tool_name, arguments) -> dict
            dynamic_tools: 可用动态工具目录
            include_lookup_knowledge: 是否注册 lookup_knowledge（基于 Agent 版本门控）
        """
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
        """Persist terminal-bound conversation events when the session is bound.

        Returns the persisted event dict (with event_index, event_id, etc.)
        or None if the session is not terminal-bound.
        """
        if not session.terminal_id or not session.conversation_id:
            return None
        try:
            from app.database import append_agent_conversation_event

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
    ) -> None:
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
                from app.runtime_api import _publish_conversation_stream_event

                await _publish_conversation_stream_event(
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
        """运行 Agent 主循环，将事件推入 event_queue。"""
        try:
            # 延迟导入避免循环依赖
            from app.terminal_agent import run_agent

            async def _execute_command_callback(session_id, command, cwd=None):
                """Agent 执行命令回调：推送 tool_step 事件。"""
                # 默认使用终端 CWD
                effective_cwd = cwd or session.terminal_cwd
                # B104: 工具调用开始 → EXPLORING
                await _emit_phase_change(PHASE_EXPLORING)
                # 推送执行前的 tool_step（status=running）
                await self._emit_session_event(
                    session,
                    "tool_step",
                    _tool_step_event(
                        tool_name="execute_command",
                        description=f"执行: {command[:60]}",
                        status="running",
                    ),
                )
                session.last_active_at = datetime.now(timezone.utc)
                session.state = AgentSessionState.EXPLORING

                # 调用实际的 execute_command
                result = await execute_command_fn(session.device_id, command, cwd=effective_cwd)

                # 推送执行后的 tool_step（status=done）
                output_preview = (
                    result.stdout[:_MAX_TOOL_STEP_PREVIEW]
                    if result and result.stdout
                    else ""
                )
                error_status = "done"
                if result and result.stderr:
                    output_preview += (
                        f" [stderr: {result.stderr[:_MAX_TOOL_STEP_ERROR_PREVIEW]}]"
                    )
                    if result.exit_code != 0:
                        error_status = "error"

                await self._emit_session_event(
                    session,
                    "tool_step",
                    _tool_step_event(
                        tool_name="execute_command",
                        description=f"执行: {command[:60]}",
                        status=error_status,
                        result_summary=output_preview or "(无输出)",
                    ),
                )

                session.last_active_at = datetime.now(timezone.utc)
                # B104: 工具调用完成 → ANALYZING
                await _emit_phase_change(PHASE_ANALYZING)
                return result

            async def _ask_user_callback(question, options, multi_select):
                """Agent 向用户提问回调。"""
                loop = asyncio.get_running_loop()
                future = loop.create_future()
                session._pending_question_future = future

                # B104: ask_user → CONFIRMING
                await _emit_phase_change(PHASE_CONFIRMING)
                session.state = AgentSessionState.ASKING
                session.last_active_at = datetime.now(timezone.utc)
                question_id = f"q_{uuid4().hex}"
                session.pending_question_id = question_id

                # B106: 推送 tool_step(running) — ask_user
                await self._emit_session_event(
                    session,
                    "tool_step",
                    _tool_step_event(
                        tool_name="ask_user",
                        description="向用户提问",
                        status="running",
                    ),
                )

                # 推送 QuestionEvent
                await self._emit_session_event(
                    session,
                    "question",
                    {
                        "question_id": question_id,
                        "question": question,
                        "options": options or [],
                        "multi_select": multi_select,
                    },
                    question_id=question_id,
                )

                # 等待回复（带超时）
                try:
                    answer = await asyncio.wait_for(future, timeout=SESSION_TIMEOUT_SECONDS)
                    session.pending_question_id = None
                    session.last_active_at = datetime.now(timezone.utc)
                    session.state = AgentSessionState.EXPLORING
                    # B106: 推送 tool_step(done) — ask_user 收到回复
                    answer_summary = str(answer)[:200] if answer else "(无回复)"
                    await self._emit_session_event(
                        session,
                        "tool_step",
                        _tool_step_event(
                            tool_name="ask_user",
                            description="向用户提问",
                            status="done",
                            result_summary=answer_summary,
                        ),
                    )
                    return answer
                except asyncio.TimeoutError:
                    # B106: 推送 tool_step(error) — 超时
                    await self._emit_session_event(
                        session,
                        "tool_step",
                        _tool_step_event(
                            tool_name="ask_user",
                            description="向用户提问",
                            status="error",
                            result_summary="timeout",
                        ),
                    )
                    raise AgentSessionExpired()
                except AgentSessionCancelled:
                    # B106: 推送 tool_step(error) — 取消
                    await self._emit_session_event(
                        session,
                        "tool_step",
                        _tool_step_event(
                            tool_name="ask_user",
                            description="向用户提问",
                            status="error",
                            result_summary="cancelled",
                        ),
                    )
                    raise

            # 使用覆盖回调或默认回调
            ask_fn = ask_user_fn_override or _ask_user_callback

            # 加载已知别名（Agent 启动时注入 ProjectContext）
            known_aliases: dict[str, str] = {}
            if self._alias_store:
                try:
                    known_aliases = await self._alias_store.list_all(
                        session.user_id, session.device_id,
                    )
                except Exception as e:
                    logger.warning("Failed to load aliases: %s", e)

            # tool_step 包装：lookup_knowledge（含 duration）
            async def _traced_lookup_knowledge(query):
                t_start = time.monotonic()
                # B104: 工具调用开始 → EXPLORING
                await _emit_phase_change(PHASE_EXPLORING)
                await self._emit_session_event(
                    session, "tool_step",
                    _tool_step_event(
                        tool_name="lookup_knowledge",
                        description=f"搜索知识库: {query[:60]}",
                        status="running",
                    ),
                )
                result = ""
                error_category = None
                try:
                    if lookup_knowledge_fn:
                        result = await lookup_knowledge_fn(query)
                except Exception as e:
                    error_category = type(e).__name__
                    duration_ms = int((time.monotonic() - t_start) * 1000)
                    await self._emit_session_event(
                        session, "tool_step",
                        _tool_step_event(
                            tool_name="lookup_knowledge",
                            description=f"搜索知识库: {query[:60]}",
                            status="error",
                            result_summary=f"error: {error_category} ({duration_ms}ms)",
                        ),
                    )
                    raise
                duration_ms = int((time.monotonic() - t_start) * 1000)
                await self._emit_session_event(
                    session, "tool_step",
                    _tool_step_event(
                        tool_name="lookup_knowledge",
                        description=f"搜索知识库: {query[:60]}",
                        status="done",
                        result_summary=(result or "(无结果)")[:200],
                    ),
                )
                # B104: 工具调用完成 → ANALYZING
                await _emit_phase_change(PHASE_ANALYZING)
                return result

            # tool_step 包装：call_dynamic_tool（含 duration + error category）
            def _classify_tool_error(error_msg: str) -> str:
                msg = error_msg.lower()
                if "timeout" in msg:
                    return "timeout"
                if "disconnect" in msg or "offline" in msg or "connection" in msg:
                    return "crash"
                if "not found" in msg or "unknown tool" in msg:
                    return "not_found"
                if "invalid" in msg or "arg" in msg:
                    return "invalid_args"
                return "unknown"

            async def _traced_tool_call(tool_name, arguments):
                t_start = time.monotonic()
                # B104: 工具调用开始 → EXPLORING
                await _emit_phase_change(PHASE_EXPLORING)
                await self._emit_session_event(
                    session, "tool_step",
                    _tool_step_event(
                        tool_name=f"call_dynamic_tool:{tool_name}",
                        description=f"调用 {tool_name}",
                        status="running",
                    ),
                )
                result = {"status": "error", "error": "tool_call_fn not available"}
                error_category = "not_found" if not tool_call_fn else None
                if tool_call_fn:
                    try:
                        result = await tool_call_fn(tool_name, arguments)
                    except asyncio.TimeoutError:
                        error_category = "timeout"
                        result = {"status": "error", "error": "timeout"}
                    except ConnectionError:
                        error_category = "crash"
                        result = {"status": "error", "error": "agent disconnected"}
                    except Exception as e:
                        error_category = _classify_tool_error(str(e))
                        result = {"status": "error", "error": str(e)}
                # 解析 ws 层返回的 error dict
                if error_category is None and result.get("status") == "error":
                    error_category = _classify_tool_error(result.get("error", ""))
                duration_ms = int((time.monotonic() - t_start) * 1000)
                output_preview = result.get("result", result.get("error", ""))[:200]
                step_status = "error" if error_category else "done"
                await self._emit_session_event(
                    session, "tool_step",
                    _tool_step_event(
                        tool_name=f"call_dynamic_tool:{tool_name}",
                        description=f"调用 {tool_name}",
                        status=step_status,
                        result_summary=output_preview or "(无输出)",
                    ),
                )
                # B104: 工具调用完成 → ANALYZING
                await _emit_phase_change(PHASE_ANALYZING)
                return result

            # B104: Phase 推断状态追踪
            _current_phase: str = ""

            async def _emit_phase_change(phase: str, description: str = "") -> None:
                """B104: 推送 phase_change 事件（去重：相同 phase 不重复 emit）。"""
                nonlocal _current_phase
                if phase == _current_phase:
                    return
                _current_phase = phase
                desc = description or _PHASE_DESCRIPTIONS.get(phase, "")
                await self._emit_session_event(
                    session,
                    "phase_change",
                    _phase_change_event(phase, desc),
                )

            # Agent 启动 → THINKING
            await _emit_phase_change(PHASE_THINKING)

            # B105: CoT 增量过滤状态
            _cot_detected: bool = False
            _streamed_text_buffer: str = ""  # 已推送的文本累积（用于 CoT 截断）

            # B105: on_model_text 回调——逐 token 推送 streaming_text SSE
            async def _on_model_text(text: str):
                """模型文本输出回调：逐 token 推送 streaming_text SSE 事件。

                B105 改动：从 PartEndEvent 完整推送改为 PartDeltaEvent 逐 token 推送。
                CoT 过滤策略：增量检测，发现 CoT 标记后截断并设置 _cot_detected 标志。
                """
                nonlocal _cot_detected, _streamed_text_buffer

                if _cot_detected:
                    return
                if not text:
                    return

                # 增量检查 CoT 标记
                text_lower = text.lower()
                for pattern in _COT_PATTERNS:
                    pattern_lower = pattern.lower()
                    if pattern_lower in text_lower:
                        _cot_detected = True
                        logger.info(
                            "streaming_text CoT pattern detected: pattern=%r", pattern,
                        )
                        return

                # 空白 delta：只有换行/空格时不推送，但累积到 buffer
                stripped = text.strip()
                if not stripped:
                    return

                # 文本输出 → RESPONDING
                await _emit_phase_change(PHASE_RESPONDING)
                _streamed_text_buffer += stripped
                await self._emit_session_event(
                    session,
                    "streaming_text",
                    _streaming_text_event(stripped),
                )

            # 调用 run_agent
            outcome = await run_agent(
                intent=session.intent,
                session_id=session.device_id,
                execute_command_fn=_execute_command_callback,
                ask_user_fn=ask_fn,
                project_aliases=known_aliases,
                message_history=session.message_history,
                lookup_knowledge_fn=_traced_lookup_knowledge if lookup_knowledge_fn else None,
                tool_call_fn=_traced_tool_call if tool_call_fn else None,
                dynamic_tools=dynamic_tools,
                include_lookup_knowledge=include_lookup_knowledge,
                on_model_text=_on_model_text,
            )

            # 保存 Agent 发现的别名
            if self._alias_store and outcome.result.aliases:
                try:
                    await self._alias_store.save_batch(
                        session.user_id, session.device_id, outcome.result.aliases,
                    )
                except Exception as e:
                    logger.warning("Failed to save aliases: %s", e)

            # usage 必须先落库，再向 SSE 推送 result/error 事件
            usage_payload = {
                "input_tokens": outcome.input_tokens,
                "output_tokens": outcome.output_tokens,
                "total_tokens": outcome.total_tokens,
                "requests": outcome.requests,
                "model_name": outcome.model_name,
            }
            saved_usage = await save_agent_usage(
                session.id,
                session.user_id,
                session.device_id,
                input_tokens=outcome.input_tokens,
                output_tokens=outcome.output_tokens,
                total_tokens=outcome.total_tokens,
                requests=outcome.requests,
                model_name=outcome.model_name,
            )
            if not saved_usage:
                logger.warning(
                    "Agent usage persistence skipped: session_id=%s user=%s device=%s",
                    session.id,
                    session.user_id,
                    session.device_id,
                )

            # B106: response_type="error" 走 error SSE 通道（模型未调用 deliver_result 的兜底）
            if outcome.result.response_type == "error":
                # B104: deliver_result → RESULT
                await _emit_phase_change(PHASE_RESULT)
                session.state = AgentSessionState.ERROR
                session.pending_question_id = None
                session.last_active_at = datetime.now(timezone.utc)
                await self._emit_session_event(
                    session,
                    "error",
                    {
                        "code": ErrorCode.AGENT_ERROR,
                        "message": outcome.result.summary,
                        "usage": usage_payload,
                    },
                )
            else:
                # 推送 ResultEvent
                # B104: deliver_result → RESULT
                await _emit_phase_change(PHASE_RESULT)
                session.state = AgentSessionState.COMPLETED
                session.result = outcome.result
                session.last_active_at = datetime.now(timezone.utc)

                await self._emit_session_event(
                    session,
                    "result",
                    {
                        "summary": outcome.result.summary,
                        "steps": [step.model_dump() for step in outcome.result.steps],
                        "response_type": outcome.result.response_type,
                        "ai_prompt": outcome.result.ai_prompt,
                        "provider": outcome.result.provider,
                        "source": outcome.result.source,
                        "need_confirm": outcome.result.need_confirm,
                        "aliases": outcome.result.aliases,
                        "usage": usage_payload,
                    },
                )

        except AgentSessionExpired:
            session.state = AgentSessionState.EXPIRED
            session.pending_question_id = None
            await self._emit_session_event(
                session,
                "error",
                _error_event_dict(ErrorCode.SESSION_EXPIRED, "会话已超时"),
            )
        except AgentSessionCancelled:
            session.state = AgentSessionState.CANCELLED
            session.pending_question_id = None
            await self._emit_session_event(
                session,
                "error",
                _error_event_dict(ErrorCode.SESSION_CANCELLED, "会话已取消"),
            )
        except asyncio.CancelledError:
            session.state = AgentSessionState.CANCELLED
            session.pending_question_id = None
            await self._emit_session_event(
                session,
                "error",
                _error_event_dict(ErrorCode.SESSION_CANCELLED, "会话已取消"),
            )
        except AgentUserFacingError as e:
            logger.warning(
                "Agent user-facing error: session_id=%s error=%s",
                session.id, e,
            )
            session.state = AgentSessionState.ERROR
            session.pending_question_id = None
            await self._emit_session_event(
                session,
                "error",
                _error_event_dict(ErrorCode.AGENT_ERROR, str(e)),
            )
        except Exception as e:
            logger.error(
                "Agent loop error: session_id=%s error=%s",
                session.id, e, exc_info=True,
            )
            session.state = AgentSessionState.ERROR
            session.pending_question_id = None
            await self._emit_session_event(
                session,
                "error",
                _error_event_dict(ErrorCode.AGENT_ERROR, f"Agent 运行出错: {type(e).__name__}: {e}"),
            )
        finally:
            # 发送结束信号
            await session.event_queue.put(None)

    async def respond(
        self,
        session_id: str,
        answer: str,
        *,
        question_id: Optional[str] = None,
    ) -> bool:
        """用户回复 ask_user 的问题。唤醒阻塞的 Future。

        Args:
            session_id: 会话 ID
            answer: 用户回复内容

        Returns:
            True 如果成功唤醒，False 如果会话不存在或没有等待中的问题
        """
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
        """取消会话。

        Args:
            session_id: 会话 ID

        Returns:
            True 如果成功取消，False 如果会话不存在或已结束
        """
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

    def get_session_count(self) -> int:
        """获取当前活跃会话数。"""
        return len(self._sessions)

    # -----------------------------------------------------------------------
    # SSE 流生成
    # -----------------------------------------------------------------------

    async def sse_stream(self, session: AgentSession) -> None:
        """生成 SSE 事件流（async generator）。

        Yields SSE 格式字符串:
          - event: tool_step / streaming_text / phase_change / question / result / error
          - : keepalive（注释帧）

        不变量 #60: 7 种合法事件类型
          session_created（由 runtime_api.py 产生）、phase_change、streaming_text、
          tool_step、question、result、error
        """
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
        """断连恢复：先回放缓存事件，再继续实时流。

        Args:
            session: AgentSession 实例
            after_index: 从哪个事件索引开始回放（0=全部回放）
        """
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


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _error_event_dict(code: str, message: str) -> dict:
    """构造错误事件字典。"""
    return {
        "code": code,
        "message": message,
    }


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

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
