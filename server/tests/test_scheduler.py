"""
B003: 定时任务调度器测试

测试场景：
1. 到点 + Agent 在线 + 一次性 → 发送 DATA 消息 + 状态变 executed
2. 到点 + Agent 在线 + 每日 → 发送 DATA 消息 + 保持 pending + execute_at 更新为次日
3. 到点 + Agent 离线 + 一次性 → 状态变 expired
4. 到点 + Agent 离线 + 每日 → 保持 pending + execute_at 推到次日
5. 多任务同时到点 → 全部执行
6. 无 pending 任务 → 无操作
7. WS 发送异常 → 一次性标记 expired，每日跳过本轮
"""
import base64
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.store.database import Database
from app.store.scheduled_task import ScheduledTaskStore
from app.services.scheduler import (
    _poll_once,
    _process_task,
    _send_text_to_terminal,
    _next_daily_execute_at,
    _is_terminal_live,
)

TEST_DB = "/tmp/test_rc_scheduler.db"


@pytest.fixture(autouse=True)
def _clean_db():
    """每个测试配置独立数据库并清理。"""
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    yield
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)


@pytest_asyncio.fixture
async def store():
    """创建并初始化 ScheduledTaskStore（含表结构）。"""
    db = Database(TEST_DB)
    await db.init_db()
    return ScheduledTaskStore(TEST_DB)


# ---------------------------------------------------------------------------
# _next_daily_execute_at
# ---------------------------------------------------------------------------

def test_next_daily_execute_at_with_timezone():
    """每日任务的下次执行时间应为次日同一时间。"""
    execute_at = "2026-05-12T08:00:00+08:00"
    result = _next_daily_execute_at(execute_at)
    expected = "2026-05-13T08:00:00+08:00"
    assert result == expected


def test_next_daily_execute_at_utc():
    """UTC 时区的每日任务推到次日。"""
    execute_at = "2026-05-12T00:00:00+00:00"
    result = _next_daily_execute_at(execute_at)
    expected = "2026-05-13T00:00:00+00:00"
    assert result == expected


# ---------------------------------------------------------------------------
# _send_text_to_terminal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_text_to_terminal_agent_offline():
    """Agent 离线时返回 False。"""
    with patch("app.services.scheduler.get_agent_connection", return_value=None):
        result = await _send_text_to_terminal("session-1", "terminal-1", "ls")
        assert result is False


@pytest.mark.asyncio
async def test_send_text_to_terminal_agent_online():
    """Agent 在线时发送 DATA 消息并返回 True。"""
    mock_conn = AsyncMock()
    with patch("app.services.scheduler.get_agent_connection", return_value=mock_conn):
        result = await _send_text_to_terminal("session-1", "terminal-1", "ls -la")
        assert result is True
        # 验证发送的消息
        call_args = mock_conn.send.call_args[0][0]
        assert call_args["type"] == "data"
        assert call_args["terminal_id"] == "terminal-1"
        assert base64.b64decode(call_args["payload"]).decode() == "ls -la"


@pytest.mark.asyncio
async def test_send_text_to_terminal_ws_error():
    """WS 发送异常时返回 False。"""
    mock_conn = AsyncMock()
    mock_conn.send.side_effect = Exception("WS error")
    with patch("app.services.scheduler.get_agent_connection", return_value=mock_conn):
        result = await _send_text_to_terminal("session-1", "terminal-1", "ls")
        assert result is False


# ---------------------------------------------------------------------------
# _process_task
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_task_one_time_online(store):
    """到点 + Agent 在线 + 一次性 → 状态变 executed。"""
    execute_at = datetime.now(timezone.utc).isoformat()
    task_id = await store.create("user1", "session-1", "t1", "echo hello", execute_at, "once")

    task = await store.get_by_id(task_id)

    with patch("app.services.scheduler._is_terminal_live", return_value=True), \
         patch("app.services.scheduler._send_text_to_terminal", return_value=True):
        await _process_task(store, task)

    updated = await store.get_by_id(task_id)
    assert updated["status"] == "executed"
    assert updated["executed_at"] is not None


@pytest.mark.asyncio
async def test_process_task_one_time_offline(store):
    """到点 + Agent 离线 + 一次性 → 状态变 expired。"""
    execute_at = datetime.now(timezone.utc).isoformat()
    task_id = await store.create("user1", "session-1", "t1", "echo hello", execute_at, "once")

    task = await store.get_by_id(task_id)

    with patch("app.services.scheduler._is_terminal_live", return_value=True), \
         patch("app.services.scheduler._send_text_to_terminal", return_value=False):
        await _process_task(store, task)

    updated = await store.get_by_id(task_id)
    assert updated["status"] == "expired"
    assert updated["executed_at"] is not None


@pytest.mark.asyncio
async def test_process_task_daily_online(store):
    """到点 + Agent 在线 + 每日 → 保持 pending + execute_at 更新为次日。"""
    execute_at = "2026-05-12T08:00:00+00:00"
    task_id = await store.create("user1", "session-1", "t1", "git pull", execute_at, "daily")

    task = await store.get_by_id(task_id)

    with patch("app.services.scheduler._is_terminal_live", return_value=True), \
         patch("app.services.scheduler._send_text_to_terminal", return_value=True):
        await _process_task(store, task)

    updated = await store.get_by_id(task_id)
    assert updated["status"] == "pending"
    assert updated["execute_at"] == "2026-05-13T08:00:00+00:00"


