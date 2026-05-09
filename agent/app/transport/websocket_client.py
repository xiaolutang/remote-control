"""
WebSocket 客户端 — 连接管理、心跳、重连、PTY 双向转发。
"""
import asyncio
import base64
import json
import logging
import os
import platform
import socket
import sys
from datetime import datetime, timezone
from typing import Optional

import websockets
from websockets import ClientConnection

from app.core.config import Config, ssl_context_for_websockets
from app.core.log_adapter import _log
from app.core.message_types import MessageType
from app.security.crypto import agent_crypto
from app.tools.knowledge_tool import (
    ensure_user_knowledge_dir,
    get_knowledge_catalog_entry,
)
from app.tools.mcp_client import MCPClientManager
from app.core.pty_wrapper import PTYWrapper, PTYConfig
from app.transport.agent_protocol import (
    TerminalSpec,
    TerminalSnapshotState,
    NON_RECOVERABLE_CODES,
    WS_CLOSE_NORMAL,
    WS_CLOSE_RECONNECT_FAILED,
)
from app.transport.agent_message_handler import AgentMessageHandler, _validate_terminal_input

logger = logging.getLogger(__name__)

__all__ = [
    "ReconnectExhausted",
    "AgentSnapshotManager",
    "TerminalRuntimeManager",
    "WebSocketClient",
    "TerminalSpec",
    "_validate_terminal_input",
]


class ReconnectExhausted(Exception):
    """重连次数耗尽，Agent 应在顶层捕获后执行清理再退出。"""

    def __init__(self, retry_count: int, max_retries: int, reason: str = "reconnect exhausted"):
        self.retry_count = retry_count
        self.max_retries = max_retries
        self.reason = reason
        super().__init__(
            f"{reason} (retries={retry_count}/{max_retries})"
        )



class AgentSnapshotManager:
    """维护 terminal 的权威恢复快照。"""

    _ALT_BUFFER_ENABLE_MARKERS = (
        b"\x1b[?1049h", b"\x1b[?1047h", b"\x1b[?47h",
    )
    _ALT_BUFFER_DISABLE_MARKERS = (
        b"\x1b[?1049l", b"\x1b[?1047l", b"\x1b[?47l",
    )

    def __init__(self, snapshot_limit_bytes: int = 128 * 1024):
        self._snapshot_limit_bytes = snapshot_limit_bytes
        self._states: dict[str, TerminalSnapshotState] = {}

    def create_terminal(self, spec: TerminalSpec) -> None:
        self._states[spec.terminal_id] = TerminalSnapshotState(
            terminal_id=spec.terminal_id, rows=spec.rows, cols=spec.cols,
        )

    def close_terminal(self, terminal_id: str) -> None:
        self._states.pop(terminal_id, None)

    def close_all(self) -> None:
        self._states.clear()

    def append_output(self, terminal_id: str, data: bytes) -> None:
        state = self._states.get(terminal_id)
        if state is None:
            return
        state.payload.extend(data)
        overflow = len(state.payload) - self._snapshot_limit_bytes
        if overflow > 0:
            del state.payload[:overflow]
        state.active_buffer = self._detect_active_buffer(state.active_buffer, data)

    def update_terminal_pty(self, terminal_id: str, rows: int, cols: int) -> None:
        state = self._states.get(terminal_id)
        if state is None:
            return
        state.rows = rows
        state.cols = cols

    def get_snapshot_payload(self, terminal_id: str) -> Optional[str]:
        state = self._states.get(terminal_id)
        if not state or not state.payload:
            return None
        return base64.b64encode(bytes(state.payload)).decode("utf-8")

    def get_snapshot_metadata(self, terminal_id: str) -> Optional[dict]:
        state = self._states.get(terminal_id)
        if state is None:
            return None
        return {"pty": {"rows": state.rows, "cols": state.cols}, "active_buffer": state.active_buffer}

    def build_snapshot_data(self, terminal_id: str) -> Optional[dict]:
        state = self._states.get(terminal_id)
        if state is None:
            return None
        payload = self.get_snapshot_payload(terminal_id)
        return {
            "terminal_id": terminal_id,
            "payload": payload or "",
            "pty": {"rows": state.rows, "cols": state.cols},
            "active_buffer": state.active_buffer,
        }

    @classmethod
    def _detect_active_buffer(cls, current: str, data: bytes) -> str:
        latest_index = -1
        next_state = current
        for marker in cls._ALT_BUFFER_ENABLE_MARKERS:
            index = data.rfind(marker)
            if index > latest_index:
                latest_index = index
                next_state = "alt"
        for marker in cls._ALT_BUFFER_DISABLE_MARKERS:
            index = data.rfind(marker)
            if index > latest_index:
                latest_index = index
                next_state = "main"
        return next_state


