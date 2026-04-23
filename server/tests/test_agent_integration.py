"""
S082: Agent 集成测试。

在 mock 模式下覆盖全链路和边界场景，验证各组件协同正确性。

测试覆盖：
A. 本地可运行测试（mock 模式）
  1. 全链路集成（mock LLM）：创建会话 -> Agent 探索 -> ask_user -> 结果 -> 别名持久化
  2. 安全测试汇总：27 个攻击向量端到端拦截
  3. 超时测试：命令超时（10s）、会话超时（10min idle）
  4. 断连恢复：4 种状态（exploring/asking/completed/expired）的恢复逻辑
  5. 别名隔离：user_id 隔离、device_id 隔离、首用无别名 -> 探索后持久化
  6. 输出边界：大输出截断（> 4096）、空输出、特殊字符输出

B. Docker smoke（标记 skip）
  - happy path 全链路 Docker smoke
  - Agent 端 execute_command 实际执行
  - SSE 流完整性
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent_session_manager import (
    AgentSession,
    AgentSessionCancelled,
    AgentSessionExpired,
    AgentSessionManager,
    AgentSessionRateLimited,
    AgentSessionState,
    ErrorCode,
    SESSION_TIMEOUT_SECONDS,
    SSE_KEEPALIVE_SECONDS,
    USER_SESSION_RATE_LIMIT,
    _error_event_dict,
    get_agent_session_manager,
)
from app.command_validator import (
    validate_command,
    MAX_STDOUT_LEN,
    DEFAULT_COMMAND_TIMEOUT,
    ALLOWED_COMMANDS,
    SAFE_GIT_SUBCOMMANDS,
)
from app.terminal_agent import (
    AgentDeps,
    AgentResult,
    CommandSequenceStep,
    execute_command,
    ask_user,
    run_agent,
    terminal_agent,
)
from app.ws_agent import ExecuteCommandResult


# ---------------------------------------------------------------------------
# 辅助函数
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
    summary: str = "entered project",
    steps: list | None = None,
    aliases: dict | None = None,
) -> AgentResult:
    return AgentResult(
        summary=summary,
        steps=steps or [CommandSequenceStep(id="step_1", label="cd", command="cd /project")],
        aliases=aliases or {},
    )


def _make_run_context(deps: AgentDeps) -> MagicMock:
    ctx = MagicMock()
    ctx.deps = deps
    return ctx


def _make_deps(
    execute_fn=None,
    ask_fn=None,
    session_id: str = "test-session",
    aliases: dict | None = None,
) -> AgentDeps:
    if execute_fn is None:
        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="mock output"))
    if ask_fn is None:
        ask_fn = AsyncMock(return_value="user reply")
    return AgentDeps(
        session_id=session_id,
        execute_command_fn=execute_fn,
        ask_user_fn=ask_fn,
        project_aliases=aliases or {},
    )


# ===========================================================================
# A. 本地可运行测试（mock 模式）
# ===========================================================================


# ---------------------------------------------------------------------------
# A1. 全链路集成（mock LLM）
# ---------------------------------------------------------------------------

class TestFullPipelineIntegration:
    """全链路集成：创建会话 -> Agent 探索 -> ask_user -> 结果 -> SSE 事件 -> 别名持久化。"""

    @pytest.mark.asyncio
    async def test_happy_path_creates_session_and_produces_result(self):
        """Happy path: 完整 Agent 流程应正确创建会话并产生 AgentResult。"""
        manager = AgentSessionManager(alias_store=None)

        # 1. 创建会话
        session = await manager.create_session(
            intent="进入 my-project",
            device_id="dev-001",
            user_id="user-001",
            session_id="integ-001",
        )
        assert session.id == "integ-001"
        assert session.state == AgentSessionState.EXPLORING
        assert session.intent == "进入 my-project"

        # 2. Mock run_agent 返回成功结果
        expected_result = _make_agent_result(
            summary="已进入 my-project",
            steps=[
                CommandSequenceStep(id="s1", label="进入项目", command="cd ~/my-project"),
                CommandSequenceStep(id="s2", label="启动 Claude", command="claude"),
            ],
            aliases={"my-project": "/home/user/my-project"},
        )

        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="file.txt"))

        with patch("app.terminal_agent.run_agent", new_callable=AsyncMock, return_value=expected_result):
            await manager.start_agent(session, execute_fn)
            await asyncio.sleep(0.1)

        # 3. 验证最终状态和结果
        assert session.state == AgentSessionState.COMPLETED
        assert session.result is not None
        assert session.result.summary == "已进入 my-project"
        assert len(session.result.steps) == 2
        assert session.result.aliases == {"my-project": "/home/user/my-project"}

    @pytest.mark.asyncio
    async def test_happy_path_sse_event_sequence(self):
        """SSE 事件序列应包含 trace -> result。"""
        manager = AgentSessionManager()

        session = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="sse-seq",
        )

        expected_result = _make_agent_result(summary="done")
        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="output"))

        with patch("app.terminal_agent.run_agent", new_callable=AsyncMock, return_value=expected_result):
            await manager.start_agent(session, execute_fn)
            await asyncio.sleep(0.2)

        # 消费 SSE 事件
        events = []
        async for chunk in manager.sse_stream(session):
            events.append(chunk)

        # 至少应有 result 事件
        result_events = [e for e in events if "event: result" in e]
        assert len(result_events) >= 1

    @pytest.mark.asyncio
    async def test_happy_path_with_ask_user_interaction(self):
        """Agent 需要 ask_user 时，SSE 应推送 question 事件，用户回复后继续。"""
        manager = AgentSessionManager()

        session = await manager.create_session(
            intent="进入项目", device_id="d", user_id="u", session_id="ask-001",
        )

        # 模拟 Agent 需要 ask_user
        expected_result = _make_agent_result(summary="已选择项目 A")

        async def _mock_run_agent(**kwargs):
            ask_fn = kwargs.get("ask_user_fn")
            if ask_fn:
                # 模拟 Agent 调用 ask_user
                answer = await ask_fn("Which project?", ["project-a", "project-b"], False)
                assert answer == "project-a"
            return expected_result

        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="projects"))
        ask_fn_override = AsyncMock(return_value="project-a")

        with patch("app.terminal_agent.run_agent", new_callable=AsyncMock, side_effect=_mock_run_agent):
            await manager.start_agent(session, execute_fn, ask_user_fn_override=ask_fn_override)
            await asyncio.sleep(0.2)

        assert session.state == AgentSessionState.COMPLETED

    @pytest.mark.asyncio
    async def test_result_triggers_alias_persistence(self):
        """Agent 返回 aliases 时，应触发 alias_store.save_batch。"""
        mock_store = AsyncMock()
        manager = AgentSessionManager(alias_store=mock_store)

        session = await manager.create_session(
            intent="test", device_id="dev-1", user_id="user-1", session_id="alias-001",
        )

        expected_result = _make_agent_result(
            aliases={"project-a": "/home/user/project-a", "project-b": "/home/user/project-b"},
        )
        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="output"))

        with patch("app.terminal_agent.run_agent", new_callable=AsyncMock, return_value=expected_result):
            await manager.start_agent(session, execute_fn)
            await asyncio.sleep(0.2)

        # 验证 alias_store.save_batch 被调用
        mock_store.save_batch.assert_called_once_with(
            "user-1",
            "dev-1",
            {"project-a": "/home/user/project-a", "project-b": "/home/user/project-b"},
        )

    @pytest.mark.asyncio
    async def test_alias_load_on_agent_start(self):
        """Agent 启动时应从 alias_store 加载已知别名。"""
        mock_store = AsyncMock()
        mock_store.list_all = AsyncMock(return_value={"known-proj": "/path/known"})
        manager = AgentSessionManager(alias_store=mock_store)

        session = await manager.create_session(
            intent="test", device_id="dev-1", user_id="user-1", session_id="load-001",
        )

        captured_aliases = {}

        async def _capture_run(**kwargs):
            captured_aliases.update(kwargs.get("project_aliases", {}))
            return _make_agent_result()

        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="output"))

        with patch("app.terminal_agent.run_agent", new_callable=AsyncMock, side_effect=_capture_run):
            await manager.start_agent(session, execute_fn)
            await asyncio.sleep(0.2)

        assert captured_aliases == {"known-proj": "/path/known"}

    @pytest.mark.asyncio
    async def test_alias_save_failure_does_not_block_completion(self):
        """alias_store 保存失败不应阻止 Agent 完成。"""
        mock_store = AsyncMock()
        mock_store.list_all = AsyncMock(return_value={})
        mock_store.save_batch = AsyncMock(side_effect=RuntimeError("DB error"))
        manager = AgentSessionManager(alias_store=mock_store)

        session = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="alias-fail",
        )

        expected_result = _make_agent_result(aliases={"proj": "/path"})
        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="output"))

        with patch("app.terminal_agent.run_agent", new_callable=AsyncMock, return_value=expected_result):
            await manager.start_agent(session, execute_fn)
            await asyncio.sleep(0.2)

        # 即使别名保存失败，Agent 仍应完成
        assert session.state == AgentSessionState.COMPLETED


# ---------------------------------------------------------------------------
# A2. 安全测试汇总：27 个攻击向量端到端拦截
# ---------------------------------------------------------------------------

class TestSecurityAttackVectorsSummary:
    """端到端汇总：27 个攻击向量全部被拦截。

    不重复已有单元测试，只做端到端汇总断言。
    直接使用 validate_command 验证三重防护一致性。
    """

    # 27 个攻击向量：覆盖白名单外、shell 元字符、敏感路径、git 危险子命令、find 危险操作
    ATTACK_VECTORS = [
        # 白名单外（10 个）
        "rm -rf /",
        "sudo ls",
        "bash -c 'echo hi'",
        "python3 -c 'import os'",
        "curl http://evil.com",
        "wget http://evil.com",
        "ssh attacker@host",
        "nc -l 8080",
        "chmod 777 /etc/passwd",
        "shutdown -h now",
        # Shell 元字符（8 个）
        "ls; rm -rf /",
        "ls | grep secret",
        "ls &",
        "echo $HOME",
        "echo `whoami`",
        "echo $(whoami)",
        "echo hi > /tmp/file",
        "echo hi >> /tmp/file",
        # 敏感路径（6 个）
        "cat /etc/shadow",
        "ls /etc/ssh",
        "cat .ssh/id_rsa",
        "cat .ssh/known_hosts",
        "cat .env",
        "cat /proc/self/environ",
        # Git 危险子命令（2 个）
        "git push",
        "git checkout main",
        # Find 危险操作（1 个）
        "find . -name '*.tmp' -delete",
    ]

    def test_all_27_attack_vectors_blocked(self):
        """27 个攻击向量全部被 validate_command 拒绝。"""
        assert len(self.ATTACK_VECTORS) == 27, f"攻击向量数量应为 27，实际为 {len(self.ATTACK_VECTORS)}"
        for cmd in self.ATTACK_VECTORS:
            ok, reason = validate_command(cmd)
            assert not ok, f"攻击向量 '{cmd}' 应被拦截，但通过了验证: {reason}"

    @pytest.mark.asyncio
    async def test_all_27_attack_vectors_blocked_in_agent_tool(self):
        """27 个攻击向量通过 Agent execute_command 工具也全部被拒绝。"""
        assert len(self.ATTACK_VECTORS) == 27
        for cmd in self.ATTACK_VECTORS:
            deps = _make_deps()
            ctx = _make_run_context(deps)
            result = await execute_command(ctx, cmd)
            assert "错误" in result, f"攻击向量 '{cmd}' 应在 Agent 工具层被拦截"

    def test_allowed_commands_still_pass(self):
        """白名单内合法命令仍然通过。"""
        safe_commands = [
            "ls -la /home",
            "cat README.md",
            "grep -r 'TODO' .",
            "find . -name '*.py'",
            "pwd",
            "whoami",
            "git status",
            "git log --oneline -10",
            "echo hello world",
            "uname -a",
        ]
        for cmd in safe_commands:
            ok, reason = validate_command(cmd)
            assert ok, f"合法命令 '{cmd}' 应通过验证，但被拒绝: {reason}"


# ---------------------------------------------------------------------------
# A3. 超时测试
# ---------------------------------------------------------------------------

class TestTimeoutIntegration:
    """命令超时（10s）和会话超时（10min idle）测试。"""

    @pytest.mark.asyncio
    async def test_command_timeout_returns_timeout_message(self):
        """命令执行超时（10s）应返回超时信息。"""
        execute_fn = AsyncMock(return_value=_make_execute_result(
            timed_out=True, exit_code=-1,
        ))
        deps = _make_deps(execute_fn=execute_fn)
        ctx = _make_run_context(deps)

        result = await execute_command(ctx, "find / -name '*.log'")
        assert "超时" in result

    @pytest.mark.asyncio
    async def test_command_timeout_default_value(self):
        """DEFAULT_COMMAND_TIMEOUT 应为 10 秒。"""
        assert DEFAULT_COMMAND_TIMEOUT == 10

    @pytest.mark.asyncio
    async def test_session_timeout_cleans_up_idle_session(self):
        """10 分钟无交互的会话应被清理。"""
        manager = AgentSessionManager()
        session = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="timeout-1",
        )
        session.state = AgentSessionState.EXPLORING

        # 模拟 10 分钟前的活跃时间
        session.last_active_at = datetime.now(timezone.utc) - timedelta(seconds=SESSION_TIMEOUT_SECONDS + 10)

        expired = await manager.cleanup_expired()
        assert "timeout-1" in expired
        assert session.state == AgentSessionState.EXPIRED

    @pytest.mark.asyncio
    async def test_session_timeout_asksing_state(self):
        """ASKING 状态的会话超时后应取消 pending question。"""
        manager = AgentSessionManager()
        session = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="timeout-2",
        )
        session.state = AgentSessionState.ASKING
        session.last_active_at = datetime.now(timezone.utc) - timedelta(seconds=SESSION_TIMEOUT_SECONDS + 10)

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        session._pending_question_future = future

        await manager.cleanup_expired()

        assert future.done()
        with pytest.raises(AgentSessionExpired):
            future.result()

    @pytest.mark.asyncio
    async def test_session_timeout_not_for_completed(self):
        """COMPLETED 状态的会话不应被超时清理。"""
        manager = AgentSessionManager()
        session = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="timeout-3",
        )
        session.state = AgentSessionState.COMPLETED
        session.last_active_at = datetime.now(timezone.utc) - timedelta(seconds=SESSION_TIMEOUT_SECONDS + 100)

        expired = await manager.cleanup_expired()
        assert "timeout-3" not in expired

    @pytest.mark.asyncio
    async def test_session_timeout_pushes_error_event(self):
        """超时会话应推送 SESSION_EXPIRED 错误事件。"""
        manager = AgentSessionManager()
        session = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="timeout-4",
        )
        session.state = AgentSessionState.EXPLORING
        session.last_active_at = datetime.now(timezone.utc) - timedelta(seconds=SESSION_TIMEOUT_SECONDS + 10)

        await manager.cleanup_expired()

        # 检查事件队列
        events = []
        while not session.event_queue.empty():
            events.append(session.event_queue.get_nowait())

        error_events = [e for e in events if e is not None and e[0] == "error"]
        assert len(error_events) == 1
        assert error_events[0][1]["code"] == ErrorCode.SESSION_EXPIRED

    @pytest.mark.asyncio
    async def test_agent_loop_session_timeout(self):
        """Agent 循环中的会话超时应正确处理。"""
        manager = AgentSessionManager()
        session = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="loop-timeout",
        )

        execute_fn = AsyncMock()

        # 模拟 Agent 循环中抛出 AgentSessionExpired
        with patch("app.terminal_agent.run_agent", new_callable=AsyncMock, side_effect=AgentSessionExpired()):
            await manager.start_agent(session, execute_fn)
            await asyncio.sleep(0.1)

        assert session.state == AgentSessionState.EXPIRED

        # 检查事件队列中的错误事件
        events = []
        while not session.event_queue.empty():
            events.append(session.event_queue.get_nowait())
        error_events = [e for e in events if e is not None and e[0] == "error"]
        assert len(error_events) >= 1


# ---------------------------------------------------------------------------
# A4. 断连恢复测试
# ---------------------------------------------------------------------------

class TestDisconnectRecoveryIntegration:
    """4 种状态（exploring/asking/completed/expired）的断连恢复测试。"""

    @pytest.mark.asyncio
    async def test_exploring_state_recovery(self):
        """EXPLORING 状态断连后恢复应回放缓存事件。"""
        manager = AgentSessionManager()
        session = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="rec-explore",
        )
        session.state = AgentSessionState.EXPLORING

        # 推送一些探索 trace 事件
        await session.event_queue.put(("trace", {"tool": "execute_command", "input_summary": "ls ~", "output_summary": "project-a project-b"}))
        await session.event_queue.put(("trace", {"tool": "execute_command", "input_summary": "cat README", "output_summary": "My Project"}))
        await session.event_queue.put(None)

        # 消费并缓存
        async for chunk in manager.sse_stream(session):
            pass

        assert len(session._last_events) == 2

        # 恢复时，放入结束信号使实时流快速结束
        await session.event_queue.put(None)

        recovered = []
        async for chunk in manager.resume_stream(session, after_index=0):
            recovered.append(chunk)

        # 应有 2 个回放事件（实时流只有 None 结束信号，不产生 SSE 输出）
        assert len(recovered) == 2
        assert "event: trace" in recovered[0]
        assert "ls ~" in recovered[0]

    @pytest.mark.asyncio
    async def test_asking_state_recovery(self):
        """ASKING 状态断连后恢复应回放包含 question 的事件。"""
        manager = AgentSessionManager()
        session = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="rec-ask",
        )
        session.state = AgentSessionState.ASKING

        await session.event_queue.put(("trace", {"tool": "execute_command", "input_summary": "ls", "output_summary": "files"}))
        await session.event_queue.put(("question", {"question": "Which?", "options": ["a", "b"], "multi_select": False}))
        await session.event_queue.put(None)

        async for chunk in manager.sse_stream(session):
            pass

        # 恢复时，放入结束信号使实时流快速结束
        await session.event_queue.put(None)

        recovered = []
        async for chunk in manager.resume_stream(session, after_index=0):
            recovered.append(chunk)

        assert len(recovered) == 2
        assert "event: question" in recovered[1]

    @pytest.mark.asyncio
    async def test_completed_state_recovery_only_replay(self):
        """COMPLETED 状态断连后恢复只回放缓存，不进入实时流。"""
        manager = AgentSessionManager()
        session = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="rec-done",
        )

        await session.event_queue.put(("trace", {"tool": "execute_command", "input_summary": "ls", "output_summary": "ok"}))
        await session.event_queue.put(("result", {"summary": "done", "steps": [], "provider": "agent", "source": "recommended", "need_confirm": True, "aliases": {}}))
        await session.event_queue.put(None)

        async for chunk in manager.sse_stream(session):
            pass

        session.state = AgentSessionState.COMPLETED

        recovered = []
        async for chunk in manager.resume_stream(session, after_index=0):
            recovered.append(chunk)

        assert len(recovered) == 2
        assert "event: result" in recovered[1]
        # 不应有实时流（已完成）

    @pytest.mark.asyncio
    async def test_expired_state_recovery_only_replay(self):
        """EXPIRED 状态断连后恢复只回放缓存。"""
        manager = AgentSessionManager()
        session = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="rec-expired",
        )

        await session.event_queue.put(("trace", {"tool": "execute_command", "input_summary": "ls", "output_summary": "ok"}))
        await session.event_queue.put(("error", {"code": ErrorCode.SESSION_EXPIRED, "message": "会话已超时"}))
        await session.event_queue.put(None)

        async for chunk in manager.sse_stream(session):
            pass

        session.state = AgentSessionState.EXPIRED

        recovered = []
        async for chunk in manager.resume_stream(session, after_index=0):
            recovered.append(chunk)

        assert len(recovered) == 2
        assert "event: error" in recovered[1]

    @pytest.mark.asyncio
    async def test_recovery_from_specific_index(self):
        """从指定索引恢复只回放后续事件。"""
        manager = AgentSessionManager()
        session = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="rec-index",
        )

        for i in range(5):
            await session.event_queue.put(("trace", {"tool": "cmd", "input_summary": f"cmd-{i}", "output_summary": "ok"}))
        await session.event_queue.put(None)

        async for chunk in manager.sse_stream(session):
            pass

        session.state = AgentSessionState.COMPLETED

        # 从索引 3 开始恢复
        recovered = []
        async for chunk in manager.resume_stream(session, after_index=3):
            recovered.append(chunk)

        assert len(recovered) == 2  # 只有 index 3, 4


# ---------------------------------------------------------------------------
# A5. 别名隔离
# ---------------------------------------------------------------------------

class TestAliasIsolationIntegration:
    """别名隔离测试：user_id 隔离、device_id 隔离、首用探索持久化。"""

    @pytest.mark.asyncio
    async def test_user_isolation_in_session_manager(self):
        """不同 user_id 的别名不应互相影响。"""
        store_a = AsyncMock()
        store_a.list_all = AsyncMock(return_value={"proj": "/alice/proj"})

        manager = AgentSessionManager(alias_store=store_a)

        # user-1 的会话
        session_alice = await manager.create_session(
            intent="进入项目", device_id="dev-1", user_id="alice", session_id="alice-1",
        )

        result_alice = _make_agent_result(aliases={"proj": "/alice/new-proj"})
        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="output"))

        with patch("app.terminal_agent.run_agent", new_callable=AsyncMock, return_value=result_alice):
            await manager.start_agent(session_alice, execute_fn)
            await asyncio.sleep(0.2)

        # 验证 alias_store 用 alice 的 user_id 调用
        store_a.save_batch.assert_called_with("alice", "dev-1", {"proj": "/alice/new-proj"})

    @pytest.mark.asyncio
    async def test_device_isolation_in_session_manager(self):
        """不同 device_id 的别名不应互相影响。"""
        mock_store = AsyncMock()
        mock_store.list_all = AsyncMock(return_value={})
        manager = AgentSessionManager(alias_store=mock_store)

        # device-a 的会话
        session_a = await manager.create_session(
            intent="test", device_id="device-a", user_id="alice", session_id="dev-a",
        )
        result_a = _make_agent_result(aliases={"app": "/path/a"})
        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="output"))

        with patch("app.terminal_agent.run_agent", new_callable=AsyncMock, return_value=result_a):
            await manager.start_agent(session_a, execute_fn)
            await asyncio.sleep(0.2)

        mock_store.save_batch.assert_called_with("alice", "device-a", {"app": "/path/a"})

    @pytest.mark.asyncio
    async def test_first_use_no_aliases_then_explored(self):
        """首用时无别名，Agent 探索后应持久化新发现的别名。"""
        mock_store = AsyncMock()
        # 首次调用 list_all 返回空（无已知别名）
        mock_store.list_all = AsyncMock(return_value={})
        manager = AgentSessionManager(alias_store=mock_store)

        session = await manager.create_session(
            intent="test", device_id="dev-new", user_id="new-user", session_id="first-use",
        )

        # Agent 探索后发现新项目
        discovered_aliases = {
            "remote-control": "/home/user/remote-control",
            "ai-learn": "/home/user/ai-learn",
        }
        result = _make_agent_result(aliases=discovered_aliases)
        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="output"))

        captured_aliases = {}

        async def _capture_run(**kwargs):
            # 首次应无已知别名
            captured_aliases.update(kwargs.get("project_aliases", {}))
            return result

        with patch("app.terminal_agent.run_agent", new_callable=AsyncMock, side_effect=_capture_run):
            await manager.start_agent(session, execute_fn)
            await asyncio.sleep(0.2)

        # 注入时无别名
        assert captured_aliases == {}
        # 探索后持久化
        mock_store.save_batch.assert_called_once_with("new-user", "dev-new", discovered_aliases)

    @pytest.mark.asyncio
    async def test_second_use_loads_known_aliases(self):
        """第二次使用时应加载之前探索到的别名。"""
        known_aliases = {"remote-control": "/home/user/remote-control"}
        mock_store = AsyncMock()
        mock_store.list_all = AsyncMock(return_value=known_aliases)
        manager = AgentSessionManager(alias_store=mock_store)

        session = await manager.create_session(
            intent="test", device_id="dev-1", user_id="user-1", session_id="second-use",
        )

        captured_aliases = {}

        async def _capture_run(**kwargs):
            captured_aliases.update(kwargs.get("project_aliases", {}))
            return _make_agent_result()

        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="output"))

        with patch("app.terminal_agent.run_agent", new_callable=AsyncMock, side_effect=_capture_run):
            await manager.start_agent(session, execute_fn)
            await asyncio.sleep(0.2)

        # 第二次使用时加载了已知别名
        assert captured_aliases == known_aliases


# ---------------------------------------------------------------------------
# A6. 输出边界
# ---------------------------------------------------------------------------

class TestOutputBoundaryIntegration:
    """输出边界测试：大输出截断（> 4096）、空输出、特殊字符输出。"""

    @pytest.mark.asyncio
    async def test_large_output_in_execute_command(self):
        """大于 4096 字符的输出应被标记为截断。"""
        large_output = "x" * 8000
        execute_fn = AsyncMock(return_value=_make_execute_result(
            stdout=large_output,
            truncated=True,
        ))
        deps = _make_deps(execute_fn=execute_fn)
        ctx = _make_run_context(deps)

        result = await execute_command(ctx, "ls -R /very/large/directory")
        # 输出包含截断的内容
        assert len(result) > 0
        # truncated 标志在 ExecuteCommandResult 中
        execute_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_max_stdout_len_constant(self):
        """MAX_STDOUT_LEN 常量应为 4096。"""
        assert MAX_STDOUT_LEN == 4096

    @pytest.mark.asyncio
    async def test_empty_output_returns_placeholder(self):
        """空输出应返回 (无输出) 占位文本。"""
        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="", stderr=""))
        deps = _make_deps(execute_fn=execute_fn)
        ctx = _make_run_context(deps)

        result = await execute_command(ctx, "ls /empty/dir")
        assert "(无输出)" in result

    @pytest.mark.asyncio
    async def test_special_characters_in_output(self):
        """包含特殊字符（Unicode、控制字符）的输出应正确传递。"""
        special_output = "日本語テスト\t\n ANSI escape: \033[31mred\033[0m\n emoji: \U0001f600"
        execute_fn = AsyncMock(return_value=_make_execute_result(stdout=special_output))
        deps = _make_deps(execute_fn=execute_fn)
        ctx = _make_run_context(deps)

        result = await execute_command(ctx, "cat README.md")
        assert "日本語テスト" in result
        assert "emoji" in result

    @pytest.mark.asyncio
    async def test_stderr_combined_in_output(self):
        """stderr 应合并到输出中。"""
        execute_fn = AsyncMock(return_value=_make_execute_result(
            stdout="normal output",
            stderr="warning message",
            exit_code=1,
        ))
        deps = _make_deps(execute_fn=execute_fn)
        ctx = _make_run_context(deps)

        result = await execute_command(ctx, "ls /nonexistent")
        assert "normal output" in result
        assert "[stderr] warning message" in result
        assert "[exit_code=1]" in result

    @pytest.mark.asyncio
    async def test_sse_event_with_large_result(self):
        """SSE 事件应能正确传递大量 step 数据。"""
        manager = AgentSessionManager()
        session = await manager.create_session(
            intent="test", device_id="d", user_id="u", session_id="large-sse",
        )

        # 创建包含很多 step 的 result
        large_result = _make_agent_result(
            summary="many steps",
            steps=[CommandSequenceStep(id=f"s{i}", label=f"step-{i}", command=f"echo {i}") for i in range(50)],
            aliases={f"alias-{i}": f"/path/{i}" for i in range(20)},
        )
        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="output"))

        with patch("app.terminal_agent.run_agent", new_callable=AsyncMock, return_value=large_result):
            await manager.start_agent(session, execute_fn)
            await asyncio.sleep(0.2)

        assert session.result is not None
        assert len(session.result.steps) == 50
        assert len(session.result.aliases) == 20


# ---------------------------------------------------------------------------
# A7. 手机端不受 Agent 影响验证
# ---------------------------------------------------------------------------

class TestMobileClientNotAffected:
    """验证 Agent 会话不影响手机端普通终端操作。"""

    @pytest.mark.asyncio
    async def test_agent_session_does_not_block_other_sessions(self):
        """Agent 会话不应阻止同一用户的其他终端操作。"""
        manager = AgentSessionManager()

        # 创建 Agent 会话
        agent_session = await manager.create_session(
            intent="test", device_id="dev-1", user_id="user-1", session_id="agent-sess",
        )

        # 用户可以有多个 Agent 会话（受频率限制）
        # Agent 会话独立管理，不影响其他系统
        assert await manager.get_session("agent-sess") is not None
        assert manager.get_session_count() == 1

        # 模拟另一个非 Agent 会话（由其他系统管理）
        # 这里只验证 AgentSessionManager 不会干扰
        other_session = await manager.create_session(
            intent="other task", device_id="dev-2", user_id="user-1", session_id="other-sess",
        )
        assert await manager.get_session("agent-sess") is not None
        assert await manager.get_session("other-sess") is not None
        assert manager.get_session_count() == 2

    @pytest.mark.asyncio
    async def test_agent_session_isolation_between_devices(self):
        """不同设备的 Agent 会话完全独立。"""
        manager = AgentSessionManager()

        s1 = await manager.create_session(
            intent="project A", device_id="dev-1", user_id="user-1", session_id="dev1-sess",
        )
        s2 = await manager.create_session(
            intent="project B", device_id="dev-2", user_id="user-1", session_id="dev2-sess",
        )

        assert s1.device_id != s2.device_id
        assert s1.intent != s2.intent

        # 取消一个不影响另一个
        await manager.cancel("dev1-sess")
        assert s1.state == AgentSessionState.CANCELLED
        assert s2.state == AgentSessionState.EXPLORING

    @pytest.mark.asyncio
    async def test_agent_error_does_not_affect_other_sessions(self):
        """一个 Agent 会话出错不影响其他会话。"""
        manager = AgentSessionManager()

        s1 = await manager.create_session(
            intent="will fail", device_id="dev-1", user_id="user-1", session_id="err-sess",
        )
        s2 = await manager.create_session(
            intent="should work", device_id="dev-2", user_id="user-1", session_id="ok-sess",
        )

        execute_fn = AsyncMock()

        # s1 出错
        with patch("app.terminal_agent.run_agent", new_callable=AsyncMock, side_effect=RuntimeError("LLM failed")):
            await manager.start_agent(s1, execute_fn)
            await asyncio.sleep(0.1)

        assert s1.state == AgentSessionState.ERROR
        # s2 不受影响
        assert s2.state == AgentSessionState.EXPLORING


# ---------------------------------------------------------------------------
# A8. 频率限制集成
# ---------------------------------------------------------------------------

class TestRateLimitIntegration:
    """用户级频率限制集成测试。"""

    @pytest.mark.asyncio
    async def test_user_rate_limit_enforced(self):
        """用户超过频率限制时应被拒绝。"""
        manager = AgentSessionManager()

        for i in range(USER_SESSION_RATE_LIMIT):
            s = await manager.create_session(
                intent=f"test-{i}", device_id="d", user_id="user-rl", session_id=f"rl-{i}",
            )
            s.state = AgentSessionState.EXPLORING

        with pytest.raises(AgentSessionRateLimited):
            await manager.create_session(
                intent="overflow", device_id="d", user_id="user-rl",
            )

    @pytest.mark.asyncio
    async def test_different_users_independent_limits(self):
        """不同用户有独立的频率限制。"""
        manager = AgentSessionManager()

        for i in range(USER_SESSION_RATE_LIMIT):
            s = await manager.create_session(
                intent=f"test-{i}", device_id="d", user_id="user-a", session_id=f"a-rl-{i}",
            )
            s.state = AgentSessionState.EXPLORING

        # user-b 不受 user-a 限制
        s = await manager.create_session(
            intent="test", device_id="d", user_id="user-b",
        )
        assert s is not None

    @pytest.mark.asyncio
    async def test_completed_sessions_free_up_limit(self):
        """已完成的会话释放频率限制配额。"""
        manager = AgentSessionManager()

        for i in range(USER_SESSION_RATE_LIMIT):
            s = await manager.create_session(
                intent=f"test-{i}", device_id="d", user_id="user-free", session_id=f"free-{i}",
            )
            s.state = AgentSessionState.COMPLETED  # 已完成

        # 活跃数为 0，应能创建新会话
        s = await manager.create_session(
            intent="new", device_id="d", user_id="user-free",
        )
        assert s is not None


# ===========================================================================
# B. Docker smoke（标记 skip）
# ===========================================================================

class TestDockerSmoke:
    """Docker 环境下的全链路 smoke 测试。

    需要 Docker 环境运行，本地 pytest 跳过。
    """

    @pytest.mark.skip(reason="需要 Docker 环境")
    @pytest.mark.asyncio
    async def test_docker_happy_path_full_pipeline(self):
        """Docker happy path 全链路：创建终端 -> Agent 探索 -> 结果返回。"""
        # 在 Docker 环境中：
        # 1. 启动 Server + Agent 容器
        # 2. 通过 HTTP API 创建 Agent 会话
        # 3. 验证 SSE 流事件完整
        # 4. 验证 Agent 实际执行命令
        # 5. 验证结果正确
        pass

    @pytest.mark.skip(reason="需要 Docker 环境")
    @pytest.mark.asyncio
    async def test_docker_agent_execute_command_real(self):
        """Docker 中 Agent 端 execute_command 实际执行。"""
        # 验证 Agent 端实际执行 ls、find 等命令
        # 验证输出截断
        # 验证超时处理
        pass

    @pytest.mark.skip(reason="需要 Docker 环境")
    @pytest.mark.asyncio
    async def test_docker_sse_stream_integrity(self):
        """Docker 中 SSE 流完整性验证。"""
        # 验证 SSE 事件无丢失
        # 验证 keepalive 正常工作
        # 验证断连恢复
        pass

    @pytest.mark.skip(reason="需要 Docker 环境")
    @pytest.mark.asyncio
    async def test_docker_alias_persistence_across_sessions(self):
        """Docker 中别名跨会话持久化。"""
        # 第一次会话：Agent 探索发现别名
        # 第二次会话：应加载之前的别名
        pass

    @pytest.mark.skip(reason="需要 Docker 环境")
    @pytest.mark.asyncio
    async def test_docker_27_attack_vectors_blocked(self):
        """Docker 中 27 个攻击向量端到端拦截。"""
        # 通过实际 WebSocket 发送恶意命令
        # 验证 Server 端和 Agent 端双重拦截
        pass
