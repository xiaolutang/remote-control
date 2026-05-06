"""
B056: PendingRequestRegistry 单元测试。

测试 registry 的 future 创建、查找、清理、超时处理。
"""
import asyncio
import pytest
from unittest.mock import MagicMock

from app.ws.agent_request import (
    PendingRequestRegistry,
    pending_registry,
)


@pytest.fixture(autouse=True)
def clean_registry():
    """每个测试前后清理 registry。"""
    pending_registry.clear_all()
    yield
    pending_registry.clear_all()


class TestPendingRequestRegistryCreate:
    """测试 future 创建。"""

    def test_create_tuple_key_future(self):
        """创建 tuple key 类型的 future（create/close/snapshot）。"""
        loop = asyncio.new_event_loop()
        try:
            future = pending_registry.create_tuple_future(
                "terminal_creates", ("session-1", "term-1"), loop=loop,
            )
            assert not future.done()
            assert pending_registry.has_tuple("terminal_creates", ("session-1", "term-1"))
        finally:
            loop.close()

    def test_create_id_key_future(self):
        """创建 string key 类型的 future（execute/lookup/tool_call）。"""
        loop = asyncio.new_event_loop()
        try:
            future = pending_registry.create_id_future(
                "execute_commands", "req-1", "session-1", loop=loop,
            )
            assert not future.done()
            assert pending_registry.has_id("execute_commands", "req-1")
        finally:
            loop.close()

    def test_tuple_key_dedup_raises_conflict(self):
        """重复创建同一 tuple key 应抛 HTTPException。"""
        from fastapi import HTTPException
        loop = asyncio.new_event_loop()
        try:
            pending_registry.create_tuple_future(
                "terminal_creates", ("session-1", "term-1"), loop=loop,
            )
            with pytest.raises(HTTPException) as exc_info:
                pending_registry.create_tuple_future(
                    "terminal_creates", ("session-1", "term-1"), loop=loop,
                )
            assert exc_info.value.status_code == 409
        finally:
            loop.close()


class TestPendingRequestRegistryLookup:
    """测试 future 查找。"""

    def test_get_tuple_future(self):
        loop = asyncio.new_event_loop()
        try:
            future = pending_registry.create_tuple_future(
                "terminal_creates", ("session-1", "term-1"), loop=loop,
            )
            found = pending_registry.get_tuple_future(
                "terminal_creates", ("session-1", "term-1"),
            )
            assert found is future
        finally:
            loop.close()

    def test_get_tuple_future_missing(self):
        found = pending_registry.get_tuple_future(
            "terminal_creates", ("session-1", "term-missing"),
        )
        assert found is None

    def test_pop_tuple_future(self):
        loop = asyncio.new_event_loop()
        try:
            future = pending_registry.create_tuple_future(
                "terminal_closes", ("session-1", "term-1"), loop=loop,
            )
            popped = pending_registry.pop_tuple_future(
                "terminal_closes", ("session-1", "term-1"),
            )
            assert popped is future
            # pop 后不应再存在
            assert pending_registry.get_tuple_future(
                "terminal_closes", ("session-1", "term-1"),
            ) is None
        finally:
            loop.close()

    def test_get_id_entry(self):
        loop = asyncio.new_event_loop()
        try:
            future = pending_registry.create_id_future(
                "execute_commands", "req-1", "session-1", loop=loop,
            )
            entry = pending_registry.get_id_entry("execute_commands", "req-1")
            assert entry is not None
            sid, fut = entry
            assert sid == "session-1"
            assert fut is future
        finally:
            loop.close()

    def test_get_id_entry_missing(self):
        entry = pending_registry.get_id_entry("execute_commands", "nonexistent")
        assert entry is None

    def test_pop_id_entry(self):
        loop = asyncio.new_event_loop()
        try:
            future = pending_registry.create_id_future(
                "lookup_knowledge", "req-1", "session-1", loop=loop,
            )
            entry = pending_registry.pop_id_entry("lookup_knowledge", "req-1")
            assert entry is not None
            _, fut = entry
            assert fut is future
            # pop 后不应再存在
            assert pending_registry.get_id_entry("lookup_knowledge", "req-1") is None
        finally:
            loop.close()


