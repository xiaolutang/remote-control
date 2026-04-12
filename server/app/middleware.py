"""
请求日志中间件

- RequestIDMiddleware: 自动生成/读取 X-Request-ID，通过 ContextVar 传递
- RequestLoggingMiddleware: 自动记录 method/path/status/耗时/client_ip
- ErrorHandlerMiddleware: 捕获未处理异常，记录完整堆栈

注册顺序（后添加先执行）: app.add_middleware(ErrorHandler) → app.add_middleware(RequestLogging) → app.add_middleware(RequestID)
实际执行顺序: RequestID → RequestLogging → ErrorHandler → 路由
"""
import logging
import time
import uuid
from contextvars import ContextVar
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.auth import TokenVerificationError
from fastapi import HTTPException

logger = logging.getLogger("request")

# ContextVar: 请求生命周期内传递 request_id
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")

# 跳过日志记录的路径
_SKIP_PATHS = {"/health", "/favicon.ico"}


class RequestIDMiddleware(BaseHTTPMiddleware):
    """为每个请求生成或读取 X-Request-ID"""

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request_id_ctx.set(rid)
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """自动记录每个 HTTP 请求的 method/path/status/耗时/client_ip"""

    async def dispatch(self, request: Request, call_next):
        # 跳过健康检查和 favicon
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        start = time.monotonic()
        response = await call_next(request)
        elapsed_ms = (time.monotonic() - start) * 1000

        rid = request_id_ctx.get("")
        client_ip = request.client.host if request.client else "-"

        logger.info(
            "%s %s %s %.1fms %s request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            client_ip,
            rid,
        )
        return response


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """捕获未处理异常，记录完整堆栈，返回标准化 JSON 错误响应"""

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except TokenVerificationError:
            # auth 模块的 TokenVerificationError 由 FastAPI exception handler 处理，不包装
            raise
        except HTTPException:
            # auth 模块及其他 HTTPException 保持原有行为，不包装
            raise
        except Exception as exc:
            rid = request_id_ctx.get("")
            logger.exception(
                "Unhandled exception: %s %s request_id=%s",
                request.method,
                request.url.path,
                rid,
            )
            return JSONResponse(
                status_code=500,
                content={
                    "detail": "Internal Server Error",
                    "request_id": rid,
                },
            )
