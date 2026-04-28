"""
B080: AgentSession 数据类定义。

从 agent_session_manager.py 拆分出的会话数据模型。
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from app.services.terminal_agent import AgentResult
from app.services.agent_session_types import (
    AgentSessionState,
    MAX_CACHED_EVENTS,
)


@dataclass
class AgentSession:
    """单个 Agent 会话的完整状态。"""
    id: str
    intent: str
    device_id: str
    user_id: str
    state: AgentSessionState
    created_at: datetime
    last_active_at: datetime
    terminal_id: Optional[str] = None
    terminal_cwd: Optional[str] = None
    conversation_id: Optional[str] = None
    pending_question_id: Optional[str] = None
    message_history: Optional[list[Any]] = None
    result: Optional[AgentResult] = None

    # SSE 事件队列（用于流式推送）
    event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)

    # ask_user 回复 Future
    _pending_question_future: Optional[asyncio.Future] = field(default=None, repr=False)

    # Agent 运行 task
    _agent_task: Optional[asyncio.Task] = field(default=None, repr=False)

    # 断连恢复：缓存最近事件
    _last_events: list = field(default_factory=list)

    # 流引用计数（有多少个 SSE 连接在消费此会话）
    _stream_ref_count: int = field(default=0, repr=False)

    @property
    def max_cached_events(self) -> int:
        return MAX_CACHED_EVENTS
