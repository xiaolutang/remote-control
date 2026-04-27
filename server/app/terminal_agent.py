"""
B079/B089/B105: Pydantic AI ReAct 智能体核心实现。

使用 Pydantic AI 框架定义 Agent，提供 execute_command、ask_user、lookup_knowledge 和 deliver_result 四个工具，
最终产物通过 deliver_result 工具交付，通过 ResultDelivered 异常终止 agent run。

B105 变更：Agent output_type 从 AgentResult 改为 str（自由文本），
模型在 ReAct 循环中自由对话，需要交付结果时主动调用 deliver_result 工具。
deliver_result 通过 ResultDelivered 异常终止 agent run 并携带结构化结果。
usage 统计通过 RunUsage 对象传入 agent.run()，在 ReAct 循环中逐轮累积。

B089 变更：重新定位为"终端侧 Claude Code 预处理助手"——Agent 的核心价值是与用户讨论编程意图，
然后将讨论上下文组装成 claude/codex 命令直接执行。lookup_knowledge 提供项目知识丰富生成的 prompt。

B093 变更：Session-scoped Agent factory——每次会话创建独立 Agent 实例，
动态工具注册为真实 Pydantic AI tool（非 prompt 注入）。
全局 `terminal_agent` 保留仅用于无动态工具的兼容场景。

架构约束：
- 不变量 #43: 最终产物通过 deliver_result 工具交付，通过 response_type 区分三种语义
- 不变量 #47: 只能基于已有事实、planner memory、用户输入、受约束的只读探索命令
- 不变量 #50: 不展示模型原始 chain-of-thought。assistant_message 为用户可见助手回复
- 不变量 #54: 探索命令必须白名单+元字符+敏感路径三重防护
- 权威边界: 不得绕过 Agent WS 直接操作 PTY
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal, Optional

from pydantic import BaseModel, ConfigDict, create_model, model_validator
from pydantic_ai import Agent, RunContext, RunUsage
import pydantic_ai.exceptions as pai_exc
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


class AgentNoDeliveryError(AgentUserFacingError):
    """模型未调用 deliver_result 工具就结束了 agent run。

    携带已累积的 RunUsage，供上游（session manager）在 error 路径中读取 usage。
    B106 负责在 session manager 中处理此异常的 usage 字段。
    """
    def __init__(self, message: str, usage: 'RunUsage'):
        super().__init__(message)
        self.usage = usage


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
    """Agent 最终收口产物，通过 response_type 区分三种语义。

    response_type:
      - 'command': 命令序列（steps 含可执行 shell 命令，需用户确认）
      - 'message': 纯信息型回复（steps=[], 无需确认）
      - 'ai_prompt': AI prompt 注入（steps=[], ai_prompt 含完整 prompt, 需用户确认）
    """
    summary: str
    steps: list[CommandSequenceStep]
    response_type: Literal["message", "command", "ai_prompt", "error"] = "command"
    ai_prompt: str = ""
    provider: str = "agent"
    source: str = "recommended"
    need_confirm: bool = True
    aliases: dict[str, str] = {}  # 本次发现的项目别名

    @model_validator(mode='after')
    def _validate_response_type_constraints(self) -> 'AgentResult':
        """校验 response_type 与字段组合的约束关系。

        - message: steps 必须为空, need_confirm=False, ai_prompt=''
        - command: steps 不能全空（至少有一个命令）, ai_prompt=''
        - ai_prompt: steps 必须为空, ai_prompt 不能为空字符串, need_confirm=True
        """
        if self.response_type == 'message':
            if self.steps:
                raise ValueError("response_type='message' 时 steps 必须为空")
            if self.need_confirm:
                raise ValueError("response_type='message' 时 need_confirm 必须为 False")
            if self.ai_prompt:
                raise ValueError("response_type='message' 时 ai_prompt 必须为空字符串")
        elif self.response_type == 'command':
            if not self.steps:
                raise ValueError("response_type='command' 时 steps 不能为空（至少需要一个命令）")
            if not self.need_confirm:
                raise ValueError("response_type='command' 时 need_confirm 必须为 True（不变量 #48）")
            if self.ai_prompt:
                raise ValueError("response_type='command' 时 ai_prompt 必须为空字符串")
        elif self.response_type == 'ai_prompt':
            if self.steps:
                raise ValueError("response_type='ai_prompt' 时 steps 必须为空")
            if not self.ai_prompt:
                raise ValueError("response_type='ai_prompt' 时 ai_prompt 不能为空字符串")
            if not self.need_confirm:
                raise ValueError("response_type='ai_prompt' 时 need_confirm 必须为 True")
        return self


class ResultDelivered(Exception):
    """deliver_result 工具触发的异常，携带 AgentResult + usage 统计。

    模型调用 deliver_result 工具时抛出此异常，run_agent() 捕获后构建 AgentRunOutcome。
    """
    def __init__(self, result: AgentResult, usage: 'RunUsage'):
        self.result = result
        self.usage = usage
        super().__init__(f"ResultDelivered: {result.response_type} - {result.summary[:50]}")


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
    tool_call_fn: Optional[Callable[[str, dict], Awaitable[dict]]] = None  # B093: 动态工具调用回调 (tool_name, arguments) -> dict
    dynamic_tools: list[dict] = field(default_factory=list)  # B093: 可用动态工具目录（仅用于 prompt 注入兼容）
    project_aliases: dict[str, str] = field(default_factory=dict)  # 已知项目别名
    usage: Optional[RunUsage] = None  # B105: usage 累积对象，由 run_agent() 传入
    on_model_text: Optional[Callable[[str], Awaitable[None]]] = None  # B106: 模型中间文本输出回调


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

SYSTEM_PROMPT = """你是终端侧 Claude Code 预处理助手。你的核心职责是帮助用户准备好在终端上使用 Claude Code 完成编程任务。

