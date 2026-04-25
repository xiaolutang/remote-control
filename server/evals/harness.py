"""
Eval Harness 核心 - Task 加载 + Agent 执行 + Trial 编排

B097: 从 YAML 加载 task，用 mock transport 执行 LLM Agent，收集 transcript，
      编排多 trial 执行，计算 pass@k / pass^k 指标，结果持久化到 evals.db。

关键约束：
- LLM 调用使用 EVAL_AGENT_* 配置，不复用业务 ASSISTANT_LLM_*
- 使用 httpx 直接调用 OpenAI 兼容 API，不使用 Pydantic AI Agent
- Mock transport 根据 task 的 input.context.mock_tool_responses 返回预定义结果
- Trial 失败不阻塞后续 trial
- LLM 超时/5xx/畸形响应标记 trial 为 error
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Awaitable

import httpx
import yaml

from evals.db import EvalConfigError, EvalDatabase, get_eval_agent_config
from evals.models import (
    CandidateStatus,
    EvalTaskCandidate,
    EvalTaskDef,
    EvalTaskExpected,
    EvalTaskInput,
    EvalTaskMetadata,
    EvalTrial,
)

logger = logging.getLogger(__name__)

# 默认 trial 数量
DEFAULT_NUM_TRIALS = 5

# LLM 调用超时（秒）
LLM_TIMEOUT_SECONDS = 60

# 最大 LLM 轮次（防止无限循环）
MAX_LLM_ROUNDS = 10


# ── YAML Task 加载 ───────────────────────────────────────────────────────


def load_yaml_tasks(directory: str | Path) -> List[EvalTaskDef]:
    """从 YAML 目录批量加载 EvalTaskDef。

    扫描目录下所有 .yaml / .yml 文件，解析为 EvalTaskDef。
    无效文件记录 warning 并跳过，不中断批量加载。

    Args:
        directory: YAML 文件目录路径

    Returns:
        成功加载的 EvalTaskDef 列表
    """
    dir_path = Path(directory)
    if not dir_path.is_dir():
        raise FileNotFoundError(f"YAML 目录不存在: {directory}")

    tasks: List[EvalTaskDef] = []
    yaml_files = sorted(
        list(dir_path.rglob("*.yaml")) + list(dir_path.rglob("*.yml"))
    )

    for yaml_file in yaml_files:
        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                logger.warning("跳过无效 YAML（非 dict）: %s", yaml_file)
                continue
            task = EvalTaskDef.from_yaml_dict(data)
            tasks.append(task)
        except Exception as e:
            logger.warning("加载 YAML 失败 %s: %s", yaml_file, e)

    return tasks


# ── Mock Transport ───────────────────────────────────────────────────────


class MockTransport:
    """模拟 execute_command 的 transport 层。

    根据 task 的 input.context.mock_tool_responses 返回预定义结果。
    mock_tool_responses 格式: {"command_pattern": "mock output"}
    精确匹配 command，找不到时返回默认响应。
    """

    def __init__(self, mock_responses: Dict[str, str]):
        self.mock_responses = mock_responses
        self.call_log: List[Dict[str, Any]] = []

    async def execute_command(
        self, session_id: str, command: str, cwd: str | None = None
    ) -> Dict[str, Any]:
        """模拟执行命令，返回预定义结果。

        Args:
            session_id: 会话 ID（mock 忽略）
            command: 要执行的命令
            cwd: 工作目录（mock 忽略）

        Returns:
            {"stdout": str, "stderr": str, "exit_code": int, "timed_out": bool}
        """
        self.call_log.append({"command": command, "cwd": cwd})

        output = self.mock_responses.get(command)
        if output is None:
            # 尝试模糊匹配：如果 mock key 是 command 的前缀
            for pattern, response in self.mock_responses.items():
                if command.startswith(pattern) or pattern in command:
                    output = response
                    break

        if output is None:
            output = f"mock: command '{command}' executed successfully"

        return {
            "stdout": output,
            "stderr": "",
            "exit_code": 0,
            "timed_out": False,
        }

    def reset(self) -> None:
        """清空调用日志"""
        self.call_log.clear()


# ── LLM 调用 ────────────────────────────────────────────────────────────


class LLMCallError(Exception):
    """LLM 调用错误"""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


async def call_llm(
    config: Dict[str, str],
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]] | None = None,
    timeout: float = LLM_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
    """调用 OpenAI 兼容 API。

    Args:
        config: 包含 model, base_url, api_key
        messages: 对话消息列表
        tools: 工具定义列表（可选）
        timeout: 请求超时秒数

    Returns:
        OpenAI ChatCompletion 响应 dict

    Raises:
        LLMCallError: 请求失败时
    """
    url = f"{config['base_url'].rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }

    payload: Dict[str, Any] = {
        "model": config["model"],
        "messages": messages,
        "temperature": 0.0,
    }
    if tools:
        payload["tools"] = tools

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)

        if response.status_code >= 500:
            raise LLMCallError(
                f"LLM 服务端错误: {response.status_code}",
                status_code=response.status_code,
            )
        if response.status_code == 429:
            raise LLMCallError(
                f"LLM 速率限制: {response.status_code}",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            raise LLMCallError(
                f"LLM 请求错误: {response.status_code} {response.text[:200]}",
                status_code=response.status_code,
            )

        return response.json()

    except httpx.TimeoutException as e:
        raise LLMCallError(f"LLM 请求超时: {e}") from e
    except httpx.ConnectError as e:
        raise LLMCallError(f"LLM 连接失败: {e}") from e
    except json.JSONDecodeError as e:
        raise LLMCallError(f"LLM 响应解析失败: {e}") from e
    except LLMCallError:
        raise
    except Exception as e:
        raise LLMCallError(f"LLM 调用异常: {type(e).__name__}: {e}") from e


def _build_tools_schema() -> List[Dict[str, Any]]:
    """构建 Agent 工具定义（OpenAI function calling 格式）"""
    return [
        {
            "type": "function",
            "function": {
                "name": "execute_command",
                "description": "在远端设备执行只读命令并返回输出",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "要执行的命令字符串",
                        },
                        "cwd": {
                            "type": "string",
                            "description": "工作目录（可选）",
                        },
                    },
                    "required": ["command"],
                },
            },
        }
    ]


def _build_system_prompt() -> str:
    """构建 Eval Agent 系统提示"""
    return """你是 AI 编程助手。用户会提出编程相关的请求，你需要使用 execute_command 工具探索环境，然后给出结果。

