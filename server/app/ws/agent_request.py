"""
Agent 请求处理 — 各请求类型处理函数（create/close terminal, snapshot, execute_command, lookup_knowledge, tool_call）

所有依赖直接从源模块导入，不再通过 ws_agent 中转。
"""
import asyncio
import logging
import time
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
from app.infra.message_types import MessageType
from app.store.session import get_session_terminal
from app.ws.agent_connection import (
    AgentConnection,
    active_agents,
    get_agent_connection,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# B056: PendingRequestRegistry — 统一管理 pending futures
# ---------------------------------------------------------------------------

# Tuple-keyed registry names (session_id, terminal_id/request_id)
_TUPLE_REGISTRY_NAMES = ("terminal_creates", "terminal_closes", "terminal_snapshots")
# ID-keyed registry names (request_id/call_id -> (session_id, Future))
_ID_REGISTRY_NAMES = ("execute_commands", "lookup_knowledge", "tool_calls")


class PendingRequestRegistry:
    """统一管理所有 pending request futures，提供创建、查找、清理和超时回收。

    两类 registry:
    - tuple-keyed: key 为 (session_id, terminal_id/request_id)，value 为 Future
    - id-keyed: key 为 request_id/call_id，value 为 (session_id, Future)
    """

    def __init__(self) -> None:
        self._tuple_dicts: dict[str, dict[tuple[str, str], asyncio.Future]] = {
            name: {} for name in _TUPLE_REGISTRY_NAMES
        }
        self._id_dicts: dict[str, dict[str, tuple[str, asyncio.Future]]] = {
            name: {} for name in _ID_REGISTRY_NAMES
        }
        # 时间戳追踪，用于超时清理
        self._tuple_timestamps: dict[str, dict[tuple[str, str], float]] = {
            name: {} for name in _TUPLE_REGISTRY_NAMES
        }
        self._id_timestamps: dict[str, dict[str, float]] = {
            name: {} for name in _ID_REGISTRY_NAMES
        }

    # -- Tuple-keyed 操作 --

    def create_tuple_future(
        self,
        registry_name: str,
        key: tuple[str, str],
        *,
        check_conflict: bool = True,
        conflict_detail: str = "",
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> asyncio.Future:
        """创建并注册一个 tuple-keyed future。"""
        d = self._tuple_dicts[registry_name]
        if check_conflict and key in d:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=conflict_detail or f"request already pending for {key}",
            )
        if loop is None:
            loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        d[key] = future
        self._tuple_timestamps[registry_name][key] = time.time()
        return future

    def has_tuple(self, registry_name: str, key: tuple[str, str]) -> bool:
        return key in self._tuple_dicts[registry_name]

    def get_tuple_future(self, registry_name: str, key: tuple[str, str]) -> Optional[asyncio.Future]:
        return self._tuple_dicts[registry_name].get(key)

    def pop_tuple_future(self, registry_name: str, key: tuple[str, str]) -> Optional[asyncio.Future]:
        self._tuple_timestamps[registry_name].pop(key, None)
        return self._tuple_dicts[registry_name].pop(key, None)

    # -- ID-keyed 操作 --

    def create_id_future(
        self,
        registry_name: str,
        key: str,
        session_id: str,
        *,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> asyncio.Future:
        """创建并注册一个 id-keyed future。"""
        if loop is None:
            loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._id_dicts[registry_name][key] = (session_id, future)
        self._id_timestamps[registry_name][key] = time.time()
        return future

    def has_id(self, registry_name: str, key: str) -> bool:
        return key in self._id_dicts[registry_name]

    def get_id_entry(self, registry_name: str, key: str) -> Optional[tuple[str, asyncio.Future]]:
        return self._id_dicts[registry_name].get(key)

    def pop_id_entry(self, registry_name: str, key: str) -> Optional[tuple[str, asyncio.Future]]:
        self._id_timestamps[registry_name].pop(key, None)
        return self._id_dicts[registry_name].pop(key, None)

    # -- 清理 --

    def cleanup_tuple_by_session(self, registry_name: str, session_id: str, reason: str) -> None:
        """清理指定 session 的 tuple-keyed futures，以 RuntimeError 异常完成。"""
        d = self._tuple_dicts[registry_name]
        for key in list(d.keys()):
            if key[0] != session_id:
                continue
            future = d.pop(key, None)
            self._tuple_timestamps[registry_name].pop(key, None)
            if future and not future.done():
                future.set_exception(RuntimeError(f"agent disconnected: {reason}"))

    def cleanup_id_by_session(self, registry_name: str, session_id: str, reason: str) -> None:
        """清理指定 session 的 id-keyed futures，以 ConnectionError 异常完成。"""
        d = self._id_dicts[registry_name]
        for key in list(d.keys()):
            entry = d.get(key)
            if entry is None:
                continue
            owner_session, future = entry
            if owner_session != session_id:
                continue
            d.pop(key, None)
            self._id_timestamps[registry_name].pop(key, None)
            if not future.done():
                future.set_exception(ConnectionError(f"agent disconnected: {reason}"))

    def cleanup_all_by_session(self, session_id: str, reason: str) -> None:
        """清理指定 session 的所有类型 futures。"""
        for name in _TUPLE_REGISTRY_NAMES:
            self.cleanup_tuple_by_session(name, session_id, reason)
        for name in _ID_REGISTRY_NAMES:
            self.cleanup_id_by_session(name, session_id, reason)

    def clear_timestamps_by_session(self, session_id: str) -> None:
        """清理指定 session 的时间戳追踪（不操作 dict/future，用于旧清理函数已处理 dict 后的补充）。"""
        for name in _TUPLE_REGISTRY_NAMES:
            ts = self._tuple_timestamps[name]
            for key in list(ts.keys()):
                if key[0] == session_id:
                    del ts[key]
        for name in _ID_REGISTRY_NAMES:
            d = self._id_dicts[name]
            ts = self._id_timestamps[name]
            for key in list(ts.keys()):
                entry = d.get(key)
                if entry is not None and entry[0] == session_id:
                    del ts[key]

    def cleanup_stale(self, max_age_seconds: float = 300) -> int:
        """清理超过 max_age_seconds 的 stale futures。返回清理数量。"""
        now = time.time()
        cleaned = 0
        for name in _TUPLE_REGISTRY_NAMES:
            d = self._tuple_dicts[name]
            ts = self._tuple_timestamps[name]
            for key in list(ts.keys()):
                if now - ts[key] > max_age_seconds:
                    future = d.pop(key, None)
                    ts.pop(key, None)
                    if future and not future.done():
                        future.set_exception(asyncio.TimeoutError("pending request expired"))
                        cleaned += 1
        for name in _ID_REGISTRY_NAMES:
            d = self._id_dicts[name]
            ts = self._id_timestamps[name]
            for key in list(ts.keys()):
                if now - ts[key] > max_age_seconds:
                    entry = d.pop(key, None)
                    ts.pop(key, None)
                    if entry:
                        _, future = entry
                        if not future.done():
                            future.set_exception(asyncio.TimeoutError("pending request expired"))
                            cleaned += 1
        return cleaned

    def clear_all(self) -> None:
        """清空所有 registry。"""
        for name in _TUPLE_REGISTRY_NAMES:
            self._tuple_dicts[name].clear()
            self._tuple_timestamps[name].clear()
        for name in _ID_REGISTRY_NAMES:
            self._id_dicts[name].clear()
            self._id_timestamps[name].clear()

    def stats(self) -> dict[str, int]:
        """返回每个 registry 的当前 pending 数量。"""
        result: dict[str, int] = {}
        for name in _TUPLE_REGISTRY_NAMES:
            result[name] = len(self._tuple_dicts[name])
        for name in _ID_REGISTRY_NAMES:
            result[name] = len(self._id_dicts[name])
        return result


# 全局 registry 实例
pending_registry = PendingRequestRegistry()

# ---------------------------------------------------------------------------
# 向后兼容的全局 dict 引用 — 供 agent_cleanup / agent_message_handler / ws_agent re-export 使用
# 这些 dict 直接指向 registry 内部存储，保持现有代码兼容。
# ---------------------------------------------------------------------------

pending_terminal_creates: dict[tuple[str, str], asyncio.Future] = pending_registry._tuple_dicts["terminal_creates"]
pending_terminal_closes: dict[tuple[str, str], asyncio.Future] = pending_registry._tuple_dicts["terminal_closes"]
pending_terminal_snapshots: dict[tuple[str, str], asyncio.Future] = pending_registry._tuple_dicts["terminal_snapshots"]
pending_execute_commands: dict[str, tuple[str, asyncio.Future]] = pending_registry._id_dicts["execute_commands"]
pending_lookup_knowledge: dict[str, tuple[str, asyncio.Future]] = pending_registry._id_dicts["lookup_knowledge"]
pending_tool_calls: dict[str, tuple[str, asyncio.Future]] = pending_registry._id_dicts["tool_calls"]

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
    """检查 execute_command 频率限制。Returns True 如果允许。"""
    now = time.time()
    timestamps = _execute_command_rate_tracker[session_id]
    cutoff = now - 60.0
    _execute_command_rate_tracker[session_id] = [t for t in timestamps if t > cutoff]
    if len(_execute_command_rate_tracker[session_id]) >= MAX_COMMAND_RATE_PER_MINUTE:
        return False
    _execute_command_rate_tracker[session_id].append(now)
    return True

# -- Terminal 请求 --

async def _request_agent_with_ack(
    session_id: str,
    *,
    registry_name: str,
    future_key: tuple[str, str],
    message: dict,
    timeout: float,
    conflict_detail: str,
    error_label: str,
) -> None:
    """向在线 agent 发送请求并等待确认的通用函数。

    完成以下公共步骤：
    1. 获取 agent 连接（不在线抛 409）
    2. 创建 tuple-keyed future
    3. 发送消息
    4. wait_for 等待并统一处理 RuntimeError / TimeoutError

    调用方在 await 此函数后自行处理成功结果（如查 DB、构造返回值）。
    """
    agent_conn = get_agent_connection(session_id)
    if not agent_conn:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="device offline")
    future = pending_registry.create_tuple_future(
        registry_name, future_key,
        conflict_detail=conflict_detail,
    )
    await agent_conn.send(message)
    try:
        await asyncio.wait_for(future, timeout=timeout)
    except RuntimeError as exc:
        pending_registry.pop_tuple_future(registry_name, future_key)
        detail = str(exc)
        if "agent disconnected" in detail or "offline" in detail:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="device offline",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail or f"terminal {future_key[1]} {error_label}失败",
        ) from exc
    except asyncio.TimeoutError as exc:
        pending_registry.pop_tuple_future(registry_name, future_key)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"terminal {future_key[1]} {error_label}超时",
        ) from exc


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
    """请求在线 agent 创建 terminal，并等待创建确认。关键路径: agent 离线抛 HTTPException。"""
    await _request_agent_with_ack(
        session_id,
        registry_name="terminal_creates",
        future_key=(session_id, terminal_id),
        message={
            "type": MessageType.CREATE_TERMINAL, "terminal_id": terminal_id, "title": title,
            "cwd": cwd, "command": command, "env": env or {},
            "rows": rows, "cols": cols, "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        timeout=timeout,
        conflict_detail=f"terminal {terminal_id} 正在创建中",
        error_label="创建",
    )
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
    """请求在线 agent 关闭 terminal（不等待确认）。best-effort: agent 离线静默跳过。"""
    agent_conn = get_agent_connection(session_id)
    if not agent_conn:
        logger.warning("close_terminal skipped: agent offline, session=%s terminal=%s", session_id, terminal_id)
        return
    await agent_conn.send({
        "type": MessageType.CLOSE_TERMINAL,
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
    """请求在线 agent 关闭 terminal，并等待关闭确认。关键路径: agent 离线抛 HTTPException。"""
    await _request_agent_with_ack(
        session_id,
        registry_name="terminal_closes",
        future_key=(session_id, terminal_id),
        message={
            "type": MessageType.CLOSE_TERMINAL,
            "terminal_id": terminal_id,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        timeout=timeout,
        conflict_detail=f"terminal {terminal_id} 正在关闭中",
        error_label="关闭",
    )
    return {"terminal_id": terminal_id, "reason": reason}

async def request_agent_terminal_snapshot(
    session_id: str,
    terminal_id: str,
    *,
    timeout: float = 1.5,
) -> Optional[dict]:
    """请求在线 agent 返回 terminal 最近输出快照。best-effort: agent 离线或超时返回 None。"""
    agent_conn = get_agent_connection(session_id)
    if not agent_conn:
        logger.warning("snapshot skipped: agent offline, session=%s terminal=%s", session_id, terminal_id)
        return None
    request_id = uuid4().hex
    future_key = (session_id, request_id)
    future = pending_registry.create_tuple_future("terminal_snapshots", future_key, check_conflict=False)
    await agent_conn.send({
        "type": MessageType.SNAPSHOT_REQUEST,
        "terminal_id": terminal_id,
        "request_id": request_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    try:
        result = await asyncio.wait_for(future, timeout=timeout)
    except Exception:
        pending_registry.pop_tuple_future("terminal_snapshots", future_key)
        logger.warning("snapshot failed: session=%s terminal=%s", session_id, terminal_id)
        return None
    if not isinstance(result, dict):
        return None
    payload = result.get("payload")
    if not payload:
        return None
    return {"payload": str(payload), "pty": result.get("pty"), "active_buffer": result.get("active_buffer")}

# -- execute_command --

async def send_execute_command(
    session_id: str, command: str, *, timeout: int = DEFAULT_COMMAND_TIMEOUT, cwd: Optional[str] = None,
) -> ExecuteCommandResult:
    """向在线 Agent 发送 execute_command 并等待结果。关键路径: agent 离线抛 HTTPException。"""
    valid, reason = validate_command(command)
    if not valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"命令验证失败: {reason}")
    agent_conn = get_agent_connection(session_id)
    if not agent_conn:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="device offline")
    if not _check_rate_limit(session_id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"execute_command 频率超限（每分钟最多 {MAX_COMMAND_RATE_PER_MINUTE} 次）",
        )
    request_id = uuid4().hex
    future = pending_registry.create_id_future("execute_commands", request_id, session_id)
    await agent_conn.send({
        "type": MessageType.EXECUTE_COMMAND, "request_id": request_id, "command": command,
        "timeout": timeout, "cwd": cwd, "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    try:
        return await asyncio.wait_for(future, timeout=timeout + 5)
    except asyncio.TimeoutError:
        pending_registry.pop_id_entry("execute_commands", request_id)
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="execute_command 超时")
    except ConnectionError as exc:
        pending_registry.pop_id_entry("execute_commands", request_id)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="device offline") from exc

# -- B093: lookup_knowledge / tool_call --

async def send_lookup_knowledge(session_id: str, query: str, timeout: int = 15) -> str:
    """向 Agent 发送 lookup_knowledge 请求并等待结果。best-effort: 失败返回空字符串。"""
    agent_conn = get_agent_connection(session_id)
    if not agent_conn:
        logger.warning("lookup_knowledge skipped: agent offline, session=%s", session_id)
        return ""
    request_id = uuid4().hex
    future = pending_registry.create_id_future("lookup_knowledge", request_id, session_id)
    try:
        await agent_conn.send({"type": MessageType.LOOKUP_KNOWLEDGE, "request_id": request_id, "query": query})
        return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        pending_registry.pop_id_entry("lookup_knowledge", request_id)
        logger.warning("lookup_knowledge 超时: session=%s query=%s", session_id, query[:50])
        return ""
    except Exception as e:
        pending_registry.pop_id_entry("lookup_knowledge", request_id)
        logger.warning("lookup_knowledge 失败: %s", e)
        return ""

async def send_tool_call(
    session_id: str,
    call_id: str,
    tool_name: str,
    arguments: dict,
    timeout: int = 30,
) -> dict:
    """向 Agent 发送动态工具调用请求并等待结果。best-effort: 失败返回 error dict。"""
    agent_conn = get_agent_connection(session_id)
    if not agent_conn:
        logger.warning("tool_call skipped: agent offline, session=%s tool=%s", session_id, tool_name)
        return {"status": "error", "error": "device offline"}
    future = pending_registry.create_id_future("tool_calls", call_id, session_id)
    try:
        await agent_conn.send({
            "type": MessageType.TOOL_CALL, "call_id": call_id, "tool_name": tool_name, "arguments": arguments,
        })
        return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        pending_registry.pop_id_entry("tool_calls", call_id)
        logger.warning("tool_call 超时: session=%s tool=%s", session_id, tool_name)
        return {"status": "error", "error": "tool_call timeout"}
    except Exception as e:
        pending_registry.pop_id_entry("tool_calls", call_id)
        logger.warning("tool_call 失败: session=%s tool=%s error=%s", session_id, tool_name, e)
        return {"status": "error", "error": str(e)}
