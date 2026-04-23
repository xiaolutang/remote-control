"""
FastAPI 应用入口
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.routes import router
from app.ws_agent import _stale_agent_ttl_checker
from app.auth import TokenVerificationError
from app.log_adapter import init_logging, close_logging
from app.middleware import (
    RequestIDMiddleware,
    RequestLoggingMiddleware,
    ErrorHandlerMiddleware,
)
from app.database import configure_database, init_db, DEFAULT_DB_PATH

logger = logging.getLogger(__name__)

# TTL checker 后台任务
_ttl_checker_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global _ttl_checker_task

    # 配置并初始化数据库（用户持久化存储）
    db_path = os.environ.get("DATABASE_PATH", DEFAULT_DB_PATH)
    configure_database(db_path)
    await init_db()
    logger.info("Database initialized")

    # 初始化远程日志（通过适配层）
    init_logging(component="server")

    # 条件启用 LLM 可观测性（logfire → OTLP → Opik）
    otel_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otel_endpoint:
        try:
            import logfire
            logfire.configure(send_to_logfire=False)
            logfire.instrument_pydantic_ai()
            logger.info("LLM observability enabled: logfire → %s", otel_endpoint)
        except Exception as exc:
            logger.warning("Failed to configure logfire: %s", exc)

    # 启动时创建 TTL checker 后台任务
    _ttl_checker_task = asyncio.create_task(_stale_agent_ttl_checker())
    logger.info("Stale agent TTL checker started")
    yield
    # 关闭时取消后台任务
    if _ttl_checker_task:
        _ttl_checker_task.cancel()
        try:
            await _ttl_checker_task
        except asyncio.CancelledError:
            pass
        logger.info("Stale agent TTL checker stopped")
    # 关闭共享 httpx 异步客户端
    from app.http_client import close_shared_http_client
    await close_shared_http_client()

    # 关闭远程日志 handler
    close_logging()


app = FastAPI(
    title="Remote Control Server",
    description="Personal Remote Control - Terminal Relay Service",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(TokenVerificationError)
async def token_verification_error_handler(request: Request, exc: TokenVerificationError):
    """Token 校验异常处理器，返回 {"detail": "...", "error_code": "..."} 格式"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "error_code": exc.error_code},
    )

# 注册中间件（后添加先执行，所以实际顺序：RequestID → RequestLogging → ErrorHandler）
app.add_middleware(ErrorHandlerMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RequestIDMiddleware)

# CORS 配置：从环境变量读取允许的域名（逗号分隔），未设置时阻止所有跨域
_cors_origins_str = os.environ.get("CORS_ORIGINS", "")
_cors_origins = [o.strip() for o in _cors_origins_str.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(router)


@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "ok", "service": "rc-server", "version": "1.0.0"}
