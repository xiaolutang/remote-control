"""
WebSocket Client 连接路由

拆分后的入口模块，负责 handler 注册和生命周期管理。
所有子模块（client_connection、client_message_handler、client_snapshot、client_presence）
直接从源模块导入依赖，不再通过本模块 re-export 中转。

S515: 将 client_websocket_handler 拆分为阶段函数：
- _ws_auth_phase: 鉴权阶段
- _ws_session_resolve: 终端查找/会话解析阶段
- _ws_register_client: 客户端注册（AES 密钥协商 + 踢出旧设备）
- _ws_message_loop: 消息循环
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
from app.store.session_normalize import _reconcile_terminals

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 阶段 1: 鉴权
# ---------------------------------------------------------------------------

async def _ws_auth_phase(websocket) -> tuple:
    """WS 鉴权阶段：accept 连接、验证 token。

    Returns:
        (payload, auth_msg) 元组，鉴权失败返回 (None, None)。
    """
    await websocket.accept()
    try:
        payload, auth_msg = await wait_for_ws_auth(websocket)
    except (WebSocketDisconnect, Exception):
        return None, None

    token_session_id = payload.get("session_id")
    if not token_session_id:
        logger.warning("Token missing session_id")
        await websocket.close(code=4003, reason="Token missing session_id")
        return None, None

    return payload, auth_msg


# ---------------------------------------------------------------------------
# 阶段 2: 会话/终端查找
# ---------------------------------------------------------------------------

class _SessionResolveResult:
    """会话解析结果。"""
    __slots__ = ("session", "session_id", "device_id", "terminal_id", "terminal")

    def __init__(self, session, session_id, device_id, terminal_id, terminal):
        self.session = session
        self.session_id = session_id
        self.device_id = device_id
        self.terminal_id = terminal_id
        self.terminal = terminal


async def _ws_session_resolve(
    websocket,
    payload: dict,
    session_id: Optional[str],
    device_id: Optional[str],
    terminal_id: Optional[str],
) -> Optional[_SessionResolveResult]:
    """WS 会话解析阶段：查找会话和终端信息。

    Returns:
        _SessionResolveResult 或 None（解析失败时已关闭 websocket）。
    """
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
        logger.warning("Get session failed: %s", e.detail)
        await websocket.close(code=http_to_ws_code(e.status_code), reason=e.detail)
        return None
    except Exception as e:
        logger.error("Get session error: %s: %s", type(e).__name__, e)
        await websocket.close(code=4500, reason=str(e))
        return None

    resolved_device_id = device_id or session.get("device", {}).get("device_id", session_id)

    # B059: 从已获取的 session 中提取 terminal 信息，避免额外 Redis 读取
    terminal = None
    if terminal_id:
        # 防御性 reconcile：确保过期/detached terminal 被标记为 closed
        _reconcile_terminals(session.get("terminals", []))
        for t in session.get("terminals", []):
            if t.get("terminal_id") == terminal_id:
                terminal = t
                break
        if not terminal:
            await websocket.close(code=4004, reason=f"terminal {terminal_id} 不存在")
            return None
        if terminal.get("status") == "closed":
            await websocket.close(code=4009, reason="terminal closed")
            return None

    return _SessionResolveResult(
        session=session,
        session_id=session_id,
        device_id=resolved_device_id,
        terminal_id=terminal_id,
        terminal=terminal,
    )


# ---------------------------------------------------------------------------
# 阶段 3: 客户端注册（AES 密钥协商 + 踢出旧设备）
# ---------------------------------------------------------------------------

async def _ws_register_client(
    websocket,
    resolve: _SessionResolveResult,
    view: str,
    auth_msg: dict,
) -> Optional[ClientConnection]:
    """WS 客户端注册阶段：创建连接对象、AES 密钥协商、踢出旧设备。

    Returns:
        ClientConnection 或 None（注册失败时已关闭 websocket）。
    """
    session_id = resolve.session_id
    terminal_id = resolve.terminal_id
    resolved_device_id = resolve.device_id

    channel_key = _channel_key(session_id, terminal_id)

    # 检查客户端数量限制
    if channel_key not in active_clients:
        active_clients[channel_key] = []

    if len(active_clients[channel_key]) >= MAX_CLIENTS_PER_SESSION:
        await websocket.close(code=4503, reason="Too many clients for this session")
        return None

    # 创建连接对象
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
        return None

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
            logger.debug(
                "Failed to kick old client: session_id=%s view=%s old_device=%s",
                session_id, view, existing_client.device_id,
                exc_info=True,
            )

    return client_conn


# ---------------------------------------------------------------------------
# 阶段 4: 消息循环
# ---------------------------------------------------------------------------

async def _ws_message_loop(
    websocket,
    client_conn: ClientConnection,
    resolve: _SessionResolveResult,
    view: str,
    agent_online: bool,
    payload: dict,
) -> None:
    """WS 消息循环阶段：发送连接成功消息、处理消息、断开时清理。"""
    session = resolve.session
    session_id = resolve.session_id
    terminal_id = resolve.terminal_id
    terminal = resolve.terminal

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
            logger.warning("Failed to update view count: %s", e)
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
            "device_id": resolve.device_id,
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


# ---------------------------------------------------------------------------
# 编排入口
# ---------------------------------------------------------------------------

async def client_websocket_handler(
    websocket,
    session_id: Optional[str],
    view: str = "mobile",
    device_id: Optional[str] = None,
    terminal_id: Optional[str] = None,
):
    """
    Client WebSocket 连接处理器（S515: 阶段调度编排）。

    阶段:
        1. 鉴权 (_ws_auth_phase)
        2. 会话/终端查找 (_ws_session_resolve)
        3. 客户端注册 (_ws_register_client)
        4. 消息循环 (_ws_message_loop)

    Args:
        websocket: WebSocket 连接
        session_id: 会话 ID
        view: 视图类型 (mobile/desktop)
        device_id: 设备 ID
        terminal_id: 终端 ID
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

    # 阶段 1: 鉴权
    payload, auth_msg = await _ws_auth_phase(websocket)
    if payload is None:
        return

    # 阶段 2: 会话/终端查找
    resolve = await _ws_session_resolve(websocket, payload, session_id, device_id, terminal_id)
    if resolve is None:
        return

    agent_online = is_agent_connected(resolve.session_id)

    # 阶段 3: 客户端注册（AES 密钥协商 + 踢出旧设备）
    client_conn = await _ws_register_client(websocket, resolve, view, auth_msg)
    if client_conn is None:
        return

    # 阶段 4: 消息循环
    await _ws_message_loop(websocket, client_conn, resolve, view, agent_online, payload)


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
        logger.warning("Failed to update view count: %s", e)

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