# 核心定位
你是 Claude Code 的"前台"，帮助用户：
1. 探索远端设备的项目结构和技术栈
2. 组装高质量的 prompt 或命令，交付给 Claude Code 执行
3. 回答 AI 编程相关的知识问答

# 结果交付方式（强制）
你必须在每次回复中调用 deliver_result 工具来交付最终结果。无论用户说了什么（问候、提问、请求命令），你都必须调用 deliver_result。
- 简单问候 → deliver_result(response_type='message', summary='回复内容')
- 知识问答 → deliver_result(response_type='message', summary='答案')
- 危险请求 → deliver_result(response_type='message', summary='拒绝说明')
- 编程请求 → 根据情况选择 command 或 ai_prompt
不要只回复文本而不调用 deliver_result，否则结果无法传递。

# response_type 选择规则（三选一，互斥）
- **response_type='command'**：用户要求执行终端操作（默认选择）
  - 启动工具（Claude Code → claude，其他工具按名称）
  - 终端命令（git、ls、find、cd、cat、grep、build、install、test、mkdir 等）
  - 用户说"用 Claude Code 做 X"→ 生成 claude 命令（如 claude -p "做 X"）
  - 所有涉及工具启动或命令执行的场景都用 command
- **response_type='ai_prompt'**：仅当用户原话明确说"注入 prompt""发送 prompt""给 Claude Code 写 prompt"时使用
  - 不包含"用 Claude Code 做 X"——那属于 command 类型
  - 不包含"让 Claude Code 执行"——那也属于 command 类型
  - 只有用户要求你编写一段 prompt 文本注入运行中的 Claude Code 时才用
- **response_type='message'**：纯信息型回复（不需要任何终端操作）
  - 知识问答、概念解释、使用建议
  - 超出范围的请求说明
  - need_confirm 必须为 False

