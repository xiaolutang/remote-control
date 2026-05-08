"""
Client 连接管理 — ClientConnection 类 + 连接注册/查询
"""
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from app.infra.crypto import encrypt_message, should_encrypt

logger = logging.getLogger(__name__)

# 活跃的 Client 连接
active_clients: dict[str, list] = {}  # channel_key -> [ClientConnection,...]

# 最大客户端数量
MAX_CLIENTS_PER_SESSION = int(os.getenv("MAX_CLIENTS_PER_SESSION", "100"))


class ClientConnection:
    """Client 连接状态"""

    def __init__(
        self,
        session_id: str,
        websocket,
        view_type: str = "mobile",
        terminal_id: Optional[str] = None,
        device_id: Optional[str] = None,
    ):
        self.session_id = session_id
        self.terminal_id = terminal_id
        self.device_id = device_id
        self.websocket = websocket
        self.view_type = view_type  # mobile 或 desktop
        self.connected_at = datetime.now(timezone.utc)
        self.aes_key: Optional[bytes] = None  # 该连接的 AES 会话密钥

    async def send(self, message: dict):
        """发送消息到 Client（自动加密）"""
        try:
            msg_type = message.get("type", "")
            if self.aes_key and should_encrypt(msg_type):
                message = encrypt_message(self.aes_key, message)
            await self.websocket.send_json(message)
        except Exception:
            logger.warning(
                "Failed to send message to client: session_id=%s terminal_id=%s",
                self.session_id, self.terminal_id,
                exc_info=True,
            )


def _channel_key(session_id: str, terminal_id: Optional[str] = None) -> str:
    return f"{session_id}:{terminal_id}" if terminal_id else session_id


def _matches_session(channel_key: str, session_id: str) -> bool:
    """判断 channel_key 是否属于指定 session（session_id 或 session_id:xxx）"""
    return channel_key == session_id or channel_key.startswith(f"{session_id}:")


def _unregister_client(channel_key: str, client_conn: ClientConnection):
    """从 active_clients 中移除 client，列表为空时删除 key"""
    if channel_key not in active_clients:
        return
    try:
        active_clients[channel_key].remove(client_conn)
    except ValueError:
        pass
    if not active_clients[channel_key]:
        del active_clients[channel_key]


def _find_client_by_view_type(
    channel_key: str,
    view_type: str,
    exclude_conn: Optional[ClientConnection] = None,
) -> Optional[ClientConnection]:
    """在同一 channel 内查找同 view_type 的已有 Client。"""
    for client in active_clients.get(channel_key, []):
        if client.view_type == view_type and client is not exclude_conn:
            return client
    return None


def get_client_count(session_id: str, terminal_id: Optional[str] = None) -> int:
    """
    获取连接的 Client 数量

    Args:
        session_id: 会话 ID

    Returns:
        Client 数量
    """
    return len(active_clients.get(_channel_key(session_id, terminal_id), []))
