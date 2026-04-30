---
date: 2026-04-30
type: architecture_discussion
status: decided
requirement_cycle: null
architecture_impact: true
supersedes: null
---

# R051 Simplify 收敛发现的技术债务

## 背景

R051（eval-architecture-overhaul）完成后，xlfoundry-simplify 四视角收敛审查发现 3 项架构级问题，无法通过当前 diff 的收敛修复解决，需回流到规划层作为独立需求包处理。

## 发现

### 1. App→Evals 依赖方向违反 R044 隔离边界

**现状**：
- `app/services/agent_session_runner.py` 直接 `from evals.db import EvalDatabase`、`from evals.quality_monitor import extract_and_store_metrics`
- `app/services/feedback_service.py` 直接 `from evals.feedback_loop import analyze_feedback`、`from evals.db import EvalDatabase`
- `evals/quality_monitor.py` 的 `_batch_read_app_db` 直接读 app.db

**违反约束**：architecture.md R044 约束 evals 为独立子系统，不应被生产服务代码直接引用。

**建议方案**：引入事件钩子机制（如 `on_result_event` / `on_feedback_created` 回调），evals 模块注册监听器。services 层只触发钩子，不直接 import evals。

**影响范围**：agent_session_runner.py、feedback_service.py、quality_monitor.py

### 2. EVAL_DB_PATH 环境变量命名不一致

**现状**：
- `agent_session_runner.py:60` 使用 `os.environ.get("EVAL_DB_PATH", "/data/evals.db")`
- `feedback_service.py:325` 使用 `os.environ.get("EVAL_DB_PATH", "/data/evals.db")`
- `eval_api.py` 中使用 `os.environ.get("EVALS_DB_PATH", "/data/evals.db")`
- 两套命名共存，且 evals 模块内部无统一常量

**建议方案**：统一为 `EVALS_DB_PATH`（复数），在 evals 模块内提供 `get_evals_db()` 工厂函数，所有使用方通过该函数获取实例。

### 3. feedback_status SSE 实时路径缺失

**现状**：
- `agent_conversation_helpers.py` 的 `_build_agent_conversation_projection` 在构建 projection 时注入 `feedback_status`
- 但 SSE 实时推送路径（`_applyConversationEventItem`）不携带 `feedback_status`
- 用户实时观看 Agent 回答时，无法看到其他设备/会话提交的反馈状态变更

**建议方案**：在 feedback 创建成功后，通过 event_bus 推送 `feedback_status_update` 事件到对应 terminal 的 SSE 流。

## 决策

- 3 项问题记录为技术债务，不阻塞 R051 合并
- 下一个规划周期（R052 或后续）安排专项需求包处理
- architecture_impact=true：方案 1 需要变更 architecture.md 的 R044 约束描述，明确"事件钩子"为 evals→app 的唯一通信通道

## 后续动作

- 等待下一个规划周期安排任务
- architecture.md 暂不修改（等方案确认后再更新）
