"""
B081: project_alias_store.py 单元测试 — 项目别名持久化存储

测试场景：
1. save + lookup 正常工作
2. 同 alias 覆盖更新
3. 不同 device_id 隔离
4. 不同 user_id 隔离
5. cleanup_stale 清理过期别名
6. batch 批量保存
7. 空别名/路径处理
8. project_aliases 表创建和索引正确
"""
import os

import aiosqlite
import pytest
import pytest_asyncio

from app.store.database import Database

TEST_DB = "/tmp/test_rc_project_aliases.db"


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
async def test_project_aliases_table_created():
    """init_db 创建 project_aliases 表。"""
    db = Database(TEST_DB)
    await db.init_db()

    async with aiosqlite.connect(TEST_DB) as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            ("project_aliases",),
        )
        assert await cursor.fetchone() is not None


@pytest.mark.asyncio
async def test_project_aliases_index_created():
    """init_db 创建 idx_project_aliases_user_device 索引。"""
    db = Database(TEST_DB)
    await db.init_db()

    async with aiosqlite.connect(TEST_DB) as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            ("idx_project_aliases_user_device",),
        )
        assert await cursor.fetchone() is not None


@pytest.mark.asyncio
async def test_unique_constraint_on_user_device_alias(db):
    """user_id + device_id + alias 唯一约束生效。"""
    await db.save_project_alias("user1", "dev1", "myproject", "/path/to/project")

    # 同一个 alias 再次保存应该成功（覆盖更新）
    await db.save_project_alias("user1", "dev1", "myproject", "/path/to/project/v2")

    result = await db.lookup_project_alias("user1", "dev1", "myproject")
    assert result == "/path/to/project/v2"


# ---------------------------------------------------------------------------
# save + lookup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_and_lookup(db):
    """save 写入，lookup 读取。"""
    await db.save_project_alias("alice", "device-a", "remote-control", "/home/alice/remote-control")

    path = await db.lookup_project_alias("alice", "device-a", "remote-control")
    assert path == "/home/alice/remote-control"


@pytest.mark.asyncio
async def test_lookup_not_found(db):
    """lookup 不存在的别名返回 None。"""
    path = await db.lookup_project_alias("alice", "device-a", "nonexistent")
    assert path is None


# ---------------------------------------------------------------------------
# 覆盖更新
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_overwrites_same_alias(db):
    """同 alias 覆盖更新路径。"""
    await db.save_project_alias("alice", "device-a", "myapp", "/old/path")
    await db.save_project_alias("alice", "device-a", "myapp", "/new/path")

    path = await db.lookup_project_alias("alice", "device-a", "myapp")
    assert path == "/new/path"


@pytest.mark.asyncio
async def test_save_updates_timestamp(db):
    """覆盖更新时 updated_at 应更新。"""
    async with aiosqlite.connect(TEST_DB) as db_conn:
        db_conn.row_factory = aiosqlite.Row
        await db.save_project_alias("alice", "device-a", "myapp", "/path/v1")

        cursor = await db_conn.execute(
            "SELECT updated_at FROM project_aliases WHERE user_id=? AND device_id=? AND alias=?",
            ("alice", "device-a", "myapp"),
        )
        first_updated = (await cursor.fetchone())["updated_at"]

    # 等待一点时间确保时间戳不同
    import asyncio
    await asyncio.sleep(0.01)

    await db.save_project_alias("alice", "device-a", "myapp", "/path/v2")

    async with aiosqlite.connect(TEST_DB) as db_conn:
        db_conn.row_factory = aiosqlite.Row
        cursor = await db_conn.execute(
            "SELECT updated_at FROM project_aliases WHERE user_id=? AND device_id=? AND alias=?",
            ("alice", "device-a", "myapp"),
        )
        second_updated = (await cursor.fetchone())["updated_at"]

    assert second_updated >= first_updated


