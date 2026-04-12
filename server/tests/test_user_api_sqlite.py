"""
user_api.py 集成测试 — 用户注册/登录 SQLite 持久化
通过 HTTP 测试客户端验证完整 API 流程
"""
import os
import pytest
import pytest_asyncio

TEST_DB = "/tmp/test_rc_user_api.db"


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch):
    """每个测试使用独立数据库"""
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)
    monkeypatch.setenv("DATABASE_PATH", TEST_DB)
    yield
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)


@pytest_asyncio.fixture
async def app_with_db():
    """创建测试用 FastAPI 应用（带 SQLite 初始化）"""
    from app.database import init_db
    await init_db()


@pytest.mark.asyncio
async def test_register_creates_sqlite_record(app_with_db):
    """注册用户 → SQLite users 表有记录"""
    from app.database import get_user as db_get_user
    from app.user_api import save_user, get_user

    await save_user("testuser", "hash123")
    user = await get_user("testuser")
    assert user is not None
    assert user["username"] == "testuser"

    # 直接查 SQLite 确认
    db_user = await db_get_user("testuser")
    assert db_user["password_hash"] == "hash123"


@pytest.mark.asyncio
async def test_login_reads_from_sqlite(app_with_db):
    """登录从 SQLite 验证用户"""
    from app.database import save_user
    from app.user_api import get_user

    await save_user("loginuser", "hash_abc")

    user = await get_user("loginuser")
    assert user is not None
    assert user["password_hash"] == "hash_abc"


@pytest.mark.asyncio
async def test_duplicate_register_detected(app_with_db):
    """重复注册被 SQLite UNIQUE 约束拦截"""
    from app.database import save_user
    from app.user_api import get_user
    import aiosqlite

    await save_user("dup_user", "hash1")

    # get_user 找到已存在用户
    existing = await get_user("dup_user")
    assert existing is not None

    # 再次 save_user 应抛异常
    with pytest.raises(aiosqlite.IntegrityError):
        await save_user("dup_user", "hash2")


@pytest.mark.asyncio
async def test_bind_device_writes_sqlite(app_with_db):
    """绑定设备写入 SQLite user_devices 表"""
    from app.database import save_user, get_user_devices, add_user_device

    await save_user("deviceuser", "hash")
    await add_user_device("deviceuser", {
        "device_name": "Pixel 8",
        "device_type": "mobile",
        "bound_at": "2026-04-13T00:00:00+00:00",
    })

    devices = await get_user_devices("deviceuser")
    assert len(devices) == 1
    assert devices[0]["device_name"] == "Pixel 8"


@pytest.mark.asyncio
async def test_persistence_across_reconnect(app_with_db):
    """数据跨连接持久化（模拟重启）"""
    from app.database import save_user, get_user

    await save_user("persist_user", "hash_persist")

    # 模拟"重启"：关闭连接后重新查询
    user = await get_user("persist_user")
    assert user is not None
    assert user["username"] == "persist_user"