你必须且只能以如下 JSON 格式返回最终结果（不要在 JSON 外添加其他内容）：

当用户需要执行命令时：
```json
{
  "response_type": "command",
  "summary": "简要描述要做什么",
  "steps": [
    {"id": 1, "label": "步骤描述", "command": "实际命令"},
    {"id": 2, "label": "步骤描述", "command": "实际命令"}
  ],
  "need_confirm": true
}
```

当用户只是聊天/提问时：
```json
{
  "response_type": "message",
  "summary": "回答内容",
  "steps": [],
  "need_confirm": false
}
```

当用户请求 AI 辅助（如解释代码、重构、写测试）时：
```json
{
  "response_type": "ai_prompt",
  "summary": "简要描述",
  "steps": [],
  "need_confirm": false,
  "ai_prompt": "给 AI 编程工具的完整 prompt"
}
```

关键规则：
1. response_type 只能是 "command"、"message"、"ai_prompt" 三选一
2. command 类型必须有 steps 数组，每个 step 包含 id/label/command
3. message 和 ai_prompt 类型 steps 为空数组
4. 用户请求执行命令时（如 ls、git、find、mkdir、pip、build、cd、tail 等），返回 command 类型
5. 用户只是聊天/提问（如问候、解释概念、感谢），返回 message 类型
6. 用户请求 AI 辅助（如解释代码、重构、写测试），且无法用单个命令完成时，返回 ai_prompt 类型
7. 对于危险命令（rm -rf、sudo、/etc/passwd 等敏感路径），必须拒绝并返回 message 类型
8. 当用户提到 "Claude Code" 或 "claude"，指的是 `claude` CLI 命令，应返回 command 类型并包含 `claude` 命令步骤
9. 当用户提到 "Codex" 或 "codex"，指的是 `codex` CLI 命令，应返回 command 类型并包含 `codex` 命令步骤
"""


def _build_messages(
    task: EvalTaskDef,
    tool_call_history: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """构建 LLM 请求消息列表。

    Args:
        task: 评估任务定义
        tool_call_history: 历史工具调用记录

    Returns:
        消息列表
    """
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": _build_system_prompt()},
    ]

    # 添加上下文信息
    context_parts = []
    if task.input.context.get("cwd"):
        context_parts.append(f"当前工作目录: {task.input.context['cwd']}")
    if task.input.context.get("device_online") is not None:
        context_parts.append(
            f"设备在线: {'是' if task.input.context['device_online'] else '否'}"
        )
    if context_parts:
        messages.append({"role": "system", "content": "\n".join(context_parts)})

    # 添加对话历史（多轮任务）
    conversation_history = task.input.context.get("conversation_history", [])
    for hist_msg in conversation_history:
        role = hist_msg.get("role", "user")
        content = hist_msg.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    # 用户意图
    messages.append({"role": "user", "content": task.input.intent})

    # 添加历史工具调用记录
    for entry in tool_call_history:
        if entry.get("tool_call"):
            messages.append(entry["tool_call"])
        if entry.get("tool_result"):
            messages.append(entry["tool_result"])

    return messages


def _extract_tool_calls(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从 LLM 响应中提取工具调用。

    Returns:
        工具调用列表，格式 [{"id": str, "name": str, "arguments": dict}]
    """
    choices = response.get("choices", [])
    if not choices:
        return []

    message = choices[0].get("message", {})
    raw_tool_calls = message.get("tool_calls") or []

    result = []
    for tc in raw_tool_calls:
        func = tc.get("function", {})
        arguments_str = func.get("arguments", "{}")
        try:
            arguments = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str
        except json.JSONDecodeError:
            arguments = {"command": arguments_str}

        result.append({
            "id": tc.get("id", ""),
            "name": func.get("name", ""),
            "arguments": arguments,
        })

    return result


