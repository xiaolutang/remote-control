"""
B079: Pydantic AI ReAct 智能体核心实现。

使用 Pydantic AI 框架定义 Agent，提供 execute_command 和 ask_user 两个工具，
最终产物收口为 AgentResult（可转化为 CommandSequence）。

架构约束：
- 不变量 #43: 最终产物必须收口为 CommandSequence
- 不变量 #47: 只能基于已有事实、planner memory、用户输入、受约束的只读探索命令
- 不变量 #54: 探索命令必须白名单+元字符+敏感路径三重防护
- 权威边界: 不得绕过 Agent WS 直接操作 PTY
"""
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.command_validator import validate_command
from app.assistant_planner import (
    planner_api_key,
    planner_base_url,
    planner_model,
    planner_timeout_ms,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result Type
# ---------------------------------------------------------------------------

class CommandSequenceStep(BaseModel):
    """单条命令步骤，与 runtime_api.AssistantCommandStep 字段对齐。"""
    id: str
    label: str
    command: str


class AgentResult(BaseModel):
    """Agent 最终收口产物，可无损转化为 AssistantCommandSequence。"""
    summary: str
    steps: list[CommandSequenceStep]
    provider: str = "agent"
    source: str = "recommended"
    need_confirm: bool = True
    aliases: dict[str, str] = {}  # 本次发现的项目别名


# ---------------------------------------------------------------------------
# Agent Deps
# ---------------------------------------------------------------------------

@dataclass
class AgentDeps:
    """Agent 运行时依赖，由会话管理器注入。"""
    session_id: str  # Agent WS session_id
    execute_command_fn: Callable[[str, str, Optional[str]], Awaitable['ExecuteCommandResult']]  # noqa: E501
    ask_user_fn: Callable[[str, list[str], bool], Awaitable[str]]
    project_aliases: dict[str, str] = field(default_factory=dict)  # 已知项目别名


# ---------------------------------------------------------------------------
# Model 构建器
# ---------------------------------------------------------------------------

def _build_model() -> OpenAIModel:
    """手动构建 OpenAIModel 以复用现有 planner 配置，避免全局环境变量污染。"""
    provider = OpenAIProvider(
        api_key=planner_api_key(),
        base_url=planner_base_url() or None,
    )
    return OpenAIModel(model_name=planner_model(), provider=provider)


# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """你是一个智能终端助手，帮助用户快速进入正确的项目目录并启动开发工具。

你的核心目标是理解用户的意图，探索远端设备上的项目结构，生成精确的命令序列。

## 决策优先级（从高到低）
1. **自主探索**：优先使用 execute_command 探索设备事实（ls、find、cat 等），减少对用户的打扰
2. **选项消歧**：当存在多个可能的项目/工具时，提供选项让用户快速选择
3. **追问补充**：仅在自主探索无法确定时，才追问用户
4. **坦诚告知**：当确实无法确定时，坦诚告知并建议手动操作

## 探索命令使用规范
- 只能使用 execute_command 工具执行只读命令
- 推荐命令：ls、find、cat、pwd、git remote/status/log
- 每次只执行一个命令，分析输出后再决定下一步
- 先从大范围探索（ls ~）逐步缩小到具体项目

## 输出格式
最终必须返回 AgentResult，包含：
- summary: 简要描述将要执行的操作
- steps: 命令步骤列表（cd + 启动工具）
- aliases: 本次发现的项目别名（目录路径 -> 用户可读名称）

## 项目别名
当你发现项目目录时，记住它们的路径和名称（从 package.json、README、目录名推断）。
这些别名会帮助未来更快地找到项目。

## 工作目录
- 用户指定的项目路径优先
- 如果用户只说了项目名，先用 find 或 ls 搜索匹配的目录
- 确认目录存在后再生成 cd 命令

## 限制
- 不能执行写、删、改操作
- 不能执行安装、更新、部署等操作
- 如果用户请求超出能力范围，坦诚告知
"""  # noqa: E501


# ---------------------------------------------------------------------------
# Agent 定义
# ---------------------------------------------------------------------------

terminal_agent = Agent(
    model=_build_model(),
    deps_type=AgentDeps,
    output_type=AgentResult,
    system_prompt=SYSTEM_PROMPT,
)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@terminal_agent.tool
async def execute_command(
    ctx: RunContext[AgentDeps],
    command: str,
    cwd: str | None = None,
) -> str:
    """在远端设备执行只读命令并返回输出。可用于探索项目结构、查看文件内容等。

    命令必须是只读的，超时默认10秒。

    Args:
        command: 要执行的命令字符串
        cwd: 工作目录（可选）
    """
    # 白名单 + 元字符 + 敏感路径 三重验证
    valid, reason = validate_command(command)
    if not valid:
        return f"错误：命令被拒绝 - {reason}"

    try:
        result = await ctx.deps.execute_command_fn(
            ctx.deps.session_id, command, cwd
        )
        if result.timed_out:
            return f"命令超时（{result.exit_code}）"
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr] {result.stderr}"
        if result.exit_code != 0:
            output += f"\n[exit_code={result.exit_code}]"
        return output or "(无输出)"
    except Exception as e:
        return f"错误：执行失败 - {type(e).__name__}: {e}"


@terminal_agent.tool
async def ask_user(
    ctx: RunContext[AgentDeps],
    question: str,
    options: list[str] | None = None,
    multi_select: bool = False,
) -> str:
    """向用户提问以获取更多上下文或澄清意图。

    Args:
        question: 要问用户的问题
        options: 可选的选项列表，用户可以从中选择
        multi_select: 是否允许多选
    """
    result = await ctx.deps.ask_user_fn(
        question, options or [], multi_select
    )
    return result


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------

async def run_agent(
    intent: str,
    session_id: str,
    execute_command_fn: Callable,
    ask_user_fn: Callable,
    project_aliases: dict[str, str] | None = None,
    message_history: list | None = None,
) -> AgentResult:
    """运行 Agent 处理用户意图。

    Args:
        intent: 用户的意图描述
        session_id: Agent WS session ID
        execute_command_fn: 执行命令的回调 (session_id, command, cwd) -> ExecuteCommandResult
        ask_user_fn: 向用户提问的回调 (question, options, multi_select) -> str
        project_aliases: 已知项目别名
        message_history: 对话历史（用于多轮）

    Returns:
        AgentResult 收口为 CommandSequence
    """
    deps = AgentDeps(
        session_id=session_id,
        execute_command_fn=execute_command_fn,
        ask_user_fn=ask_user_fn,
        project_aliases=project_aliases or {},
    )
    result = await terminal_agent.run(
        user_prompt=intent,
        deps=deps,
        message_history=message_history,
    )
    return result.output