@pytest.mark.asyncio
async def test_process_task_daily_offline(store):
    """到点 + Agent 离线 + 每日 → 保持 pending + execute_at 推到次日。"""
    execute_at = "2026-05-12T08:00:00+00:00"
    task_id = await store.create("user1", "session-1", "t1", "git pull", execute_at, "daily")

    task = await store.get_by_id(task_id)

    with patch("app.services.scheduler._is_terminal_live", return_value=True), \
         patch("app.services.scheduler._send_text_to_terminal", return_value=False):
        await _process_task(store, task)

    updated = await store.get_by_id(task_id)
    assert updated["status"] == "pending"
    assert updated["execute_at"] == "2026-05-13T08:00:00+00:00"


# ---------------------------------------------------------------------------
# _process_task — terminal not live
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_task_one_time_terminal_not_live(store):
    """到点 + terminal 不存在/已关闭 + 一次性 → 状态变 expired。"""
    execute_at = datetime.now(timezone.utc).isoformat()
    task_id = await store.create("user1", "session-1", "t1", "echo hello", execute_at, "once")

    task = await store.get_by_id(task_id)

    with patch("app.services.scheduler._is_terminal_live", return_value=False):
        await _process_task(store, task)

    updated = await store.get_by_id(task_id)
    assert updated["status"] == "expired"
    assert updated["executed_at"] is not None


@pytest.mark.asyncio
async def test_process_task_daily_terminal_not_live(store):
    """到点 + terminal 不存在/已关闭 + 每日 → 跳过本轮，execute_at 推到次日。"""
    execute_at = "2026-05-12T08:00:00+00:00"
    task_id = await store.create("user1", "session-1", "t1", "git pull", execute_at, "daily")

    task = await store.get_by_id(task_id)

    with patch("app.services.scheduler._is_terminal_live", return_value=False):
        await _process_task(store, task)

    updated = await store.get_by_id(task_id)
    assert updated["status"] == "pending"
    assert updated["execute_at"] == "2026-05-13T08:00:00+00:00"


# ---------------------------------------------------------------------------
# _poll_once
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_poll_once_no_pending_tasks(store):
    """无 pending 任务 → 无操作。"""
    # 创建一个 executed 状态的任务（不是 pending）
    execute_at = datetime.now(timezone.utc).isoformat()
    task_id = await store.create("user1", "session-1", "t1", "echo hello", execute_at, "once")
    await store.update_status(task_id, "executed", executed_at=execute_at)

    with patch("app.services.scheduler._process_task") as mock_process:
        await _poll_once(store)
        mock_process.assert_not_called()


@pytest.mark.asyncio
async def test_poll_once_multiple_due_tasks(store):
    """多任务同时到点 → 全部执行。"""
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    await store.create("user1", "session-1", "t1", "cmd1", past, "once")
    await store.create("user1", "session-1", "t2", "cmd2", past, "daily")
    await store.create("user1", "session-2", "t3", "cmd3", past, "once")

    with patch("app.services.scheduler._is_terminal_live", return_value=True), \
         patch("app.services.scheduler._send_text_to_terminal", return_value=True):
        await _poll_once(store)

    # 验证所有任务都被处理了
    # 一次性任务变为 executed
    tasks = await store.list_pending_due(datetime.now(timezone.utc).isoformat())
    # 应该只剩 daily 任务（已更新 execute_at 到次日）
    # 查所有任务验证状态
    all_tasks_user1 = await store.list_by_user("user1")
    executed_count = sum(1 for t in all_tasks_user1 if t["status"] == "executed")
    pending_count = sum(1 for t in all_tasks_user1 if t["status"] == "pending")
    assert executed_count == 2  # 两个一次性任务
    assert pending_count == 1  # 一个每日任务


@pytest.mark.asyncio
async def test_poll_once_future_task_not_picked(store):
    """未到点的任务不会被拾取。"""
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    await store.create("user1", "session-1", "t1", "cmd1", future, "once")

    with patch("app.services.scheduler._process_task") as mock_process:
        await _poll_once(store)
        mock_process.assert_not_called()


@pytest.mark.asyncio
async def test_poll_once_ws_exception_one_time_expired(store):
    """WS 发送异常 → 一次性标记 expired。"""
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    task_id = await store.create("user1", "session-1", "t1", "cmd1", past, "once")

    with patch("app.services.scheduler._is_terminal_live", return_value=True), \
         patch("app.services.scheduler._send_text_to_terminal", return_value=False):
        await _poll_once(store)

    task = await store.get_by_id(task_id)
    assert task["status"] == "expired"


@pytest.mark.asyncio
async def test_poll_once_ws_exception_daily_skip(store):
    """WS 发送异常 → 每日跳过本轮，execute_at 推到次日。"""
    execute_at = "2026-05-12T08:00:00+00:00"
    task_id = await store.create("user1", "session-1", "t1", "cmd1", execute_at, "daily")

    with patch("app.services.scheduler._is_terminal_live", return_value=True), \
         patch("app.services.scheduler._send_text_to_terminal", return_value=False):
        await _poll_once(store)

    task = await store.get_by_id(task_id)
    assert task["status"] == "pending"
    assert task["execute_at"] == "2026-05-13T08:00:00+00:00"