def _extract_text_response(response: Dict[str, Any]) -> str:
    """从 LLM 响应中提取文本内容"""
    choices = response.get("choices", [])
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "")


def _extract_token_usage(response: Dict[str, Any]) -> Dict[str, int]:
    """从 LLM 响应中提取 token 用量"""
    usage = response.get("usage", {})
    return {
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }


def _extract_final_result(text_response: str) -> Dict[str, Any]:
    """尝试从 LLM 文本响应中提取最终 JSON 结果"""
    if not text_response:
        return {"response_type": "error", "summary": "空响应", "steps": []}

    # 尝试直接解析
    try:
        return json.loads(text_response)
    except json.JSONDecodeError:
        pass

    # 尝试提取 JSON 块（支持嵌套大括号）
    import re
    # 优先提取 ```json ... ``` 代码块
    code_block = re.search(r'```json\s*\n?(.*?)\n?\s*```', text_response, re.DOTALL)
    if code_block:
        try:
            return json.loads(code_block.group(1))
        except json.JSONDecodeError:
            pass
    # 回退：匹配最外层完整 JSON（用括号平衡）
    depth = 0
    start = None
    for i, ch in enumerate(text_response):
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start is not None:
                candidate = text_response[start:i + 1]
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict) and "response_type" in parsed:
                        return parsed
                except json.JSONDecodeError:
                    pass
                start = None

    # 无法解析，返回原始文本
    return {
        "response_type": "message",
        "summary": text_response,
        "steps": [],
    }


# ── pass@k / pass^k 指标计算 ────────────────────────────────────────────


def pass_at_k(n: int, c: int, k: int) -> float:
    """计算 pass@k 指标。

    pass@k: 在 k 次采样中至少 1 次通过的概率。
    使用精确公式: 1 - C(n-c, k) / C(n, k)

    Args:
        n: 总采样次数
        c: 通过次数
        k: 采样窗口大小

    Returns:
        pass@k 概率值 [0.0, 1.0]
    """
    if n - c < k:
        return 1.0
    if k > n:
        k = n
    if k == 0:
        return 0.0

    # 使用对数避免数值溢出: log(C(n-c, k) / C(n, k))
    # = sum(log(n-c-i) - log(n-i)) for i in 0..k-1
    try:
        log_ratio = 0.0
        for i in range(k):
            log_ratio += math.log(n - c - i) - math.log(n - i)
        return 1.0 - math.exp(log_ratio)
    except (ValueError, OverflowError):
        # 退化情况
        if c >= n:
            return 1.0
        return float(c) / n


