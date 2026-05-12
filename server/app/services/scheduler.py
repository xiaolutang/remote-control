"""
B003: 定时任务调度器

后台 asyncio 协程，每 30 秒轮询 scheduled_tasks 表，
找到 status=pending 且 execute_at <= now 的任务，
通过 WS DATA 消息发送到目标 terminal。

一次性任务: 发送成功→status=executed, Agent 离线→status=expired
每日任务: 发送成功→保持 pending + execute_at 推到次日, Agent 离线→跳过本轮 + execute_at 推到次日
"""
import asyncio
import base64
import logging
from datetime import datetime, timezone, timedelta

from app.store.scheduled_task import ScheduledTaskStore
from app.store.session import list_session_terminals
from app.ws.agent_connection import get_agent_connection
from app.infra.message_types import MessageType

logger = logging.getLogger(__name__)

POLL_INTERVAL = 30  # 秒


async def _send_text_to_terminal(session_id: str, terminal_id: str, text: str) -> bool:
    """通过 WS DATA 消息向终端发送文本。返回是否成功。"""
    agent_conn = get_agent_connection(session_id)
    if not agent_conn:
        return False
    try:
        payload = base64.b64encode(text.encode()).decode()
        await agent_conn.send({
            "type": MessageType.DATA,
            "terminal_id": terminal_id,
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return True
    except Exception:
        logger.exception("WS send failed for session=%s terminal=%s", session_id, terminal_id)
        return False


async def _is_terminal_live(session_id: str, terminal_id: str) -> bool:
    """检查 terminal 是否存在且状态为 live。"""
    try:
        terminals = await list_session_terminals(session_id)
        terminal = next(
            (t for t in terminals if t.get("terminal_id") == terminal_id),
            None,
        )
        return terminal is not None and terminal.get("status") == "live"
    except Exception:
        logger.exception("Failed to check terminal liveness for session=%s terminal=%s", session_id, terminal_id)
        return False


def _next_daily_execute_at(execute_at_str: str) -> str:
    """计算每日任务的下次 execute_at（次日同 time-of-day + timezone）。

    使用标准库 datetime.fromisoformat() 解析 ISO 字符串（Python 3.11+ 支持带时区的 ISO 格式）。
    """
    current = datetime.fromisoformat(execute_at_str)
    next_time = current + timedelta(days=1)
    return next_time.isoformat()


async def scheduled_task_poller(db_path: str):
    """后台轮询协程，每 30 秒检查并执行到期的定时任务。"""
    store = ScheduledTaskStore(db_path)
    logger.info("Scheduled task poller started (interval=%ds)", POLL_INTERVAL)

    while True:
        try:
            await asyncio.sleep(POLL_INTERVAL)
            await _poll_once(store)
        except asyncio.CancelledError:
            logger.info("Scheduled task poller cancelled")
            raise
        except Exception:
            logger.exception("Scheduled task poller error")
            await asyncio.sleep(5)  # 异常后短暂等待再重试


async def _poll_once(store: ScheduledTaskStore):
    """执行一次轮询。"""
    now = datetime.now(timezone.utc).isoformat()

    tasks = await store.list_pending_due(now)

    if not tasks:
        return

    logger.info("Found %d due scheduled tasks", len(tasks))

    for task in tasks:
        await _process_task(store, task)


async def _process_task(store: ScheduledTaskStore, task: dict):
    """处理单个到期任务。"""
    task_id = task["id"]
    session_id = task["session_id"]
    terminal_id = task["terminal_id"]
    text_content = task["text_content"]
    repeat_type = task["repeat_type"]

    now_iso = datetime.now(timezone.utc).isoformat()

    # 检查 terminal 是否仍然存在且为 live
    terminal_live = await _is_terminal_live(session_id, terminal_id)

    if not terminal_live:
        # terminal 不存在或已关闭
        if repeat_type == "daily":
            # 每日任务：跳过本轮，推到次日
            next_execute_at = _next_daily_execute_at(task["execute_at"])
            await store.update_execute_at(task_id, next_execute_at)
            logger.warning("Daily task %d skipped (terminal not live), next at %s", task_id, next_execute_at)
        else:
            # 一次性任务：标记为 expired
            await store.update_status(task_id, "expired", executed_at=now_iso)
            logger.warning("One-time task %d expired (terminal not live)", task_id)
        return

    success = await _send_text_to_terminal(session_id, terminal_id, text_content)

    if repeat_type == "daily":
        next_execute_at = _next_daily_execute_at(task["execute_at"])
        if success:
            # 每日任务成功：保持 pending，更新 execute_at 为次日
            await store.update_execute_at(task_id, next_execute_at)
            logger.info("Daily task %d executed, next at %s", task_id, next_execute_at)
        else:
            # 每日任务失败（Agent 离线）：跳过本轮，推到次日
            await store.update_execute_at(task_id, next_execute_at)
            logger.warning("Daily task %d skipped (agent offline), next at %s", task_id, next_execute_at)
    else:
        # 一次性任务
        if success:
            await store.update_status(task_id, "executed", executed_at=now_iso)
            logger.info("One-time task %d executed", task_id)
        else:
            await store.update_status(task_id, "expired", executed_at=now_iso)
            logger.warning("One-time task %d expired (agent offline)", task_id)
