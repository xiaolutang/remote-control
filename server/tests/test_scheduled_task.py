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
async def db():
    """创建并初始化 Database（含表结构）。"""
    database = Database(TEST_DB)
    await database.init_db()
    return database


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
async def test_create_and_get_by_id(db):
    """创建任务 → 查询验证字段完整。"""
    execute_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    task = await db.create_scheduled_task(
        user_id="user1",
        session_id="session-001",
        terminal_id="terminal-001",
        text_content="ls -la",
        execute_at=execute_at,
        repeat_type="none",
    )
    assert task is not None
    assert isinstance(task["id"], int)

    task_id = task["id"]
    task = await db.get_scheduled_task_by_id(task_id)
    assert task is not None
    assert task["user_id"] == "user1"
    assert task["session_id"] == "session-001"
    assert task["terminal_id"] == "terminal-001"
    assert task["text_content"] == "ls -la"
    assert task["execute_at"] == execute_at
    assert task["repeat_type"] == "none"
    assert task["status"] == "pending"
    assert task["created_at"] is not None
    assert task["executed_at"] is None


@pytest.mark.asyncio
async def test_get_by_id_not_found(db):
    """查询不存在的 ID 返回 None。"""
    result = await db.get_scheduled_task_by_id(99999)
    assert result is None


# ---------------------------------------------------------------------------
# list_by_user
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_by_user(db):
    """按 user_id 查询 → 返回该用户所有任务。"""
    execute_at = datetime.now(timezone.utc).isoformat()
    await db.create_scheduled_task("user1", "session-a", "t1", "cmd1", execute_at, "none")
    await db.create_scheduled_task("user1", "session-b", "t2", "cmd2", execute_at, "daily")
    await db.create_scheduled_task("user2", "session-c", "t3", "cmd3", execute_at, "none")

    tasks = await db.list_scheduled_tasks_by_user("user1")
    assert len(tasks) == 2
    user_ids = {t["user_id"] for t in tasks}
    assert user_ids == {"user1"}


@pytest.mark.asyncio
async def test_list_by_user_empty(db):
    """用户无任务时返回空列表。"""
    tasks = await db.list_scheduled_tasks_by_user("nonexistent_user")
    assert tasks == []


@pytest.mark.asyncio
async def test_list_by_user_with_status_filter(db):
    """按 user_id + status 过滤。"""
    execute_at = datetime.now(timezone.utc).isoformat()
    task1 = await db.create_scheduled_task("user1", "s1", "t1", "cmd1", execute_at, "none")
    await db.create_scheduled_task("user1", "s2", "t2", "cmd2", execute_at, "none")

    # 将第一个任务状态更新为 executed
    await db.update_scheduled_task_status(task1["id"], "executed")

    # 过滤 pending
    pending = await db.list_scheduled_tasks_by_user("user1", status="pending")
    assert len(pending) == 1
    assert pending[0]["status"] == "pending"

    # 过滤 executed
    executed = await db.list_scheduled_tasks_by_user("user1", status="executed")
    assert len(executed) == 1
    assert executed[0]["status"] == "executed"


# ---------------------------------------------------------------------------
# list_by_session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_by_session(db):
    """按 session_id 查询 → 返回该 session 所有任务。"""
    execute_at = datetime.now(timezone.utc).isoformat()
    await db.create_scheduled_task("user1", "session-x", "t1", "cmd1", execute_at, "none")
    await db.create_scheduled_task("user2", "session-x", "t2", "cmd2", execute_at, "hourly")
    await db.create_scheduled_task("user1", "session-y", "t3", "cmd3", execute_at, "none")

    tasks = await db.list_scheduled_tasks_by_session("session-x")
    assert len(tasks) == 2
    session_ids = {t["session_id"] for t in tasks}
    assert session_ids == {"session-x"}


@pytest.mark.asyncio
async def test_list_by_session_empty(db):
    """session 无任务时返回空列表。"""
    tasks = await db.list_scheduled_tasks_by_session("nonexistent_session")
    assert tasks == []


