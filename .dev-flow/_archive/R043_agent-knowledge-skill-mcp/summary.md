# R043: agent-claude-knowledge

> 状态：**规划中** (2026-04-24)
> 分支：`feat/R043-agent-claude-knowledge`

## 范围

在智能助手的 Agent 和 Planner system prompt 中增加 Claude Code / Codex CLI 工具知识、使用技巧和 Vibe Coding 方法论，使助手能：
1. 正确识别 "Claude Code" 并映射到 `claude` 命令
2. 回答 "Claude Code 怎么用" 等工具使用问题
3. 根据用户场景（重构/写测试/排查 bug）附带使用建议

## 技术方案

- 纯 system prompt 文本修改
- 不涉及命令白名单、Agent 工具定义或客户端逻辑变更
- 两个 prompt 独立修改，无交叉依赖
