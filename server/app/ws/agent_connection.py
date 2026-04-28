"""
Agent 连接管理 — AgentConnection 类 + 连接注册/查询 + 心跳配置
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.infra.crypto import encrypt_message, should_encrypt

# 心跳配置
HEARTBEAT_INTERVAL = 30  # 秒
HEARTBEAT_TIMEOUT = 60  # 秒


class AgentConnection:
    """Agent 连接状态"""

    def __init__(self, session_id: str, websocket, owner: str = ""):
        self.session_id = session_id
        self.websocket = websocket
        self.owner = owner
        self.last_heartbeat = datetime.now(timezone.utc)
        self.connected_at = datetime.now(timezone.utc)
        self.aes_key: bytes | None = None  # 该连接的 AES 会话密钥
        # B093: Agent 上报的工具目录快照
        self.tool_catalog: list[dict] = []  # [{"name", "kind", "description", "parameters", ...}]

    async def send(self, message: dict):
        """发送消息到 Agent（自动加密）"""
        msg_type = message.get("type", "")
        if self.aes_key and should_encrypt(msg_type):
            message = encrypt_message(self.aes_key, message)
        await self.websocket.send_json(message)

    def update_heartbeat(self):
        """更新心跳时间"""
        self.last_heartbeat = datetime.now(timezone.utc)

    def is_alive(self) -> bool:
        """检查连接是否存活"""
        elapsed = (datetime.now(timezone.utc) - self.last_heartbeat).total_seconds()
        return elapsed < HEARTBEAT_TIMEOUT


# 活跃的 Agent 连接
active_agents: dict[str, AgentConnection] = {}  # session_id -> connection


def get_agent_connection(session_id: str) -> Optional[AgentConnection]:
    """
    获取 Agent 连接

    Args:
        session_id: 会话 ID

    Returns:
        AgentConnection 对象或 None
    """
    return active_agents.get(session_id)


def is_agent_connected(session_id: str) -> bool:
    """
    检查 Agent 是否连接

    Args:
        session_id: 会话 ID

    Returns:
        是否已连接
    """
    return session_id in active_agents
