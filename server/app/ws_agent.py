"""
WebSocket Agent 连接路由
"""
import asyncio
import json
import base64
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import WebSocketDisconnect, HTTPException, status

from app.crypto import get_crypto_manager, encrypt_message, decrypt_message, should_encrypt
from app.ws_auth import wait_for_ws_auth, http_to_ws_code, MAX_WS_MESSAGE_SIZE
import logging

logger = logging.getLogger(__name__)
from app.session import (
    get_session,
    set_session_online,
    set_session_offline,
    update_session_device_metadata,
    update_session_device_heartbeat,
    append_history,
    get_session_terminal,
    list_recoverable_session_terminals,
    update_session_terminal_status,
)

# 活跃的 Agent 连接
active_agents: dict[str, "AgentConnection"] = {}  # session_id -> connection
pending_terminal_creates: dict[tuple[str, str], asyncio.Future] = {}
pending_terminal_closes: dict[tuple[str, str], asyncio.Future] = {}

# Stale Agent 追踪（TTL 机制）
# session_id -> 过期时间（datetime）
stale_agents: dict[str, datetime] = {}

# 心跳配置
HEARTBEAT_INTERVAL = 30  # 秒
HEARTBEAT_TIMEOUT = 60  # 秒

# Stale TTL 配置
STALE_TTL_SECONDS = 90  # Agent 断开后等待 90 秒才真正 offline


class AgentConnection:
    """Agent 连接状态"""

    def __init__(self, session_id: str, websocket, owner: str = ""):
        self.session_id = session_id
        self.websocket = websocket
        self.owner = owner
        self.last_heartbeat = datetime.now(timezone.utc)
        self.connected_at = datetime.now(timezone.utc)
        self.aes_key: bytes | None = None  # 该连接的 AES 会话密钥

    async def send(self, message: dict):
        """发送消息到 Agent（自动加密）"""
        msg_type = message.get("type", "")
        if self.aes_key and should_encrypt(msg_type):
            message = encrypt_message(self.aes_key, message)
        await self.websocket.send_json(message)

    def update_heartbeat(self):
        """更新心跳时间"""
        self.last_heartbeat = datetime.now(timezone.utc)

    def is_alive(self) -> bool:
        """检查连接是否存活"""
        elapsed = (datetime.now(timezone.utc) - self.last_heartbeat).total_seconds()
        return elapsed < HEARTBEAT_TIMEOUT


