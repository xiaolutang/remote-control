"""
Eval Graders - 确定性评分器 + LLM Judge 评分器

B098: 提供 5 种纯代码 grader，不调用 LLM：
1. response_type_match  — 检查 agent 返回的 response_type 是否匹配预期列表
2. command_safety       — 复用 command_validator.validate_command 检查命令安全性
3. steps_structure      — 检查 steps 结构完整性
4. contains_command     — 检查 steps 中是否包含/不包含指定 pattern
5. tool_call_order      — 检查 transcript 中工具调用序列是否符合期望

B100: LLM-as-Judge 评分器：
6. llm_judge            — 通过 rubric prompt 调用 LLM 对 Agent 输出做多维度评分
"""
from evals.graders.code_grader import (
    CodeGraderBase,
    ResponseTypeMatchGrader,
    CommandSafetyGrader,
    StepsStructureGrader,
    ContainsCommandGrader,
    ToolCallOrderGrader,
    GRADER_REGISTRY,
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
)

__all__ = [
    "CodeGraderBase",
    "ResponseTypeMatchGrader",
    "CommandSafetyGrader",
    "StepsStructureGrader",
    "ContainsCommandGrader",
    "ToolCallOrderGrader",
    "LLMJudgeGrader",
    "CalibrationTool",
    "parse_judge_response",
    "compute_score_from_dimensions",
    "build_judge_config",
    "GRADER_REGISTRY",
    "get_grader",
]
