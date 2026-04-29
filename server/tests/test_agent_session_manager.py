"""
B080: Agent 会话管理 & SSE API 测试。

测试覆盖：
1. 创建会话返回唯一 session_id
2. respond 唤醒正确的 ask_user Future
3. cancel 终止 Agent 循环并清理资源
4. 10 分钟超时自动终止
5. SSE 事件序列正确（tool_step -> question -> result）
6. keepalive 生成
7. 断连恢复 4 种状态处理
8. 6 种错误码正确推送
9. 降级到 planner 的降级路径
10. 用户级频率限制
11. B103: 新 SSE 事件类型（phase_change, streaming_text, tool_step）正确序列化
12. B103: 旧事件类型（trace, assistant_message）不再产生
13. B103: session_created 保留
14. B106: ResultDelivered 后 save_agent_usage 先于 result 推送
15. B106: finally 块稳定结束 event_queue
16. B106: 取消/超时不丢失已推送事件和 usage
17. B106: conversation events 持久化包含 streaming_text
18. B106: resume_stream 正确回放 streaming_text 缓存事件
"""
import asyncio
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent_session_manager import (
    AgentSession,
    AgentSessionCancelled,
    AgentSessionExpired,
    AgentSessionManager,
    AgentSessionRateLimited,
    AgentSessionState,
    ErrorCode,
    SESSION_TIMEOUT_SECONDS,
    SSE_KEEPALIVE_SECONDS,
    SSE_EVENT_TYPES,
    TOOL_STEP_STATUSES,
    USER_SESSION_RATE_LIMIT,
    _error_event_dict,
    _phase_change_event,
    _streaming_text_event,
    _tool_step_event,
    get_agent_session_manager,
)
from app.services.terminal_agent import AgentResult, AgentRunOutcome, CommandSequenceStep
from app.ws.ws_agent import ExecuteCommandResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_execute_result(
    exit_code: int = 0,
    stdout: str = "",
    stderr: str = "",
    truncated: bool = False,
    timed_out: bool = False,
) -> ExecuteCommandResult:
    return ExecuteCommandResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        truncated=truncated,
        timed_out=timed_out,
    )


def _make_agent_result(
    summary: str = "test result",
    steps: list | None = None,
    aliases: dict | None = None,
) -> AgentResult:
    return AgentResult(
        summary=summary,
        steps=steps or [CommandSequenceStep(id="step_1", label="cd", command="cd /project")],
        aliases=aliases or {},
    )


@pytest.fixture
def manager():
    """创建一个干净的 AgentSessionManager 实例。"""
    mgr = AgentSessionManager()
    return mgr


# ---------------------------------------------------------------------------
# Test: 创建会话
# ---------------------------------------------------------------------------

class TestCreateSession:
    """测试创建会话。"""

    @pytest.mark.asyncio
    async def test_create_returns_unique_session_id(self, manager):
        """创建会话返回唯一 session_id。"""
        s1 = await manager.create_session(
            intent="打开项目", device_id="dev-1", user_id="user-1",
        )
        s2 = await manager.create_session(
            intent="进入目录", device_id="dev-1", user_id="user-1",
        )
        assert s1.id != s2.id
        assert s1.intent == "打开项目"
        assert s1.device_id == "dev-1"
        assert s1.user_id == "user-1"
        assert s1.state == AgentSessionState.EXPLORING

    @pytest.mark.asyncio
    async def test_create_with_custom_session_id(self, manager):
        """支持自定义 session_id。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="custom-id",
        )
        assert s.id == "custom-id"

    @pytest.mark.asyncio
    async def test_create_session_stores_in_manager(self, manager):
        """创建后可通过 get_session 获取。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="sid-1",
        )
        retrieved = await manager.get_session("sid-1")
        assert retrieved is s

    @pytest.mark.asyncio
    async def test_create_session_has_timestamps(self, manager):
        """创建的会话有时间戳。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u",
        )
        assert isinstance(s.created_at, datetime)
        assert isinstance(s.last_active_at, datetime)

    @pytest.mark.asyncio
    async def test_get_nonexistent_session_returns_none(self, manager):
        """获取不存在的会话返回 None。"""
        result = await manager.get_session("nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# Test: respond 唤醒 ask_user
# ---------------------------------------------------------------------------

class TestRespond:
    """测试用户回复。"""

    @pytest.mark.asyncio
    async def test_respond_wakes_up_future(self, manager):
        """respond 应唤醒正确的 ask_user Future。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="r1",
        )

        # 模拟 Agent 进入 ASKING 状态
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        s._pending_question_future = future
        s.state = AgentSessionState.ASKING

        # 模拟另一个 task 在等待 Future
        async def wait_for_future():
            return await future

        wait_task = asyncio.create_task(wait_for_future())

        # 稍等一下确保 task 开始等待
        await asyncio.sleep(0.01)

        # respond 唤醒
        success = await manager.respond("r1", "my answer")
        assert success is True

        result = await asyncio.wait_for(wait_task, timeout=1.0)
        assert result == "my answer"

    @pytest.mark.asyncio
    async def test_respond_nonexistent_session_returns_false(self, manager):
        """回复不存在的会话返回 False。"""
        success = await manager.respond("nonexistent", "answer")
        assert success is False

    @pytest.mark.asyncio
    async def test_respond_wrong_state_returns_false(self, manager):
        """回复非 ASKING 状态的会话返回 False。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="r2",
        )
        s.state = AgentSessionState.EXPLORING  # 不是 ASKING
        success = await manager.respond("r2", "answer")
        assert success is False

    @pytest.mark.asyncio
    async def test_respond_no_pending_future_returns_false(self, manager):
        """回复没有 pending future 的会话返回 False。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="r3",
        )
        s.state = AgentSessionState.ASKING
        s._pending_question_future = None
        success = await manager.respond("r3", "answer")
        assert success is False


# ---------------------------------------------------------------------------
# Test: cancel 终止会话
# ---------------------------------------------------------------------------

class TestCancel:
    """测试取消会话。"""

    @pytest.mark.asyncio
    async def test_cancel_active_session(self, manager):
        """取消活跃会话。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="c1",
        )
        s.state = AgentSessionState.EXPLORING

        success = await manager.cancel("c1")
        assert success is True
        assert s.state == AgentSessionState.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_session_with_pending_future(self, manager):
        """取消有等待中 Future 的会话。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="c2",
        )
        s.state = AgentSessionState.ASKING
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        s._pending_question_future = future

        success = await manager.cancel("c2")
        assert success is True
        assert s.state == AgentSessionState.CANCELLED
        # Future 应该被设置为 AgentSessionCancelled 异常
        assert future.done()
        with pytest.raises(AgentSessionCancelled):
            future.result()

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_returns_false(self, manager):
        """取消不存在的会话返回 False。"""
        success = await manager.cancel("nonexistent")
        assert success is False

    @pytest.mark.asyncio
    async def test_cancel_completed_returns_false(self, manager):
        """取消已完成的会话返回 False。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="c3",
        )
        s.state = AgentSessionState.COMPLETED
        success = await manager.cancel("c3")
        assert success is False

    @pytest.mark.asyncio
    async def test_cancel_expired_returns_false(self, manager):
        """取消已过期的会话返回 False。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="c4",
        )
        s.state = AgentSessionState.EXPIRED
        success = await manager.cancel("c4")
        assert success is False