async def agent_websocket_handler(
    websocket,
):
    """
    Agent WebSocket 连接处理器

    Args:
        websocket: WebSocket 连接
    """
    # 先 accept 连接
    await websocket.accept()

    # 等待首条 auth 消息并验证 token
    try:
        payload, auth_msg = await wait_for_ws_auth(websocket)
    except (WebSocketDisconnect, Exception):
        return

    session_id = payload["session_id"]

    # 检查是否已有 Agent 连接
    if session_id in active_agents:
        await websocket.close(code=4009, reason="Session already has an active agent")
        return

    # 如果 Agent 处于 stale 状态，恢复它（清除 stale 标记，继续正常连接）
    if _is_agent_stale(session_id):
        _clear_agent_stale(session_id)
        logger.info("Agent recovered from stale: session_id=%s", session_id)

    # 获取会话信息
    try:
        session = await get_session(session_id)
    except HTTPException as e:
        await websocket.close(code=http_to_ws_code(e.status_code), reason=e.detail)
        return

    owner = session.get("owner", payload.get("sub", ""))
    cleanup_reason = "agent_shutdown"

    # 创建连接对象
    agent_conn = AgentConnection(session_id, websocket, owner)

    # 解密 AES 会话密钥（从 auth 原始消息中提取，不在 JWT payload 里）
    encrypted_aes_key = auth_msg.pop("encrypted_aes_key", None)
    if encrypted_aes_key:
        try:
            agent_conn.aes_key = get_crypto_manager().rsa_decrypt(encrypted_aes_key)
            logger.info("Agent AES key established: session_id=%s", session_id)
        except Exception as e:
            logger.info("Failed to decrypt Agent AES key: session_id=%s error=%s", session_id, e)

    active_agents[session_id] = agent_conn
    logger.info(
        "Agent connected: session_id=%s owner=%s",
        session_id, owner,
    )

    # 原子更新：status=online + agent_online=True
    try:
        await set_session_online(session_id)
    except Exception:
        del active_agents[session_id]
        raise
    heartbeat_task = None

    try:
        # 获取当前视图连接数
        from app.ws_client import get_view_counts
        view_counts = get_view_counts(session_id)

        # 发送连接成功消息（符合 CONTRACT-002）
        await websocket.send_json({
            "type": "connected",
            "session_id": session_id,
            "owner": owner,
            "views": view_counts,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # 在 grace period 内恢复 detached terminals，避免 runtime 列表出现空壳。
        await _restore_recoverable_terminals(session_id, agent_conn)

        # 启动心跳检查任务
        heartbeat_task = asyncio.create_task(
            _heartbeat_checker(websocket, session_id)
        )

        # 消息处理循环
        async for raw_text in websocket.iter_text():
            if not raw_text or not raw_text.strip():
                logger.debug("Agent sent empty message: session_id=%s", session_id)
                continue
            if len(raw_text) > MAX_WS_MESSAGE_SIZE:
                logger.warning("Agent message too large: session_id=%s len=%d", session_id, len(raw_text))
                continue
            try:
                message = json.loads(raw_text)
            except json.JSONDecodeError as je:
                logger.warning(
                    "Agent sent invalid JSON: session_id=%s error=%s len=%d",
                    session_id, je, len(raw_text),
                )
                continue

            # 解密 AES 加密消息
            if message.get("encrypted") and agent_conn.aes_key:
                try:
                    message = decrypt_message(agent_conn.aes_key, message)
                except Exception as e:
                    logger.info(
                        "Agent decrypt FAIL: session_id=%s key=%s iv=%s data_len=%s error=%s",
                        session_id,
                        agent_conn.aes_key.hex()[:16],
                        message.get("iv", "")[:16],
                        len(message.get("data", "")),
                        e,
                    )
                    continue

            await _handle_agent_message(websocket, session_id, message)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("Agent connection error: session_id=%s error=%s", session_id, e, exc_info=True)
        cleanup_reason = "network_lost"
    finally:
        # 清理连接
        if heartbeat_task and heartbeat_task.done():
            try:
                timeout_reason = heartbeat_task.result()
                if timeout_reason:
                    cleanup_reason = timeout_reason
            except Exception:
                pass
        await _cleanup_agent(session_id, cleanup_reason)
        if heartbeat_task:
            heartbeat_task.cancel()


async def _handle_agent_message(websocket, session_id: str, message: dict):
    """
    处理 Agent 发来的消息

    Args:
        websocket: WebSocket 连接
        session_id: 会话 ID
        message: 消息内容
    """
    # 延迟导入避免循环依赖，但只在函数顶部导入一次
    from app.ws_client import broadcast_to_clients

    msg_type = message.get("type")

    if msg_type == "ping":
        # 心跳响应
        agent_conn = active_agents.get(session_id)
        if agent_conn:
            agent_conn.update_heartbeat()
            await update_session_device_heartbeat(session_id, online=True)
            await agent_conn.send({"type": "pong"})

    elif msg_type == "data":
        # 终端输出数据
        payload = message.get("payload", "")
        direction = message.get("direction", "output")
        terminal_id = message.get("terminal_id")

        # 追加到历史记录
        try:
            # 解码 base64 数据
            try:
                decoded_data = base64.b64decode(payload).decode("utf-8", errors="replace")
            except Exception:
                decoded_data = payload

            await append_history(session_id, decoded_data, direction)
        except Exception as e:
            logger.error("Failed to append history: session_id=%s error=%s", session_id, e)

        # 转发给所有 Client
        await broadcast_to_clients(session_id, {
            "type": "data",
            "terminal_id": terminal_id,
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, terminal_id=terminal_id)

    elif msg_type == "resize":
        # 终端窗口大小变化
        terminal_id = message.get("terminal_id")
        # 转发给所有 Client
        await broadcast_to_clients(session_id, {
            "type": "resize",
            "terminal_id": terminal_id,
            "rows": message.get("rows"),
            "cols": message.get("cols"),
        }, terminal_id=terminal_id)

    elif msg_type == "terminal_created":
        terminal_id = message.get("terminal_id")
        if terminal_id:
            terminal = await update_session_terminal_status(
                session_id,
                terminal_id,
                terminal_status="detached",
            )
            future = pending_terminal_creates.pop((session_id, terminal_id), None)
            if future and not future.done():
                future.set_result(terminal)
            # 广播终端创建通知给所有客户端（session 级别，不限制特定终端）
            await broadcast_to_clients(session_id, {
                "type": "terminals_changed",
                "action": "created",
                "terminal_id": terminal_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }, terminal_id=None)

    elif msg_type == "terminal_closed":
        terminal_id = message.get("terminal_id")
        if terminal_id:
            reason = message.get("reason", "terminal_exit")
            await update_session_terminal_status(
                session_id,
                terminal_id,
                terminal_status="closed",
                disconnect_reason=reason,
            )
            # 处理 create 等待中的 future（终端在创建过程中被关闭）
            create_future = pending_terminal_creates.pop((session_id, terminal_id), None)
            if create_future and not create_future.done():
                create_future.set_exception(RuntimeError(f"terminal {terminal_id} closed: {reason}"))
            # 处理 close 等待中的 future（正常关闭确认）
            close_future = pending_terminal_closes.pop((session_id, terminal_id), None)
            if close_future and not close_future.done():
                close_future.set_result({"terminal_id": terminal_id, "reason": reason})
            # 广播终端关闭通知给所有客户端（session 级别，不限制特定终端）
            await broadcast_to_clients(session_id, {
                "type": "terminals_changed",
                "action": "closed",
                "terminal_id": terminal_id,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }, terminal_id=None)

    elif msg_type == "agent_metadata":
        platform_name = (message.get("platform") or "").strip()
        hostname = (message.get("hostname") or "").strip()
        session = await get_session(session_id)
        current_name = (session.get("device", {}).get("name") or "").strip()
        await update_session_device_metadata(
            session_id,
            platform=platform_name or None,
            hostname=hostname or None,
            name=hostname if hostname and not current_name else None,
        )

    else:
        # 未知消息类型
        await websocket.send_json({
            "type": "error",
            "message": f"Unknown message type: {msg_type}",
        })


async def _heartbeat_checker(websocket, session_id: str):
    """
    心跳检查器

    定期检查 Agent 是否存活，超时则断开连接
    """
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)

        agent_conn = active_agents.get(session_id)
        if not agent_conn:
            break

        if not agent_conn.is_alive():
            logger.warning("Agent heartbeat timeout: session_id=%s", session_id)
            await websocket.close(code=1008, reason="Heartbeat timeout")
            return "network_lost"

    return None


def _cleanup_pending_futures(
    pending_dict: dict[tuple[str, str], asyncio.Future],
    session_id: str,
    reason: str,
) -> None:
    """清理指定 session 的所有 pending futures。"""
    for key, future in list(pending_dict.items()):
        pending_session_id, _ = key
        if pending_session_id != session_id:
            continue
        pending_dict.pop(key, None)
        if not future.done():
            future.set_exception(RuntimeError(f"agent disconnected: {reason}"))


async def _cleanup_agent(session_id: str, reason: str = "agent_shutdown"):
    """
    清理 Agent 连接

    将 Agent 标记为 stale 而非立即 offline，等待 TTL 过期。

    Args:
        session_id: 会话 ID
        reason: 断开原因
    """
    if session_id in active_agents:
        del active_agents[session_id]

    _cleanup_pending_futures(pending_terminal_creates, session_id, reason)
    _cleanup_pending_futures(pending_terminal_closes, session_id, reason)

    # 将 Agent 标记为 stale（等待 TTL 过期后再真正 offline）
    _mark_agent_stale(session_id)


def _mark_agent_stale(session_id: str):
    """
    将 Agent 标记为 stale 状态

    Args:
        session_id: 会话 ID
    """
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=STALE_TTL_SECONDS)
    stale_agents[session_id] = expires_at
    logger.info("Agent marked stale: session_id=%s expires_at=%s", session_id, expires_at.isoformat())


def _is_agent_stale(session_id: str) -> bool:
    """
    检查 Agent 是否处于 stale 状态

    Args:
        session_id: 会话 ID

    Returns:
        是否为 stale 状态
    """
    return session_id in stale_agents


def _clear_agent_stale(session_id: str):
    """
    清除 Agent 的 stale 状态

    Args:
        session_id: 会话 ID
    """
    if session_id in stale_agents:
        del stale_agents[session_id]
        logger.debug("Agent stale cleared: session_id=%s", session_id)


async def _expire_stale_agent(session_id: str):
    """
    过期 stale Agent，将其真正设为 offline

    Args:
        session_id: 会话 ID
    """
    if session_id in stale_agents:
        del stale_agents[session_id]

    # 原子更新：status=offline + agent_online=False + bulk close terminals
    try:
        await set_session_offline(session_id, reason="device_offline")
        logger.info("Agent expired from stale to offline: session_id=%s", session_id)
    except Exception as e:
        logger.error("Failed to expire stale agent: session_id=%s error=%s", session_id, e)


async def _stale_agent_ttl_checker():
    """
    Stale Agent TTL 检查器

    定期检查 stale_agents 中的 Agent 是否过期，过期则设为 offline
    """
    while True:
        await asyncio.sleep(10)  # 每 10 秒检查一次

        now = datetime.now(timezone.utc)
        expired_sessions = []

        for session_id, expires_at in stale_agents.items():
            if now >= expires_at:
                expired_sessions.append(session_id)

        for session_id in expired_sessions:
            await _expire_stale_agent(session_id)


async def _cleanup_agent_immediately(session_id: str):
    """
    立即清理 Agent（不经过 stale 状态）

    用于显式停止等场景。

    Args:
        session_id: 会话 ID
    """
    # 先清除 stale 状态
    _clear_agent_stale(session_id)

    # 原子更新：status=offline + agent_online=False + bulk close terminals
    try:
        await set_session_offline(session_id, reason="agent_shutdown")
    except Exception as e:
        logger.error("Failed to cleanup agent immediately: session_id=%s error=%s", session_id, e)


async def _restore_recoverable_terminals(session_id: str, agent_conn: AgentConnection):
    """在 agent 重连后恢复 grace period 内的 detached terminals。"""
    try:
        terminals = await list_recoverable_session_terminals(session_id)
    except Exception:
        return

    for terminal in terminals:
        await agent_conn.send({
            "type": "create_terminal",
            "terminal_id": terminal["terminal_id"],
            "title": terminal.get("title", terminal["terminal_id"]),
            "cwd": terminal.get("cwd", ""),
            "command": terminal.get("command", "/bin/bash"),
            "env": terminal.get("env", {}) or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })


def get_agent_connection(session_id: str) -> Optional[AgentConnection]:
    """
    获取 Agent 连接

    Args:
        session_id: 会话 ID

    Returns:
        AgentConnection 对象或 None
    """
    return active_agents.get(session_id)


def is_agent_connected(session_id: str) -> bool:
    """
    检查 Agent 是否连接

    Args:
        session_id: 会话 ID

    Returns:
        是否已连接
    """
    return session_id in active_agents


async def request_agent_create_terminal(
    session_id: str,
    *,
    terminal_id: str,
    title: str,
    cwd: str,
    command: str,
    env: Optional[dict] = None,
    timeout: float = 5.0,
) -> dict:
    """请求在线 agent 创建 terminal，并等待创建确认。"""
    agent_conn = get_agent_connection(session_id)
    if not agent_conn:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="device offline")

    future_key = (session_id, terminal_id)
    if future_key in pending_terminal_creates:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"terminal {terminal_id} 正在创建中",
        )

    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()
    pending_terminal_creates[future_key] = future

    await agent_conn.send({
        "type": "create_terminal",
        "terminal_id": terminal_id,
        "title": title,
        "cwd": cwd,
        "command": command,
        "env": env or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    try:
        await asyncio.wait_for(future, timeout=timeout)
    except RuntimeError as exc:
        pending_terminal_creates.pop(future_key, None)
        detail = str(exc)
        if "agent disconnected" in detail or "offline" in detail:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="device offline",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail or f"terminal {terminal_id} 创建失败",
        ) from exc
    except asyncio.TimeoutError as exc:
        pending_terminal_creates.pop(future_key, None)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"terminal {terminal_id} 创建超时",
        ) from exc

    terminal = await get_session_terminal(session_id, terminal_id)
    if not terminal:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"terminal {terminal_id} 创建后未找到",
        )
    return terminal


