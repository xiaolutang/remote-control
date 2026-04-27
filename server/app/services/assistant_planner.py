"""
聊天式智能终端助手的服务端 planner。

当前实现提供两种 provider 形态：
1. 直连 OpenAI-compatible LLM（推荐，和日知项目一致）
2. 代理到外部 planner URL（兼容旧接法）
"""
import asyncio
import json
import os
from typing import Any, Dict, List, Optional

from app.infra.http_client import get_shared_http_client


class AssistantPlannerError(Exception):
    """服务端 planner 统一异常基类。"""

    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


class AssistantPlannerUnavailable(AssistantPlannerError):
    pass


class AssistantPlannerTimeout(AssistantPlannerError):
    pass


class AssistantPlannerRateLimited(AssistantPlannerError):
    def __init__(self, reason: str, detail: str, retry_after: int = 60):
        super().__init__(reason, detail)
        self.retry_after = retry_after


def planner_timeout_ms() -> int:
    return max(1000, int(os.environ.get("ASSISTANT_PLAN_PROVIDER_TIMEOUT_MS", "12000")))


def planner_budget_blocked() -> bool:
    return os.environ.get("ASSISTANT_PLAN_BUDGET_BLOCKED", "0").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def planner_budget_retry_after() -> int:
    return max(1, int(os.environ.get("ASSISTANT_PLAN_BUDGET_RETRY_AFTER", "3600")))


def planner_endpoint() -> str:
    return os.environ.get("LLM_PLANNER_URL", "").strip()


def planner_api_key() -> str:
    return (
        os.environ.get("ASSISTANT_LLM_API_KEY")
        or os.environ.get("LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    ).strip()


def planner_base_url() -> str:
    return os.environ.get("LLM_BASE_URL", "").strip()


def planner_model() -> str:
    return os.environ.get("LLM_MODEL", "glm-5.1").strip()


def _extract_json_block(raw: Any) -> Optional[str]:
    content = str(raw or "").strip()
    if not content:
        return None
    if content.startswith("{") and content.endswith("}"):
        return content
    fenced_start = content.find("```")
    if fenced_start >= 0:
        first_brace = content.find("{", fenced_start)
        last_brace = content.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            return content[first_brace : last_brace + 1]
    start = content.find("{")
    end = content.rfind("}")
    if start >= 0 and end > start:
        return content[start : end + 1]
    return None


def _is_dangerous_command(command: str) -> bool:
    normalized = command.lower()
    blocked_patterns = [
        "rm -rf /",
        "sudo ",
        "shutdown",
        "reboot",
        "mkfs",
        "dd if=",
        ":(){",
    ]
    return any(pattern in normalized for pattern in blocked_patterns)


def _normalize_plan_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    command_sequence = data.get("command_sequence") or data.get("sequence")
    if not isinstance(command_sequence, dict):
        raise AssistantPlannerUnavailable(
            "service_llm_invalid",
            "planner 返回缺少 command_sequence",
        )

    steps = command_sequence.get("steps")
    if not isinstance(steps, list) or not steps:
        raise AssistantPlannerUnavailable(
            "service_llm_invalid",
            "planner 返回的命令步骤为空",
        )

    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict) or not str(step.get("command", "")).strip():
            raise AssistantPlannerUnavailable(
                "service_llm_invalid",
                f"planner 返回第 {index} 步命令非法",
            )
        if _is_dangerous_command(str(step.get("command", "")).strip()):
            raise AssistantPlannerUnavailable(
                "service_llm_invalid",
                f"planner 返回第 {index} 步命令存在风险",
            )

    command_sequence.setdefault("provider", "service_llm")
    command_sequence.setdefault("source", "intent")
    command_sequence.setdefault("need_confirm", True)
    data["assistant_messages"] = data.get("assistant_messages") or []
    data["trace"] = data.get("trace") or []
    data["command_sequence"] = command_sequence
    data["fallback_used"] = bool(data.get("fallback_used", False))
    data["fallback_reason"] = data.get("fallback_reason")
    data["evaluation_context"] = data.get("evaluation_context") or {}
    return data


def _build_direct_messages(
    *,
    intent: str,
    device_id: str,
    project_context: Dict[str, Any],
    planner_memory: Dict[str, List[Dict[str, Any]]],
    planner_config: Dict[str, Any],
    conversation_id: str,
    message_id: str,
) -> List[Dict[str, str]]:
    system_prompt = """
你是一个受约束的终端命令规划器，只能输出 JSON 对象，不能输出 markdown。

目标：
- 根据用户意图、设备上下文、候选项目、历史 memory，生成一组可在同一个 shell 会话中顺序执行的命令
- 当前产品主要进入 Claude，若用户意图是进入项目继续编码/排查，最后一步优先使用 claude
- 你的输出会直接给用户确认，因此必须保守、明确、可解释

安全约束：
- 不要输出危险命令，不要 sudo，不要删除文件，不要重启/关机，不要格式化磁盘
- 不要联网下载安装依赖
- 路径只能来自已有候选项目、已知终端 cwd、用户显式输入的路径，或通过 pwd/ls/find/cd 这类安全命令逐步确认
- 如果不能确定项目路径，允许先输出保守的探测命令，并把 need_confirm 设为 true

输出 schema：
{
  "assistant_messages": [
    {"type": "assistant", "text": "string"}
  ],
  "trace": [
    {"stage": "context|memory|planner", "title": "string", "status": "completed|fallback|warning", "summary": "string"}
  ],
  "command_sequence": {
    "summary": "string",
    "provider": "service_llm",
    "source": "intent",
    "need_confirm": true,
    "steps": [
      {"id": "step_1", "label": "string", "command": "single shell command"}
    ]
  },
  "fallback_used": false,
  "fallback_reason": null,
  "evaluation_context": {
    "matched_candidate_id": "string|null",
    "matched_cwd": "string|null",
    "matched_label": "string|null",
    "memory_hits": 0,
    "tool_calls": 1
  }
}
""".strip()
    user_payload = {
        "intent": intent,
        "device_id": device_id,
        "conversation_id": conversation_id,
        "message_id": message_id,
        "project_context": project_context,
        "planner_memory": planner_memory,
        "planner_config": planner_config,
    }
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": json.dumps(user_payload, ensure_ascii=False),
        },
    ]


