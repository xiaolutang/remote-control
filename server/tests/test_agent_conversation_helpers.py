"""Agent conversation helper tests for history truncation and reconstruction."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from app.api.agent_conversation_helpers import (
    _build_agent_conversation_projection,
    _build_agent_message_history_from_events,
    _cache_key,
    _estimate_event_tokens,
    _invalidate_projection_cache,
    _projection_cache,
    _PROJECTION_CACHE_TTL,
    _truncate_events_by_token_budget,
)


def _event(event_type: str, payload: dict, role: str = "assistant") -> dict:
    return {
        "event_type": event_type,
        "role": role,
        "payload": payload,
    }


def test_truncate_events_by_token_budget_keeps_all_events_under_budget():
    events = [
        _event("user_intent", {"text": "open project"}, role="user"),
        _event("tool_step", {"tool_name": "execute_command", "status": "running", "command": "pwd"}),
        _event("result", {"summary": "done"}),
    ]

    truncated = _truncate_events_by_token_budget(events, budget=10_000)

    assert truncated == events


def test_truncate_events_by_token_budget_drops_oldest_events_first():
    events = [
        _event("user_intent", {"text": "a" * 120}, role="user"),
        _event("tool_step", {"tool_name": "execute_command", "status": "running", "command": "b" * 120}),
        _event("result", {"summary": "c" * 120}),
    ]

    budget = _estimate_event_tokens(events[1]) + _estimate_event_tokens(events[2])
    truncated = _truncate_events_by_token_budget(events, budget=budget)

    assert len(truncated) == 2
    assert truncated[0]["event_type"] == "tool_step"
    assert truncated[1]["event_type"] == "result"


def test_truncate_events_by_token_budget_keeps_latest_event_when_single_event_exceeds_budget():
    events = [_event("tool_step", {"tool_name": "execute_command", "status": "done", "result_summary": "x" * 800})]

    truncated = _truncate_events_by_token_budget(events, budget=10)

    assert truncated == events


def test_truncated_events_can_build_valid_message_history():
    events = [
        _event("user_intent", {"text": "old context"}, role="user"),
        _event("question", {"question": "Which project?"}),
        _event("answer", {"text": "remote-control"}, role="user"),
        _event(
            "tool_step",
            {"tool_name": "execute_command", "status": "running", "command": "git status"},
        ),
        _event(
            "tool_step",
            {"tool_name": "execute_command", "status": "done", "result_summary": "working tree clean"},
        ),
        _event("result", {"summary": "checked repository state"}),
    ]

    truncated = _truncate_events_by_token_budget(events, budget=500)
    history = _build_agent_message_history_from_events(truncated)

    assert len(history) >= 4
    assert isinstance(history[0], ModelRequest)
    assert isinstance(history[0].parts[0], UserPromptPart)
    assert isinstance(history[1], ModelResponse)
    assert isinstance(history[1].parts[0], ToolCallPart)
    assert isinstance(history[2], ModelRequest)
    assert isinstance(history[2].parts[0], ToolReturnPart)
    assert isinstance(history[-1], ModelResponse)
    assert isinstance(history[-1].parts[0], TextPart)


# ---------------------------------------------------------------------------
# B060: 全量投影 TTL 缓存测试
# ---------------------------------------------------------------------------

_UID = "user1"
_DID = "dev1"
_TID = "term1"


def _mock_conversation(**overrides):
    """构建模拟的 conversation 记录。"""
    base = {
        "conversation_id": "conv-1",
        "status": "active",
        "truncation_epoch": 0,
    }
    base.update(overrides)
    return base


def _mock_event(event_index: int, event_type: str = "user_intent", **payload_overrides):
    """构建模拟的 conversation event。"""
    return {
        "event_index": event_index,
        "event_id": f"evt-{event_index}",
        "event_type": event_type,
        "type": event_type,
        "role": "user",
        "payload": {"text": f"event {event_index}", **payload_overrides},
        "created_at": "2026-01-01T00:00:00",
    }


@patch("app.api.agent_conversation_helpers._deps")
@pytest.mark.asyncio
async def test_full_projection_hits_cache(mock_deps):
    """无 after_index 的全量投影在 TTL 内命中缓存，不重复查询 SQLite。"""
    mock_deps.get_agent_conversation = AsyncMock(return_value=_mock_conversation())
    mock_deps.list_agent_conversation_events = AsyncMock(return_value=[_mock_event(0)])
    mock_session_mgr = MagicMock()
    mock_session_mgr.get_active_terminal_session.return_value = None
    mock_deps.get_agent_session_manager.return_value = mock_session_mgr

    # 第一次调用 — 执行实际查询并写入缓存
    proj1 = await _build_agent_conversation_projection(
        user_id=_UID, device_id=_DID, terminal_id=_TID,
    )
    assert mock_deps.get_agent_conversation.call_count == 1
    assert proj1.conversation_id == "conv-1"
    assert len(proj1.events) == 1

    # 第二次调用 — 命中缓存，不触发 SQLite
    proj2 = await _build_agent_conversation_projection(
        user_id=_UID, device_id=_DID, terminal_id=_TID,
    )
    assert mock_deps.get_agent_conversation.call_count == 1  # 未增加
    assert proj2.conversation_id == "conv-1"
    assert len(proj2.events) == 1

    # 返回的是 deep copy，修改互不影响
    proj2.events[0].payload["extra"] = "modified"
    assert "extra" not in proj1.events[0].payload


@patch("app.api.agent_conversation_helpers._deps")
@pytest.mark.asyncio
async def test_full_projection_cache_expires_after_ttl(mock_deps):
    """缓存 TTL（500ms）过期后，重新执行 SQLite 查询。"""
    mock_deps.get_agent_conversation = AsyncMock(return_value=_mock_conversation())
    mock_deps.list_agent_conversation_events = AsyncMock(return_value=[_mock_event(0)])
    mock_session_mgr = MagicMock()
    mock_session_mgr.get_active_terminal_session.return_value = None
    mock_deps.get_agent_session_manager.return_value = mock_session_mgr

    # 第一次调用写入缓存
    await _build_agent_conversation_projection(
        user_id=_UID, device_id=_DID, terminal_id=_TID,
    )
    assert mock_deps.get_agent_conversation.call_count == 1

    # 模拟 TTL 过期：直接修改缓存中的时间戳
    ck = _cache_key(_UID, _DID, _TID)
    assert ck in _projection_cache
    cached_at, cached_proj = _projection_cache[ck]
    _projection_cache[ck] = (cached_at - _PROJECTION_CACHE_TTL - 0.1, cached_proj)

    # 过期后再次调用，触发新的 SQLite 查询
    await _build_agent_conversation_projection(
        user_id=_UID, device_id=_DID, terminal_id=_TID,
    )
    assert mock_deps.get_agent_conversation.call_count == 2


@patch("app.api.agent_conversation_helpers._deps")
@pytest.mark.asyncio
async def test_incremental_projection_skips_cache(mock_deps):
    """有 after_index 的增量投影完全跳过缓存，每次都查询 SQLite。"""
    mock_deps.get_agent_conversation = AsyncMock(return_value=_mock_conversation())
    mock_deps.list_agent_conversation_events = AsyncMock(return_value=[_mock_event(5)])
    mock_session_mgr = MagicMock()
    mock_session_mgr.get_active_terminal_session.return_value = None
    mock_deps.get_agent_session_manager.return_value = mock_session_mgr

    for _ in range(3):
        await _build_agent_conversation_projection(
            user_id=_UID, device_id=_DID, terminal_id=_TID, after_index=4,
        )

    # 每次都查询 SQLite，不命中缓存
    assert mock_deps.get_agent_conversation.call_count == 3
    # 增量查询不写入缓存
    assert _cache_key(_UID, _DID, _TID) not in _projection_cache


@patch("app.api.agent_conversation_helpers._deps")
@pytest.mark.asyncio
async def test_invalidate_cache_on_new_event(mock_deps):
    """_invalidate_projection_cache 立即清除对应 conversation 的缓存。"""
    mock_deps.get_agent_conversation = AsyncMock(return_value=_mock_conversation())
    mock_deps.list_agent_conversation_events = AsyncMock(return_value=[_mock_event(0)])
    mock_session_mgr = MagicMock()
    mock_session_mgr.get_active_terminal_session.return_value = None
    mock_deps.get_agent_session_manager.return_value = mock_session_mgr

    # 写入缓存
    await _build_agent_conversation_projection(
        user_id=_UID, device_id=_DID, terminal_id=_TID,
    )
    assert mock_deps.get_agent_conversation.call_count == 1

    # 模拟新事件到达，失效缓存
    _invalidate_projection_cache(_UID, _DID, _TID)
    assert _cache_key(_UID, _DID, _TID) not in _projection_cache

    # 更新 mock 返回新事件
    mock_deps.list_agent_conversation_events = AsyncMock(
        return_value=[_mock_event(0), _mock_event(1)],
    )

    # 失效后重新查询
    proj = await _build_agent_conversation_projection(
        user_id=_UID, device_id=_DID, terminal_id=_TID,
    )
    assert mock_deps.get_agent_conversation.call_count == 2
    assert len(proj.events) == 2


@patch("app.api.agent_conversation_helpers._deps")
@pytest.mark.asyncio
async def test_cache_key_isolation(mock_deps):
    """不同 conversation_id 的缓存互不干扰。"""
    call_count = 0
    conversations = {
        (_UID, _DID, _TID): _mock_conversation(conversation_id="conv-1"),
        ("user2", "dev2", "term2"): _mock_conversation(conversation_id="conv-2"),
    }

    async def _get_conv(uid, did, tid):
        nonlocal call_count
        call_count += 1
        return conversations.get((uid, did, tid))

    mock_deps.get_agent_conversation = AsyncMock(side_effect=_get_conv)
    mock_deps.list_agent_conversation_events = AsyncMock(return_value=[_mock_event(0)])
    mock_session_mgr = MagicMock()
    mock_session_mgr.get_active_terminal_session.return_value = None
    mock_deps.get_agent_session_manager.return_value = mock_session_mgr

    # user1:dev1:term1 写入缓存
    await _build_agent_conversation_projection(
        user_id=_UID, device_id=_DID, terminal_id=_TID,
    )

    # user2:dev2:term2 不命中 user1 的缓存
    await _build_agent_conversation_projection(
        user_id="user2", device_id="dev2", terminal_id="term2",
    )

    # 两次不同的 conversation 都调用了 get_agent_conversation
    assert call_count == 2


@patch("app.api.agent_conversation_helpers._deps")
@pytest.mark.asyncio
async def test_empty_conversation_not_cached(mock_deps):
    """conversation 不存在（None）时返回 empty 状态，不写入缓存。"""
    mock_deps.get_agent_conversation = AsyncMock(return_value=None)

    proj = await _build_agent_conversation_projection(
        user_id=_UID, device_id=_DID, terminal_id=_TID,
    )
    assert proj.status == "empty"
    assert proj.conversation_id is None
    assert _cache_key(_UID, _DID, _TID) not in _projection_cache
