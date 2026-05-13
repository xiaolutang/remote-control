"""
B001: scheduled_task store 单元测试

测试场景：
1. 表结构自动创建
2. create → 查询验证字段完整
3. 按 user_id 查询 → 返回该用户所有任务
4. 按 session_id 查询 → 返回该 session 所有任务
5. 更新状态 pending→executed → 验证状态和时间戳
6. 删除任务 → 再查询返回 None
7. 边界：空列表、不存在的 ID
8. 按 status 过滤查询
"""
import os
from datetime import datetime, timezone, timedelta

import aiosqlite
import pytest
import pytest_asyncio

from app.store.database import Database
from app.store.scheduled_task import ScheduledTaskStore

TEST_DB = "/tmp/test_rc_scheduled_task.db"


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
# 表结构验证
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_scheduled_tasks_table_created():
    """init_db 创建 scheduled_tasks 表。"""
    db = Database(TEST_DB)
    await db.init_db()

    async with aiosqlite.connect(TEST_DB) as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            ("scheduled_tasks",),
        )
        assert await cursor.fetchone() is not None


@pytest.mark.asyncio
async def test_scheduled_tasks_indexes_created():
    """init_db 创建相关索引。"""
    db = Database(TEST_DB)
    await db.init_db()

    async with aiosqlite.connect(TEST_DB) as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name IN (?, ?)",
            ("idx_scheduled_tasks_user_id", "idx_scheduled_tasks_session_id"),
        )
        rows = await cursor.fetchall()
        assert len(rows) == 2


# ---------------------------------------------------------------------------
# create + get_by_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_and_get_by_id(store):
    """创建任务 → 查询验证字段完整。"""
    execute_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    task_id = await store.create(
        user_id="user1",
        session_id="session-001",
        terminal_id="terminal-001",
        text_content="ls -la",
        execute_at=execute_at,
        repeat_type="once",
    )
    assert task_id is not None
    assert isinstance(task_id, int)

    task = await store.get_by_id(task_id)
    assert task is not None
    assert task["user_id"] == "user1"
    assert task["session_id"] == "session-001"
    assert task["terminal_id"] == "terminal-001"
    assert task["text_content"] == "ls -la"
    assert task["execute_at"] == execute_at
    assert task["repeat_type"] == "once"
    assert task["status"] == "pending"
    assert task["created_at"] is not None
    assert task["executed_at"] is None


@pytest.mark.asyncio
async def test_get_by_id_not_found(store):
    """查询不存在的 ID 返回 None。"""
    result = await store.get_by_id(99999)
    assert result is None


# ---------------------------------------------------------------------------
# list_by_user
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_by_user(store):
    """按 user_id 查询 → 返回该用户所有任务。"""
    execute_at = datetime.now(timezone.utc).isoformat()
    await store.create("user1", "session-a", "t1", "cmd1", execute_at, "once")
    await store.create("user1", "session-b", "t2", "cmd2", execute_at, "daily")
    await store.create("user2", "session-c", "t3", "cmd3", execute_at, "once")

    tasks = await store.list_by_user("user1")
    assert len(tasks) == 2
    user_ids = {t["user_id"] for t in tasks}
    assert user_ids == {"user1"}


@pytest.mark.asyncio
async def test_list_by_user_empty(store):
    """用户无任务时返回空列表。"""
    tasks = await store.list_by_user("nonexistent_user")
    assert tasks == []


@pytest.mark.asyncio
async def test_list_by_user_with_status_filter(store):
    """按 user_id + status 过滤。"""
    execute_at = datetime.now(timezone.utc).isoformat()
    id1 = await store.create("user1", "s1", "t1", "cmd1", execute_at, "once")
    await store.create("user1", "s2", "t2", "cmd2", execute_at, "once")

    # 将第一个任务状态更新为 executed
    await store.update_status(id1, "executed")

    # 过滤 pending
    pending = await store.list_by_user("user1", status="pending")
    assert len(pending) == 1
    assert pending[0]["status"] == "pending"

    # 过滤 executed
    executed = await store.list_by_user("user1", status="executed")
    assert len(executed) == 1
    assert executed[0]["status"] == "executed"


# ---------------------------------------------------------------------------
# list_by_session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_by_session(store):
    """按 session_id 查询 → 返回该 session 所有任务。"""
    execute_at = datetime.now(timezone.utc).isoformat()
    await store.create("user1", "session-x", "t1", "cmd1", execute_at, "once")
    await store.create("user2", "session-x", "t2", "cmd2", execute_at, "daily")
    await store.create("user1", "session-y", "t3", "cmd3", execute_at, "once")

    tasks = await store.list_by_session("session-x")
    assert len(tasks) == 2
    session_ids = {t["session_id"] for t in tasks}
    assert session_ids == {"session-x"}


@pytest.mark.asyncio
async def test_list_by_session_empty(store):
    """session 无任务时返回空列表。"""
    tasks = await store.list_by_session("nonexistent_session")
    assert tasks == []


@pytest.mark.asyncio
async def test_list_by_session_with_status_filter(store):
    """按 session_id + status 过滤。"""
    execute_at = datetime.now(timezone.utc).isoformat()
    id1 = await store.create("user1", "s1", "t1", "cmd1", execute_at, "once")
    await store.create("user1", "s1", "t2", "cmd2", execute_at, "once")

    await store.update_status(id1, "executed")

    pending = await store.list_by_session("s1", status="pending")
    assert len(pending) == 1

    executed = await store.list_by_session("s1", status="executed")
    assert len(executed) == 1


