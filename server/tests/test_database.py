"""
database.py 单元测试 — SQLite 用户持久化层
"""
import os
import pytest
import pytest_asyncio
import aiosqlite

# 测试用临时数据库路径
TEST_DB = "/tmp/test_rc_users.db"


@pytest.fixture(autouse=True)
def _clean_db():
    """每个测试配置独立数据库并清理"""
    from app.database import configure_database

    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    configure_database(TEST_DB)
    yield
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)


@pytest_asyncio.fixture
async def db_with_tables():
    """初始化表结构"""
    from app.database import init_db
    await init_db()
    return TEST_DB


@pytest.mark.asyncio
async def test_init_db_creates_tables(db_with_tables):
    """init_db 创建 users 和 user_devices 表"""
    async with aiosqlite.connect(TEST_DB) as db:
        # 检查 users 表
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
        )
        assert await cursor.fetchone() is not None

        # 检查 user_devices 表
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='user_devices'"
        )
        assert await cursor.fetchone() is not None


@pytest.mark.asyncio
async def test_init_db_creates_index(db_with_tables):
    """init_db 创建 username 索引"""
    async with aiosqlite.connect(TEST_DB) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_user_devices_username'"
        )
        assert await cursor.fetchone() is not None


@pytest.mark.asyncio
async def test_save_and_get_user(db_with_tables):
    """save_user 写入，get_user 读取"""
    from app.database import save_user, get_user

    await save_user("alice", "hash123")
    user = await get_user("alice")

    assert user is not None
    assert user["username"] == "alice"
    assert user["password_hash"] == "hash123"
    assert "created_at" in user


@pytest.mark.asyncio
async def test_get_user_not_found(db_with_tables):
    """get_user 查不存在的用户返回 None"""
    from app.database import get_user

    result = await get_user("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_save_duplicate_user_raises(db_with_tables):
    """重复 username 抛出 IntegrityError"""
    from app.database import save_user

    await save_user("bob", "hash1")
    with pytest.raises(aiosqlite.IntegrityError):
        await save_user("bob", "hash2")


@pytest.mark.asyncio
async def test_add_and_get_user_devices(db_with_tables):
    """add_user_device 写入，get_user_devices 读取"""
    from app.database import save_user, add_user_device, get_user_devices

    await save_user("charlie", "hash")
    await add_user_device("charlie", {
        "device_name": "iPhone 15",
        "device_type": "mobile",
        "bound_at": "2026-04-13T00:00:00+00:00",
    })
    await add_user_device("charlie", {
        "device_name": "MacBook",
        "device_type": "desktop",
        "bound_at": "2026-04-13T01:00:00+00:00",
    })

    devices = await get_user_devices("charlie")
    assert len(devices) == 2
    names = [d["device_name"] for d in devices]
    assert "iPhone 15" in names
    assert "MacBook" in names


@pytest.mark.asyncio
async def test_get_user_devices_empty(db_with_tables):
    """无设备时返回空列表"""
    from app.database import save_user, get_user_devices

    await save_user("dave", "hash")
    devices = await get_user_devices("dave")
    assert devices == []


@pytest.mark.asyncio
async def test_fk_prevents_device_without_user(db_with_tables):
    """外键约束：绑定设备到不存在的用户时抛出 IntegrityError"""
    from app.database import add_user_device

    with pytest.raises(aiosqlite.IntegrityError):
        await add_user_device("nonexistent_user", {
            "device_name": "Ghost Phone",
            "device_type": "mobile",
            "bound_at": "2026-04-13T00:00:00+00:00",
        })


@pytest.mark.asyncio
async def test_init_db_idempotent():
    """init_db 多次调用不报错"""
    from app.database import init_db

    await init_db()
    await init_db()  # 第二次不应抛异常


@pytest.mark.asyncio
async def test_init_db_creates_directory(tmp_path):
    """init_db 自动创建数据目录"""
    from app.database import configure_database, init_db

    db_path = os.path.join(str(tmp_path), "subdir", "test.db")
    configure_database(db_path)
    await init_db()
    assert os.path.exists(db_path)


@pytest.mark.asyncio
async def test_configure_database_creates_instance():
    """configure_database 返回 Database 实例"""
    from app.database import configure_database, Database

    db = configure_database("/tmp/test_configure.db")
    assert isinstance(db, Database)
    assert db.db_path == "/tmp/test_configure.db"
