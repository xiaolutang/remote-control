"""
Agent 本地 HTTP Server

提供控制面 API，用于 Flutter UI 与本地 Agent 进程通信。
只用于控制面（启动/停止/状态查询/配置），不传输终端数据。
"""
import asyncio
import json
import os
import secrets
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable, Awaitable

from aiohttp import web


# 端口配置
DEFAULT_PORT = 18765
PORT_RANGE = range(18765, 18770)  # 5 个候选端口: 18765-18769
BIND_ADDRESS = "127.0.0.1"


def _log(message: str) -> None:
    """日志输出到 stderr"""
    if os.environ.get("FLUTTER_TEST"):
        return
    print(f"[LocalServer] {message}", file=sys.stderr, flush=True)


def get_state_file_path() -> Path:
    """
    获取状态文件路径（跨平台）

    Returns:
        状态文件的完整路径
    """
    if sys.platform == "darwin":
        # macOS: ~/Library/Application Support/remote-control/
        base = Path.home() / "Library" / "Application Support" / "remote-control"
    elif sys.platform == "win32":
        # Windows: %APPDATA%/remote-control/
        base = Path(os.environ.get("APPDATA", Path.home())) / "remote-control"
    else:
        # Linux 和其他: ~/.local/share/remote-control/
        base = Path.home() / ".local" / "share" / "remote-control"

    return base / "agent-state.json"


def write_state_file(state: dict) -> None:
    """写入状态文件"""
    state_file = get_state_file_path()
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    _log(f"状态文件已写入: {state_file}")


def read_state_file() -> Optional[dict]:
    """读取状态文件"""
    state_file = get_state_file_path()
    if not state_file.exists():
        return None
    try:
        return json.loads(state_file.read_text())
    except (json.JSONDecodeError, IOError) as e:
        _log(f"读取状态文件失败: {e}")
        return None


def clear_state_file() -> None:
    """清理状态文件"""
    state_file = get_state_file_path()
    if state_file.exists():
        state_file.unlink()
        _log(f"状态文件已清理: {state_file}")


def is_process_alive(pid: int) -> bool:
    """检查进程是否存活"""
    try:
        os.kill(pid, 0)  # 0 = 检查进程存在但不发送信号
        return True
    except OSError:
        return False


def find_available_port() -> Optional[int]:
    """
    找到可用端口

    Returns:
        可用端口号，如果全部被占用返回 None
    """
    for port in PORT_RANGE:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((BIND_ADDRESS, port))
                return port
        except OSError:
            continue
    return None


