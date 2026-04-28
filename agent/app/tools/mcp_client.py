"""
B092: MCP Client 框架。

管理 MCP Server 子进程的生命周期（启动、工具发现、调用中转、崩溃处理）。
支持 stdio 传输协议，通过 JSON-RPC 与 MCP Server 通信。
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Optional

from app.tools.skill_registry import (
    SkillManifest,
    ensure_skills_dir,
    discover_skills,
)
from app.tools.mcp_rpc import (
    build_subprocess_env,
    filter_known_args,
    parse_tool,
    send_jsonrpc,
    send_notification,
    serialize_result,
    validate_args,
)
from app.tools.mcp_types import (
    MCPToolInfo,
    MCPServerState,
    MAX_TOOL_RESULT_SIZE,
    MAX_TOOLS_PER_SNAPSHOT,
    MAX_DESCRIPTION_LENGTH,
    MAX_SCHEMA_SIZE,
)

logger = logging.getLogger(__name__)
_AGENT_ROOT = Path(__file__).resolve().parents[2]


class MCPClientManager:
    """管理所有 MCP Server 子进程。"""

    def __init__(self):
        self._servers: dict[str, MCPServerState] = {}  # skill_name -> state

    @property
    def servers(self) -> dict[str, MCPServerState]:
        return self._servers

    async def start_all(self) -> None:
        """发现并启动所有已启用的 Skill。"""
        ensure_skills_dir()
        entries = discover_skills()

        for entry in entries:
            if not entry.enabled or entry.manifest is None:
                continue
            try:
                await self._start_skill(entry.manifest)
            except Exception as e:
                logger.warning("启动 Skill %s 失败，跳过: %s", entry.name, e)

    async def _start_skill(self, manifest: SkillManifest) -> None:
        """启动单个 MCP Server 子进程并获取工具列表。"""
        state = MCPServerState(
            skill_name=manifest.name,
            manifest=manifest,
        )

        try:
            # 构建启动命令
            cmd = [manifest.command] + manifest.args
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(_AGENT_ROOT),
                env=self._build_subprocess_env(),
            )
            state.process = process
            state.running = True

            # 初始化握手：发送 initialize 请求
            init_result = await self._send_jsonrpc(
                state,
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "rc-agent", "version": "1.0.0"},
                },
            )

            if init_result is None:
                await self._stop_skill(state)
                logger.warning("Skill %s 初始化失败，跳过", manifest.name)
                return

            # 发送 initialized 通知
            await self._send_notification(state, "notifications/initialized")

            # 获取工具列表
            tools_result = await self._send_jsonrpc(state, "tools/list", {})
            if tools_result and "tools" in tools_result:
                for tool_def in tools_result["tools"]:
                    tool_info = self._parse_tool(manifest.name, tool_def)
                    if tool_info:
                        state.tools.append(tool_info)

            self._servers[manifest.name] = state
            logger.info("Skill %s 启动成功，工具数: %d", manifest.name, len(state.tools))

        except Exception as e:
            logger.warning("启动 Skill %s 异常: %s", manifest.name, e)
            await self._stop_skill(state)

    def _build_subprocess_env(self) -> dict[str, str]:
        """为 MCP 子进程补齐 agent 包导入上下文。"""
        return build_subprocess_env(_AGENT_ROOT)

    async def _send_jsonrpc(
        self,
        state: MCPServerState,
        method: str,
        params: dict,
    ) -> Optional[dict]:
        """发送 JSON-RPC 请求并等待响应。"""
        return await send_jsonrpc(state, method, params)

    async def _send_notification(
        self,
        state: MCPServerState,
        method: str,
        params: dict | None = None,
    ) -> None:
        """发送 JSON-RPC 通知（无 id，不等待响应）。"""
        await send_notification(state, method, params)

    def _parse_tool(self, skill_name: str, tool_def: dict) -> Optional[MCPToolInfo]:
        """解析工具定义，检查 namespaced 格式和限制。"""
        return parse_tool(skill_name, tool_def)

    async def call_tool(
        self,
        namespaced_name: str,
        arguments: dict,
    ) -> dict:
        """调用动态 MCP 工具。

        Args:
            namespaced_name: 格式 skill_name.tool_name
            arguments: 工具参数

        Returns:
            tool_result 格式的 dict:
            - success: {"status": "success", "result": str}
            - error: {"status": "error", "error": str}
        """
        # 解析 skill_name 和 tool_name
        parts = namespaced_name.split(".", 1)
        if len(parts) != 2:
            return {"status": "error", "error": f"invalid tool name: {namespaced_name}"}

        skill_name, tool_name = parts
        state = self._servers.get(skill_name)
        if not state or not state.running:
            return {"status": "error", "error": f"MCP Server {skill_name} 不可用"}

        # 参数校验
        tool_info = None
        for t in state.tools:
            if t.tool_name == tool_name:
                tool_info = t
                break

        if tool_info is None:
            return {"status": "error", "error": f"工具 {namespaced_name} 不存在"}

        # 校验 required 参数
        validation_error = self._validate_args(tool_info, arguments)
        if validation_error:
            return {"status": "error", "error": validation_error}

        # 剥离 schema 未声明的额外参数，只转发已知字段
        filtered_args = self._filter_known_args(tool_info, arguments)

        # 调用 MCP Server
        try:
            result = await self._send_jsonrpc(
                state,
                "tools/call",
                {"name": tool_name, "arguments": filtered_args},
            )
        except Exception as e:
            return {"status": "error", "error": f"调用异常: {e}"}

        if result is None:
            # 检查进程是否仍在运行
            if not state.running:
                return {
                    "status": "error",
                    "error": f"MCP Server {skill_name} 已崩溃",
                    "fallback_hint": "retry_without_tool",
                }
            return {"status": "error", "error": f"工具 {namespaced_name} 调用无响应"}

        # 序列化结果
        serialized = self._serialize_result(result)

        # 截断检查
        if len(serialized.encode("utf-8")) > MAX_TOOL_RESULT_SIZE:
            original_size = len(serialized.encode("utf-8"))
            truncated = serialized[:MAX_TOOL_RESULT_SIZE]
            truncated += f"\n[已截断，原始大小 {original_size} bytes]"
            return {
                "status": "success",
                "result": truncated,
                "truncated": True,
                "original_size": original_size,
            }

        return {"status": "success", "result": serialized}

    def _validate_args(self, tool_info: MCPToolInfo, arguments: dict) -> Optional[str]:
        """校验参数，返回 None 表示通过，否则返回错误描述。"""
        return validate_args(tool_info, arguments)

    def _filter_known_args(self, tool_info: MCPToolInfo, arguments: dict) -> dict:
        """过滤参数，只保留 schema 中声明的字段。"""
        return filter_known_args(tool_info, arguments)

    def _serialize_result(self, result: Any) -> str:
        """序列化 MCP Server 返回的结果为文本。"""
        return serialize_result(result)

    async def _stop_skill(self, state: MCPServerState) -> None:
        """停止单个 MCP Server。"""
        state.running = False
        if state.process:
            try:
                state.process.terminate()
                await asyncio.wait_for(state.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                state.process.kill()
                await state.process.wait()
            except Exception:
                pass
            state.process = None

    async def stop_all(self) -> None:
        """停止所有 MCP Server。"""
        for state in list(self._servers.values()):
            await self._stop_skill(state)
        self._servers.clear()

    def get_all_tools(self) -> list[MCPToolInfo]:
        """获取所有已注册的动态工具列表。"""
        tools = []
        for state in self._servers.values():
            tools.extend(state.tools)
        return tools[:MAX_TOOLS_PER_SNAPSHOT]

    def build_tool_catalog(self) -> list[dict]:
        """构建 tool_catalog_snapshot 中的动态工具列表。"""
        tools = self.get_all_tools()
        catalog = []
        for tool in tools:
            catalog.append({
                "name": tool.namespaced_name,
                "kind": "dynamic",
                "skill": tool.skill_name,
                "description": tool.description,
                "parameters": tool.parameters,
                "capability": tool.capability,
            })
        return catalog

    async def check_health(self) -> None:
        """检查所有 MCP Server 健康状态，清理已崩溃的。"""
        to_remove = []
        for skill_name, state in self._servers.items():
            if not state.running:
                to_remove.append(skill_name)
                continue
            if state.process and state.process.returncode is not None:
                logger.warning("MCP Server %s 已退出 (code=%d)", skill_name, state.process.returncode)
                state.running = False
                to_remove.append(skill_name)

        for skill_name in to_remove:
            state = self._servers.pop(skill_name, None)
            if state:
                await self._stop_skill(state)
