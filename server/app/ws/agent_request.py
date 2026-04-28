"""
Agent 请求处理 — 各请求类型处理函数（create/close terminal, snapshot, execute_command, lookup_knowledge, tool_call）
"""
import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import HTTPException, status

from app.infra.command_validator import (
    validate_command,
    DEFAULT_COMMAND_TIMEOUT,
    MAX_COMMAND_RATE_PER_MINUTE,
)
from app.ws.agent_connection import (
    AgentConnection,
    active_agents,
    get_agent_connection,
)

logger = logging.getLogger(__name__)

# 延迟导入入口模块中的 store 函数，保证 mock patch 路径兼容
import app.ws.ws_agent as _ws  # isort: skip  — 需要 ws_agent 先加载完成

# re-export store 函数供测试 mock patch 兼容
from app.store.session import get_session_terminal              # noqa: F401

# pending futures — terminal
pending_terminal_creates: dict[tuple[str, str], asyncio.Future] = {}
pending_terminal_closes: dict[tuple[str, str], asyncio.Future] = {}
pending_terminal_snapshots: dict[tuple[str, str], asyncio.Future] = {}

# B078: execute_command pending futures (session-scoped)
# key: request_id, value: (session_id, Future)
pending_execute_commands: dict[str, tuple[str, asyncio.Future]] = {}

# B093: lookup_knowledge / tool_call pending futures
# key: request_id/call_id, value: (session_id, Future)
pending_lookup_knowledge: dict[str, tuple[str, asyncio.Future]] = {}
pending_tool_calls: dict[str, tuple[str, asyncio.Future]] = {}

# B078: 频率限制追踪（每 session_id 的请求时间戳列表）
_execute_command_rate_tracker: dict[str, list[float]] = defaultdict(list)


@dataclass
class ExecuteCommandResult:
    """execute_command 的返回结果。"""
    exit_code: int
    stdout: str
    stderr: str
    truncated: bool
    timed_out: bool


def _handle_execute_command_result(message: dict):
    """处理 Agent 返回的 execute_command_result，resolve 对应的 Future。"""
    request_id = message.get("request_id")
    if not request_id:
        return
    entry = pending_execute_commands.pop(request_id, None)
    if entry:
        _, future = entry
        if not future.done():
            future.set_result(ExecuteCommandResult(
                exit_code=int(message.get("exit_code", -1)),
                stdout=str(message.get("stdout", "")),
                stderr=str(message.get("stderr", "")),
                truncated=bool(message.get("truncated", False)),
                timed_out=bool(message.get("timed_out", False)),
            ))


def _cleanup_execute_command_futures(session_id: str, reason: str):
    """清理指定 session 的所有 pending execute_command futures。"""
    for rid in list(pending_execute_commands.keys()):
        entry = pending_execute_commands.get(rid)
        if entry is None:
            continue
        owner_session, future = entry
        if owner_session != session_id:
            continue
        pending_execute_commands.pop(rid, None)
        if not future.done():
            future.set_exception(ConnectionError(f"agent disconnected: {reason}"))


def _cleanup_pending_futures_by_id(
    pending_dict: dict[str, tuple[str, asyncio.Future]],
    session_id: str,
    reason: str,
) -> None:
    """清理指定 session 的 pending futures（按 tuple 中附带的 session_id 过滤）。"""
    for key in list(pending_dict.keys()):
        entry = pending_dict.get(key)
        if entry is None:
            continue
        owner_session, future = entry
        if owner_session != session_id:
            continue
        pending_dict.pop(key, None)
        if not future.done():
            future.set_exception(ConnectionError(f"agent disconnected: {reason}"))


def _check_rate_limit(session_id: str) -> bool:
    """检查 execute_command 频率限制。

    Returns:
        True 如果允许，False 如果超频
    """
    import time
    now = time.time()
    timestamps = _execute_command_rate_tracker[session_id]
    # 清理超过 60 秒的旧记录
    cutoff = now - 60.0
    _execute_command_rate_tracker[session_id] = [
        t for t in timestamps if t > cutoff
    ]
    if len(_execute_command_rate_tracker[session_id]) >= MAX_COMMAND_RATE_PER_MINUTE:
        return False
    _execute_command_rate_tracker[session_id].append(now)
    return True


# ---------------------------------------------------------------------------
# Terminal 请求
# ---------------------------------------------------------------------------

