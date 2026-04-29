"""
Invariant Grader — 检查 Agent session 的状态不变量

B054: 在 eval trial 后自动检查多轮状态一致性。
三种不变量规则：
1. token_monotonic_increase — 验证后续 run 的 total_tokens >= 前一次
2. usage_non_negative — input/output/total tokens 均不能为负
3. sse_sequence_valid — SSE 事件序列合法性（phase_change 开始、result/error 结束）

设计：
- 继承 CodeGraderBase，注册为 "invariant" 类型
- config 通过 task.expected.model_extra["invariants"] 传入
- 每条 invariant 独立检查，收集所有 violation
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

from evals.graders.code_grader import CodeGraderBase, GRADER_REGISTRY, _register
from evals.models import EvalGraderResult, EvalTaskDef, EvalTrial


# ── 不变量检查函数 ──────────────────────────────────────────────────────────


def _check_token_monotonic(trial: EvalTrial) -> List[str]:
    """检查 token 累加单调递增。

    从 trial transcript 中的 result/final_result 事件提取 usage.total_tokens，
    验证后续 run 的 total_tokens >= 前一次（累加不减少）。

    Returns:
        violation 列表（空表示通过）
    """
    violations: List[str] = []
    prev_total: int | None = None

    for entry in trial.transcript_json:
        role = entry.get("role", "")

        # 从 assistant 角色或 final_result 角色中提取 token_usage
        if role in ("assistant", "final_result"):
            token_usage = entry.get("token_usage") or {}
            total_tokens = int(token_usage.get("total_tokens", 0) or 0)

            if total_tokens > 0:
                if prev_total is not None and total_tokens < prev_total:
                    violations.append(
                        f"token decreased from {prev_total} to {total_tokens}"
                    )
                prev_total = total_tokens

        # 也从 agent_result 中提取 token_usage
        agent_result = entry.get("agent_result") or {}
        if isinstance(agent_result, dict):
            token_usage = agent_result.get("token_usage") or {}
            total_tokens = int(token_usage.get("total_tokens", 0) or 0)

            if total_tokens > 0:
                if prev_total is not None and total_tokens < prev_total:
                    violations.append(
                        f"token decreased from {prev_total} to {total_tokens}"
                    )
                prev_total = total_tokens

    return violations


def _check_usage_non_negative(trial: EvalTrial) -> List[str]:
    """检查所有 usage 字段均为非负。

    从 trial transcript 中所有事件提取 usage 字段，
    检查 input_tokens, output_tokens, total_tokens 均不能为负。

    Returns:
        violation 列表（空表示通过）
    """
    violations: List[str] = []
    token_fields = ("input_tokens", "output_tokens", "total_tokens")

    for idx, entry in enumerate(trial.transcript_json):
        # 检查顶层的 token_usage
        token_usage = entry.get("token_usage") or {}
        if isinstance(token_usage, dict):
            for field in token_fields:
                val = token_usage.get(field)
                if val is not None and int(val) < 0:
                    violations.append(
                        f"negative {field}={val} in event at index {idx}"
                    )

        # 检查 agent_result 内嵌的 token_usage
        agent_result = entry.get("agent_result") or {}
        if isinstance(agent_result, dict):
            token_usage = agent_result.get("token_usage") or {}
            if isinstance(token_usage, dict):
                for field in token_fields:
                    val = token_usage.get(field)
                    if val is not None and int(val) < 0:
                        violations.append(
                            f"negative {field}={val} in event at index {idx}"
                        )

    return violations


def _check_sse_sequence(trial: EvalTrial) -> List[str]:
    """检查 SSE 事件序列合法性。

    规则：
    1. 必须以 phase_change(thinking) 开始（或至少出现 phase_change）
    2. 必须以 result 或 error 结束
    3. 中间不允许出现两个连续 phase_change(phase=result)

    Returns:
        violation 列表（空表示通过）
    """
    violations: List[str] = []

    # 收集所有 SSE 事件
    all_sse_events: List[Dict[str, Any]] = []
    for entry in trial.transcript_json:
        sse_events = entry.get("sse_events") or []
        if isinstance(sse_events, list):
            all_sse_events.extend(sse_events)

    # 也检查 agent_result 中的 sse_events
    agent_result = trial.agent_result_json or {}
    sse_events = agent_result.get("sse_events") or []
    if isinstance(sse_events, list):
        all_sse_events.extend(sse_events)

    if not all_sse_events:
        # 无 SSE 事件时不算违规（可能非 integration 模式）
        return violations

    # 提取事件类型
    event_types: List[str] = []
    for event in all_sse_events:
        event_type = event.get("event_type", "") or event.get("type", "")
        event_types.append(str(event_type))

    # 规则 1：必须包含 phase_change
    phase_change_indices = [
        idx for idx, et in enumerate(event_types) if et == "phase_change"
    ]
    if not phase_change_indices:
        violations.append("missing phase_change event")
    else:
        # 检查首个 phase_change 的 phase 是否为 thinking
        first_phase = all_sse_events[phase_change_indices[0]]
        phase_payload = first_phase.get("payload") or {}
        phase_value = phase_payload.get("phase", "")
        if phase_value and phase_value != "thinking":
            violations.append(
                f"first phase_change phase is '{phase_value}', expected 'thinking'"
            )

    # 规则 2：必须以 result 或 error 结束
    if event_types:
        last_event_type = event_types[-1]
        if last_event_type not in ("result", "error"):
            violations.append("missing result/error terminal event")

    # 规则 3：不允许两个连续 phase_change(phase=result)
    prev_phase_is_result = False
    for event in all_sse_events:
        event_type = str(event.get("event_type", "") or event.get("type", ""))
        if event_type == "phase_change":
            phase_payload = event.get("payload") or {}
            phase_value = phase_payload.get("phase", "")
            if phase_value == "result":
                if prev_phase_is_result:
                    violations.append(
                        "consecutive phase_change(phase=result) events"
                    )
                prev_phase_is_result = True
            else:
                prev_phase_is_result = False
        else:
            prev_phase_is_result = False

    return violations


# ── 不变量函数映射 ──────────────────────────────────────────────────────────


SUPPORTED_INVARIANTS: Dict[str, Callable[[EvalTrial], List[str]]] = {
    "token_monotonic_increase": _check_token_monotonic,
    "usage_non_negative": _check_usage_non_negative,
    "sse_sequence_valid": _check_sse_sequence,
}


# ── InvariantGrader ────────────────────────────────────────────────────────


@_register
class InvariantGrader(CodeGraderBase):
    """检查 Agent session 的状态不变量。

    从 task.expected 的 model_extra 中读取 invariants 列表，
    依次调用对应的检查函数，收集所有 violation。

    config 示例（在 task YAML 的 expected 中）:
        expected:
          invariants:
            - token_monotonic_increase
            - usage_non_negative
    """

    @property
    def grader_type(self) -> str:
        return "invariant"

    def grade(self, trial: EvalTrial, task: EvalTaskDef) -> EvalGraderResult:
        """执行所有配置的不变量检查。

        Args:
            trial: 评估试验记录
            task: 评估任务定义

        Returns:
            EvalGraderResult，details_json 包含各 invariant 的检查结果
        """
        # 获取配置的 invariants 列表
        config_invariants = self._get_invariants_config(task)

        if not config_invariants:
            return EvalGraderResult(
                trial_id=trial.trial_id,
                grader_type=self.grader_type,
                passed=True,
                score=1.0,
                details_json={
                    "checked_invariants": [],
                    "violations": [],
                    "reason": "未配置 invariants，默认通过",
                },
            )

        all_violations: List[Dict[str, Any]] = []
        checked: List[str] = []

        for invariant_name in config_invariants:
            check_fn = SUPPORTED_INVARIANTS.get(invariant_name)
            if check_fn is None:
                all_violations.append({
                    "invariant": invariant_name,
                    "violations": [f"未知的不变量规则: {invariant_name}"],
                })
                checked.append(invariant_name)
                continue

            violations = check_fn(trial)
            checked.append(invariant_name)
            if violations:
                all_violations.append({
                    "invariant": invariant_name,
                    "violations": violations,
                })

        passed = len(all_violations) == 0
        total = len(config_invariants)
        passed_count = total - len(all_violations)
        score = passed_count / total if total > 0 else 1.0

        # 构建原因描述
        if passed:
            reason = f"所有 {total} 个不变量检查通过"
        else:
            violation_descriptions = []
            for v in all_violations:
                for detail in v["violations"]:
                    violation_descriptions.append(
                        f"[{v['invariant']}] {detail}"
                    )
            reason = f"不变量违反: {'; '.join(violation_descriptions)}"

        return EvalGraderResult(
            trial_id=trial.trial_id,
            grader_type=self.grader_type,
            passed=passed,
            score=score,
            details_json={
                "checked_invariants": checked,
                "violations": all_violations,
                "reason": reason,
            },
        )

    def _get_invariants_config(self, task: EvalTaskDef) -> List[str]:
        """从 task 配置中提取 invariants 列表。

        支持两种配置方式：
        1. task.expected.model_extra["invariants"]
        2. task.graders 中含 {"type": "invariant", "invariants": [...]}

        Returns:
            invariants 名称列表
        """
        # 方式 1：从 expected 的 model_extra 中获取
        if task.expected.model_extra:
            invariants = task.expected.model_extra.get("invariants")
            if invariants and isinstance(invariants, list):
                return invariants

        # 方式 2：从 task 的额外字段获取（graders 可能包含配置）
        if task.model_extra:
            # 检查 graders 中是否有 invariant 配置
            graders = task.model_extra.get("graders_config") or []
            for grader_conf in graders:
                if isinstance(grader_conf, dict) and grader_conf.get("type") == "invariant":
                    inv = grader_conf.get("invariants", [])
                    if isinstance(inv, list):
                        return inv

        return []