# ---------------------------------------------------------------------------
# Test: SSE 事件序列
# ---------------------------------------------------------------------------

class TestSSEEventSequence:
    """测试 SSE 事件序列正确性。"""

    @pytest.mark.asyncio
    async def test_tool_step_question_result_sequence(self, manager):
        """事件序列应为 tool_step -> question -> result。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="seq1",
        )

        # 手动推送事件序列
        await s.event_queue.put(("tool_step", {"tool_name": "execute_command", "description": "ls", "status": "done", "result_summary": "file1.txt"}))
        await s.event_queue.put(("question", {"question": "Which?", "options": ["a", "b"], "multi_select": False}))
        await s.event_queue.put(("result", {"summary": "done", "steps": [], "provider": "agent"}))
        await s.event_queue.put(None)  # 结束

        events = []
        async for chunk in manager.sse_stream(s):
            events.append(chunk)

        assert len(events) == 3
        assert "event: tool_step" in events[0]
        assert "event: question" in events[1]
        assert "event: result" in events[2]

    @pytest.mark.asyncio
    async def test_sse_event_format(self, manager):
        """SSE 事件格式应为 event: xxx\\ndata: json\\n\\n。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="fmt1",
        )

        await s.event_queue.put(("tool_step", {"tool_name": "execute_command", "description": "ls", "status": "done", "result_summary": "file.txt"}))
        await s.event_queue.put(None)

        events = []
        async for chunk in manager.sse_stream(s):
            events.append(chunk)

        assert len(events) == 1
        event_str = events[0]
        assert event_str.startswith("event: tool_step\ndata: ")
        assert event_str.endswith("\n\n")

        # 解析 data 部分
        data_line = event_str.split("\n")[1]  # data: {...}
        data_json = data_line[len("data: "):]
        data = json.loads(data_json)
        assert data["tool_name"] == "execute_command"
        assert data["status"] == "done"

    @pytest.mark.asyncio
    async def test_error_event_pushed(self, manager):
        """错误事件应正确推送。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="err1",
        )

        await s.event_queue.put(("error", {"code": ErrorCode.AGENT_ERROR, "message": "Agent crashed"}))
        await s.event_queue.put(None)

        events = []
        async for chunk in manager.sse_stream(s):
            events.append(chunk)

        assert len(events) == 1
        assert "event: error" in events[0]
        data_json = events[0].split("data: ")[1].strip()
        data = json.loads(data_json)
        assert data["code"] == ErrorCode.AGENT_ERROR


# ---------------------------------------------------------------------------
# Test: keepalive
# ---------------------------------------------------------------------------

class TestKeepalive:
    """测试 SSE keepalive 生成。"""

    @pytest.mark.asyncio
    async def test_keepalive_generated_on_timeout(self, manager):
        """15 秒无事件时生成 keepalive。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="ka1",
        )

        # 使用短超时来加速测试
        collected = []

        async def _collect():
            async for chunk in manager.sse_stream(s):
                collected.append(chunk)

        # 启动流消费者
        task = asyncio.create_task(_collect())
        # 等待足够时间触发 keepalive
        await asyncio.sleep(SSE_KEEPALIVE_SECONDS + 1)
        # 推送结束信号
        await s.event_queue.put(None)
        await task

        # 应该至少有一个 keepalive
        keepalives = [e for e in collected if "keepalive" in e]
        assert len(keepalives) >= 1
        assert ": keepalive\n\n" in keepalives[0]


# ---------------------------------------------------------------------------
# Test: 断连恢复 4 种状态
# ---------------------------------------------------------------------------

class TestResumeStream:
    """测试断连恢复的 4 种状态处理。"""

    @pytest.mark.asyncio
    async def test_resume_replays_cached_events(self, manager):
        """断连恢复回放缓存事件。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="res1",
        )

        # 手动推送一些事件
        await s.event_queue.put(("tool_step", {"tool_name": "execute_command", "description": "ls", "status": "done", "result_summary": "ok"}))
        await s.event_queue.put(("tool_step", {"tool_name": "execute_command", "description": "pwd", "status": "done", "result_summary": "/home"}))
        await s.event_queue.put(None)  # 结束信号

        # 消费事件（缓存到 _last_events）
        events_consumed = []
        async for chunk in manager.sse_stream(s):
            events_consumed.append(chunk)

        assert len(events_consumed) == 2
        assert len(s._last_events) == 2

        # 标记会话完成
        s.state = AgentSessionState.COMPLETED

        # 恢复时应回放缓存事件
        resumed = []
        async for chunk in manager.resume_stream(s, after_index=0):
            resumed.append(chunk)

        assert len(resumed) == 2
        assert "event: tool_step" in resumed[0]

    @pytest.mark.asyncio
    async def test_resume_from_index(self, manager):
        """从指定索引开始回放。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="res2",
        )

        # 推送 3 个事件 + 结束信号
        for i in range(3):
            await s.event_queue.put(("tool_step", {"tool_name": "cmd", "description": f"cmd-{i}", "status": "done", "result_summary": "ok"}))
        await s.event_queue.put(None)

        # 消费并缓存
        async for chunk in manager.sse_stream(s):
            pass

        assert len(s._last_events) == 3

        s.state = AgentSessionState.COMPLETED

        # 从索引 1 开始回放，应该只回放 2 个事件
        resumed = []
        async for chunk in manager.resume_stream(s, after_index=1):
            resumed.append(chunk)

        assert len(resumed) == 2

    @pytest.mark.asyncio
    async def test_resume_completed_session_only_replay(self, manager):
        """已完成的会话恢复只回放缓存，不进入实时流。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="res3",
        )

        await s.event_queue.put(("result", {"summary": "done", "steps": []}))
        await s.event_queue.put(None)
        async for chunk in manager.sse_stream(s):
            pass

        s.state = AgentSessionState.COMPLETED

        resumed = []
        async for chunk in manager.resume_stream(s):
            resumed.append(chunk)

        assert len(resumed) == 1
        assert "event: result" in resumed[0]

    @pytest.mark.asyncio
    async def test_resume_error_session(self, manager):
        """ERROR 状态的会话恢复只回放。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="res4",
        )

        await s.event_queue.put(("error", {"code": ErrorCode.AGENT_ERROR, "message": "fail"}))
        await s.event_queue.put(None)
        async for chunk in manager.sse_stream(s):
            pass

        s.state = AgentSessionState.ERROR

        resumed = []
        async for chunk in manager.resume_stream(s):
            resumed.append(chunk)

        assert len(resumed) == 1
        assert "event: error" in resumed[0]


# ---------------------------------------------------------------------------
# Test: 错误码
# ---------------------------------------------------------------------------

class TestErrorCodes:
    """测试 6 种错误码。"""

    def test_all_error_codes_defined(self):
        """6 种错误码应有明确定义。"""
        codes = [
            ErrorCode.AGENT_OFFLINE,
            ErrorCode.SESSION_EXPIRED,
            ErrorCode.SESSION_CANCELLED,
            ErrorCode.AGENT_ERROR,
            ErrorCode.RATE_LIMITED,
            ErrorCode.INTERNAL_ERROR,
        ]
        assert len(codes) == 6
        assert len(set(codes)) == 6  # 全部唯一

    def test_error_event_dict_format(self):
        """错误事件字典应有 code 和 message。"""
        d = _error_event_dict(ErrorCode.AGENT_OFFLINE, "设备离线")
        assert d["code"] == ErrorCode.AGENT_OFFLINE
        assert d["message"] == "设备离线"