async def request_agent_create_terminal(
    session_id: str,
    *,
    terminal_id: str,
    title: str,
    cwd: str,
    command: str,
    env: Optional[dict] = None,
    rows: int = 24,
    cols: int = 80,
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
        "rows": rows,
        "cols": cols,
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


async def request_agent_terminal_snapshot(
    session_id: str,
    terminal_id: str,
    *,
    timeout: float = 1.5,
) -> Optional[dict]:
    """请求在线 agent 返回 terminal 最近输出快照。"""
    agent_conn = get_agent_connection(session_id)
    if not agent_conn:
        return None

    request_id = uuid4().hex
    future_key = (session_id, request_id)
    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()
    pending_terminal_snapshots[future_key] = future

    await agent_conn.send({
        "type": "snapshot_request",
        "terminal_id": terminal_id,
        "request_id": request_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    try:
        result = await asyncio.wait_for(future, timeout=timeout)
    except Exception:
        pending_terminal_snapshots.pop(future_key, None)
        return None

    if not isinstance(result, dict):
        return None
    payload = result.get("payload")
    if not payload:
        return None
    return {
        "payload": str(payload),
        "pty": result.get("pty"),
        "active_buffer": result.get("active_buffer"),
    }


# ---------------------------------------------------------------------------
# execute_command
# ---------------------------------------------------------------------------

async def send_execute_command(
    session_id: str,
    command: str,
    *,
    timeout: int = DEFAULT_COMMAND_TIMEOUT,
    cwd: Optional[str] = None,
) -> ExecuteCommandResult:
    """向在线 Agent 发送 execute_command 并等待结果。

    Args:
        session_id: 会话 ID
        command: 要执行的命令
        timeout: 命令执行超时（秒），默认 10
        cwd: 工作目录（可选）

    Returns:
        ExecuteCommandResult 包含 exit_code, stdout, stderr, truncated, timed_out

    Raises:
        HTTPException: 设备离线、命令不合法、频率超限、超时
    """
    # 1. Server 端白名单验证
    valid, reason = validate_command(command)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"命令验证失败: {reason}",
        )

    # 2. 检查 Agent 连接
    agent_conn = get_agent_connection(session_id)
    if not agent_conn:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="device offline",
        )

    # 3. 频率限制
    if not _check_rate_limit(session_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"execute_command 频率超限（每分钟最多 {MAX_COMMAND_RATE_PER_MINUTE} 次）",
        )

    # 4. 创建 Future 并发送
    request_id = uuid4().hex
    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()
    pending_execute_commands[request_id] = (session_id, future)

    await agent_conn.send({
        "type": "execute_command",
        "request_id": request_id,
        "command": command,
        "timeout": timeout,
        "cwd": cwd,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    # 5. 等待结果（Agent 端 timeout + 网络 buffer）
    try:
        result = await asyncio.wait_for(future, timeout=timeout + 5)
    except asyncio.TimeoutError:
        pending_execute_commands.pop(request_id, None)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="execute_command 超时",
        )
    except ConnectionError as exc:
        pending_execute_commands.pop(request_id, None)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="device offline",
        ) from exc

    return result


# ---------------------------------------------------------------------------
# B093: lookup_knowledge / tool_call
# ---------------------------------------------------------------------------

async def send_lookup_knowledge(
    session_id: str,
    query: str,
    timeout: int = 15,
) -> str:
    """向 Agent 发送 lookup_knowledge 请求并等待结果。

    Returns:
        知识检索结果文本
    """
    agent_conn = get_agent_connection(session_id)
    if not agent_conn:
        return ""  # Agent 离线，返回空（不阻塞）

    request_id = uuid4().hex
    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()
    pending_lookup_knowledge[request_id] = (session_id, future)

    try:
        await agent_conn.send({
            "type": "lookup_knowledge",
            "request_id": request_id,
            "query": query,
        })
        result = await asyncio.wait_for(future, timeout=timeout)
        return result
    except asyncio.TimeoutError:
        pending_lookup_knowledge.pop(request_id, None)
        logger.warning("lookup_knowledge 超时: session=%s query=%s", session_id, query[:50])
        return ""
    except Exception as e:
        pending_lookup_knowledge.pop(request_id, None)
        logger.warning("lookup_knowledge 失败: %s", e)
        return ""


async def send_tool_call(
    session_id: str,
    call_id: str,
    tool_name: str,
    arguments: dict,
    timeout: int = 30,
) -> dict:
    """向 Agent 发送动态工具调用请求并等待结果。

    Returns:
        tool_result dict
    """
    agent_conn = get_agent_connection(session_id)
    if not agent_conn:
        return {"status": "error", "error": "device offline"}

    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()
    pending_tool_calls[call_id] = (session_id, future)

    try:
        await agent_conn.send({
            "type": "tool_call",
            "call_id": call_id,
            "tool_name": tool_name,
            "arguments": arguments,
        })
        result = await asyncio.wait_for(future, timeout=timeout)
        return result
    except asyncio.TimeoutError:
        pending_tool_calls.pop(call_id, None)
        return {"status": "error", "error": "tool_call timeout"}
    except Exception as e:
        pending_tool_calls.pop(call_id, None)
        return {"status": "error", "error": str(e)}