def check_port_in_use(port: int) -> bool:
    """检查端口是否被占用"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((BIND_ADDRESS, port))
            return False
    except OSError:
        return True


class LocalServer:
    """Agent 本地 HTTP Server"""

    def __init__(
        self,
        agent_client,  # WebSocketClient 实例
        port: Optional[int] = None,
    ):
        """
        初始化本地 HTTP Server

        Args:
            agent_client: WebSocketClient 实例，用于获取 Agent 状态和控制
            port: 指定端口，如果为 None 则自动选择
        """
        self.agent_client = agent_client
        self.port = port or DEFAULT_PORT
        self.app: Optional[web.Application] = None
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self._running = False
        self._keep_running_in_background = True
        # B068: 本地 HTTP token 认证
        self._local_token: Optional[str] = None

    @property
    def keep_running_in_background(self) -> bool:
        """是否在后台运行"""
        return self._keep_running_in_background

    @keep_running_in_background.setter
    def keep_running_in_background(self, value: bool):
        self._keep_running_in_background = value

    def _collect_terminals(self) -> list[dict]:
        """收集终端列表"""
        runtime_manager = getattr(self.agent_client, "runtime_manager", None)
        terminals = []
        if runtime_manager:
            for spec in runtime_manager.list_terminals():
                terminals.append({
                    "id": spec.terminal_id,
                    "title": spec.title,
                    "cwd": spec.cwd,
                    "command": spec.command,
                })
        return terminals

    def _setup_routes(self):
        """设置路由"""
        self.app.add_routes([
            web.get("/health", self._handle_health),
            web.get("/status", self._handle_status),
            web.post("/stop", self._handle_stop),
            web.post("/config", self._handle_config),
            web.get("/terminals", self._handle_terminals),
            # B095: Skill/Knowledge 管理 API
            web.get("/skills", self._handle_skills),
            web.post("/skills/toggle", self._handle_skills_toggle),
            web.get("/knowledge", self._handle_knowledge),
            web.post("/knowledge/toggle", self._handle_knowledge_toggle),
        ])
        # B068: 添加 token 认证中间件（health 端点除外）
        self.app.middlewares.append(self._auth_middleware)

    @web.middleware
    async def _auth_middleware(self, request: web.Request, handler):
        """Token 认证中间件，/health 端点免认证"""
        if request.path == "/health":
            return await handler(request)
        if not self._local_token:
            return await handler(request)
        # 检查 Authorization: Bearer <token>
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if token == self._local_token:
                return await handler(request)
        return web.json_response(
            {"ok": False, "error": "Unauthorized"},
            status=401,
        )

    async def _handle_health(self, request: web.Request) -> web.Response:
        """健康检查端点"""
        return web.json_response({"status": "ok"})

    async def _handle_status(self, request: web.Request) -> web.Response:
        """获取 Agent 状态"""
        terminals = self._collect_terminals()

        return web.json_response({
            "running": self._running,
            "pid": os.getpid(),
            "port": self.port,
            "server_url": self.agent_client.server_url,
            "connected": self.agent_client.is_connected,
            "session_id": self.agent_client.session_id,
            "terminals_count": len(terminals),
            "terminals": terminals,
            "keep_running_in_background": self._keep_running_in_background,
        })

    async def _handle_stop(self, request: web.Request) -> web.Response:
        """停止 Agent"""
        try:
            data = await request.json()
        except (json.JSONDecodeError, ValueError):
            data = {}

        grace_timeout = data.get("grace_timeout", 5)

        _log(f"收到停止命令，grace_timeout={grace_timeout}")

        # 清理状态文件
        clear_state_file()

        # 触发 Agent 停止（通过调用 stop() 方法而非直接修改私有属性）
        asyncio.create_task(self._trigger_stop())

        return web.json_response({"ok": True, "message": "Agent 正在停止"})

    async def _trigger_stop(self):
        """延迟触发停止，确保 HTTP 响应先发送"""
        await asyncio.sleep(0.1)
        # 设置 _running = False 会触发 WebSocketClient 主循环退出
        self.agent_client._running = False

    async def _handle_config(self, request: web.Request) -> web.Response:
        """更新配置"""
        try:
            data = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response(
                {"ok": False, "error": "无效的 JSON"},
                status=400,
            )

        updated = []

        if "keep_running_in_background" in data:
            self._keep_running_in_background = bool(data["keep_running_in_background"])
            updated.append("keep_running_in_background")

            # 更新状态文件
            state = read_state_file() or {}
            state["keep_running"] = self._keep_running_in_background
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
            write_state_file(state)

        return web.json_response({
            "ok": True,
            "updated": updated,
            "keep_running_in_background": self._keep_running_in_background,
        })

    async def _handle_terminals(self, request: web.Request) -> web.Response:
        """获取终端列表"""
        terminals = self._collect_terminals()

        return web.json_response({
            "terminals": terminals,
            "count": len(terminals),
        })

    # ─── B095: Skill/Knowledge 管理 API ───

    async def _handle_skills(self, request: web.Request) -> web.Response:
        """GET /skills — 返回所有已发现 skill 列表及启用状态"""
        from app.skill_registry import discover_skills

        entries = discover_skills()
        skills = []
        for entry in entries:
            item = {
                "name": entry.name,
                "description": entry.manifest.description if entry.manifest else "",
                "enabled": entry.enabled,
            }
            skills.append(item)

        return web.json_response({"skills": skills, "count": len(skills)})

    async def _handle_skills_toggle(self, request: web.Request) -> web.Response:
        """POST /skills/toggle — 切换指定 skill 启用/禁用"""
        from app.skill_registry import (
            discover_skills,
            load_skill_registry,
            save_skill_registry,
        )

        try:
            data = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response(
                {"ok": False, "error": "无效的 JSON"},
                status=400,
            )

        name = data.get("name")
        enabled = data.get("enabled")

        if not isinstance(name, str) or not name.strip():
            return web.json_response(
                {"ok": False, "error": "缺少有效的 name 参数"},
                status=400,
            )
        if not isinstance(enabled, bool):
            return web.json_response(
                {"ok": False, "error": "缺少有效的 enabled 参数"},
                status=400,
            )

        # 检查 skill 是否存在
        entries = discover_skills()
        found = any(e.name == name for e in entries)
        if not found:
            return web.json_response(
                {"ok": False, "error": f"Skill '{name}' 不存在"},
                status=404,
            )

        # 更新 registry
        registry = load_skill_registry()
        registry[name] = enabled
        save_skill_registry(registry)

        return web.json_response({"ok": True, "name": name, "enabled": enabled})

    async def _handle_knowledge(self, request: web.Request) -> web.Response:
        """GET /knowledge — 返回所有知识文件列表及启用状态"""
        from app.knowledge_tool import load_knowledge_config, _scan_all_knowledge_files

        config = load_knowledge_config()
        all_files = _scan_all_knowledge_files()

        files = []
        for filename, path in all_files:
            files.append({
                "filename": filename,
                "enabled": config.is_enabled(filename),
            })

        return web.json_response({"knowledge": files, "count": len(files)})

    async def _handle_knowledge_toggle(self, request: web.Request) -> web.Response:
        """POST /knowledge/toggle — 切换指定知识文件启用/禁用"""
        from app.knowledge_tool import (
            load_knowledge_config,
            save_knowledge_config,
            _scan_all_knowledge_files,
        )

        try:
            data = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response(
                {"ok": False, "error": "无效的 JSON"},
                status=400,
            )

        filename = data.get("filename")
        enabled = data.get("enabled")

        if not isinstance(filename, str) or not filename.strip():
            return web.json_response(
                {"ok": False, "error": "缺少有效的 filename 参数"},
                status=400,
            )
        if not isinstance(enabled, bool):
            return web.json_response(
                {"ok": False, "error": "缺少有效的 enabled 参数"},
                status=400,
            )

        # 检查文件是否存在
        all_files = _scan_all_knowledge_files()
        found = any(f[0] == filename for f in all_files)
        if not found:
            return web.json_response(
                {"ok": False, "error": f"Knowledge file '{filename}' 不存在"},
                status=404,
            )

        # 更新配置
        config = load_knowledge_config()
        if enabled:
            config.disabled_files.discard(filename)
        else:
            config.disabled_files.add(filename)
        save_knowledge_config(config)

        return web.json_response({"ok": True, "filename": filename, "enabled": enabled})

    async def start(self) -> bool:
        """
        启动本地 HTTP Server

        Returns:
            是否成功启动
        """
        # 如果没有指定端口，尝试找一个可用端口
        if self.port == DEFAULT_PORT and check_port_in_use(self.port):
            found_port = find_available_port()
            if found_port is None:
                _log("所有候选端口都被占用")
                return False
            if found_port != self.port:
                _log(f"默认端口 {DEFAULT_PORT} 被占用，使用端口 {found_port}")
            self.port = found_port

        self.app = web.Application()
        self._setup_routes()

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        try:
            self.site = web.TCPSite(self.runner, BIND_ADDRESS, self.port)
            await self.site.start()
            self._running = True

            # B068: 生成 local_token 并写入状态文件
            self._local_token = secrets.token_hex(32)

            # 写入状态文件
            write_state_file({
                "pid": os.getpid(),
                "port": self.port,
                "server_url": self.agent_client.server_url,
                "session_id": self.agent_client.session_id,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "keep_running": self._keep_running_in_background,
                "local_token": self._local_token,
            })

            _log(f"本地 HTTP Server 已启动: http://{BIND_ADDRESS}:{self.port}")
            return True

        except OSError as e:
            _log(f"启动本地 HTTP Server 失败: {e}")
            return False

    async def stop(self):
        """停止本地 HTTP Server"""
        self._running = False

        if self.runner:
            await self.runner.cleanup()
            self.runner = None
            self.site = None

        _log("本地 HTTP Server 已停止")


async def discover_local_agent() -> Optional[dict]:
    """
    发现本地运行的 Agent

    优先通过状态文件发现，如果失败则扫描端口范围。

    Returns:
        Agent 状态信息，如果未找到返回 None
    """
    import aiohttp

    # 1. 尝试通过状态文件发现
    state = read_state_file()
    if state:
        port = state.get("port")
        pid = state.get("pid")

        # 检查进程是否存在
        if pid and is_process_alive(pid):
            # 健康检查
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"http://{BIND_ADDRESS}:{port}/health",
                        timeout=aiohttp.ClientTimeout(total=2),
                    ) as resp:
                        if resp.status == 200:
                            _log(f"通过状态文件发现 Agent: port={port}, pid={pid}")
                            return state
            except Exception as e:
                _log(f"状态文件中的 Agent 无响应: {e}")
        else:
            _log(f"状态文件中的进程已不存在: pid={pid}")

    # 2. 扫描端口范围
    for port in PORT_RANGE:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"http://{BIND_ADDRESS}:{port}/health",
                    timeout=aiohttp.ClientTimeout(total=1),
                ) as resp:
                    if resp.status == 200:
                        _log(f"通过端口扫描发现 Agent: port={port}")
                        # 获取完整状态
                        async with session.get(
                            f"http://{BIND_ADDRESS}:{port}/status",
                            timeout=aiohttp.ClientTimeout(total=2),
                        ) as status_resp:
                            if status_resp.status == 200:
                                return await status_resp.json()
        except Exception:
            continue

    return None
