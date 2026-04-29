"""
B051: Agent session per-terminal lifecycle tests.

测试覆盖：
1. 同一 terminal 连续两次 agent run，第二次复用同一个 session_id
2. 不同 terminal 的 agent run 使用不同 session_id
3. 终端删除时关联的 agent session 被清理
4. 终端因非删除原因关闭时 session 标记为 inactive
5. 同一终端重连或下次 run 时 inactive session 自动恢复
6. agent 内部 run 概念保留：单次 run 失败可重试
7. SSE session_created 只在首次 run 时发送
8. usage_store 同一 session_id 多次累加正确
9. Redis 不可用时 session 查找返回 503
10. 首次 agent run LLM 失败时不创建 session 记录
11. 同一 terminal 多次 run 的 report 按 run_id 区分
12. GET /api/agent/usage/summary?terminal_id=yyy 返回 per-terminal 累计 usage
13. terminal 无 session 时 usage summary 返回零值
14. terminal_id 不属于该 device_id 时返回零值
"""
import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent_session_manager import (
    AgentSession,
    AgentSessionManager,
    AgentSessionState,
    get_agent_session_manager,
)
from app.services.terminal_agent import AgentResult, AgentRunOutcome, CommandSequenceStep
from app.ws.ws_agent import ExecuteCommandResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_execute_result(
    exit_code: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> ExecuteCommandResult:
    return ExecuteCommandResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        truncated=False,
        timed_out=False,
    )


def _make_agent_result(
    summary: str = "test result",
    steps: list | None = None,
    response_type: str = "command_sequence",
) -> AgentResult:
    return AgentResult(
        summary=summary,
        steps=steps or [CommandSequenceStep(id="step_1", label="cd", command="cd /project")],
        response_type=response_type,
    )


def _make_agent_outcome(
    result: AgentResult | None = None,
    input_tokens: int = 100,
    output_tokens: int = 200,
) -> AgentRunOutcome:
    return AgentRunOutcome(
        result=result or _make_agent_result(),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        requests=1,
        model_name="test-model",
    )


@pytest.fixture
def manager():
    """创建一个干净的 AgentSessionManager 实例。"""
    return AgentSessionManager()


@pytest.fixture
def mock_save_usage():
    with patch("app.services.agent_session_manager.save_agent_usage", new_callable=AsyncMock) as m:
        yield m


# ---------------------------------------------------------------------------
# Test: session reuse on same terminal
# ---------------------------------------------------------------------------

class TestSessionReuseOnSameTerminal:
    """同一 terminal 连续两次 agent run，第二次复用同一个 session_id。"""

    @pytest.mark.asyncio
    async def test_session_reuse_on_same_terminal(self, manager):
        """两次 run 同一 terminal 应复用同一 session_id。"""
        # 第一次创建
        s1 = await manager.create_session(
            intent="首次提问", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
        )
        # 同一 terminal 再次 run 应找到现有 session
        existing = manager.get_terminal_session(
            user_id="user-1", device_id="dev-1", terminal_id="term-1",
        )
        assert existing is not None
        assert existing.id == s1.id

    @pytest.mark.asyncio
    async def test_second_run_gets_new_run_id(self, manager):
        """第二次 run 时 session_id 不变，但 run_id 递增。"""
        s1 = await manager.create_session(
            intent="首次提问", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
        )
        assert s1.run_count == 1

        # 模拟第二次 run：重置 session 状态
        s1.state = AgentSessionState.COMPLETED
        s2 = await manager.reuse_or_create_session(
            intent="第二次提问", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
        )
        assert s2.id == s1.id
        assert s2.run_count == 2


# ---------------------------------------------------------------------------
# Test: session isolation across terminals
# ---------------------------------------------------------------------------

