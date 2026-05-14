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
    cancel_scheduled_tasks_by_terminal,
    close_agent_conversation,
    create_scheduled_task,
    delete_scheduled_task,
    find_pending_duplicate,
    get_agent_conversation,
    get_agent_execution_report,
    get_approved_scan_roots,
    get_assistant_planner_run,
    get_or_create_agent_conversation,
    get_pinned_projects,
    get_planner_config,
    get_scheduled_task_by_id,
    get_usage_summary,
    list_agent_conversation_events,
    list_assistant_planner_memory,
    list_pending_due_scheduled_tasks,
    list_project_aliases,
    list_scheduled_tasks_by_session,
    list_scheduled_tasks_by_session_and_terminal,
    list_scheduled_tasks_by_user,
    lookup_project_alias,
    replace_approved_scan_roots,
    replace_pinned_projects,
    report_assistant_execution,
    save_agent_execution_report,
    save_assistant_planner_run,
    save_planner_config,
    save_project_alias,
    save_project_aliases_batch,
    update_scheduled_task_execute_at,
    update_scheduled_task_status,
)

# ---- app.ws ----
from app.ws.agent_connection import (  # noqa: F401
    get_agent_connection,
    is_agent_connected,
)
from app.ws.agent_request import (  # noqa: F401
    request_agent_close_terminal_with_ack,
    request_agent_create_terminal,
    send_execute_command,
    send_lookup_knowledge,
    send_tool_call,
)
from app.ws.client_presence import get_view_counts  # noqa: F401

# ---- app.store.session_crud ----
from app.store.session_crud import verify_session_ownership  # noqa: F401

# ---- app.services ----
from app.services.agent_session_manager import get_agent_session_manager  # noqa: F401
from app.services.assistant_planner import plan_with_service_llm  # noqa: F401

# ---- 便捷组合函数 ----

from fastapi import HTTPException, status as _status


async def get_owned_device_session(device_id: str, user_id: str) -> dict:
    """获取设备 session，不存在则抛 404。"""
    session = await get_session_by_device_id(device_id, user_id)
    if not session:
        raise HTTPException(
            status_code=_status.HTTP_404_NOT_FOUND,
            detail=f"device {device_id} 不存在",
        )
    return session
