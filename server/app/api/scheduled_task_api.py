"""
B002: 定时任务 REST API

POST   /api/scheduled-tasks          创建定时任务
GET    /api/scheduled-tasks          查询定时任务列表
DELETE /api/scheduled-tasks/{task_id} 删除定时任务
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, status, Depends, Query

from app.infra.auth import get_current_user_id
from app.api import _deps
from app.api.schemas import (
    ScheduledTaskCreateRequest,
    ScheduledTaskCreateResponse,
    ScheduledTaskItem,
    ScheduledTaskListResponse,
    ScheduledTaskStatus,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_scheduled_task_store():
    """获取 ScheduledTaskStore 实例（复用 Database 的 db_path）。"""
    from app.store.database import _get_db
    from app.store.scheduled_task import ScheduledTaskStore
    db = _get_db()
    return ScheduledTaskStore(db.db_path)


@router.post("/scheduled-tasks", status_code=status.HTTP_201_CREATED)
async def create_scheduled_task(
    body: ScheduledTaskCreateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """创建定时任务。

    验证流程:
    1. execute_at 必须是未来时间
    2. session 存在且属于当前用户
    3. terminal 存在
    4. Agent 在线
    5. 创建任务
    """
    # 1. 验证 execute_at 是未来时间
    try:
        execute_at_dt = datetime.fromisoformat(body.execute_at)
        if execute_at_dt.tzinfo is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="execute_at 必须包含时区信息",
            )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="execute_at 格式无效，需要 ISO 8601 格式",
        )

    if execute_at_dt <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="execute_at 必须是未来时间",
        )

    # 将 execute_at normalize 为 UTC ISO 字符串，确保 SQLite 字典序排序正确
    execute_at_utc = execute_at_dt.astimezone(timezone.utc).isoformat()

    # 2. 验证 session 存在且属于当前用户
    session = await _deps.verify_session_ownership(body.session_id, user_id)
    if not session or not session.get("user_id"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session 不存在",
        )

    # 3. 验证 terminal 存在且状态为 live
    terminals = await _deps.list_session_terminals(body.session_id)
    terminal = next(
        (t for t in terminals if t.get("terminal_id") == body.terminal_id),
        None,
    )
    if not terminal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Terminal 不存在",
        )
    if terminal.get("status") != "live":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="终端已关闭或未就绪",
        )

    # 4. 验证 Agent 在线
    if not _deps.is_agent_connected(body.session_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent 不在线",
        )

    # 5. 创建任务
    store = _get_scheduled_task_store()
    task_id = await store.create(
        user_id=user_id,
        session_id=body.session_id,
        terminal_id=body.terminal_id,
        text_content=body.text_content,
        execute_at=execute_at_utc,
        repeat_type=body.repeat_type.value,
    )

    # 查询刚创建的任务以获取完整数据
    task = await store.get_by_id(task_id)

    return ScheduledTaskCreateResponse(
        id=task["id"],
        session_id=task["session_id"],
        terminal_id=task["terminal_id"],
        text_content=task["text_content"],
        execute_at=task["execute_at"],
        repeat_type=task["repeat_type"],
        status=task["status"],
        created_at=task["created_at"],
    )


@router.get("/scheduled-tasks")
async def list_scheduled_tasks(
    session_id: Optional[str] = Query(None),
    status_query: Optional[str] = Query(None, alias="status"),
    user_id: str = Depends(get_current_user_id),
):
    """查询定时任务列表。

    验证流程:
    1. 如果有 session_id，验证 session 属于当前用户
    2. 按 user_id 查询，可选按 session_id / status 过滤
    """
    # 1. 如果有 session_id，验证 session 属于当前用户
    if session_id:
        session = await _deps.verify_session_ownership(session_id, user_id)
        if not session or not session.get("user_id"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session 不存在",
            )

    # 2. 查询
    store = _get_scheduled_task_store()

    if session_id:
        raw_tasks = await store.list_by_session(session_id, status=status_query)
    else:
        raw_tasks = await store.list_by_user(user_id, status=status_query)

    tasks = [
        ScheduledTaskItem(
            id=t["id"],
            session_id=t["session_id"],
            terminal_id=t["terminal_id"],
            text_content=t["text_content"],
            execute_at=t["execute_at"],
            repeat_type=t["repeat_type"],
            status=t["status"],
            created_at=t["created_at"],
            executed_at=t.get("executed_at"),
        )
        for t in raw_tasks
    ]

    return ScheduledTaskListResponse(tasks=tasks)


@router.delete("/scheduled-tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scheduled_task(
    task_id: int,
    user_id: str = Depends(get_current_user_id),
):
    """删除定时任务。

    验证流程:
    1. 查询任务 -> 不存在 -> 404
    2. 验证任务属于当前用户 -> 不属于 -> 403
    3. 删除
    """
    store = _get_scheduled_task_store()

    # 1. 查询任务
    task = await store.get_by_id(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )

    # 2. 验证任务属于当前用户
    if task.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权删除此任务",
        )

    # 3. 删除
    await store.delete(task_id)