# ai_prompt 质量标准（response_type='ai_prompt' 时）
一个好的 ai_prompt 应包含：
1. **项目路径**：明确指定工作目录
2. **相关文件**：列出需要关注的文件路径
3. **具体任务**：清晰描述要完成什么
4. **约束条件**：需要遵守的规范（如测试框架、代码风格）
5. **上下文**：之前讨论中达成的共识

示例：
"在 /Users/dev/my-project 目录下，查看 src/auth.py 和 tests/test_auth.py，重构认证模块：
- 将 JWT 验证逻辑提取为独立的 auth_validator.py
- 添加 token 刷新功能
- 保持现有测试通过
- 使用 pytest 运行测试验证"

# Claude Code 使用指导
你可以帮助用户了解如何更好地使用 Claude Code：
- 推荐命令：用 `which claude` 验证工具是否可用
- 项目导航：用 execute_command 探索项目结构
- 知识查询：用 lookup_knowledge 获取 Claude Code 使用技巧
- 如果远端设备有动态扩展工具可用，可以直接调用对应工具名

# 工具使用优先级
1. **execute_command**：探索远端设备（目录、文件、项目结构）
2. **lookup_knowledge**：获取 AI 编程技巧和项目知识
3. **动态扩展工具**：按名称调用远端设备上注册的扩展工具（如 MCP 技能）
4. **deliver_result**：准备好结果时调用，完成本次交互
5. **ask_user**：仅在需要澄清用户模糊意图时使用，不要主动追问 Claude Code 是否在运行

# AI 编程工具映射
- "Claude Code" / "Claude" / "用 Claude" / "claude code" → 命令 `claude`
- "Codex CLI" / "Codex" / "用 Codex" / "codex" → 仅知识说明（info-only），**不生成 `codex` 执行命令**

# lookup_knowledge 降级规则
- lookup_knowledge 不可用（工具未注册）：忽略，继续正常处理
- lookup_knowledge 返回空/未命中：在 summary 中说明，不阻塞命令生成
- 禁止在 lookup_knowledge 不可用时自行编造知识内容

# 动态扩展工具降级规则
- 扩展工具不可用（远端设备无注册工具）：忽略，继续正常处理
- 扩展工具返回错误：在 summary 中说明，不阻塞命令生成

# 探索规范
- 推荐命令：ls、find、cat、pwd、git remote/status/log、which
- 每次只执行一个命令，分析输出后再决定下一步
- 先从大范围探索（ls ~）逐步缩小到具体项目

# 项目别名
发现项目目录时，在 aliases 字段中记录路径和名称映射。

