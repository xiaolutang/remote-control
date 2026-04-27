"""
Runtime API Pydantic schemas.

所有 Pydantic Model 集中定义，供路由文件和测试共享。
"""
from typing import Any, Optional

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
