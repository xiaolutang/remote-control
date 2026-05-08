"""
WebSocket Agent 连接路由

拆分后的入口模块，负责 handler 注册和生命周期管理。
所有子模块（agent_connection、agent_request、agent_cleanup、agent_message_handler）
直接从源模块导入依赖，不再通过本模块 re-export 中转。
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import WebSocketDisconnect, HTTPException

from app.infra.crypto import get_crypto_manager, decrypt_message
from app.infra.message_types import MessageType
from app.store.session import (
    get_session,
    set_session_online,
    list_recoverable_session_terminals,
)

from app.ws.ws_auth import (
    wait_for_ws_auth,
    http_to_ws_code,
    MAX_WS_MESSAGE_SIZE,
    is_secure_websocket_transport,
)

# 子模块导入：handler 自身使用
from app.ws.agent_connection import (
    AgentConnection,
    active_agents,
    HEARTBEAT_INTERVAL,
    HEARTBEAT_TIMEOUT,
)
from app.ws.agent_cleanup import (
    CLEANUP_REASON_AGENT_SHUTDOWN,
    CLEANUP_REASON_NETWORK_LOST,
    _is_agent_stale,
    _clear_agent_stale,
    _cleanup_agent,
    _restore_recoverable_terminals,
    _stale_agent_ttl_checker,
    _cleanup_agent_immediately,
)
from app.ws.agent_message_handler import (
    _handle_agent_message,
)
from app.ws.ws_common import (
    is_degradable_session_state_error as _is_degradable_session_state_error,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 心跳检查器（与 WebSocket 连接生命周期绑定，留在入口模块）
# ---------------------------------------------------------------------------

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
            return CLEANUP_REASON_NETWORK_LOST

    return None


async def _set_session_online_best_effort(session_id: str) -> None:
    """在线状态写回失败时保持连接存活，避免已建立会话被存储异常打断。"""
    try:
        await set_session_online(session_id)
    except Exception as exc:
        if not _is_degradable_session_state_error(exc):
            raise
        logger.warning(
            "Session online persistence degraded: session_id=%s error=%s",
            session_id,
            exc,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# WebSocket 入口处理器
# ---------------------------------------------------------------------------

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
    cleanup_reason = CLEANUP_REASON_AGENT_SHUTDOWN

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

    # 不变量 #27 服务端守卫：非 TLS 连接（ws://）必须携带 AES 密钥
    if not is_secure_websocket_transport(websocket) and not agent_conn.aes_key:
        logger.warning("ws:// connection rejected: no AES key, session_id=%s", session_id)
        await websocket.close(code=4003, reason="ws:// requires encrypted_aes_key")
        return

    active_agents[session_id] = agent_conn
    logger.info(
        "Agent connected: session_id=%s owner=%s",
        session_id, owner,
    )

    # 原子更新：status=online + agent_online=True。存储异常降级为告警，避免已建立连接被打断。
    await _set_session_online_best_effort(session_id)
    heartbeat_task = None

    try:
        # 获取当前视图连接数
        from app.ws.client_presence import get_view_counts
        view_counts = get_view_counts(session_id)

        # 发送连接成功消息（符合 CONTRACT-002）
        await websocket.send_json({
            "type": MessageType.CONNECTED,
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
                        "Agent decrypt FAIL: session_id=%s iv_len=%s data_len=%s error=%s",
                        session_id,
                        len(message.get("iv", "")),
                        len(message.get("data", "")),
                        e,
                    )
                    continue

            await _handle_agent_message(websocket, session_id, message)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("Agent connection error: session_id=%s error=%s", session_id, e, exc_info=True)
        cleanup_reason = CLEANUP_REASON_NETWORK_LOST
    finally:
        # 清理连接
        if heartbeat_task and heartbeat_task.done():
            try:
                timeout_reason = heartbeat_task.result()
                if timeout_reason:
                    cleanup_reason = timeout_reason
            except Exception:
                logger.debug(
                    "Heartbeat task raised exception: session_id=%s",
                    session_id,
                    exc_info=True,
                )
        await _cleanup_agent(session_id, cleanup_reason)
        if heartbeat_task:
            heartbeat_task.cancel()
