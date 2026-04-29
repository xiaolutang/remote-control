"""
B080: Agent 会话运行循环。

从 agent_session_manager.py 拆分出的 _run_agent_loop 函数。
该函数管理 Agent 主循环的核心逻辑，包括工具调用追踪、phase 变更、
SSE 事件推送等。

架构约束：
- 不变量 #43: 产物收口为 CommandSequence（AgentResult）
- 不变量 #50: streaming_text 为逐 token 推送模型文本输出
- 不变量 #60: Agent SSE 采用阶段驱动模型
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
) -> None:
    """B052: result 事件后异步触发 quality_monitor 指标提取（best-effort）。

    优先使用 session 内存缓存（_last_events），它只包含当前 run 的事件
    （reuse 路径中已被清空）。这避免了从 DB 查询完整 terminal conversation
    时混入前次 run 的事件（B051 per-terminal session 后同一 terminal 多次
    run 共享 conversation）。

    _last_events 为空时 fallback 到 DB 查询（首次 run 或缓存被截断）。
    无 terminal_id / conversation_id 时 fallback 为合成 result 事件。

    不阻塞主流程，异常仅记录日志。
    """
    try:
        import asyncio
        import os
        from evals.db import EvalDatabase
        from evals.quality_monitor import extract_and_store_metrics

        eval_db_path = os.environ.get("EVAL_DB_PATH", "/data/evals.db")
        eval_db = EvalDatabase(eval_db_path)

        terminal_id = session.terminal_id or ""

        # 快照当前 run 的内存缓存（_last_events 在 reuse 时被清空）
        cached_events = list(session._last_events)

        async def _do_extract():
            try:
                await eval_db.init_db()

                events = []

                # 优先使用内存缓存（仅当前 run 的事件）
                if cached_events:
                    events = [
                        {"event_type": et, "payload": ed}
                        for et, ed in cached_events
                        if ed is not None
                    ]

                # Fallback: 从 DB 查询完整 conversation 事件
                if not events and terminal_id and session.conversation_id:
                    try:
                        from app.store.database import list_agent_conversation_events
                        events = await list_agent_conversation_events(
                            session.user_id,
                            session.device_id,
                            terminal_id,
                        )
                    except Exception as e:
                        logger.debug(
                            "Quality monitor: DB query failed, using fallback: %s", e,
                        )
                        events = []

                # Final fallback: 合成 result 事件
                if not events:
                    events = [{
                        "event_type": "result",
                        "payload": result_event_data,
                    }]

                await extract_and_store_metrics(
                    eval_db,
                    events,
                    session_id=session.id,
                    user_id=session.user_id,
                    device_id=session.device_id,
                    intent=session.intent,
                    source="production",
                    terminal_id=terminal_id,
                    result_event_id=result_event_id,
                )
            except Exception as e:
                logger.warning(
                    "Quality monitor extraction failed (best-effort): session_id=%s error=%s",
                    session.id, e,
                )

        asyncio.ensure_future(_do_extract())
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

async def run_agent_loop(
    manager,
    session: AgentSession,
    execute_command_fn,
    ask_user_fn_override=None,
    lookup_knowledge_fn=None,
    tool_call_fn=None,
    dynamic_tools=None,
    include_lookup_knowledge=True,
) -> None:
    """运行 Agent 主循环，将事件推入 event_queue。

    Args:
        manager: AgentSessionManager 实例（用于调用 _emit_session_event 等）
        session: AgentSession 实例
        execute_command_fn: (device_id, command, cwd) -> ExecuteCommandResult
        ask_user_fn_override: 可选覆盖 ask_user 回调
        lookup_knowledge_fn: 可选知识检索回调 (query) -> str
        tool_call_fn: 可选动态工具调用回调 (tool_name, arguments) -> dict
        dynamic_tools: 可用动态工具目录
        include_lookup_knowledge: 是否注册 lookup_knowledge
    """
    try:
        # 延迟导入避免循环依赖
        from app.services.terminal_agent import run_agent

        async def _execute_command_callback(session_id, command, cwd=None):
            """Agent 执行命令回调：推送 tool_step 事件。"""
            # 默认使用终端 CWD
            effective_cwd = cwd or session.terminal_cwd
            # B104: 工具调用开始 → EXPLORING
            await _emit_phase_change(PHASE_EXPLORING)
            # 推送执行前的 tool_step（status=running）
            await manager._emit_session_event(
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

            await manager._emit_session_event(
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
            await manager._emit_session_event(
                session,
                "tool_step",
                _tool_step_event(
                    tool_name="ask_user",
                    description="向用户提问",
                    status="running",
                ),
            )

            # 推送 QuestionEvent
            await manager._emit_session_event(
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
                await manager._emit_session_event(
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
                await manager._emit_session_event(
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
                await manager._emit_session_event(
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
        if manager._alias_store:
            try:
                known_aliases = await manager._alias_store.list_all(
                    session.user_id, session.device_id,
                )
            except Exception as e:
                logger.warning("Failed to load aliases: %s", e)

        # tool_step 包装：lookup_knowledge（含 duration）
        async def _traced_lookup_knowledge(query):
            t_start = time.monotonic()
            # B104: 工具调用开始 → EXPLORING
            await _emit_phase_change(PHASE_EXPLORING)
            await manager._emit_session_event(
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
                await manager._emit_session_event(
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
            await manager._emit_session_event(
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
            await manager._emit_session_event(
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
            await manager._emit_session_event(
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
            await manager._emit_session_event(
                session,
                "phase_change",
                _phase_change_event(phase, desc),
            )

        # Agent 启动 → THINKING
        await _emit_phase_change(PHASE_THINKING)

        # B105: on_model_text 回调——逐 token 推送 streaming_text SSE
        async def _on_model_text(text: str):
            """模型文本输出回调：逐 token 推送 streaming_text SSE 事件。"""
            if not text:
                return

            # 空白 delta：只有换行/空格时不推送
            stripped = text.strip()
            if not stripped:
                return

            # 文本输出 → RESPONDING
            await _emit_phase_change(PHASE_RESPONDING)
            await manager._emit_session_event(
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
        if manager._alias_store and outcome.result.aliases:
            try:
                await manager._alias_store.save_batch(
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
        saved_usage = await _get_save_agent_usage()(
            session.id,
            session.user_id,
            session.device_id,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            total_tokens=outcome.total_tokens,
            requests=outcome.requests,
            model_name=outcome.model_name,
            terminal_id=session.terminal_id,
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
            await manager._emit_session_event(
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
            event_record = await manager._emit_session_event(
                session,
                "result",
                result_event_data,
            )

            # B052: result 事件后异步触发 quality_monitor（best-effort）
            result_event_id = ""
            if event_record and isinstance(event_record, dict):
                result_event_id = event_record.get("event_id", "")
            _trigger_quality_monitor(
                manager, session,
                result_event_data=result_event_data,
                result_event_id=result_event_id,
            )

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
