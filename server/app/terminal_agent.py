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


class AgentUserFacingError(RuntimeError):
    """可直接展示给最终用户的 Agent 运行错误。"""


def _user_facing_model_error_message(error: Exception) -> str:
    message = str(error).lower()
    if any(
        keyword in message
        for keyword in (
            "api key",
            "authentication",
            "unauthorized",
            "invalid api key",
            "insufficient_quota",
            "quota",
            "rate limit",
            "billing",
            "401",
            "402",
            "403",
            "429",
        )
    ):
        return "智能服务 Token 或配额不可用，请联系开发者"
    return "智能服务暂时不可用，请联系开发者"


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


@dataclass
class AgentRunOutcome:
    """run_agent() 返回值：AgentResult + token usage 统计。

    usage 仅通过 SSE result 事件推送，不持久化到 AgentSession.result。
    """
    result: AgentResult
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    requests: int = 0
    model_name: str = ""


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
你必须始终输出合法 JSON，格式为 AgentResult 对象。禁止输出纯文本、Markdown 或任何非 JSON 内容。
包含字段：summary（操作描述）、steps（命令步骤列表，每项含 id/label/command）、aliases（项目别名映射）、need_confirm。
正确示例：{"summary": "已定位到项目目录", "steps": [{"id": "s1", "label": "进入项目", "command": "cd ~/project"}], "need_confirm": true, "aliases": {}}

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

## 非终端意图处理
如果用户的输入与终端命令、项目导航、开发工具无关（如打招呼、闲聊、提问），
返回 steps 为空的 AgentResult。正确示例：
{"summary": "我专注于帮助你进入项目目录和启动开发工具，请告诉我你想做什么。", "steps": [], "need_confirm": false, "aliases": {}}
永远不要因为无法生成命令而报错或抛异常，也不要输出纯文本。
"""  # noqa: E501


# ---------------------------------------------------------------------------
# Agent 定义
# ---------------------------------------------------------------------------

terminal_agent = Agent(
    model=_build_model(),
    deps_type=AgentDeps,
    output_type=AgentResult,
    system_prompt=SYSTEM_PROMPT,
    retries=3,
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
) -> AgentRunOutcome:
    """运行 Agent 处理用户意图。

    Args:
        intent: 用户的意图描述
        session_id: Agent WS session ID
        execute_command_fn: 执行命令的回调 (session_id, command, cwd) -> ExecuteCommandResult
        ask_user_fn: 向用户提问的回调 (question, options, multi_select) -> str
        project_aliases: 已知项目别名
        message_history: 对话历史（用于多轮）

    Returns:
        AgentRunOutcome 包含 AgentResult + token usage 统计
    """
    deps = AgentDeps(
        session_id=session_id,
        execute_command_fn=execute_command_fn,
        ask_user_fn=ask_user_fn,
        project_aliases=project_aliases or {},
    )
    if not planner_api_key():
        raise AgentUserFacingError("智能服务 Token 未配置，请联系开发者")
    try:
        run_result = await terminal_agent.run(
            user_prompt=intent,
            deps=deps,
            message_history=message_history,
        )
        usage = run_result.usage()
        return AgentRunOutcome(
            result=run_result.output,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            requests=usage.requests,
            model_name=planner_model(),
        )
    except Exception as e:
        # SSE 会话上下文中所有异常都需优雅降级，不能让流崩溃
        # 但区分日志级别：模型类异常 warning，编程错误 error
        import pydantic_ai.exceptions as pai_exc
        if isinstance(e, (
            pai_exc.UnexpectedModelBehavior,
            pai_exc.ModelHTTPError,
        )):
            logger.warning("Agent model error: %s", e)
            raise AgentUserFacingError(_user_facing_model_error_message(e)) from e
        else:
            logger.error("Agent run unexpected error: %s: %s", type(e).__name__, e)
            raise
