"""
历史记录 REST API
"""
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
from typing import List

from app.session import (
    get_history,
    get_history_count,
    verify_session_ownership,
)
from app.auth import get_current_user_id

router = APIRouter()


class HistoryRecord(BaseModel):
    timestamp: str
    direction: str
    data: str


class HistoryResponse(BaseModel):
    session_id: str
    total: int
    offset: int
    limit: int
    records: List[HistoryRecord]


@router.get("/history/{session_id}")
async def get_history_endpoint(
    session_id: str,
    offset: int = 0,
    limit: int = 100,
    user_id: str = Depends(get_current_user_id),
):
    """
    获取历史记录端点

    验证流程：
    1. 从 token 获取当前 user_id（通过 get_current_user_id）
    2. 验证目标 session 归属
    """
    # 验证分页参数
    if offset < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="offset 不能为负数",
        )

    if limit <= 0 or limit > 1000:
        limit = 1000

    # 验证目标 session 归属（如果有 user_id）
    if user_id:
        await verify_session_ownership(session_id, user_id)

    # 获取历史记录
    try:
        records = await get_history(session_id, offset, limit)
        total = await get_history_count(session_id)
    except HTTPException:
        raise

    # 转换为响应格式
    return HistoryResponse(
        session_id=session_id,
        total=total,
        offset=offset,
        limit=limit,
        records=[
            HistoryRecord(
                timestamp=r.get("timestamp"),
                direction=r.get("direction", "output"),
                data=r.get("data"),
            )
            for r in records
        ],
    )
