"""
B058b: refresh_token_store 单元测试

覆盖 store/get/delete + Redis 不可用 fail-closed 场景。
"""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def mock_redis():
    """mock Redis 连接"""
    redis = AsyncMock()
    redis.set = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.delete = AsyncMock(return_value=0)
    return redis


class TestStoreRefreshToken:
    """store_refresh_token 测试"""

    @pytest.mark.asyncio
    async def test_store_sets_key_with_ttl(self, mock_redis):
        """存储 refresh token → 调用 redis.set(key, token, ex=ttl)"""
        from app.store.refresh_token_store import store_refresh_token

        with patch("app.store.refresh_token_store.get_redis", return_value=mock_redis):
            await store_refresh_token("sess-1", "rt-abc")

        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][0] == "refresh_token:sess-1"
        assert call_args[0][1] == "rt-abc"
        # TTL 应该是 30 天 * 24 * 60 * 60
        ttl = call_args[1].get("ex") or call_args[0][2]
        assert ttl == 30 * 24 * 60 * 60

    @pytest.mark.asyncio
    async def test_store_redis_down_raises(self):
        """Redis 不可用 → 抛异常（fail-closed）"""
        from app.store.refresh_token_store import store_refresh_token

        with patch("app.store.refresh_token_store.get_redis", side_effect=Exception("Redis down")):
            with pytest.raises(Exception, match="Redis down"):
                await store_refresh_token("sess-1", "rt-abc")

    @pytest.mark.asyncio
    async def test_store_redis_set_fails(self, mock_redis):
        """Redis SET 命令失败 → 抛异常"""
        from app.store.refresh_token_store import store_refresh_token

        mock_redis.set = AsyncMock(side_effect=Exception("SET failed"))
        with patch("app.store.refresh_token_store.get_redis", return_value=mock_redis):
            with pytest.raises(Exception, match="SET failed"):
                await store_refresh_token("sess-1", "rt-abc")


class TestGetStoredRefreshToken:
    """get_stored_refresh_token 测试"""

    @pytest.mark.asyncio
    async def test_get_returns_token(self, mock_redis):
        """Redis 中存在 → 返回 token"""
        from app.store.refresh_token_store import get_stored_refresh_token

        mock_redis.get = AsyncMock(return_value="rt-xyz")
        with patch("app.store.refresh_token_store.get_redis", return_value=mock_redis):
            result = await get_stored_refresh_token("sess-1")

        assert result == "rt-xyz"
        mock_redis.get.assert_called_once_with("refresh_token:sess-1")

    @pytest.mark.asyncio
    async def test_get_returns_none_when_not_exists(self, mock_redis):
        """Redis 中不存在 → 返回 None"""
        from app.store.refresh_token_store import get_stored_refresh_token

        mock_redis.get = AsyncMock(return_value=None)
        with patch("app.store.refresh_token_store.get_redis", return_value=mock_redis):
            result = await get_stored_refresh_token("sess-1")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_redis_down_raises(self):
        """Redis 不可用 → 抛异常（fail-closed）"""
        from app.store.refresh_token_store import get_stored_refresh_token

        with patch("app.store.refresh_token_store.get_redis", side_effect=Exception("Redis down")):
            with pytest.raises(Exception, match="Redis down"):
                await get_stored_refresh_token("sess-1")

    @pytest.mark.asyncio
    async def test_get_redis_get_fails(self, mock_redis):
        """Redis GET 命令失败 → 抛异常"""
        from app.store.refresh_token_store import get_stored_refresh_token

        mock_redis.get = AsyncMock(side_effect=Exception("GET failed"))
        with patch("app.store.refresh_token_store.get_redis", return_value=mock_redis):
            with pytest.raises(Exception, match="GET failed"):
                await get_stored_refresh_token("sess-1")


class TestDeleteRefreshToken:
    """delete_refresh_token 测试"""

    @pytest.mark.asyncio
    async def test_delete_calls_redis_delete(self, mock_redis):
        """删除 → 调用 redis.delete(key)"""
        from app.store.refresh_token_store import delete_refresh_token

        with patch("app.store.refresh_token_store.get_redis", return_value=mock_redis):
            await delete_refresh_token("sess-1")

        mock_redis.delete.assert_called_once_with("refresh_token:sess-1")

    @pytest.mark.asyncio
    async def test_delete_redis_down_raises(self):
        """Redis 不可用 → 抛异常（fail-closed）"""
        from app.store.refresh_token_store import delete_refresh_token

        with patch("app.store.refresh_token_store.get_redis", side_effect=Exception("Redis down")):
            with pytest.raises(Exception, match="Redis down"):
                await delete_refresh_token("sess-1")

    @pytest.mark.asyncio
    async def test_delete_redis_delete_fails(self, mock_redis):
        """Redis DELETE 命令失败 → 抛异常"""
        from app.store.refresh_token_store import delete_refresh_token

        mock_redis.delete = AsyncMock(side_effect=Exception("DELETE failed"))
        with patch("app.store.refresh_token_store.get_redis", return_value=mock_redis):
            with pytest.raises(Exception, match="DELETE failed"):
                await delete_refresh_token("sess-1")


class TestKeyFormat:
    """验证 Redis key 格式"""

    def test_key_format(self):
        """key 格式为 refresh_token:{session_id}"""
        from app.store.refresh_token_store import _refresh_token_key

        assert _refresh_token_key("abc-123") == "refresh_token:abc-123"
        assert _refresh_token_key("") == "refresh_token:"
