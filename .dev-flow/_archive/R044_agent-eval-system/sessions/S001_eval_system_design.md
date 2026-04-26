# S001: R044 Agent 智能体评估体系设计

> 日期：2026-04-25
> 参考来源：Anthropic "Demystifying evals for AI agents" + 项目实际缺口分析

## 需求背景

当前 Agent 测试体系 180+ 测试全部 mock LLM，验证的是基础设施而非智能。核心缺口：
1. 无 golden dataset、无自动化测试集、无回归测试
2. 没有对 Agent 回答质量做自动评分
3. 有 token usage 统计但没有 Answer Relevance、幻觉率等质量指标
4. 没有用户反馈→打标→数据集→回归测试的闭环

## 架构决策

1. `server/evals/` 独立包，不侵入业务代码
2. 独立 `evals.db`（与 `app.db` 隔离）
3. Mock transport：eval 不需真实设备，mock `execute_command` 返回预定义输出
4. 真实 LLM 调用：eval 的核心价值是测试 LLM 行为
5. 模型配置必须显式设置，不搞默认值
6. 复用 `command_validator.py` 做 safety grader
7. 无前端改动

## 环境变量要求

评估体系所有模型配置独立于业务 agent，不复用 ASSISTANT_LLM_* 变量。

| 变量 | 用途 | 必填 |
|------|------|------|
| `EVAL_AGENT_MODEL` | 被测 Agent 模型名 | 是 |
| `EVAL_AGENT_BASE_URL` | 被测 Agent API 地址 | 是 |
| `EVAL_AGENT_API_KEY` | 被测 Agent API 密钥 | 是 |
| `EVAL_JUDGE_MODEL` | LLM-as-Judge 模型名 | 否（未配置跳过 Judge） |
| `EVAL_JUDGE_BASE_URL` | Judge API 地址 | 否（默认同 EVAL_AGENT_BASE_URL） |
| `EVAL_JUDGE_API_KEY` | Judge API 密钥 | 否（默认同 EVAL_AGENT_API_KEY） |
| `EVAL_FEEDBACK_MODEL` | 反馈打标模型名 | 否（未配置跳过自动转换） |
| `EVAL_FEEDBACK_BASE_URL` | 反馈打标 API 地址 | 否（默认同 EVAL_AGENT_BASE_URL） |
| `EVAL_FEEDBACK_API_KEY` | 反馈打标 API 密钥 | 否（默认同 EVAL_AGENT_API_KEY） |

## 任务总览

13 个任务，4 个 phase，全部 server-side：
- Phase 1 (eval-core): B096, B097, B098, S089
- Phase 2 (eval-dataset): B099, B100, S090
- Phase 3 (online-quality): B101, B102, S091
- Phase 4 (feedback-loop): B103, B104, S092
