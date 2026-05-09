"""
S521: Server Redis pipeline 批量读取测试。

覆盖 S518 的 list_sessions_for_user 中 pipeline 批量读取优化。
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.store.session import list_sessions_for_user
from app.store.session_types import KEY_PREFIX, _session_key


def _session_data(session_id, user_id="user-1", name=None):
    """构造标准 session 数据"""
    data = {
        "session_id": session_id,
        "user_id": user_id,
        "status": "online",
        "agent_online": True,
        "terminals": [],
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    if name:
        data["name"] = name
    return data


class TestPipelineBatchRead:
    """pipeline 批量读取多个 session"""

    @pytest.mark.asyncio
    async def test_pipeline_reads_all_sessions(self):
        """pipeline 一次读取 3 个 session 数据"""
        sids = {"sess-1", "sess-2", "sess-3"}
        raw_values = [
            json.dumps(_session_data("sess-1")).encode(),
            json.dumps(_session_data("sess-2")).encode(),
            json.dumps(_session_data("sess-3")).encode(),
        ]

        mock_redis = AsyncMock()
        mock_redis.smembers = AsyncMock(return_value=sids)
        mock_redis.exists = AsyncMock(return_value=True)  # _ensure_user_index

        # Pipeline mock
        mock_pipe = AsyncMock()
        mock_pipe.get = MagicMock(return_value=mock_pipe)
        mock_pipe.execute = AsyncMock(return_value=raw_values)
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch("app.store.session.redis_conn") as mock_conn:
            mock_conn.get_redis = AsyncMock(return_value=mock_redis)
            result = await list_sessions_for_user("user-1")

        assert len(result) == 3
        result_ids = {s["session_id"] for s in result}
        assert result_ids == sids

    @pytest.mark.asyncio
    async def test_pipeline_skips_deleted_sessions(self):
        """pipeline 结果中 None 值（已删除 session）被跳过"""
        sids = {"sess-1", "sess-deleted", "sess-3"}
        raw_values = [
            json.dumps(_session_data("sess-1")).encode(),
            None,  # 已删除
            json.dumps(_session_data("sess-3")).encode(),
        ]

        mock_redis = AsyncMock()
        mock_redis.smembers = AsyncMock(return_value=sids)
        mock_redis.exists = AsyncMock(return_value=True)

        mock_pipe = AsyncMock()
        mock_pipe.get = MagicMock(return_value=mock_pipe)
        mock_pipe.execute = AsyncMock(return_value=raw_values)
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch("app.store.session.redis_conn") as mock_conn:
            mock_conn.get_redis = AsyncMock(return_value=mock_redis)
            result = await list_sessions_for_user("user-1")

        assert len(result) == 2
        result_ids = {s["session_id"] for s in result}
        assert "sess-deleted" not in result_ids


class TestPipelineFallback:
    """pipeline 不可用时回退到逐个读取"""

    @pytest.mark.asyncio
    async def test_fallback_on_pipeline_error(self):
        """pipeline 抛异常时回退到逐个 redis.get"""
        sids = {"sess-fb"}
        raw_data = json.dumps(_session_data("sess-fb")).encode()

        mock_redis = AsyncMock()
        mock_redis.smembers = AsyncMock(return_value=sids)
        mock_redis.exists = AsyncMock(return_value=True)

        # pipeline 抛 AttributeError
        mock_redis.pipeline = MagicMock(side_effect=AttributeError("no pipeline"))

        # 逐个 get
        mock_redis.get = AsyncMock(return_value=raw_data)

        with patch("app.store.session.redis_conn") as mock_conn:
            mock_conn.get_redis = AsyncMock(return_value=mock_redis)
            result = await list_sessions_for_user("user-1")

        assert len(result) == 1
        assert result[0]["session_id"] == "sess-fb"


class TestPipelineStaleCleanup:
    """pipeline 发现 stale session 后清理索引"""

    @pytest.mark.asyncio
    async def test_stale_ids_removed_from_index(self):
        """已删除 session 的索引被清理"""
        sids = {"sess-ok", "sess-stale"}
        raw_values = [
            json.dumps(_session_data("sess-ok")).encode(),
            None,  # stale
        ]

        mock_redis = AsyncMock()
        mock_redis.smembers = AsyncMock(return_value=sids)
        mock_redis.exists = AsyncMock(return_value=True)
        mock_redis.srem = AsyncMock()

        mock_pipe = AsyncMock()
        mock_pipe.get = MagicMock(return_value=mock_pipe)
        mock_pipe.execute = AsyncMock(return_value=raw_values)
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        with patch("app.store.session.redis_conn") as mock_conn:
            mock_conn.get_redis = AsyncMock(return_value=mock_redis)
            result = await list_sessions_for_user("user-1")

        assert len(result) == 1
        mock_redis.srem.assert_called_once()
        # 确认清理了 stale id
        srem_call = mock_redis.srem.call_args
        assert "sess-stale" in srem_call[0]


class TestListSessionsForUserEdgeCases:
    """边界场景"""

    @pytest.mark.asyncio
    async def test_empty_user_id(self):
        """空 user_id 返回空列表"""
        result = await list_sessions_for_user("")
        assert result == []

    @pytest.mark.asyncio
    async def test_none_user_id(self):
        """None user_id 返回空列表"""
        result = await list_sessions_for_user(None)
        assert result == []

    @pytest.mark.asyncio
    async def test_no_sessions_returns_empty(self):
        """用户无 session 返回空列表"""
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=True)
        mock_redis.smembers = AsyncMock(return_value=set())

        with patch("app.store.session.redis_conn") as mock_conn:
            mock_conn.get_redis = AsyncMock(return_value=mock_redis)
            result = await list_sessions_for_user("user-empty")

        assert result == []

    @pytest.mark.asyncio
    async def test_placeholder_filtered(self):
        """__empty__ 占位符被过滤"""
        sids = {"__empty__"}
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=True)
        mock_redis.smembers = AsyncMock(return_value=sids)

        with patch("app.store.session.redis_conn") as mock_conn:
            mock_conn.get_redis = AsyncMock(return_value=mock_redis)
            result = await list_sessions_for_user("user-placeholder")

        assert result == []