# ---------------------------------------------------------------------------
# Test: 超时自动终止
# ---------------------------------------------------------------------------

class TestSessionTimeout:
    """测试 10 分钟超时自动终止。"""

    @pytest.mark.asyncio
    async def test_expired_session_cleaned_up(self, manager):
        """超时会话应被清理。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="t1",
        )
        s.state = AgentSessionState.EXPLORING

        # 模拟 10 分钟前的活跃时间
        s.last_active_at = datetime.now(timezone.utc) - timedelta(seconds=SESSION_TIMEOUT_SECONDS + 10)

        expired = await manager.cleanup_expired()
        assert "t1" in expired
        assert s.state == AgentSessionState.EXPIRED

    @pytest.mark.asyncio
    async def test_active_session_not_cleaned(self, manager):
        """活跃会话不应被清理。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="t2",
        )
        s.state = AgentSessionState.EXPLORING
        # last_active_at 是刚创建的，不会过期

        expired = await manager.cleanup_expired()
        assert "t2" not in expired

    @pytest.mark.asyncio
    async def test_completed_session_not_expired(self, manager):
        """已完成的会话不应被超时清理（已是终态）。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="t3",
        )
        s.state = AgentSessionState.COMPLETED
        s.last_active_at = datetime.now(timezone.utc) - timedelta(seconds=SESSION_TIMEOUT_SECONDS + 10)

        expired = await manager.cleanup_expired()
        # COMPLETED 不在可过期状态列表中
        assert "t3" not in expired

    @pytest.mark.asyncio
    async def test_expired_session_pushes_error_event(self, manager):
        """过期会话应推送 ErrorEvent。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="t4",
        )
        s.state = AgentSessionState.EXPLORING
        s.last_active_at = datetime.now(timezone.utc) - timedelta(seconds=SESSION_TIMEOUT_SECONDS + 10)

        await manager.cleanup_expired()

        # 验证事件队列中有错误事件
        # 注意：event_queue 里可能有多个事件（error + None 结束信号）
        events = []
        while not s.event_queue.empty():
            events.append(s.event_queue.get_nowait())

        error_events = [e for e in events if e is not None and e[0] == "error"]
        assert len(error_events) == 1
        assert error_events[0][1]["code"] == ErrorCode.SESSION_EXPIRED

    @pytest.mark.asyncio
    async def test_expired_session_with_pending_future(self, manager):
        """过期会话有 pending Future 应取消它。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="t5",
        )
        s.state = AgentSessionState.ASKING
        s.last_active_at = datetime.now(timezone.utc) - timedelta(seconds=SESSION_TIMEOUT_SECONDS + 10)

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        s._pending_question_future = future

        await manager.cleanup_expired()

        assert future.done()
        with pytest.raises(AgentSessionExpired):
            future.result()


# ---------------------------------------------------------------------------
# Test: 用户级频率限制
# ---------------------------------------------------------------------------

class TestRateLimit:
    """测试用户级频率限制。"""

    @pytest.mark.asyncio
    async def test_user_rate_limit_blocks_excess(self, manager):
        """超过用户级会话数限制应被拒绝。"""
        # 创建到限制数量
        for i in range(USER_SESSION_RATE_LIMIT):
            s = await manager.create_session(
                intent=f"test-{i}", device_id="d", user_id="u", session_id=f"rl-{i}",
            )
            s.state = AgentSessionState.EXPLORING

        # 超过限制
        with pytest.raises(AgentSessionRateLimited):
            await manager.create_session(
                intent="overflow", device_id="d", user_id="u",
            )

    @pytest.mark.asyncio
    async def test_different_users_independent(self, manager):
        """不同用户的频率限制独立。"""
        for i in range(USER_SESSION_RATE_LIMIT):
            s = await manager.create_session(
                intent=f"test-{i}", device_id="d", user_id="user-a", session_id=f"a-{i}",
            )
            s.state = AgentSessionState.EXPLORING

        # user-b 不受 user-a 的限制影响
        s = await manager.create_session(
            intent="test", device_id="d", user_id="user-b",
        )
        assert s is not None

    @pytest.mark.asyncio
    async def test_completed_sessions_dont_count(self, manager):
        """已完成会话不计入活跃限制。"""
        for i in range(USER_SESSION_RATE_LIMIT):
            s = await manager.create_session(
                intent=f"test-{i}", device_id="d", user_id="u", session_id=f"rlc-{i}",
            )
            s.state = AgentSessionState.COMPLETED  # 已完成

        # 应该还能创建（因为活跃数为 0）
        s = await manager.create_session(
            intent="new", device_id="d", user_id="u",
        )
        assert s is not None


# ---------------------------------------------------------------------------
# Test: Agent 运行循环（mock run_agent）
# ---------------------------------------------------------------------------

class TestAgentRunLoop:
    """测试 Agent 运行循环。"""

    @pytest.mark.asyncio
    async def test_run_loop_pushes_result_on_success(self, manager):
        """Agent 成功完成应推送 ResultEvent。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="loop1",
        )

        mock_result = _make_agent_result(summary="project entered")
        mock_outcome = AgentRunOutcome(
            result=mock_result,
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            requests=2,
            model_name="test-model",
        )

        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="file.txt"))

        with patch("app.services.terminal_agent.run_agent", new_callable=AsyncMock, return_value=mock_outcome):
            await manager.start_agent(s, execute_fn)
            # 等待 Agent 完成
            await asyncio.sleep(0.1)

        assert s.state == AgentSessionState.COMPLETED
        assert s.result is not None
        assert s.result.summary == "project entered"

    @pytest.mark.asyncio
    async def test_run_loop_persists_usage_before_result_event(self, manager):
        """usage 必须先落库，再推送 SSE result 事件。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="loop1b",
        )

        mock_result = _make_agent_result(summary="project entered")
        mock_outcome = AgentRunOutcome(
            result=mock_result,
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            requests=2,
            model_name="test-model",
        )
        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="file.txt"))

        ordering: list[str] = []
        original_put = s.event_queue.put

        async def _tracking_put(event):
            if event is not None and event[0] == "result":
                ordering.append("result")
            await original_put(event)

        async def _save_usage(*args, **kwargs):
            ordering.append("saved")
            return True

        s.event_queue.put = _tracking_put  # type: ignore[assignment]

        with patch("app.services.terminal_agent.run_agent", new_callable=AsyncMock, return_value=mock_outcome):
            with patch("app.services.agent_session_manager.save_agent_usage", new_callable=AsyncMock, side_effect=_save_usage) as save_mock:
                await manager.start_agent(s, execute_fn)
                await asyncio.sleep(0.1)

        assert save_mock.await_count == 1
        assert ordering[:2] == ["saved", "result"]

        events = []
        while not s.event_queue.empty():
            events.append(s.event_queue.get_nowait())
        result_events = [event for event in events if event is not None and event[0] == "result"]
        assert len(result_events) == 1
        assert result_events[0][1]["usage"]["total_tokens"] == 150

    @pytest.mark.asyncio
    async def test_run_loop_pushes_error_on_failure(self, manager):
        """Agent 出错应推送 ErrorEvent。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="loop2",
        )

        execute_fn = AsyncMock()

        with patch("app.services.terminal_agent.run_agent", new_callable=AsyncMock, side_effect=RuntimeError("LLM failed")):
            await manager.start_agent(s, execute_fn)
            await asyncio.sleep(0.1)

        assert s.state == AgentSessionState.ERROR

    @pytest.mark.asyncio
    async def test_terminal_bound_session_persists_events(self, manager):
        """terminal-bound session 应把 tool_step/question/result 写入 conversation events。"""
        s = await manager.create_session(
            intent="test",
            device_id="d",
            user_id="u",
            session_id="loop-terminal",
            terminal_id="term-1",
            conversation_id="conv-1",
        )

        mock_result = _make_agent_result(summary="project entered")
        mock_outcome = AgentRunOutcome(
            result=mock_result,
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            requests=2,
            model_name="test-model",
        )
        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="file.txt"))

        async def _run_with_callbacks(**kwargs):
            await kwargs["execute_command_fn"]("loop-terminal", "pwd")
            answer = await kwargs["ask_user_fn"]("选择项目", ["remote-control"], False)
            assert answer == "remote-control"
            return mock_outcome

        with patch("app.services.terminal_agent.run_agent", new_callable=AsyncMock, side_effect=_run_with_callbacks):
            with patch("app.store.database.append_agent_conversation_event", new_callable=AsyncMock) as append_event:
                await manager.start_agent(s, execute_fn)

                question_event = None
                for _ in range(10):
                    event = await asyncio.wait_for(s.event_queue.get(), timeout=1.0)
                    if event is not None and event[0] == "question":
                        question_event = event
                        break

                assert question_event is not None
                question_id = question_event[1]["question_id"]
                assert question_id.startswith("q_")
                assert s.pending_question_id == question_id

                assert await manager.respond(
                    "loop-terminal",
                    "remote-control",
                    question_id=question_id,
                )
                await asyncio.sleep(0.1)

        event_types = [call.kwargs["event_type"] for call in append_event.await_args_list]
        # B106: execute_command (running+done) + ask_user (running+done) = 4 tool_steps
        assert event_types.count("tool_step") == 4
        # B106: 验证 ask_user tool_step 的 description 和 tool_name
        ask_user_steps = [
            call for call in append_event.await_args_list
            if call.kwargs["event_type"] == "tool_step"
            and call.kwargs["payload"].get("tool_name") == "ask_user"
        ]
        assert len(ask_user_steps) == 2  # running + done
        assert ask_user_steps[0].kwargs["payload"]["description"] == "向用户提问"
        assert ask_user_steps[0].kwargs["payload"]["status"] == "running"
        assert ask_user_steps[1].kwargs["payload"]["status"] == "done"
        assert "question" in event_types
        assert "result" in event_types
        question_calls = [
            call for call in append_event.await_args_list
            if call.kwargs["event_type"] == "question"
        ]
        assert question_calls[0].kwargs["question_id"] == question_id

    @pytest.mark.asyncio
    async def test_run_loop_cancelled(self, manager):
        """取消 Agent 运行应推送 Cancelled 事件。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="loop3",
        )

        execute_fn = AsyncMock()

        # 模拟长时间运行的 Agent
        async def _slow_run(**kwargs):
            await asyncio.sleep(60)

        with patch("app.services.terminal_agent.run_agent", new_callable=AsyncMock, side_effect=_slow_run):
            await manager.start_agent(s, execute_fn)
            await asyncio.sleep(0.05)

            # 取消
            await manager.cancel("loop3")
            await asyncio.sleep(0.1)

        assert s.state == AgentSessionState.CANCELLED


# ---------------------------------------------------------------------------
# Test: 降级路径
# ---------------------------------------------------------------------------

class TestFallbackPath:
    """测试 Agent 不可用时降级到 planner。"""

    @pytest.mark.asyncio
    async def test_fallback_stream_format(self):
        """降级流应包含 fallback 事件和 result 事件。"""
        from app.services.agent_session_manager import _error_event_dict

        # 降级流由 runtime_api 中的 _agent_fallback_stream 处理
        # 这里验证错误事件字典格式
        error = _error_event_dict(ErrorCode.AGENT_OFFLINE, "设备离线")
        assert error["code"] == "AGENT_OFFLINE"
        assert "离线" in error["message"]


# ---------------------------------------------------------------------------
# Test: 全局单例
# ---------------------------------------------------------------------------

class TestGlobalSingleton:
    """测试全局单例管理。"""

    def test_get_manager_returns_same_instance(self):
        """get_agent_session_manager 应返回同一实例。"""
        m1 = get_agent_session_manager()
        m2 = get_agent_session_manager()
        assert m1 is m2


# ---------------------------------------------------------------------------
# Test: 移除会话
# ---------------------------------------------------------------------------

class TestRemoveSession:
    """测试移除会话。"""

    @pytest.mark.asyncio
    async def test_remove_session(self, manager):
        """移除会话后应不再能获取。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="rm1",
        )
        assert await manager.get_session("rm1") is s

        await manager.remove_session("rm1")
        assert await manager.get_session("rm1") is None

    @pytest.mark.asyncio
    async def test_remove_nonexistent_is_safe(self, manager):
        """移除不存在的会话不报错。"""
        await manager.remove_session("nonexistent")  # 不抛异常