async def _plan_with_openai_compatible(
    *,
    intent: str,
    device_id: str,
    project_context: Dict[str, Any],
    planner_memory: Dict[str, List[Dict[str, Any]]],
    planner_config: Dict[str, Any],
    conversation_id: str,
    message_id: str,
) -> Dict[str, Any]:
    api_key = planner_api_key()
    if not api_key:
        raise AssistantPlannerUnavailable(
            "service_llm_unavailable",
            "服务端 LLM API Key 未配置",
        )

    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise AssistantPlannerUnavailable(
            "service_llm_unavailable",
            "服务端缺少 openai 依赖，无法直连 LLM",
        ) from exc

    timeout_seconds = planner_timeout_ms() / 1000.0
    client_kwargs: Dict[str, Any] = {
        "api_key": api_key,
        "timeout": timeout_seconds,
    }
    base_url = planner_base_url()
    if base_url:
        client_kwargs["base_url"] = base_url

    client = AsyncOpenAI(**client_kwargs)
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=planner_model(),
                messages=_build_direct_messages(
                    intent=intent,
                    device_id=device_id,
                    project_context=project_context,
                    planner_memory=planner_memory,
                    planner_config=planner_config,
                    conversation_id=conversation_id,
                    message_id=message_id,
                ),
                response_format={"type": "json_object"},
            ),
            timeout=timeout_seconds + 0.5,
        )
    except asyncio.TimeoutError as exc:
        raise AssistantPlannerTimeout(
            "service_llm_timeout",
            "服务端 LLM planner 调用超时",
        ) from exc
    except Exception as exc:
        exc_name = exc.__class__.__name__
        status_code = getattr(exc, "status_code", None)
        if exc_name == "RateLimitError" or status_code == 429:
            retry_after = int(getattr(exc, "retry_after", 60) or 60)
            raise AssistantPlannerRateLimited(
                "service_llm_rate_limited",
                "服务端 LLM planner 触发限流",
                retry_after=retry_after,
            ) from exc
        if exc_name in {"APITimeoutError"}:
            raise AssistantPlannerTimeout(
                "service_llm_timeout",
                "服务端 LLM planner 调用超时",
            ) from exc
        if status_code in {402, 403}:
            raise AssistantPlannerRateLimited(
                "service_llm_budget_blocked",
                "服务端 LLM planner 预算或配额受限",
                retry_after=planner_budget_retry_after(),
            ) from exc
        raise AssistantPlannerUnavailable(
            "service_llm_unavailable",
            f"服务端 LLM planner 请求失败: {exc}",
        ) from exc
    finally:
        close_method = getattr(client, "close", None)
        if close_method is not None:
            await close_method()

    try:
        raw_content = response.choices[0].message.content
    except Exception as exc:
        raise AssistantPlannerUnavailable(
            "service_llm_invalid",
            "服务端 LLM planner 返回结构非法",
        ) from exc

    content = _extract_json_block(raw_content)
    if content is None:
        raise AssistantPlannerUnavailable(
            "service_llm_invalid",
            "服务端 LLM planner 未返回 JSON",
        )

    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise AssistantPlannerUnavailable(
            "service_llm_invalid",
            "服务端 LLM planner 返回 JSON 解析失败",
        ) from exc
    if not isinstance(payload, dict):
        raise AssistantPlannerUnavailable(
            "service_llm_invalid",
            "服务端 LLM planner 返回非法 JSON 结构",
        )
    return _normalize_plan_payload(payload)


