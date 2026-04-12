"""
反馈 API 路由

提供反馈提交和查询功能。
"""
import logging
from typing import Optional, List, Dict, Any, Literal
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.auth import async_verify_token
from app.feedback_service import (
    create_feedback,
    get_feedback,
)
from app.session import get_session

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/feedback", tags=["feedback"])

# HTTP Bearer 认证
security = HTTPBearer()


async def get_current_payload(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """获取当前认证的 payload"""
    token = credentials.credentials
    return await async_verify_token(token)


async def _get_real_user_id(payload: dict) -> str:
    """通过 JWT payload 的 sub（session_id）查 session 记录获取真实 user_id。

    fail-closed：session 查不到或 user_id 为空时抛 401。
    """
    session_id = payload.get("session_id", "")
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证信息",
        )
    try:
        session = await get_session(session_id)
    except Exception as e:
        logger.warning("Session lookup failed for user resolution: session_id=%s error=%s", session_id, e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="会话不存在或已过期",
        )
    user_id = session.get("user_id", "")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户信息缺失",
        )
    return user_id


# ============ 请求/响应模型 ============

class FeedbackCreateRequest(BaseModel):
    """提交反馈请求"""
    session_id: str = Field(..., description="会话 ID")
    category: Literal["connection", "terminal", "crash", "suggestion", "other"] = Field(
        ..., description="反馈分类"
    )
    description: str = Field(
        ..., description="反馈描述", max_length=10000,
    )
    platform: Optional[str] = Field(None, description="平台信息")
    app_version: Optional[str] = Field(None, description="应用版本")


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
    payload: dict = Depends(get_current_payload),
):
    """
    提交反馈

    - **session_id**: 会话 ID
    - **category**: 反馈分类（connection/terminal/crash/suggestion/other）
    - **description**: 反馈描述（最大 10000 字符）
    - **platform**: 平台信息（可选）
    - **app_version**: 应用版本（可选）
    """
    user_id = await _get_real_user_id(payload)

    result = await create_feedback(
        user_id=user_id,
        session_id=request.session_id,
        category=request.category,
        description=request.description,
        platform=request.platform,
        app_version=request.app_version,
    )

    return FeedbackResponse(
        feedback_id=result["feedback_id"],
        created_at=result["created_at"],
    )


@router.get("/{feedback_id}", response_model=FeedbackDetailResponse)
async def get_feedback_detail(
    feedback_id: str,
    payload: dict = Depends(get_current_payload),
):
    """
    查询反馈详情

    - **feedback_id**: 反馈 ID
    """
    user_id = await _get_real_user_id(payload)

    feedback = await get_feedback(feedback_id, user_id)
    if feedback is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"反馈 {feedback_id} 不存在",
        )

    return FeedbackDetailResponse(**feedback)