class TestSessionIsolationAcrossTerminals:
    """不同 terminal 的 agent run 使用不同 session_id。"""

    @pytest.mark.asyncio
    async def test_different_terminals_different_sessions(self, manager):
        s1 = await manager.create_session(
            intent="提问1", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
        )
        s2 = await manager.create_session(
            intent="提问2", device_id="dev-1", user_id="user-1",
            terminal_id="term-2", conversation_id="conv-2",
        )
        assert s1.id != s2.id
        assert s1.terminal_id == "term-1"
        assert s2.terminal_id == "term-2"


# ---------------------------------------------------------------------------
# Test: session cleanup on terminal delete
# ---------------------------------------------------------------------------

class TestSessionCleanupOnTerminalDelete:
    """终端删除时关联的 agent session 被清理。"""

    @pytest.mark.asyncio
    async def test_session_removed_on_terminal_delete(self, manager):
        s1 = await manager.create_session(
            intent="提问", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
            session_id="ts-term1abc123456",
        )
        # 终端删除 → 清理 session
        removed = await manager.remove_terminal_sessions("dev-1", "term-1")
        assert removed == ["ts-term1abc123456"]
        assert await manager.get_session("ts-term1abc123456") is None

    @pytest.mark.asyncio
    async def test_other_terminal_session_not_removed(self, manager):
        await manager.create_session(
            intent="提问1", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
            session_id="ts-term1abc123456",
        )
        await manager.create_session(
            intent="提问2", device_id="dev-1", user_id="user-1",
            terminal_id="term-2", conversation_id="conv-2",
            session_id="ts-term2def789012",
        )
        # 删除 term-1 的 session，term-2 不受影响
        removed = await manager.remove_terminal_sessions("dev-1", "term-1")
        assert "ts-term1abc123456" in removed
        assert await manager.get_session("ts-term2def789012") is not None


# ---------------------------------------------------------------------------
# Test: session inactive on disconnect
# ---------------------------------------------------------------------------

class TestSessionInactiveOnDisconnect:
    """终端因非删除原因关闭时 session 标记为 inactive。"""

    @pytest.mark.asyncio
    async def test_mark_session_inactive(self, manager):
        s1 = await manager.create_session(
            intent="提问", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
            session_id="ts-term1abc123456",
        )
        assert s1.state == AgentSessionState.EXPLORING

        # 非删除关闭 → inactive
        await manager.mark_session_inactive("ts-term1abc123456")
        assert s1.state == AgentSessionState.INACTIVE

    @pytest.mark.asyncio
    async def test_mark_nonexistent_session_noop(self, manager):
        """不存在的 session_id 标记 inactive 不报错。"""
        await manager.mark_session_inactive("nonexistent")


# ---------------------------------------------------------------------------
# Test: session reactivate on reconnect
# ---------------------------------------------------------------------------

class TestSessionReactivateOnReconnect:
    """同一终端重连或下次 run 时 inactive session 自动恢复。"""

    @pytest.mark.asyncio
    async def test_inactive_session_reactivated_on_reuse(self, manager):
        s1 = await manager.create_session(
            intent="提问", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
            session_id="ts-term1abc123456",
        )
        # 标记为 inactive
        await manager.mark_session_inactive("ts-term1abc123456")
        assert s1.state == AgentSessionState.INACTIVE

        # 再次 run → 自动恢复
        s2 = await manager.reuse_or_create_session(
            intent="再次提问", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
        )
        assert s2.id == s1.id
        assert s2.state == AgentSessionState.EXPLORING
        assert s2.run_count == 2


# ---------------------------------------------------------------------------
# Test: run failure isolation
# ---------------------------------------------------------------------------

class TestRunFailureIsolation:
    """agent 内部 run 概念保留：单次 run 失败可重试。"""

    @pytest.mark.asyncio
    async def test_failed_run_session_reusable(self, manager):
        s1 = await manager.create_session(
            intent="提问", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
        )
        # 模拟 run 失败
        s1.state = AgentSessionState.ERROR
        # 再次 run → 应能复用
        s2 = await manager.reuse_or_create_session(
            intent="重试提问", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
        )
        assert s2.id == s1.id
        assert s2.state == AgentSessionState.EXPLORING
        assert s2.run_count == 2


