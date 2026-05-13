"""
Runtime API Pydantic schemas.

所有 Pydantic Model 集中定义，供路由文件和测试共享。
"""
from enum import StrEnum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Device
# ---------------------------------------------------------------------------


class RuntimeDeviceItem(BaseModel):
    device_id: str
    name: str
    owner: str
    agent_online: bool
    platform: str = ""
    hostname: str = ""
    last_heartbeat_at: Optional[str] = None
    max_terminals: int
    active_terminals: int


class RuntimeDeviceListResponse(BaseModel):
    devices: list[RuntimeDeviceItem]


class UpdateDeviceRequest(BaseModel):
    name: Optional[str] = None


# ---------------------------------------------------------------------------
# Terminal
# ---------------------------------------------------------------------------


class RuntimeTerminalItem(BaseModel):
    terminal_id: str
    title: str
    cwd: str
    command: str
    status: str
    updated_at: Optional[str] = None
    disconnect_reason: Optional[str] = None
    views: dict


class RuntimeTerminalListResponse(BaseModel):
    device_id: str
    device_online: bool
    terminals: list[RuntimeTerminalItem]


class CreateTerminalRequest(BaseModel):
    title: str
    cwd: str
    command: str
    env: dict = Field(default_factory=dict)
    terminal_id: str


class UpdateTerminalRequest(BaseModel):
    title: str


# ---------------------------------------------------------------------------
# Project Context
# ---------------------------------------------------------------------------


class ProjectContextCandidate(BaseModel):
    candidate_id: str
    device_id: str
    label: str
    cwd: str
    source: str
    tool_hints: list[str] = Field(default_factory=list)
    last_used_at: Optional[str] = None
    updated_at: Optional[str] = None
    requires_confirmation: bool = False


class DeviceProjectContextSnapshot(BaseModel):
    device_id: str
    generated_at: str
    candidates: list[ProjectContextCandidate]


class PinnedProjectItem(BaseModel):
    label: str
    cwd: str


class ApprovedScanRootItem(BaseModel):
    root_path: str
    scan_depth: int = 2
    enabled: bool = True


class PlannerRuntimeConfig(BaseModel):
    provider: str = "claude_cli"
    llm_enabled: bool = True
    endpoint_profile: str = "openai_compatible"
    credentials_mode: str = "client_secure_storage"
    requires_explicit_opt_in: bool = False


class ProjectContextSettingsResponse(BaseModel):
    device_id: str
    pinned_projects: list[PinnedProjectItem] = Field(default_factory=list)
    approved_scan_roots: list[ApprovedScanRootItem] = Field(default_factory=list)
    planner_config: PlannerRuntimeConfig = Field(default_factory=PlannerRuntimeConfig)


class UpdateProjectContextSettingsRequest(BaseModel):
    pinned_projects: list[PinnedProjectItem] = Field(default_factory=list)
    approved_scan_roots: list[ApprovedScanRootItem] = Field(default_factory=list)
    planner_config: PlannerRuntimeConfig = Field(default_factory=PlannerRuntimeConfig)


# ---------------------------------------------------------------------------
# Assistant
# ---------------------------------------------------------------------------


class AssistantFallbackPolicy(BaseModel):
    allow_claude_cli: bool = True
    allow_local_rules: bool = True


class AssistantPlanRequest(BaseModel):
    intent: str
    conversation_id: str
    message_id: str
    fallback_policy: AssistantFallbackPolicy = Field(default_factory=AssistantFallbackPolicy)


class AssistantMessageItem(BaseModel):
    type: str = "assistant"
    text: str


class AssistantTraceItem(BaseModel):
    stage: str
    title: str
    status: str
    summary: str


class AssistantCommandStep(BaseModel):
    id: str
    label: str
    command: str


class AssistantCommandSequence(BaseModel):
    summary: str
    provider: str
    source: str
    need_confirm: bool = True
    steps: list[AssistantCommandStep]


class AssistantPlanLimits(BaseModel):
    rate_limited: bool = False
    budget_blocked: bool = False
    provider_timeout_ms: int
    retry_after: Optional[int] = None


class AssistantPlanResponse(BaseModel):
    conversation_id: str
    message_id: str
    assistant_messages: list[AssistantMessageItem] = Field(default_factory=list)
    trace: list[AssistantTraceItem] = Field(default_factory=list)
    command_sequence: AssistantCommandSequence
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    limits: AssistantPlanLimits
    evaluation_context: dict = Field(default_factory=dict)


class AssistantExecutionReportRequest(BaseModel):
    conversation_id: str
    message_id: str
    terminal_id: Optional[str] = None
    execution_status: str
    failed_step_id: Optional[str] = None
    output_summary: Optional[str] = None
    command_sequence: dict


class AssistantExecutionReportResponse(BaseModel):
    acknowledged: bool
    memory_updated: bool
    evaluation_recorded: bool


# ---------------------------------------------------------------------------
# Agent Usage
# ---------------------------------------------------------------------------


class AgentUsageSummaryScope(BaseModel):
    total_sessions: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_requests: int = 0
    latest_model_name: str = ""


class AgentUsageSummaryResponse(BaseModel):
    device: AgentUsageSummaryScope
    terminal: Optional[AgentUsageSummaryScope] = None
    user: AgentUsageSummaryScope


# ---------------------------------------------------------------------------
# Agent Session
# ---------------------------------------------------------------------------


class AgentRunRequest(BaseModel):
    """Agent 运行请求。"""
    intent: str
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    client_event_id: Optional[str] = None
    truncate_after_index: Optional[int] = None


class AgentRespondRequest(BaseModel):
    """用户回复 Agent 问题。"""
    answer: str
    question_id: Optional[str] = None
    client_event_id: Optional[str] = None


