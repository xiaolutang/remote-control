import json
import os
import sys
import types
from unittest.mock import patch

import pytest

from app.assistant_planner import (
    AssistantPlannerRateLimited,
    AssistantPlannerUnavailable,
    plan_with_service_llm,
)


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


class _FakeChatCompletions:
    def __init__(self, *, response_content: str | None = None, error: Exception | None = None):
        self.response_content = response_content
        self.error = error
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return _FakeResponse(self.response_content or "{}")


class _FakeAsyncOpenAI:
    last_instance = None
    next_completion = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.chat = types.SimpleNamespace(completions=self.__class__.next_completion)
        self.closed = False
        self.__class__.last_instance = self

    async def close(self):
        self.closed = True


class _FakeRateLimitError(Exception):
    status_code = 429
    retry_after = 17


@pytest.mark.asyncio
async def test_plan_with_service_llm_uses_openai_compatible_direct_mode():
    completion = _FakeChatCompletions(
        response_content=json.dumps(
            {
                "assistant_messages": [
                    {"type": "assistant", "text": "已定位 remote-control 项目。"}
                ],
                "trace": [
                    {
                        "stage": "planner",
                        "title": "调用 LLM",
                        "status": "completed",
                        "summary": "已生成命令序列",
                    }
                ],
                "command_sequence": {
                    "summary": "进入 remote-control 并启动 Claude",
                    "provider": "service_llm",
                    "source": "intent",
                    "need_confirm": True,
                    "steps": [
                        {
                            "id": "step_1",
                            "label": "进入项目目录",
                            "command": "cd /Users/demo/project/remote-control",
                        },
                        {
                            "id": "step_2",
                            "label": "启动 Claude",
                            "command": "claude",
                        },
                    ],
                },
                "fallback_used": False,
                "fallback_reason": None,
                "evaluation_context": {
                    "matched_candidate_id": "remote-control",
                    "matched_cwd": "/Users/demo/project/remote-control",
                    "matched_label": "remote-control",
                    "memory_hits": 1,
                    "tool_calls": 2,
                },
            }
        )
    )
    _FakeAsyncOpenAI.next_completion = completion
    fake_openai = types.SimpleNamespace(AsyncOpenAI=_FakeAsyncOpenAI)

    with patch.dict(
        os.environ,
        {
            "ASSISTANT_LLM_API_KEY": "test-key",
            "ASSISTANT_LLM_BASE_URL": "https://example.test/v1",
            "ASSISTANT_LLM_MODEL": "gpt-4.1-mini",
            "ASSISTANT_LLM_PLANNER_URL": "",
        },
        clear=False,
    ):
        with patch.dict(sys.modules, {"openai": fake_openai}):
            result = await plan_with_service_llm(
                intent="进入 remote-control 修登录问题",
                device_id="mbp-01",
                project_context={
                    "candidate_projects": [
                        {
                            "candidate_id": "remote-control",
                            "label": "remote-control",
                            "cwd": "/Users/demo/project/remote-control",
                        }
                    ]
                },
                planner_memory={"successful_paths": []},
                planner_config={"provider": "claude_cli", "llm_enabled": True},
                conversation_id="conv-001",
                message_id="msg-001",
            )

    assert result["command_sequence"]["provider"] == "service_llm"
    assert result["command_sequence"]["steps"][0]["command"] == (
        "cd /Users/demo/project/remote-control"
    )
    assert _FakeAsyncOpenAI.last_instance is not None
    assert _FakeAsyncOpenAI.last_instance.kwargs["api_key"] == "test-key"
    assert _FakeAsyncOpenAI.last_instance.kwargs["base_url"] == "https://example.test/v1"
    assert _FakeAsyncOpenAI.last_instance.closed is True
    call = completion.calls[0]
    assert call["model"] == "gpt-4.1-mini"
    assert call["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_plan_with_service_llm_maps_direct_rate_limit():
    completion = _FakeChatCompletions(error=_FakeRateLimitError("rate limited"))
    _FakeAsyncOpenAI.next_completion = completion
    fake_openai = types.SimpleNamespace(AsyncOpenAI=_FakeAsyncOpenAI)

    with patch.dict(
        os.environ,
        {
            "ASSISTANT_LLM_API_KEY": "test-key",
            "ASSISTANT_LLM_PLANNER_URL": "",
        },
        clear=False,
    ):
        with patch.dict(sys.modules, {"openai": fake_openai}):
            with pytest.raises(AssistantPlannerRateLimited) as exc_info:
                await plan_with_service_llm(
                    intent="进入 remote-control",
                    device_id="mbp-01",
                    project_context={},
                    planner_memory={},
                    planner_config={"provider": "claude_cli", "llm_enabled": True},
                    conversation_id="conv-001",
                    message_id="msg-001",
                )

    assert exc_info.value.reason == "service_llm_rate_limited"
    assert exc_info.value.retry_after == 17


@pytest.mark.asyncio
async def test_plan_with_service_llm_requires_config_when_no_provider_available():
    with patch.dict(
        os.environ,
        {
            "ASSISTANT_LLM_API_KEY": "",
            "ASSISTANT_LLM_BASE_URL": "",
            "ASSISTANT_LLM_PLANNER_URL": "",
            "LLM_API_KEY": "",
            "LLM_BASE_URL": "",
            "OPENAI_API_KEY": "",
            "OPENAI_BASE_URL": "",
        },
        clear=False,
    ):
        with pytest.raises(AssistantPlannerUnavailable) as exc_info:
            await plan_with_service_llm(
                intent="进入 remote-control",
                device_id="mbp-01",
                project_context={},
                planner_memory={},
                planner_config={"provider": "claude_cli", "llm_enabled": True},
                conversation_id="conv-001",
                message_id="msg-001",
            )

    assert exc_info.value.reason == "service_llm_unavailable"
    assert "未配置" in exc_info.value.detail
