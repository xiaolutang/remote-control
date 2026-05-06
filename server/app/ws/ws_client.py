"""
WebSocket Client 连接路由

拆分后的入口模块，负责 handler 注册和生命周期管理。
所有子模块（client_connection、client_message_handler、client_snapshot、client_presence）
直接从源模块导入依赖，不再通过本模块 re-export 中转。
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import WebSocketDisconnect, HTTPException

from app.infra.crypto import get_crypto_manager, decrypt_message, should_encrypt
from app.infra.message_types import MessageType
from app.store.session import (
    get_session,
    get_session_by_device_id,
    get_session_terminal,
    update_session_view_count,
    update_session_terminal_views,
)
from app.ws.agent_connection import (
    is_agent_connected,
)
from app.ws.ws_auth import (
    wait_for_ws_auth,
    http_to_ws_code,
    MAX_WS_MESSAGE_SIZE,
    is_secure_websocket_transport,
)

# 子模块导入：handler 自身使用
from app.ws.client_connection import (
    ClientConnection,
    active_clients,
    MAX_CLIENTS_PER_SESSION,
    _channel_key,
    _unregister_client,
    _find_client_by_view_type,
)
from app.ws.client_message_handler import (
    _handle_client_message,
)
from app.ws.client_snapshot import (
    _send_terminal_snapshot,
)
from app.ws.client_presence import (
    get_view_counts,
    broadcast_to_clients,
    _broadcast_presence,
)

logger = logging.getLogger(__name__)


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
    if not is_secure_websocket_transport(websocket) and not client_conn.aes_key:
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
                "type": MessageType.DEVICE_KICKED,
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
            "type": MessageType.CONNECTED,
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
                await websocket.send_json({"type": MessageType.ERROR, "message": "Message too large"})
                continue
            try:
                message = json.loads(raw_text)
            except json.JSONDecodeError:
                await websocket.send_json({"type": MessageType.ERROR, "message": "Invalid JSON"})
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
