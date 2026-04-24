"""
B078: Server 端 execute_command 集成测试。

测试 Future 映射、超时处理、频率限制、Agent 断连清理。
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ws_agent import (
    send_execute_command,
    _handle_execute_command_result,
    _cleanup_execute_command_futures,
    _check_rate_limit,
    pending_execute_commands,
    _execute_command_rate_tracker,
    ExecuteCommandResult,
    active_agents,
    AgentConnection,
)
from app.command_validator import MAX_COMMAND_RATE_PER_MINUTE


@pytest.fixture(autouse=True)
def clean_state():
    """每个测试前后清理全局状态。"""
    pending_execute_commands.clear()
    _execute_command_rate_tracker.clear()
    active_agents.clear()
    yield
    pending_execute_commands.clear()
    _execute_command_rate_tracker.clear()
    active_agents.clear()


class TestHandleExecuteCommandResult:
    """测试 Agent 返回结果处理。"""

    def test_success_result_resolves_future(self):
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        request_id = "test-req-123"
        pending_execute_commands[request_id] = ("session-1", future)

        _handle_execute_command_result({
            "type": "execute_command_result",
            "request_id": request_id,
            "exit_code": 0,
            "stdout": "hello",
            "stderr": "",
            "truncated": False,
            "timed_out": False,
        })

        assert future.done()
        result = future.result()
        assert isinstance(result, ExecuteCommandResult)
        assert result.exit_code == 0
        assert result.stdout == "hello"
        assert result.stderr == ""
        assert not result.truncated
        assert not result.timed_out
        assert request_id not in pending_execute_commands
        loop.close()

    def test_error_result_resolves_future(self):
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        request_id = "test-req-err"
        pending_execute_commands[request_id] = ("session-1", future)

        _handle_execute_command_result({
            "type": "execute_command_result",
            "request_id": request_id,
            "exit_code": 1,
            "stdout": "",
            "stderr": "command failed",
            "truncated": False,
            "timed_out": False,
        })

        assert future.done()
        result = future.result()
        assert result.exit_code == 1
        assert result.stderr == "command failed"
        loop.close()

    def test_timed_out_result(self):
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        request_id = "test-req-timeout"
        pending_execute_commands[request_id] = ("session-1", future)

        _handle_execute_command_result({
            "type": "execute_command_result",
            "request_id": request_id,
            "exit_code": -1,
            "stdout": "",
            "stderr": "command timed out",
            "truncated": False,
            "timed_out": True,
        })

        assert future.done()
        result = future.result()
        assert result.timed_out
        assert result.exit_code == -1
        loop.close()

    def test_truncated_result(self):
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        request_id = "test-req-trunc"
        pending_execute_commands[request_id] = ("session-1", future)

        _handle_execute_command_result({
            "type": "execute_command_result",
            "request_id": request_id,
            "exit_code": 0,
            "stdout": "a" * 5000,
            "stderr": "",
            "truncated": True,
            "timed_out": False,
        })

        assert future.done()
        result = future.result()
        assert result.truncated
        loop.close()

    def test_unknown_request_id_ignored(self):
        """未知 request_id 的消息应被忽略。"""
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        pending_execute_commands["known-id"] = ("session-1", future)

        _handle_execute_command_result({
            "type": "execute_command_result",
            "request_id": "unknown-id",
            "exit_code": 0,
            "stdout": "x",
            "stderr": "",
            "truncated": False,
            "timed_out": False,
        })

        assert not future.done()
        loop.close()

    def test_missing_request_id_ignored(self):
        _handle_execute_command_result({
            "type": "execute_command_result",
            "exit_code": 0,
            "stdout": "x",
        })
        # 不应抛异常

    def test_already_done_future_ignored(self):
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        future.set_result(ExecuteCommandResult(
            exit_code=0, stdout="old", stderr="",
            truncated=False, timed_out=False,
        ))
        request_id = "already-done"
        pending_execute_commands[request_id] = ("session-1", future)

        _handle_execute_command_result({
            "type": "execute_command_result",
            "request_id": request_id,
            "exit_code": 1,
            "stdout": "new",
            "stderr": "",
            "truncated": False,
            "timed_out": False,
        })

        assert future.result().stdout == "old"
        loop.close()


class TestCleanupExecuteCommandFutures:
    """测试 Agent 断连时清理 pending futures。"""

    def test_cleanup_sets_connection_error(self):
        loop = asyncio.new_event_loop()
        future1 = loop.create_future()
        future2 = loop.create_future()
        pending_execute_commands["req-1"] = ("session-1", future1)
        pending_execute_commands["req-2"] = ("session-1", future2)

        _cleanup_execute_command_futures("session-1", "agent_shutdown")

        assert future1.done()
        assert future2.done()
        with pytest.raises(ConnectionError, match="agent disconnected"):
            future1.result()
        with pytest.raises(ConnectionError, match="agent disconnected"):
            future2.result()
        assert len(pending_execute_commands) == 0
        loop.close()

    def test_cleanup_does_not_touch_done_futures(self):
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        future.set_result(ExecuteCommandResult(
            exit_code=0, stdout="", stderr="",
            truncated=False, timed_out=False,
        ))
        pending_execute_commands["req-done"] = ("session-1", future)

        _cleanup_execute_command_futures("session-1", "agent_shutdown")

        # 已经完成的 future 不应被改变
        assert future.result().exit_code == 0
        loop.close()


class TestRateLimit:
    """测试频率限制。"""

    def test_rate_limit_allows_up_to_max(self):
        session_id = "rate-test-session"
        for i in range(MAX_COMMAND_RATE_PER_MINUTE):
            assert _check_rate_limit(session_id), f"第 {i+1} 次应该通过"

    def test_rate_limit_blocks_over_max(self):
        session_id = "rate-test-session"
        for i in range(MAX_COMMAND_RATE_PER_MINUTE):
            _check_rate_limit(session_id)
        # 第 MAX+1 次应被拒绝
        assert not _check_rate_limit(session_id)

    def test_rate_limit_per_session(self):
        """不同 session 独立计算。"""
        session_a = "session-a"
        session_b = "session-b"
        for _ in range(MAX_COMMAND_RATE_PER_MINUTE):
            _check_rate_limit(session_a)
        assert not _check_rate_limit(session_a)
        # session_b 仍可使用
        assert _check_rate_limit(session_b)

    def test_rate_limit_resets_after_window(self):
        """超过时间窗口后限制重置。"""
        session_id = "window-test"
        # 填满配额
        for _ in range(MAX_COMMAND_RATE_PER_MINUTE):
            _check_rate_limit(session_id)
        assert not _check_rate_limit(session_id)

        # 模拟时间窗口过期（直接清除旧记录）
        old_timestamps = _execute_command_rate_tracker[session_id]
        # 将所有时间戳设为 120 秒前
        _execute_command_rate_tracker[session_id] = [
            t - 120 for t in old_timestamps
        ]

        # 现在应该允许
        assert _check_rate_limit(session_id)

    def test_rate_limit_cleans_old_entries(self):
        """频率检查时清理过期记录。"""
        session_id = "cleanup-test"
        # 添加一个过期的记录
        _execute_command_rate_tracker[session_id] = [time.time() - 120]
        # 新的请求应该正常通过，且过期记录被清理
        assert _check_rate_limit(session_id)
        # 只保留新的记录
        assert len(_execute_command_rate_tracker[session_id]) == 1


class TestSendExecuteCommand:
    """测试 send_execute_command 公开 API。"""

    @pytest.mark.asyncio
    async def test_reject_invalid_command(self):
        """白名单外的命令应返回 400。"""
        with pytest.raises(Exception) as exc_info:
            await send_execute_command("session-1", "rm -rf /")
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_reject_when_agent_offline(self):
        """Agent 离线应返回 409。"""
        with pytest.raises(Exception) as exc_info:
            await send_execute_command("session-1", "ls")
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_rate_limit_returns_429(self):
        """超频应返回 429。"""
        # 模拟 Agent 在线
        mock_ws = MagicMock()
        agent_conn = AgentConnection("session-1", mock_ws)
        agent_conn.send = AsyncMock()
        active_agents["session-1"] = agent_conn

        # 填满配额
        for _ in range(MAX_COMMAND_RATE_PER_MINUTE):
            _check_rate_limit("session-1")

        with pytest.raises(Exception) as exc_info:
            await send_execute_command("session-1", "ls")
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_success_flow(self):
        """正常流程：发送命令并接收结果。"""
        mock_ws = MagicMock()
        agent_conn = AgentConnection("session-1", mock_ws)
        agent_conn.send = AsyncMock()
        active_agents["session-1"] = agent_conn

        # 在后台模拟 Agent 响应
        async def simulate_response():
            await asyncio.sleep(0.05)
            # 找到 pending future 并 resolve
            for rid, entry in list(pending_execute_commands.items()):
                _, fut = entry
                if not fut.done():
                    fut.set_result(ExecuteCommandResult(
                        exit_code=0,
                        stdout="file1.txt\nfile2.txt\n",
                        stderr="",
                        truncated=False,
                        timed_out=False,
                    ))
                    break

        asyncio.create_task(simulate_response())

        result = await send_execute_command("session-1", "ls")
        assert isinstance(result, ExecuteCommandResult)
        assert result.exit_code == 0
        assert "file1.txt" in result.stdout
        assert not result.truncated
        assert not result.timed_out
        # send 被调用过
        agent_conn.send.assert_called_once()
        call_msg = agent_conn.send.call_args[0][0]
        assert call_msg["type"] == "execute_command"
        assert call_msg["command"] == "ls"

    @pytest.mark.asyncio
    async def test_timeout_returns_504(self):
        """Agent 不响应时应超时返回 504。"""
        mock_ws = MagicMock()
        agent_conn = AgentConnection("session-1", mock_ws)
        agent_conn.send = AsyncMock()
        active_agents["session-1"] = agent_conn

        with pytest.raises(Exception) as exc_info:
            await send_execute_command("session-1", "ls", timeout=1)
        assert exc_info.value.status_code == 504

    @pytest.mark.asyncio
    async def test_agent_disconnect_during_wait(self):
        """Agent 在等待中断连应返回 409。"""
        mock_ws = MagicMock()
        agent_conn = AgentConnection("session-1", mock_ws)
        agent_conn.send = AsyncMock()
        active_agents["session-1"] = agent_conn

        # 模拟断连清理
        async def simulate_disconnect():
            await asyncio.sleep(0.05)
            _cleanup_execute_command_futures("session-1", "agent_shutdown")

        asyncio.create_task(simulate_disconnect())

        with pytest.raises(Exception) as exc_info:
            await send_execute_command("session-1", "ls", timeout=5)
        assert exc_info.value.status_code == 409


class TestExecuteCommandResultDataclass:
    """测试 ExecuteCommandResult 数据类。"""

    def test_create_result(self):
        result = ExecuteCommandResult(
            exit_code=0,
            stdout="output",
            stderr="",
            truncated=False,
            timed_out=False,
        )
        assert result.exit_code == 0
        assert result.stdout == "output"
        assert not result.truncated
        assert not result.timed_out

    def test_result_with_errors(self):
        result = ExecuteCommandResult(
            exit_code=127,
            stdout="",
            stderr="command not found",
            truncated=False,
            timed_out=False,
        )
        assert result.exit_code == 127
        assert "not found" in result.stderr


class TestSessionIsolation:
    """测试跨 session 的 pending futures 隔离。"""

    def test_cleanup_only_affects_target_session(self):
        """一个 session 断连不应清理另一个 session 的 pending futures。"""
        loop = asyncio.new_event_loop()
        future_a = loop.create_future()
        future_b = loop.create_future()
        pending_execute_commands["req-a"] = ("session-a", future_a)
        pending_execute_commands["req-b"] = ("session-b", future_b)

        _cleanup_execute_command_futures("session-a", "agent_shutdown")

        # session-a 的 future 被清理
        assert future_a.done()
        with pytest.raises(ConnectionError):
            future_a.result()
        assert "req-a" not in pending_execute_commands

        # session-b 的 future 不受影响
        assert not future_b.done()
        assert "req-b" in pending_execute_commands
        loop.close()

    def test_cleanup_session_scoped_lookup_knowledge(self):
        """pending_lookup_knowledge 按 session 隔离清理。"""
        from app.ws_agent import pending_lookup_knowledge, _cleanup_pending_futures_by_id
        loop = asyncio.new_event_loop()
        future_a = loop.create_future()
        future_b = loop.create_future()
        pending_lookup_knowledge["req-a"] = ("session-a", future_a)
        pending_lookup_knowledge["req-b"] = ("session-b", future_b)

        _cleanup_pending_futures_by_id(pending_lookup_knowledge, "session-a", "shutdown")

        assert future_a.done()
        assert not future_b.done()
        pending_lookup_knowledge.clear()
        loop.close()

    def test_cleanup_session_scoped_tool_calls(self):
        """pending_tool_calls 按 session 隔离清理。"""
        from app.ws_agent import pending_tool_calls, _cleanup_pending_futures_by_id
        loop = asyncio.new_event_loop()
        future_a = loop.create_future()
        future_b = loop.create_future()
        pending_tool_calls["call-a"] = ("session-a", future_a)
        pending_tool_calls["call-b"] = ("session-b", future_b)

        _cleanup_pending_futures_by_id(pending_tool_calls, "session-a", "shutdown")

        assert future_a.done()
        assert not future_b.done()
        pending_tool_calls.clear()
        loop.close()
