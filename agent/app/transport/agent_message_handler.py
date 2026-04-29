"""
Agent 消息处理器 — 处理从 Server 收到的各类消息。
"""
import asyncio
import base64
import json
import logging
import os
import shlex
from datetime import datetime, timezone

from app.security.command_validator import (
    validate_command,
    MAX_STDOUT_LEN,
    MAX_STDERR_LEN,
    DEFAULT_COMMAND_TIMEOUT,
)
from app.tools.knowledge_tool import lookup_knowledge
from app.transport.agent_protocol import TerminalSpec

logger = logging.getLogger(__name__)


def _log(message: str) -> None:
    """Agent 日志输出到 stderr + logging"""
    import sys
    if os.environ.get("FLUTTER_TEST"):
        return
    print(f"[Agent] {message}", file=sys.stderr, flush=True)
    logger.info(message)


def _validate_terminal_input(command, cwd, env):
    """B068: 校验 terminal 创建参数。返回 None 表示通过，否则返回错误描述。"""
    if not isinstance(command, str):
        return f"command must be string, got {type(command).__name__}"
    if not command.strip():
        return "command must not be empty"
    if cwd is not None:
        if not isinstance(cwd, str):
            return f"cwd must be string, got {type(cwd).__name__}"
        import os.path
        expanded = os.path.expanduser(cwd)
        if not os.path.isabs(expanded):
            return f"cwd must be absolute path, got '{cwd}'"
    if not isinstance(env, dict):
        return f"env must be dict, got {type(env).__name__}"
    for k, v in env.items():
        if not isinstance(v, str):
            return f"env['{k}'] must be string, got {type(v).__name__}"
    return None