# 限制
- execute_command 工具只能执行只读命令（用于探索环境）
- 但你可以通过 deliver_result(response_type='command') 建议任何命令让用户确认执行（包括写、安装、构建等）
- 只有超出安全边界的请求（如 rm -rf /、sudo、访问敏感路径）才用 message 类型拒绝
- 不要将你的思考过程展示给用户，只展示对用户有用的信息
- 当用户要求执行某个操作（如 ls、git status）时，直接通过 deliver_result(response_type='command') 生成命令
- 不要先用 execute_command 执行用户要求的操作再返回 message——那是你自己探索时才做的事
- execute_command 仅用于你需要主动了解环境时（如检查项目结构、查看文件内容）
"""  # noqa: E501


# ---------------------------------------------------------------------------
# Built-in tool implementations（纯函数，不绑定到特定 Agent 实例）
# ---------------------------------------------------------------------------

async def _tool_execute_command(
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


async def _tool_ask_user(
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


async def _tool_lookup_knowledge(
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


async def _tool_deliver_result(
    ctx: RunContext[AgentDeps],
    response_type: Literal["message", "command", "ai_prompt", "error"],
    summary: str,
    steps: list[dict] | None = None,
    ai_prompt: str = "",
    provider: str = "agent",
    source: str = "recommended",
    need_confirm: bool = True,
    aliases: dict[str, str] | None = None,
) -> str:
    """交付 Agent 处理结果。当你完成与用户的讨论，需要返回最终结果时调用此工具。

    通过 response_type 区分三种语义：
    - 'command': 命令序列（steps 含可执行 shell 命令，需用户确认）
    - 'message': 纯信息型回复（steps=[], 无需确认）
    - 'ai_prompt': AI prompt 注入（steps=[], ai_prompt 含完整 prompt, 需用户确认）

    Args:
        response_type: 结果类型，可选 'command'、'message'、'ai_prompt'
        summary: 结果摘要
        steps: 命令步骤列表，每项含 id/label/command。message 和 ai_prompt 类型必须为空列表
        ai_prompt: AI prompt 文本，仅 ai_prompt 类型使用
        provider: 提供者标识，默认 'agent'
        source: 来源标识，默认 'recommended'
        need_confirm: 是否需要用户确认，message 类型必须为 False
        aliases: 项目别名映射
    """
    try:
        parsed_steps = [
            CommandSequenceStep(**step) for step in (steps or [])
        ]
        agent_result = AgentResult(
            summary=summary,
            steps=parsed_steps,
            response_type=response_type,
            ai_prompt=ai_prompt,
            provider=provider,
            source=source,
            need_confirm=need_confirm,
            aliases=aliases or {},
        )
    except Exception as e:
        logger.warning("deliver_result 参数校验失败: %s", e)
        return f"交付失败：参数校验错误 - {e}"

    # 从 deps 读取累积的 usage
    usage = ctx.deps.usage if ctx.deps.usage is not None else RunUsage()

    raise ResultDelivered(result=agent_result, usage=usage)


# ---------------------------------------------------------------------------
# Agent Factory（Session-scoped）
# ---------------------------------------------------------------------------

def _register_builtin_tools(agent: Agent[AgentDeps, str]) -> None:
    """在 Agent 实例上注册内置工具。"""
    agent.tool(_tool_execute_command)
    agent.tool(_tool_ask_user)
    agent.tool(_tool_deliver_result)


def _register_lookup_knowledge(agent: Agent[AgentDeps, str]) -> None:
    """条件注册 lookup_knowledge 工具（仅当 Agent 支持时）。"""
    agent.tool(_tool_lookup_knowledge)


# ---------------------------------------------------------------------------
# JSON Schema → Pydantic model 转换（用于动态工具参数签名）
# ---------------------------------------------------------------------------

_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _json_schema_to_fields(schema: dict) -> dict:
    """将 JSON Schema properties 转为 create_model 字段定义。

    仅处理顶层 properties 中的简单类型。
    嵌套 object/array 使用 dict/list fallback。
    """
    fields = {}
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    for name, prop in props.items():
        prop_type = prop.get("type", "string")
        python_type = _TYPE_MAP.get(prop_type, str)
        if name in required:
            fields[name] = (python_type, ...)
        else:
            fields[name] = (python_type, None)
    return fields


def _register_dynamic_tool(
    agent: Agent[AgentDeps, str],
    tool_info: dict,
) -> None:
    """将一个动态工具注册为独立的 Pydantic AI tool。

    从 tool_info.parameters JSON Schema 创建动态 Pydantic model，
    作为工具参数的类型签名，让模型感知 per-tool 参数结构。
    创建失败时 fallback 到泛泛的 arguments: dict。

    Args:
        agent: 目标 Agent 实例
        tool_info: 工具信息 {"name", "description", "parameters", ...}
    """
    tool_name = tool_info.get("name", "unknown")
    tool_description = tool_info.get("description", "")
    parameters = tool_info.get("parameters", {})

    # 从 JSON Schema 创建动态参数 model
    param_model = None
    if parameters and isinstance(parameters, dict) and parameters.get("properties"):
        try:
            fields = _json_schema_to_fields(parameters)
            model_name = f'{tool_name.replace(".", "_")}_params'
            param_model = create_model(
                model_name,
                __config__=ConfigDict(extra="allow"),
                **fields,
            )
        except Exception:
            logger.warning("动态工具 %s 参数 model 创建失败，使用 dict fallback", tool_name)
            param_model = None

    def _make_dynamic_tool(name: str, desc: str, pmodel: type[BaseModel] | None):
        if pmodel is not None:
            async def _dynamic_tool(
                ctx: RunContext[AgentDeps],
                arguments: pmodel,  # type: ignore[valid-type]
            ) -> str:
                """动态工具（带参数 schema）。"""
                return await call_dynamic_tool(ctx, name, arguments.model_dump())
        else:
            async def _dynamic_tool(
                ctx: RunContext[AgentDeps],
                arguments: dict,
            ) -> str:
                """动态工具（无 schema fallback）。"""
                return await call_dynamic_tool(ctx, name, arguments)

        _dynamic_tool.__name__ = name.replace(".", "_")
        _dynamic_tool.__qualname__ = f"dynamic_{name.replace('.', '_')}"
        _dynamic_tool.__doc__ = desc or f"调用远端动态工具 {name}。"
        return _dynamic_tool

    tool_fn = _make_dynamic_tool(tool_name, tool_description, param_model)
    agent.tool(name=tool_name, description=tool_description or f"动态工具 {tool_name}")(tool_fn)


def build_session_agent(
    dynamic_tools: list[dict] | None = None,
    include_lookup_knowledge: bool = True,
) -> Agent[AgentDeps, str]:
    """构建 session-scoped Agent 实例。

    每次会话创建独立 Agent，动态工具注册为真实 Pydantic AI tool。
    不修改任何全局状态。

    B105: output_type=str 允许模型自由文本回复，通过 deliver_result 工具交付结构化结果。

    Args:
        dynamic_tools: 已验证的动态工具列表
        include_lookup_knowledge: 是否注册 lookup_knowledge 工具

    Returns:
        配置好工具的 Agent 实例
    """
    agent = Agent(
        model=_build_model(),
        deps_type=AgentDeps,
        output_type=str,
        system_prompt=SYSTEM_PROMPT,
        retries=3,
    )

    # 注册内置工具
    _register_builtin_tools(agent)

    # 条件注册 lookup_knowledge
    if include_lookup_knowledge:
        _register_lookup_knowledge(agent)

    # 注册动态工具
    for tool_info in (dynamic_tools or []):
        _register_dynamic_tool(agent, tool_info)

    return agent


# ---------------------------------------------------------------------------
# 全局 terminal_agent（仅用于无动态工具的兼容场景 / 测试）
# ---------------------------------------------------------------------------

terminal_agent = Agent(
    model=_build_model(),
    deps_type=AgentDeps,
    output_type=str,
    system_prompt=SYSTEM_PROMPT,
    retries=3,
)

# 在全局 Agent 上注册所有内置工具
terminal_agent.tool(_tool_execute_command)
terminal_agent.tool(_tool_ask_user)
terminal_agent.tool(_tool_lookup_knowledge)
terminal_agent.tool(_tool_deliver_result)


# 保留旧名称兼容（测试直接 import 这些函数名）
execute_command = _tool_execute_command
ask_user = _tool_ask_user
lookup_knowledge = _tool_lookup_knowledge
deliver_result = _tool_deliver_result


# ---------------------------------------------------------------------------
# 通用动态工具调用函数（用于测试 + 未通过 factory 注册时的 fallback）
# ---------------------------------------------------------------------------

async def call_dynamic_tool(
    ctx: RunContext[AgentDeps],
    tool_name: str,
    arguments: dict,
) -> str:
    """调用远端设备上的动态扩展工具（通用版）。

    用于 session-scoped factory 的动态注册工具内部实现，
    以及测试中直接调用的场景。

    Args:
        ctx: Pydantic AI RunContext
        tool_name: 动态工具名称（namespaced 格式：skill.tool）
        arguments: 工具参数
    """
    if ctx.deps.tool_call_fn is None:
        return "错误：动态工具不可用（远端设备未注册扩展工具）"
    try:
        result = await ctx.deps.tool_call_fn(tool_name, arguments)
        if result.get("status") == "error":
            return f"工具调用失败：{result.get('error', '未知错误')}"
        return result.get("result", "")
    except Exception as e:
        logger.warning("call_dynamic_tool error: %s", e)
        return f"错误：动态工具调用失败 - {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# 动态工具校验（Finding 2: Server-side snapshot validation）
# ---------------------------------------------------------------------------

# 校验常量
MAX_TOOLS_PER_SNAPSHOT = 50
MAX_DESCRIPTION_LENGTH = 500
MAX_SCHEMA_SIZE = 4096  # 4KB
MAX_SNAPSHOT_SIZE = 256 * 1024  # 256KB
ALLOWED_CAPABILITIES = {"read_only", "info_only"}


def validate_tool_catalog(tools: list[dict]) -> list[dict]:
    """校验 Agent 上报的工具目录，返回过滤后的合法工具列表。

    校验规则（对应 B093 AC #786-790）：
    - 最多 MAX_TOOLS_PER_SNAPSHOT 个工具
    - description 超过 MAX_DESCRIPTION_LENGTH 截断
    - parameters schema 超过 MAX_SCHEMA_SIZE 忽略该工具
    - capability 不在 ALLOWED_CAPABILITIES 中则拒绝该工具
    - name 必须是 namespaced 格式（含 .）
    - parameters 必须是合法 dict（如果存在）

    Args:
        tools: Agent 上报的原始工具列表

    Returns:
        校验通过的工具列表（空列表如果 snapshot 超过 MAX_SNAPSHOT_SIZE）
    """
    # Snapshot 级 256KB 边界校验（按 UTF-8 字节数）
    try:
        snapshot_bytes = len(json.dumps(tools).encode("utf-8"))
        if snapshot_bytes > MAX_SNAPSHOT_SIZE:
            logger.warning(
                "Tool catalog snapshot 超过 %d 字节（实际 %d），拒绝整个 snapshot",
                MAX_SNAPSHOT_SIZE, snapshot_bytes,
            )
            return []
    except (TypeError, ValueError):
        logger.warning("Tool catalog snapshot 序列化失败，拒绝")
        return []

    validated = []
    for i, tool in enumerate(tools):
        if len(validated) >= MAX_TOOLS_PER_SNAPSHOT:
            logger.warning(
                "Tool catalog 超过 %d 上限，截断剩余工具",
                MAX_TOOLS_PER_SNAPSHOT,
            )
            break

        name = tool.get("name", "")
        kind = tool.get("kind", "dynamic")

        # namespaced 校验（仅 dynamic 类型）
        if kind == "dynamic" and "." not in name:
            logger.warning("工具 '%s' 缺少 namespace 前缀，忽略", name)
            continue

        # skill 字段校验（仅 dynamic 类型）
        if kind == "dynamic":
            skill = tool.get("skill")
            if not skill or not isinstance(skill, str):
                logger.warning("工具 '%s' 缺少 skill 字段，忽略", name)
                continue

        # capability 校验
        capability = tool.get("capability", "read_only")
        if capability not in ALLOWED_CAPABILITIES:
            logger.warning(
                "工具 '%s' capability='%s' 不在允许列表 %s，忽略",
                name, capability, ALLOWED_CAPABILITIES,
            )
            continue

        # parameters 校验（所有工具必填，且必须是合法 JSON Schema）
        parameters = tool.get("parameters")
        if parameters is None:
            logger.warning("工具 '%s' 缺少 parameters，忽略", name)
            continue
        if not isinstance(parameters, dict):
            logger.warning("工具 '%s' parameters 不是 dict，忽略", name)
            continue
        # JSON Schema 基本合法性
        if not any(k in parameters for k in ("type", "properties", "$schema")):
            logger.warning("工具 '%s' parameters 不是合法 JSON Schema，忽略", name)
            continue
        try:
            schema_size = len(json.dumps(parameters).encode("utf-8"))
            if schema_size > MAX_SCHEMA_SIZE:
                logger.warning(
                    "工具 '%s' schema 超过 %d 字节，忽略",
                    name, MAX_SCHEMA_SIZE,
                )
                continue
        except (TypeError, ValueError):
            logger.warning("工具 '%s' schema 序列化失败，忽略", name)
            continue

        # description 截断
        description = tool.get("description", "")
        if len(description) > MAX_DESCRIPTION_LENGTH:
            tool = {**tool, "description": description[:MAX_DESCRIPTION_LENGTH]}
            logger.info("工具 '%s' description 截断至 %d 字符", name, MAX_DESCRIPTION_LENGTH)

        validated.append(tool)

    return validated


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
    tool_call_fn: Callable[[str, dict], Awaitable[dict]] | None = None,
    dynamic_tools: list[dict] | None = None,
    include_lookup_knowledge: bool = True,
    on_model_text: Callable[[str], Awaitable[None]] | None = None,
) -> AgentRunOutcome:
    """运行 Agent 处理用户意图。

    B105 变更：Agent output_type=str，模型自由文本回复。
    通过 deliver_result 工具交付结构化结果（ResultDelivered 异常）。
    usage 通过 RunUsage 对象传入 agent.run()，逐轮累积。

    Args:
        intent: 用户的意图描述
        session_id: Agent WS session ID
        execute_command_fn: 执行命令的回调 (session_id, command, cwd) -> ExecuteCommandResult
        ask_user_fn: 向用户提问的回调 (question, options, multi_select) -> str
        project_aliases: 已知项目别名
        message_history: 对话历史（用于多轮）
        lookup_knowledge_fn: 知识检索回调 (query) -> str，可选
        tool_call_fn: 动态工具调用回调 (tool_name, arguments) -> dict，可选
        dynamic_tools: 已验证的动态工具目录，可选
        include_lookup_knowledge: 是否注册 lookup_knowledge（基于 Agent 版本）
        on_model_text: 模型中间文本输出回调 (text) -> None，可选

    Returns:
        AgentRunOutcome 包含 AgentResult + token usage 统计
    """
    # 创建 RunUsage 对象用于累积 token 用量
    # 传入 agent.run() 后会在 ReAct 循环中逐轮累积
    usage_tracker = RunUsage()

    deps = AgentDeps(
        session_id=session_id,
        execute_command_fn=execute_command_fn,
        ask_user_fn=ask_user_fn,
        lookup_knowledge_fn=lookup_knowledge_fn,
        tool_call_fn=tool_call_fn,
        dynamic_tools=dynamic_tools or [],
        project_aliases=project_aliases or {},
        usage=usage_tracker,
        on_model_text=on_model_text,
    )

    # Session-scoped Agent factory：为每个会话创建独立 Agent
    agent = build_session_agent(
        dynamic_tools=dynamic_tools,
        include_lookup_knowledge=include_lookup_knowledge,
    )

    if not planner_api_key():
        raise AgentUserFacingError("智能服务 Token 未配置，请联系开发者")

    # 最多重试 2 次（含首次，共 3 次尝试），仅对 LLM 调用错误重试
    # 重试间 usage_tracker 不重置，保留之前累积的 token 用量
    max_attempts = 3
    retry_hint = None

    # B106: 构建 event_stream_handler 用于捕获模型中间文本输出
    # 通过 PartStartEvent/PartDeltaEvent 捕获 TextPart，累积完整文本后回调 on_model_text
    _current_text_parts: dict[int, str] = {}  # part_index -> accumulated text (only for TextPart)

    async def _event_stream_handler(ctx, events):
        """处理模型流式事件，捕获文本输出并回调 on_model_text。

        关键设计：只有 PartStartEvent.part 是 TextPart 时才追踪。
        同 index 新的 PartStartEvent（非 TextPart，如 ToolCallPart）会替换旧追踪，
        防止被替换的临时文本泄漏到 assistant_message（不变量 #50）。
        """
        nonlocal _current_text_parts
        if on_model_text is None:
            return
        async for event in events:
            from pydantic_ai.messages import PartStartEvent, PartDeltaEvent, PartEndEvent, TextPart, TextPartDelta
            if isinstance(event, PartStartEvent):
                if isinstance(event.part, TextPart):
                    text = event.part.content
                    _current_text_parts[event.index] = text or ""
                else:
                    # 同 index 非文本 Part 替换了旧的 TextPart，清除旧追踪
                    _current_text_parts.pop(event.index, None)
            elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                if event.index in _current_text_parts:
                    _current_text_parts[event.index] += event.delta.content_delta
            elif isinstance(event, PartEndEvent):
                # 只有仍然在追踪中的文本 part（未被同 index 非 TextPart 替换）才发送
                accumulated = _current_text_parts.pop(event.index, None)
                if accumulated and accumulated.strip():
                    try:
                        await on_model_text(accumulated.strip())
                    except Exception:
                        logger.debug("on_model_text callback error", exc_info=True)

    _stream_handler = _event_stream_handler if on_model_text else None

    for attempt in range(1, max_attempts + 1):
        try:
            run_result = await agent.run(
                user_prompt=intent if retry_hint is None else f"{intent}\n\n{retry_hint}",
                deps=deps,
                message_history=message_history,
                usage=usage_tracker,
                event_stream_handler=_stream_handler,
            )
            # 模型正常结束但没调用 deliver_result（协议违约）
            # 给一次重试机会（清空文本追踪，避免重复 assistant_message 气泡）
            if attempt < max_attempts:
                logger.warning(
                    "Agent completed without deliver_result (attempt %d), retrying with hint",
                    attempt,
                )
                _current_text_parts.clear()  # 清空前一次文本追踪，防止重复气泡
                retry_hint = "注意：你上次回复没有调用 deliver_result 工具交付结果。请确保在回复中调用 deliver_result 工具来交付最终结果。"
                continue

            # 重试后仍失败，返回 error fallback
            logger.warning("Agent completed without deliver_result after retry, returning error fallback")
            usage = run_result.usage()
            fallback_result = AgentResult(
                summary="Agent 未能交付结构化结果，请重试",
                steps=[],
                response_type="error",
                need_confirm=False,
            )
            return AgentRunOutcome(
                result=fallback_result,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
                requests=usage.requests,
                model_name=planner_model(),
            )
        except ResultDelivered as rd:
            # deliver_result 工具成功交付，携带结构化结果 + usage
            usage = rd.usage if rd.usage is not None else usage_tracker
            return AgentRunOutcome(
                result=rd.result,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
                requests=usage.requests,
                model_name=planner_model(),
            )
        except pai_exc.UnexpectedModelBehavior as e:
            if attempt < max_attempts:
                logger.warning(
                    "Agent model behavior error (attempt %d/%d), retrying: %s",
                    attempt, max_attempts, e,
                )
                retry_hint = "注意：上次调用出现了格式问题。请确保正确调用 deliver_result 工具来交付结果。"
                continue
            logger.warning("Agent model error after %d attempts: %s", max_attempts, e)
            raise AgentUserFacingError(_user_facing_model_error_message(e)) from e
        except pai_exc.ModelHTTPError as e:
            logger.warning("Agent model HTTP error: %s", e)
            raise AgentUserFacingError(_user_facing_model_error_message(e)) from e
        except Exception as e:
            logger.error("Agent run unexpected error: %s: %s", type(e).__name__, e)
            raise
