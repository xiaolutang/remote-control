---
date: 2026-04-29
type: requirement_clarification
requirement_cycle: R049
---

# S001: brainstorm 结论转化为 bug fix 计划

## 背景

用户通过 xlfoundry-brainstorm 提出一系列问题，逐一讨论后确认 3 个需要修复的 bug。

## 确认的问题与方案

### Issue 1: 终端注入内容截断
- 现象：AI Prompt 注入终端时多行内容被截断
- 方案：Bracketed Paste Mode 转义序列包裹
- 文件：ws_connection_manager.dart

### Issue 2: 聊天面板命令显示截断
- 现象：命令卡片被 maxLines:3 截断
- 方案：移除命令内容区的 maxLines 限制
- 文件：agent_panel_widgets.dart + agent_panel_result_views.dart

### Issue 3 (用户跳过): 工具执行折叠展示
- 用户说"算了 先不处理这个吧"

### Issue 4: 工具注册 name 参数 bug
- 现象：GLM 拼接出 _tool_execute_command_tool_execute_command
- 根因：agent.tool() 未显式传入 name 参数
- 文件：terminal_agent_tools.py

### 额外完成: 知识库目录修复
- 发现 _get_builtin_knowledge_dir() 指向不存在的目录
- 已创建 agent/app/tools/knowledge/ 并新增 2 个官方文档知识文件

## 架构校验

三个修复均无架构冲突：
- Issue 1 符合不变量 #61（PTY 写入完整性）
- Issue 2 纯 UI 展示调整
- Issue 4 工具注册机制修复，不涉及架构变更

## 工作流选择

- 用户选择 mode B（Codex Plugin 审核）
- runtime: skill_orchestrated
- review/audit/risk_provider: codex_plugin
