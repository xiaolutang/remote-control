"""
B079/B089: Pydantic AI ReAct 智能体核心实现。

使用 Pydantic AI 框架定义 Agent，提供 execute_command、ask_user 和 lookup_knowledge 三个工具，
最终产物收口为 AgentResult（可转化为 CommandSequence）。

B089 变更：重新定位为"AI 编程启动器"——Agent 的核心价值是与用户讨论编程意图，
然后将讨论上下文组装成 claude/codex 命令直接执行。lookup_knowledge 提供项目知识丰富生成的 prompt。

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
    if any(
        keyword in message
        for keyword in (
            "json",
            "parse",
            "unexpectedmodelbehavior",
            "validation",
            "structure",
            "schema",
        )
    ):
        return "智能服务响应格式异常，请重试或换个表述"
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
    lookup_knowledge_fn: Optional[Callable[[str], Awaitable[str]]] = None  # B089: 知识检索回调
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

SYSTEM_PROMPT = """你是 AI 编程启动器，帮助用户将编程意图转化为可执行的 AI 编程工具命令（claude / codex）。

# 最高优先级规则（不可违反）
你的每一次回复都必须且只能是合法 JSON 对象，格式如下：
{"summary": "描述", "steps": [{"id": "s1", "label": "步骤名", "command": "命令"}], "need_confirm": true, "aliases": {}}

禁止输出：纯文本、Markdown、解释说明、自然语言描述。
无论是直接回答、使用工具后、还是无法生成命令时，都必须输出上述 JSON 格式。

# 核心定位：AI 编程启动器
你的核心工作是：
1. 与用户讨论编程意图（做什么、怎么做）
2. 使用 lookup_knowledge 获取 AI 编程技巧和项目知识
3. 将讨论结果组装成 claude 或 codex 命令，让用户直接在终端执行

# AI 编程工具映射
- "Claude Code" / "Claude" / "用 Claude" → 命令 `claude`
- "Codex CLI" → 仅用于知识说明（info-only），不生成 `codex` 执行命令
- 推荐用 `which claude` 验证工具是否可用，不存在时提示用户安装

# 工具使用优先级
1. **lookup_knowledge**：用户问 AI 编程相关问题或需要项目知识时优先调用
2. **execute_command**：探索远端设备（目录、文件、项目结构）
3. **ask_user**：多选项消歧或追问澄清

# 用户旅程
## 编程意图 → 生成命令（主旅程）
用户："帮我用 Claude 重构 auth 模块" →
  你调用 lookup_knowledge("重构代码 Claude Code 技巧") →
  你调用 execute_command("pwd") 确认项目位置 →
  输出：{"summary": "基于重构技巧启动 Claude Code", "steps": [{"id": "s1", "label": "用 Claude Code 重构 auth 模块", "command": "claude"}], "need_confirm": true, "aliases": {}}

## 信息型问答（纯知识）
用户："Claude Code 怎么用" →
  你调用 lookup_knowledge("Claude Code 使用技巧") →
  输出：{"summary": "Claude Code 使用技巧：1. ...", "steps": [], "need_confirm": false, "aliases": {}}

## 混合意图（知识 + 命令）
用户："帮我看看 Claude Code 怎么用，然后打开 remote-control 项目" →
  你调用 lookup_knowledge("Claude Code 使用技巧") →
  你调用 execute_command("find ~ -maxdepth 3 -name 'package.json'") →
  输出：{"summary": "Claude Code 使用技巧：...。已定位项目。", "steps": [{"id": "s1", "label": "进入项目并启动 Claude Code", "command": "cd ~/remote-control && claude"}], "need_confirm": true, "aliases": {"remote-control": "~/remote-control"}}

# lookup_knowledge 降级规则
- lookup_knowledge 不可用（工具未注册）：忽略，继续正常处理
- lookup_knowledge 返回空/未命中：在 summary 中说明，不阻塞命令生成
- 禁止在 lookup_knowledge 不可用时自行编造知识内容

