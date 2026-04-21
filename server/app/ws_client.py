"""
WebSocket Client 连接路由
"""
import asyncio
import base64
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import WebSocketDisconnect, HTTPException

from app.crypto import get_crypto_manager, encrypt_message, decrypt_message, should_encrypt
from app.session import (
    get_session,
    get_session_by_device_id,
    get_session_terminal,
    get_terminal_output_history,
    update_session_view_count,
    update_session_pty_size,
    update_session_terminal_pty,
    update_session_terminal_views,
)
from app.ws_agent import (
    get_agent_connection,
    is_agent_connected,
    request_agent_terminal_snapshot,
)
from app.ws_auth import wait_for_ws_auth, http_to_ws_code, MAX_WS_MESSAGE_SIZE

logger = logging.getLogger(__name__)


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
        self.aes_key: Optional[bytes] = None  # 该连接的 AES 会话密钥

    async def send(self, message: dict):
        """发送消息到 Client（自动加密）"""
        try:
            msg_type = message.get("type", "")
            if self.aes_key and should_encrypt(msg_type):
                message = encrypt_message(self.aes_key, message)
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
    channel_key: str,
    view_type: str,
    exclude_conn: Optional[ClientConnection] = None,
) -> Optional[ClientConnection]:
    """在同一 channel 内查找同 view_type 的已有 Client。"""
    for client in active_clients.get(channel_key, []):
        if client.view_type == view_type and client is not exclude_conn:
            return client
    return None