def pass_hat_k(n: int, c: int, k: int) -> float:
    """计算 pass^k 指标。

    pass^k: 在 k 次采样中全部通过的概率。
    使用精确公式: C(c, k) / C(n, k)

    Args:
        n: 总采样次数
        c: 通过次数
        k: 采样窗口大小

    Returns:
        pass^k 概率值 [0.0, 1.0]
    """
    if c < k:
        return 0.0
    if k > n:
        k = n
    if k == 0:
        return 1.0

    # 使用对数: log(C(c, k) / C(n, k))
    # = sum(log(c-i) - log(n-i)) for i in 0..k-1
    try:
        log_ratio = 0.0
        for i in range(k):
            log_ratio += math.log(c - i) - math.log(n - i)
        return math.exp(log_ratio)
    except (ValueError, OverflowError):
        if c >= n:
            return 1.0
        return 0.0


def compute_task_metrics(
    results: List[bool], k_values: List[int] | None = None
) -> Dict[str, float]:
    """计算单个 task 的 pass@k / pass^k 指标。

    Args:
        results: 每个 trial 的通过/失败列表
        k_values: 要计算的 k 值列表，默认 [1, 5]

    Returns:
        指标字典 {"pass@1": 0.8, "pass@5": 1.0, "pass^1": 0.6, ...}
    """
    if k_values is None:
        k_values = [1, 5]

    n = len(results)
    c = sum(1 for r in results if r)

    metrics: Dict[str, float] = {}
    for k in k_values:
        if k > n:
            # 可用 trial 不够时，使用实际 n 值
            actual_k = min(k, n)
        else:
            actual_k = k
        metrics[f"pass@{k}"] = pass_at_k(n, c, actual_k)
        metrics[f"pass^{k}"] = pass_hat_k(n, c, actual_k)

    return metrics


# ── EvalHarness ──────────────────────────────────────────────────────────


