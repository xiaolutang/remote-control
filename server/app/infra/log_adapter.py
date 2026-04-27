"""
日志适配层 — 封装 log-service-sdk 的初始化和关闭逻辑。

SDK 变更或替换时只需修改此文件，消费方不直接依赖 SDK。
"""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_handler: Optional[object] = None


def init_logging(
    component: str = "server",
    service_name: str = "remote-control",
) -> Optional[object]:
    """初始化远程日志。SDK 不可用时优雅降级，重复调用幂等。"""
    global _handler
    if _handler is not None:
        return _handler

    log_service_url = os.environ.get("LOG_SERVICE_URL", "http://localhost:8001")
    log_level = os.environ.get("LOG_LEVEL", "INFO")

    try:
        from log_service_sdk import setup_remote_logging
        _handler = setup_remote_logging(
            endpoint=log_service_url,
            service_name=service_name,
            component=component,
            level=log_level,
        )
        logger.info("远程日志已初始化: endpoint=%s, level=%s", log_service_url, log_level)
    except Exception as e:
        logger.warning("远程日志初始化失败（不影响运行）: %s", e)

    return _handler


def close_logging() -> None:
    """关闭远程日志 handler，flush 剩余日志。未初始化时调用安全。"""
    global _handler
    if _handler is None:
        return
    try:
        _handler.close()
        logger.info("远程日志 handler 已关闭")
    except Exception:
        pass
    _handler = None
