"""
Agent 消息分发 + 各消息类型处理

注意：store 函数通过 app.ws.ws_agent 延迟引用，
以确保测试 patch("app.ws.ws_agent.xxx") 能生效。
"""
import base64
import logging
from datetime import datetime, timezone

from app.infra.crypto import decrypt_message
from app.ws.agent_connection import (
    AgentConnection,
    active_agents,
    get_agent_connection,
)
from app.ws.agent_request import (
    pending_terminal_creates,
    pending_terminal_closes,
    pending_terminal_snapshots,
    pending_lookup_knowledge,
    pending_tool_calls,
    _handle_execute_command_result,
)
from app.ws.agent_cleanup import (
    _close_agent_conversation_for_terminal,
)

logger = logging.getLogger(__name__)

# 延迟导入入口模块中的 store 函数，保证 mock patch 路径兼容
# （测试统一 patch "app.ws.ws_agent.xxx"）
import app.ws.ws_agent as _ws  # isort: skip  — 需要 ws_agent 先加载完成


async def _handle_agent_message(websocket, session_id: str, message: dict):
    """
    处理 Agent 发来的消息

    Args:
        websocket: WebSocket 连接
        session_id: 会话 ID
        message: 消息内容
    """
    # 延迟导入避免循环依赖，但只在函数顶部导入一次
    from app.ws.ws_client import broadcast_to_clients

    msg_type = message.get("type")

    if msg_type == "ping":
        # 心跳响应
        agent_conn = active_agents.get(session_id)
        if agent_conn:
            agent_conn.update_heartbeat()
            try:
                await _ws.update_session_device_heartbeat(session_id, online=True)
            except Exception as exc:
                if not _ws._is_degradable_session_state_error(exc):
                    raise
                logger.warning(
                    "Agent heartbeat persistence degraded: session_id=%s error=%s",
                    session_id,
                    exc,
                    exc_info=True,
                )
            await agent_conn.send({"type": "pong"})

    elif msg_type == "data":
        # 终端输出数据
        payload = message.get("payload", "")
        direction = message.get("direction", "output")
        terminal_id = message.get("terminal_id")
        terminal = (
            await _ws.get_session_terminal(session_id, terminal_id)
            if terminal_id
            else None
        )
        attach_epoch = int((terminal or {}).get("attach_epoch", 0) or 0)
        recovery_epoch = int((terminal or {}).get("recovery_epoch", 0) or 0)

        # 追加到历史记录
        try:
            # 解码 base64 数据
            try:
                decoded_data = base64.b64decode(payload).decode("utf-8", errors="replace")
            except Exception:
                decoded_data = payload

            await _ws.append_history(
                session_id,
                decoded_data,
                direction,
                terminal_id=terminal_id,
            )
        except Exception as e:
            logger.error("Failed to append history: session_id=%s error=%s", session_id, e)

        # 转发给所有 Client
        await broadcast_to_clients(session_id, {
            "type": "output",
            "terminal_id": terminal_id,
            "payload": payload,
            "attach_epoch": attach_epoch,
            "recovery_epoch": recovery_epoch,
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
            terminal = await _ws.update_session_terminal_status(
                session_id,
                terminal_id,
                terminal_status="recovering",
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
            await _ws.update_session_terminal_status(
                session_id,
                terminal_id,
                terminal_status="closed",
                disconnect_reason=reason,
            )
            await _close_agent_conversation_for_terminal(session_id, terminal_id, reason)
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

    elif msg_type == "snapshot_data":
        terminal_id = message.get("terminal_id")
        request_id = message.get("request_id")
        if terminal_id and request_id:
            future = pending_terminal_snapshots.pop((session_id, request_id), None)
            if future and not future.done():
                future.set_result({
                    "terminal_id": terminal_id,
                    "payload": message.get("payload", ""),
                    "pty": message.get("pty"),
                    "active_buffer": message.get("active_buffer"),
                })

    elif msg_type == "execute_command_result":
        _handle_execute_command_result(message)

    elif msg_type == "tool_catalog_snapshot":
        # B093: Agent 上报工具目录
        tools = message.get("tools", [])
        if isinstance(tools, list):
            from app.services.terminal_agent import validate_tool_catalog
            validated = validate_tool_catalog(tools)
            agent_conn = get_agent_connection(session_id)
            if agent_conn:
                agent_conn.tool_catalog = validated
                logger.info(
                    "Agent %s 上报工具目录: %d/%d 通过校验",
                    session_id, len(validated), len(tools),
                )

    elif msg_type == "lookup_knowledge_result":
        # B093: lookup_knowledge 结果回流
        request_id = message.get("request_id", "")
        entry = pending_lookup_knowledge.pop(request_id, None)
        if entry:
            _, future = entry
            if not future.done():
                future.set_result(message.get("result", ""))

    elif msg_type == "tool_result":
        # B093: 动态工具调用结果回流
        call_id = message.get("call_id", "")
        entry = pending_tool_calls.pop(call_id, None)
        if entry:
            _, future = entry
            if not future.done():
                future.set_result(message)

    elif msg_type == "agent_metadata":
        platform_name = (message.get("platform") or "").strip()
        hostname = (message.get("hostname") or "").strip()
        try:
            session = await _ws.get_session(session_id)
            current_name = (session.get("device", {}).get("name") or "").strip()
            await _ws.update_session_device_metadata(
                session_id,
                platform=platform_name or None,
                hostname=hostname or None,
                name=hostname if hostname and not current_name else None,
            )
        except Exception as exc:
            if not _ws._is_degradable_session_state_error(exc):
                raise
            logger.warning(
                "Agent metadata persistence degraded: session_id=%s error=%s",
                session_id,
                exc,
                exc_info=True,
            )

    else:
        # 未知消息类型
        await websocket.send_json({
            "type": "error",
            "message": f"Unknown message type: {msg_type}",
        })
