"""
MCP 子进程通信与工具解析辅助函数。
"""
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from app.tools.mcp_types import (
    MCPServerState,
    MCPToolInfo,
    MAX_DESCRIPTION_LENGTH,
    MAX_SCHEMA_SIZE,
)

logger = logging.getLogger(__name__)


def build_subprocess_env(agent_root: Path) -> dict[str, str]:
    """为 MCP 子进程补齐 agent 包导入上下文。"""
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    path_parts = [str(agent_root)]
    if existing:
        path_parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(path_parts)
    return env


async def send_jsonrpc(
    state: MCPServerState,
    method: str,
    params: dict,
) -> Optional[dict]:
    """发送 JSON-RPC 请求并等待响应。"""
    if not state.process or not state.running:
        return None

    request_id = state.next_request_id()
    request = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    }

    try:
        msg = json.dumps(request) + "\n"
        state.process.stdin.write(msg.encode("utf-8"))
        await state.process.stdin.drain()

        timeout = state.manifest.timeout
        response_line = await asyncio.wait_for(
            state.process.stdout.readline(), timeout=timeout
        )

        if not response_line:
            state.running = False
            return None

        response = json.loads(response_line.decode("utf-8"))
        if "error" in response:
            logger.warning("MCP %s.%s 错误: %s", state.skill_name, method, response["error"])
            return None

        return response.get("result")
    except asyncio.TimeoutError:
        logger.warning("MCP %s.%s 超时 (%ds)", state.skill_name, method, timeout)
        return None
    except Exception as e:
        logger.warning("MCP %s.%s 通信失败: %s", state.skill_name, method, e)
        state.running = False
        return None


async def send_notification(
    state: MCPServerState,
    method: str,
    params: dict | None = None,
) -> None:
    """发送 JSON-RPC 通知。"""
    if not state.process or not state.running:
        return

    notification = {"jsonrpc": "2.0", "method": method}
    if params:
        notification["params"] = params

    try:
        msg = json.dumps(notification) + "\n"
        state.process.stdin.write(msg.encode("utf-8"))
        await state.process.stdin.drain()
    except Exception as e:
        logger.warning("发送通知失败: %s", e)


def parse_tool(skill_name: str, tool_def: dict) -> Optional[MCPToolInfo]:
    """解析工具定义。"""
    tool_name = tool_def.get("name", "")
    if not tool_name:
        logger.warning("工具定义缺少 name: %s", tool_def)
        return None

    description = tool_def.get("description", "")
    if len(description) > MAX_DESCRIPTION_LENGTH:
        description = description[:MAX_DESCRIPTION_LENGTH]

    parameters = tool_def.get("inputSchema", tool_def.get("parameters", {}))
    if not isinstance(parameters, dict):
        parameters = {"type": "object", "properties": {}}

    if len(json.dumps(parameters)) > MAX_SCHEMA_SIZE:
        logger.warning("工具 %s.%s schema 超出 4KB 限制，跳过", skill_name, tool_name)
        return None

    return MCPToolInfo(
        skill_name=skill_name,
        tool_name=tool_name,
        namespaced_name=f"{skill_name}.{tool_name}",
        description=description,
        parameters=parameters,
        capability=tool_def.get("capability", "read_only"),
    )


def validate_args(tool_info: MCPToolInfo, arguments: dict) -> Optional[str]:
    """校验工具参数。"""
    schema = tool_info.parameters
    if not schema:
        return None

    required = schema.get("required", [])
    properties = schema.get("properties", {})
    for req_field in required:
        if req_field not in arguments:
            return f"invalid_args:missing_required:{req_field}"

    type_map = {"string": str, "number": (int, float), "integer": int, "boolean": bool}
    for key, value in arguments.items():
        if key not in properties:
            continue
        expected_type = properties[key].get("type")
        if expected_type in type_map and not isinstance(value, type_map[expected_type]):
            return f"invalid_args:type_mismatch:{key}:expected_{expected_type}"

    return None


def filter_known_args(tool_info: MCPToolInfo, arguments: dict) -> dict:
    """过滤 schema 未声明的参数。"""
    schema = tool_info.parameters
    if not schema:
        return arguments
    properties = schema.get("properties", {})
    if not properties:
        return arguments
    return {k: v for k, v in arguments.items() if k in properties}


def serialize_result(result: Any) -> str:
    """序列化 MCP Server 返回结果。"""
    if isinstance(result, dict):
        content = result.get("content", [])
        if isinstance(content, list) and content:
            texts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    texts.append(item.get("text", ""))
                elif isinstance(item, dict):
                    texts.append(json.dumps(item, ensure_ascii=False))
            if texts:
                return "\n".join(texts)
        return json.dumps(result, ensure_ascii=False)

    if isinstance(result, (list, tuple)):
        return json.dumps(result, ensure_ascii=False)

    return str(result)
