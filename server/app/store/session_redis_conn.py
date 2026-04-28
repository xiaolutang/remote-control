"""
session 子模块 — Redis 连接管理。
"""
import logging
from typing import Optional

import redis.asyncio as aioredis
from fastapi import HTTPException, status

from app.store.session_types import REDIS_URL, REDIS_PASSWORD

logger = logging.getLogger(__name__)


class RedisConnection:
    """Redis 连接管理"""

    def __init__(self):
        self._pool: Optional[aioredis.Redis] = None
        self._redis: Optional[aioredis.Redis] = None

    async def get_redis(self) -> aioredis.Redis:
        """获取 Redis 连接"""
        if self._redis is None:
            try:
                self._pool = aioredis.ConnectionPool.from_url(
                    REDIS_URL,
                    password=REDIS_PASSWORD,
                    decode_responses=True,
                    max_connections=10,
                )
                self._redis = aioredis.Redis(connection_pool=self._pool)
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"Redis 连接失败: {e}",
                )
        return self._redis

    async def close(self):
        """关闭连接"""
        if self._pool:
            await self._pool.disconnect()


# 全局连接实例
redis_conn = RedisConnection()


async def get_redis():
    """获取 Redis 连接（模块级函数）"""
    return await redis_conn.get_redis()
