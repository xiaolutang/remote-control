---
date: 2026-04-29
type: architecture_discussion
status: decided
requirement_cycle: R051
architecture_impact: true
supersedes: null
---

# 评估体系补全 + 架构修正

## 背景

R050 token-usage-optimization 上线后暴露了严重的 token 追踪 bug（accumulator 在 session 切换时归零，导致只记录第一条消息的 token）。排查发现根因是 session-per-question 的架构设计导致客户端状态管理复杂化，同时评估体系完全没覆盖到这类多轮状态一致性场景。进一步梳理发现多个已实现功能断链（后端做了但前端没接、自动触发没接入、UI 入口缺失）。

## 决策

### 决策 1：Session 生命周期改为跟终端绑定

- **之前**：每次提问创建新 session_id（session-per-question）
- **之后**：Terminal = Conversation = Session（1:1:1）
- Session 在首次 agent run 时懒创建（lazy），终端删除时清理
- 断开重连、面板关闭重开不影响 session
- Agent 内部"run"概念保留为内部实现细节（用于单次重试和错误隔离），不暴露给外部
- 客户端 SessionUsageAccumulator 不再需要，token 展示直接从服务端 API 获取
- 历史数据不需要迁移（项目未上线）

### 决策 2：评估体系 5 项缺失补全

对比 Anthropic "Demystifying Evals for AI Agents" 文章，当前评估体系缺失：

1. **Production Path Testing**：让 Integration 模式的评估走 SSE → 服务端 usage API 全链路验证
2. **不变量 Grader**：定义状态不变量（同终端 token 只增不减），每次 trial 后自动校验
3. **多轮状态一致性测试**：连续 N 次提问后验证累计状态
4. **效率指标补全**：n_turns、n_toolcalls、time_to_first_token、output_tokens_per_sec、time_to_last_token
5. **Balanced Problem Sets**：给每个类别补「不应该发生」的反向测试

### 决策 3：断链修复

| 断链点 | 修复方式 |
|--------|----------|
| feedback_service.py 没调用 analyze_feedback() | 反馈创建后异步调用，打通反馈→eval闭环 |
| quality_monitor 无自动触发 | 接入 Agent session 完成回调 |
| Agent 面板无回答质量反馈按钮 | 面板结果区域增加反馈入口 |
| Eval 结果无查看入口 | `python -m evals report` 生成 HTML 报告，浏览器查看 |
| Eval CLI 无文档 | 补到 CLAUDE.md |

### 决策 4：Eval HTML 报告方案

替代客户端 UI 方案，用静态 HTML 报告：
- `python -m evals report` 生成报告
- `python -m evals report --compare <run_id> <run_id>` 对比两次运行
- `python -m evals report --regression-only` 只看退化
- 内容：总览（pass rate + 趋势）、按 category 分、退化标红、改进标绿、失败详情可展开 transcript
- 纯 CSS/SVG，不依赖外部库

## 架构影响

- session 生命周期从 per-question 改为 per-terminal，影响 agent_session_manager、agent_api、agent_report_api
- agent 内部 run 概念保留，但不再暴露 session_id 给客户端
- 评估体系新增 grader 类型，需要扩展 YAML task schema 和 grader 注册表

### 决策 5：Eval 集成模式清理保障

- 集成模式 `tear_down()` 已实现（docker compose down + stop_agent + cleanup_terminals）
- 但进程被强制 kill 时 `with` 块可能没走到 `tear_down()`，导致 Docker 容器残留
- 补充信号处理（SIGINT/SIGTERM），确保异常退出也能清理
- Eval 测试数据（evals.db）会持续积累，需要定期清理策略

## 开放问题

- Agent session 管理器重构的详细方案（run vs session 的内部边界）
- Quality Monitor 回调接入点（agent_conversation close 事件？还是 result 事件后？）

## 后续动作

- 进入 xlfoundry-plan 拆解为可执行任务
- 建议分为 4 个阶段：架构修正 → 断链修复 → 评估补全 → 清理
