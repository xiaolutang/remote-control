"""
Runtime API — 路由聚合入口。

将各子域路由统一 include 到一个 router 下，
对外保持与 routes.py 相同的 import 接口。

向后兼容导出 — 供 tests mock 使用:
所有被 `patch("app.api.runtime_api.xxx")` mock 的符号在此重导出，
确保 mock 目标模块有对应属性。
"""
import logging

from fastapi import APIRouter

# 子域路由
from app.api.device_api import router as device_router
from app.api.terminal_api import router as terminal_router
from app.api.project_context_api import router as project_context_router
from app.api.assistant_api import router as assistant_router
from app.api.agent_usage_api import router as agent_usage_router
from app.api.agent_api import router as agent_router
from app.api.agent_report_api import router as agent_report_router
from app.api.eval_api import router as eval_router

logger = logging.getLogger(__name__)

router = APIRouter()

router.include_router(device_router)
router.include_router(terminal_router)
router.include_router(project_context_router)
router.include_router(assistant_router)
router.include_router(agent_usage_router)
router.include_router(agent_router)
router.include_router(agent_report_router)
router.include_router(eval_router)


# ---------------------------------------------------------------------------
# 向后兼容重导出 — 供 agent_session_manager / tests 直接 import 和 mock
# ---------------------------------------------------------------------------

# -- helpers --
from app.api._helpers import device_online as _device_online  # noqa: E402, F401

# -- agent conversation helpers --
from app.api.agent_conversation_helpers import (  # noqa: E402, F401
    _publish_conversation_stream_event,
)
from app.infra.event_bus import (  # noqa: E402, F401
    publish_conversation_stream_event as _publish_conversation_stream_event_bus,
)
from app.api.agent_api import stream_terminal_agent_conversation  # noqa: E402, F401

# -- shared deps (all mocked in tests via app.api._deps.xxx) --
from app.api._deps import (  # noqa: E402, F401
    create_session_terminal,
    get_agent_connection,
    get_agent_execution_report,
    get_agent_session_manager,
    get_approved_scan_roots,
    get_assistant_planner_run,
    get_or_create_agent_conversation,
    get_pinned_projects,
    get_planner_config,
    get_session_by_device_id,
    get_session_terminal,
    get_usage_summary,
    get_view_counts,
    is_agent_connected,
    list_agent_conversation_events,
    list_assistant_planner_memory,
    list_session_terminals,
    list_sessions_for_user,
    plan_with_service_llm,
    replace_approved_scan_roots,
    replace_pinned_projects,
    report_assistant_execution,
    request_agent_close_terminal_with_ack,
    request_agent_create_terminal,
    save_agent_execution_report,
    save_assistant_planner_run,
    save_planner_config,
    send_execute_command,
    send_lookup_knowledge,
    send_tool_call,
    update_session_device_metadata,
    update_session_terminal_metadata,
    update_session_terminal_status,
    append_agent_conversation_event,
    close_agent_conversation,
    get_agent_conversation,
)

# -- assistant plan helpers (mocked in tests) --
from app.api.assistant_plan_helpers import _check_assistant_plan_rate_limit  # noqa: E402, F401

# -- agent report helpers (mocked in tests) --
from app.api.agent_report_api import _get_alias_store  # noqa: E402, F401

# -- eval helpers (mocked in tests) --
from app.api.eval_api import _ensure_eval_db  # noqa: E402, F401
