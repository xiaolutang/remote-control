"""
日志适配层 — 封装 log-service-sdk 的初始化和关闭逻辑。

SDK 变更或替换时只需修改此文件，消费方不直接依赖 SDK。
Agent 端特有行为：LOG_SERVICE_URL 未设置或为空时跳过初始化。
"""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_handler: Optional[object] = None


def init_logging(
    component: str = "agent",
    service_name: str = "remote-control",
) -> Optional[object]:
    """初始化远程日志。LOG_SERVICE_URL 未设置或为空时跳过。SDK 不可用时优雅降级。"""
    global _handler
    if _handler is not None:
        return _handler

    log_service_url = os.environ.get("LOG_SERVICE_URL", "")
    if not log_service_url:
        logger.debug("LOG_SERVICE_URL not set, remote logging disabled")
        return None

    try:
        from log_service_sdk import setup_remote_logging
        _handler = setup_remote_logging(
            endpoint=log_service_url,
            service_name=service_name,
            component=component,
            level=os.environ.get("LOG_LEVEL", "INFO"),
        )
        logger.info("Agent remote logging initialized: endpoint=%s", log_service_url)
    except Exception as e:
        logger.warning("Agent remote logging init failed (non-blocking): %s", e)

    return _handler


def close_logging() -> None:
    """关闭远程日志 handler，flush 剩余日志。未初始化时调用安全。"""
    global _handler
    if _handler is None:
        return
    try:
        _handler.close()
    except Exception:
        pass
    _handler = None
