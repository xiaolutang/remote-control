"""Agent conversation helper tests for history truncation and reconstruction."""

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from app.api.agent_conversation_helpers import (
    _build_agent_message_history_from_events,
    _estimate_event_tokens,
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
