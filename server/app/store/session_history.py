"""
session 子模块 — output history CRUD。
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import HTTPException, status

from app.store.session_types import HISTORY_TTL_DAYS, _session_key, _history_key
from app.store.session_normalize import _validate_session_id
from app.store.session_redis_conn import redis_conn

logger = logging.getLogger(__name__)


async def append_history(
    session_id: str,
    data: str,
    direction: str = "output",
    terminal_id: Optional[str] = None,
) -> dict:
    """
    追加历史记录

    Args:
        session_id: 会话 ID
        data: 终端输出数据
        direction: 方向 (input/output)
        terminal_id: 关联的 terminal ID

    Returns:
        包含 timestamp 和 index 的字典
    """
    _validate_session_id(session_id)

    redis = await redis_conn.get_redis()
    history_key = _history_key(session_id)

    now = datetime.now(timezone.utc)
    record = {
        "timestamp": now.isoformat(),
        "direction": direction,
        "data": data,
        "terminal_id": terminal_id,
    }

    # 使用 LPUSH 添加到列表末尾
    index = await redis.rpush(history_key, json.dumps(record))

    # 设置过期时间
    ttl_seconds = HISTORY_TTL_DAYS * 24 * 60 * 60
    await redis.expire(history_key, ttl_seconds)

    return {
        "timestamp": record["timestamp"],
        "index": index - 1,  # LPUSH 返回的是列表长度，index 从 0 开始
    }


async def get_history(
    session_id: str,
    offset: int = 0,
    limit: int = 100,
    *,
    terminal_id: Optional[str] = None,
    direction: Optional[str] = None,
) -> List[dict]:
    """
    分页获取历史记录

    Args:
        session_id: 会话 ID
        offset: 偏移量
        limit: 限制数量 (最大 1000)
        terminal_id: 过滤指定 terminal
        direction: 过滤指定方向

    Returns:
        历史记录列表
    """
    _validate_session_id(session_id)

    if offset < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="offset 不能为负数",
        )

    if limit <= 0 or limit > 1000:
        limit = min(max(limit, 1), 1000)

    redis = await redis_conn.get_redis()
    history_key = _history_key(session_id)

    # 检查会话是否存在
    session_key = _session_key(session_id)
    if not await redis.exists(session_key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"会话 {session_id} 不存在",
        )

    total = await redis.llen(history_key)
    if total == 0:
        return []

    # 降级兜底路径，限制最大扫描量防止长 session 内存膨胀
    max_scan = min(total, 5000)
    records = [json.loads(r) for r in await redis.lrange(history_key, total - max_scan, total - 1)]

    if terminal_id is not None:
        records = [
            record for record in records if record.get("terminal_id") == terminal_id
        ]

    if direction is not None:
        records = [
            record for record in records if record.get("direction") == direction
        ]

    if offset >= len(records):
        return []

    end = min(offset + limit, len(records))
    return records[offset:end]


async def get_terminal_output_history(
    session_id: str,
    terminal_id: str,
    *,
    limit: int = 2000,
) -> List[dict]:
    """获取指定 terminal 的输出历史，用于诊断/降级兜底。"""
    return await get_history(
        session_id,
        offset=0,
        limit=limit,
        terminal_id=terminal_id,
        direction="output",
    )


async def get_history_count(session_id: str) -> int:
    """
    获取历史记录总数

    Args:
        session_id: 会话 ID

    Returns:
        历史记录数量
    """
    _validate_session_id(session_id)

    redis = await redis_conn.get_redis()
    history_key = _history_key(session_id)

    return await redis.llen(history_key)


async def cleanup_old_history(session_id: str, max_records: int = 100000) -> int:
    """
    清理旧的历史记录

    Args:
        session_id: 会话 ID
        max_records: 最大保留记录数

    Returns:
        删除的记录数
    """
    _validate_session_id(session_id)

    redis = await redis_conn.get_redis()
    history_key = _history_key(session_id)

    total = await redis.llen(history_key)
    if total <= max_records:
        return 0

    # 保留最新的 max_records 条
    # 使用 LTRIM 保留指定范围
    await redis.ltrim(history_key, -max_records, -1)

    return total - max_records
