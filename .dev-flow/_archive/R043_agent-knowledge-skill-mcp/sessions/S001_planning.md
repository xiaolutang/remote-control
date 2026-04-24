# S001: R043 需求讨论与规划

> 日期：2026-04-24

## 需求来源

实际使用中发现智能助手不理解 "Claude Code"，无法映射到 `claude` CLI 命令。

## 需求确认

1. 增强 system prompt 中的 Claude 生态工具知识（Claude Code + Codex）
2. 增加 Claude Code 使用技巧（启动方式、交互技巧、CLAUDE.md 配置）
3. 增加 Vibe Coding 方法论
4. 场景化建议：重构/写测试/排查 bug/新功能 → 附带 1 条提示
5. 非终端意图扩展：允许回答工具使用问题
6. 明确用户旅程边界：信息型问答（steps=[]）vs 工具启动意图（可执行 CommandSequence）

## 架构校验

无冲突。仅涉及 system prompt 文本，不改变命令白名单、工具定义或客户端逻辑。

## 任务拆解

- B089: Agent SYSTEM_PROMPT 增强（L2, risk: state_sync）
- B090: Planner system_prompt 增强 + schema 回归保护（L2, risk: state_sync）
- S085: Agent prompt 测试 + 别名/边界/场景覆盖（L1, risk: boundary）
- S086: Planner prompt 测试 + schema 回归（L2, risk: boundary）
- S087: 更新 test_coverage.md 与 alignment_checklist.md（L1）

## 审核历史

### Codex Plan Review #1 (2026-04-24T17:44:40+0800)
- status: **fail**
- 5 findings: 缺 schema 回归、缺用户旅程边界、planner 测试落错文件、配套产物未更新、缺 risk_tags
- 全部修复

### Codex Plan Review #2 (2026-04-24T17:53:17+0800)
- status: **conditional_pass**
- 2 findings: Planner 缺信息型问答路由边界、4 类场景建议映射缺测试
- 全部修复

### Codex Plan Review #3 (2026-04-24T18:01:15+0800)
- status: **pass**
- findings: []
- required_changes: []

## 工作流

- 模式：A（本地执行）
- 运行时：skill_orchestrated
- 审核提供方：codex_plugin
