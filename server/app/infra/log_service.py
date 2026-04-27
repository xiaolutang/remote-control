"""
客户端日志存储服务

日志存储在 Redis List 中，每个会话最多保留 1000 条日志。
"""
import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Literal
from fastapi import HTTPException, status

from app.store.session import redis_conn, _validate_session_id

# 日志键名前缀
LOG_KEY_PREFIX = "rc:logs"

# 每个会话最大日志条数
MAX_LOGS_PER_SESSION = 1000

# 日志级别类型
LogLevel = Literal["debug", "info", "warn", "error", "fatal"]

# 级别权重（用于过滤）
LEVEL_WEIGHTS = {
    "debug": 0,
    "info": 1,
    "warn": 2,
    "error": 3,
    "fatal": 4,
}


def _log_key(session_id: str) -> str:
    """生成日志存储键"""
    return f"{LOG_KEY_PREFIX}:{session_id}"


def _validate_level(level: str) -> LogLevel:
    """验证日志级别"""
    if level not in LEVEL_WEIGHTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效日志级别: {level}，有效值: debug/info/warn/error/fatal",
        )
    return level


async def append_log(
    session_id: str,
    level: LogLevel,
    message: str,
    timestamp: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> dict:
    """
    追加一条日志

    Args:
        session_id: 会话 ID
        level: 日志级别
        message: 日志消息
        timestamp: 时间戳（可选，默认当前时间）
        metadata: 元数据（可选）

    Returns:
        包含 timestamp 和 index 的字典
    """
    _validate_session_id(session_id)
    _validate_level(level)

    redis = await redis_conn.get_redis()
    log_key = _log_key(session_id)

    # 使用提供的时间戳或生成当前时间
    ts = timestamp or datetime.now(timezone.utc).isoformat()

    record = {
        "level": level,
        "message": message,
        "timestamp": ts,
        "metadata": metadata or {},
    }

    # 添加到列表头部（最新的在前）
    await redis.lpush(log_key, json.dumps(record))

    # 检查并清理超出限制的旧日志
    count = await redis.llen(log_key)
    if count > MAX_LOGS_PER_SESSION:
        # 保留最新的 MAX_LOGS_PER_SESSION 条
        await redis.ltrim(log_key, 0, MAX_LOGS_PER_SESSION - 1)

    return {
        "timestamp": ts,
        "level": level,
    }


async def append_logs_batch(
    session_id: str,
    logs: List[Dict[str, Any]],
) -> dict:
    """
    批量追加日志

    Args:
        session_id: 会话 ID
        logs: 日志列表，每条包含 level/message/timestamp/metadata

    Returns:
        包含 received 数量的字典
    """
    _validate_session_id(session_id)

    if not logs:
        return {"received": 0}

    redis = await redis_conn.get_redis()
    log_key = _log_key(session_id)

    # 验证并准备所有日志记录
    records = []
    for log in logs:
        level = _validate_level(log.get("level", "info"))
        record = {
            "level": level,
            "message": log.get("message", ""),
            "timestamp": log.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            "metadata": log.get("metadata") or {},
        }
        records.append(json.dumps(record))

    # 批量添加
    if records:
        await redis.lpush(log_key, *records)

    # 清理超出限制的旧日志
    count = await redis.llen(log_key)
    if count > MAX_LOGS_PER_SESSION:
        await redis.ltrim(log_key, 0, MAX_LOGS_PER_SESSION - 1)

    # 通知订阅者
    for record_str in records:
        record = json.loads(record_str)
        await notify_log_subscribers(session_id, record)

    return {"received": len(records)}


async def get_logs(
    session_id: str,
    level: Optional[LogLevel] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    offset: int = 0,
    limit: int = 100,
) -> Dict[str, Any]:
    """
    查询日志

    Args:
        session_id: 会话 ID
        level: 过滤级别（最小级别，如 warn 表示 warn/error/fatal）
        since: 起始时间（ISO8601）
        until: 结束时间（ISO8601）
        offset: 偏移量
        limit: 限制数量（最大 500）

    Returns:
        包含 session_id/total/offset/limit/logs 的字典
    """
    _validate_session_id(session_id)

    if level:
        _validate_level(level)

    if offset < 0:
        offset = 0

    if limit <= 0 or limit > 500:
        limit = min(max(limit, 1), 500)

    redis = await redis_conn.get_redis()
    log_key = _log_key(session_id)

    # 获取所有日志
    all_logs = await redis.lrange(log_key, 0, -1)

    # 解析并过滤
    filtered_logs = []
    min_level_weight = LEVEL_WEIGHTS.get(level, 0) if level else 0

    for log_str in all_logs:
        log_data = json.loads(log_str)
        log_level = log_data.get("level", "info")

        # 级别过滤
        if level and LEVEL_WEIGHTS.get(log_level, 0) < min_level_weight:
            continue

        # 时间过滤
        log_ts = log_data.get("timestamp", "")
        if since and log_ts < since:
            continue
        if until and log_ts > until:
            continue

        filtered_logs.append(log_data)

    # 分页
    total = len(filtered_logs)
    paginated = filtered_logs[offset:offset + limit]

    return {
        "session_id": session_id,
        "total": total,
        "offset": offset,
        "limit": limit,
        "logs": paginated,
    }


async def get_log_count(session_id: str) -> int:
    """
    获取日志总数

    Args:
        session_id: 会话 ID

    Returns:
        日志数量
    """
    _validate_session_id(session_id)

    redis = await redis_conn.get_redis()
    log_key = _log_key(session_id)

    return await redis.llen(log_key)


async def clear_logs(session_id: str) -> int:
    """
    清除会话的所有日志

    Args:
        session_id: 会话 ID

    Returns:
        删除的日志数量
    """
    _validate_session_id(session_id)

    redis = await redis_conn.get_redis()
    log_key = _log_key(session_id)

    count = await redis.llen(log_key)
    if count > 0:
        await redis.delete(log_key)

    return count


# 用于实时日志流的订阅者管理
_log_subscribers: Dict[str, List] = {}


async def subscribe_logs(session_id: str, callback):
    """
    订阅日志更新

    Args:
        session_id: 会话 ID
        callback: 回调函数
    """
    if session_id not in _log_subscribers:
        _log_subscribers[session_id] = []
    _log_subscribers[session_id].append(callback)


async def unsubscribe_logs(session_id: str, callback):
    """
    取消订阅日志更新

    Args:
        session_id: 会话 ID
        callback: 回调函数
    """
    if session_id in _log_subscribers:
        try:
            _log_subscribers[session_id].remove(callback)
            if not _log_subscribers[session_id]:
                del _log_subscribers[session_id]
        except ValueError:
            pass


async def notify_log_subscribers(session_id: str, log_record: dict):
    """
    通知日志订阅者

    Args:
        session_id: 会话 ID
        log_record: 日志记录
    """
    subscribers = _log_subscribers.get(session_id, [])
    for callback in subscribers:
        try:
            await callback(log_record)
        except Exception:
            pass
