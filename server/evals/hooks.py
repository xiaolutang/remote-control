"""
Evals 模块事件钩子注册。

R051: 将 evals 相关逻辑从 app 层移到 evals 模块内部，
通过 event_bus 注册钩子，app 层只触发事件，不直接 import evals。
"""
import asyncio
import logging

logger = logging.getLogger(__name__)


async def _on_result_event(
    session,
    result_event_data: dict,
    result_event_id: str = "",
    result_event_index: int = -1,
) -> None:
    """处理 result 事件 → quality_monitor 指标提取。"""
    from evals.db import get_evals_db
    from evals.quality_monitor import extract_and_store_metrics

    eval_db = get_evals_db()
    await eval_db.init_db()

    terminal_id = session.terminal_id or ""
    events = []

    if terminal_id and session.conversation_id:
        try:
            from app.store.database import list_agent_conversation_events
            after_index = session._run_start_event_index if session._run_start_event_index >= 0 else None
            events = await list_agent_conversation_events(
                session.user_id,
                session.device_id,
                terminal_id,
                after_index=after_index,
            )
            if result_event_index >= 0:
                events = [e for e in events if e.get("event_index", -1) <= result_event_index]
        except Exception as e:
            logger.debug("Quality monitor: DB query failed, using fallback: %s", e)
            events = []

    if not events:
        events = [{"event_type": "result", "payload": result_event_data}]

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


async def _on_feedback_created(
    feedback_id: str,
    category: str,
    description: str,
    **kwargs,
) -> None:
    """处理 feedback 创建 → analyze_feedback。"""
    from evals.db import get_evals_db
    from evals.feedback_loop import analyze_feedback

    eval_db = get_evals_db()
    await eval_db.init_db()

    candidate_id = await analyze_feedback(
        eval_db,
        feedback_id=feedback_id,
        category=category,
        description=description,
    )
    if candidate_id:
        logger.info("Feedback→Candidate: feedback_id=%s candidate_id=%s", feedback_id, candidate_id)


def register_all_hooks() -> None:
    """注册所有 evals 事件钩子。在应用启动时调用。"""
    from app.infra.event_bus import register_evals_hook

    register_evals_hook("on_result_event", _on_result_event)
    register_evals_hook("on_feedback_created", _on_feedback_created)
    logger.info("Evals hooks registered: on_result_event, on_feedback_created")
