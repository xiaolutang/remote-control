"""
Agent Report REST API — 执行结果回写 + alias 持久化。
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status, Depends

from app.infra.auth import get_current_user_id
from app.api import _deps
from app.store.project_alias_store import ProjectAliasStore
from app.api.schemas import (
    AgentExecutionReportRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_alias_store() -> ProjectAliasStore:
    from app.store.database import _get_db
    db = _get_db()
    return ProjectAliasStore(db.db_path)


@router.post("/runtime/devices/{device_id}/assistant/agent/{session_id}/report")
async def report_agent_execution(
    device_id: str,
    session_id: str,
    request: AgentExecutionReportRequest,
    user_id: str = Depends(get_current_user_id),
):
    """接收客户端执行结果回写。

    - 记录 execution report（幂等：同一 session_id 不重复处理）
    - success=True 且有 aliases 时触发别名持久化
    - 失败时仍回写（用于评估 trace），但不更新别名
    """
    manager = _deps.get_agent_session_manager()
    agent_session = await manager.get_session(session_id)

    if agent_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"会话 {session_id} 不存在",
        )
    if agent_session.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权操作此会话",
        )
    if agent_session.device_id != device_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="设备 ID 不匹配",
        )

    existing_report = await _deps.get_agent_execution_report(session_id)
    if existing_report:
        return {
            "status": "ok",
            "session_id": session_id,
            "idempotent": True,
        }

    aliases: dict[str, str] = {}
    if request.success and agent_session.result and agent_session.result.aliases:
        aliases = agent_session.result.aliases

    await _deps.save_agent_execution_report(
        session_id=session_id,
        user_id=user_id,
        device_id=device_id,
        success=request.success,
        executed_command=request.executed_command,
        failure_step=request.failure_step,
        aliases=aliases,
    )

    if request.success and aliases:
        try:
            alias_store = _get_alias_store()
            await alias_store.save_batch(user_id, device_id, aliases)
        except Exception as e:
            logger.warning(
                "Failed to save aliases for session %s: %s",
                session_id, e, exc_info=True,
            )

    return {
        "status": "ok",
        "session_id": session_id,
        "idempotent": False,
    }
