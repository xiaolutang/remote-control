"""
B122: 轻量级进程内事件总线。

解耦 services 层对 api 层的依赖：
- agent_session_manager 不再直接导入 api 层的 _publish_conversation_stream_event
- api 层通过 subscribe / unsubscribe 注册回调
- services 层通过 publish 发布事件
"""
import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

# 事件处理器签名
EventHandler = Callable[..., Awaitable[None]]

# conversation stream 事件订阅者注册表
# key: (user_id, device_id, terminal_id)  value: set of async callbacks
_conversation_stream_handlers: dict[tuple[str, str, str], list[EventHandler]] = defaultdict(list)


def conversation_stream_key(user_id: str, device_id: str, terminal_id: str) -> tuple[str, str, str]:
    return (user_id, device_id, terminal_id)


def subscribe_conversation_stream(
    user_id: str,
    device_id: str,
    terminal_id: str,
    handler: EventHandler,
) -> None:
    """注册 conversation stream 事件处理器。"""
    key = conversation_stream_key(user_id, device_id, terminal_id)
    _conversation_stream_handlers[key].append(handler)


def unsubscribe_conversation_stream(
    user_id: str,
    device_id: str,
    terminal_id: str,
    handler: EventHandler,
) -> None:
    """移除 conversation stream 事件处理器。"""
    key = conversation_stream_key(user_id, device_id, terminal_id)
    handlers = _conversation_stream_handlers.get(key)
    if handlers:
        try:
            handlers.remove(handler)
        except ValueError:
            pass
        if not handlers:
            _conversation_stream_handlers.pop(key, None)


async def publish_conversation_stream_event(
    user_id: str,
    device_id: str,
    terminal_id: str,
    event: dict[str, Any],
) -> None:
    """发布 conversation stream 事件给所有订阅者。"""
    key = conversation_stream_key(user_id, device_id, terminal_id)
    handlers = list(_conversation_stream_handlers.get(key, []))
    for handler in handlers:
        try:
            await handler(event)
        except Exception:
            logger.debug(
                "event_bus handler error: key=%s handler=%s",
                key, getattr(handler, "__name__", handler),
                exc_info=True,
            )
