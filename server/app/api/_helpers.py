"""
共享辅助函数 — device_online / model_dump / json_loads 等。
"""
import json
import logging
from typing import Any, Optional

from app.api import _deps

logger = logging.getLogger(__name__)


def device_online(session: dict) -> bool:
    session_id = session.get("session_id", "")
    if session_id:
        return _deps.is_agent_connected(session_id)
    return bool(session.get("agent_online", False))


def model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value


def json_loads(value: Any, default: Any) -> Any:
    if not value:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default