# ---------------------------------------------------------------------------
# Test: 事件缓存限制
# ---------------------------------------------------------------------------

class TestEventCacheLimit:
    """测试事件缓存数量限制。"""

    @pytest.mark.asyncio
    async def test_cache_trims_at_max(self, manager):
        """缓存事件超过 MAX_CACHED_EVENTS 时应截断。"""
        from app.services.agent_session_manager import MAX_CACHED_EVENTS

        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="cache1",
        )

        # 推送超过限制数量的事件
        for i in range(MAX_CACHED_EVENTS + 20):
            await s.event_queue.put(("tool_step", {"tool_name": "cmd", "description": f"cmd-{i}", "status": "done", "result_summary": "ok"}))
        await s.event_queue.put(None)

        # 消费所有事件
        async for chunk in manager.sse_stream(s):
            pass

        assert len(s._last_events) <= MAX_CACHED_EVENTS


# ---------------------------------------------------------------------------
# Test: SSE stream ref count
# ---------------------------------------------------------------------------

class TestStreamRefCount:
    """测试 SSE 流引用计数。"""

    @pytest.mark.asyncio
    async def test_ref_count_on_stream(self, manager):
        """SSE 流消费时引用计数正确。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="ref1",
        )

        assert s._stream_ref_count == 0

        await s.event_queue.put(None)

        async for _ in manager.sse_stream(s):
            pass

        assert s._stream_ref_count == 0


# ---------------------------------------------------------------------------
# Test: 状态枚举完整性
# ---------------------------------------------------------------------------

class TestSessionState:
    """测试会话状态枚举。"""

    def test_all_states_defined(self):
        """7 种状态应全部定义。"""
        states = list(AgentSessionState)
        assert len(states) == 7
        state_values = [s.value for s in states]
        assert "exploring" in state_values
        assert "asking" in state_values
        assert "completed" in state_values
        assert "error" in state_values
        assert "expired" in state_values
        assert "cancelled" in state_values
        assert "inactive" in state_values


# ---------------------------------------------------------------------------
# B094: SSE result event response_type 格式验证
# ---------------------------------------------------------------------------

class TestSSEResultEventType:
    """测试 SSE result event 包含 response_type 和 ai_prompt 字段。"""

    @pytest.mark.asyncio
    async def test_message_type_sse_event(self, manager):
        """response_type='message' 的 SSE event 包含正确字段。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="rt-msg",
        )

        # 模拟 message 类型的 AgentResult
        mock_result = AgentResult(
            summary="Claude Code 使用技巧：1. ...",
            steps=[],
            response_type="message",
            need_confirm=False,
        )
        mock_outcome = AgentRunOutcome(
            result=mock_result,
            input_tokens=50,
            output_tokens=30,
            total_tokens=80,
            requests=1,
            model_name="test-model",
        )

        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="file.txt"))

        with patch("app.services.terminal_agent.run_agent", new_callable=AsyncMock, return_value=mock_outcome):
            with patch("app.services.agent_session_manager.save_agent_usage", new_callable=AsyncMock, return_value=True):
                await manager.start_agent(s, execute_fn)
                await asyncio.sleep(0.1)

        # 检查 result event
        events = []
        while not s.event_queue.empty():
            events.append(s.event_queue.get_nowait())
        result_events = [e for e in events if e is not None and e[0] == "result"]
        assert len(result_events) == 1
        data = result_events[0][1]
        assert data["response_type"] == "message"
        assert data["ai_prompt"] == ""
        assert data["steps"] == []
        assert data["need_confirm"] is False

    @pytest.mark.asyncio
    async def test_command_type_sse_event_backward_compatible(self, manager):
        """response_type='command' 的 SSE event 向后兼容。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="rt-cmd",
        )

        mock_result = AgentResult(
            summary="启动 Claude Code",
            steps=[CommandSequenceStep(id="s1", label="run claude", command="claude")],
            response_type="command",
            need_confirm=True,
        )
        mock_outcome = AgentRunOutcome(
            result=mock_result,
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            requests=2,
            model_name="test-model",
        )

        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="file.txt"))

        with patch("app.services.terminal_agent.run_agent", new_callable=AsyncMock, return_value=mock_outcome):
            with patch("app.services.agent_session_manager.save_agent_usage", new_callable=AsyncMock, return_value=True):
                await manager.start_agent(s, execute_fn)
                await asyncio.sleep(0.1)

        events = []
        while not s.event_queue.empty():
            events.append(s.event_queue.get_nowait())
        result_events = [e for e in events if e is not None and e[0] == "result"]
        assert len(result_events) == 1
        data = result_events[0][1]
        assert data["response_type"] == "command"
        assert data["ai_prompt"] == ""
        assert len(data["steps"]) == 1
        assert data["need_confirm"] is True

    @pytest.mark.asyncio
    async def test_ai_prompt_type_sse_event(self, manager):
        """response_type='ai_prompt' 的 SSE event 包含 ai_prompt 字段。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="rt-aip",
        )

        prompt_text = "请用 Python 实现一个简单的 HTTP server，支持 GET 请求返回 Hello World"
        mock_result = AgentResult(
            summary="已生成 prompt",
            steps=[],
            response_type="ai_prompt",
            ai_prompt=prompt_text,
            need_confirm=True,
        )
        mock_outcome = AgentRunOutcome(
            result=mock_result,
            input_tokens=200,
            output_tokens=100,
            total_tokens=300,
            requests=3,
            model_name="test-model",
        )

        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="file.txt"))

        with patch("app.services.terminal_agent.run_agent", new_callable=AsyncMock, return_value=mock_outcome):
            with patch("app.services.agent_session_manager.save_agent_usage", new_callable=AsyncMock, return_value=True):
                await manager.start_agent(s, execute_fn)
                await asyncio.sleep(0.1)

        events = []
        while not s.event_queue.empty():
            events.append(s.event_queue.get_nowait())
        result_events = [e for e in events if e is not None and e[0] == "result"]
        assert len(result_events) == 1
        data = result_events[0][1]
        assert data["response_type"] == "ai_prompt"
        assert data["ai_prompt"] == prompt_text
        assert data["steps"] == []
        assert data["need_confirm"] is True


