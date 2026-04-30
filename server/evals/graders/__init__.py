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

S126: 新增 grader（注册表名与 YAML 配置一一对应）：
7. steps_contain_match  — YAML 配置名（与 contains_command 同逻辑）
8. safety_rejection     — 安全拒绝行为检查
9. knowledge_relevance  — 知识检索相关性检查
10. knowledge_miss_handling — 知识未命中处理检查
11. step_append         — 多轮追加步骤检查
12. context_reference   — 多轮上下文引用检查
13. intent_correction   — 多轮意图修正检查
14. content_quality     — summary 实质内容检查
15. summary_completeness — integration summary 最小完整度检查
16. token_budget        — integration input token 预算检查
17. sse_sequence        — integration SSE 事件序列检查

B054: 不变量 Grader：
18. invariant           — 多轮状态一致性检查（token 单调递增、usage 非负、SSE 序列合法）
"""
from evals.graders.code_grader import (
    CodeGraderBase,
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
    GRADER_REGISTRY,
    GRADER_ALIASES,
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
from evals.graders.invariant_grader import (
    InvariantGrader,
    SUPPORTED_INVARIANTS,
)

__all__ = [
    "CodeGraderBase",
    "ResponseTypeMatchGrader",
    "CommandSafetyGrader",
    "StepsStructureGrader",
    "ContainsCommandGrader",
    "ToolCallOrderGrader",
    "StepsContainMatchGrader",
    "SafetyRejectionGrader",
    "KnowledgeRelevanceGrader",
    "KnowledgeMissHandlingGrader",
    "StepAppendGrader",
    "ContextReferenceGrader",
    "IntentCorrectionGrader",
    "ContentQualityGrader",
    "SummaryCompletenessGrader",
    "TokenBudgetGrader",
    "SSESequenceGrader",
    "InvariantGrader",
    "SUPPORTED_INVARIANTS",
    "LLMJudgeGrader",
    "CalibrationTool",
    "parse_judge_response",
    "compute_score_from_dimensions",
    "build_judge_config",
    "GRADER_REGISTRY",
    "GRADER_ALIASES",
    "get_grader",
]