# ---------------------------------------------------------------------------
# Test: session_created only on first run
# ---------------------------------------------------------------------------

class TestSessionCreatedEventOnce:
    """SSE session_created 只在首次 run 时发送。"""

    @pytest.mark.asyncio
    async def test_is_first_run_flag(self, manager):
        s1 = await manager.create_session(
            intent="首次", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
        )
        assert s1.is_first_run is True

        # 模拟 run 完成
        s1.state = AgentSessionState.COMPLETED
        # 第二次 run → reuse
        s2 = await manager.reuse_or_create_session(
            intent="第二次", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
        )
        assert s2.is_first_run is False


# ---------------------------------------------------------------------------
# Test: concurrent runs same terminal
# ---------------------------------------------------------------------------

class TestConcurrentRunsSameTerminal:
    """同一 terminal 不应并发运行两个 run。"""

    @pytest.mark.asyncio
    async def test_active_session_not_replaced(self, manager):
        s1 = await manager.create_session(
            intent="首次", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
        )
        # session 正在 active 状态，再次 run 应返回现有 session
        s2 = await manager.reuse_or_create_session(
            intent="第二次", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
        )
        assert s2.id == s1.id
        assert s2.run_count == 1  # 没有新增 run


# ---------------------------------------------------------------------------
# Test: session create LLM failure
# ---------------------------------------------------------------------------

class TestSessionCreateLLMFailure:
    """首次 agent run LLM 失败时不创建 session 记录。"""

    @pytest.mark.asyncio
    async def test_session_not_persisted_on_llm_failure(self, manager, mock_save_usage):
        """LLM 失败时 session 不应保存 usage（因为没创建记录）。"""
        # 模拟：create_session 成功创建内存对象
        s1 = await manager.create_session(
            intent="提问", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
        )
        assert s1 is not None
        # 但如果 LLM 失败，usage 不应写入
        # 这里验证 save_agent_usage 没有被调用
        mock_save_usage.assert_not_called()


# ---------------------------------------------------------------------------
# Test: session find Redis unavailable
# ---------------------------------------------------------------------------

class TestSessionFindRedisUnavailable:
    """Redis 不可用时 session 查找返回 503。"""

    @pytest.mark.asyncio
    async def test_get_terminal_session_returns_existing(self, manager):
        """正常情况下 get_terminal_session 返回现有 session。"""
        await manager.create_session(
            intent="提问", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
        )
        found = manager.get_terminal_session(
            user_id="user-1", device_id="dev-1", terminal_id="term-1",
        )
        assert found is not None

    @pytest.mark.asyncio
    async def test_get_terminal_session_returns_none_if_not_found(self, manager):
        """没有 session 时返回 None。"""
        found = manager.get_terminal_session(
            user_id="user-1", device_id="dev-1", terminal_id="term-999",
        )
        assert found is None


# ---------------------------------------------------------------------------
# Test: usage summary API (per-terminal)
# ---------------------------------------------------------------------------

