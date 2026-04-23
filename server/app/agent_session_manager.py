"""
B080: Agent 会话管理 & SSE 流式 API。

管理 Agent 会话的完整生命周期：创建、运行、暂停/唤醒、超时、取消。
通过 SSE (Server-Sent Events) 实时推送 Agent 循环事件。

架构约束：
- 不变量 #43: 产物收口为 CommandSequence（AgentResult）
- 不变量 #50: 不展示模型原始 chain-of-thought
- 不变量 #51: 每次规划必须有可回放 trace
- 不变量 #52: 用户级限流 + provider timeout
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

from app.terminal_agent import AgentResult

logger = logging.getLogger(__name__)


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
class TraceEvent:
    """Agent 探索过程追踪。"""
    tool: str              # "execute_command" | "think"
    input_summary: str     # 命令或思考摘要
    output_summary: str    # 输出摘要


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


@dataclass
class ErrorEventData:
    """错误事件数据。"""
    code: str               # ErrorCode 中的值
    message: str


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
            # 如果有等待中的 ask_user Future，取消它
            if session._pending_question_future and not session._pending_question_future.done():
                session._pending_question_future.set_exception(AgentSessionExpired())

            # 推送超时错误事件
            await session.event_queue.put((
                "error",
                _error_event_dict(ErrorCode.SESSION_EXPIRED, "会话已超时（10 分钟无交互）"),
            ))
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
        if not self.check_user_rate_limit(user_id):
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
        )
        self._sessions[sid] = session
        logger.info("Session created: session_id=%s user=%s device=%s", sid, user_id, device_id)
        return session

    async def start_agent(
        self,
        session: AgentSession,
        execute_command_fn,
        ask_user_fn_override=None,
    ) -> None:
        """启动 Agent 运行循环。

        Args:
            session: AgentSession 实例
            execute_command_fn: (session_id, command, cwd) -> ExecuteCommandResult
            ask_user_fn_override: 可选覆盖 ask_user 回调
        """
        task = asyncio.create_task(
            self._run_agent_loop(session, execute_command_fn, ask_user_fn_override)
        )
        session._agent_task = task

    async def _run_agent_loop(
        self,
        session: AgentSession,
        execute_command_fn,
        ask_user_fn_override=None,
    ) -> None:
        """运行 Agent 主循环，将事件推入 event_queue。"""
        try:
            # 延迟导入避免循环依赖
            from app.terminal_agent import run_agent

            async def _execute_command_callback(session_id, command, cwd=None):
                """Agent 执行命令回调：推送 trace 事件。"""
                # 推送执行前的 trace
                await session.event_queue.put((
                    "trace",
                    {
                        "tool": "execute_command",
                        "input_summary": command[:200],
                        "output_summary": "",
                    },
                ))
                session.last_active_at = datetime.now(timezone.utc)
                session.state = AgentSessionState.EXPLORING

                # 调用实际的 execute_command
                result = await execute_command_fn(session.device_id, command, cwd=cwd)

                # 推送执行后的 trace
                output_preview = result.stdout[:200] if result and result.stdout else ""
                if result and result.stderr:
                    output_preview += f" [stderr: {result.stderr[:100]}]"

                await session.event_queue.put((
                    "trace",
                    {
                        "tool": "execute_command",
                        "input_summary": command[:200],
                        "output_summary": output_preview or "(无输出)",
                    },
                ))

                session.last_active_at = datetime.now(timezone.utc)
                return result

            async def _ask_user_callback(question, options, multi_select):
                """Agent 向用户提问回调。"""
                loop = asyncio.get_running_loop()
                future = loop.create_future()
                session._pending_question_future = future

                session.state = AgentSessionState.ASKING
                session.last_active_at = datetime.now(timezone.utc)

                # 推送 QuestionEvent
                await session.event_queue.put((
                    "question",
                    {
                        "question": question,
                        "options": options or [],
                        "multi_select": multi_select,
                    },
                ))

                # 等待回复（带超时）
                try:
                    answer = await asyncio.wait_for(future, timeout=SESSION_TIMEOUT_SECONDS)
                    session.last_active_at = datetime.now(timezone.utc)
                    session.state = AgentSessionState.EXPLORING
                    return answer
                except asyncio.TimeoutError:
                    raise AgentSessionExpired()
                except AgentSessionCancelled:
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

            # 调用 run_agent
            result = await run_agent(
                intent=session.intent,
                session_id=session.device_id,
                execute_command_fn=_execute_command_callback,
                ask_user_fn=ask_fn,
                project_aliases=known_aliases,
            )

            # 保存 Agent 发现的别名
            if self._alias_store and result.aliases:
                try:
                    await self._alias_store.save_batch(
                        session.user_id, session.device_id, result.aliases,
                    )
                except Exception as e:
                    logger.warning("Failed to save aliases: %s", e)

            # 推送 ResultEvent
            session.state = AgentSessionState.COMPLETED
            session.result = result
            session.last_active_at = datetime.now(timezone.utc)

            await session.event_queue.put((
                "result",
                {
                    "summary": result.summary,
                    "steps": [step.model_dump() for step in result.steps],
                    "provider": result.provider,
                    "source": result.source,
                    "need_confirm": result.need_confirm,
                    "aliases": result.aliases,
                },
            ))

        except AgentSessionExpired:
            session.state = AgentSessionState.EXPIRED
            await session.event_queue.put((
                "error",
                _error_event_dict(ErrorCode.SESSION_EXPIRED, "会话已超时"),
            ))
        except AgentSessionCancelled:
            session.state = AgentSessionState.CANCELLED
            await session.event_queue.put((
                "error",
                _error_event_dict(ErrorCode.SESSION_CANCELLED, "会话已取消"),
            ))
        except asyncio.CancelledError:
            session.state = AgentSessionState.CANCELLED
            await session.event_queue.put((
                "error",
                _error_event_dict(ErrorCode.SESSION_CANCELLED, "会话已取消"),
            ))
        except Exception as e:
            logger.error(
                "Agent loop error: session_id=%s error=%s",
                session.id, e, exc_info=True,
            )
            session.state = AgentSessionState.ERROR
            await session.event_queue.put((
                "error",
                _error_event_dict(ErrorCode.AGENT_ERROR, f"Agent 运行出错: {type(e).__name__}: {e}"),
            ))
        finally:
            # 发送结束信号
            await session.event_queue.put(None)

    async def respond(self, session_id: str, answer: str) -> bool:
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
        if session._pending_question_future is None:
            return False
        if session._pending_question_future.done():
            return False

        session._pending_question_future.set_result(answer)
        session._pending_question_future = None
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
        session.last_active_at = datetime.now(timezone.utc)

        # 取消等待中的 ask_user Future
        if session._pending_question_future and not session._pending_question_future.done():
            session._pending_question_future.set_exception(AgentSessionCancelled())

        # 取消 Agent 运行 task
        if session._agent_task and not session._agent_task.done():
            session._agent_task.cancel()

        # 推送取消事件（如果队列还在消费中）
        await session.event_queue.put((
            "error",
            _error_event_dict(ErrorCode.SESSION_CANCELLED, "会话已被用户取消"),
        ))
        await session.event_queue.put(None)

        logger.info("Session cancelled: session_id=%s", session_id)
        return True

    async def get_session(self, session_id: str) -> Optional[AgentSession]:
        """获取会话。"""
        return self._sessions.get(session_id)

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
          - event: trace / question / result / error
          - : keepalive（注释帧）
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