async def request_agent_close_terminal(
    session_id: str,
    *,
    terminal_id: str,
    reason: str = "server_forced_close",
) -> None:
    """请求在线 agent 关闭 terminal（不等待确认）。"""
    agent_conn = get_agent_connection(session_id)
    if not agent_conn:
        return

    await agent_conn.send({
        "type": "close_terminal",
        "terminal_id": terminal_id,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


async def request_agent_close_terminal_with_ack(
    session_id: str,
    *,
    terminal_id: str,
    reason: str = "server_forced_close",
    timeout: float = 5.0,
) -> dict:
    """请求在线 agent 关闭 terminal，并等待关闭确认。"""
    agent_conn = get_agent_connection(session_id)
    if not agent_conn:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="device offline")

    future_key = (session_id, terminal_id)
    if future_key in pending_terminal_closes:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"terminal {terminal_id} 正在关闭中",
        )

    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()
    pending_terminal_closes[future_key] = future

    await agent_conn.send({
        "type": "close_terminal",
        "terminal_id": terminal_id,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    try:
        await asyncio.wait_for(future, timeout=timeout)
    except RuntimeError as exc:
        pending_terminal_closes.pop(future_key, None)
        detail = str(exc)
        if "agent disconnected" in detail or "offline" in detail:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="device offline",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail or f"terminal {terminal_id} 关闭失败",
        ) from exc
    except asyncio.TimeoutError as exc:
        pending_terminal_closes.pop(future_key, None)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"terminal {terminal_id} 关闭超时",
        ) from exc

    return {"terminal_id": terminal_id, "reason": reason}