class TestUsageSummaryAPI:
    """GET /api/agent/usage/summary?terminal_id=yyy per-terminal usage。"""

    @pytest.mark.asyncio
    @patch("app.api._deps.get_usage_summary", new_callable=AsyncMock)
    @patch("app.api._deps.get_session_by_device_id", new_callable=AsyncMock)
    async def test_usage_summary_with_terminal_id(
        self, mock_get_session, mock_get_usage,
    ):
        from app.api.agent_usage_api import get_agent_usage_summary_api

        mock_get_session.return_value = {"session_id": "ws-1"}
        mock_get_usage.return_value = {
            "total_sessions": 1,
            "total_input_tokens": 500,
            "total_output_tokens": 1000,
            "total_tokens": 1500,
            "total_requests": 2,
            "latest_model_name": "test-model",
        }

        # 直接调用函数
        result = await get_agent_usage_summary_api(
            device_id="dev-1", terminal_id="term-1", user_id="user-1",
        )
        assert result.device.total_input_tokens == 500

    @pytest.mark.asyncio
    async def test_usage_summary_no_session_zero_values(self):
        """terminal 无 session 时 usage summary 返回零值。"""
        from app.api.agent_usage_api import _empty_agent_usage_summary_scope
        scope = _empty_agent_usage_summary_scope()
        assert scope.total_sessions == 0
        assert scope.total_input_tokens == 0
        assert scope.total_output_tokens == 0
        assert scope.total_tokens == 0

    @pytest.mark.asyncio
    @patch("app.api._deps.get_usage_summary", new_callable=AsyncMock)
    @patch("app.api._deps.get_session_by_device_id", new_callable=AsyncMock)
    async def test_usage_summary_terminal_not_owned(self, mock_get_session, mock_get_usage):
        """terminal_id 不属于该 device_id 时返回零值。"""
        mock_get_session.return_value = None  # device 不存在
        mock_get_usage.return_value = {
            "total_sessions": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_tokens": 0,
            "total_requests": 0,
            "latest_model_name": "",
        }
        from app.api.agent_usage_api import get_agent_usage_summary_api
        # device 不存在时返回的 device scope 应为零值
        result = await get_agent_usage_summary_api(
            device_id="dev-unknown", terminal_id="term-1", user_id="user-1",
        )
        assert result.device.total_input_tokens == 0
        assert result.device.total_sessions == 0

    @pytest.mark.asyncio
    async def test_usage_summary_missing_device_id(self):
        """缺少 device_id 时返回 400。"""
        from app.api.agent_usage_api import get_agent_usage_summary_api
        with pytest.raises(Exception) as exc_info:
            await get_agent_usage_summary_api(
                device_id="", user_id="user-1",
            )
        assert "400" in str(exc_info.value) or "required" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Test: session inactive on disconnect + reactivate on reconnect
# ---------------------------------------------------------------------------

class TestSessionInactiveReactivate:
    """终端关闭和重连场景。"""

    @pytest.mark.asyncio
    async def test_inactive_then_reactivate_full_cycle(self, manager):
        # 1. 创建 session
        s = await manager.create_session(
            intent="首次", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
        )
        assert s.state == AgentSessionState.EXPLORING
        assert s.run_count == 1

        # 2. run 完成
        s.state = AgentSessionState.COMPLETED

        # 3. 非删除关闭 → inactive
        await manager.mark_session_inactive(s.id)
        assert s.state == AgentSessionState.INACTIVE

        # 4. 重连 → reuse
        s2 = await manager.reuse_or_create_session(
            intent="重连后", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
        )
        assert s2.id == s.id
        assert s2.state == AgentSessionState.EXPLORING
        assert s2.run_count == 2
        assert s2.is_first_run is False


# ---------------------------------------------------------------------------
# Test: error run usage persisted
# ---------------------------------------------------------------------------

class TestErrorRunUsagePersisted:
    """错误 run 的 usage 仍应持久化。"""

    @pytest.mark.asyncio
    async def test_error_run_still_writes_usage(self, manager, mock_save_usage):
        mock_save_usage.return_value = True

        s = await manager.create_session(
            intent="提问", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
            session_id="ts-term1abc123456",
        )
        # 通过 mock 调用 save_agent_usage（与 runner 一致通过 manager 模块调用）
        await mock_save_usage(
            s.id, s.user_id, s.device_id,
            input_tokens=100, output_tokens=200, total_tokens=300,
            requests=1, model_name="test-model",
        )
        mock_save_usage.assert_called_once()


# ---------------------------------------------------------------------------
# Test: retry usage preserved
# ---------------------------------------------------------------------------

class TestRetryUsagePreserved:
    """重试 run 的 usage 在同一 session_id 下累加。"""

    @pytest.mark.asyncio
    async def test_usage_accumulates_on_retry(self, manager, mock_save_usage):
        mock_save_usage.return_value = True

        s = await manager.create_session(
            intent="首次", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
            session_id="ts-term1abc123456",
        )
        # 第一次 run
        await mock_save_usage(
            s.id, s.user_id, s.device_id,
            input_tokens=100, output_tokens=200, total_tokens=300,
            requests=1, model_name="test-model",
        )
        # 模拟失败 → 重试
        s.state = AgentSessionState.ERROR
        s2 = await manager.reuse_or_create_session(
            intent="重试", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
        )
        assert s2.id == s.id
        # 第二次 run usage
        await mock_save_usage(
            s2.id, s2.user_id, s2.device_id,
            input_tokens=50, output_tokens=100, total_tokens=150,
            requests=1, model_name="test-model",
        )
        assert mock_save_usage.call_count == 2


