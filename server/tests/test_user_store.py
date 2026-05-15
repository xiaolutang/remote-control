"""
UserStoreMixin.get_user_max_terminals 单元测试
"""
import os
import pytest
import pytest_asyncio

from app.store.database import configure_database, init_db
from app.store.session_types import DEFAULT_MAX_TERMINALS

TEST_DB = "/tmp/test_rc_user_store.db"


@pytest.fixture(autouse=True)
def _clean_db():
    """每个测试配置独立数据库并清理"""
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    configure_database(TEST_DB)
    yield
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)


@pytest_asyncio.fixture
async def db():
    """初始化表结构，返回 Database 实例"""
    from app.store.database import _get_db
    await init_db()
    return _get_db()


@pytest.mark.asyncio
async def test_get_user_max_terminals_returns_user_value(db):
    """用户存在且设置了 max_terminals 时返回用户值"""
    await db.save_user("alice", "hash123")
    # 直接写 max_terminals（migration 已添加列）
    async with db._connect() as conn:
        await conn.execute("UPDATE users SET max_terminals = 5 WHERE username = ?", ("alice",))
        await conn.commit()

    result = await db.get_user_max_terminals("alice")
    assert result == 5


@pytest.mark.asyncio
async def test_get_user_max_terminals_fallback_to_default_when_user_missing(db):
    """用户不存在时 get_user_max_terminals 返回 None，由 database 模块函数 fallback 到 DEFAULT"""
    result = await db.get_user_max_terminals("nonexistent")
    assert result is None

    # 验证模块级便捷函数 fallback 行为
    from app.store import database
    fallback = await database.get_user_max_terminals("nonexistent")
    assert fallback == DEFAULT_MAX_TERMINALS