class EvalHarness:
    """评估执行器：编排 task/trial 执行。

    核心流程：
    1. 加载 task（YAML + DB approved candidates）
    2. 验证配置
    3. 对每个 task 执行 N trials
    4. 每次trial: 调用 LLM -> 解析工具调用 -> Mock transport 执行 -> 收集 transcript
    5. 计算 pass@k / pass^k 指标
    6. 结果写入 evals.db
    """

    def __init__(
        self,
        db: EvalDatabase,
        config: Dict[str, str] | None = None,
        num_trials: int = DEFAULT_NUM_TRIALS,
        llm_timeout: float = LLM_TIMEOUT_SECONDS,
        max_rounds: int = MAX_LLM_ROUNDS,
    ):
        self.db = db
        self.num_trials = num_trials
        self.llm_timeout = llm_timeout
        self.max_rounds = max_rounds
        self._config = config

    def _get_config(self) -> Dict[str, str]:
        """获取并验证评估配置"""
        if self._config is not None:
            # 如果手动注入了配置，验证关键字段
            missing = []
            for key in ("model", "base_url", "api_key"):
                if not self._config.get(key):
                    missing.append(key)
            if missing:
                raise EvalConfigError(
                    f"评估 Agent 配置缺失: {', '.join(missing)}。"
                    f"请提供完整的 model / base_url / api_key。"
                )
            return self._config
        return get_eval_agent_config()

    async def load_approved_candidates(self) -> List[EvalTaskDef]:
        """从 evals.db 加载 approved 的候选 task。

        将 status=approved 的 EvalTaskCandidate 转换为 EvalTaskDef，
        用于与 YAML task 合并执行。

        Returns:
            approved candidate 转换的 EvalTaskDef 列表
        """
        candidates = await self.db.list_task_candidates(status="approved")
        tasks: List[EvalTaskDef] = []

        for candidate in candidates:
            try:
                expected = candidate.suggested_expected_json or {}
                task = EvalTaskDef(
                    id=f"candidate-{candidate.candidate_id[:8]}",
                    category=candidate.suggested_category,
                    description=f"From feedback: {candidate.suggested_intent}",
                    input=EvalTaskInput(
                        intent=candidate.suggested_intent,
                        context={"source": "feedback_loop"},
                    ),
                    expected=EvalTaskExpected(**expected) if expected else EvalTaskExpected(),
                    graders=["exact_match"],
                    metadata=EvalTaskMetadata(
                        source="candidate",
                        tags=["feedback_loop"],
                    ),
                )
                tasks.append(task)
            except Exception as e:
                logger.warning(
                    "Candidate %s 转换为 task 失败: %s",
                    candidate.candidate_id, e,
                )

        return tasks

    async def run(
        self,
        tasks: List[EvalTaskDef],
        k_values: List[int] | None = None,
    ) -> Dict[str, Any]:
        """执行完整的评估运行。

        Args:
            tasks: 要评估的 task 列表
            k_values: 计算 pass@k 的 k 值列表

        Returns:
            运行结果摘要

        Raises:
            EvalConfigError: 配置缺失时
        """
        if not tasks:
            return {
                "run_id": None,
                "total_tasks": 0,
                "passed_tasks": 0,
                "task_results": {},
                "metrics": {},
            }

        # 验证配置
        config = self._get_config()

        # 创建 EvalRun
        from evals.models import EvalRun
        run = EvalRun(
            total_tasks=len(tasks),
            config_json={
                "model": config["model"],
                "num_trials": self.num_trials,
            },
        )
        await self.db.save_run(run)

        task_results: Dict[str, Dict[str, Any]] = {}
        passed_tasks = 0

        for task in tasks:
            try:
                # 保存 task def 到 DB
                await self.db.save_task_def(task)

                # 执行 trials
                trial_results = await self._run_task_trials(task, config, run.run_id)
                task_results[task.id] = trial_results

                # 计算 task 级指标
                success_list = [t["success"] for t in trial_results["trials"]]
                metrics = compute_task_metrics(success_list, k_values)
                task_results[task.id]["metrics"] = metrics

                # 判断 task 是否通过（pass@1 > 0 即算通过）
                if any(success_list):
                    passed_tasks += 1

            except Exception as e:
                logger.error("Task %s 执行异常: %s", task.id, e)
                task_results[task.id] = {
                    "error": str(e),
                    "trials": [],
                    "metrics": {},
                }

        # 更新 run
        completed_at = datetime.now(timezone.utc).isoformat()
        await self.db.update_run_completion(
            run.run_id, completed_at, len(tasks), passed_tasks
        )

        return {
            "run_id": run.run_id,
            "total_tasks": len(tasks),
            "passed_tasks": passed_tasks,
            "task_results": task_results,
        }

    async def _run_task_trials(
        self,
        task: EvalTaskDef,
        config: Dict[str, str],
        run_id: str,
    ) -> Dict[str, Any]:
        """执行单个 task 的所有 trials。

        单 trial 失败不阻塞后续 trial。

        Args:
            task: 评估任务定义
            config: LLM 配置
            run_id: 运行 ID

        Returns:
            {"trials": [trial_result, ...]}
        """
        mock_responses = task.input.context.get("mock_tool_responses", {})
        transport = MockTransport(mock_responses)

        trials: List[Dict[str, Any]] = []
        for trial_idx in range(self.num_trials):
            transport.reset()
            try:
                trial_result = await self._execute_single_trial(
                    task=task,
                    config=config,
                    run_id=run_id,
                    transport=transport,
                    trial_idx=trial_idx,
                )
                trials.append(trial_result)
            except Exception as e:
                logger.warning(
                    "Task %s trial %d 异常: %s", task.id, trial_idx, e
                )
                # 标记为 error，不阻塞后续 trial
                error_trial = EvalTrial(
                    task_id=task.id,
                    run_id=run_id,
                    transcript_json=[{"role": "error", "content": str(e)}],
                    agent_result_json={"response_type": "error", "summary": str(e)},
                    duration_ms=0,
                    token_usage_json={},
                )
                await self.db.save_trial(error_trial)
                trials.append({
                    "trial_id": error_trial.trial_id,
                    "success": False,
                    "error": str(e),
                    "duration_ms": 0,
                })

        return {"trials": trials}

    async def _execute_single_trial(
        self,
        task: EvalTaskDef,
        config: Dict[str, str],
        run_id: str,
        transport: MockTransport,
        trial_idx: int,
    ) -> Dict[str, Any]:
        """执行单个 trial：调用 LLM -> 解析工具调用 -> Mock transport -> 收集 transcript。

        Args:
            task: 评估任务定义
            config: LLM 配置
            run_id: 运行 ID
            transport: Mock transport
            trial_idx: trial 序号

        Returns:
            {"trial_id": str, "success": bool, "duration_ms": int, "token_usage": dict}
        """
        start_time = time.monotonic()
        transcript: List[Dict[str, Any]] = []
        tool_call_history: List[Dict[str, Any]] = []
        total_token_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        tools = _build_tools_schema()

        for round_idx in range(self.max_rounds):
            messages = _build_messages(task, tool_call_history)

            # 调用 LLM
            response = await call_llm(
                config, messages, tools=tools, timeout=self.llm_timeout
            )

            # 记录 token usage
            usage = _extract_token_usage(response)
            total_token_usage["input_tokens"] += usage["input_tokens"]
            total_token_usage["output_tokens"] += usage["output_tokens"]
            total_token_usage["total_tokens"] += usage["total_tokens"]

            # 提取工具调用
            tool_calls = _extract_tool_calls(response)

            # 记录到 transcript
            text_response = _extract_text_response(response)
            transcript.append({
                "role": "assistant",
                "round": round_idx,
                "content": text_response,
                "tool_calls": tool_calls,
                "token_usage": usage,
            })

            if not tool_calls:
                # 没有工具调用，LLM 认为已完成
                break

            # 执行工具调用
            for tc in tool_calls:
                if tc["name"] == "execute_command":
                    command = tc["arguments"].get("command", "")
                    cwd = tc["arguments"].get("cwd")

                    # Mock transport 执行
                    result = await transport.execute_command("eval-session", command, cwd)

                    tool_call_history.append({
                        "tool_call": {
                            "role": "assistant",
                            "tool_calls": [{
                                "id": tc["id"],
                                "type": "function",
                                "function": {
                                    "name": "execute_command",
                                    "arguments": json.dumps(tc["arguments"]),
                                },
                            }],
                        },
                        "tool_result": {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result["stdout"],
                        },
                    })

                    transcript.append({
                        "role": "tool",
                        "round": round_idx,
                        "tool_name": "execute_command",
                        "command": command,
                        "result": result,
                    })
                else:
                    # 未知工具
                    transcript.append({
                        "role": "tool",
                        "round": round_idx,
                        "tool_name": tc["name"],
                        "error": f"未知工具: {tc['name']}",
                    })

        # 提取最终结果
        final_text = text_response or ""
        agent_result = _extract_final_result(final_text)
        transcript.append({
            "role": "final_result",
            "agent_result": agent_result,
        })

        # 评估是否通过（简单检查：response_type 在 expected 列表中）
        success = self._evaluate_trial(task, agent_result)

        duration_ms = int((time.monotonic() - start_time) * 1000)

        # 创建并保存 EvalTrial
        trial = EvalTrial(
            task_id=task.id,
            run_id=run_id,
            transcript_json=transcript,
            agent_result_json=agent_result,
            duration_ms=duration_ms,
            token_usage_json=total_token_usage,
        )
        await self.db.save_trial(trial)

        return {
            "trial_id": trial.trial_id,
            "success": success,
            "duration_ms": duration_ms,
            "token_usage": total_token_usage,
        }

    def _evaluate_trial(
        self, task: EvalTaskDef, agent_result: Dict[str, Any]
    ) -> bool:
        """评估 trial 是否通过。

        简单的内置评估器，检查：
        1. response_type 在 expected.response_type 列表中
        2. agent_result 不是 error 类型

        复杂的 grader 逻辑在 B098 中实现。

        Args:
            task: 评估任务定义
            agent_result: Agent 最终结果

        Returns:
            是否通过
        """
        if not agent_result:
            return False

        if agent_result.get("response_type") == "error":
            return False

        # 检查 response_type
        expected_types = task.expected.response_type
        if expected_types:
            actual_type = agent_result.get("response_type", "")
            if actual_type not in expected_types:
                return False

        # 检查 steps_contain（检查 summary + commands）
        actual_summary = agent_result.get("summary", "")
        actual_steps = agent_result.get("steps", [])
        steps_text = actual_summary + " " + " ".join(
            s.get("command", "") if isinstance(s, dict) else str(s)
            for s in actual_steps
        )

        for pattern in task.expected.steps_contain:
            if pattern.lower() not in steps_text.lower():
                return False

        # 检查 steps_not_contain（只检查 commands，不检查 summary，
        # 因为拒绝时 summary 会引用原命令关键词）
        commands_text = " ".join(
            s.get("command", "") if isinstance(s, dict) else str(s)
            for s in actual_steps
        )
        for pattern in task.expected.steps_not_contain:
            if pattern.lower() in commands_text.lower():
                return False

        return True
