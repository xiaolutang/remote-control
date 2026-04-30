# S001: Token Usage 优化规划

## 背景

用户发现当前 Token 汇总逻辑有两个问题：
1. 展示维度不对：当前是「当前终端」vs「我的总计」（都是全量聚合），应该改为「总消耗」vs「当前对话消耗」
2. 交互不好：点击展示几秒后自动消失的 toast 体验差

经过 brainstorm 讨论，确认方案：
- **数据来源**：客户端内存累积 SSE 事件 usage（SessionUsageAccumulator），同时修复 Server 端 DB 累加问题
- **交互方式**：可展开/收起区域替代 toast

## 决策

- 选择方案 A（客户端累积 SSE 事件）+ 方案 B（可展开/收起 UI）
- 不涉及新 API 端点、DB schema 变更或架构变更
- 全自动化测试覆盖（server 单元测试 + client 单元/Widget 测试）

## 任务拆解

| ID | 描述 | 依赖 |
|----|------|------|
| B050 | 修复 usage_store ON CONFLICT 累加 + 测试 | 无 |
| F051 | Client 会话级 usage 累加器 + 测试 | 无 |
| F052 | 替换 toast 为可展开/收起区域 + widget 测试 | F051 |

## workflow

- mode: B (codex_plugin 审核)
- runtime: skill_orchestrated
- review/audit/risk: codex_plugin
