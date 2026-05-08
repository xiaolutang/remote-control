"""
WebSocket 共享工具函数。

子模块拆分后，ws_agent / agent_message_handler 等模块共享的辅助函数集中于此，
避免重复定义。
"""
from fastapi import HTTPException
from redis.exceptions import RedisError


def is_degradable_session_state_error(exc: Exception) -> bool:
    """仅将底层存储类故障视为可降级，避免吞掉真实业务错误。"""
    if isinstance(exc, HTTPException):
        return exc.status_code >= 500
    return isinstance(exc, (RedisError, OSError, ConnectionError, TimeoutError))
