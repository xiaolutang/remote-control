"""
WebSocket 客户端
"""
import asyncio
import base64
import json
import logging
import os
import platform
import socket
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import websockets
from websockets import ClientConnection

from app.pty_wrapper import PTYWrapper, PTYConfig


from app.config import Config

logger = logging.getLogger(__name__)


def _validate_terminal_input(command, cwd, env) -> Optional[str]:
    """B068: 校验 terminal 创建参数。返回 None 表示通过，否则返回错误描述。"""
    # command 必须为字符串且非空
    if not isinstance(command, str):
        return f"command must be string, got {type(command).__name__}"
    if not command.strip():
        return "command must not be empty"
    # cwd 如果提供，必须为绝对路径
    if cwd is not None:
        if not isinstance(cwd, str):
            return f"cwd must be string, got {type(cwd).__name__}"
        import os.path
        if not os.path.isabs(cwd):
            return f"cwd must be absolute path, got '{cwd}'"
    # env 值必须为字符串
    if not isinstance(env, dict):
        return f"env must be dict, got {type(env).__name__}"
    for k, v in env.items():
        if not isinstance(v, str):
            return f"env['{k}'] must be string, got {type(v).__name__}"
    return None


def _log(message: str) -> None:
    """Agent 日志输出到 stderr + logging（SDK handler 自动上报到 log-service）"""
    if os.environ.get("FLUTTER_TEST"):
        return
    print(f"[Agent] {message}", file=sys.stderr, flush=True)
    logger.info(message)


@dataclass
class TerminalSpec:
    """终端运行参数。"""
    terminal_id: str
    command: str
    args: list[str] = field(default_factory=list)
    cwd: Optional[str] = None
    env: dict = field(default_factory=dict)
    title: str = ""


