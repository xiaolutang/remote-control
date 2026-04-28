"""
MCP 相关类型和常量。
"""
import asyncio
from dataclasses import dataclass, field
from typing import Optional

from app.skill_registry import SkillManifest

# 动态工具结果限制
MAX_TOOL_RESULT_SIZE = 64 * 1024  # 64 KB

# tool_catalog 限制
MAX_TOOLS_PER_SNAPSHOT = 50
MAX_DESCRIPTION_LENGTH = 500
MAX_SCHEMA_SIZE = 4 * 1024  # 4 KB


@dataclass
class MCPToolInfo:
    """单个动态 MCP 工具的注册信息。"""
    skill_name: str
    tool_name: str
    namespaced_name: str  # skill_name.tool_name
    description: str
    parameters: dict  # JSON Schema
    capability: str = "read_only"


@dataclass
class MCPServerState:
    """单个 MCP Server 的运行时状态。"""
    skill_name: str
    manifest: SkillManifest
    process: Optional[asyncio.subprocess.Process] = None
    tools: list[MCPToolInfo] = field(default_factory=list)
    stale: bool = False
    running: bool = False
    _next_id: int = 0

    def next_request_id(self) -> int:
        self._next_id += 1
        return self._next_id