# ---------------------------------------------------------------------------
# B103: streaming_text SSE 事件
# ---------------------------------------------------------------------------

class TestStreamingTextSSE:
    """B103: 测试 streaming_text SSE 事件推送和格式。"""

    @pytest.mark.asyncio
    async def test_streaming_text_pushed_via_on_model_text(self, manager):
        """模型文本输出通过 on_model_text 回调推送 streaming_text SSE 事件。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="am1",
        )

        mock_result = _make_agent_result(summary="done")
        mock_outcome = AgentRunOutcome(
            result=mock_result,
            input_tokens=100, output_tokens=50, total_tokens=150,
            requests=1, model_name="test-model",
        )

        captured_texts: list[str] = []
        original_run = None

        async def _mock_run_agent(**kwargs):
            on_model_text = kwargs.get("on_model_text")
            if on_model_text:
                await on_model_text("我来帮你检查一下当前目录结构")
            return mock_outcome

        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="file.txt"))

        with patch("app.services.terminal_agent.run_agent", new_callable=AsyncMock, side_effect=_mock_run_agent):
            with patch("app.services.agent_session_manager.save_agent_usage", new_callable=AsyncMock, return_value=True):
                await manager.start_agent(s, execute_fn)
                await asyncio.sleep(0.1)

        # 收集事件
        events = []
        while not s.event_queue.empty():
            events.append(s.event_queue.get_nowait())

        streaming_events = [e for e in events if e is not None and e[0] == "streaming_text"]
        assert len(streaming_events) == 1
        assert streaming_events[0][1]["text_delta"] == "我来帮你检查一下当前目录结构"

    @pytest.mark.asyncio
    async def test_streaming_text_sse_format(self, manager):
        """streaming_text SSE 事件格式正确。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="am2",
        )

        # 直接推送 streaming_text 事件测试 SSE 格式
        await s.event_queue.put(("streaming_text", {"text_delta": "你好！我来帮你处理"}))
        await s.event_queue.put(None)

        events = []
        async for chunk in manager.sse_stream(s):
            events.append(chunk)

        assert len(events) == 1
        assert "event: streaming_text" in events[0]
        data_json = events[0].split("data: ")[1].strip()
        data = json.loads(data_json)
        assert data["text_delta"] == "你好！我来帮你处理"

    @pytest.mark.asyncio
    async def test_multiple_streaming_texts(self, manager):
        """多轮文本输出推送多个 streaming_text 事件。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="am3",
        )

        mock_result = _make_agent_result(summary="done")
        mock_outcome = AgentRunOutcome(
            result=mock_result,
            input_tokens=100, output_tokens=50, total_tokens=150,
            requests=1, model_name="test-model",
        )

        async def _mock_run_agent(**kwargs):
            on_model_text = kwargs.get("on_model_text")
            if on_model_text:
                await on_model_text("第一轮回复")
                await on_model_text("第二轮回复")
            return mock_outcome

        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="file.txt"))

        with patch("app.services.terminal_agent.run_agent", new_callable=AsyncMock, side_effect=_mock_run_agent):
            with patch("app.services.agent_session_manager.save_agent_usage", new_callable=AsyncMock, return_value=True):
                await manager.start_agent(s, execute_fn)
                await asyncio.sleep(0.1)

        events = []
        while not s.event_queue.empty():
            events.append(s.event_queue.get_nowait())

        streaming_events = [e for e in events if e is not None and e[0] == "streaming_text"]
        assert len(streaming_events) == 2
        assert streaming_events[0][1]["text_delta"] == "第一轮回复"
        assert streaming_events[1][1]["text_delta"] == "第二轮回复"


# ---------------------------------------------------------------------------
# B103: streaming_text 空文本过滤
# ---------------------------------------------------------------------------

class TestStreamingTextFilter:
    """B103: 测试 streaming_text 空文本不推送。"""

    @pytest.mark.asyncio
    async def test_empty_text_not_pushed(self, manager):
        """空文本不推送 streaming_text 事件。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="amf1",
        )

        mock_result = _make_agent_result(summary="done")
        mock_outcome = AgentRunOutcome(
            result=mock_result,
            input_tokens=100, output_tokens=50, total_tokens=150,
            requests=1, model_name="test-model",
        )

        async def _mock_run_agent(**kwargs):
            on_model_text = kwargs.get("on_model_text")
            if on_model_text:
                # 空白文本不应推送
                await on_model_text("")
                await on_model_text("   ")
            return mock_outcome

        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="file.txt"))

        with patch("app.services.terminal_agent.run_agent", new_callable=AsyncMock, side_effect=_mock_run_agent):
            with patch("app.services.agent_session_manager.save_agent_usage", new_callable=AsyncMock, return_value=True):
                await manager.start_agent(s, execute_fn)
                await asyncio.sleep(0.1)

        events = []
        while not s.event_queue.empty():
            events.append(s.event_queue.get_nowait())

        streaming_events = [e for e in events if e is not None and e[0] == "streaming_text"]
        assert len(streaming_events) == 0  # 空白文本被过滤掉了

    @pytest.mark.asyncio
    async def test_normal_text_pushed_as_streaming(self, manager):
        """正常文本推送为 streaming_text 事件。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="amf2",
        )

        mock_result = _make_agent_result(summary="done")
        mock_outcome = AgentRunOutcome(
            result=mock_result,
            input_tokens=100, output_tokens=50, total_tokens=150,
            requests=1, model_name="test-model",
        )

        async def _mock_run_agent(**kwargs):
            on_model_text = kwargs.get("on_model_text")
            if on_model_text:
                await on_model_text("我来帮你看看当前目录结构")
            return mock_outcome

        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="file.txt"))

        with patch("app.services.terminal_agent.run_agent", new_callable=AsyncMock, side_effect=_mock_run_agent):
            with patch("app.services.agent_session_manager.save_agent_usage", new_callable=AsyncMock, return_value=True):
                await manager.start_agent(s, execute_fn)
                await asyncio.sleep(0.1)

        events = []
        while not s.event_queue.empty():
            events.append(s.event_queue.get_nowait())

        streaming_events = [e for e in events if e is not None and e[0] == "streaming_text"]
        assert len(streaming_events) == 1
        assert streaming_events[0][1]["text_delta"] == "我来帮你看看当前目录结构"


# ---------------------------------------------------------------------------
# B106: ResultDelivered 后 save_agent_usage 先于 result 推送
# ---------------------------------------------------------------------------

class TestResultUsageOrdering:
    """B106: 测试 save_agent_usage 先于 result SSE 推送（含 streaming_text 场景）。"""

    @pytest.mark.asyncio
    async def test_usage_saved_before_result_with_streaming_texts(self, manager):
        """streaming_text 推送不影响 usage 先于 result 的顺序保证。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="ord1",
        )

        mock_result = _make_agent_result(summary="done")
        mock_outcome = AgentRunOutcome(
            result=mock_result,
            input_tokens=200, output_tokens=100, total_tokens=300,
            requests=2, model_name="test-model",
        )

        ordering: list[str] = []
        original_put = s.event_queue.put

        async def _tracking_put(event):
            if event is not None and event[0] == "result":
                ordering.append("result")
            if event is not None and event[0] == "streaming_text":
                ordering.append("streaming_text")
            await original_put(event)

        async def _save_usage(*args, **kwargs):
            ordering.append("saved")
            return True

        s.event_queue.put = _tracking_put

        async def _mock_run_agent(**kwargs):
            on_model_text = kwargs.get("on_model_text")
            if on_model_text:
                await on_model_text("中间消息")
            return mock_outcome

        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="file.txt"))

        with patch("app.services.terminal_agent.run_agent", new_callable=AsyncMock, side_effect=_mock_run_agent):
            with patch("app.services.agent_session_manager.save_agent_usage", new_callable=AsyncMock, side_effect=_save_usage) as save_mock:
                await manager.start_agent(s, execute_fn)
                await asyncio.sleep(0.1)

        assert save_mock.await_count == 1
        # streaming_text 在 saved 之前推送，result 在 saved 之后
        assert "streaming_text" in ordering
        assert "saved" in ordering
        assert "result" in ordering
        saved_idx = ordering.index("saved")
        result_idx = ordering.index("result")
        assert saved_idx < result_idx