class TestPendingRequestRegistryCleanup:
    """测试 future 清理（按 session）。"""

    def test_cleanup_tuple_futures_by_session(self):
        """清理指定 session 的 tuple key futures。"""
        loop = asyncio.new_event_loop()
        try:
            f1 = pending_registry.create_tuple_future(
                "terminal_creates", ("session-a", "term-1"), loop=loop,
            )
            f2 = pending_registry.create_tuple_future(
                "terminal_creates", ("session-b", "term-2"), loop=loop,
            )
            pending_registry.cleanup_tuple_by_session(
                "terminal_creates", "session-a", "test_reason",
            )
            # session-a 的 future 被异常完成
            assert f1.done()
            with pytest.raises(RuntimeError, match="agent disconnected"):
                f1.result()
            # session-b 的 future 不受影响
            assert not f2.done()
        finally:
            loop.close()

    def test_cleanup_id_futures_by_session(self):
        """清理指定 session 的 id key futures。"""
        loop = asyncio.new_event_loop()
        try:
            f1 = pending_registry.create_id_future(
                "execute_commands", "req-1", "session-a", loop=loop,
            )
            f2 = pending_registry.create_id_future(
                "execute_commands", "req-2", "session-b", loop=loop,
            )
            pending_registry.cleanup_id_by_session(
                "execute_commands", "session-a", "test_reason",
            )
            assert f1.done()
            with pytest.raises(ConnectionError, match="agent disconnected"):
                f1.result()
            assert not f2.done()
        finally:
            loop.close()

    def test_cleanup_all_by_session(self):
        """清理指定 session 的所有类型的 futures。"""
        loop = asyncio.new_event_loop()
        try:
            f_create = pending_registry.create_tuple_future(
                "terminal_creates", ("session-a", "term-1"), loop=loop,
            )
            f_close = pending_registry.create_tuple_future(
                "terminal_closes", ("session-a", "term-2"), loop=loop,
            )
            f_snap = pending_registry.create_tuple_future(
                "terminal_snapshots", ("session-a", "req-1"), loop=loop,
            )
            f_exec = pending_registry.create_id_future(
                "execute_commands", "req-exec", "session-a", loop=loop,
            )
            f_lookup = pending_registry.create_id_future(
                "lookup_knowledge", "req-lk", "session-a", loop=loop,
            )
            f_tool = pending_registry.create_id_future(
                "tool_calls", "call-1", "session-a", loop=loop,
            )
            # 其他 session 的 future
            f_other = pending_registry.create_id_future(
                "execute_commands", "req-other", "session-b", loop=loop,
            )

            pending_registry.cleanup_all_by_session("session-a", "shutdown")

            for f in [f_create, f_close, f_snap, f_exec, f_lookup, f_tool]:
                assert f.done()
            assert not f_other.done()
        finally:
            loop.close()

    def test_cleanup_does_not_touch_done_futures(self):
        """已完成的 future 不应被修改。"""
        loop = asyncio.new_event_loop()
        try:
            future = pending_registry.create_tuple_future(
                "terminal_creates", ("session-a", "term-1"), loop=loop,
            )
            future.set_result({"status": "ok"})

            pending_registry.cleanup_tuple_by_session(
                "terminal_creates", "session-a", "test_reason",
            )

            # 结果应保持原值
            assert future.result() == {"status": "ok"}
        finally:
            loop.close()


class TestPendingRequestRegistryTimeoutCleanup:
    """测试超时清理。"""

    def test_cleanup_stale_futures_by_age(self):
        """超过指定时间的 pending futures 应被清理。"""
        import time
        loop = asyncio.new_event_loop()
        try:
            # 创建一个 future 并手动设置创建时间为 120 秒前
            future = pending_registry.create_tuple_future(
                "terminal_creates", ("session-a", "term-old"), loop=loop,
            )
            # 手动修改注册时间
            key = ("session-a", "term-old")
            pending_registry._tuple_timestamps["terminal_creates"][key] = time.time() - 120

            # 创建一个新 future
            new_future = pending_registry.create_tuple_future(
                "terminal_creates", ("session-b", "term-new"), loop=loop,
            )

            # 清理 60 秒以上的 stale futures
            cleaned = pending_registry.cleanup_stale(max_age_seconds=60)
            assert cleaned >= 1
            assert future.done()
            assert not new_future.done()
        finally:
            loop.close()

    def test_cleanup_stale_cancels_id_futures(self):
        """超时清理也适用于 id 类型的 futures。"""
        import time
        loop = asyncio.new_event_loop()
        try:
            future = pending_registry.create_id_future(
                "execute_commands", "req-old", "session-a", loop=loop,
            )
            # 修改时间戳
            pending_registry._id_timestamps["execute_commands"]["req-old"] = time.time() - 120

            cleaned = pending_registry.cleanup_stale(max_age_seconds=60)
            assert cleaned >= 1
            assert future.done()
        finally:
            loop.close()


class TestPendingRequestRegistryClearAll:
    """测试全量清理。"""

    def test_clear_all_empties_everything(self):
        loop = asyncio.new_event_loop()
        try:
            pending_registry.create_tuple_future(
                "terminal_creates", ("s1", "t1"), loop=loop,
            )
            pending_registry.create_id_future(
                "execute_commands", "r1", "s1", loop=loop,
            )
            pending_registry.clear_all()
            assert not pending_registry.has_tuple("terminal_creates", ("s1", "t1"))
            assert not pending_registry.has_id("execute_commands", "r1")
        finally:
            loop.close()


class TestPendingRequestRegistryRepr:
    """测试 registry 统计信息。"""

    def test_stats_counts(self):
        loop = asyncio.new_event_loop()
        try:
            pending_registry.create_tuple_future(
                "terminal_creates", ("s1", "t1"), loop=loop,
            )
            pending_registry.create_tuple_future(
                "terminal_creates", ("s1", "t2"), loop=loop,
            )
            pending_registry.create_id_future(
                "execute_commands", "r1", "s1", loop=loop,
            )
            stats = pending_registry.stats()
            assert stats["terminal_creates"] == 2
            assert stats["execute_commands"] == 1
            assert stats["terminal_closes"] == 0
        finally:
            loop.close()