class AgentMessageHandler:
    """处理从 Server 收到的各类消息，由 WebSocketClient 委派调用。"""

    def __init__(self, client):
        """
        Args:
            client: WebSocketClient 实例，用于访问 runtime_manager / snapshot_manager / mcp_manager 等
        """
        self._client = client

    async def dispatch(self, data: dict):
        """分发消息到对应处理器。"""
        msg_type = data.get("type")
        _log(f"收到消息 type={msg_type} data={json.dumps(data, ensure_ascii=False)[:200]}")

        if msg_type == "data":
            await self._handle_data(data)
        elif msg_type == "resize":
            await self._handle_resize(data)
        elif msg_type == "create_terminal":
            await self._handle_create_terminal(data)
        elif msg_type == "close_terminal":
            await self._handle_close_terminal(data)
        elif msg_type == "snapshot_request":
            await self._handle_snapshot_request(data)
        elif msg_type == "execute_command":
            asyncio.create_task(self._handle_execute_command(data))
        elif msg_type == "lookup_knowledge":
            asyncio.create_task(self._handle_lookup_knowledge(data))
        elif msg_type == "tool_call":
            asyncio.create_task(self._handle_tool_call(data))
        elif msg_type == "pong":
            pass
        elif msg_type == "error":
            _log(f"服务器错误: {data.get('message')}")

    async def _handle_data(self, data: dict):
        """处理 data 消息 — 写入 PTY。"""
        payload = data.get("payload", "")
        try:
            decoded = base64.b64decode(payload)
        except Exception:
            decoded = payload.encode("utf-8")

        try:
            terminal_id = data.get("terminal_id")
            target = self._client.runtime_manager.get_terminal(terminal_id) if terminal_id else self._client.pty
            if target:
                write_ok = target.write(decoded)
                if not write_ok:
                    _log(
                        f"终端输入写入失败: terminal_id={terminal_id or 'session'} "
                        f"bytes={len(decoded)}"
                    )
                elif len(decoded) >= 1024:
                    _log(
                        f"终端输入已写入: terminal_id={terminal_id or 'session'} "
                        f"bytes={len(decoded)}"
                    )
        except Exception as e:
            _log(f"数据写入失败: {e}")

    async def _handle_resize(self, data: dict):
        """处理 resize 消息。"""
        try:
            rows = data.get("rows", 24)
            cols = data.get("cols", 80)
            terminal_id = data.get("terminal_id")
            target = self._client.runtime_manager.get_terminal(terminal_id) if terminal_id else self._client.pty
            if target:
                target.resize(rows, cols)
                if terminal_id:
                    self._client.snapshot_manager.update_terminal_pty(
                        terminal_id, int(rows), int(cols),
                    )
        except Exception as e:
            _log(f"终端大小调整失败: {e}")

    async def _handle_create_terminal(self, data: dict):
        """处理 create_terminal 消息。"""
        terminal_id = data.get("terminal_id")
        if not terminal_id:
            return

        command = data.get("command", self._client.command)
        cwd = data.get("cwd")
        env = data.get("env", {}) or {}
        validation_error = _validate_terminal_input(command, cwd, env)
        if validation_error:
            _log(f"Terminal {terminal_id} 输入校验失败: {validation_error}")
            await self._client._send_ws_message(
                self._client.runtime_manager.build_terminal_closed_event(
                    terminal_id, reason=f"validation_failed: {validation_error}"
                )
            )
            return

        try:
            spec = TerminalSpec(
                terminal_id=terminal_id,
                title=data.get("title", terminal_id),
                cwd=cwd,
                command=command,
                env=env,
                rows=int(data.get("rows", 24) or 24),
                cols=int(data.get("cols", 80) or 80),
            )
            runtime = self._client.runtime_manager.create_terminal(spec)
            self._client.snapshot_manager.create_terminal(spec)
            self._client._runtime_tasks[terminal_id] = asyncio.create_task(
                self._client._runtime_pty_to_websocket(terminal_id, runtime)
            )
            await self._client._send_ws_message(
                self._client.runtime_manager.build_terminal_created_event(terminal_id)
            )
        except Exception as e:
            _log(f"Terminal {terminal_id} 创建失败: {e}")
            try:
                await self._client._send_ws_message(
                    self._client.runtime_manager.build_terminal_closed_event(
                        terminal_id, reason="create_failed"
                    )
                )
            except Exception:
                pass

    async def _handle_close_terminal(self, data: dict):
        """处理 close_terminal 消息。"""
        terminal_id = data.get("terminal_id")
        try:
            if terminal_id and self._client.runtime_manager.get_terminal(terminal_id):
                event = self._client.runtime_manager.close_terminal(
                    terminal_id, reason=data.get("reason", "terminal_exit"),
                )
                self._client.snapshot_manager.close_terminal(terminal_id)
                task = self._client._runtime_tasks.pop(terminal_id, None)
                if task:
                    task.cancel()
                await self._client._send_ws_message(event)
        except Exception as e:
            _log(f"Terminal {terminal_id} 关闭失败: {e}")

    async def _handle_snapshot_request(self, data: dict):
        """处理 snapshot_request 消息。"""
        terminal_id = data.get("terminal_id")
        request_id = data.get("request_id")
        if not terminal_id or not request_id:
            return
        snapshot = self._client.snapshot_manager.build_snapshot_data(terminal_id)
        await self._client._send_ws_message({
            "type": "snapshot_data",
            "terminal_id": terminal_id,
            "request_id": request_id,
            "payload": (snapshot or {}).get("payload", ""),
            "pty": (snapshot or {}).get("pty"),
            "active_buffer": (snapshot or {}).get("active_buffer", "main"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    async def _handle_execute_command(self, data: dict):
        """B078: 处理 execute_command 消息，执行只读命令并返回结果。"""
        request_id = data.get("request_id", "")
        command = data.get("command", "")
        timeout = int(data.get("timeout") or DEFAULT_COMMAND_TIMEOUT)
        cwd = data.get("cwd") or None
        if cwd:
            cwd = os.path.expanduser(cwd)

        valid, reason = validate_command(command)
        if not valid:
            _log(f"execute_command 拒绝: {reason} command={command[:100]}")
            await self._client._send_ws_message({
                "type": "execute_command_result",
                "request_id": request_id,
                "exit_code": -1,
                "stdout": "",
                "stderr": reason,
                "truncated": False,
                "timed_out": False,
            })
            return

        try:
            parts = shlex.split(command)
        except ValueError:
            await self._client._send_ws_message({
                "type": "execute_command_result",
                "request_id": request_id,
                "exit_code": -1,
                "stdout": "",
                "stderr": "命令格式无效",
                "truncated": False,
                "timed_out": False,
            })
            return

        try:
            proc = await asyncio.create_subprocess_exec(
                *parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout,
                )
                timed_out = False
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                stdout_bytes = b""
                stderr_bytes = b"command timed out"
                timed_out = True

            stdout_str = stdout_bytes.decode("utf-8", errors="replace")
            stderr_str = stderr_bytes.decode("utf-8", errors="replace")

            truncated = len(stdout_str) > MAX_STDOUT_LEN or len(stderr_str) > MAX_STDERR_LEN
            stdout_str = stdout_str[:MAX_STDOUT_LEN]
            stderr_str = stderr_str[:MAX_STDERR_LEN]

            await self._client._send_ws_message({
                "type": "execute_command_result",
                "request_id": request_id,
                "exit_code": proc.returncode if proc.returncode is not None else -1,
                "stdout": stdout_str,
                "stderr": stderr_str,
                "truncated": truncated,
                "timed_out": timed_out,
            })
        except Exception as e:
            _log(f"execute_command 执行异常: {e}")
            await self._client._send_ws_message({
                "type": "execute_command_result",
                "request_id": request_id,
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "truncated": False,
                "timed_out": False,
            })

    async def _handle_lookup_knowledge(self, data: dict):
        """B091: 处理 lookup_knowledge 消息。"""
        request_id = data.get("request_id", "")
        query = data.get("query", "")
        try:
            result = lookup_knowledge(query)
            await self._client._send_ws_message({
                "type": "lookup_knowledge_result",
                "request_id": request_id,
                "result": result,
            })
        except Exception as e:
            _log(f"lookup_knowledge 检索异常: {e}")
            await self._client._send_ws_message({
                "type": "lookup_knowledge_result",
                "request_id": request_id,
                "result": "",
                "error": str(e),
            })

    async def _handle_tool_call(self, data: dict):
        """B092: 处理动态 MCP 工具调用。"""
        call_id = data.get("call_id", "")
        tool_name = data.get("tool_name", "")
        arguments = data.get("arguments", {})

        built_in_tools = {"execute_command", "ask_user", "lookup_knowledge"}
        if tool_name in built_in_tools:
            await self._client._send_ws_message({
                "type": "tool_result",
                "call_id": call_id,
                "status": "error",
                "error": f"built-in tool {tool_name} should use dedicated handler",
            })
            return

        try:
            result = await self._client.mcp_manager.call_tool(tool_name, arguments)
            response = {
                "type": "tool_result",
                "call_id": call_id,
                "status": result.get("status", "error"),
            }
            if "result" in result:
                response["result"] = result["result"]
            if "error" in result:
                response["error"] = result["error"]
            if result.get("truncated"):
                response["truncated"] = True
                response["original_size"] = result.get("original_size", 0)
            if result.get("fallback_hint"):
                response["fallback_hint"] = result["fallback_hint"]
            await self._client._send_ws_message(response)
        except Exception as e:
            _log(f"tool_call 异常: {e}")
            await self._client._send_ws_message({
                "type": "tool_result",
                "call_id": call_id,
                "status": "error",
                "error": str(e),
            })