class TerminalRuntimeManager:
    """管理多个 terminal runtime。"""

    def __init__(self, pty_factory=PTYWrapper):
        self._pty_factory = pty_factory
        self._runtimes: dict[str, tuple[TerminalSpec, PTYWrapper]] = {}

    def create_terminal(self, spec: TerminalSpec) -> PTYWrapper:
        if spec.terminal_id in self._runtimes:
            raise ValueError(f"terminal {spec.terminal_id} already exists")
        runtime = self._pty_factory(
            spec.command, args=spec.args,
            config=PTYConfig(rows=spec.rows, cols=spec.cols, env=spec.env, cwd=spec.cwd),
        )
        if not runtime.start():
            err_msg = f"failed to start terminal {spec.terminal_id}"
            if runtime.start_error:
                err_msg += f": {runtime.start_error}"
            raise RuntimeError(err_msg)
        self._runtimes[spec.terminal_id] = (spec, runtime)
        return runtime

    def get_terminal(self, terminal_id: str) -> Optional[PTYWrapper]:
        entry = self._runtimes.get(terminal_id)
        return entry[1] if entry else None

    def list_terminals(self) -> list[TerminalSpec]:
        return [entry[0] for entry in self._runtimes.values()]

    def close_terminal(self, terminal_id: str, reason: str = "terminal_exit") -> dict:
        entry = self._runtimes.pop(terminal_id, None)
        if not entry:
            raise KeyError(terminal_id)
        spec, runtime = entry
        runtime.stop()
        return self.build_terminal_closed_event(terminal_id, reason)

    @staticmethod
    def build_terminal_closed_event(terminal_id: str, reason: str = "terminal_exit") -> dict:
        return {
            "type": MessageType.TERMINAL_CLOSED,
            "terminal_id": terminal_id,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def build_terminal_created_event(self, terminal_id: str) -> dict:
        entry = self._runtimes.get(terminal_id)
        if not entry:
            raise KeyError(terminal_id)
        spec, _ = entry
        return {
            "type": MessageType.TERMINAL_CREATED,
            "terminal_id": spec.terminal_id,
            "title": spec.title,
            "cwd": spec.cwd or "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def close_all(self, reason: str = "agent_shutdown") -> list[dict]:
        events = []
        for terminal_id in list(self._runtimes.keys()):
            events.append(self.close_terminal(terminal_id, reason=reason))
        return events


class WebSocketClient:
    """WebSocket 客户端，处理与服务器的通信"""

    def __init__(
        self,
        server_url: str,
        token: str,
        command: str = "/bin/bash",
        shell_mode: bool = False,
        auto_reconnect: bool = True,
        max_retries: int = 60,
        retry_delay: float = 1.0,
        local_display: bool = False,
    ):
        self.server_url = server_url
        self.token = token
        self.command = command
        self.shell_mode = shell_mode
        self.auto_reconnect = auto_reconnect
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.local_display = local_display

        self.ws: Optional[ClientConnection] = None
        self.pty: Optional[PTYWrapper] = None
        self._connected = False
        self._session_id: Optional[str] = None
        self._retry_count = 0
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._stdin_reader: Optional[asyncio.StreamReader] = None
        self.runtime_manager = TerminalRuntimeManager()
        self.snapshot_manager = AgentSnapshotManager()
        self._runtime_tasks: dict[str, asyncio.Task] = {}
        self._send_lock = asyncio.Lock()
        self.mcp_manager = MCPClientManager()
        self._local_server = None
        self._local_port: Optional[int] = None
        self._message_handler = AgentMessageHandler(self)

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    async def run(self):
        """主运行循环"""
        self._running = True
        _should_exit = False

        await self._start_local_server()

        while self._running:
            try:
                await self._connect_and_run()
            except websockets.exceptions.ConnectionClosedError as e:
                close_code = e.rcvd.code if e.rcvd else None
                if close_code in NON_RECOVERABLE_CODES:
                    logger.error("不可恢复错误 (code=%s)，停止重连: %s", close_code, e)
                    await self._cleanup()
                    self._running = False
                    _should_exit = True
                    break
                logger.warning("连接关闭: code=%s", close_code)
                _should_exit = await self._handle_reconnect()
                if _should_exit is not None:
                    break
            except Exception as e:
                logger.error("连接错误: %s", e)
                _should_exit = await self._handle_reconnect()
                if _should_exit is not None:
                    break

        if _should_exit:
            logger.info("Agent 重连耗尽，抛出 ReconnectExhausted")
            raise ReconnectExhausted(
                retry_count=self._retry_count,
                max_retries=self.max_retries,
                reason="reconnect exhausted",
            )

    async def _handle_reconnect(self) -> Optional[bool]:
        """处理重连逻辑。

        Returns:
            True  — 重连耗尽，应设置 _should_exit 并 break
            None  — 将继续重连（已 sleep + 递增计数）
            不返回 False — 未自动重连或已停止运行时也返回 None 让调用方 break
        """
        if not self.auto_reconnect or not self._running:
            return None
        if self._retry_count >= self.max_retries:
            logger.error("超过最大重试次数 (%s)，停止重连", self.max_retries)
            await self._cleanup(network_lost=True)
            return True
        delay = min(self.retry_delay * (2 ** self._retry_count), 60.0)
        logger.info("将在 %s 秒后重连 (第 %s 次)", delay, self._retry_count + 1)
        await asyncio.sleep(delay)
        self._retry_count += 1
        return None

    async def _connect_and_run(self):
        """连接服务器并运行主循环"""
        ws_url = f"{self.server_url}/ws/agent"
        logger.info("正在连接服务器: %s", self.server_url)

        if self.server_url.startswith("ws://") and not agent_crypto.has_public_key:
            http_base = self.server_url.replace("ws://", "http://")
            try:
                await agent_crypto.fetch_public_key(http_base)
            except Exception as e:
                logger.error("ws:// 公钥获取失败: %s", e)
                raise

        original_no_proxy = os.environ.get('NO_PROXY', '')
        os.environ['NO_PROXY'] = 'localhost,127.0.0.1,host.docker.internal'

        try:
            async with websockets.connect(
                ws_url,
                ping_interval=None,
                ssl=ssl_context_for_websockets() if ws_url.startswith("wss://") else None,
            ) as ws:
                self.ws = ws
                self._connected = True
                logger.info("已连接到服务器")

                try:
                    # auth 消息
                    auth_msg = {"type": MessageType.AUTH, "token": self.token}
                    ws_needs_encryption = self.server_url.startswith("ws://")

                    if ws_needs_encryption and not agent_crypto.has_public_key:
                        raise Exception("ws:// 连接必须加密，但公钥未获取")

                    if agent_crypto.has_public_key:
                        try:
                            agent_crypto.generate_aes_key()
                            auth_msg["encrypted_aes_key"] = agent_crypto.get_encrypted_aes_key_b64()
                            logger.info("AES key generated and encrypted")
                        except Exception as e:
                            logger.error("AES key exchange failed: %s", e)
                            agent_crypto.clear_aes_key()
                            if ws_needs_encryption:
                                raise Exception("ws:// 连接 AES 密钥交换失败") from e

                    await ws.send(json.dumps(auth_msg))

                    message = await asyncio.wait_for(ws.recv(), timeout=30)
                    data = json.loads(message)
                    if data.get("type") == MessageType.CONNECTED:
                        self._session_id = data.get("session_id")
                        self._retry_count = 0
                        logger.info("会话已建立: %s", self._session_id)
                    else:
                        raise Exception(f"意外的消息类型: {data.get('type')}")

                    await self._send_ws_message({
                        "type": MessageType.AGENT_METADATA,
                        "platform": platform.system().lower(),
                        "hostname": socket.gethostname(),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

                    ensure_user_knowledge_dir()
                    await self.mcp_manager.start_all()

                    catalog_tools = [get_knowledge_catalog_entry()]
                    catalog_tools.extend(self.mcp_manager.build_tool_catalog())
                    await self._send_ws_message({
                        "type": MessageType.TOOL_CATALOG_SNAPSHOT,
                        "tools": catalog_tools,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

                    self.pty = PTYWrapper(self.command)
                    if not self.pty.start():
                        raise Exception("无法启动 PTY")
                    logger.info("PTY 已启动: %s", self.command)

                    if self.local_display:
                        logger.info("本地终端显示已启用（本地键盘可直接操作）")
                        logger.info("-" * 40)

                    self._tasks = [
                        asyncio.create_task(self._pty_to_websocket()),
                        asyncio.create_task(self._websocket_to_pty()),
                        asyncio.create_task(self._heartbeat_loop()),
                    ]
                    if self.local_display:
                        self._tasks.append(asyncio.create_task(self._local_stdin_to_pty()))

                    await asyncio.gather(*self._tasks)

                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error("运行错误: %s", e)
                    raise
                finally:
                    await self._cleanup()
        finally:
            if original_no_proxy:
                os.environ['NO_PROXY'] = original_no_proxy
            else:
                os.environ.pop('NO_PROXY', None)

    async def _pty_to_websocket(self):
        """PTY 输出转发到 WebSocket"""
        while self._running and self._connected:
            try:
                data = await self.pty.read()
                if data is None:
                    await asyncio.sleep(0.01)
                    continue
                if self.local_display:
                    try:
                        sys.stdout.buffer.write(data)
                        sys.stdout.buffer.flush()
                    except Exception:
                        pass
                payload = base64.b64encode(data).decode("utf-8")
                await self._send_ws_message({
                    "type": MessageType.DATA, "payload": payload,
                    "direction": "output",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as e:
                logger.error("PTY 读取错误: %s", e)
                if isinstance(e, (websockets.exceptions.ConnectionClosedError,
                                  websockets.exceptions.ConnectionClosedOK)):
                    self._connected = False
                break

    async def _runtime_pty_to_websocket(self, terminal_id: str, runtime: PTYWrapper):
        """额外 terminal 的 PTY 输出转发到 WebSocket。"""
        try:
            while self._running and self._connected:
                data = await runtime.read()
                if data is None:
                    if not runtime.is_running():
                        break
                    await asyncio.sleep(0.01)
                    continue
                payload = base64.b64encode(data).decode("utf-8")
                self.snapshot_manager.append_output(terminal_id, data)
                await self._send_ws_message({
                    "type": MessageType.DATA, "terminal_id": terminal_id,
                    "payload": payload, "direction": "output",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
        finally:
            try:
                event = self.runtime_manager.close_terminal(terminal_id)
                self.snapshot_manager.close_terminal(terminal_id)
                await self._send_ws_message(event)
            except KeyError:
                pass
            self._runtime_tasks.pop(terminal_id, None)

    async def _websocket_to_pty(self):
        """WebSocket 消息接收循环 — 委派给 AgentMessageHandler"""
        while self._running and self._connected:
            try:
                message = await asyncio.wait_for(self.ws.recv(), timeout=1)
                data = json.loads(message)

                if data.get("encrypted") and agent_crypto.has_public_key:
                    try:
                        data = agent_crypto.decrypt_message(data)
                    except Exception as e:
                        logger.warning("Decrypt failed: %s", e)
                        continue

                await self._message_handler.dispatch(data)

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("WebSocket 接收错误: %s", e)
                self._connected = False
                break

    async def _send_ws_message(self, message: dict):
        """发送消息到 WebSocket（自动加密）。"""
        if self.ws and self._connected:
            msg_type = message.get("type", "")
            if agent_crypto.has_public_key and agent_crypto.should_encrypt(msg_type):
                try:
                    message = agent_crypto.encrypt_message(message)
                except Exception as e:
                    logger.error("Encrypt failed, dropping message: %s", e)
                    return
            text = json.dumps(message)
            async with self._send_lock:
                await self.ws.send(text)

    async def _local_stdin_to_pty(self):
        """本地标准输入转发到 PTY"""
        if not self.local_display:
            return
        try:
            loop = asyncio.get_event_loop()
            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            await loop.connect_read_pipe(lambda: protocol, sys.stdin)
            self._stdin_reader = reader

            while self._running and self._connected:
                try:
                    data = await asyncio.wait_for(reader.read(1024), timeout=0.1)
                    if data:
                        self.pty.write(data)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break
        except Exception as e:
            logger.error("本地输入读取错误: %s", e)

    async def _heartbeat_loop(self):
        """心跳循环"""
        while self._running and self._connected:
            try:
                await self._send_ws_message({"type": MessageType.PING})
                await asyncio.sleep(30)
            except Exception as e:
                logger.error("心跳发送错误: %s", e)
                self._connected = False
                break

    async def _start_local_server(self):
        """启动本地 HTTP Server"""
        try:
            from local_server import LocalServer
            self._local_server = LocalServer(self)
            success = await self._local_server.start()
            if success:
                self._local_port = self._local_server.port
                logger.info("本地控制服务已启动，端口: %s", self._local_port)
            else:
                logger.warning("本地控制服务启动失败，继续运行（无本地控制能力）")
        except Exception as e:
            logger.error("启动本地控制服务异常: %s", e)
            self._local_server = None

    async def _stop_local_server(self):
        if self._local_server:
            await self._local_server.stop()
            self._local_server = None
            self._local_port = None

    async def _cleanup(self, *, network_lost: bool = False):
        """清理资源

        Args:
            network_lost: True 表示因重连失败而退出（终端应进入 recoverable 状态），
                         False 表示主动退出（终端正常关闭）。
        """
        if not self._connected and not self._tasks:
            return

        close_reason = "network_lost" if network_lost else "agent_shutdown"
        ws_close_code = WS_CLOSE_RECONNECT_FAILED if network_lost else WS_CLOSE_NORMAL

        self._connected = False
        agent_crypto.clear_aes_key()
        await self.mcp_manager.stop_all()

        task_states = []
        for task in self._tasks:
            status = "done" if task.done() else "pending"
            if task.done() and not task.cancelled():
                try:
                    exc = task.exception()
                    if exc:
                        status = f"error({type(exc).__name__}: {exc})"
                except asyncio.CancelledError:
                    status = "cancelled"
            task_states.append(f"{task.get_name()}={status}")
        logger.info("断连原因排查 — 任务状态: %s, close_reason=%s", ', '.join(task_states), close_reason)

        for task in self._tasks:
            task.cancel()
        self._tasks = []

        for task in self._runtime_tasks.values():
            task.cancel()
        self._runtime_tasks = {}

        close_events = self.runtime_manager.close_all(reason=close_reason)
        self.snapshot_manager.close_all()
        if self.ws and close_events:
            for event in close_events:
                try:
                    await self._send_ws_message(event)
                except Exception:
                    pass

        if self.pty:
            self.pty.stop()
            self.pty = None

        if self.ws:
            try:
                await self.ws.close(code=ws_close_code, reason=close_reason)
            except Exception:
                try:
                    await self.ws.close()
                except Exception:
                    pass
            self.ws = None

        if self._local_server and not self._local_server.keep_running_in_background:
            await self._stop_local_server()

    async def stop(self):
        """停止客户端"""
        self._running = False
        await self._cleanup()
        logger.info("客户端已停止")
