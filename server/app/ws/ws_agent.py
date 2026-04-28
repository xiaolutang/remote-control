"""
WebSocket Agent 连接路由

拆分后的入口模块，从子模块导入并 re-export 所有公共符号，
保证 `from app.ws.ws_agent import X` 继续工作。
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import WebSocketDisconnect, HTTPException

from app.infra.crypto import get_crypto_manager, decrypt_message

# session store 函数：ws_agent 自身使用，同时 re-export 给子模块延迟引用 + 测试 mock 兼容
from app.store.session import (                             # noqa: F401
    get_session,
    set_session_online,
    set_session_offline,
    set_session_offline_recoverable,
    update_session_device_heartbeat,
    update_session_terminal_status,
    update_session_device_metadata,
    get_session_terminal,
    append_history,
    list_recoverable_session_terminals,
)

from app.ws.ws_auth import (
    wait_for_ws_auth,
    http_to_ws_code,
    MAX_WS_MESSAGE_SIZE,
    is_secure_websocket_transport,
)
# 测试 patch 兼容：async_verify_token 通过 ws_agent 模块 patch
from app.infra.auth import async_verify_token               # noqa: F401

# ---- 从子模块 re-export 所有公共符号 ----

# agent_connection: AgentConnection 类 + 连接注册/查询 + 心跳配置
from app.ws.agent_connection import (                     # noqa: F401
    AgentConnection,
    active_agents,
    get_agent_connection,
    is_agent_connected,
    HEARTBEAT_INTERVAL,
    HEARTBEAT_TIMEOUT,
)

# agent_request: 各请求类型处理函数 + pending futures
from app.ws.agent_request import (                       # noqa: F401
    ExecuteCommandResult,
    pending_terminal_creates,
    pending_terminal_closes,
    pending_terminal_snapshots,
    pending_execute_commands,
    pending_lookup_knowledge,
    pending_tool_calls,
    _execute_command_rate_tracker,
    _handle_execute_command_result,
    _cleanup_execute_command_futures,
    _cleanup_pending_futures_by_id,
    _check_rate_limit,
    request_agent_create_terminal,
    request_agent_close_terminal,
    request_agent_close_terminal_with_ack,
    request_agent_terminal_snapshot,
    send_execute_command,
    send_lookup_knowledge,
    send_tool_call,
)

# agent_cleanup: 断连清理 + stale 管理 + TTL 检查
from app.ws.agent_cleanup import (                       # noqa: F401
    CLEANUP_REASON_AGENT_SHUTDOWN,
    CLEANUP_REASON_NETWORK_LOST,
    CLEANUP_REASON_DEVICE_OFFLINE,
    STALE_TTL_SECONDS,
    stale_agents,
    _cleanup_pending_futures,
    _cleanup_agent,
    _mark_agent_stale,
    _is_agent_stale,
    _clear_agent_stale,
    _uses_immediate_offline_cleanup,
    _expire_stale_agent,
    _stale_agent_ttl_checker,
    _cleanup_agent_immediately,
    _set_session_offline_immediately,
    _restore_recoverable_terminals,
    _close_agent_conversation_for_terminal,
    _close_agent_conversations_for_session,
)

# agent_message_handler: 消息分发
from app.ws.agent_message_handler import (               # noqa: F401
    _handle_agent_message,
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

    # 原子更新：status=online + agent_online=True
    try:
        await set_session_online(session_id)
    except Exception:
        del active_agents[session_id]
        raise
    heartbeat_task = None

    try:
        # 获取当前视图连接数
        from app.ws.ws_client import get_view_counts
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
                pass
        await _cleanup_agent(session_id, cleanup_reason)
        if heartbeat_task:
            heartbeat_task.cancel()
