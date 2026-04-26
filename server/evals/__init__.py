"""
Eval 数据模型与数据库层

评估框架独立包，提供：
- Pydantic 模型（EvalTaskDef, EvalTrial, EvalGraderResult, EvalRun 等）
- 独立 evals.db（6 张表）
- 环境变量配置检查（EVAL_AGENT_*）
"""
