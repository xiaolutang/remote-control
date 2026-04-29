"""
Eval REST API — 质量指标、评估候选 CRUD。
"""
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, status, Depends
import logging

from app.infra.auth import get_current_user_id
from evals.db import EvalDatabase
from evals.feedback_loop import (
    approve_candidate,
    list_candidates,
    reject_candidate,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_eval_db_instance: Optional[EvalDatabase] = None
_eval_db_initialized: bool = False


def _get_eval_db() -> EvalDatabase:
    """获取 EvalDatabase 单例（使用 EVALS_DB_PATH 环境变量或默认路径）。"""
    global _eval_db_instance
    if _eval_db_instance is None:
        db_path = os.environ.get("EVALS_DB_PATH", "/data/evals.db")
        _eval_db_instance = EvalDatabase(db_path)
    return _eval_db_instance


async def _ensure_eval_db() -> EvalDatabase:
    """获取 EvalDatabase 单例并确保表已创建（仅首次调用时执行 init_db）。"""
    global _eval_db_initialized
    db = _get_eval_db()
    if not _eval_db_initialized:
        await db.init_db()
        _eval_db_initialized = True
    return db


@router.get("/eval/quality/metrics")
async def get_quality_metrics(
    metric_name: Optional[str] = None,
    user_id: Optional[str] = None,
    device_id: Optional[str] = None,
    session_id: Optional[str] = None,
    source: Optional[str] = "production",
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = 100,
    _user_id: str = Depends(get_current_user_id),
):
    """查询质量指标记录，支持多条件过滤。

    B055: 新增 source 过滤参数，默认 'production'。
    source 可选 'production'（生产看板）或 'integration'（eval 指标）。
    """
    try:
        db = await _ensure_eval_db()
        metrics = await db.query_quality_metrics(
            metric_name=metric_name,
            user_id=user_id,
            device_id=device_id,
            session_id=session_id,
            source=source,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
        return [m.model_dump() for m in metrics]
    except Exception as e:
        logger.error("Failed to query quality metrics: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"查询质量指标失败: {type(e).__name__}",
        )


@router.get("/eval/quality/summary")
async def get_quality_summary(
    metric_name: Optional[str] = None,
    user_id: Optional[str] = None,
    device_id: Optional[str] = None,
    source: Optional[str] = "production",
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    group_by: str = "day",
    _user_id: str = Depends(get_current_user_id),
):
    """按时间窗口聚合质量指标（日/周/月）。

    B055: 新增 source 过滤参数，默认 'production'。
    """
    try:
        db = await _ensure_eval_db()
        result = await db.aggregate_quality_metrics(
            metric_name=metric_name,
            user_id=user_id,
            device_id=device_id,
            source=source,
            start_time=start_time,
            end_time=end_time,
            group_by=group_by,
        )
        return result
    except Exception as e:
        logger.error("Failed to aggregate quality metrics: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"聚合质量指标失败: {type(e).__name__}",
        )


@router.get("/eval/candidates")
async def get_eval_candidates(
    status_filter: Optional[str] = None,
    _user_id: str = Depends(get_current_user_id),
):
    """列出候选评估任务（可选按状态过滤）。"""
    try:
        db = await _ensure_eval_db()
        result = await list_candidates(db, status=status_filter)
        return result
    except Exception as e:
        logger.error("Failed to list candidates: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"列出候选任务失败: {type(e).__name__}",
        )


async def _handle_candidate_review(
    action_fn,
    candidate_id: str,
    user_id: str,
    action_label: str,
):
    """审核候选任务的共享 handler（approve / reject）。"""
    try:
        db = await _ensure_eval_db()
        result = await action_fn(db, candidate_id, reviewer=user_id)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"候选任务 {candidate_id} 不存在",
            )
        if "error" in result:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=result["error"],
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to %s candidate: %s", action_label, e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{action_label}候选任务失败: {type(e).__name__}",
        )


@router.post("/eval/candidates/{candidate_id}/approve")
async def approve_eval_candidate(
    candidate_id: str,
    _user_id: str = Depends(get_current_user_id),
):
    """审核通过候选任务（approved 后可被 harness 加载执行）。"""
    return await _handle_candidate_review(approve_candidate, candidate_id, _user_id, "审核")


@router.post("/eval/candidates/{candidate_id}/reject")
async def reject_eval_candidate(
    candidate_id: str,
    _user_id: str = Depends(get_current_user_id),
):
    """审核拒绝候选任务。"""
    return await _handle_candidate_review(reject_candidate, candidate_id, _user_id, "拒绝")
