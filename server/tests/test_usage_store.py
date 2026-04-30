"""
B050: usage_store.py 单元测试 — ON CONFLICT 累加逻辑

测试场景：
1. 单次写入后查询验证字段值
2. 同 session_id 两次写入，验证累加
3. model_name 保留最新非空值
4. 多 session 聚合验证
5. 无记录时返回全零
6. 已有记录含 NULL 字段时累加正确
7. 负数输入被当 0 处理
"""
import os

import aiosqlite
import pytest
import pytest_asyncio

from app.store.database import Database

TEST_DB = "/tmp/test_rc_usage_store.db"


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
    """创建并初始化 Database 实例。"""
    database = Database(TEST_DB)
    await database.init_db()
    return database


# ---------------------------------------------------------------------------
# test_save_usage_single_write: 单次写入后查询验证字段值
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_usage_single_write(db):
    """单次写入后查询验证字段值。"""
    ok = await db.save_agent_usage(
        "sess-001",
        "user-1",
        "device-a",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        requests=1,
        model_name="gpt-4",
    )
    assert ok is True

    async with aiosqlite.connect(TEST_DB) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT * FROM agent_usage_records WHERE session_id = ?",
            ("sess-001",),
        )
        row = await cursor.fetchone()

    assert row is not None
    assert row["session_id"] == "sess-001"
    assert row["user_id"] == "user-1"
    assert row["device_id"] == "device-a"
    assert row["input_tokens"] == 100
    assert row["output_tokens"] == 50
    assert row["total_tokens"] == 150
    assert row["requests"] == 1
    assert row["model_name"] == "gpt-4"


# ---------------------------------------------------------------------------
# test_save_usage_accumulate: 同 session_id 两次写入，验证累加
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_usage_accumulate(db):
    """同一 session_id 两次写入，token 和 requests 累加。"""
    # 第一次写入
    await db.save_agent_usage(
        "sess-002",
        "user-1",
        "device-a",
        input_tokens=1000,
        output_tokens=500,
        total_tokens=1500,
        requests=3,
        model_name="gpt-4",
    )
    # 第二次写入
    await db.save_agent_usage(
        "sess-002",
        "user-1",
        "device-a",
        input_tokens=2000,
        output_tokens=1000,
        total_tokens=3000,
        requests=2,
        model_name="gpt-4",
    )

    async with aiosqlite.connect(TEST_DB) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT * FROM agent_usage_records WHERE session_id = ?",
            ("sess-002",),
        )
        row = await cursor.fetchone()

    assert row is not None
    assert row["input_tokens"] == 3000   # 1000 + 2000
    assert row["output_tokens"] == 1500  # 500 + 1000
    assert row["total_tokens"] == 4500   # 1500 + 3000
    assert row["requests"] == 5          # 3 + 2


# ---------------------------------------------------------------------------
# test_save_usage_model_name_latest: 验证 model_name 保留最新非空值
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_usage_model_name_latest(db):
    """model_name 保留最新非空值，空值时保留旧值。"""
    # 第一次写入 model_name
    await db.save_agent_usage(
        "sess-003",
        "user-1",
        "device-a",
        total_tokens=100,
        model_name="gpt-4",
    )

    # 第二次写入不同 model_name（非空，应覆盖）
    await db.save_agent_usage(
        "sess-003",
        "user-1",
        "device-a",
        total_tokens=200,
        model_name="claude-3",
    )

    async with aiosqlite.connect(TEST_DB) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT model_name FROM agent_usage_records WHERE session_id = ?",
            ("sess-003",),
        )
        row = await cursor.fetchone()
    assert row["model_name"] == "claude-3"

    # 第三次写入 model_name 为空（None），应保留旧值 claude-3
    await db.save_agent_usage(
        "sess-003",
        "user-1",
        "device-a",
        total_tokens=50,
        model_name=None,
    )

    async with aiosqlite.connect(TEST_DB) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT model_name FROM agent_usage_records WHERE session_id = ?",
            ("sess-003",),
        )
        row = await cursor.fetchone()
    assert row["model_name"] == "claude-3"


# ---------------------------------------------------------------------------
# test_get_usage_summary_multi_session: 多 session 聚合验证
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_usage_summary_multi_session(db):
    """多个 session 的 usage 被 get_usage_summary 正确聚合。"""
    await db.save_agent_usage(
        "sess-a",
        "user-1",
        "device-a",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        requests=1,
        model_name="gpt-4",
    )
    await db.save_agent_usage(
        "sess-b",
        "user-1",
        "device-b",
        input_tokens=200,
        output_tokens=100,
        total_tokens=300,
        requests=2,
        model_name="claude-3",
    )

    summary = await db.get_usage_summary("user-1")

    assert summary["total_sessions"] == 2
    assert summary["total_input_tokens"] == 300   # 100 + 200
    assert summary["total_output_tokens"] == 150   # 50 + 100
    assert summary["total_tokens"] == 450          # 150 + 300
    assert summary["total_requests"] == 3          # 1 + 2
    # latest_model_name 为最近 created_at 的记录
    assert summary["latest_model_name"] in ("gpt-4", "claude-3")


