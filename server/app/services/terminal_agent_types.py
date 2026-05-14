"""
B079/B089/B105: Pydantic AI ReAct 智能体 — 类型定义与异常。

从 terminal_agent.py 拆分出的子模块，包含：
- 异常类：AgentUserFacingError, AgentNoDeliveryError
- 错误消息生成：_user_facing_model_error_message
- 结果类型：CommandSequenceStep, AgentResult, ResultDelivered, AgentRunOutcome
- 依赖容器：AgentDeps
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal, Optional

from pydantic import BaseModel, model_validator
try:
    from pydantic_ai import RunUsage
except ImportError:
    from pydantic_ai.usage import Usage as RunUsage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# pydantic_ai 版本兼容 helper
# ---------------------------------------------------------------------------

def _extract_input_tokens(usage) -> int:
    """从 RunUsage 提取 input token 数（兼容新旧字段名）。"""
    if hasattr(usage, 'input_tokens'):
        return usage.input_tokens
    return getattr(usage, 'request_tokens', 0)


def _extract_output_tokens(usage) -> int:
    """从 RunUsage 提取 output token 数（兼容新旧字段名）。"""
    if hasattr(usage, 'output_tokens'):
        return usage.output_tokens
    return getattr(usage, 'response_tokens', 0)


# ---------------------------------------------------------------------------
# 异常类
# ---------------------------------------------------------------------------

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

    S001: 调度字段（仅 command 类型允许）：
      - schedule_at: 带时区的 ISO 8601 字符串，如 "2026-06-01T08:00:00+08:00"
      - repeat_type: "once" 或 "daily"，必须与 schedule_at 同时存在或同时为空
    """
    summary: str
    steps: list[CommandSequenceStep]
    response_type: Literal["message", "command", "ai_prompt", "error"] = "command"
    ai_prompt: str = ""
    provider: str = "agent"
    source: str = "recommended"
    need_confirm: bool = True
    aliases: dict[str, str] = {}  # 本次发现的项目别名
    schedule_at: Optional[str] = None  # S001: 带时区的 ISO 8601
    repeat_type: Optional[Literal["once", "daily"]] = None  # S001: once 或 daily

    @model_validator(mode='after')
    def _validate_response_type_constraints(self) -> 'AgentResult':
        """校验 response_type 与字段组合的约束关系。

        - message: steps 必须为空, need_confirm=False, ai_prompt='', 不允许调度字段
        - command: steps 不能全空（至少有一个命令）, ai_prompt='', 允许调度字段
        - ai_prompt: steps 必须为空, ai_prompt 不能为空字符串, need_confirm=True, 不允许调度字段

        S001 调度字段约束：
        - schedule_at 和 repeat_type 必须同时存在或同时为空
        - 仅 response_type=command 允许携带调度字段
        - schedule_at 必须包含时区偏移（+xx:xx / -xx:xx / Z）
        """
        if self.response_type == 'message':
            if self.steps:
                raise ValueError("response_type='message' 时 steps 必须为空")
            if self.need_confirm:
                raise ValueError("response_type='message' 时 need_confirm 必须为 False")
            if self.ai_prompt:
                raise ValueError("response_type='message' 时 ai_prompt 必须为空字符串")
            if self.schedule_at is not None or self.repeat_type is not None:
                raise ValueError("response_type='message' 不允许携带 schedule_at/repeat_type，仅 command 类型支持调度")
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
            if self.schedule_at is not None or self.repeat_type is not None:
                raise ValueError("response_type='ai_prompt' 不允许携带 schedule_at/repeat_type，仅 command 类型支持调度")

        # S001: 调度字段组合校验（所有 response_type 共用）
        has_schedule = self.schedule_at is not None
        has_repeat = self.repeat_type is not None
        if has_schedule and not has_repeat:
            raise ValueError("schedule_at 和 repeat_type 必须同时存在，缺少 repeat_type")
        if has_repeat and not has_schedule:
            raise ValueError("schedule_at 和 repeat_type 必须同时存在，缺少 schedule_at")

        # S001: schedule_at 时区校验
        if has_schedule and has_repeat:
            tz_pattern = r'.*[+-]\d{2}:\d{2}$|.*Z$'
            if not re.match(tz_pattern, self.schedule_at):
                raise ValueError("schedule_at 必须包含时区偏移（如 +08:00 或 Z）")

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

    @classmethod
    def from_usage(cls, result: AgentResult, usage, model_name: str = "") -> 'AgentRunOutcome':
        """从 RunUsage 对象构造 AgentRunOutcome（集中版本兼容逻辑）。"""
        return cls(
            result=result,
            input_tokens=_extract_input_tokens(usage),
            output_tokens=_extract_output_tokens(usage),
            total_tokens=usage.total_tokens,
            requests=usage.requests,
            model_name=model_name,
        )


# ---------------------------------------------------------------------------
# Agent Deps
# ---------------------------------------------------------------------------

# 前向引用类型（避免循环导入，仅在类型注解中使用）
_ExecuteCommandResult = object  # placeholder for ExecuteCommandResult


@dataclass
class AgentDeps:
    """Agent 运行时依赖，由会话管理器注入。"""
    session_id: str  # Agent WS session_id
    execute_command_fn: Callable[[str, str, Optional[str]], Awaitable[object]]  # noqa: E501
    ask_user_fn: Callable[[str, list[str], bool], Awaitable[str]]
    lookup_knowledge_fn: Optional[Callable[[str], Awaitable[str]]] = None  # B089: 知识检索回调
    tool_call_fn: Optional[Callable[[str, dict], Awaitable[dict]]] = None  # B093: 动态工具调用回调 (tool_name, arguments) -> dict
    dynamic_tools: list[dict] = field(default_factory=list)  # B093: 可用动态工具目录（仅用于 prompt 注入兼容）
    project_aliases: dict[str, str] = field(default_factory=dict)  # 已知项目别名
    usage: Optional[RunUsage] = None  # B105: usage 累积对象，由 run_agent() 传入
    on_model_text: Optional[Callable[[str], Awaitable[None]]] = None  # B106: 模型中间文本输出回调
    list_scheduled_tasks_fn: Optional[Callable[[], Awaitable[list[dict]]]] = None  # B001: 查询当前终端定时任务回调
    cancel_scheduled_task_fn: Optional[Callable[[int], Awaitable[str]]] = None  # B001: 取消指定定时任务回调（返回成功/失败信息）
