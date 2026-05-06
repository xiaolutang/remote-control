"""
Client Snapshot 管理 — 终端快照请求与发送
"""
import base64
import logging
from datetime import datetime, timezone

from app.infra.message_types import MessageType
from app.store.session import get_session_terminal, get_terminal_output_history
from app.ws.agent_request import request_agent_terminal_snapshot

logger = logging.getLogger(__name__)


async def _send_terminal_snapshot(websocket, session_id: str, terminal_id: str) -> None:
    terminal = await get_session_terminal(session_id, terminal_id)
    attach_epoch = int((terminal or {}).get("attach_epoch", 0) or 0)
    recovery_epoch = int((terminal or {}).get("recovery_epoch", 0) or 0)

    await websocket.send_json({
        "type": MessageType.SNAPSHOT_START,
        "terminal_id": terminal_id,
        "attach_epoch": attach_epoch,
        "recovery_epoch": recovery_epoch,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    snapshot_data = await request_agent_terminal_snapshot(session_id, terminal_id)
    if snapshot_data:
        await websocket.send_json({
            "type": MessageType.SNAPSHOT_CHUNK,
            "terminal_id": terminal_id,
            "attach_epoch": attach_epoch,
            "recovery_epoch": recovery_epoch,
            "payload": snapshot_data["payload"],
            "pty": snapshot_data.get("pty"),
            "active_buffer": snapshot_data.get("active_buffer", "main"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    else:
        # history 只作为诊断级降级兜底，不再是主恢复源
        records = await get_terminal_output_history(session_id, terminal_id, limit=2000)
        chunk = ""
        max_chunk_size = 32 * 1024
        for record in records:
            data = record.get("data", "")
            if not data:
                continue
            if len(chunk) + len(data) > max_chunk_size and chunk:
                await websocket.send_json({
                    "type": MessageType.SNAPSHOT_CHUNK,
                    "terminal_id": terminal_id,
                    "attach_epoch": attach_epoch,
                    "recovery_epoch": recovery_epoch,
                    "payload": base64.b64encode(chunk.encode("utf-8")).decode("utf-8"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                chunk = ""
            chunk += data

        if chunk:
            await websocket.send_json({
                "type": MessageType.SNAPSHOT_CHUNK,
                "terminal_id": terminal_id,
                "attach_epoch": attach_epoch,
                "recovery_epoch": recovery_epoch,
                "payload": base64.b64encode(chunk.encode("utf-8")).decode("utf-8"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
    await websocket.send_json({
        "type": MessageType.SNAPSHOT_COMPLETE,
        "terminal_id": terminal_id,
        "attach_epoch": attach_epoch,
        "recovery_epoch": recovery_epoch,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