class TerminalRuntimeManager:
    """管理多个 terminal runtime。"""

    def __init__(self, pty_factory=PTYWrapper):
        self._pty_factory = pty_factory
        self._runtimes: dict[str, tuple[TerminalSpec, PTYWrapper]] = {}

    def create_terminal(self, spec: TerminalSpec) -> PTYWrapper:
        if spec.terminal_id in self._runtimes:
            raise ValueError(f"terminal {spec.terminal_id} already exists")

        runtime = self._pty_factory(
            spec.command,
            args=spec.args,
            config=PTYConfig(env=spec.env, cwd=spec.cwd),
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
            "type": "terminal_closed",
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
            "type": "terminal_created",
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
        max_retries: int = 5,
        retry_delay: float = 1.0,
        local_display: bool = False,
    ):
        """
        初始化 WebSocket 客户端

        Args:
            server_url: 服务器 WebSocket URL (wss://...)
            token: 认证 Token
            command: 要执行的命令
            shell_mode: 是否启动交互式 shell
            auto_reconnect: 是否自动重连
            max_retries: 最大重试次数
            retry_delay: 初始重连延迟（秒）
            local_display: 是否在本地终端显示 PTY 输出
        """
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
        self._runtime_tasks: dict[str, asyncio.Task] = {}
        self._send_lock = asyncio.Lock()
        # 本地 HTTP Server（用于 Flutter UI 控制）
        self._local_server = None
        self._local_port: Optional[int] = None

    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._connected

    @property
    def session_id(self) -> Optional[str]:
        """当前会话 ID"""
        return self._session_id

    # 不可恢复的 WebSocket close code（服务器主动拒绝，重连无意义）
    _NON_RECOVERABLE_CODES = {4001, 4004, 4009}

    async def run(self):
        """主运行循环"""
        self._running = True

        # 启动本地 HTTP Server（用于 Flutter UI 控制）
        await self._start_local_server()

        while self._running:
            try:
                await self._connect_and_run()
            except websockets.exceptions.ConnectionClosedError as e:
                # 结构化检查 WebSocket close code
                close_code = e.rcvd.code if e.rcvd else None
                if close_code in self._NON_RECOVERABLE_CODES:
                    _log(f"不可恢复错误 (code={close_code})，停止重连: {e}")
                    self._running = False
                    break
                _log(f"连接关闭: code={close_code}")
                if not self.auto_reconnect or not self._running:
                    break
                if self._retry_count >= self.max_retries:
                    _log(f"超过最大重试次数 ({self.max_retries})，停止重连")
                    break
                delay = self.retry_delay * (2 ** self._retry_count)
                _log(f"将在 {delay} 秒后重连 (第 {self._retry_count + 1} 次)")
                await asyncio.sleep(delay)
                self._retry_count += 1
            except Exception as e:
                _log(f"连接错误: {e}")
                if not self.auto_reconnect or not self._running:
                    break

                if self._retry_count >= self.max_retries:
                    _log(f"超过最大重试次数 ({self.max_retries})，停止重连")
                    break
                # 指数退避
                delay = self.retry_delay * (2 ** self._retry_count)
                _log(f"将在 {delay} 秒后重连 (第 {self._retry_count + 1} 次)")
                await asyncio.sleep(delay)
                self._retry_count += 1

    async def _connect_and_run(self):
        """连接服务器并运行主循环"""
        # B068: token 不再通过 URL query 参数传递
        ws_url = f"{self.server_url}/ws/agent"

        _log(f"正在连接服务器: {self.server_url}")

        # 禁用代理 - 设置 NO_PROXY 环境变量
        import os
        original_no_proxy = os.environ.get('NO_PROXY', '')
        os.environ['NO_PROXY'] = 'localhost,127.0.0.1,host.docker.internal'

        try:
            async with websockets.connect(
                ws_url,
                ping_interval=None,  # 禁用协议级 ping，使用应用级心跳（30s）
            ) as ws:
                self.ws = ws
                self._connected = True
                _log("已连接到服务器")

                try:
                    # B068: 发送 auth 消息进行鉴权
                    await ws.send(json.dumps({
                        "type": "auth",
                        "token": self.token,
                    }))

                    # 等待连接确认消息
                    # 等待连接确认消息
                    message = await asyncio.wait_for(ws.recv(), timeout=30)
                    data = json.loads(message)
                    if data.get("type") == "connected":
                        self._session_id = data.get("session_id")
                        self._retry_count = 0  # 仅在握手成功后重置重试计数
                        _log(f"会话已建立: {self._session_id}")
                    else:
                        raise Exception(f"意外的消息类型: {data.get('type')}")

                    await self._send_ws_message({
                        "type": "agent_metadata",
                        "platform": platform.system().lower(),
                        "hostname": socket.gethostname(),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

                    # 启动 PTY
                    self.pty = PTYWrapper(self.command)
                    if not self.pty.start():
                        raise Exception("无法启动 PTY")

                    _log(f"PTY 已启动: {self.command}")

                    if self.local_display:
                        _log("本地终端显示已启用（本地键盘可直接操作）")
                        _log("-" * 40)

                    # 启动双向转发任务
                    self._tasks = [
                        asyncio.create_task(self._pty_to_websocket()),
                        asyncio.create_task(self._websocket_to_pty()),
                        asyncio.create_task(self._heartbeat_loop()),
                    ]

                    # 添加本地输入任务
                    if self.local_display:
                        self._tasks.append(asyncio.create_task(self._local_stdin_to_pty()))

                    # 等待所有任务完成
                    await asyncio.gather(*self._tasks)

                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    _log(f"运行错误: {e}")
                    raise
                finally:
                    await self._cleanup()
        finally:
            # 恢复 NO_PROXY 设置
            if original_no_proxy:
                os.environ['NO_PROXY'] = original_no_proxy
            else:
                os.environ.pop('NO_PROXY', None)

    async def _pty_to_websocket(self):
        """PTY 输出转发到 WebSocket（同时显示在本地终端）"""
        while self._running and self._connected:
            try:
                data = await self.pty.read()
                if data is None:
                    await asyncio.sleep(0.01)
                    continue

                # 本地显示
                if self.local_display:
                    try:
                        sys.stdout.buffer.write(data)
                        sys.stdout.buffer.flush()
                    except Exception:
                        pass

                # Base64 编码
                payload = base64.b64encode(data).decode("utf-8")

                message = {
                    "type": "data",
                    "payload": payload,
                    "direction": "output",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

                await self._send_ws_message(message)

            except Exception as e:
                _log(f"PTY 读取错误: {e}")
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
                await self._send_ws_message({
                    "type": "data",
                    "terminal_id": terminal_id,
                    "payload": payload,
                    "direction": "output",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
        finally:
            try:
                event = self.runtime_manager.close_terminal(terminal_id)
                await self._send_ws_message(event)
            except KeyError:
                pass
            self._runtime_tasks.pop(terminal_id, None)

    async def _websocket_to_pty(self):
        """WebSocket 消息转发到 PTY（同时显示在本地终端）"""
        while self._running and self._connected:
            try:
                message = await asyncio.wait_for(self.ws.recv(), timeout=1)
                data = json.loads(message)
                msg_type = data.get("type")
                _log(f"收到消息 type={msg_type} data={json.dumps(data, ensure_ascii=False)[:200]}")

                if msg_type == "data":
                    # 解码 Base64 数据
                    payload = data.get("payload", "")
                    try:
                        decoded = base64.b64decode(payload)
                    except Exception:
                        decoded = payload.encode("utf-8")

                    try:
                        terminal_id = data.get("terminal_id")
                        target = self.runtime_manager.get_terminal(terminal_id) if terminal_id else self.pty
                        if target:
                            target.write(decoded)
                    except Exception as e:
                        _log(f"数据写入失败: {e}")

                elif msg_type == "resize":
                    # 终端大小变化
                    try:
                        rows = data.get("rows", 24)
                        cols = data.get("cols", 80)
                        terminal_id = data.get("terminal_id")
                        target = self.runtime_manager.get_terminal(terminal_id) if terminal_id else self.pty
                        if target:
                            target.resize(rows, cols)
                    except Exception as e:
                        _log(f"终端大小调整失败: {e}")

                elif msg_type == "create_terminal":
                    terminal_id = data.get("terminal_id")
                    if not terminal_id:
                        continue
                    # B068: 命令执行校验
                    command = data.get("command", self.command)
                    cwd = data.get("cwd")
                    env = data.get("env", {}) or {}
                    validation_error = _validate_terminal_input(command, cwd, env)
                    if validation_error:
                        _log(f"Terminal {terminal_id} 输入校验失败: {validation_error}")
                        await self._send_ws_message(
                            self.runtime_manager.build_terminal_closed_event(
                                terminal_id, reason=f"validation_failed: {validation_error}"
                            )
                        )
                        continue
                    try:
                        spec = TerminalSpec(
                            terminal_id=terminal_id,
                            title=data.get("title", terminal_id),
                            cwd=cwd,
                            command=command,
                            env=env,
                        )
                        runtime = self.runtime_manager.create_terminal(spec)
                        self._runtime_tasks[terminal_id] = asyncio.create_task(
                            self._runtime_pty_to_websocket(terminal_id, runtime)
                        )
                        await self._send_ws_message(
                            self.runtime_manager.build_terminal_created_event(terminal_id)
                        )
                    except Exception as e:
                        # 终端创建失败不应断开 Agent 连接
                        _log(f"Terminal {terminal_id} 创建失败: {e}")
                        try:
                            await self._send_ws_message(
                                self.runtime_manager.build_terminal_closed_event(
                                    terminal_id, reason="create_failed"
                                )
                            )
                        except Exception:
                            pass  # WS 本身也断了，无法通知，静默忽略
                        continue

                elif msg_type == "close_terminal":
                    terminal_id = data.get("terminal_id")
                    try:
                        if terminal_id and self.runtime_manager.get_terminal(terminal_id):
                            event = self.runtime_manager.close_terminal(
                                terminal_id,
                                reason=data.get("reason", "terminal_exit"),
                            )
                            task = self._runtime_tasks.pop(terminal_id, None)
                            if task:
                                task.cancel()
                            await self._send_ws_message(event)
                    except Exception as e:
                        _log(f"Terminal {terminal_id} 关闭失败: {e}")
                        continue

                elif msg_type == "pong":
                    # 心跳响应，忽略
                    pass

                elif msg_type == "error":
                    _log(f"服务器错误: {data.get('message')}")
                    break

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                _log(f"WebSocket 接收错误: {e}")
                break

    async def _send_ws_message(self, message: dict):
        """发送消息到 WebSocket。

        使用 asyncio.Lock 确保 ws.send() 不被并发调用。
        json.dumps 在 Lock 外完成，避免不必要地延长 Lock 持有时间。
        """
        if self.ws and self._connected:
            text = json.dumps(message)
            async with self._send_lock:
                await self.ws.send(text)

    async def _local_stdin_to_pty(self):
        """本地标准输入转发到 PTY"""
        if not self.local_display:
            return

        try:
            # 设置 stdin 为非阻塞模式
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
            _log(f"本地输入读取错误: {e}")

    async def _heartbeat_loop(self):
        """心跳循环"""
        while self._running and self._connected:
            try:
                await self._send_ws_message({"type": "ping"})
                await asyncio.sleep(30)  # 30 秒心跳间隔
            except Exception as e:
                _log(f"心跳发送错误: {e}")
                break

    async def _start_local_server(self):
        """启动本地 HTTP Server（用于 Flutter UI 控制）"""
        try:
            from local_server import LocalServer

            self._local_server = LocalServer(self)
            success = await self._local_server.start()
            if success:
                self._local_port = self._local_server.port
                _log(f"本地控制服务已启动，端口: {self._local_port}")
            else:
                _log("本地控制服务启动失败，继续运行（无本地控制能力）")
        except Exception as e:
            _log(f"启动本地控制服务异常: {e}")
            self._local_server = None

    async def _stop_local_server(self):
        """停止本地 HTTP Server"""
        if self._local_server:
            await self._local_server.stop()
            self._local_server = None
            self._local_port = None

    async def _cleanup(self):
        """清理资源"""
        if not self._connected and not self._tasks:
            return  # 避免重复清理

        self._connected = False

        # 记录各任务状态，用于排查断连原因
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
        _log(f"断连原因排查 — 任务状态: {', '.join(task_states)}")

        # 取消所有任务
        for task in self._tasks:
            task.cancel()

        self._tasks = []

        for task in self._runtime_tasks.values():
            task.cancel()
        self._runtime_tasks = {}

        # 关闭所有 terminal 并发送关闭事件
        close_events = self.runtime_manager.close_all()
        if self.ws and close_events:
            for event in close_events:
                try:
                    await self._send_ws_message(event)
                except Exception:
                    pass  # 忽略发送失败

        # 停止 PTY
        if self.pty:
            self.pty.stop()
            self.pty = None

        # 关闭 WebSocket
        if self.ws:
            await self.ws.close()
            self.ws = None

        # 停止本地 HTTP Server（如果不需要后台运行）
        if self._local_server and not self._local_server.keep_running_in_background:
            await self._stop_local_server()

    async def stop(self):
        """停止客户端"""
        self._running = False
        await self._cleanup()
        _log("客户端已停止")
