"""
日志 API 路由

提供客户端日志上报、查询和实时流功能。
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Literal
from fastapi import APIRouter, Depends, Query, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth import async_verify_token
from app.http_client import get_shared_http_client
from app.log_service import (
    append_logs_batch,
    get_logs,
    get_log_count,
    subscribe_logs,
    unsubscribe_logs,
    LogLevel,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/logs", tags=["logs"])

# HTTP Bearer 认证
security = HTTPBearer()


async def get_current_payload(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """获取当前认证的 payload"""
    token = credentials.credentials
    return await async_verify_token(token)


# ============ 请求/响应模型 ============

class LogEntry(BaseModel):
    """单条日志"""
    level: Literal["debug", "info", "warn", "error", "fatal"] = "info"
    message: str
    timestamp: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class UploadLogsRequest(BaseModel):
    """批量上报日志请求"""
    session_id: str = Field(..., description="会话 ID")
    uid: str = Field("", description="用户标识（username），未登录时为空")
    logs: List[LogEntry] = Field(..., description="日志列表")


class UploadLogsResponse(BaseModel):
    """批量上报日志响应"""
    success: bool = True
    received: int


class LogRecord(BaseModel):
    """日志记录"""
    level: str
    message: str
    timestamp: str
    metadata: Dict[str, Any] = {}


class GetLogsResponse(BaseModel):
    """查询日志响应"""
    session_id: str
    total: int
    offset: int
    limit: int
    logs: List[LogRecord]


# ============ API 端点 ============

@router.post("", response_model=UploadLogsResponse)
async def upload_logs(
    request: UploadLogsRequest,
    payload: dict = Depends(get_current_payload),
):
    """
    批量上报客户端日志

    - **session_id**: 会话 ID
    - **logs**: 日志列表，每条包含 level/message/timestamp/metadata
    """
    # 日志 API 允许上报任意 session_id 的日志（调试目的）
    # 但需要 token 有效

    # 转换日志格式
    logs_data = [
        {
            "level": log.level,
            "message": log.message,
            "timestamp": log.timestamp,
            "metadata": log.metadata,
        }
        for log in request.logs
    ]

    result = await append_logs_batch(request.session_id, logs_data)

    # 代理转发到 log-service（best-effort，路径 B，不阻塞响应）
    asyncio.create_task(_forward_to_log_service(request.session_id, logs_data, uid=request.uid))

    return UploadLogsResponse(
        success=True,
        received=result["received"],
    )


@router.get("", response_model=GetLogsResponse)
async def list_logs(
    session_id: str = Query(..., description="会话 ID"),
    level: Optional[LogLevel] = Query(None, description="过滤级别（最小级别）"),
    since: Optional[str] = Query(None, description="起始时间（ISO8601）"),
    until: Optional[str] = Query(None, description="结束时间（ISO8601）"),
    offset: int = Query(0, ge=0, description="偏移量"),
    limit: int = Query(100, ge=1, le=500, description="限制数量"),
    payload: dict = Depends(get_current_payload),
):
    """
    查询客户端日志

    - **session_id**: 会话 ID（必填）
    - **level**: 过滤级别，如 warn 表示 warn/error/fatal
    - **since**: 起始时间（ISO8601 格式）
    - **until**: 结束时间（ISO8601 格式）
    - **offset**: 分页偏移量
    - **limit**: 每页数量（最大 500）
    """
    result = await get_logs(
        session_id=session_id,
        level=level,
        since=since,
        until=until,
        offset=offset,
        limit=limit,
    )

    return GetLogsResponse(**result)


@router.get("/stream")
async def stream_logs(
    session_id: str = Query(..., description="会话 ID"),
    level: Optional[LogLevel] = Query(None, description="过滤级别（最小级别）"),
    payload: dict = Depends(get_current_payload),
):
    """
    实时日志流 (Server-Sent Events)

    连接后持续推送新日志，直到客户端断开连接。

    - **session_id**: 会话 ID（必填）
    - **level**: 过滤级别，如 warn 表示只推送 warn/error/fatal
    """
    from app.log_service import LEVEL_WEIGHTS

    min_level_weight = LEVEL_WEIGHTS.get(level, 0) if level else 0

    async def event_generator():
        """SSE 事件生成器"""
        queue = asyncio.Queue()

        async def on_log(log_record):
            """日志回调"""
            # 级别过滤
            log_level = log_record.get("level", "info")
            if level and LEVEL_WEIGHTS.get(log_level, 0) < min_level_weight:
                return
            await queue.put(log_record)

        # 订阅日志
        await subscribe_logs(session_id, on_log)

        try:
            # 发送初始连接成功事件
            yield f"event: connected\ndata: {json.dumps({'session_id': session_id})}\n\n"

            while True:
                try:
                    # 等待新日志，超时 30 秒发送心跳
                    log_record = await asyncio.wait_for(
                        queue.get(),
                        timeout=30.0
                    )

                    # 发送日志事件
                    yield f"event: log\ndata: {json.dumps(log_record)}\n\n"

                except asyncio.TimeoutError:
                    # 发送心跳
                    yield f"event: ping\ndata: {json.dumps({'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"

        except asyncio.CancelledError:
            # 客户端断开连接
            pass
        finally:
            # 取消订阅
            await unsubscribe_logs(session_id, on_log)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/count")
async def count_logs(
    session_id: str = Query(..., description="会话 ID"),
    payload: dict = Depends(get_current_payload),
):
    """
    获取日志数量

    - **session_id**: 会话 ID（必填）
    """
    count = await get_log_count(session_id)

    return {
        "session_id": session_id,
        "count": count,
    }


async def _forward_to_log_service(session_id: str, logs_data: list[dict], *, uid: str = "") -> None:
    """将客户端日志代理转发到 log-service ingest API（路径 B，best-effort）。

    使用 httpx.AsyncClient 异步发送，timeout=3s，失败不重试。
    不影响 Redis 存储和 API 响应。
    """
    log_service_url = os.environ.get("LOG_SERVICE_URL", "http://localhost:8001")
    if not log_service_url:
        return

    # 映射日志格式：LogEntry → IngestLogEntry
    entries = []
    for log in logs_data:
        entry = {
            "level": log.get("level", "info"),
            "message": log.get("message", ""),
            "timestamp": log.get("timestamp"),
            "service_name": "remote-control",
            "component": "client",
            "uid": uid,
            "extra": {"session_id": session_id},
        }
        if log.get("metadata"):
            entry["extra"].update(log["metadata"])
        entries.append(entry)

    if not entries:
        return

    try:
        client = get_shared_http_client()
        response = await client.post(
            f"{log_service_url}/api/logs/ingest",
            json={"entries": entries},
        )
        response.raise_for_status()
        logger.debug("Forwarded %d logs to log-service: session_id=%s", len(entries), session_id)
    except Exception as e:
        logger.warning(
            "Failed to forward logs to log-service (best-effort): session_id=%s error=%s",
            session_id, e,
        )