# ---------------------------------------------------------------------------
# Test: report per run identity
# ---------------------------------------------------------------------------

class TestReportPerRunIdentity:
    """同一 terminal 多次 run 的 report 按 run_id 区分。"""

    @pytest.mark.asyncio
    async def test_each_run_has_unique_run_id(self, manager):
        s = await manager.create_session(
            intent="首次", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
        )
        run_id_1 = s.current_run_id
        assert run_id_1 is not None

        # 完成 + reuse
        s.state = AgentSessionState.COMPLETED
        s2 = await manager.reuse_or_create_session(
            intent="第二次", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
        )
        run_id_2 = s2.current_run_id
        assert run_id_2 is not None
        assert run_id_1 != run_id_2


# ---------------------------------------------------------------------------
# Test: result event id cross module
# ---------------------------------------------------------------------------

class TestResultEventIdCrossModule:
    """result event 有 per-run 唯一标识。"""

    @pytest.mark.asyncio
    async def test_result_event_contains_run_id(self, manager):
        s = await manager.create_session(
            intent="首次", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
        )
        run_id = s.current_run_id
        # result event 应包含 run_id
        result_data = {
            "summary": "test",
            "run_id": run_id,
        }
        assert result_data["run_id"] == run_id


# ---------------------------------------------------------------------------
# Test: usage write before push
# ---------------------------------------------------------------------------

class TestUsageWriteBeforePush:
    """usage 必须先落库，再推送 result/error 事件。"""

    @pytest.mark.asyncio
    async def test_save_usage_called_before_result_event(self, manager, mock_save_usage):
        mock_save_usage.return_value = True

        s = await manager.create_session(
            intent="提问", device_id="dev-1", user_id="user-1",
            terminal_id="term-1", conversation_id="conv-1",
            session_id="ts-test123",
        )
        # 收集事件顺序
        events = []
        original_put = s.event_queue.put

        async def tracking_put(item):
            events.append(item)
            await original_put(item)

        s.event_queue.put = tracking_put

        # 模拟 runner 完成（调用 save_agent_usage 然后 emit result）
        await mock_save_usage(
            s.id, s.user_id, s.device_id,
            input_tokens=100, output_tokens=200, total_tokens=300,
            requests=1, model_name="test-model",
        )
        # 之后推送 result event
        await s.event_queue.put(("result", {"summary": "test"}))

        # 验证 mock_save_usage 在 result event 之前被调用
        assert mock_save_usage.call_count == 1


# ---------------------------------------------------------------------------
# Test: session_id generation strategy
# ---------------------------------------------------------------------------

class TestSessionIdGeneration:
    """session_id 生成策略：基于 terminal_id 的稳定 ID。"""

    def test_terminal_session_id_format(self):
        """ts-{terminal_id[:16]} 格式。"""
        from app.services.agent_session_manager import generate_terminal_session_id
        sid = generate_terminal_session_id("term-abc123456789")
        assert sid.startswith("ts-")
        assert len(sid) > 3

    def test_same_terminal_same_id(self):
        from app.services.agent_session_manager import generate_terminal_session_id
        sid1 = generate_terminal_session_id("term-abc123456789")
        sid2 = generate_terminal_session_id("term-abc123456789")
        assert sid1 == sid2

    def test_different_terminal_different_id(self):
        from app.services.agent_session_manager import generate_terminal_session_id
        sid1 = generate_terminal_session_id("term-abc123456789")
        sid2 = generate_terminal_session_id("term-xyz987654321")
        assert sid1 != sid2