@pytest.mark.asyncio
async def test_list_by_session_with_status_filter(db):
    """按 session_id + status 过滤。"""
    execute_at = datetime.now(timezone.utc).isoformat()
    task1 = await db.create_scheduled_task("user1", "s1", "t1", "cmd1", execute_at, "none")
    await db.create_scheduled_task("user1", "s1", "t2", "cmd2", execute_at, "none")

    await db.update_scheduled_task_status(task1["id"], "executed")

    pending = await db.list_scheduled_tasks_by_session("s1", status="pending")
    assert len(pending) == 1

    executed = await db.list_scheduled_tasks_by_session("s1", status="executed")
    assert len(executed) == 1


# ---------------------------------------------------------------------------
# update_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_status_pending_to_executed(db):
    """更新状态 pending→executed → 验证状态和时间戳。"""
    execute_at = datetime.now(timezone.utc).isoformat()
    task = await db.create_scheduled_task("user1", "s1", "t1", "echo hello", execute_at, "none")
    task_id = task["id"]

    # 初始状态
    task = await db.get_scheduled_task_by_id(task_id)
    assert task["status"] == "pending"
    assert task["executed_at"] is None

    # 更新为 executed
    executed_at = datetime.now(timezone.utc).isoformat()
    await db.update_scheduled_task_status(task_id, "executed", executed_at=executed_at)

    task = await db.get_scheduled_task_by_id(task_id)
    assert task["status"] == "executed"
    assert task["executed_at"] == executed_at


@pytest.mark.asyncio
async def test_update_status_without_executed_at(db):
    """更新状态不传 executed_at 时，executed_at 为 None。"""
    execute_at = datetime.now(timezone.utc).isoformat()
    task = await db.create_scheduled_task("user1", "s1", "t1", "cmd", execute_at, "none")
    task_id = task["id"]

    await db.update_scheduled_task_status(task_id, "failed")

    task = await db.get_scheduled_task_by_id(task_id)
    assert task["status"] == "failed"
    assert task["executed_at"] is None


@pytest.mark.asyncio
async def test_update_status_nonexistent_task(db):
    """更新不存在的任务不报错。"""
    # 应该不抛异常，只是影响 0 行
    await db.update_scheduled_task_status(99999, "executed")


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete(db):
    """删除任务 → 再查询返回 None。"""
    execute_at = datetime.now(timezone.utc).isoformat()
    task = await db.create_scheduled_task("user1", "s1", "t1", "rm -rf /", execute_at, "none")
    task_id = task["id"]

    task = await db.get_scheduled_task_by_id(task_id)
    assert task is not None

    await db.delete_scheduled_task(task_id)

    task = await db.get_scheduled_task_by_id(task_id)
    assert task is None


@pytest.mark.asyncio
async def test_delete_nonexistent_task(db):
    """删除不存在的任务不报错。"""
    await db.delete_scheduled_task(99999)


# ---------------------------------------------------------------------------
# 综合场景
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_lifecycle(db):
    """完整生命周期：创建 → 查询 → 更新 → 删除。"""
    execute_at = datetime.now(timezone.utc).isoformat()

    # 创建
    task = await db.create_scheduled_task("alice", "sess-1", "term-1", "git pull", execute_at, "daily")
    task_id = task["id"]

    # 查询 by user
    tasks = await db.list_scheduled_tasks_by_user("alice")
    assert len(tasks) == 1
    assert tasks[0]["text_content"] == "git pull"

    # 查询 by session
    tasks = await db.list_scheduled_tasks_by_session("sess-1")
    assert len(tasks) == 1

    # 更新状态
    executed_at = datetime.now(timezone.utc).isoformat()
    await db.update_scheduled_task_status(task_id, "executed", executed_at=executed_at)

    # 确认更新
    task = await db.get_scheduled_task_by_id(task_id)
    assert task["status"] == "executed"
    assert task["executed_at"] == executed_at

    # 删除
    await db.delete_scheduled_task(task_id)
    assert await db.get_scheduled_task_by_id(task_id) is None

    # 删除后查询为空
    tasks = await db.list_scheduled_tasks_by_user("alice")
    assert tasks == []