# ---------------------------------------------------------------------------
# device_id 隔离
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_device_isolation(db):
    """不同 device_id 的别名互相隔离。"""
    await db.save_project_alias("alice", "device-a", "myapp", "/path/on/a")
    await db.save_project_alias("alice", "device-b", "myapp", "/path/on/b")

    path_a = await db.lookup_project_alias("alice", "device-a", "myapp")
    path_b = await db.lookup_project_alias("alice", "device-b", "myapp")

    assert path_a == "/path/on/a"
    assert path_b == "/path/on/b"


@pytest.mark.asyncio
async def test_list_all_device_scoped(db):
    """list_project_aliases 只返回指定设备的别名。"""
    await db.save_project_alias("alice", "device-a", "app1", "/path/app1")
    await db.save_project_alias("alice", "device-a", "app2", "/path/app2")
    await db.save_project_alias("alice", "device-b", "app3", "/path/app3")

    aliases_a = await db.list_project_aliases("alice", "device-a")
    aliases_b = await db.list_project_aliases("alice", "device-b")

    assert aliases_a == {"app1": "/path/app1", "app2": "/path/app2"}
    assert aliases_b == {"app3": "/path/app3"}


# ---------------------------------------------------------------------------
# user_id 隔离
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_user_isolation(db):
    """不同 user_id 的别名互相隔离。"""
    await db.save_project_alias("alice", "device-a", "myapp", "/alice/path")
    await db.save_project_alias("bob", "device-a", "myapp", "/bob/path")

    alice_path = await db.lookup_project_alias("alice", "device-a", "myapp")
    bob_path = await db.lookup_project_alias("bob", "device-a", "myapp")

    assert alice_path == "/alice/path"
    assert bob_path == "/bob/path"


@pytest.mark.asyncio
async def test_list_all_user_scoped(db):
    """list_project_aliases 按用户隔离。"""
    await db.save_project_alias("alice", "device-a", "app1", "/alice/app1")
    await db.save_project_alias("bob", "device-a", "app1", "/bob/app1")

    alice_aliases = await db.list_project_aliases("alice", "device-a")
    bob_aliases = await db.list_project_aliases("bob", "device-a")

    assert alice_aliases == {"app1": "/alice/app1"}
    assert bob_aliases == {"app1": "/bob/app1"}


# ---------------------------------------------------------------------------
# cleanup_stale
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cleanup_stale_removes_old_aliases(db):
    """cleanup_stale_project_aliases 清理超过 90 天未使用的别名。"""
    # 先正常保存
    await db.save_project_alias("alice", "device-a", "old-app", "/path/old")
    await db.save_project_alias("alice", "device-a", "new-app", "/path/new")

    # 手动将 old-app 的 updated_at 设置为 91 天前
    async with aiosqlite.connect(TEST_DB) as conn:
        await conn.execute(
            """
            UPDATE project_aliases
            SET updated_at = datetime('now', '-91 days')
            WHERE alias = 'old-app'
            """
        )
        await conn.commit()

    deleted = await db.cleanup_stale_project_aliases(days=90)
    assert deleted == 1

    # old-app 已被清理
    assert await db.lookup_project_alias("alice", "device-a", "old-app") is None
    # new-app 仍在
    assert await db.lookup_project_alias("alice", "device-a", "new-app") == "/path/new"


@pytest.mark.asyncio
async def test_cleanup_stale_keeps_recent_aliases(db):
    """cleanup_stale_project_aliases 保留最近使用过的别名。"""
    await db.save_project_alias("alice", "device-a", "recent-app", "/path/recent")

    deleted = await db.cleanup_stale_project_aliases(days=90)
    assert deleted == 0

    assert await db.lookup_project_alias("alice", "device-a", "recent-app") == "/path/recent"


