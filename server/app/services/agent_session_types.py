"""
B080: Agent 会话类型定义 & SSE 事件辅助。

从 agent_session_manager.py 拆分出的类型/常量/辅助函数模块。

架构约束：
- 不变量 #60: Agent SSE 采用阶段驱动模型，6 种事件类型：
  session_created, phase_change, streaming_text, tool_step, question, result, error
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# B103: SSE 事件类型定义（不变量 #60）
# ---------------------------------------------------------------------------

# 7 种合法 SSE 事件类型
SSE_EVENT_TYPES = frozenset({
    "session_created",   # 由 runtime_api.py SSE 端点产生
    "phase_change",      # 阶段切换（B104 填充）
    "streaming_text",    # 逐 token 文本推送（B105 填充）
    "tool_step",         # 工具调用步骤（B106 填充）
    "question",          # Agent 向用户提问
    "result",            # Agent 最终结果
    "error",             # 错误事件
})

# tool_step 事件中 status 字段的合法值
TOOL_STEP_STATUSES = frozenset({"running", "done", "error"})

# B104: Phase 常量定义
PHASE_THINKING = "THINKING"        # Agent 启动，正在分析意图
PHASE_EXPLORING = "EXPLORING"      # 正在执行工具/命令探索环境
PHASE_ANALYZING = "ANALYZING"      # 正在分析工具执行结果
PHASE_CONFIRMING = "CONFIRMING"    # 等待用户确认（ask_user 工具）
PHASE_RESPONDING = "RESPONDING"    # 正在生成回复（文本输出）
PHASE_RESULT = "RESULT"            # 完成，已交付结果

# Phase 描述映射
_PHASE_DESCRIPTIONS: dict[str, str] = {
    PHASE_THINKING: "正在分析你的意图...",
    PHASE_EXPLORING: "正在探索环境...",
    PHASE_ANALYZING: "正在分析结果...",
    PHASE_CONFIRMING: "等待确认...",
    PHASE_RESPONDING: "正在生成回复...",
    PHASE_RESULT: "完成",
}

# tool_step 事件中命令输出预览的最大字符数
_MAX_TOOL_STEP_PREVIEW = 1000
_MAX_TOOL_STEP_ERROR_PREVIEW = 200

# ---------------------------------------------------------------------------
# 会话超时 & 频率限制常量
# ---------------------------------------------------------------------------

SESSION_TIMEOUT_SECONDS = 600       # 10 分钟无交互超时
SSE_KEEPALIVE_SECONDS = 15          # SSE keepalive 间隔
MAX_CACHED_EVENTS = 100             # 断连恢复缓存最近事件数
CLEANUP_INTERVAL_SECONDS = 30       # 超时清理检查间隔

# 频率限制
USER_SESSION_RATE_LIMIT = 5         # 每用户最多同时进行的会话数
USER_SESSION_RATE_WINDOW = 60       # 频率限制窗口（秒）


# ---------------------------------------------------------------------------
# 错误码定义
# ---------------------------------------------------------------------------

class ErrorCode:
    """6 种明确错误码。"""
    AGENT_OFFLINE = "AGENT_OFFLINE"             # Agent 设备离线
    SESSION_EXPIRED = "SESSION_EXPIRED"         # 会话超时
    SESSION_CANCELLED = "SESSION_CANCELLED"     # 会话被用户取消
    AGENT_ERROR = "AGENT_ERROR"                 # Agent 运行出错
    RATE_LIMITED = "RATE_LIMITED"               # 频率超限
    INTERNAL_ERROR = "INTERNAL_ERROR"           # 内部错误


# ---------------------------------------------------------------------------
# 状态枚举
# ---------------------------------------------------------------------------

class AgentSessionState(str, Enum):
    """Agent 会话状态。"""
    EXPLORING = "exploring"      # Agent 正在执行探索命令
    ASKING = "asking"            # Agent 等待用户回复
    COMPLETED = "completed"      # Agent 完成，有结果
    ERROR = "error"              # Agent 出错
    EXPIRED = "expired"          # 会话超时
    CANCELLED = "cancelled"      # 用户取消
    INACTIVE = "inactive"        # 终端非删除关闭，session 暂停


# ---------------------------------------------------------------------------
# SSE 事件数据类
# ---------------------------------------------------------------------------

@dataclass
class QuestionEvent:
    """Agent 向用户提问。"""
    question: str
    options: list[str]
    multi_select: bool


@dataclass
class ResultEvent:
    """Agent 最终结果。"""
    summary: str
    steps: list[dict]       # CommandSequenceStep as dict
    provider: str
    source: str
    need_confirm: bool
    aliases: dict[str, str]
    usage: Optional[dict[str, Any]] = None


@dataclass
class ErrorEventData:
    """错误事件数据。"""
    code: str               # ErrorCode 中的值
    message: str


# ---------------------------------------------------------------------------
# B103: 新 SSE 事件类型辅助函数（框架，具体逻辑由 B104/B105/B106 填充）
# ---------------------------------------------------------------------------

def _phase_change_event(phase: str, description: str = "") -> dict[str, Any]:
    """构造 phase_change 事件数据。"""
    return {"phase": phase, "description": description}


def _streaming_text_event(text_delta: str) -> dict[str, Any]:
    """构造 streaming_text 事件数据。"""
    return {"text_delta": text_delta}


def _tool_step_event(
    tool_name: str,
    description: str = "",
    status: str = "running",
    result_summary: str = "",
    *,
    command: str = "",
) -> dict[str, Any]:
    """构造 tool_step 事件数据。"""
    if status not in TOOL_STEP_STATUSES:
        status = "running"
    payload: dict[str, Any] = {
        "tool_name": tool_name,
        "description": description,
        "status": status,
        "result_summary": result_summary,
    }
    if command:
        payload["command"] = command
    return payload


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class AgentSessionExpired(Exception):
    """会话超时异常。"""
    pass


class AgentSessionCancelled(Exception):
    """会话取消异常。"""
    pass


class AgentSessionRateLimited(Exception):
    """频率超限异常。"""
    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(f"Rate limited, retry after {retry_after}s")


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _error_event_dict(code: str, message: str) -> dict:
    """构造错误事件字典。"""
    return {
        "code": code,
        "message": message,
    }