async def client_websocket_handler(
    websocket,
    session_id: Optional[str],
    view: str = "mobile",
    device_id: Optional[str] = None,
    terminal_id: Optional[str] = None,
):
    """
    Client WebSocket 连接处理器

    Args:
        websocket: WebSocket 连接
        session_id: 会话 ID
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

    # 等待首条 auth 消息并验证 token
    try:
        payload, auth_msg = await wait_for_ws_auth(websocket)
    except (WebSocketDisconnect, Exception):
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
        await websocket.close(code=http_to_ws_code(e.status_code), reason=e.detail)
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

    # 解密 AES 会话密钥（从 auth 原始消息中提取，不在 JWT payload 里）
    encrypted_aes_key = auth_msg.pop("encrypted_aes_key", None)
    if encrypted_aes_key:
        try:
            client_conn.aes_key = get_crypto_manager().rsa_decrypt(encrypted_aes_key)
            logger.info("Client AES key established: session_id=%s view=%s", session_id, view)
        except Exception as e:
            logger.warning("Failed to decrypt Client AES key: session_id=%s error=%s", session_id, e)

    # 不变量 #27 服务端守卫：非 TLS 连接（ws://）必须携带 AES 密钥
    forwarded_proto = dict(websocket.headers).get("x-forwarded-proto", "")
    if forwarded_proto != "https" and not client_conn.aes_key:
        logger.warning("ws:// connection rejected: no AES key, session_id=%s", session_id)
        await websocket.close(code=4003, reason="ws:// requires encrypted_aes_key")
        return

    active_clients[channel_key].append(client_conn)
    logger.info(
        "Client connected: session_id=%s view=%s device_id=%s terminal_id=%s",
        session_id, view, resolved_device_id, terminal_id,
    )

    # 检测同端已有连接，直接踢出
    existing_client = _find_client_by_view_type(
        channel_key,
        view,
        exclude_conn=client_conn,
    )
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
        connected_terminal_status = terminal.get("status") if terminal else None
        connected_terminal_pty = (
            (terminal.get("pty") if terminal else None)
            or session.get("pty")
            or {"rows": 24, "cols": 80}
        )
        connected_views = {"mobile": 0, "desktop": 0}
        connected_geometry_owner_view = None
        connected_attach_epoch = 0
        connected_recovery_epoch = 0

        try:
            await update_session_view_count(session_id, view, 1)
        except Exception as e:
            logger.warning(f"Failed to update view count: {e}")

        if terminal_id:
            terminal = await update_session_terminal_views(
                session_id,
                terminal_id,
                views=get_view_counts(session_id, terminal_id),
                preferred_owner_view=view,
            )
            connected_terminal_status = terminal.get("status")
            connected_terminal_pty = terminal.get("pty") or connected_terminal_pty
            connected_views = terminal.get("views") or connected_views
            connected_geometry_owner_view = terminal.get("geometry_owner_view")
            connected_attach_epoch = int(terminal.get("attach_epoch", 0) or 0)
            connected_recovery_epoch = int(terminal.get("recovery_epoch", 0) or 0)

        # 发送连接成功消息（符合 CONTRACT-003）
        await websocket.send_json({
            "type": "connected",
            "session_id": session_id,
            "device_id": resolved_device_id,
            "terminal_id": terminal_id,
            "device_online": agent_online,
            "terminal_status": connected_terminal_status,
            "agent_online": agent_online,
            "view": view,
            "owner": owner,
            "views": connected_views,
            "geometry_owner_view": connected_geometry_owner_view,
            "pty": connected_terminal_pty,
            "attach_epoch": connected_attach_epoch,
            "recovery_epoch": connected_recovery_epoch,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        if terminal_id:
            await _send_terminal_snapshot(websocket, session_id, terminal_id)

        # 广播 presence 更新
        await _broadcast_presence(session_id, terminal_id)

        # 消息处理循环
        async for raw_text in websocket.iter_text():
            if not raw_text or not raw_text.strip():
                continue
            if len(raw_text) > MAX_WS_MESSAGE_SIZE:
                await websocket.send_json({"type": "error", "message": "Message too large"})
                continue
            try:
                message = json.loads(raw_text)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            # 解密 AES 加密消息
            if message.get("encrypted") and client_conn.aes_key:
                try:
                    message = decrypt_message(client_conn.aes_key, message)
                except Exception as e:
                    logger.warning(
                        "Client message decrypt failed: session_id=%s error=%s",
                        session_id, e,
                    )
                    continue

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
                "type": "resize",
                "source_view": view,
                "terminal_id": terminal_id,
                "rows": rows,
                "cols": cols,
            })
            await broadcast_to_clients(
                session_id,
                {
                    "type": "resize",
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
            "type": "error",
            "message": f"Unknown message type: {msg_type}",
        })


async def _send_terminal_snapshot(websocket, session_id: str, terminal_id: str) -> None:
    terminal = await get_session_terminal(session_id, terminal_id)
    attach_epoch = int((terminal or {}).get("attach_epoch", 0) or 0)
    recovery_epoch = int((terminal or {}).get("recovery_epoch", 0) or 0)

    await websocket.send_json({
        "type": "snapshot_start",
        "terminal_id": terminal_id,
        "attach_epoch": attach_epoch,
        "recovery_epoch": recovery_epoch,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    snapshot_data = await request_agent_terminal_snapshot(session_id, terminal_id)
    if snapshot_data:
        await websocket.send_json({
            "type": "snapshot_chunk",
            "terminal_id": terminal_id,
            "attach_epoch": attach_epoch,
            "recovery_epoch": recovery_epoch,
            "payload": snapshot_data["payload"],
            "pty": snapshot_data.get("pty"),
            "active_buffer": snapshot_data.get("active_buffer", "main"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    else:
        # history 只作为诊断级降级兜底，不再是主恢复源
        records = await get_terminal_output_history(session_id, terminal_id, limit=2000)
        chunk = ""
        max_chunk_size = 32 * 1024
        for record in records:
            data = record.get("data", "")
            if not data:
                continue
            if len(chunk) + len(data) > max_chunk_size and chunk:
                await websocket.send_json({
                    "type": "snapshot_chunk",
                    "terminal_id": terminal_id,
                    "attach_epoch": attach_epoch,
                    "recovery_epoch": recovery_epoch,
                    "payload": base64.b64encode(chunk.encode("utf-8")).decode("utf-8"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                chunk = ""
            chunk += data

        if chunk:
            await websocket.send_json({
                "type": "snapshot_chunk",
                "terminal_id": terminal_id,
                "attach_epoch": attach_epoch,
                "recovery_epoch": recovery_epoch,
                "payload": base64.b64encode(chunk.encode("utf-8")).decode("utf-8"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
    await websocket.send_json({
        "type": "snapshot_complete",
        "terminal_id": terminal_id,
        "attach_epoch": attach_epoch,
        "recovery_epoch": recovery_epoch,
        "timestamp": datetime.now(timezone.utc).isoformat(),
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

    if terminal_id:
        terminal = await get_session_terminal(session_id, terminal_id)
        if terminal and terminal.get("status") != "closed":
            await update_session_terminal_views(
                session_id,
                terminal_id,
                views=get_view_counts(session_id, terminal_id),
            )

    # 广播 presence 更新
    await _broadcast_presence(session_id, terminal_id)


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
    geometry_owner_view = None
    if terminal_id:
        terminal = await get_session_terminal(session_id, terminal_id)
        if terminal:
            geometry_owner_view = terminal.get("geometry_owner_view")
    message = {
        "type": "presence",
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
