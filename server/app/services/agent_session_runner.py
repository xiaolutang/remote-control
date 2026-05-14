"""
B080: Agent 会话运行循环。

从 agent_session_manager.py 拆分出的 _run_agent_loop 函数。
该函数管理 Agent 主循环的核心逻辑，包括工具调用追踪、phase 变更、
SSE 事件推送等。

架构约束：
- 不变量 #43: 产物收口为 CommandSequence（AgentResult）
- 不变量 #50: streaming_text 为逐 token 推送模型文本输出
- 不变量 #60: Agent SSE 采用阶段驱动模型

S514: 将 run_agent_loop 中的 5 个嵌套闭包提取为 AgentLoopRunner 类方法，
run_agent_loop 作为编排器只做调度。
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from app.services.terminal_agent import AgentUserFacingError
from app.services.agent_session_types import (
    PHASE_THINKING, PHASE_EXPLORING, PHASE_ANALYZING, PHASE_CONFIRMING, PHASE_RESPONDING, PHASE_RESULT,
    _PHASE_DESCRIPTIONS, _MAX_TOOL_STEP_PREVIEW, _MAX_TOOL_STEP_ERROR_PREVIEW, SESSION_TIMEOUT_SECONDS,
    ErrorCode, AgentSessionState,
    _phase_change_event, _streaming_text_event, _tool_step_event, _error_event_dict,
    AgentSessionExpired, AgentSessionCancelled,
)
from app.services.agent_session import AgentSession

logger = logging.getLogger(__name__)


def _trigger_quality_monitor(
    manager,
    session: AgentSession,
    *,
    result_event_data: dict,
    result_event_id: str = "",
    result_event_index: int = -1,
) -> None:
    """B052: result 事件后通过事件钩子触发 evals 指标提取（best-effort）。

    不再直接 import evals 模块，通过 event_bus 触发钩子。
    钩子的具体实现在 evals 模块启动时注册。
    """
    try:
        from app.infra.event_bus import emit_evals_event_background

        emit_evals_event_background(
            "on_result_event",
            session=session,
            result_event_data=result_event_data,
            result_event_id=result_event_id,
            result_event_index=result_event_index,
        )
    except Exception as e:
        logger.info("Quality monitor trigger skipped: session_id=%s error=%s", session.id, e)


def _get_save_agent_usage():
    """延迟获取 save_agent_usage，确保测试 patch 目标正确。

    测试通过 patch("app.services.agent_session_manager.save_agent_usage") mock 此函数，
    因此不能直接 from app.store.database import save_agent_usage，
    必须通过 agent_session_manager 模块间接引用。
    """
    import app.services.agent_session_manager as _mgr_mod
    return _mgr_mod.save_agent_usage


def _classify_tool_error(error_msg: str) -> str:
    """工具调用错误分类。"""
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


class AgentLoopRunner:
    """Agent 主循环执行器。

    S514: 将 run_agent_loop 中的闭包提取为类方法。
    manager 和 session 通过构造函数注入，外部回调函数也作为实例属性保存。
    """

    def __init__(
        self,
        manager,
        session: AgentSession,
        execute_command_fn,
        ask_user_fn_override=None,
        lookup_knowledge_fn=None,
        tool_call_fn=None,
        dynamic_tools=None,
        include_lookup_knowledge=True,
        scheduled_task_store=None,
    ):
        self.manager = manager
        self.session = session
        self.execute_command_fn = execute_command_fn
        self.ask_user_fn_override = ask_user_fn_override
        self.lookup_knowledge_fn = lookup_knowledge_fn
        self.tool_call_fn = tool_call_fn
        self.dynamic_tools = dynamic_tools
        self.include_lookup_knowledge = include_lookup_knowledge
        self.scheduled_task_store = scheduled_task_store

        # B104: Phase 推断状态追踪
        self._current_phase: str = ""

    # ------------------------------------------------------------------
    # 闭包提取为实例方法
    # ------------------------------------------------------------------

    async def emit_phase_change(self, phase: str, description: str = "") -> None:
        """B104: 推送 phase_change 事件（去重：相同 phase 不重复 emit）。"""
        if phase == self._current_phase:
            return
        self._current_phase = phase
        desc = description or _PHASE_DESCRIPTIONS.get(phase, "")
        await self.manager._emit_session_event(
            self.session,
            "phase_change",
            _phase_change_event(phase, desc),
        )

    async def execute_command_callback(self, session_id, command, cwd=None):
        """Agent 执行命令回调：推送 tool_step 事件。"""
        session = self.session
        # 默认使用终端 CWD
        effective_cwd = cwd or session.terminal_cwd
        # B104: 工具调用开始 → EXPLORING
        await self.emit_phase_change(PHASE_EXPLORING)
        # 推送执行前的 tool_step（status=running）
        await self.manager._emit_session_event(
            session,
            "tool_step",
            _tool_step_event(
                tool_name="execute_command",
                description=f"执行: {command[:60]}",
                status="running",
                command=command,
            ),
        )
        session.last_active_at = datetime.now(timezone.utc)
        session.state = AgentSessionState.EXPLORING

        # 调用实际的 execute_command
        result = await self.execute_command_fn(session.device_id, command, cwd=effective_cwd)

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

        await self.manager._emit_session_event(
            session,
            "tool_step",
            _tool_step_event(
                tool_name="execute_command",
                description=f"执行: {command[:60]}",
                status=error_status,
                result_summary=output_preview or "(无输出)",
                command=command,
            ),
        )

        session.last_active_at = datetime.now(timezone.utc)
        # B104: 工具调用完成 → ANALYZING
        await self.emit_phase_change(PHASE_ANALYZING)
        return result

    async def ask_user_callback(self, question, options, multi_select):
        """Agent 向用户提问回调。"""
        session = self.session
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        session._pending_question_future = future

        # B104: ask_user → CONFIRMING
        await self.emit_phase_change(PHASE_CONFIRMING)
        session.state = AgentSessionState.ASKING
        session.last_active_at = datetime.now(timezone.utc)
        question_id = f"q_{uuid4().hex}"
        session.pending_question_id = question_id

        # B106: 推送 tool_step(running) — ask_user
        await self.manager._emit_session_event(
            session,
            "tool_step",
            _tool_step_event(
                tool_name="ask_user",
                description="向用户提问",
                status="running",
            ),
        )

        # 推送 QuestionEvent
        await self.manager._emit_session_event(
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
            await self.manager._emit_session_event(
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
            await self.manager._emit_session_event(
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
            await self.manager._emit_session_event(
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

    async def traced_lookup_knowledge(self, query):
        """tool_step 包装：lookup_knowledge（含 duration）。"""
        session = self.session
        t_start = time.monotonic()
        # B104: 工具调用开始 → EXPLORING
        await self.emit_phase_change(PHASE_EXPLORING)
        await self.manager._emit_session_event(
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
            if self.lookup_knowledge_fn:
                result = await self.lookup_knowledge_fn(query)
        except Exception as e:
            error_category = type(e).__name__
            duration_ms = int((time.monotonic() - t_start) * 1000)
            await self.manager._emit_session_event(
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
        await self.manager._emit_session_event(
            session, "tool_step",
            _tool_step_event(
                tool_name="lookup_knowledge",
                description=f"搜索知识库: {query[:60]}",
                status="done",
                result_summary=(result or "(无结果)")[:200],
            ),
        )
        # B104: 工具调用完成 → ANALYZING
        await self.emit_phase_change(PHASE_ANALYZING)
        return result

    async def traced_tool_call(self, tool_name, arguments):
        """tool_step 包装：call_dynamic_tool（含 duration + error category）。"""
        session = self.session
        t_start = time.monotonic()
        # B104: 工具调用开始 → EXPLORING
        await self.emit_phase_change(PHASE_EXPLORING)
        await self.manager._emit_session_event(
            session, "tool_step",
            _tool_step_event(
                tool_name=f"call_dynamic_tool:{tool_name}",
                description=f"调用 {tool_name}",
                status="running",
            ),
        )
        result = {"status": "error", "error": "tool_call_fn not available"}
        error_category = "not_found" if not self.tool_call_fn else None
        if self.tool_call_fn:
            try:
                result = await self.tool_call_fn(tool_name, arguments)
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
        await self.manager._emit_session_event(
            session, "tool_step",
            _tool_step_event(
                tool_name=f"call_dynamic_tool:{tool_name}",
                description=f"调用 {tool_name}",
                status=step_status,
                result_summary=output_preview or "(无输出)",
            ),
        )
        # B104: 工具调用完成 → ANALYZING
        await self.emit_phase_change(PHASE_ANALYZING)
        return result

    async def on_model_text(self, text: str):
        """B105: 模型文本输出回调：逐 token 推送 streaming_text SSE 事件。"""
        if not text:
            return

        # 空白 delta：只有换行/空格时不推送
        stripped = text.strip()
        if not stripped:
            return

        # 文本输出 → RESPONDING
        await self.emit_phase_change(PHASE_RESPONDING)
        await self.manager._emit_session_event(
            self.session,
            "streaming_text",
            _streaming_text_event(stripped),
        )

    # ------------------------------------------------------------------
    # 编排方法
    # ------------------------------------------------------------------

    async def _load_known_aliases(self) -> dict[str, str]:
        """加载已知别名（Agent 启动时注入 ProjectContext）。"""
        known_aliases: dict[str, str] = {}
        if self.manager._db:
            try:
                known_aliases = await self.manager._db.list_project_aliases(
                    self.session.user_id, self.session.device_id,
                )
            except Exception as e:
                logger.warning("Failed to load aliases: %s", e)
        return known_aliases

    async def _invoke_agent(self, known_aliases, ask_fn):
        """调用 run_agent 核心。"""
        from app.services.terminal_agent import run_agent

        # B001: 创建定时任务回调闭包（捕获 user_id / device_id / terminal_id）
        list_fn = None
        cancel_fn = None
        if self.scheduled_task_store is not None and self.session.terminal_id:
            store = self.scheduled_task_store
            user_id = self.session.user_id
            device_id = self.session.device_id
            terminal_id = self.session.terminal_id

            async def _list_scheduled_tasks() -> list[dict]:
                """查询当前终端的定时任务。

                闭包捕获 device_id（映射为 store 的 session_id）和 terminal_id。
                """
                return await store.list_scheduled_tasks_by_session_and_terminal(
                    session_id=device_id,  # 命名映射：store 的 session_id = device_id
                    terminal_id=terminal_id,
                )

            async def _cancel_scheduled_task(task_id: int) -> str:
                """取消定时任务，校验归属（user_id + device_id + terminal_id）。"""
                task = await store.get_scheduled_task_by_id(task_id)
                if task is None:
                    return f"任务 {task_id} 不存在"
                if task.get("user_id") != user_id:
                    return f"任务 {task_id} 不属于当前用户，无权取消"
                if task.get("session_id") != device_id:
                    return f"任务 {task_id} 不属于当前设备，无权取消"
                if task.get("terminal_id") != terminal_id:
                    return f"任务 {task_id} 不属于当前终端，无权取消"
                await store.delete_scheduled_task(task_id)
                return f"任务 {task_id} 已成功取消"

            list_fn = _list_scheduled_tasks
            cancel_fn = _cancel_scheduled_task

        return await run_agent(
            intent=self.session.intent,
            session_id=self.session.device_id,
            execute_command_fn=self.execute_command_callback,
            ask_user_fn=ask_fn,
            project_aliases=known_aliases,
            message_history=self.session.message_history,
            lookup_knowledge_fn=self.traced_lookup_knowledge if self.lookup_knowledge_fn else None,
            tool_call_fn=self.traced_tool_call if self.tool_call_fn else None,
            dynamic_tools=self.dynamic_tools,
            include_lookup_knowledge=self.include_lookup_knowledge,
            on_model_text=self.on_model_text,
            list_scheduled_tasks_fn=list_fn,
            cancel_scheduled_task_fn=cancel_fn,
        )

    async def _persist_aliases(self, outcome):
        """保存 Agent 发现的别名。"""
        if self.manager._db and outcome.result.aliases:
            try:
                await self.manager._db.save_project_aliases_batch(
                    self.session.user_id, self.session.device_id, outcome.result.aliases,
                )
            except Exception as e:
                logger.warning("Failed to save aliases: %s", e)

    async def _persist_usage(self, outcome) -> dict:
        """保存 Agent usage，返回 usage_payload。"""
        session = self.session
        usage_payload = {
            "input_tokens": outcome.input_tokens,
            "output_tokens": outcome.output_tokens,
            "total_tokens": outcome.total_tokens,
            "requests": outcome.requests,
            "model_name": outcome.model_name,
        }
        saved_usage = await _get_save_agent_usage()(
            session.id,
            session.user_id,
            session.device_id,
            input_tokens=usage_payload["input_tokens"],
            output_tokens=usage_payload["output_tokens"],
            total_tokens=usage_payload["total_tokens"],
            requests=usage_payload["requests"],
            model_name=usage_payload["model_name"],
            terminal_id=session.terminal_id,
        )
        if not saved_usage:
            logger.warning(
                "Agent usage persistence skipped: session_id=%s user=%s device=%s",
                session.id,
                session.user_id,
                session.device_id,
            )
        return usage_payload

    async def _emit_result(self, outcome, usage_payload: dict):
        """推送 result/error SSE 事件。"""
        session = self.session

        # B106: response_type="error" 走 error SSE 通道
        if outcome.result.response_type == "error":
            # B104: deliver_result → RESULT
            await self.emit_phase_change(PHASE_RESULT)
            session.state = AgentSessionState.ERROR
            session.pending_question_id = None
            session.last_active_at = datetime.now(timezone.utc)
            await self.manager._emit_session_event(
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
            await self.emit_phase_change(PHASE_RESULT)
            session.state = AgentSessionState.COMPLETED
            session.result = outcome.result
            session.last_active_at = datetime.now(timezone.utc)

            result_event_data = {
                "summary": outcome.result.summary,
                "steps": [step.model_dump() for step in outcome.result.steps],
                "response_type": outcome.result.response_type,
                "ai_prompt": outcome.result.ai_prompt,
                "provider": outcome.result.provider,
                "source": outcome.result.source,
                "need_confirm": outcome.result.need_confirm,
                "aliases": outcome.result.aliases,
                "usage": usage_payload,
            }
            # S001: 透传调度字段（仅 command 类型携带时才有值）
            if outcome.result.schedule_at is not None:
                result_event_data["schedule_at"] = outcome.result.schedule_at
            if outcome.result.repeat_type is not None:
                result_event_data["repeat_type"] = outcome.result.repeat_type
            event_record = await self.manager._emit_session_event(
                session,
                "result",
                result_event_data,
            )

            # B052: result 事件后异步触发 quality_monitor（best-effort）
            result_event_id = ""
            result_event_index = -1
            if event_record and isinstance(event_record, dict):
                result_event_id = event_record.get("event_id", "")
                result_event_index = event_record.get("event_index", -1)
            _trigger_quality_monitor(
                self.manager, session,
                result_event_data=result_event_data,
                result_event_id=result_event_id,
                result_event_index=result_event_index,
            )

    async def run(self) -> None:
        """Agent 主循环编排：调度各阶段。"""
        session = self.session

        # Agent 启动 → THINKING
        await self.emit_phase_change(PHASE_THINKING)

        # 使用覆盖回调或默认回调
        ask_fn = self.ask_user_fn_override or self.ask_user_callback

        # 加载已知别名
        known_aliases = await self._load_known_aliases()

        # 调用 run_agent
        outcome = await self._invoke_agent(known_aliases, ask_fn)

        # 保存别名
        await self._persist_aliases(outcome)

        # usage 落库
        usage_payload = await self._persist_usage(outcome)

        # 推送 result/error 事件
        await self._emit_result(outcome, usage_payload)


async def run_agent_loop(
    manager,
    session: AgentSession,
    execute_command_fn,
    ask_user_fn_override=None,
    lookup_knowledge_fn=None,
    tool_call_fn=None,
    dynamic_tools=None,
    include_lookup_knowledge=True,
    scheduled_task_store=None,
) -> None:
    """运行 Agent 主循环，将事件推入 event_queue。

    保持原有函数签名以确保向后兼容。
    内部委托给 AgentLoopRunner.run() 执行。

    Args:
        manager: AgentSessionManager 实例（用于调用 _emit_session_event 等）
        session: AgentSession 实例
        execute_command_fn: (device_id, command, cwd) -> ExecuteCommandResult
        ask_user_fn_override: 可选覆盖 ask_user 回调
        lookup_knowledge_fn: 可选知识检索回调 (query) -> str
        tool_call_fn: 可选动态工具调用回调 (tool_name, arguments) -> dict
        dynamic_tools: 可用动态工具目录
        include_lookup_knowledge: 是否注册 lookup_knowledge
        scheduled_task_store: 可选 ScheduledTaskStore 实例（B001 定时任务工具回调）
    """
    runner = AgentLoopRunner(
        manager, session,
        execute_command_fn,
        ask_user_fn_override=ask_user_fn_override,
        lookup_knowledge_fn=lookup_knowledge_fn,
        tool_call_fn=tool_call_fn,
        dynamic_tools=dynamic_tools,
        include_lookup_knowledge=include_lookup_knowledge,
        scheduled_task_store=scheduled_task_store,
    )

    try:
        await runner.run()
    except AgentSessionExpired:
        session.state = AgentSessionState.EXPIRED
        session.pending_question_id = None
        await manager._emit_session_event(
            session,
            "error",
            _error_event_dict(ErrorCode.SESSION_EXPIRED, "会话已超时"),
        )
    except AgentSessionCancelled:
        session.state = AgentSessionState.CANCELLED
        session.pending_question_id = None
        await manager._emit_session_event(
            session,
            "error",
            _error_event_dict(ErrorCode.SESSION_CANCELLED, "会话已取消"),
        )
    except asyncio.CancelledError:
        session.state = AgentSessionState.CANCELLED
        session.pending_question_id = None
        await manager._emit_session_event(
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
        await manager._emit_session_event(
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
        await manager._emit_session_event(
            session,
            "error",
            _error_event_dict(ErrorCode.AGENT_ERROR, f"Agent 运行出错: {type(e).__name__}: {e}"),
        )
    finally:
        # 发送结束信号
        await session.event_queue.put(None)
