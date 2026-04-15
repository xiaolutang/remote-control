"""
WebSocket 认证共享模块

提取 ws_agent.py 和 ws_client.py 共用的认证逻辑：
- HTTP 状态码到 WS 关闭码映射
- WebSocket 首条 auth 消息验证
- 共享常量
"""
import asyncio
import json
import os
from typing import Tuple

from fastapi import WebSocketDisconnect, HTTPException

from app.auth import async_verify_token, TokenVerificationError
import logging

logger = logging.getLogger(__name__)

# WS 认证配置
WS_AUTH_TIMEOUT = 5  # 秒
MAX_WS_MESSAGE_SIZE = int(os.environ.get("MAX_WS_MESSAGE_SIZE", 1 * 1024 * 1024))  # 1MB


def http_to_ws_code(http_code: int) -> int:
    """将 HTTP 状态码映射为有效的 WebSocket 关闭码"""
    mapping = {
        401: 4001,  # Unauthorized
        403: 4003,  # Forbidden
        404: 4004,  # Not Found
        409: 4009,  # Conflict
        500: 4500,  # Internal Server Error
        503: 4503,  # Service Unavailable
    }
    return mapping.get(http_code, 4500)


async def wait_for_ws_auth(websocket) -> Tuple[dict, dict]:
    """
    等待 WebSocket 首条 auth 消息并验证 token。

    Returns:
        (jwt_payload, raw_auth_msg) — JWT 解码后的 payload 和原始 auth 消息

    Raises:
        WebSocketDisconnect: 认证失败时关闭连接
    """
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=WS_AUTH_TIMEOUT)
    except asyncio.TimeoutError:
        await websocket.close(code=4002, reason="Auth timeout")
        raise WebSocketDisconnect(code=4002)

    if len(raw) > MAX_WS_MESSAGE_SIZE:
        await websocket.close(code=4003, reason="Message too large")
        raise WebSocketDisconnect(code=4003)

    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        await websocket.close(code=4004, reason="Invalid JSON in auth message")
        raise WebSocketDisconnect(code=4004)

    if msg.get("type") != "auth" or not msg.get("token"):
        await websocket.close(code=4004, reason="Expected auth message")
        raise WebSocketDisconnect(code=4004)

    token = msg["token"]

    try:
        payload = await async_verify_token(token)
    except TokenVerificationError as e:
        reason = e.error_code if e.error_code else e.detail
        logger.warning(f"Token verification failed: {reason}")
        await websocket.close(code=http_to_ws_code(e.status_code), reason=reason)
        raise WebSocketDisconnect(code=http_to_ws_code(e.status_code))
    except HTTPException as e:
        logger.warning(f"Token verification failed: {e.detail}")
        await websocket.close(code=http_to_ws_code(e.status_code), reason=e.detail)
        raise WebSocketDisconnect(code=http_to_ws_code(e.status_code))
    except Exception as e:
        logger.warning(f"Token verification error: {type(e).__name__}: {e}")
        await websocket.close(code=4500, reason=str(e))
        raise WebSocketDisconnect(code=4500)

    return payload, msg