async def _plan_with_http_endpoint(
    *,
    intent: str,
    device_id: str,
    project_context: Dict[str, Any],
    planner_memory: Dict[str, List[Dict[str, Any]]],
    planner_config: Dict[str, Any],
    conversation_id: str,
    message_id: str,
) -> Dict[str, Any]:
    endpoint = planner_endpoint()
    if not endpoint:
        raise AssistantPlannerUnavailable(
            "service_llm_unavailable",
            "服务端 LLM planner 未配置",
        )

    payload = {
        "model": planner_model(),
        "intent": intent,
        "device_id": device_id,
        "conversation_id": conversation_id,
        "message_id": message_id,
        "project_context": project_context,
        "planner_memory": planner_memory,
        "planner_config": planner_config,
    }

    headers: Dict[str, str] = {"Content-Type": "application/json"}
    api_key = planner_api_key()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    timeout_seconds = planner_timeout_ms() / 1000.0
    client = get_shared_http_client()

    try:
        import httpx

        response = await asyncio.wait_for(
            client.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=timeout_seconds,
            ),
            timeout=timeout_seconds + 0.5,
        )
    except asyncio.TimeoutError as exc:
        raise AssistantPlannerTimeout(
            "service_llm_timeout",
            "服务端 LLM planner 调用超时",
        ) from exc
    except httpx.TimeoutException as exc:
        raise AssistantPlannerTimeout(
            "service_llm_timeout",
            "服务端 LLM planner 调用超时",
        ) from exc
    except httpx.HTTPError as exc:
        raise AssistantPlannerUnavailable(
            "service_llm_unavailable",
            f"服务端 LLM planner 请求失败: {exc}",
        ) from exc

    if response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After", "60") or "60")
        raise AssistantPlannerRateLimited(
            "service_llm_rate_limited",
            "服务端 LLM planner 触发限流",
            retry_after=retry_after,
        )
    if response.status_code in {402, 403}:
        raise AssistantPlannerRateLimited(
            "service_llm_budget_blocked",
            "服务端 LLM planner 预算或配额受限",
            retry_after=planner_budget_retry_after(),
        )
    if response.status_code >= 500:
        raise AssistantPlannerUnavailable(
            "service_llm_unavailable",
            f"服务端 LLM planner 返回 {response.status_code}",
        )
    if response.status_code >= 400:
        raise AssistantPlannerUnavailable(
            "service_llm_invalid",
            f"服务端 LLM planner 返回非法响应 {response.status_code}",
        )

    return _normalize_plan_payload(response.json())


async def plan_with_service_llm(
    *,
    intent: str,
    device_id: str,
    project_context: Dict[str, Any],
    planner_memory: Dict[str, List[Dict[str, Any]]],
    planner_config: Dict[str, Any],
    conversation_id: str,
    message_id: str,
) -> Dict[str, Any]:
    """调用服务端受控 LLM planner。"""
    if planner_budget_blocked():
        raise AssistantPlannerRateLimited(
            "service_llm_budget_blocked",
            "服务端智能规划当前预算或配额受限",
            retry_after=planner_budget_retry_after(),
        )

    if planner_endpoint():
        return await _plan_with_http_endpoint(
            intent=intent,
            device_id=device_id,
            project_context=project_context,
            planner_memory=planner_memory,
            planner_config=planner_config,
            conversation_id=conversation_id,
            message_id=message_id,
        )

    return await _plan_with_openai_compatible(
        intent=intent,
        device_id=device_id,
        project_context=project_context,
        planner_memory=planner_memory,
        planner_config=planner_config,
        conversation_id=conversation_id,
        message_id=message_id,
    )
