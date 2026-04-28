"""
B079/B089/B105: Pydantic AI ReAct 智能体 — 工具注册与校验。

从 terminal_agent.py 拆分出的子模块，包含：
- 内置工具实现：_tool_execute_command, _tool_ask_user, _tool_lookup_knowledge, _tool_deliver_result
- 工具注册：_register_builtin_tools, _register_lookup_knowledge
- 动态工具：_json_schema_to_fields, _register_dynamic_tool, call_dynamic_tool
- 工具目录校验：validate_tool_catalog 及常量
"""
import json
import logging
from typing import Literal

from pydantic import ConfigDict, create_model
from pydantic_ai import Agent, RunContext, RunUsage

from app.infra.command_validator import validate_command
from app.services.terminal_agent_types import (
    AgentDeps,
    AgentResult,
    CommandSequenceStep,
    ResultDelivered,
)

logger = logging.getLogger(__name__)


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
    """交付 Agent 处理结果。仅在需要提交命令或 AI Prompt 时调用此工具。
    纯文本回复（问候、知识问答等）请直接输出文字，不要调用此工具。

    通过 response_type 区分两种语义：
    - 'command': 命令序列（steps 含可执行 shell 命令，需用户确认）
    - 'ai_prompt': AI prompt 注入（steps=[], ai_prompt 含完整 prompt, 需用户确认）

    Args:
        response_type: 结果类型，可选 'command'、'ai_prompt'
        summary: 结果摘要
        steps: 命令步骤列表，每项含 id/label/command。ai_prompt 类型必须为空列表
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
# Agent Factory 工具注册（Session-scoped）
# ---------------------------------------------------------------------------

def _register_builtin_tools(agent: Agent[AgentDeps, str]) -> None:
    """在 Agent 实例上注册内置工具。"""
    agent.tool(_tool_execute_command, name="execute_command")
    agent.tool(_tool_ask_user, name="ask_user")
    agent.tool(_tool_deliver_result, name="deliver_result")


def _register_lookup_knowledge(agent: Agent[AgentDeps, str]) -> None:
    """条件注册 lookup_knowledge 工具（仅当 Agent 支持时）。"""
    agent.tool(_tool_lookup_knowledge, name="lookup_knowledge")


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

    def _make_dynamic_tool(name: str, desc: str, pmodel: type | None):
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