class AgentExecutionReportRequest(BaseModel):
    """Agent 执行结果回写请求。"""
    success: bool
    executed_command: Optional[str] = None
    failure_step: Optional[str] = None


class AgentConversationEventItem(BaseModel):
    event_index: int
    event_id: str
    type: str
    role: str
    session_id: Optional[str] = None
    question_id: Optional[str] = None
    client_event_id: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None


class AgentConversationProjection(BaseModel):
    conversation_id: Optional[str] = None
    device_id: str
    terminal_id: str
    status: str
    next_event_index: int
    truncation_epoch: int = 0
    active_session_id: Optional[str] = None
    events: list[AgentConversationEventItem]


# ---------------------------------------------------------------------------
# Scheduled Task
# ---------------------------------------------------------------------------


class ScheduledTaskRepeatType(StrEnum):
    """定时任务重复类型。"""
    once = "once"
    daily = "daily"


class ScheduledTaskStatus(StrEnum):
    """定时任务状态。"""
    pending = "pending"
    executed = "executed"
    expired = "expired"
    cancelled = "cancelled"


class ScheduledTaskCreateRequest(BaseModel):
    """创建定时任务请求。"""
    session_id: str
    terminal_id: str
    text_content: str
    execute_at: str  # ISO 8601 datetime with timezone
    repeat_type: ScheduledTaskRepeatType = ScheduledTaskRepeatType.once


class ScheduledTaskCreateResponse(BaseModel):
    """创建定时任务响应。"""
    id: int
    session_id: str
    terminal_id: str
    text_content: str
    execute_at: str
    repeat_type: ScheduledTaskRepeatType
    status: ScheduledTaskStatus
    created_at: str  # ISO 8601


class ScheduledTaskItem(BaseModel):
    """定时任务列表条目。"""
    id: int
    session_id: str
    terminal_id: str
    text_content: str
    execute_at: str
    repeat_type: ScheduledTaskRepeatType
    status: ScheduledTaskStatus
    created_at: str  # ISO 8601
    executed_at: Optional[str] = None  # ISO 8601 or null


class ScheduledTaskListResponse(BaseModel):
    """定时任务列表响应。"""
    tasks: list[ScheduledTaskItem]


# ---------------------------------------------------------------------------
# User / Auth
# ---------------------------------------------------------------------------


class UserRegister(BaseModel):
    username: str
    password: Optional[str] = None
    password_encrypted: Optional[str] = None
    device_name: Optional[str] = None
    view: Optional[str] = None


class UserLogin(BaseModel):
    username: str
    password: Optional[str] = None  # 明文密码（兼容旧客户端）
    password_encrypted: Optional[str] = None  # RSA 加密后的密码（base64）
    view: Optional[str] = None


class DeviceInfo(BaseModel):
    device_name: str
    device_type: str = "mobile"  # mobile, tablet, desktop


class LoginResponse(BaseModel):
    success: bool
    message: str
    username: Optional[str] = None
    session_id: Optional[str] = None
    token: Optional[str] = None
    expires_at: Optional[str] = None
    refresh_token: Optional[str] = None
    refresh_expires_at: Optional[str] = None


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    success: bool
    access_token: str
    refresh_token: str
    expires_in: int  # 秒
    refresh_expires_in: int  # 秒
    token_type: str = "Bearer"


class DeviceListResponse(BaseModel):
    devices: list


class SessionStateResponse(BaseModel):
    """Session 状态响应模型 (CONTRACT-001)"""
    session_id: str
    owner: str
    agent_online: bool
    views: dict
    pty: dict
    updated_at: str


# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------


class LogEntry(BaseModel):
    """单条日志"""
    level: Literal["debug", "info", "warn", "error", "fatal"] = "info"
    message: str
    timestamp: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class UploadLogsRequest(BaseModel):
    """批量上报日志请求"""
    session_id: str = Field(..., description="会话 ID")
    uid: str = Field("", description="用户标识（username），未登录时为空")
    logs: List[LogEntry] = Field(..., description="日志列表")


class UploadLogsResponse(BaseModel):
    """批量上报日志响应"""
    success: bool = True
    received: int


class LogRecord(BaseModel):
    """日志记录"""
    level: str
    message: str
    timestamp: str
    metadata: Dict[str, Any] = {}


class GetLogsResponse(BaseModel):
    """查询日志响应"""
    session_id: str
    total: int
    offset: int
    limit: int
    logs: List[LogRecord]


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------


class FeedbackCreateRequest(BaseModel):
    """提交反馈请求"""
    session_id: Optional[str] = Field(None, description="会话 ID（旧字段，可选）")
    category: Literal["connection", "terminal", "crash", "suggestion", "other"] = Field(
        ..., description="反馈分类"
    )
    description: str = Field(
        ..., description="反馈描述", max_length=10000,
    )
    platform: Optional[str] = Field(None, description="平台信息")
    app_version: Optional[str] = Field(None, description="应用版本")
    # B052 新增字段
    terminal_id: Optional[str] = Field(None, description="终端 ID")
    result_event_id: Optional[str] = Field(None, description="关联的 result 事件 ID")
    feedback_type: Optional[Literal["helpful", "needs_improvement", "error_report"]] = Field(
        None, description="反馈类型"
    )
    device_id: Optional[str] = Field(None, description="设备 ID（用于 SSE 实时推送）")


class FeedbackResponse(BaseModel):
    """反馈响应"""
    feedback_id: str
    created_at: str


class FeedbackDetailResponse(BaseModel):
    """反馈详情响应"""
    feedback_id: str
    user_id: str
    session_id: str
    category: str
    description: str
    platform: str = ""
    app_version: str = ""
    created_at: str
    logs: List[Dict[str, Any]] = []