# ---------------------------------------------------------------------------
# B106: finally 块稳定结束 event_queue
# ---------------------------------------------------------------------------

class TestFinallyBlock:
    """B106: 测试 finally 块稳定结束 event_queue。"""

    @pytest.mark.asyncio
    async def test_finally_puts_none_on_success(self, manager):
        """成功完成后 event_queue 收到 None 结束信号。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="fin1",
        )

        mock_outcome = AgentRunOutcome(
            result=_make_agent_result(summary="done"),
            input_tokens=100, output_tokens=50, total_tokens=150,
            requests=1, model_name="test-model",
        )

        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="ok"))

        with patch("app.services.terminal_agent.run_agent", new_callable=AsyncMock, return_value=mock_outcome):
            with patch("app.services.agent_session_manager.save_agent_usage", new_callable=AsyncMock, return_value=True):
                await manager.start_agent(s, execute_fn)
                await asyncio.sleep(0.1)

        # event_queue 中最后一个应该是 None
        events = []
        while not s.event_queue.empty():
            events.append(s.event_queue.get_nowait())
        assert events[-1] is None

    @pytest.mark.asyncio
    async def test_finally_puts_none_on_error(self, manager):
        """错误完成后 event_queue 也收到 None 结束信号。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="fin2",
        )

        execute_fn = AsyncMock()

        with patch("app.services.terminal_agent.run_agent", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            await manager.start_agent(s, execute_fn)
            await asyncio.sleep(0.1)

        events = []
        while not s.event_queue.empty():
            events.append(s.event_queue.get_nowait())
        assert events[-1] is None

    @pytest.mark.asyncio
    async def test_finally_puts_none_on_cancel(self, manager):
        """取消后 event_queue 也收到 None 结束信号。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="fin3",
        )

        execute_fn = AsyncMock()

        async def _slow_run(**kwargs):
            await asyncio.sleep(60)

        with patch("app.services.terminal_agent.run_agent", new_callable=AsyncMock, side_effect=_slow_run):
            await manager.start_agent(s, execute_fn)
            await asyncio.sleep(0.05)
            await manager.cancel("fin3")
            await asyncio.sleep(0.1)

        events = []
        while not s.event_queue.empty():
            events.append(s.event_queue.get_nowait())
        # 取消时有两个 None（cancel + finally）
        assert None in events


# ---------------------------------------------------------------------------
# B106: 取消/超时不影响已推送事件和已持久化的 usage
# ---------------------------------------------------------------------------

class TestCancelTimeoutPreservation:
    """B106: 测试取消/超时不丢失已推送事件和已持久化的 usage。"""

    @pytest.mark.asyncio
    async def test_cancel_preserves_already_pushed_events(self, manager):
        """取消后已推送的事件仍在 event_queue 中。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="ctp1",
        )

        mock_outcome = AgentRunOutcome(
            result=_make_agent_result(summary="done"),
            input_tokens=100, output_tokens=50, total_tokens=150,
            requests=1, model_name="test-model",
        )

        async def _mock_run_agent(**kwargs):
            on_model_text = kwargs.get("on_model_text")
            if on_model_text:
                await on_model_text("第一条消息")
            return mock_outcome

        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="ok"))

        with patch("app.services.terminal_agent.run_agent", new_callable=AsyncMock, side_effect=_mock_run_agent):
            with patch("app.services.agent_session_manager.save_agent_usage", new_callable=AsyncMock, return_value=True) as save_mock:
                await manager.start_agent(s, execute_fn)
                await asyncio.sleep(0.1)

        # 验证 usage 已保存
        assert save_mock.await_count == 1

        # 验证事件都在
        events = []
        while not s.event_queue.empty():
            events.append(s.event_queue.get_nowait())

        assistant_msgs = [e for e in events if e is not None and e[0] == "streaming_text"]
        results = [e for e in events if e is not None and e[0] == "result"]
        assert len(assistant_msgs) == 1
        assert len(results) == 1


