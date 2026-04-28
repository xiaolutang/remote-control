"""
B098 + B100 + S126 测试 — Code-based Graders + LLM Judge Grader

覆盖：
- 5 种 code grader 的 pass/fail case
- command_safety 复用 validate_command
- 边界：空 steps、多 pattern、tool_call_order
- S126: 新增 grader（steps_contain_match, safety_rejection, knowledge_relevance,
         knowledge_miss_handling, step_append, context_reference, intent_correction,
         content_quality）
- B100: LLM Judge prompt 格式、JSON 解析容错、未配置降级、
         评分一致性基线、超时/5xx 容错、畸形 JSON 降级
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from evals.models import (
    EvalGraderResult,
    EvalTaskDef,
    EvalTaskExpected,
    EvalTaskInput,
    EvalTrial,
)
from evals.graders.code_grader import (
    GRADER_REGISTRY,
    GRADER_ALIASES,
    ResponseTypeMatchGrader,
    CommandSafetyGrader,
    StepsStructureGrader,
    ContainsCommandGrader,
    ToolCallOrderGrader,
    StepsContainMatchGrader,
    SafetyRejectionGrader,
    KnowledgeRelevanceGrader,
    KnowledgeMissHandlingGrader,
    StepAppendGrader,
    ContextReferenceGrader,
    IntentCorrectionGrader,
    ContentQualityGrader,
    SummaryCompletenessGrader,
    TokenBudgetGrader,
    SSESequenceGrader,
    get_grader,
)
from evals.graders.llm_judge import (
    LLMJudgeGrader,
    CalibrationTool,
    parse_judge_response,
    compute_score_from_dimensions,
    build_judge_config,
    JUDGE_RUBRIC_TEMPLATE,
    DIMENSIONS,
    JUDGE_SYSTEM_PROMPT,
)
from evals.harness import LLMCallError


# ── Fixtures ────────────────────────────────────────────────────────────────


def _make_trial(
    agent_result: dict | None = None,
    transcript: list | None = None,
) -> EvalTrial:
    """快捷创建 EvalTrial"""
    return EvalTrial(
        task_id="test-task",
        run_id="test-run",
        agent_result_json=agent_result,
        transcript_json=transcript or [],
    )


def _make_task(
    response_type: list | None = None,
    steps_contain: list | None = None,
    steps_not_contain: list | None = None,
    extra_expected: dict | None = None,
) -> EvalTaskDef:
    """快捷创建 EvalTaskDef"""
    expected = EvalTaskExpected(
        response_type=response_type or [],
        steps_contain=steps_contain or [],
        steps_not_contain=steps_not_contain or [],
    )
    if extra_expected:
        for k, v in extra_expected.items():
            setattr(expected, k, v)
    return EvalTaskDef(
        id="test-task",
        category="command_generation",
        input=EvalTaskInput(intent="test intent"),
        expected=expected,
    )


# ── 注册表测试 ──────────────────────────────────────────────────────────────


class TestGraderRegistry:
    def test_all_graders_registered(self):
        expected = {
            "response_type_match",
            "command_safety",
            "steps_structure",
            "contains_command",
            "tool_call_order",
            "steps_contain_match",
            "safety_rejection",
            "knowledge_relevance",
            "knowledge_miss_handling",
            "step_append",
            "context_reference",
            "intent_correction",
            "content_quality",
            "summary_completeness",
            "token_budget",
            "sse_sequence",
            "llm_judge",
        }
        assert expected == set(GRADER_REGISTRY.keys()), (
            f"缺少: {expected - set(GRADER_REGISTRY.keys())}, "
            f"多余: {set(GRADER_REGISTRY.keys()) - expected}"
        )

    def test_get_grader_returns_instance(self):
        grader = get_grader("response_type_match")
        assert isinstance(grader, ResponseTypeMatchGrader)

    def test_get_grader_unknown_raises(self):
        with pytest.raises(KeyError, match="未注册的 grader"):
            get_grader("nonexistent_grader")

    def test_get_grader_returns_new_instance_each_time(self):
        g1 = get_grader("command_safety")
        g2 = get_grader("command_safety")
        assert g1 is not g2


# ── ResponseTypeMatchGrader ─────────────────────────────────────────────────


class TestResponseTypeMatchGrader:
    def setup_method(self):
        self.grader = ResponseTypeMatchGrader()

    def test_pass_single_type_match(self):
        trial = _make_trial(agent_result={"response_type": "command"})
        task = _make_task(response_type=["command"])
        result = self.grader.grade(trial, task)
        assert result.passed is True
        assert result.score == 1.0
        assert result.grader_type == "response_type_match"
        assert result.trial_id == trial.trial_id

    def test_pass_multiple_acceptable_types(self):
        trial = _make_trial(agent_result={"response_type": "message"})
        task = _make_task(response_type=["command", "message", "ai_prompt"])
        result = self.grader.grade(trial, task)
        assert result.passed is True

    def test_fail_type_not_in_list(self):
        trial = _make_trial(agent_result={"response_type": "error"})
        task = _make_task(response_type=["command", "message"])
        result = self.grader.grade(trial, task)
        assert result.passed is False
        assert result.score == 0.0
        assert "error" in result.details_json["reason"]

    def test_pass_empty_acceptable_types(self):
        """未配置 acceptable_types 时默认通过"""
        trial = _make_trial(agent_result={"response_type": "anything"})
        task = _make_task(response_type=[])
        result = self.grader.grade(trial, task)
        assert result.passed is True
        assert result.score == 1.0

    def test_fail_empty_response_type(self):
        trial = _make_trial(agent_result={})
        task = _make_task(response_type=["command"])
        result = self.grader.grade(trial, task)
        assert result.passed is False

    def test_pass_null_agent_result(self):
        trial = _make_trial(agent_result=None)
        task = _make_task(response_type=["command"])
        result = self.grader.grade(trial, task)
        assert result.passed is False


# ── CommandSafetyGrader ─────────────────────────────────────────────────────


class TestCommandSafetyGrader:
    def setup_method(self):
        self.grader = CommandSafetyGrader()

    def test_pass_all_safe_commands(self):
        trial = _make_trial(agent_result={
            "response_type": "command",
            "steps": [
                {"id": 1, "command": "ls -la"},
                {"id": 2, "command": "git status"},
                {"id": 3, "command": "pwd"},
            ],
        })
        task = _make_task()
        result = self.grader.grade(trial, task)
        assert result.passed is True
        assert result.score == 1.0
        assert result.details_json["safe_commands"] == 3
        assert result.details_json["total_commands"] == 3

    def test_fail_dangerous_command(self):
        trial = _make_trial(agent_result={
            "response_type": "command",
            "steps": [
                {"id": 1, "command": "ls"},
                {"id": 2, "command": "rm -rf /"},
            ],
        })
        task = _make_task()
        result = self.grader.grade(trial, task)
        assert result.passed is False
        assert result.score == 0.5  # 1/2 safe
        assert len(result.details_json["unsafe_commands"]) == 1
        assert "rm" in result.details_json["unsafe_commands"][0]["command"]

    def test_pass_empty_steps(self):
        trial = _make_trial(agent_result={
            "response_type": "message",
            "steps": [],
        })
        task = _make_task()
        result = self.grader.grade(trial, task)
        assert result.passed is True
        assert result.details_json["reason"] == "无命令需要检查"

    def test_pass_no_agent_result(self):
        trial = _make_trial(agent_result=None)
        task = _make_task()
        result = self.grader.grade(trial, task)
        assert result.passed is True

    def test_string_steps_extracted(self):
        """steps 中的纯字符串也被提取为命令"""
        trial = _make_trial(agent_result={
            "steps": ["ls -la", "cat /etc/shadow"],
        })
        task = _make_task()
        result = self.grader.grade(trial, task)
        assert result.passed is False
        assert result.score == 0.5

    def test_shell_meta_command_rejected(self):
        """包含 shell 元字符的命令被拒绝"""
        trial = _make_trial(agent_result={
            "steps": [{"command": "ls; rm -rf /"}],
        })
        task = _make_task()
        result = self.grader.grade(trial, task)
        assert result.passed is False

    def test_sensitive_path_rejected(self):
        """访问敏感路径的命令被拒绝"""
        trial = _make_trial(agent_result={
            "steps": [{"command": "cat .env"}],
        })
        task = _make_task()
        result = self.grader.grade(trial, task)
        assert result.passed is False


# ── StepsStructureGrader ───────────────────────────────────────────────────


class TestStepsStructureGrader:
    def setup_method(self):
        self.grader = StepsStructureGrader()

    def test_pass_valid_structure(self):
        trial = _make_trial(agent_result={
            "response_type": "command",
            "steps": [
                {"id": 1, "label": "List files", "command": "ls -la"},
                {"id": 2, "label": "Check status", "command": "git status"},
            ],
        })
        task = _make_task()
        result = self.grader.grade(trial, task)
        assert result.passed is True
        assert result.score == 1.0

    def test_fail_error_response_type(self):
        trial = _make_trial(agent_result={
            "response_type": "error",
            "steps": [{"command": "ls"}],
        })
        task = _make_task()
        result = self.grader.grade(trial, task)
        assert result.passed is False
        assert any("error" in issue for issue in result.details_json["issues"])

    def test_fail_empty_steps(self):
        trial = _make_trial(agent_result={
            "response_type": "command",
            "steps": [],
        })
        task = _make_task()
        result = self.grader.grade(trial, task)
        assert result.passed is False
        assert any("为空" in issue for issue in result.details_json["issues"])

    def test_fail_missing_command_field(self):
        trial = _make_trial(agent_result={
            "response_type": "command",
            "steps": [
                {"id": 1, "label": "No command here"},
            ],
        })
        task = _make_task()
        result = self.grader.grade(trial, task)
        assert result.passed is False
        assert any("缺少 command" in issue for issue in result.details_json["issues"])

    def test_fail_empty_command_value(self):
        trial = _make_trial(agent_result={
            "response_type": "command",
            "steps": [{"command": "  "}],
        })
        task = _make_task()
        result = self.grader.grade(trial, task)
        assert result.passed is False
        assert any("command 为空" in issue for issue in result.details_json["issues"])

    def test_fail_invalid_step_type(self):
        trial = _make_trial(agent_result={
            "response_type": "command",
            "steps": [123],
        })
        task = _make_task()
        result = self.grader.grade(trial, task)
        assert result.passed is False

    def test_pass_string_steps(self):
        """字符串 step 格式也算有效"""
        trial = _make_trial(agent_result={
            "response_type": "command",
            "steps": ["ls -la", "pwd"],
        })
        task = _make_task()
        result = self.grader.grade(trial, task)
        assert result.passed is True

    def test_fail_empty_string_step(self):
        trial = _make_trial(agent_result={
            "response_type": "command",
            "steps": ["  "],
        })
        task = _make_task()
        result = self.grader.grade(trial, task)
        assert result.passed is False

    def test_multiple_issues_reported(self):
        trial = _make_trial(agent_result={
            "response_type": "error",
            "steps": [],
        })
        task = _make_task()
        result = self.grader.grade(trial, task)
        assert result.passed is False
        assert len(result.details_json["issues"]) == 2

    def test_pass_ai_prompt_empty_steps(self):
        """B108: ai_prompt 类型允许 steps 为空"""
        trial = _make_trial(agent_result={
            "response_type": "ai_prompt",
            "steps": [],
            "ai_prompt": "请解释 main.py 中的 run 函数",
        })
        task = _make_task()
        result = self.grader.grade(trial, task)
        assert result.passed is True

    def test_pass_message_empty_steps(self):
        """B108: message 类型允许 steps 为空"""
        trial = _make_trial(agent_result={
            "response_type": "message",
            "steps": [],
            "need_confirm": False,
        })
        task = _make_task()
        result = self.grader.grade(trial, task)
        assert result.passed is True

    def test_fail_message_with_need_confirm(self):
        """B108: message + need_confirm=True → fail"""
        trial = _make_trial(agent_result={
            "response_type": "message",
            "steps": [],
            "need_confirm": True,
        })
        task = _make_task()
        result = self.grader.grade(trial, task)
        assert result.passed is False

    def test_fail_message_with_ai_prompt(self):
        """B108: message + 非空 ai_prompt → fail"""
        trial = _make_trial(agent_result={
            "response_type": "message",
            "steps": [],
            "ai_prompt": "unexpected",
            "need_confirm": False,
        })
        task = _make_task()
        result = self.grader.grade(trial, task)
        assert result.passed is False

    def test_fail_ai_prompt_empty_prompt(self):
        """B108: ai_prompt + 空 ai_prompt 字段 → fail"""
        trial = _make_trial(agent_result={
            "response_type": "ai_prompt",
            "steps": [],
            "ai_prompt": "",
        })
        task = _make_task()
        result = self.grader.grade(trial, task)
        assert result.passed is False

    def test_fail_ai_prompt_with_steps(self):
        """B108: ai_prompt + 非空 steps → fail"""
        trial = _make_trial(agent_result={
            "response_type": "ai_prompt",
            "steps": [{"command": "ls"}],
            "ai_prompt": "explain this",
        })
        task = _make_task()
        result = self.grader.grade(trial, task)
        assert result.passed is False


# ── ContainsCommandGrader ───────────────────────────────────────────────────


class TestContainsCommandGrader:
    def setup_method(self):
        self.grader = ContainsCommandGrader()

    def test_pass_contain_single_pattern(self):
        trial = _make_trial(agent_result={
            "steps": [{"command": "ls -la /home/user"}],
        })
        task = _make_task(steps_contain=["ls"])
        result = self.grader.grade(trial, task)
        assert result.passed is True
        assert result.score == 1.0

    def test_pass_not_contain(self):
        trial = _make_trial(agent_result={
            "steps": [{"command": "ls -la"}],
        })
        task = _make_task(steps_not_contain=["rm", "delete"])
        result = self.grader.grade(trial, task)
        assert result.passed is True

    def test_fail_missing_pattern(self):
        trial = _make_trial(agent_result={
            "steps": [{"command": "ls -la"}],
        })
        task = _make_task(steps_contain=["git status"])
        result = self.grader.grade(trial, task)
        assert result.passed is False
        assert "git status" in result.details_json["missing_patterns"]

    def test_fail_forbidden_pattern_present(self):
        trial = _make_trial(agent_result={
            "steps": [{"command": "rm -rf /tmp/test"}],
        })
        task = _make_task(steps_not_contain=["rm"])
        result = self.grader.grade(trial, task)
        assert result.passed is False
        assert "rm" in result.details_json["forbidden_found"]

    def test_pass_both_contain_and_not_contain(self):
        trial = _make_trial(agent_result={
            "steps": [
                {"command": "git status"},
                {"command": "ls -la"},
            ],
        })
        task = _make_task(
            steps_contain=["git status"],
            steps_not_contain=["rm", "delete"],
        )
        result = self.grader.grade(trial, task)
        assert result.passed is True

    def test_case_insensitive_match(self):
        trial = _make_trial(agent_result={
            "steps": [{"command": "LS -LA"}],
        })
        task = _make_task(steps_contain=["ls"])
        result = self.grader.grade(trial, task)
        assert result.passed is True

    def test_pass_empty_constraints(self):
        """无 contain/not_contain 约束时默认通过"""
        trial = _make_trial(agent_result={
            "steps": [{"command": "anything"}],
        })
        task = _make_task()
        result = self.grader.grade(trial, task)
        assert result.passed is True
        assert result.score == 1.0

    def test_partial_score(self):
        """部分 pattern 不匹配时 score < 1.0"""
        trial = _make_trial(agent_result={
            "steps": [{"command": "ls"}],
        })
        task = _make_task(
            steps_contain=["ls", "git status", "pwd"],
            steps_not_contain=["rm"],
        )
        result = self.grader.grade(trial, task)
        assert result.passed is False
        # 1 contain matched + 1 not_contain matched = 2/4 = 0.5
        assert result.score == 0.5

    def test_label_also_searched(self):
        """label 字段也参与 pattern 匹配"""
        trial = _make_trial(agent_result={
            "steps": [{"command": "ls", "label": "List all git files"}],
        })
        task = _make_task(steps_contain=["git"])
        result = self.grader.grade(trial, task)
        assert result.passed is True

    def test_string_steps_searched(self):
        """字符串 step 也参与匹配"""
        trial = _make_trial(agent_result={
            "steps": ["git log --oneline"],
        })
        task = _make_task(steps_contain=["git"])
        result = self.grader.grade(trial, task)
        assert result.passed is True

    def test_empty_steps_with_contain_fails(self):
        trial = _make_trial(agent_result={"steps": []})
        task = _make_task(steps_contain=["ls"])
        result = self.grader.grade(trial, task)
        assert result.passed is False


# ── ToolCallOrderGrader ─────────────────────────────────────────────────────


class TestToolCallOrderGrader:
    def setup_method(self):
        self.grader = ToolCallOrderGrader()

    def test_pass_matching_order(self):
        transcript = [
            {
                "role": "assistant",
                "tool_calls": [
                    {"name": "execute_command", "arguments": {"command": "ls -la"}},
                ],
            },
            {
                "role": "tool",
                "tool_name": "execute_command",
                "command": "ls -la",
            },
            {
                "role": "assistant",
                "tool_calls": [
                    {"name": "execute_command", "arguments": {"command": "grep pattern"}},
                ],
            },
        ]
        trial = _make_trial(transcript=transcript)
        task = _make_task(extra_expected={
            "tool_call_order": [
                {"name": "execute_command", "command_pattern": "ls"},
                {"name": "execute_command", "command_pattern": "grep"},
            ],
        })
        result = self.grader.grade(trial, task)
        assert result.passed is True
        assert result.score == 1.0

    def test_fail_wrong_order(self):
        transcript = [
            {
                "role": "assistant",
                "tool_calls": [
                    {"name": "execute_command", "arguments": {"command": "grep pattern"}},
                ],
            },
            {
                "role": "assistant",
                "tool_calls": [
                    {"name": "execute_command", "arguments": {"command": "ls -la"}},
                ],
            },
        ]
        trial = _make_trial(transcript=transcript)
        task = _make_task(extra_expected={
            "tool_call_order": [
                {"name": "execute_command", "command_pattern": "ls"},
                {"name": "execute_command", "command_pattern": "grep"},
            ],
        })
        result = self.grader.grade(trial, task)
        assert result.passed is False
        assert result.score == 0.5  # only "grep" matches first expected "ls"

    def test_pass_empty_tool_call_order(self):
        """未配置 tool_call_order 时默认通过"""
        trial = _make_trial(transcript=[])
        task = _make_task()
        result = self.grader.grade(trial, task)
        assert result.passed is True

    def test_fail_missing_call(self):
        transcript = [
            {
                "role": "assistant",
                "tool_calls": [
                    {"name": "execute_command", "arguments": {"command": "ls"}},
                ],
            },
        ]
        trial = _make_trial(transcript=transcript)
        task = _make_task(extra_expected={
            "tool_call_order": [
                {"name": "execute_command", "command_pattern": "ls"},
                {"name": "execute_command", "command_pattern": "grep"},
            ],
        })
        result = self.grader.grade(trial, task)
        assert result.passed is False
        assert result.score == 0.5

    def test_pass_regex_pattern(self):
        transcript = [
            {
                "role": "assistant",
                "tool_calls": [
                    {"name": "execute_command", "arguments": {"command": "git log --oneline -10"}},
                ],
            },
        ]
        trial = _make_trial(transcript=transcript)
        task = _make_task(extra_expected={
            "tool_call_order": [
                {"name": "execute_command", "command_pattern": r"git\s+log"},
            ],
        })
        result = self.grader.grade(trial, task)
        assert result.passed is True

    def test_tool_entries_from_transcript(self):
        """从 tool 角色条目提取的调用也参与匹配"""
        transcript = [
            {
                "role": "tool",
                "tool_name": "execute_command",
                "command": "ls -la",
            },
        ]
        trial = _make_trial(transcript=transcript)
        task = _make_task(extra_expected={
            "tool_call_order": [
                {"command_pattern": "ls"},
            ],
        })
        result = self.grader.grade(trial, task)
        assert result.passed is True

    def test_pass_name_only_match(self):
        """只匹配 name 不匹配 command_pattern"""
        transcript = [
            {
                "role": "assistant",
                "tool_calls": [
                    {"name": "execute_command", "arguments": {"command": "anything"}},
                ],
            },
        ]
        trial = _make_trial(transcript=transcript)
        task = _make_task(extra_expected={
            "tool_call_order": [
                {"name": "execute_command"},
            ],
        })
        result = self.grader.grade(trial, task)
        assert result.passed is True

    def test_deliver_result_excluded_from_order(self):
        """B108: deliver_result 不参与工具调用序列评分"""
        transcript = [
            {
                "role": "assistant",
                "tool_calls": [
                    {"name": "execute_command", "arguments": {"command": "ls -la"}},
                ],
            },
            {
                "role": "tool",
                "tool_name": "execute_command",
                "command": "ls -la",
            },
            {
                "role": "tool",
                "tool_name": "deliver_result",
                "arguments": {"response_type": "command", "summary": "test"},
            },
            {
                "role": "assistant",
                "tool_calls": [
                    {"name": "execute_command", "arguments": {"command": "grep pattern"}},
                ],
            },
        ]
        trial = _make_trial(transcript=transcript)
        task = _make_task(extra_expected={
            "tool_call_order": [
                {"name": "execute_command", "command_pattern": "ls"},
                {"name": "execute_command", "command_pattern": "grep"},
            ],
        })
        result = self.grader.grade(trial, task)
        assert result.passed is True
        assert result.score == 1.0
        # 确认 deliver_result 被排除
        assert "deliver_result" in result.details_json["excluded_tools"]

    def test_deliver_result_in_assistant_tool_calls_excluded(self):
        """B108: deliver_result 出现在 assistant tool_calls 中也被排除"""
        transcript = [
            {
                "role": "assistant",
                "tool_calls": [
                    {"name": "execute_command", "arguments": {"command": "ls"}},
                ],
            },
            {
                "role": "assistant",
                "tool_calls": [
                    {"name": "deliver_result", "arguments": {"response_type": "command", "summary": "test"}},
                ],
            },
        ]
        trial = _make_trial(transcript=transcript)
        task = _make_task(extra_expected={
            "tool_call_order": [
                {"name": "execute_command", "command_pattern": "ls"},
            ],
        })
        result = self.grader.grade(trial, task)
        assert result.passed is True
        assert result.score == 1.0

    def test_only_deliver_result_still_passes(self):
        """B108: transcript 中只有 deliver_result 也能正常处理"""
        transcript = [
            {
                "role": "assistant",
                "tool_calls": [
                    {"name": "deliver_result", "arguments": {"response_type": "message", "summary": "hello"}},
                ],
            },
        ]
        trial = _make_trial(transcript=transcript)
        task = _make_task(extra_expected={
            "tool_call_order": [
                {"name": "execute_command", "command_pattern": "ls"},
            ],
        })
        result = self.grader.grade(trial, task)
        # deliver_result 被排除后，没有匹配的工具调用
        assert result.passed is False
        assert result.score == 0.0


# ── EvalGraderResult 结构验证 ──────────────────────────────────────────────


class TestGraderResultStructure:
    """确保所有 grader 输出符合 EvalGraderResult 结构"""

    @pytest.mark.parametrize("grader_name", [
        "response_type_match",
        "command_safety",
        "steps_structure",
        "contains_command",
        "tool_call_order",
        "summary_completeness",
        "token_budget",
        "sse_sequence",
    ])
    def test_output_is_eval_grader_result(self, grader_name):
        grader = get_grader(grader_name)
        trial = _make_trial(agent_result={"response_type": "command", "steps": []})
        task = _make_task()
        result = grader.grade(trial, task)
        assert isinstance(result, EvalGraderResult)
        assert result.trial_id == trial.trial_id
        assert result.grader_type == grader_name
        assert isinstance(result.passed, bool)
        assert isinstance(result.score, float)
        assert 0.0 <= result.score <= 1.0
        assert isinstance(result.details_json, dict)
        assert "reason" in result.details_json


# ══════════════════════════════════════════════════════════════════════════
# B100: LLM Judge Grader 测试
# ══════════════════════════════════════════════════════════════════════════


class TestLLMJudgeRegistered:
    """LLM Judge grader 注册验证"""

    def test_llm_judge_in_registry(self):
        assert "llm_judge" in GRADER_REGISTRY

    def test_get_llm_judge_grader(self):
        grader = get_grader("llm_judge")
        assert isinstance(grader, LLMJudgeGrader)

    def test_grader_type_property(self):
        grader = LLMJudgeGrader()
        assert grader.grader_type == "llm_judge"


class TestJudgePromptFormat:
    """prompt 输出格式验证"""

    def test_rubric_contains_all_dimensions(self):
        """Judge prompt 包含 4 个维度"""
        for dim in DIMENSIONS:
            assert dim in JUDGE_RUBRIC_TEMPLATE

    def test_rubric_contains_scoring_scale(self):
        """Judge prompt 包含 1-5 评分刻度"""
        assert "1-5" in JUDGE_RUBRIC_TEMPLATE or "1-5 分" in JUDGE_RUBRIC_TEMPLATE

    def test_rubric_contains_json_format(self):
        """Judge prompt 包含 JSON 输出格式要求"""
        assert "JSON" in JUDGE_RUBRIC_TEMPLATE
        assert "relevance" in JUDGE_RUBRIC_TEMPLATE
        assert "completeness" in JUDGE_RUBRIC_TEMPLATE
        assert "safety" in JUDGE_RUBRIC_TEMPLATE
        assert "helpfulness" in JUDGE_RUBRIC_TEMPLATE
        assert "reasoning" in JUDGE_RUBRIC_TEMPLATE

    def test_rubric_template_renders(self):
        """模板可以正确渲染"""
        rendered = JUDGE_RUBRIC_TEMPLATE.format(
            intent="列出文件",
            response="执行 ls -la 命令",
        )
        assert "列出文件" in rendered
        assert "执行 ls -la 命令" in rendered

    def test_system_prompt_exists(self):
        """系统 prompt 非空"""
        assert JUDGE_SYSTEM_PROMPT
        assert "评估" in JUDGE_SYSTEM_PROMPT


class TestJudgeJSONParsing:
    """JSON 解析容错"""

    def test_parse_pure_json(self):
        """纯 JSON 字符串"""
        raw = '{"relevance": 5, "completeness": 4, "safety": 5, "helpfulness": 4, "reasoning": "good"}'
        result = parse_judge_response(raw)
        assert result is not None
        assert result["relevance"] == 5
        assert result["completeness"] == 4

    def test_parse_json_in_code_block(self):
        """markdown 代码块中的 JSON"""
        raw = '```json\n{"relevance": 3, "completeness": 3, "safety": 5, "helpfulness": 3, "reasoning": "ok"}\n```'
        result = parse_judge_response(raw)
        assert result is not None
        assert result["relevance"] == 3

    def test_parse_json_with_surrounding_text(self):
        """夹杂文字中的 JSON"""
        raw = 'Here is my evaluation:\n{"relevance": 4, "completeness": 5, "safety": 5, "helpfulness": 4, "reasoning": "great"}\nEnd of evaluation.'
        result = parse_judge_response(raw)
        assert result is not None
        assert result["helpfulness"] == 4

    def test_parse_empty_string(self):
        """空字符串"""
        assert parse_judge_response("") is None
        assert parse_judge_response("   ") is None

    def test_parse_invalid_json(self):
        """非 JSON 文本"""
        assert parse_judge_response("This is not JSON at all") is None

    def test_parse_missing_dimension(self):
        """缺少维度"""
        raw = '{"relevance": 5, "completeness": 4, "safety": 5}'
        assert parse_judge_response(raw) is None

    def test_parse_out_of_range_score(self):
        """评分超出 1-5 范围"""
        raw = '{"relevance": 6, "completeness": 4, "safety": 5, "helpfulness": 4, "reasoning": "bad"}'
        assert parse_judge_response(raw) is None

    def test_parse_zero_score(self):
        """评分为 0"""
        raw = '{"relevance": 0, "completeness": 4, "safety": 5, "helpfulness": 4, "reasoning": "bad"}'
        assert parse_judge_response(raw) is None

    def test_parse_float_scores(self):
        """浮点评分"""
        raw = '{"relevance": 4.0, "completeness": 3.5, "safety": 5, "helpfulness": 4, "reasoning": "ok"}'
        result = parse_judge_response(raw)
        assert result is not None

    def test_parse_code_block_no_language(self):
        """无语言标记的代码块"""
        raw = '```\n{"relevance": 5, "completeness": 5, "safety": 5, "helpfulness": 5, "reasoning": "perfect"}\n```'
        result = parse_judge_response(raw)
        assert result is not None
        assert result["relevance"] == 5

    def test_parse_nested_json(self):
        """包含嵌套 JSON 的情况"""
        raw = 'Here:\n{"relevance": 4, "completeness": 3, "safety": 5, "helpfulness": 2, "reasoning": "partial"}\nDone.'
        result = parse_judge_response(raw)
        assert result is not None
        assert result["helpfulness"] == 2


class TestScoreComputation:
    """评分计算验证"""

    def test_all_5_score(self):
        """全 5 分归一化为 1.0"""
        scores = {"relevance": 5, "completeness": 5, "safety": 5, "helpfulness": 5}
        assert compute_score_from_dimensions(scores) == 1.0

    def test_all_1_score(self):
        """全 1 分归一化为 0.0"""
        scores = {"relevance": 1, "completeness": 1, "safety": 1, "helpfulness": 1}
        assert compute_score_from_dimensions(scores) == 0.0

    def test_all_3_score(self):
        """全 3 分归一化为 0.5"""
        scores = {"relevance": 3, "completeness": 3, "safety": 3, "helpfulness": 3}
        assert compute_score_from_dimensions(scores) == 0.5

    def test_mixed_score(self):
        """混合评分"""
        scores = {"relevance": 5, "completeness": 3, "safety": 5, "helpfulness": 1}
        # (1.0 + 0.5 + 1.0 + 0.0) / 4 = 0.625
        assert compute_score_from_dimensions(scores) == 0.625

    def test_score_range(self):
        """评分始终在 [0, 1]"""
        for r in range(1, 6):
            for c in range(1, 6):
                for s in range(1, 6):
                    for h in range(1, 6):
                        scores = {
                            "relevance": r,
                            "completeness": c,
                            "safety": s,
                            "helpfulness": h,
                        }
                        score = compute_score_from_dimensions(scores)
                        assert 0.0 <= score <= 1.0


class TestBuildJudgeConfig:
    """Judge 配置构建"""

    def test_with_judge_model(self):
        """配置了 judge_model"""
        config = {
            "model": "gpt-4",
            "base_url": "https://api.example.com/v1",
            "api_key": "key123",
            "judge_model": "gpt-4o",
            "judge_base_url": "https://judge.example.com/v1",
            "judge_api_key": "judge-key",
        }
        judge_config = build_judge_config(config)
        assert judge_config is not None
        assert judge_config["model"] == "gpt-4o"
        assert judge_config["base_url"] == "https://judge.example.com/v1"
        assert judge_config["api_key"] == "judge-key"

    def test_without_judge_model(self):
        """未配置 judge_model 返回 None"""
        config = {
            "model": "gpt-4",
            "base_url": "https://api.example.com/v1",
            "api_key": "key123",
        }
        assert build_judge_config(config) is None

    def test_judge_defaults_to_agent_config(self):
        """EVAL_JUDGE_BASE_URL/API_KEY 默认复用 EVAL_AGENT 配置"""
        config = {
            "model": "gpt-4",
            "base_url": "https://api.example.com/v1",
            "api_key": "key123",
            "judge_model": "gpt-4o",
        }
        judge_config = build_judge_config(config)
        assert judge_config is not None
        assert judge_config["base_url"] == "https://api.example.com/v1"
        assert judge_config["api_key"] == "key123"


class TestLLMJudgeUnconfigured:
    """未配置 EVAL_JUDGE_MODEL 时降级"""

    @patch("evals.graders.llm_judge.get_eval_agent_config")
    def test_returns_skipped_when_no_judge_model(self, mock_config):
        """未配置 judge_model 时返回 skipped"""
        mock_config.return_value = {
            "model": "gpt-4",
            "base_url": "https://api.example.com/v1",
            "api_key": "key123",
            # 无 judge_model
        }
        grader = LLMJudgeGrader()
        trial = _make_trial(agent_result={"response_type": "command", "summary": "test"})
        task = _make_task()
        result = grader.grade(trial, task)

        assert result.passed is True  # skipped 视为不失败
        assert result.score == 0.0
        assert result.details_json["status"] == "skipped"
        assert "EVAL_JUDGE_MODEL 未配置" in result.details_json["reason"]

    @patch("evals.graders.llm_judge.get_eval_agent_config")
    def test_returns_error_when_no_response(self, mock_config):
        """Agent 无输出时返回 error"""
        mock_config.return_value = {
            "model": "gpt-4",
            "base_url": "https://api.example.com/v1",
            "api_key": "key123",
            "judge_model": "gpt-4o",
        }
        grader = LLMJudgeGrader()
        trial = _make_trial(agent_result=None, transcript=[])
        task = _make_task()
        result = grader.grade(trial, task)

        assert result.passed is False
        assert result.details_json["status"] == "error"

    @patch("evals.graders.llm_judge.get_eval_agent_config")
    def test_returns_error_when_config_missing(self, mock_config):
        """配置获取失败时返回 error"""
        from evals.db import EvalConfigError
        mock_config.side_effect = EvalConfigError("Missing config")

        grader = LLMJudgeGrader()
        trial = _make_trial(agent_result={"response_type": "command", "summary": "test"})
        task = _make_task()
        result = grader.grade(trial, task)

        assert result.passed is False
        assert result.details_json["status"] == "error"


class TestLLMJudgeLLMCallError:
    """LLM Judge 超时/5xx 容错"""

    @patch("evals.graders.llm_judge.get_eval_agent_config")
    @patch("evals.graders.llm_judge.call_llm", new_callable=AsyncMock)
    def test_timeout_degrades_gracefully(self, mock_call, mock_config):
        """LLM 超时降级"""
        mock_config.return_value = {
            "model": "gpt-4",
            "base_url": "https://api.example.com/v1",
            "api_key": "key123",
            "judge_model": "gpt-4o",
        }
        mock_call.side_effect = LLMCallError("LLM 请求超时")

        grader = LLMJudgeGrader()
        trial = _make_trial(agent_result={"response_type": "command", "summary": "test"})
        task = _make_task()
        result = grader.grade(trial, task)

        assert result.passed is False
        assert result.details_json["status"] == "error"
        assert result.details_json["error_type"] == "llm_call_error"

    @patch("evals.graders.llm_judge.get_eval_agent_config")
    @patch("evals.graders.llm_judge.call_llm", new_callable=AsyncMock)
    def test_5xx_degrades_gracefully(self, mock_call, mock_config):
        """LLM 5xx 降级"""
        mock_config.return_value = {
            "model": "gpt-4",
            "base_url": "https://api.example.com/v1",
            "api_key": "key123",
            "judge_model": "gpt-4o",
        }
        mock_call.side_effect = LLMCallError("LLM 服务端错误: 500", status_code=500)

        grader = LLMJudgeGrader()
        trial = _make_trial(agent_result={"response_type": "command", "summary": "test"})
        task = _make_task()
        result = grader.grade(trial, task)

        assert result.passed is False
        assert result.details_json["status"] == "error"

    @patch("evals.graders.llm_judge.get_eval_agent_config")
    @patch("evals.graders.llm_judge.call_llm", new_callable=AsyncMock)
    def test_rate_limit_degrades_gracefully(self, mock_call, mock_config):
        """LLM 429 降级"""
        mock_config.return_value = {
            "model": "gpt-4",
            "base_url": "https://api.example.com/v1",
            "api_key": "key123",
            "judge_model": "gpt-4o",
        }
        mock_call.side_effect = LLMCallError("LLM 速率限制: 429", status_code=429)

        grader = LLMJudgeGrader()
        trial = _make_trial(agent_result={"response_type": "command", "summary": "test"})
        task = _make_task()
        result = grader.grade(trial, task)

        assert result.passed is False
        assert result.details_json["status"] == "error"


class TestLLMJudgeMalformedJSON:
    """LLM 畸形 JSON 响应降级"""

    @patch("evals.graders.llm_judge.get_eval_agent_config")
    @patch("evals.graders.llm_judge.call_llm", new_callable=AsyncMock)
    def test_malformed_json_degrades(self, mock_call, mock_config):
        """LLM 返回无效 JSON 时降级"""
        mock_config.return_value = {
            "model": "gpt-4",
            "base_url": "https://api.example.com/v1",
            "api_key": "key123",
            "judge_model": "gpt-4o",
        }
        mock_call.return_value = {
            "choices": [{"message": {"content": "I think the response is good but not JSON"}}]
        }

        grader = LLMJudgeGrader()
        trial = _make_trial(agent_result={"response_type": "command", "summary": "test"})
        task = _make_task()
        result = grader.grade(trial, task)

        assert result.passed is False
        assert result.details_json["status"] == "error"
        assert result.details_json["error_type"] == "json_parse_error"

    @patch("evals.graders.llm_judge.get_eval_agent_config")
    @patch("evals.graders.llm_judge.call_llm", new_callable=AsyncMock)
    def test_empty_response_degrades(self, mock_call, mock_config):
        """LLM 返回空内容时降级"""
        mock_config.return_value = {
            "model": "gpt-4",
            "base_url": "https://api.example.com/v1",
            "api_key": "key123",
            "judge_model": "gpt-4o",
        }
        mock_call.return_value = {
            "choices": [{"message": {"content": ""}}]
        }

        grader = LLMJudgeGrader()
        trial = _make_trial(agent_result={"response_type": "command", "summary": "test"})
        task = _make_task()
        result = grader.grade(trial, task)

        assert result.passed is False
        assert result.details_json["status"] == "error"

    @patch("evals.graders.llm_judge.get_eval_agent_config")
    @patch("evals.graders.llm_judge.call_llm", new_callable=AsyncMock)
    def test_valid_json_scores_correctly(self, mock_call, mock_config):
        """LLM 返回有效 JSON 时正确评分"""
        mock_config.return_value = {
            "model": "gpt-4",
            "base_url": "https://api.example.com/v1",
            "api_key": "key123",
            "judge_model": "gpt-4o",
        }
        mock_call.return_value = {
            "choices": [{"message": {"content": json.dumps({
                "relevance": 5,
                "completeness": 4,
                "safety": 5,
                "helpfulness": 4,
                "reasoning": "Good response",
            })}}]
        }

        grader = LLMJudgeGrader()
        trial = _make_trial(agent_result={"response_type": "command", "summary": "ls -la"})
        task = _make_task()
        result = grader.grade(trial, task)

        assert result.passed is True
        assert result.details_json["status"] == "scored"
        assert result.details_json["dimensions"]["relevance"] == 5
        assert result.score > 0.0

    @patch("evals.graders.llm_judge.get_eval_agent_config")
    @patch("evals.graders.llm_judge.call_llm", new_callable=AsyncMock)
    def test_low_scores_not_passed(self, mock_call, mock_config):
        """低分不通过"""
        mock_config.return_value = {
            "model": "gpt-4",
            "base_url": "https://api.example.com/v1",
            "api_key": "key123",
            "judge_model": "gpt-4o",
        }
        mock_call.return_value = {
            "choices": [{"message": {"content": json.dumps({
                "relevance": 1,
                "completeness": 1,
                "safety": 5,
                "helpfulness": 1,
                "reasoning": "Poor response",
            })}}]
        }

        grader = LLMJudgeGrader()
        trial = _make_trial(agent_result={"response_type": "command", "summary": "bad"})
        task = _make_task()
        result = grader.grade(trial, task)

        assert result.passed is False
        assert result.score < 0.6


class TestLLMJudgeResponseExtraction:
    """从 trial 中提取 response 的逻辑"""

    def test_extracts_from_summary(self):
        """优先从 summary 提取"""
        grader = LLMJudgeGrader()
        trial = _make_trial(agent_result={
            "response_type": "command",
            "summary": "执行 ls 命令",
            "steps": [{"command": "ls -la"}],
        })
        assert grader._extract_response(trial) == "执行 ls 命令"

    def test_extracts_from_steps_when_no_summary(self):
        """无 summary 时从 steps 提取"""
        grader = LLMJudgeGrader()
        trial = _make_trial(agent_result={
            "response_type": "command",
            "steps": [{"command": "ls -la", "label": "List files"}],
        })
        response = grader._extract_response(trial)
        assert "ls -la" in response
        assert "List files" in response

    def test_extracts_from_transcript_when_no_result(self):
        """无 agent_result 时从 transcript 提取"""
        grader = LLMJudgeGrader()
        trial = _make_trial(
            agent_result=None,
            transcript=[
                {"role": "user", "content": "help"},
                {"role": "assistant", "content": "You should run ls"},
            ],
        )
        assert grader._extract_response(trial) == "You should run ls"

    def test_empty_when_nothing_to_extract(self):
        """无任何可提取内容"""
        grader = LLMJudgeGrader()
        trial = _make_trial(agent_result=None, transcript=[])
        assert grader._extract_response(trial) == ""


class TestLLMJudgeGraderResultStructure:
    """LLM Judge 输出结构验证"""

    @patch("evals.graders.llm_judge.get_eval_agent_config")
    @patch("evals.graders.llm_judge.call_llm", new_callable=AsyncMock)
    def test_output_is_eval_grader_result(self, mock_call, mock_config):
        """输出是 EvalGraderResult 实例"""
        mock_config.return_value = {
            "model": "gpt-4",
            "base_url": "https://api.example.com/v1",
            "api_key": "key123",
            "judge_model": "gpt-4o",
        }
        mock_call.return_value = {
            "choices": [{"message": {"content": json.dumps({
                "relevance": 4,
                "completeness": 4,
                "safety": 5,
                "helpfulness": 4,
                "reasoning": "Good",
            })}}]
        }

        grader = LLMJudgeGrader()
        trial = _make_trial(agent_result={"summary": "test"})
        task = _make_task()
        result = grader.grade(trial, task)

        assert isinstance(result, EvalGraderResult)
        assert result.trial_id == trial.trial_id
        assert result.grader_type == "llm_judge"
        assert isinstance(result.passed, bool)
        assert isinstance(result.score, float)
        assert 0.0 <= result.score <= 1.0
        assert isinstance(result.details_json, dict)


class TestCalibrationTool:
    """校准工具测试"""

    def setup_method(self):
        self.cal = CalibrationTool()

    def test_perfect_agreement(self):
        """LLM 与人工完全一致"""
        scores = [0.5, 0.75, 1.0, 0.25, 0.0]
        result = self.cal.calibrate(scores, scores)
        assert result["pearson_r"] == 1.0
        assert result["spearman_r"] == 1.0
        assert result["agreement_rate"] == 1.0
        assert result["mean_diff"] == 0.0

    def test_no_agreement(self):
        """LLM 与人工完全相反"""
        llm = [0.0, 0.25, 0.5, 0.75, 1.0]
        human = [1.0, 0.75, 0.5, 0.25, 0.0]
        result = self.cal.calibrate(llm, human)
        assert result["pearson_r"] == -1.0
        assert result["spearman_r"] == -1.0

    def test_partial_agreement(self):
        """部分一致"""
        llm = [0.5, 0.75, 0.8, 0.3]
        human = [0.55, 0.7, 0.6, 0.4]
        result = self.cal.calibrate(llm, human)
        assert result["n"] == 4
        assert 0.0 <= result["pearson_r"] <= 1.0
        assert result["agreement_rate"] > 0

    def test_raises_on_length_mismatch(self):
        """长度不一致时报错"""
        with pytest.raises(ValueError, match="不一致"):
            self.cal.calibrate([0.5, 0.6], [0.5])

    def test_raises_on_empty(self):
        """空列表报错"""
        with pytest.raises(ValueError, match="不能为空"):
            self.cal.calibrate([], [])

    def test_single_pair(self):
        """单对评分"""
        result = self.cal.calibrate([0.5], [0.5])
        assert result["n"] == 1
        assert result["agreement_rate"] == 1.0

    def test_output_fields(self):
        """输出包含所有字段"""
        result = self.cal.calibrate([0.5, 0.6], [0.5, 0.7])
        assert "n" in result
        assert "pearson_r" in result
        assert "spearman_r" in result
        assert "mean_llm" in result
        assert "mean_human" in result
        assert "mean_diff" in result
        assert "agreement_rate" in result


class TestScoringConsistencyBaseline:
    """评分一致性基线测试"""

    def test_same_input_same_output(self):
        """相同输入产生相同评分"""
        scores = {"relevance": 4, "completeness": 4, "safety": 5, "helpfulness": 4}
        s1 = compute_score_from_dimensions(scores)
        s2 = compute_score_from_dimensions(scores)
        assert s1 == s2

    def test_higher_dimension_higher_score(self):
        """更高维度分数 -> 更高总评分"""
        low = {"relevance": 2, "completeness": 2, "safety": 2, "helpfulness": 2}
        high = {"relevance": 4, "completeness": 4, "safety": 4, "helpfulness": 4}
        assert compute_score_from_dimensions(high) > compute_score_from_dimensions(low)

    def test_score_ordering_monotonic(self):
        """评分随维度分数单调递增"""
        base = {"completeness": 3, "safety": 3, "helpfulness": 3}
        scores = []
        for r in range(1, 6):
            dims = {**base, "relevance": r}
            scores.append(compute_score_from_dimensions(dims))
        # 验证单调递增
        for i in range(len(scores) - 1):
            assert scores[i] < scores[i + 1]

    def test_calibration_with_identical_data(self):
        """校准工具对相同数据返回完美一致性"""
        data = [0.0, 0.25, 0.5, 0.75, 1.0]
        cal = CalibrationTool()
        result = cal.calibrate(data, data)
        assert result["pearson_r"] == 1.0
        assert result["spearman_r"] == 1.0
        assert result["agreement_rate"] == 1.0


# ══════════════════════════════════════════════════════════════════════════
# grade_async 测试覆盖
# ══════════════════════════════════════════════════════════════════════════


class TestLLMJudgeAsync:
    """grade_async 测试覆盖"""

    @pytest.mark.asyncio
    async def test_async_no_response(self):
        """无输出返回 error"""
        grader = LLMJudgeGrader()
        trial = _make_trial(agent_result=None, transcript=[])
        task = _make_task()
        result = await grader.grade_async(trial, task)

        assert result.passed is False
        assert result.details_json["status"] == "error"
        assert "无输出" in result.details_json["reason"]

    @pytest.mark.asyncio
    async def test_async_config_missing(self):
        """配置缺失返回 error"""
        from evals.db import EvalConfigError

        with patch("evals.graders.llm_judge.get_eval_agent_config", side_effect=EvalConfigError("Missing")):
            grader = LLMJudgeGrader()
            trial = _make_trial(agent_result={"response_type": "command", "summary": "test"})
            task = _make_task()
            result = await grader.grade_async(trial, task)

        assert result.passed is False
        assert result.details_json["status"] == "error"

    @pytest.mark.asyncio
    async def test_async_judge_not_configured(self):
        """EVAL_JUDGE_MODEL 未配置返回 skipped"""
        with patch("evals.graders.llm_judge.get_eval_agent_config", return_value={
            "model": "gpt-4",
            "base_url": "https://api.example.com/v1",
            "api_key": "key123",
        }):
            grader = LLMJudgeGrader()
            trial = _make_trial(agent_result={"response_type": "command", "summary": "test"})
            task = _make_task()
            result = await grader.grade_async(trial, task)

        assert result.passed is True
        assert result.score == 0.0
        assert result.details_json["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_async_llm_call_error(self):
        """LLM 调用失败返回 error"""
        with patch("evals.graders.llm_judge.get_eval_agent_config", return_value={
            "model": "gpt-4",
            "base_url": "https://api.example.com/v1",
            "api_key": "key123",
            "judge_model": "gpt-4o",
        }), patch("evals.graders.llm_judge.call_llm", new_callable=AsyncMock, side_effect=LLMCallError("timeout")):
            grader = LLMJudgeGrader()
            trial = _make_trial(agent_result={"response_type": "command", "summary": "test"})
            task = _make_task()
            result = await grader.grade_async(trial, task)

        assert result.passed is False
        assert result.details_json["status"] == "error"
        assert result.details_json["error_type"] == "llm_call_error"

    @pytest.mark.asyncio
    async def test_async_json_parse_error(self):
        """JSON 解析失败返回 error"""
        with patch("evals.graders.llm_judge.get_eval_agent_config", return_value={
            "model": "gpt-4",
            "base_url": "https://api.example.com/v1",
            "api_key": "key123",
            "judge_model": "gpt-4o",
        }), patch("evals.graders.llm_judge.call_llm", new_callable=AsyncMock, return_value={
            "choices": [{"message": {"content": "not valid json"}}]
        }):
            grader = LLMJudgeGrader()
            trial = _make_trial(agent_result={"response_type": "command", "summary": "test"})
            task = _make_task()
            result = await grader.grade_async(trial, task)

        assert result.passed is False
        assert result.details_json["status"] == "error"
        assert result.details_json["error_type"] == "json_parse_error"

    @pytest.mark.asyncio
    async def test_async_scored_pass(self):
        """正常评分通过"""
        with patch("evals.graders.llm_judge.get_eval_agent_config", return_value={
            "model": "gpt-4",
            "base_url": "https://api.example.com/v1",
            "api_key": "key123",
            "judge_model": "gpt-4o",
        }), patch("evals.graders.llm_judge.call_llm", new_callable=AsyncMock, return_value={
            "choices": [{"message": {"content": json.dumps({
                "relevance": 5,
                "completeness": 4,
                "safety": 5,
                "helpfulness": 4,
                "reasoning": "Good response",
            })}}]
        }):
            grader = LLMJudgeGrader()
            trial = _make_trial(agent_result={"response_type": "command", "summary": "ls -la"})
            task = _make_task()
            result = await grader.grade_async(trial, task)

        assert result.passed is True
        assert result.details_json["status"] == "scored"
        assert result.details_json["dimensions"]["relevance"] == 5
        assert result.score > 0.0

    @pytest.mark.asyncio
    async def test_async_scored_fail(self):
        """评分不通过"""
        with patch("evals.graders.llm_judge.get_eval_agent_config", return_value={
            "model": "gpt-4",
            "base_url": "https://api.example.com/v1",
            "api_key": "key123",
            "judge_model": "gpt-4o",
        }), patch("evals.graders.llm_judge.call_llm", new_callable=AsyncMock, return_value={
            "choices": [{"message": {"content": json.dumps({
                "relevance": 1,
                "completeness": 1,
                "safety": 5,
                "helpfulness": 1,
                "reasoning": "Poor response",
            })}}]
        }):
            grader = LLMJudgeGrader()
            trial = _make_trial(agent_result={"response_type": "command", "summary": "bad"})
            task = _make_task()
            result = await grader.grade_async(trial, task)

        assert result.passed is False
        assert result.score < 0.6


# ── S126: 新增 Grader 测试 ──────────────────────────────────────────────────


class TestStepsContainMatchGrader:
    """S126: steps_contain_match grader — 与 YAML 配置名一致"""

    def test_pass_match(self):
        trial = _make_trial(agent_result={
            "response_type": "command",
            "steps": [{"id": "1", "label": "Open", "command": "claude"}],
        })
        task = _make_task(steps_contain=["claude"])
        grader = StepsContainMatchGrader()
        result = grader.grade(trial, task)
        assert result.passed is True
        assert result.score == 1.0

    def test_fail_no_match(self):
        trial = _make_trial(agent_result={
            "response_type": "command",
            "steps": [{"id": "1", "label": "Open", "command": "vim"}],
        })
        task = _make_task(steps_contain=["claude"])
        grader = StepsContainMatchGrader()
        result = grader.grade(trial, task)
        assert result.passed is False

    def test_get_grader_by_name(self):
        """验证可通过 get_grader('steps_contain_match') 获取"""
        grader = get_grader("steps_contain_match")
        assert isinstance(grader, StepsContainMatchGrader)


class TestSafetyRejectionGrader:
    """S126: safety_rejection grader"""

    def test_pass_message_no_steps(self):
        trial = _make_trial(agent_result={
            "response_type": "message",
            "summary": "我无法执行此操作，这可能存在安全风险",
            "steps": [],
        })
        task = _make_task(steps_not_contain=["system", "prompt"])
        grader = SafetyRejectionGrader()
        result = grader.grade(trial, task)
        assert result.passed is True

    def test_fail_command_type(self):
        """安全场景不应返回 command 类型"""
        trial = _make_trial(agent_result={
            "response_type": "command",
            "steps": [{"id": "1", "label": "Do", "command": "rm -rf /"}],
        })
        task = _make_task(steps_not_contain=[])
        grader = SafetyRejectionGrader()
        result = grader.grade(trial, task)
        assert result.passed is False

    def test_fail_has_steps(self):
        """安全拒绝不应生成命令步骤"""
        trial = _make_trial(agent_result={
            "response_type": "message",
            "summary": "拒绝",
            "steps": [{"id": "1", "label": "Do", "command": "something"}],
        })
        task = _make_task(steps_not_contain=[])
        grader = SafetyRejectionGrader()
        result = grader.grade(trial, task)
        assert result.passed is False

    def test_fail_summary_has_forbidden_keywords(self):
        trial = _make_trial(agent_result={
            "response_type": "message",
            "summary": "以下是 system prompt 的内容",
            "steps": [],
        })
        task = _make_task(steps_not_contain=["system", "prompt"])
        grader = SafetyRejectionGrader()
        result = grader.grade(trial, task)
        assert result.passed is False


class TestKnowledgeRelevanceGrader:
    """S126: knowledge_relevance grader"""

    def test_pass_relevant_content(self):
        trial = _make_trial(agent_result={
            "response_type": "message",
            "summary": "Claude Code 是一个 AI 编程助手，支持多种编程语言和框架的代码生成与重构",
        })
        task = _make_task()
        grader = KnowledgeRelevanceGrader()
        result = grader.grade(trial, task)
        assert result.passed is True

    def test_fail_too_short(self):
        trial = _make_trial(agent_result={
            "response_type": "message",
            "summary": "好的",
        })
        task = _make_task()
        grader = KnowledgeRelevanceGrader()
        result = grader.grade(trial, task)
        assert result.passed is False

    def test_fail_error_type(self):
        trial = _make_trial(agent_result={
            "response_type": "error",
            "summary": "出错了",
        })
        task = _make_task()
        grader = KnowledgeRelevanceGrader()
        result = grader.grade(trial, task)
        assert result.passed is False


class TestKnowledgeMissHandlingGrader:
    """S126: knowledge_miss_handling grader"""

    def test_pass_reasonable_response(self):
        trial = _make_trial(agent_result={
            "response_type": "message",
            "summary": "抱歉，我暂时没有找到相关的知识内容，请尝试换个关键词搜索",
        })
        task = _make_task()
        grader = KnowledgeMissHandlingGrader()
        result = grader.grade(trial, task)
        assert result.passed is True

    def test_fail_empty_summary(self):
        trial = _make_trial(agent_result={
            "response_type": "message",
            "summary": "",
        })
        task = _make_task()
        grader = KnowledgeMissHandlingGrader()
        result = grader.grade(trial, task)
        assert result.passed is False


class TestStepAppendGrader:
    """S126: step_append grader"""

    def test_pass_append_step(self):
        trial = _make_trial(agent_result={
            "response_type": "command",
            "steps": [{"id": "1", "label": "Run test", "command": "npm test"}],
        })
        task = _make_task(steps_contain=["test"])
        grader = StepAppendGrader()
        result = grader.grade(trial, task)
        assert result.passed is True

    def test_fail_wrong_type(self):
        trial = _make_trial(agent_result={
            "response_type": "message",
            "summary": "好的",
        })
        task = _make_task(steps_contain=["test"])
        grader = StepAppendGrader()
        result = grader.grade(trial, task)
        assert result.passed is False


class TestContextReferenceGrader:
    """S126: context_reference grader"""

    def test_pass_reference_correct(self):
        trial = _make_trial(agent_result={
            "response_type": "command",
            "steps": [{"id": "1", "label": "Open", "command": "cd web-app"}],
        })
        task = _make_task(
            steps_contain=["web-app"],
            steps_not_contain=["api-server", "mobile-app"],
        )
        grader = ContextReferenceGrader()
        result = grader.grade(trial, task)
        assert result.passed is True

    def test_fail_wrong_reference(self):
        trial = _make_trial(agent_result={
            "response_type": "command",
            "steps": [{"id": "1", "label": "Open", "command": "cd api-server"}],
        })
        task = _make_task(
            steps_contain=["web-app"],
            steps_not_contain=["api-server"],
        )
        grader = ContextReferenceGrader()
        result = grader.grade(trial, task)
        assert result.passed is False


class TestIntentCorrectionGrader:
    """S126: intent_correction grader"""

    def test_pass_correction(self):
        trial = _make_trial(agent_result={
            "response_type": "command",
            "steps": [{"id": "1", "label": "Build", "command": "npm run build"}],
        })
        task = _make_task(
            steps_contain=["build"],
            steps_not_contain=["start"],
        )
        grader = IntentCorrectionGrader()
        result = grader.grade(trial, task)
        assert result.passed is True

    def test_fail_not_corrected(self):
        trial = _make_trial(agent_result={
            "response_type": "command",
            "steps": [{"id": "1", "label": "Start", "command": "npm start"}],
        })
        task = _make_task(
            steps_contain=["build"],
            steps_not_contain=["start"],
        )
        grader = IntentCorrectionGrader()
        result = grader.grade(trial, task)
        assert result.passed is False


class TestContentQualityGrader:
    """S126: content_quality grader"""

    def test_pass_good_summary(self):
        trial = _make_trial(agent_result={
            "response_type": "message",
            "summary": "这是一个有实质内容的回复，包含了具体的操作步骤和建议",
        })
        task = _make_task()
        grader = ContentQualityGrader()
        result = grader.grade(trial, task)
        assert result.passed is True
        assert result.score == 1.0

    def test_pass_command_with_summary(self):
        trial = _make_trial(agent_result={
            "response_type": "command",
            "summary": "执行以下命令来安装项目依赖并启动开发服务器",
            "steps": [{"id": "1", "label": "Install", "command": "npm install"}],
        })
        task = _make_task()
        grader = ContentQualityGrader()
        result = grader.grade(trial, task)
        assert result.passed is True

    def test_fail_too_short(self):
        """summary 长度 <= 10 字符应不通过"""
        trial = _make_trial(agent_result={
            "response_type": "message",
            "summary": "好的",
        })
        task = _make_task()
        grader = ContentQualityGrader()
        result = grader.grade(trial, task)
        assert result.passed is False
        assert "过短" in result.details_json["reason"]

    def test_fail_empty_summary(self):
        trial = _make_trial(agent_result={
            "response_type": "message",
            "summary": "",
        })
        task = _make_task()
        grader = ContentQualityGrader()
        result = grader.grade(trial, task)
        assert result.passed is False

    def test_fail_error_type(self):
        trial = _make_trial(agent_result={
            "response_type": "error",
            "summary": "这是一个很长的错误信息但类型不对",
        })
        task = _make_task()
        grader = ContentQualityGrader()
        result = grader.grade(trial, task)
        assert result.passed is False

    def test_fail_low_quality_pattern(self):
        """纯无意义短语应不通过"""
        trial = _make_trial(agent_result={
            "response_type": "message",
            "summary": "ok...............",  # > 10 字符，匹配 ok[.!]*$ 模式
        })
        task = _make_task()
        grader = ContentQualityGrader()
        result = grader.grade(trial, task)
        assert result.passed is False


class TestSummaryCompletenessGrader:
    def test_summary_min_length_threshold(self):
        grader = SummaryCompletenessGrader()
        task = _make_task(extra_expected={"summary_min_length": 200})

        short_trial = _make_trial(agent_result={
            "response_type": "message",
            "summary": "a" * 199,
        })
        assert grader.grade(short_trial, task).passed is False

        exact_trial = _make_trial(agent_result={
            "response_type": "message",
            "summary": "a" * 200,
        })
        assert grader.grade(exact_trial, task).passed is True

    def test_message_without_summary_min_length_graceful_non_empty_check(self):
        grader = SummaryCompletenessGrader()
        task = _make_task(response_type=["message"])
        trial = _make_trial(agent_result={
            "response_type": "message",
            "summary": "简短但非空",
        })
        assert grader.grade(trial, task).passed is True


class TestTokenBudgetGrader:
    def test_input_tokens_within_budget_passes(self):
        grader = TokenBudgetGrader()
        trial = _make_trial(agent_result={
            "response_type": "message",
            "summary": "ok",
            "token_usage": {"input_tokens": 49999},
        })
        assert grader.grade(trial, _make_task()).passed is True

    def test_input_tokens_exceed_budget_fails(self):
        grader = TokenBudgetGrader()
        trial = _make_trial(agent_result={
            "response_type": "message",
            "summary": "ok",
            "token_usage": {"input_tokens": 50001},
        })
        assert grader.grade(trial, _make_task()).passed is False

    def test_missing_token_usage_gracefully_passes(self):
        grader = TokenBudgetGrader()
        trial = _make_trial(agent_result={
            "response_type": "message",
            "summary": "ok",
        })
        assert grader.grade(trial, _make_task()).passed is True


class TestSSESequenceGrader:
    def test_valid_sequence_passes(self):
        grader = SSESequenceGrader()
        trial = _make_trial(agent_result={
            "response_type": "message",
            "summary": "ok",
            "sse_events": [
                {"event_type": "session_created", "payload": {"session_id": "s1"}},
                {"event_type": "phase_change", "payload": {"phase": "THINKING"}},
                {"event_type": "tool_step", "payload": {"tool_name": "execute_command", "status": "running"}},
                {"event_type": "result", "payload": {"summary": "ok"}},
            ],
        })
        assert grader.grade(trial, _make_task()).passed is True

    def test_missing_session_created_fails(self):
        grader = SSESequenceGrader()
        trial = _make_trial(agent_result={
            "response_type": "message",
            "summary": "ok",
            "sse_events": [
                {"event_type": "tool_step", "payload": {"tool_name": "execute_command", "status": "running"}},
                {"event_type": "result", "payload": {"summary": "ok"}},
            ],
        })
        assert grader.grade(trial, _make_task()).passed is False

    def test_missing_result_or_error_fails(self):
        grader = SSESequenceGrader()
        trial = _make_trial(agent_result={
            "response_type": "message",
            "summary": "ok",
            "sse_events": [
                {"event_type": "session_created", "payload": {"session_id": "s1"}},
                {"event_type": "phase_change", "payload": {"phase": "THINKING"}},
            ],
        })
        assert grader.grade(trial, _make_task()).passed is False

    def test_event_after_result_fails(self):
        grader = SSESequenceGrader()
        trial = _make_trial(agent_result={
            "response_type": "message",
            "summary": "ok",
            "sse_events": [
                {"event_type": "session_created", "payload": {"session_id": "s1"}},
                {"event_type": "result", "payload": {"summary": "ok"}},
                {"event_type": "question", "payload": {"question_id": "q1"}},
            ],
        })
        assert grader.grade(trial, _make_task()).passed is False

    def test_missing_sse_events_gracefully_passes(self):
        grader = SSESequenceGrader()
        trial = _make_trial(agent_result={
            "response_type": "message",
            "summary": "ok",
        })
        assert grader.grade(trial, _make_task()).passed is True


class TestYAMLGraderNameCoverage:
    """S126: 验证所有 YAML 配置中使用的 grader 名称都能正确加载"""

    YAML_GRADER_NAMES = [
        "response_type_match",
        "steps_contain_match",
        "contains_command",
        "steps_structure",
        "safety_rejection",
        "knowledge_relevance",
        "knowledge_miss_handling",
        "step_append",
        "context_reference",
        "intent_correction",
        "content_quality",
        "summary_completeness",
        "sse_sequence",
        "tool_call_order",
        "command_safety",
        "llm_judge",
    ]

    def test_all_yaml_graders_loadable(self):
        """所有 YAML 中使用的 grader 名称都能通过 get_grader 获取"""
        missing = []
        for name in self.YAML_GRADER_NAMES:
            try:
                grader = get_grader(name)
                assert grader is not None
            except KeyError:
                missing.append(name)
        assert not missing, f"以下 grader 无法加载: {missing}"
