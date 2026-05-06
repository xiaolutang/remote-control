"""
session 子模块 — 规范化、验证与 terminal 辅助逻辑。
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status

from app.store.session_types import (
    SESSION_STATES,
    TERMINAL_STATES,
    DEFAULT_MAX_TERMINALS,
    MAX_TERMINAL_RECORDS,
    _default_device_state,
)


# ─── 状态规范化 ───

def _normalize_session_status(session_status: str) -> str:
    legacy_map = {
        "offline": "offline_expired",
    }
    return legacy_map.get(session_status, session_status if session_status in SESSION_STATES else "pending")


def _normalize_terminal_status(terminal_status: str) -> str:
    legacy_map = {
        "pending": "recovering",
        "attached": "live",
        "detached": "detached_recoverable",
        "closing": "detached_recoverable",
    }
    normalized = legacy_map.get(terminal_status, terminal_status)
    return normalized if normalized in TERMINAL_STATES else "recovering"


# ─── 验证 ───

def _validate_terminal_status(terminal_status: str) -> None:
    """验证 terminal 状态。"""
    if terminal_status not in TERMINAL_STATES and terminal_status not in {
        "pending",
        "attached",
        "detached",
        "closing",
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效的 terminal 状态: {terminal_status}",
        )


def _validate_session_status(session_status: str) -> None:
    if session_status not in SESSION_STATES and session_status != "offline":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效状态: {session_status}",
        )


def _validate_session_id(session_id: str) -> None:
    """验证 session_id 格式"""
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="session_id 不能为空",
        )

    if len(session_id) > 1024:  # 1KB
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="session_id 过长",
        )


# ─── session 数据规范化 ───

def _normalize_session_data(session_id: str, session_data: dict) -> dict:
    """兼容旧 session 结构，补齐 device 相关字段。

    返回 (normalized_dict, changed: bool) 元组。
    changed=True 表示 normalize 期间产生了实际差异，需要回写 Redis。
    """
    changed = False
    normalized = dict(session_data)

    # ── status ──
    normalized.setdefault("status", "pending")
    new_status = _normalize_session_status(normalized["status"])
    if normalized["status"] != new_status:
        normalized["status"] = new_status
        changed = True

    # ── scalar defaults ──
    for key, default in (("agent_online", False),):
        if key not in normalized:
            normalized[key] = default
            changed = True

    # ── views ──
    if "views" not in normalized:
        normalized["views"] = {"mobile": 0, "desktop": 0}
        changed = True

    # ── pty ──
    normalized.setdefault("pty", {"rows": 24, "cols": 80})
    normalized_terminal_pty = {
        "rows": max(1, int(normalized["pty"].get("rows", 24))),
        "cols": max(1, int(normalized["pty"].get("cols", 80))),
    }
    if normalized["pty"] != normalized_terminal_pty:
        normalized["pty"] = normalized_terminal_pty
        changed = True

    # ── terminals ──
    normalized.setdefault("terminals", [])
    normalized_terminals = []
    terminal_changed = False
    for terminal in normalized["terminals"]:
        terminal_copy = dict(terminal)
        new_t_status = _normalize_terminal_status(terminal_copy.get("status", "recovering"))
        if terminal_copy.get("status") != new_t_status:
            terminal_copy["status"] = new_t_status
            terminal_changed = True
        if "views" not in terminal_copy:
            terminal_copy["views"] = {"mobile": 0, "desktop": 0}
            terminal_changed = True
        owner_view = terminal_copy.get("geometry_owner_view")
        valid_owner = owner_view if owner_view in {"mobile", "desktop"} else None
        if terminal_copy.get("geometry_owner_view") != valid_owner:
            terminal_copy["geometry_owner_view"] = valid_owner
            terminal_changed = True
        new_epoch = max(0, int(terminal_copy.get("attach_epoch", 0) or 0))
        if terminal_copy.get("attach_epoch") != new_epoch:
            terminal_copy["attach_epoch"] = new_epoch
            terminal_changed = True
        new_rec_epoch = max(0, int(terminal_copy.get("recovery_epoch", 0) or 0))
        if terminal_copy.get("recovery_epoch") != new_rec_epoch:
            terminal_copy["recovery_epoch"] = new_rec_epoch
            terminal_changed = True
        new_pty = {
            "rows": max(
                1,
                int((terminal_copy.get("pty") or normalized_terminal_pty).get("rows", 24)),
            ),
            "cols": max(
                1,
                int((terminal_copy.get("pty") or normalized_terminal_pty).get("cols", 80)),
            ),
        }
        if terminal_copy.get("pty") != new_pty:
            terminal_copy["pty"] = new_pty
            terminal_changed = True
        normalized_terminals.append(terminal_copy)
    if terminal_changed:
        normalized["terminals"] = normalized_terminals
        changed = True

    # ── device ──
    device = dict(normalized.get("device") or {})
    defaults = _default_device_state(session_id)
    device_changed = False
    for key, value in defaults.items():
        if key not in device:
            device[key] = value
            device_changed = True
    if not device.get("max_terminals_configured", False) and device.get("max_terminals") != DEFAULT_MAX_TERMINALS:
        device["max_terminals"] = DEFAULT_MAX_TERMINALS
        device_changed = True
    if device_changed:
        normalized["device"] = device
        changed = True

    return normalized, changed


# ─── terminal 辅助 ───

def _active_terminal_count(terminals: list[dict]) -> int:
    """统计占用 terminal 名额的实例数。"""
    return sum(1 for terminal in terminals if terminal.get("status") != "closed")


def _terminal_updated_at(terminal: dict) -> str:
    return terminal.get("updated_at") or terminal.get("created_at") or ""


def _trim_terminal_records(terminals: list[dict], limit: int = MAX_TERMINAL_RECORDS) -> int:
    """只保留最近的少量 terminal 记录，优先保留未关闭终端。"""
    if len(terminals) <= limit:
        return 0

    active = sorted(
        [terminal for terminal in terminals if terminal.get("status") != "closed"],
        key=_terminal_updated_at,
        reverse=True,
    )
    closed = sorted(
        [terminal for terminal in terminals if terminal.get("status") == "closed"],
        key=_terminal_updated_at,
        reverse=True,
    )

    kept = active[:limit]
    if len(kept) < limit:
        kept.extend(closed[: limit - len(kept)])

    kept_ids = {terminal["terminal_id"] for terminal in kept}
    original_len = len(terminals)
    terminals[:] = [terminal for terminal in terminals if terminal["terminal_id"] in kept_ids]
    return original_len - len(terminals)


def _close_expired_detached_terminals(terminals: list[dict], now: Optional[datetime] = None) -> int:
    """关闭超出 grace period 的 detached terminal。"""
    current = now or datetime.now(timezone.utc)
    changed = 0

    for terminal in terminals:
        if _normalize_terminal_status(terminal.get("status", "recovering")) != "detached_recoverable":
            continue
        grace_expires_at = terminal.get("grace_expires_at")
        if not grace_expires_at:
            continue
        if current < datetime.fromisoformat(grace_expires_at):
            continue
        terminal["status"] = "closed"
        terminal["disconnect_reason"] = terminal.get("disconnect_reason") or "grace_expired"
        terminal["grace_expires_at"] = None
        terminal["updated_at"] = current.isoformat()
        changed += 1

    return changed


def _backfill_terminal_views(terminals: list[dict]) -> int:
    """兼容旧数据：补齐缺失 views 和无效 geometry_owner_view，不做状态推断。"""
    changed = 0

    for terminal in terminals:
        if "views" not in terminal:
            terminal["views"] = {"mobile": 0, "desktop": 0}
            changed += 1
        owner_view = terminal.get("geometry_owner_view")
        if owner_view not in {"mobile", "desktop", None}:
            terminal["geometry_owner_view"] = None
            changed += 1

    return changed


def _resolve_geometry_owner_view(
    terminal: dict,
    views: dict[str, int],
    *,
    preferred_owner_view: Optional[str] = None,
) -> Optional[str]:
    """为 shared terminal 选择唯一的几何 owner。"""
    total_views = views["mobile"] + views["desktop"]
    if total_views <= 0:
        return None

    current_owner_view = terminal.get("geometry_owner_view")
    if current_owner_view in {"mobile", "desktop"} and views.get(current_owner_view, 0) > 0:
        return current_owner_view

    if preferred_owner_view in {"mobile", "desktop"} and views.get(preferred_owner_view, 0) > 0:
        return preferred_owner_view

    if views["mobile"] > 0:
        return "mobile"
    if views["desktop"] > 0:
        return "desktop"
    return None


def _clear_terminal_attachment_state(terminal: dict) -> None:
    terminal["views"] = {"mobile": 0, "desktop": 0}
    terminal["geometry_owner_view"] = None


def _advance_attach_epoch(terminal: dict) -> int:
    terminal["attach_epoch"] = max(0, int(terminal.get("attach_epoch", 0) or 0)) + 1
    return terminal["attach_epoch"]


def _advance_recovery_epoch(terminal: dict) -> int:
    terminal["recovery_epoch"] = max(0, int(terminal.get("recovery_epoch", 0) or 0)) + 1
    return terminal["recovery_epoch"]


def _reconcile_terminals(terminals: list[dict]) -> int:
    """执行 reconcile + close expired + trim 的标准组合。"""
    changed = _backfill_terminal_views(terminals)
    changed += _close_expired_detached_terminals(terminals)
    changed += _trim_terminal_records(terminals)
    return changed


def is_terminal_recoverable(terminal: dict, now: Optional[datetime] = None) -> bool:
    """terminal 是否仍处于可恢复窗口。"""
    if _normalize_terminal_status(terminal.get("status", "recovering")) != "detached_recoverable":
        return False
    grace_expires_at = terminal.get("grace_expires_at")
    if not grace_expires_at:
        return False
    current = now or datetime.now(timezone.utc)
    return current < datetime.fromisoformat(grace_expires_at)
