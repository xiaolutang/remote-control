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


# ---- WebSocket 关闭码常量 ----
# 集中定义，避免散落在各 ws 模块中。
# 4xxx 为应用自定义码。

class WSCloseCode:
    """WebSocket 关闭码常量。"""
    # 协议标准码
    NORMAL = 1000        # 正常关闭
    ABNORMAL = 1006      # 无 close frame（网络中断）
    POLICY_VIOLATION = 1008  # 心跳超时

    # 应用自定义码 — 认证/协议
    AUTH_TIMEOUT = 4002      # 认证超时
    PROTOCOL_ERROR = 4003    # 协议错误（缺少加密/Token 缺字段）
    INVALID_MESSAGE = 4004   # 无效消息（JSON 错误/非 auth 消息）

    # 应用自定义码 — 业务
    SESSION_CONFLICT = 4009  # Session/terminal 冲突
    DEVICE_REPLACED = 4011   # 设备被新连接替换

    # 应用自定义码 — 客户端错误
    INVALID_VIEW = 4400      # 无效 view_type

    # 应用自定义码 — 服务端错误
    INTERNAL_ERROR = 4500    # 服务端内部错误
    NETWORK_LOST = 4501      # Agent 网络丢失
    TOO_MANY_CLIENTS = 4503  # 客户端连接数超限
