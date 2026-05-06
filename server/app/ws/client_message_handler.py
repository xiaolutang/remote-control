"""
Client 消息处理 — DATA / RESIZE 等消息的转发与处理
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from app.infra.message_types import MessageType
from app.store.session import (
    get_session_terminal,
    update_session_pty_size,
    update_session_terminal_pty,
)
from app.ws.agent_connection import get_agent_connection
from app.ws.client_presence import broadcast_to_clients, get_view_counts

logger = logging.getLogger(__name__)


async def _handle_client_message(
    websocket,
    session_id: str,
    message: dict,
    view: str = "mobile",
    terminal_id: Optional[str] = None,
):
    """
    处理 Client 发来的消息

    Args:
        websocket: WebSocket 连接
        session_id: 会话 ID
        message: 消息内容
        view: 视图类型
    """
    msg_type = message.get("type")

    if msg_type == MessageType.DATA:
        # 用户输入数据，转发给 Agent
        payload = message.get("payload", "")

        # 获取 Agent 连接
        agent_conn = get_agent_connection(session_id)
        if agent_conn:
            await agent_conn.send({
                "type": MessageType.DATA,
                "source_view": view,
                "terminal_id": terminal_id,
                "payload": payload,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    elif msg_type == MessageType.RESIZE:
        # 终端窗口大小变化，转发给 Agent
        agent_conn = get_agent_connection(session_id)
        if agent_conn:
            if terminal_id:
                terminal = await get_session_terminal(session_id, terminal_id)
                if not terminal:
                    return
                geometry_owner_view = terminal.get("geometry_owner_view")
                if geometry_owner_view and geometry_owner_view != view:
                    return
            else:
                # session 级 PTY（无 terminal_id）为共享资源，
                # 桌面端优先控制尺寸，移动端在桌面端在线时让出
                view_counts = get_view_counts(session_id, terminal_id)
                if view == "mobile" and view_counts.get("desktop", 0) > 0:
                    return
            rows = message.get("rows", 24)
            cols = message.get("cols", 80)
            await update_session_pty_size(session_id, rows=rows, cols=cols)
            if terminal_id:
                await update_session_terminal_pty(
                    session_id,
                    terminal_id,
                    rows=rows,
                    cols=cols,
                )
            await agent_conn.send({
                "type": MessageType.RESIZE,
                "source_view": view,
                "terminal_id": terminal_id,
                "rows": rows,
                "cols": cols,
            })
            await broadcast_to_clients(
                session_id,
                {
                    "type": MessageType.RESIZE,
                    "terminal_id": terminal_id,
                    "rows": rows,
                    "cols": cols,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                terminal_id=terminal_id,
            )

    else:
        # 未知消息类型
        await websocket.send_json({
            "type": MessageType.ERROR,
            "message": f"Unknown message type: {msg_type}",
        })