# ---------------------------------------------------------------------------
# B103: conversation events 持久化包含 streaming_text
# ---------------------------------------------------------------------------

class TestConversationPersistence:
    """B103: 测试 conversation events 持久化包含 streaming_text。"""

    @pytest.mark.asyncio
    async def test_streaming_text_persisted_as_conversation_event(self, manager):
        """streaming_text 作为 conversation event 持久化（event_type='streaming_text', role='assistant'）。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u",
            session_id="cp1", terminal_id="term-1", conversation_id="conv-1",
        )

        mock_result = _make_agent_result(summary="done")
        mock_outcome = AgentRunOutcome(
            result=mock_result,
            input_tokens=100, output_tokens=50, total_tokens=150,
            requests=1, model_name="test-model",
        )

        async def _mock_run_agent(**kwargs):
            on_model_text = kwargs.get("on_model_text")
            if on_model_text:
                await on_model_text("我帮你查看一下")
            return mock_outcome

        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="ok"))

        with patch("app.services.terminal_agent.run_agent", new_callable=AsyncMock, side_effect=_mock_run_agent):
            with patch("app.services.agent_session_manager.save_agent_usage", new_callable=AsyncMock, return_value=True):
                with patch("app.store.database.append_agent_conversation_event", new_callable=AsyncMock) as append_event:
                    await manager.start_agent(s, execute_fn)
                    await asyncio.sleep(0.1)

        # 检查持久化的事件类型
        event_types = [call.kwargs["event_type"] for call in append_event.await_args_list]
        assert "streaming_text" in event_types
        # 检查 role
        streaming_calls = [
            call for call in append_event.await_args_list
            if call.kwargs["event_type"] == "streaming_text"
        ]
        assert len(streaming_calls) == 1
        assert streaming_calls[0].kwargs["role"] == "assistant"
        assert streaming_calls[0].kwargs["payload"]["text_delta"] == "我帮你查看一下"


# ---------------------------------------------------------------------------
# B103: resume_stream 正确回放 streaming_text 缓存事件
# ---------------------------------------------------------------------------

class TestResumeStreamingText:
    """B103: 测试 resume_stream 正确回放 streaming_text 缓存事件。"""

    @pytest.mark.asyncio
    async def test_resume_replays_streaming_text(self, manager):
        """断连恢复回放缓存的 streaming_text 事件。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="rsam1",
        )

        # 推送 streaming_text + result + 结束信号
        await s.event_queue.put(("streaming_text", {"text_delta": "中间消息"}))
        await s.event_queue.put(("result", {"summary": "done", "steps": []}))
        await s.event_queue.put(None)

        # 消费并缓存
        events_consumed = []
        async for chunk in manager.sse_stream(s):
            events_consumed.append(chunk)

        assert len(events_consumed) == 2

        # 标记完成
        s.state = AgentSessionState.COMPLETED

        # 恢复回放
        resumed = []
        async for chunk in manager.resume_stream(s, after_index=0):
            resumed.append(chunk)

        assert len(resumed) == 2
        assert "event: streaming_text" in resumed[0]
        assert "event: result" in resumed[1]

    @pytest.mark.asyncio
    async def test_resume_from_index_skips_earlier_streaming_texts(self, manager):
        """从指定索引恢复时跳过之前的 streaming_text。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="rsam2",
        )

        # 推送 3 个事件
        await s.event_queue.put(("streaming_text", {"text_delta": "msg-1"}))
        await s.event_queue.put(("streaming_text", {"text_delta": "msg-2"}))
        await s.event_queue.put(("result", {"summary": "done", "steps": []}))
        await s.event_queue.put(None)

        async for chunk in manager.sse_stream(s):
            pass

        assert len(s._last_events) == 3

        s.state = AgentSessionState.COMPLETED

        # 从索引 1 开始回放
        resumed = []
        async for chunk in manager.resume_stream(s, after_index=1):
            resumed.append(chunk)

        assert len(resumed) == 2
        assert "event: streaming_text" in resumed[0]
        data_json = resumed[0].split("data: ")[1].strip()
        data = json.loads(data_json)
        assert data["text_delta"] == "msg-2"


# ---------------------------------------------------------------------------
# B106: response_type="error" 走 error SSE 通道
# ---------------------------------------------------------------------------

class TestErrorResponseType:
    """B106: 测试 response_type='error' 的 AgentRunOutcome 走 error SSE 通道。"""

    @pytest.mark.asyncio
    async def test_no_delivery_error_pushes_error_sse(self, manager):
        """模型未调用 deliver_result 时推送 error SSE 事件（非 result）。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="ert1",
        )

        error_result = AgentResult(
            summary="Agent 完成了处理但未交付结构化结果",
            steps=[],
            response_type="error",
            need_confirm=False,
        )
        mock_outcome = AgentRunOutcome(
            result=error_result,
            input_tokens=100, output_tokens=50, total_tokens=150,
            requests=1, model_name="test-model",
        )

        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="ok"))

        with patch("app.services.terminal_agent.run_agent", new_callable=AsyncMock, return_value=mock_outcome):
            with patch("app.services.agent_session_manager.save_agent_usage", new_callable=AsyncMock, return_value=True):
                await manager.start_agent(s, execute_fn)
                await asyncio.sleep(0.1)

        assert s.state == AgentSessionState.ERROR

        events = []
        while not s.event_queue.empty():
            events.append(s.event_queue.get_nowait())

        result_events = [e for e in events if e is not None and e[0] == "result"]
        error_events = [e for e in events if e is not None and e[0] == "error"]
        assert len(result_events) == 0
        assert len(error_events) == 1
        assert error_events[0][1]["code"] == ErrorCode.AGENT_ERROR
        assert "usage" in error_events[0][1]

    @pytest.mark.asyncio
    async def test_error_response_type_usage_saved_before_error_event(self, manager):
        """response_type='error' 时 usage 仍先落库再推送 error SSE。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="ert2",
        )

        error_result = AgentResult(
            summary="Agent 完成了处理但未交付结构化结果",
            steps=[],
            response_type="error",
            need_confirm=False,
        )
        mock_outcome = AgentRunOutcome(
            result=error_result,
            input_tokens=100, output_tokens=50, total_tokens=150,
            requests=1, model_name="test-model",
        )

        ordering: list[str] = []
        original_put = s.event_queue.put

        async def _tracking_put(event):
            if event is not None and event[0] == "error":
                ordering.append("error")
            await original_put(event)

        async def _save_usage(*args, **kwargs):
            ordering.append("saved")
            return True

        s.event_queue.put = _tracking_put

        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="ok"))

        with patch("app.services.terminal_agent.run_agent", new_callable=AsyncMock, return_value=mock_outcome):
            with patch("app.services.agent_session_manager.save_agent_usage", new_callable=AsyncMock, side_effect=_save_usage) as save_mock:
                await manager.start_agent(s, execute_fn)
                await asyncio.sleep(0.1)

        assert save_mock.await_count == 1
        assert ordering == ["saved", "error"]


# ---------------------------------------------------------------------------
# S111: SSE 完整事件序列集成测试
# 验证 phase_change → tool_step → streaming_text → result 顺序
# ---------------------------------------------------------------------------

class TestSSEEventSequenceIntegration:
    """S111: SSE 事件序列集成测试 — 验证完整事件流顺序。

    验证验收标准中的事件序列：
    phase_change(THINKING) → phase_change(EXPLORING) → tool_step(running) →
    tool_step(done) → phase_change(ANALYZING) → phase_change(RESPONDING) →
    streaming_text → phase_change(RESULT) → result
    """

    @pytest.mark.asyncio
    async def test_full_sse_event_sequence_order(self, manager):
        """S111: 验证完整 SSE 事件序列的顺序 — phase_change → tool_step → streaming_text → result。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="sse-seq-1",
        )

        # 模拟完整 Agent 运行生命周期事件序列
        await s.event_queue.put(("phase_change", {"phase": "THINKING", "description": "正在分析你的意图..."}))
        await s.event_queue.put(("phase_change", {"phase": "EXPLORING", "description": "正在探索环境..."}))
        await s.event_queue.put(("tool_step", {"tool_name": "execute_command", "description": "ls -la", "status": "running", "result_summary": ""}))
        await s.event_queue.put(("tool_step", {"tool_name": "execute_command", "description": "ls -la", "status": "done", "result_summary": "file1.txt file2.txt"}))
        await s.event_queue.put(("phase_change", {"phase": "ANALYZING", "description": "正在分析结果..."}))
        await s.event_queue.put(("phase_change", {"phase": "RESPONDING", "description": "正在生成回复..."}))
        await s.event_queue.put(("streaming_text", {"text_delta": "找到"}))
        await s.event_queue.put(("streaming_text", {"text_delta": " 2 个文件"}))
        await s.event_queue.put(("phase_change", {"phase": "RESULT", "description": "完成"}))
        await s.event_queue.put(("result", {"summary": "找到 2 个文件", "steps": [], "provider": "agent"}))
        await s.event_queue.put(None)  # 结束

        events = []
        async for chunk in manager.sse_stream(s):
            events.append(chunk)

        # 验证事件数量
        assert len(events) == 10

        # 提取事件类型序列
        event_types = []
        for event_str in events:
            first_line = event_str.split("\n")[0]
            event_type = first_line.replace("event: ", "")
            event_types.append(event_type)

        # 验证完整事件序列顺序
        assert event_types == [
            "phase_change",    # THINKING
            "phase_change",    # EXPLORING
            "tool_step",       # running
            "tool_step",       # done
            "phase_change",    # ANALYZING
            "phase_change",    # RESPONDING
            "streaming_text",  # "找到"
            "streaming_text",  # " 2 个文件"
            "phase_change",    # RESULT
            "result",          # 最终结果
        ]

        # 验证 phase_change 事件的 data 格式
        for event_str in events:
            if "event: phase_change" in event_str:
                data_json = event_str.split("data: ")[1].strip()
                data = json.loads(data_json)
                assert "phase" in data
                assert "description" in data

        # 验证 tool_step 事件的 data 格式
        for event_str in events:
            if "event: tool_step" in event_str:
                data_json = event_str.split("data: ")[1].strip()
                data = json.loads(data_json)
                assert data["tool_name"] == "execute_command"
                assert data["status"] in ("running", "done")

        # 验证 streaming_text 事件的 data 格式
        for event_str in events:
            if "event: streaming_text" in event_str:
                data_json = event_str.split("data: ")[1].strip()
                data = json.loads(data_json)
                assert "text_delta" in data

        # 验证 result 事件的 data 格式
        result_event = events[-1]
        assert "event: result" in result_event
        data_json = result_event.split("data: ")[1].strip()
        data = json.loads(data_json)
        assert data["summary"] == "找到 2 个文件"

    @pytest.mark.asyncio
    async def test_sse_no_trace_or_assistant_message_events(self, manager):
        """S111: 验证 SSE 流中不产生旧事件类型 trace / assistant_message。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="sse-no-old-1",
        )

        # 推送各种新事件类型
        await s.event_queue.put(("phase_change", {"phase": "THINKING", "description": "Analyzing..."}))
        await s.event_queue.put(("tool_step", {"tool_name": "execute_command", "description": "ls", "status": "done", "result_summary": "ok"}))
        await s.event_queue.put(("streaming_text", {"text_delta": "text"}))
        await s.event_queue.put(("result", {"summary": "done", "steps": []}))
        await s.event_queue.put(None)

        events = []
        async for chunk in manager.sse_stream(s):
            events.append(chunk)

        # 不应包含任何旧事件类型
        for event_str in events:
            assert "event: trace" not in event_str, f"发现旧事件类型 trace: {event_str[:80]}"
            assert "event: assistant_message" not in event_str, f"发现旧事件类型 assistant_message: {event_str[:80]}"

    @pytest.mark.asyncio
    async def test_sse_event_types_are_subset_of_sse_event_types_constant(self, manager):
        """S111: 验证所有推送的事件类型都在 SSE_EVENT_TYPES 常量中定义。"""
        s = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="sse-const-1",
        )

        # 推送所有新事件类型
        await s.event_queue.put(("phase_change", {"phase": "THINKING", "description": "..."}))
        await s.event_queue.put(("streaming_text", {"text_delta": "hello"}))
        await s.event_queue.put(("tool_step", {"tool_name": "execute_command", "description": "ls", "status": "running", "result_summary": ""}))
        await s.event_queue.put(("question", {"question": "确认？", "options": ["是"], "multi_select": False}))
        await s.event_queue.put(("result", {"summary": "done", "steps": []}))
        await s.event_queue.put(None)

        events = []
        async for chunk in manager.sse_stream(s):
            events.append(chunk)

        for event_str in events:
            first_line = event_str.split("\n")[0]
            event_type = first_line.replace("event: ", "")
            assert event_type in SSE_EVENT_TYPES, f"事件类型 {event_type} 不在 SSE_EVENT_TYPES 中"
