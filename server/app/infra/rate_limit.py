"""
基于 Redis 的 IP 速率限制

为 /api/login 和 /api/register 提供每 IP 每分钟请求次数限制。
Redis 不可用时 fail-open（不额外拦截），但认证/session Redis 失败仍返回 503。
"""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def _get_rate_limit_redis():
    """获取 Redis 连接"""
    from app.store.session import get_redis
    return await get_redis()


async def check_rate_limit(ip: str) -> Optional[int]:
    """
    检查 IP 是否超过速率限制。

    Args:
        ip: 客户端 IP 地址

    Returns:
        None 表示通过（未超限或 Redis 不可用）。
        整数表示当前剩余次数（retry-after 秒数前不可再请求）。
    """
    limit = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "10"))
    if limit <= 0:
        return None  # 限速已禁用

    try:
        redis = await _get_rate_limit_redis()
        key = f"rate_limit:{ip}"
        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, 60)  # 首次请求设置 60 秒过期
        if current > limit:
            return 60  # 返回 retry-after 秒数
        return None  # 未超限
    except Exception as e:
        # Redis 不可用时 fail-open，不拦截请求
        logger.warning("Rate limit Redis check failed (fail-open): %s", e)
        return None
