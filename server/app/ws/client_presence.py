"""
Client Presence 管理 — 视图计数、广播、presence 更新
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from app.infra.message_types import MessageType
from app.store.session import get_session_terminal
from app.ws.agent_connection import get_agent_connection
from app.ws.client_connection import (
    ClientConnection,
    active_clients,
    _channel_key,
    _matches_session,
)

logger = logging.getLogger(__name__)


def get_view_counts(session_id: str, terminal_id: Optional[str] = None) -> dict:
    """
    获取各视图类型的连接数

    Args:
        session_id: 会话 ID

    Returns:
        {"mobile": count, "desktop": count}
    """
    clients = active_clients.get(_channel_key(session_id, terminal_id), [])
    counts = {"mobile": 0, "desktop": 0}
    for client in clients:
        view_type = getattr(client, "view_type", "mobile")
        if view_type in counts:
            counts[view_type] += 1
    return counts


async def broadcast_to_clients(session_id: str, message: dict, terminal_id: Optional[str] = None):
    """
    广播消息到所有连接的 Client

    Args:
        session_id: 会话 ID
        message: 消息内容
        terminal_id: 终端 ID，如果为 None 则广播到该 session 下的所有客户端
    """
    logger.debug(f"[broadcast_to_clients] session={session_id} terminal_id={terminal_id} msg_type={message.get('type')} active_channels={list(active_clients.keys())}")
    if terminal_id is None:
        # 广播到该 session 下的所有频道（包括 session 级别和所有终端级别）
        sent_clients = set()
        for channel_key, clients in active_clients.items():
            if _matches_session(channel_key, session_id):
                logger.debug(f"[broadcast_to_clients] matched channel={channel_key} clients={len(clients)}")
                for client in clients:
                    # 避免重复发送（同一个客户端可能在多个频道）
                    if client not in sent_clients:
                        await client.send(message)
                        sent_clients.add(client)
        logger.debug(f"[broadcast_to_clients] sent to {len(sent_clients)} unique clients")
    else:
        # 只广播到特定终端频道
        clients = active_clients.get(_channel_key(session_id, terminal_id), [])
        for client in clients:
            await client.send(message)


async def _broadcast_presence(session_id: str, terminal_id: Optional[str] = None):
    """
    广播 presence 更新到所有客户端

    Args:
        session_id: 会话 ID
    """
    view_counts = get_view_counts(session_id, terminal_id)
    geometry_owner_view = None
    if terminal_id:
        terminal = await get_session_terminal(session_id, terminal_id)
        if terminal:
            geometry_owner_view = terminal.get("geometry_owner_view")
    message = {
        "type": MessageType.PRESENCE,
        "terminal_id": terminal_id,
        "views": view_counts,
        "geometry_owner_view": geometry_owner_view,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await broadcast_to_clients(session_id, message, terminal_id)

    # 同时通知 Agent
    agent_conn = get_agent_connection(session_id)
    if agent_conn:
        await agent_conn.send(message)