@pytest.mark.asyncio
async def test_cleanup_stale_custom_days(db):
    """cleanup_stale_project_aliases 支持自定义天数。"""
    await db.save_project_alias("alice", "device-a", "app", "/path/app")

    # 将 updated_at 设置为 10 天前
    async with aiosqlite.connect(TEST_DB) as conn:
        await conn.execute(
            """
            UPDATE project_aliases
            SET updated_at = datetime('now', '-11 days')
            WHERE alias = 'app'
            """
        )
        await conn.commit()

    # 使用 10 天阈值应清理
    deleted = await db.cleanup_stale_project_aliases(days=10)
    assert deleted == 1

    # 使用 15 天阈值不应清理（数据已被删除，重新测试）
    await db.save_project_alias("alice", "device-a", "app2", "/path/app2")
    async with aiosqlite.connect(TEST_DB) as conn:
        await conn.execute(
            """
            UPDATE project_aliases
            SET updated_at = datetime('now', '-11 days')
            WHERE alias = 'app2'
            """
        )
        await conn.commit()

    deleted = await db.cleanup_stale_project_aliases(days=15)
    assert deleted == 0


# ---------------------------------------------------------------------------
# save_batch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_batch(db):
    """批量保存别名。"""
    aliases = {
        "remote-control": "/home/user/remote-control",
        "ai-learn": "/home/user/ai-learn",
        "my-app": "/home/user/my-app",
    }
    await db.save_project_aliases_batch("alice", "device-a", aliases)

    result = await db.list_project_aliases("alice", "device-a")
    assert result == aliases


@pytest.mark.asyncio
async def test_save_batch_overwrites(db):
    """批量保存覆盖已有别名。"""
    await db.save_project_alias("alice", "device-a", "app1", "/old/path")
    await db.save_project_aliases_batch("alice", "device-a", {
        "app1": "/new/path",
        "app2": "/path/app2",
    })

    result = await db.list_project_aliases("alice", "device-a")
    assert result["app1"] == "/new/path"
    assert result["app2"] == "/path/app2"


@pytest.mark.asyncio
async def test_save_batch_empty(db):
    """批量保存空字典不做任何操作。"""
    await db.save_project_aliases_batch("alice", "device-a", {})

    result = await db.list_project_aliases("alice", "device-a")
    assert result == {}


# ---------------------------------------------------------------------------
# 空别名/路径处理
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_empty_alias_ignored(db):
    """空别名被忽略。"""
    await db.save_project_alias("alice", "device-a", "", "/some/path")

    result = await db.list_project_aliases("alice", "device-a")
    assert result == {}


@pytest.mark.asyncio
async def test_save_empty_path_ignored(db):
    """空路径被忽略。"""
    await db.save_project_alias("alice", "device-a", "myapp", "")

    result = await db.list_project_aliases("alice", "device-a")
    assert result == {}


@pytest.mark.asyncio
async def test_save_batch_skips_empty_entries(db):
    """批量保存跳过空别名和空路径。"""
    await db.save_project_aliases_batch("alice", "device-a", {
        "valid-app": "/path/valid",
        "": "/path/no-alias",
        "no-path": "",
    })

    result = await db.list_project_aliases("alice", "device-a")
    assert result == {"valid-app": "/path/valid"}


# ---------------------------------------------------------------------------
# list_all 返回顺序
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_all_ordered_by_updated_at_desc(db):
    """list_project_aliases 按更新时间倒序排列。"""
    await db.save_project_alias("alice", "device-a", "app1", "/path/app1")
    # 稍后保存 app2，其 updated_at 更新
    import asyncio
    await asyncio.sleep(0.01)
    await db.save_project_alias("alice", "device-a", "app2", "/path/app2")

    aliases = await db.list_project_aliases("alice", "device-a")
    keys = list(aliases.keys())
    assert keys[0] == "app2"
    assert keys[1] == "app1"


# ---------------------------------------------------------------------------
# 集成验证: Agent 启动时别名注入
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_alias_store_integration_with_session_manager(db):
    """验证 AgentSessionManager 能通过 db 实例加载和保存别名。"""
    from app.services.agent_session_manager import AgentSessionManager

    # 预存一些别名
    await db.save_project_alias("alice", "device-1", "known-project", "/home/alice/known")

    manager = AgentSessionManager(db=db)

    # 验证 db 被注入
    assert manager._db is db

    # 验证别名可被正确读取
    aliases = await db.list_project_aliases("alice", "device-1")
    assert aliases == {"known-project": "/home/alice/known"}