# ---------------------------------------------------------------------------
# update_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_status_pending_to_executed(store):
    """更新状态 pending→executed → 验证状态和时间戳。"""
    execute_at = datetime.now(timezone.utc).isoformat()
    task_id = await store.create("user1", "s1", "t1", "echo hello", execute_at, "once")

    # 初始状态
    task = await store.get_by_id(task_id)
    assert task["status"] == "pending"
    assert task["executed_at"] is None

    # 更新为 executed
    executed_at = datetime.now(timezone.utc).isoformat()
    await store.update_status(task_id, "executed", executed_at=executed_at)

    task = await store.get_by_id(task_id)
    assert task["status"] == "executed"
    assert task["executed_at"] == executed_at


@pytest.mark.asyncio
async def test_update_status_without_executed_at(store):
    """更新状态不传 executed_at 时，executed_at 为 None。"""
    execute_at = datetime.now(timezone.utc).isoformat()
    task_id = await store.create("user1", "s1", "t1", "cmd", execute_at, "once")

    await store.update_status(task_id, "expired")

    task = await store.get_by_id(task_id)
    assert task["status"] == "expired"
    assert task["executed_at"] is None


@pytest.mark.asyncio
async def test_update_status_nonexistent_task(store):
    """更新不存在的任务不报错。"""
    # 应该不抛异常，只是影响 0 行
    await store.update_status(99999, "executed")


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete(store):
    """删除任务 → 再查询返回 None。"""
    execute_at = datetime.now(timezone.utc).isoformat()
    task_id = await store.create("user1", "s1", "t1", "rm -rf /", execute_at, "once")

    task = await store.get_by_id(task_id)
    assert task is not None

    await store.delete(task_id)

    task = await store.get_by_id(task_id)
    assert task is None


@pytest.mark.asyncio
async def test_delete_nonexistent_task(store):
    """删除不存在的任务不报错。"""
    await store.delete(99999)


# ---------------------------------------------------------------------------
# 综合场景
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_lifecycle(store):
    """完整生命周期：创建 → 查询 → 更新 → 删除。"""
    execute_at = datetime.now(timezone.utc).isoformat()

    # 创建
    task_id = await store.create("alice", "sess-1", "term-1", "git pull", execute_at, "daily")

    # 查询 by user
    tasks = await store.list_by_user("alice")
    assert len(tasks) == 1
    assert tasks[0]["text_content"] == "git pull"

    # 查询 by session
    tasks = await store.list_by_session("sess-1")
    assert len(tasks) == 1

    # 更新状态
    executed_at = datetime.now(timezone.utc).isoformat()
    await store.update_status(task_id, "executed", executed_at=executed_at)

    # 确认更新
    task = await store.get_by_id(task_id)
    assert task["status"] == "executed"
    assert task["executed_at"] == executed_at

    # 删除
    await store.delete(task_id)
    assert await store.get_by_id(task_id) is None

    # 删除后查询为空
    tasks = await store.list_by_user("alice")
    assert tasks == []


# ---------------------------------------------------------------------------
# cancel_by_terminal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_by_terminal_cancels_pending(store):
    """关闭终端时，该终端的 pending 任务变为 cancelled。"""
    execute_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    await store.create("user1", "s1", "t1", "cmd1", execute_at, "once")
    await store.create("user1", "s1", "t1", "cmd2", execute_at, "once")
    await store.create("user1", "s1", "t2", "cmd3", execute_at, "once")

    count = await store.cancel_by_terminal("s1", "t1")
    assert count == 2

    # t1 的两个任务都是 cancelled
    t1_tasks = await store.list_by_session("s1", status="cancelled")
    assert len(t1_tasks) == 2
    assert all(t["terminal_id"] == "t1" for t in t1_tasks)

    # t2 的任务仍然是 pending
    t2_tasks = await store.list_by_session("s1", status="pending")
    assert len(t2_tasks) == 1
    assert t2_tasks[0]["terminal_id"] == "t2"


@pytest.mark.asyncio
async def test_cancel_by_terminal_skips_non_pending(store):
    """只有 pending 任务被取消，其他状态不受影响。"""
    execute_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    id1 = await store.create("user1", "s1", "t1", "cmd1", execute_at, "once")
    await store.create("user1", "s1", "t1", "cmd2", execute_at, "once")
    id3 = await store.create("user1", "s1", "t1", "cmd3", execute_at, "once")

    # 先执行一个，过期一个
    await store.update_status(id1, "executed")
    await store.update_status(id3, "expired")

    count = await store.cancel_by_terminal("s1", "t1")
    assert count == 1  # 只有 cmd2 是 pending

    task1 = await store.get_by_id(id1)
    assert task1["status"] == "executed"

    task3 = await store.get_by_id(id3)
    assert task3["status"] == "expired"

    # cmd2 被取消
    cancelled = await store.list_by_session("s1", status="cancelled")
    assert len(cancelled) == 1


@pytest.mark.asyncio
async def test_cancel_by_terminal_no_pending(store):
    """没有 pending 任务时返回 0。"""
    execute_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    id1 = await store.create("user1", "s1", "t1", "cmd", execute_at, "once")
    await store.update_status(id1, "executed")

    count = await store.cancel_by_terminal("s1", "t1")
    assert count == 0


@pytest.mark.asyncio
async def test_cancel_by_terminal_wrong_session(store):
    """不同 session 的任务不受影响。"""
    execute_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    await store.create("user1", "s1", "t1", "cmd1", execute_at, "once")
    await store.create("user1", "s2", "t1", "cmd2", execute_at, "once")

    count = await store.cancel_by_terminal("s1", "t1")
    assert count == 1

    # s2 的任务仍 pending
    s2_tasks = await store.list_by_session("s2", status="pending")
    assert len(s2_tasks) == 1
