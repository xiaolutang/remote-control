"""
B098 测试 — Code-based Graders

覆盖：
- 5 种 grader 的 pass/fail case
- command_safety 复用 validate_command
- 边界：空 steps、多 pattern、tool_call_order
"""
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
    ResponseTypeMatchGrader,
    CommandSafetyGrader,
    StepsStructureGrader,
    ContainsCommandGrader,
    ToolCallOrderGrader,
    get_grader,
)


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
    def test_all_five_graders_registered(self):
        expected = {
            "response_type_match",
            "command_safety",
            "steps_structure",
            "contains_command",
            "tool_call_order",
        }
        assert expected == set(GRADER_REGISTRY.keys())

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


# ── EvalGraderResult 结构验证 ──────────────────────────────────────────────


class TestGraderResultStructure:
    """确保所有 grader 输出符合 EvalGraderResult 结构"""

    @pytest.mark.parametrize("grader_name", [
        "response_type_match",
        "command_safety",
        "steps_structure",
        "contains_command",
        "tool_call_order",
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
