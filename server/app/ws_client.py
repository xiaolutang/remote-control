"""
WebSocket Client 连接路由
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import WebSocketDisconnect, HTTPException

from app.auth import async_verify_token, TokenVerificationError
from app.session import (
    get_session,
    get_session_by_device_id,
    get_session_terminal,
    update_session_view_count,
    update_session_terminal_status,
)
from app.ws_agent import (
    get_agent_connection,
    is_agent_connected,
)

logger = logging.getLogger(__name__)


def _http_to_ws_code(http_code: int) -> int:
    """将 HTTP 状态码映射为有效的 WebSocket 关闭码"""
    mapping = {
        401: 4001,
        403: 4003,
        404: 4004,
        409: 4009,
        500: 4500,
        503: 4504,
    }
    return mapping.get(http_code, 4500)

# 活跃的 Client 连接
active_clients: dict[str, list] = {}  # channel_key -> [ClientConnection,...]

# 最大客户端数量
MAX_CLIENTS_PER_SESSION = 100


def _channel_key(session_id: str, terminal_id: Optional[str] = None) -> str:
    return f"{session_id}:{terminal_id}" if terminal_id else session_id


class ClientConnection:
    """Client 连接状态"""

    def __init__(
        self,
        session_id: str,
        websocket,
        view_type: str = "mobile",
        terminal_id: Optional[str] = None,
        device_id: Optional[str] = None,
    ):
        self.session_id = session_id
        self.terminal_id = terminal_id
        self.device_id = device_id
        self.websocket = websocket
        self.view_type = view_type  # mobile 或 desktop
        self.connected_at = datetime.now(timezone.utc)

    async def send(self, message: dict):
        """发送消息到 Client"""
        try:
            await self.websocket.send_json(message)
        except Exception:
            pass


def _matches_session(channel_key: str, session_id: str) -> bool:
    """判断 channel_key 是否属于指定 session（session_id 或 session_id:xxx）"""
    return channel_key == session_id or channel_key.startswith(f"{session_id}:")


def _unregister_client(channel_key: str, client_conn: ClientConnection):
    """从 active_clients 中移除 client，列表为空时删除 key"""
    if channel_key not in active_clients:
        return
    try:
        active_clients[channel_key].remove(client_conn)
    except ValueError:
        pass
    if not active_clients[channel_key]:
        del active_clients[channel_key]


def _find_client_by_view_type(
    session_id: str,
    view_type: str,
    exclude_conn: Optional[ClientConnection] = None,
) -> Optional[ClientConnection]:
    """在所有 channel_key 中查找同 session 同 view_type 的已有 Client"""
    for channel_key, clients in active_clients.items():
        if _matches_session(channel_key, session_id):
            for client in clients:
                if client.view_type == view_type and client is not exclude_conn:
                    return client
    return None


async def client_websocket_handler(
    websocket,
    session_id: Optional[str],
    token: str,
    view: str = "mobile",
    device_id: Optional[str] = None,
    terminal_id: Optional[str] = None,
):
    """
    Client WebSocket 连接处理器

    Args:
        websocket: WebSocket 连接
        session_id: 会话 ID
        token: JWT Token
        view: 视图类型 (mobile/desktop)
    """
    logger.debug(
        "Client WebSocket connecting: session_id=%s device_id=%s terminal_id=%s view=%s",
        session_id,
        device_id,
        terminal_id,
        view,
    )

    # 验证 view 参数
    if view not in ["mobile", "desktop"]:
        await websocket.close(code=4400, reason=f"Invalid view type: {view}")
        return

    # 先 accept 连接
    await websocket.accept()

    # 验证 Token
    try:
        payload = await async_verify_token(token)
    except TokenVerificationError as e:
        # TokenVerificationError 携带 error_code，优先使用
        reason = e.error_code if e.error_code else e.detail
        logger.warning(f"Token verification failed: {reason}")
        await websocket.close(code=_http_to_ws_code(e.status_code), reason=reason)
        return
    except HTTPException as e:
        logger.warning(f"Token verification failed: {e.detail}")
        await websocket.close(code=_http_to_ws_code(e.status_code), reason=e.detail)
        return
    except Exception as e:
        logger.warning(f"Token verification error: {type(e).__name__}: {e}")
        await websocket.close(code=4500, reason=str(e))
        return

    # 注意：不再强制验证 URL 参数中的 session_id 与 token 中的一致性
    # 只要 token 有效且能获取到 session_id，就允许连接
    token_session_id = payload.get("session_id")
    if not token_session_id:
        logger.warning(f"Token missing session_id")
        await websocket.close(code=4003, reason="Token missing session_id")
        return

    # 获取会话信息
    try:
        if device_id:
            session = await get_session_by_device_id(device_id, payload.get("sub", ""))
            if not session:
                raise HTTPException(status_code=404, detail=f"device {device_id} 不存在")
            session_id = session["session_id"]
        else:
            session = await get_session(session_id)
    except HTTPException as e:
        logger.warning(f"Get session failed: {e.detail}")
        await websocket.close(code=_http_to_ws_code(e.status_code), reason=e.detail)
        return
    except Exception as e:
        logger.error(f"Get session error: {type(e).__name__}: {e}")
        await websocket.close(code=4500, reason=str(e))
        return

    resolved_device_id = device_id or session.get("device", {}).get("device_id", session_id)
    channel_key = _channel_key(session_id, terminal_id)

    terminal = None
    agent_online = is_agent_connected(session_id)
    if terminal_id:
        terminal = await get_session_terminal(session_id, terminal_id)
        if not terminal:
            await websocket.close(code=4004, reason=f"terminal {terminal_id} 不存在")
            return
        if terminal.get("status") == "closed":
            await websocket.close(code=4009, reason="terminal closed")
            return

    # --- 同端设备在线限制 ---
    # 新设备连接时，检测同端已有连接，直接踢出旧设备。
    # token_version 机制已在登录层保证旧设备的 HTTP 请求失效，
    # 此处仅处理 WS 层面的连接替换。

    # 检查客户端数量限制
    if channel_key not in active_clients:
        active_clients[channel_key] = []

    if len(active_clients[channel_key]) >= MAX_CLIENTS_PER_SESSION:
        await websocket.close(code=4503, reason="Too many clients for this session")
        return

    # 创建连接对象并注册
    client_conn = ClientConnection(
        session_id,
        websocket,
        view,
        terminal_id=terminal_id,
        device_id=resolved_device_id,
    )
    active_clients[channel_key].append(client_conn)
    logger.info(
        "Client connected: session_id=%s view=%s device_id=%s terminal_id=%s",
        session_id, view, resolved_device_id, terminal_id,
    )

    # 检测同端已有连接，直接踢出
    existing_client = _find_client_by_view_type(session_id, view, exclude_conn=client_conn)
    if existing_client:
        logger.info(
            "Kicking existing client: session_id=%s view=%s old_device=%s",
            session_id, view, existing_client.device_id,
        )
        # 先从 active_clients 移除，避免时间窗口内第三个设备重复踢出
        existing_channel = _channel_key(existing_client.session_id, existing_client.terminal_id)
        _unregister_client(existing_channel, existing_client)
        try:
            await existing_client.send({
                "type": "device_kicked",
                "reason": "replaced_by_new_device",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            await existing_client.websocket.close(code=4011, reason="replaced by new device")
        except Exception:
            pass  # 旧 Client 可能已经断开

    # --- 同端设备在线限制结束 ---

    try:
        # 获取 owner 信息
        owner = session.get("owner", payload.get("sub", ""))

        # 发送连接成功消息（符合 CONTRACT-003）
        await websocket.send_json({
            "type": "connected",
            "session_id": session_id,
            "device_id": resolved_device_id,
            "terminal_id": terminal_id,
            "device_online": agent_online,
            "terminal_status": terminal.get("status") if terminal else None,
            "agent_online": agent_online,
            "view": view,
            "owner": owner,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # 更新视图连接数
        try:
            await update_session_view_count(session_id, view, 1)
        except Exception as e:
            logger.warning(f"Failed to update view count: {e}")

        if terminal_id:
            await update_session_terminal_status(
                session_id,
                terminal_id,
                terminal_status="attached",
            )

        # 广播 presence 更新
        await _broadcast_presence(session_id, terminal_id)

        # 消息处理循环
        async for message in websocket.iter_json():
            await _handle_client_message(
                websocket,
                session_id,
                message,
                view,
                terminal_id=terminal_id,
            )

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(
            "Client connection error: session_id=%s view=%s error=%s",
            session_id, view, e, exc_info=True,
        )
    finally:
        # 清理连接
        await _cleanup_client(session_id, client_conn, view, terminal_id=terminal_id)


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

    if msg_type == "data":
        # 用户输入数据，转发给 Agent
        payload = message.get("payload", "")

        # 获取 Agent 连接
        agent_conn = get_agent_connection(session_id)
        if agent_conn:
            await agent_conn.send({
                "type": "data",
                "source_view": view,
                "terminal_id": terminal_id,
                "payload": payload,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    elif msg_type == "resize":
        # 终端窗口大小变化，转发给 Agent
        agent_conn = get_agent_connection(session_id)
        if agent_conn:
            rows = message.get("rows", 24)
            cols = message.get("cols", 80)
            await agent_conn.send({
                "type": "resize",
                "source_view": view,
                "terminal_id": terminal_id,
                "rows": rows,
                "cols": cols,
            })

    else:
        # 未知消息类型
        await websocket.send_json({
            "type": "error",
            "message": f"Unknown message type: {msg_type}",
        })


async def _cleanup_client(
    session_id: str,
    client_conn: ClientConnection,
    view: str = "mobile",
    terminal_id: Optional[str] = None,
):
    """
    清理 Client 连接

    Args:
        session_id: 会话 ID
        client_conn: 客户端连接对象
        view: 视图类型
    """
    channel_key = _channel_key(session_id, terminal_id)
    _unregister_client(channel_key, client_conn)

    # 更新视图连接数
    try:
        await update_session_view_count(session_id, view, -1)
    except Exception as e:
        logger.warning(f"Failed to update view count: {e}")

    # 广播 presence 更新
    await _broadcast_presence(session_id, terminal_id)
    if terminal_id and get_client_count(session_id, terminal_id) == 0:
        terminal = await get_session_terminal(session_id, terminal_id)
        if terminal and terminal.get("status") != "closed":
            await update_session_terminal_status(
                session_id,
                terminal_id,
                terminal_status="detached",
            )


async def broadcast_to_clients(session_id: str, message: dict, terminal_id: Optional[str] = None):
    """
    广播消息到所有连接的 Client

    Args:
        session_id: 会话 ID
        message: 消息内容
        terminal_id: 终端 ID，如果为 None 则广播到该 session 下的所有客户端
    """
    logger.info(f"[broadcast_to_clients] session={session_id} terminal_id={terminal_id} msg_type={message.get('type')} active_channels={list(active_clients.keys())}")
    if terminal_id is None:
        # 广播到该 session 下的所有频道（包括 session 级别和所有终端级别）
        sent_clients = set()
        for channel_key, clients in active_clients.items():
            if _matches_session(channel_key, session_id):
                logger.info(f"[broadcast_to_clients] matched channel={channel_key} clients={len(clients)}")
                for client in clients:
                    # 避免重复发送（同一个客户端可能在多个频道）
                    if client not in sent_clients:
                        await client.send(message)
                        sent_clients.add(client)
        logger.info(f"[broadcast_to_clients] sent to {len(sent_clients)} unique clients")
    else:
        # 只广播到特定终端频道
        clients = active_clients.get(_channel_key(session_id, terminal_id), [])
        for client in clients:
            await client.send(message)


def get_client_count(session_id: str, terminal_id: Optional[str] = None) -> int:
    """
    获取连接的 Client 数量

    Args:
        session_id: 会话 ID

    Returns:
        Client 数量
    """
    return len(active_clients.get(_channel_key(session_id, terminal_id), []))


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


async def _broadcast_presence(session_id: str, terminal_id: Optional[str] = None):
    """
    广播 presence 更新到所有客户端

    Args:
        session_id: 会话 ID
    """
    view_counts = get_view_counts(session_id, terminal_id)
    message = {
        "type": "presence",
        "terminal_id": terminal_id,
        "views": view_counts,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await broadcast_to_clients(session_id, message, terminal_id)

    # 同时通知 Agent
    agent_conn = get_agent_connection(session_id)
    if agent_conn:
        await agent_conn.send(message)
