"""
三端共享的 WS 消息类型常量定义。

server / agent / client 三端必须保持同步。
新增消息类型时，必须三端同时更新。

PLAINTEXT_MSG_TYPES: 不加密传输的消息类型集合（协议握手/心跳）。
不在 PLAINTEXT_MSG_TYPES 中的消息必须加密传输。
"""
from enum import StrEnum


class MessageType(StrEnum):
    """WebSocket 消息类型枚举。"""

    # ---- 协议握手 / 心跳（PLAINTEXT） ----
    AUTH = "auth"
    CONNECTED = "connected"
    PING = "ping"
    PONG = "pong"

    # ---- 终端数据 ----
    DATA = "data"
    OUTPUT = "output"

    # ---- 终端控制 ----
    RESIZE = "resize"
    CREATE_TERMINAL = "create_terminal"
    CLOSE_TERMINAL = "close_terminal"
    TERMINAL_CREATED = "terminal_created"
    TERMINAL_CLOSED = "terminal_closed"
    TERMINALS_CHANGED = "terminals_changed"

    # ---- 快照 ----
    SNAPSHOT = "snapshot"
    SNAPSHOT_START = "snapshot_start"
    SNAPSHOT_CHUNK = "snapshot_chunk"
    SNAPSHOT_COMPLETE = "snapshot_complete"
    SNAPSHOT_REQUEST = "snapshot_request"
    SNAPSHOT_DATA = "snapshot_data"

    # ---- 执行命令 ----
    EXECUTE_COMMAND = "execute_command"
    EXECUTE_COMMAND_RESULT = "execute_command_result"

    # ---- 知识库 / 工具 ----
    LOOKUP_KNOWLEDGE = "lookup_knowledge"
    LOOKUP_KNOWLEDGE_RESULT = "lookup_knowledge_result"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOOL_CATALOG_SNAPSHOT = "tool_catalog_snapshot"

    # ---- Agent 元数据 ----
    AGENT_METADATA = "agent_metadata"

    # ---- 在线状态 ----
    PRESENCE = "presence"

    # ---- 连接管理 ----
    DEVICE_KICKED = "device_kicked"
    ERROR = "error"


# 不加密的控制消息类型（协议握手/心跳）
PLAINTEXT_MSG_TYPES: frozenset[str] = frozenset({
    MessageType.AUTH,
    MessageType.CONNECTED,
    MessageType.PING,
    MessageType.PONG,
})
