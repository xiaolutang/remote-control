"""
反馈 API 路由

提供反馈提交和查询功能。
"""
import logging
from typing import Optional, List, Dict, Any, Literal
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.infra.auth import get_current_user_id
from app.services.feedback_service import (
    create_feedback,
    get_feedback,
)

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/feedback", tags=["feedback"])


# ============ 请求/响应模型 ============

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


# ============ API 端点 ============

@router.post("", response_model=FeedbackResponse)
async def submit_feedback(
    request: FeedbackCreateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    提交反馈

    - **session_id**: 会话 ID（旧字段，可选）
    - **category**: 反馈分类（connection/terminal/crash/suggestion/other）
    - **description**: 反馈描述（最大 10000 字符）
    - **platform**: 平台信息（可选）
    - **app_version**: 应用版本（可选）
    - **terminal_id**: 终端 ID（B052 新增，可选）
    - **result_event_id**: 关联的 result 事件 ID（B052 新增，可选）
    - **feedback_type**: 反馈类型（B052 新增，可选）
    """
    result = await create_feedback(
        user_id=user_id,
        session_id=request.session_id or "",
        category=request.category,
        description=request.description,
        platform=request.platform,
        app_version=request.app_version,
        terminal_id=request.terminal_id,
        result_event_id=request.result_event_id,
        feedback_type=request.feedback_type,
    )

    return FeedbackResponse(
        feedback_id=result["feedback_id"],
        created_at=result["created_at"],
    )


@router.get("/{feedback_id}", response_model=FeedbackDetailResponse)
async def get_feedback_detail(
    feedback_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """
    查询反馈详情

    - **feedback_id**: 反馈 ID
    """

    feedback = await get_feedback(feedback_id, user_id)
    if feedback is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"反馈 {feedback_id} 不存在",
        )

    return FeedbackDetailResponse(**feedback)

