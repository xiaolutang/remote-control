"""
Refresh Token Redis CRUD

API 层通过本模块操作 refresh token，不直接访问 Redis。
Redis 不可用时 fail-closed（抛异常，由调用方返回 503）。
"""
import logging
from typing import Optional

from app.store.session import get_redis
from app.infra.auth import REFRESH_TOKEN_EXPIRATION_DAYS

_logger = logging.getLogger("store.refresh_token")

# Redis key 前缀
_REFRESH_TOKEN_KEY_PREFIX = "refresh_token"


def _refresh_token_key(session_id: str) -> str:
    """构造 refresh token Redis key"""
    return f"{_REFRESH_TOKEN_KEY_PREFIX}:{session_id}"


async def store_refresh_token(session_id: str, refresh_token: str) -> None:
    """存储 refresh token 到 Redis

    Raises:
        Exception: Redis 不可用时抛出异常（fail-closed）
    """
    redis = await get_redis()
    key = _refresh_token_key(session_id)
    ttl_seconds = REFRESH_TOKEN_EXPIRATION_DAYS * 24 * 60 * 60
    await redis.set(key, refresh_token, ex=ttl_seconds)


async def get_stored_refresh_token(session_id: str) -> Optional[str]:
    """从 Redis 获取 refresh token

    Returns:
        refresh token 字符串，不存在返回 None

    Raises:
        Exception: Redis 不可用时抛出异常（fail-closed）
    """
    redis = await get_redis()
    key = _refresh_token_key(session_id)
    return await redis.get(key)


async def delete_refresh_token(session_id: str) -> None:
    """删除 Redis 中的 refresh token（单次使用后失效）

    Raises:
        Exception: Redis 不可用时抛出异常（fail-closed）
    """
    redis = await get_redis()
    key = _refresh_token_key(session_id)
    await redis.delete(key)
