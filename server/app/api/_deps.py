"""
共享依赖 — 集中导出所有 store / ws / services 函数。

路由模块统一从此处导入，测试 mock 也统一打在此模块上，
避免因 `from X import Y` 创建局部绑定导致 mock 不生效的问题。
"""
# ---- app.store.session ----
from app.store.session import (  # noqa: F401
    create_session_terminal,
    get_session_by_device_id,
    get_session_terminal,
    list_session_terminals,
    list_sessions_for_user,
    update_session_device_metadata,
    update_session_terminal_metadata,
    update_session_terminal_status,
)

# ---- app.store.database ----
from app.store.database import (  # noqa: F401
    append_agent_conversation_event,
    close_agent_conversation,
    get_agent_conversation,
    get_agent_execution_report,
    get_approved_scan_roots,
    get_assistant_planner_run,
    get_or_create_agent_conversation,
    get_pinned_projects,
    get_planner_config,
    get_usage_summary,
    list_agent_conversation_events,
    list_assistant_planner_memory,
    replace_approved_scan_roots,
    replace_pinned_projects,
    report_assistant_execution,
    save_agent_execution_report,
    save_assistant_planner_run,
    save_planner_config,
)

# ---- app.ws ----
from app.ws.ws_agent import (  # noqa: F401
    get_agent_connection,
    is_agent_connected,
    request_agent_close_terminal_with_ack,
    request_agent_create_terminal,
    send_execute_command,
    send_lookup_knowledge,
    send_tool_call,
)
from app.ws.ws_client import get_view_counts  # noqa: F401

# ---- app.services ----
from app.services.agent_session_manager import get_agent_session_manager  # noqa: F401
from app.services.assistant_planner import plan_with_service_llm  # noqa: F401