# 探索规范
- 推荐命令：ls、find、cat、pwd、git remote/status/log、which
- 每次只执行一个命令，分析输出后再决定下一步
- 先从大范围探索（ls ~）逐步缩小到具体项目

# 决策优先级
1. 自主探索：优先用 execute_command 获取事实
2. 知识增强：用 lookup_knowledge 获取 AI 编程技巧
3. 选项消歧：多个可能时用 ask_user 让用户选择
4. 坦诚告知：无法确定时告知并建议手动操作

# 项目别名
发现项目目录时，在 aliases 字段中记录路径和名称映射。

# 限制
- 只能执行只读命令，不能执行写、删、改、安装、更新、部署
- 用户请求超出范围时，返回 steps 为空、need_confirm 为 false 的 JSON
- Codex CLI 仅用于知识说明，不生成 codex 执行命令
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


@terminal_agent.tool
async def lookup_knowledge(
    ctx: RunContext[AgentDeps],
    query: str,
) -> str:
    """检索本地知识文件，返回与查询关键词匹配的知识内容。

    用于获取 Claude Code 使用技巧、Vibe Coding 方法论、项目相关知识和 AI 编程最佳实践。
    当 lookup_knowledge 不可用（Agent 设备不支持）时，返回空字符串，不阻塞后续处理。

    Args:
        query: 检索关键词
    """
    if ctx.deps.lookup_knowledge_fn is None:
        return ""
    try:
        result = await ctx.deps.lookup_knowledge_fn(query)
        return result
    except Exception as e:
        logger.warning("lookup_knowledge error: %s", e)
        return ""


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
    lookup_knowledge_fn: Callable[[str], Awaitable[str]] | None = None,
) -> AgentRunOutcome:
    """运行 Agent 处理用户意图。

    Args:
        intent: 用户的意图描述
        session_id: Agent WS session ID
        execute_command_fn: 执行命令的回调 (session_id, command, cwd) -> ExecuteCommandResult
        ask_user_fn: 向用户提问的回调 (question, options, multi_select) -> str
        project_aliases: 已知项目别名
        message_history: 对话历史（用于多轮）
        lookup_knowledge_fn: 知识检索回调 (query) -> str，可选

    Returns:
        AgentRunOutcome 包含 AgentResult + token usage 统计
    """
    deps = AgentDeps(
        session_id=session_id,
        execute_command_fn=execute_command_fn,
        ask_user_fn=ask_user_fn,
        lookup_knowledge_fn=lookup_knowledge_fn,
        project_aliases=project_aliases or {},
    )
    if not planner_api_key():
        raise AgentUserFacingError("智能服务 Token 未配置，请联系开发者")

    import pydantic_ai.exceptions as pai_exc

    # 最多重试 2 次（含首次，共 3 次尝试），仅对 JSON 格式错误重试
    max_attempts = 3
    retry_hint = None
    for attempt in range(1, max_attempts + 1):
        try:
            run_result = await terminal_agent.run(
                user_prompt=intent if retry_hint is None else f"{intent}\n\n{retry_hint}",
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
        except pai_exc.UnexpectedModelBehavior as e:
            if attempt < max_attempts:
                logger.warning(
                    "Agent JSON format error (attempt %d/%d), retrying: %s",
                    attempt, max_attempts, e,
                )
                retry_hint = "注意：你上次输出不是合法 JSON。请严格按格式输出：{\"summary\": \"...\", \"steps\": [...], \"need_confirm\": true, \"aliases\": {}}"
                continue
            logger.warning("Agent model error after %d attempts: %s", max_attempts, e)
            raise AgentUserFacingError(_user_facing_model_error_message(e)) from e
        except pai_exc.ModelHTTPError as e:
            logger.warning("Agent model HTTP error: %s", e)
            raise AgentUserFacingError(_user_facing_model_error_message(e)) from e
        except Exception as e:
            logger.error("Agent run unexpected error: %s: %s", type(e).__name__, e)
            raise
