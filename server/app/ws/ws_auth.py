"""
WebSocket 认证共享模块

提取 ws_agent.py 和 ws_client.py 共用的认证逻辑：
- HTTP 状态码到 WS 关闭码映射
- WebSocket 首条 auth 消息验证
- 安全传输层判定
- 共享常量
"""
import asyncio
import json
import os
import secrets
from typing import Tuple

from fastapi import WebSocketDisconnect, HTTPException

from app.infra.auth import async_verify_token, TokenVerificationError
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


def _normalized_headers(websocket) -> dict[str, str]:
    raw_headers = getattr(websocket, "headers", None)
    if isinstance(raw_headers, dict):
        header_items = raw_headers.items()
    else:
        try:
            header_items = dict(raw_headers or {}).items()
        except (TypeError, ValueError):
            header_items = ()

    return {
        str(key).strip().lower(): str(value).strip()
        for key, value in header_items
    }


def _trusted_proxy_tls_token() -> str:
    return os.environ.get("TRUSTED_PROXY_TLS_TOKEN", "").strip()


def is_secure_websocket_transport(websocket) -> bool:
    """判断当前 WebSocket 是否运行在 TLS 或可信反代终止后的安全链路上。"""
    raw_scope = getattr(websocket, "scope", None)
    scope = raw_scope if isinstance(raw_scope, dict) else {}
    scheme = str(scope.get("scheme", "")).strip().lower()
    if scheme in {"https", "wss"}:
        return True

    headers = _normalized_headers(websocket)
    trusted_tls_header = os.environ.get(
        "TRUSTED_PROXY_TLS_HEADER",
        "x-rc-forwarded-tls",
    ).strip().lower()
    trusted_tls_token = _trusted_proxy_tls_token()

    if (
        trusted_tls_header
        and trusted_tls_token
        and secrets.compare_digest(
            headers.get(trusted_tls_header, ""),
            trusted_tls_token,
        )
    ):
        return True

    return False


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