@pytest.mark.asyncio
async def test_get_usage_summary_with_device_filter(db):
    """get_usage_summary 支持 device_id 过滤。"""
    await db.save_agent_usage(
        "sess-a",
        "user-1",
        "device-a",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        requests=1,
    )
    await db.save_agent_usage(
        "sess-b",
        "user-1",
        "device-b",
        input_tokens=200,
        output_tokens=100,
        total_tokens=300,
        requests=2,
    )

    summary = await db.get_usage_summary("user-1", device_id="device-a")

    assert summary["total_sessions"] == 1
    assert summary["total_input_tokens"] == 100
    assert summary["total_tokens"] == 150


# ---------------------------------------------------------------------------
# test_get_usage_summary_empty: 无记录时返回全零
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_usage_summary_empty(db):
    """无记录时 get_usage_summary 返回全零。"""
    summary = await db.get_usage_summary("nonexistent-user")

    assert summary["total_sessions"] == 0
    assert summary["total_input_tokens"] == 0
    assert summary["total_output_tokens"] == 0
    assert summary["total_tokens"] == 0
    assert summary["total_requests"] == 0
    assert summary["latest_model_name"] == ""


# ---------------------------------------------------------------------------
# test_accumulate_with_null_existing: 已有记录含 NULL 字段时累加正确
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_accumulate_with_null_existing(db):
    """已有记录（字段为 0）时累加正确。

    表 DDL 定义 NOT NULL DEFAULT 0，正常路径不会产生 NULL。
    此测试验证从 0 基线开始累加的正确性，SQL 使用 COALESCE 防御。
    """
    # 第一次不传任何 token 值（使用默认 0）
    await db.save_agent_usage(
        "sess-null",
        "user-1",
        "device-a",
    )

    # 累加操作
    await db.save_agent_usage(
        "sess-null",
        "user-1",
        "device-a",
        input_tokens=500,
        output_tokens=250,
        total_tokens=750,
        requests=1,
    )

    async with aiosqlite.connect(TEST_DB) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT * FROM agent_usage_records WHERE session_id = ?",
            ("sess-null",),
        )
        row = await cursor.fetchone()

    assert row is not None
    assert row["input_tokens"] == 500   # 0 + 500
    assert row["output_tokens"] == 250  # 0 + 250
    assert row["total_tokens"] == 750   # 0 + 750
    assert row["requests"] == 1         # 0 + 1


# ---------------------------------------------------------------------------
# test_negative_input_treated_as_zero: 负数输入被当 0 处理
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_negative_input_treated_as_zero(db):
    """负数输入被当 0 处理，不导致脏数据。"""
    # 先写入正常值
    await db.save_agent_usage(
        "sess-neg",
        "user-1",
        "device-a",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        requests=2,
        model_name="gpt-4",
    )

    # 写入负数值
    await db.save_agent_usage(
        "sess-neg",
        "user-1",
        "device-a",
        input_tokens=-500,
        output_tokens=-200,
        total_tokens=-300,
        requests=-1,
    )

    async with aiosqlite.connect(TEST_DB) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT * FROM agent_usage_records WHERE session_id = ?",
            ("sess-neg",),
        )
        row = await cursor.fetchone()

    assert row is not None
    # 负数被 max(0, ...) 处理为 0，累加后保持原值
    assert row["input_tokens"] == 100   # 100 + 0
    assert row["output_tokens"] == 50   # 50 + 0
    assert row["total_tokens"] == 150   # 150 + 0
    assert row["requests"] == 2         # 2 + 0
    # model_name 未传时保留旧值
    assert row["model_name"] == "gpt-4"


# ---------------------------------------------------------------------------
# test_save_usage_returns_false_on_error: 异常时返回 False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_usage_returns_false_on_error(db):
    """写入异常时返回 False。"""
    # 使用空 session_id 测试（SQLite 对 NOT NULL 约束的行为）
    # 传入 None 作为 session_id 应触发异常
    result = await db.save_agent_usage(
        None,  # type: ignore
        "user-1",
        "device-a",
        total_tokens=100,
    )
    assert result is False


# ---------------------------------------------------------------------------
# test_accumulate_null_handling_safe_path: 正常路径累加无 NULL 问题
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_accumulate_null_handling_safe_path(db):
    """正常路径下累加始终正确（不产生 NULL）。"""
    # 多次累加，全部走 save_agent_usage
    for i in range(5):
        await db.save_agent_usage(
            "sess-acc",
            "user-1",
            "device-a",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            requests=1,
            model_name=f"model-{i}",
        )

    async with aiosqlite.connect(TEST_DB) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT * FROM agent_usage_records WHERE session_id = ?",
            ("sess-acc",),
        )
        row = await cursor.fetchone()

    assert row is not None
    assert row["input_tokens"] == 500   # 100 * 5
    assert row["output_tokens"] == 250  # 50 * 5
    assert row["total_tokens"] == 750   # 150 * 5
    assert row["requests"] == 5         # 1 * 5
    # 最后一次 model_name 为 "model-4"（非空）
    assert row["model_name"] == "model-4"
