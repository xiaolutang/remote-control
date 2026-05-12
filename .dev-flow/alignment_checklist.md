# Alignment Checklist — R061

## 架构一致性

- [x] architecture.md 新增客户端模块边界规则，与所有任务方向一致
- [ ] F001-F004 完成后 services/ 无 screens/ import，models/ 无 flutter/material.dart import
- [ ] 不涉及后端改动
- [ ] 不涉及 API 契约变更（api_contracts.md 标记 N/A）

## 模块边界收敛

- [ ] F001: account_menu_action_handler 不在 services/ 目录
- [ ] F002: services/ui_helpers.dart 不含 UI Widget 代码
- [ ] F003: models/ 下无 flutter/material.dart import
- [ ] F004: services/ 无 BuildContext / context.read 依赖

## 模式收敛

- [ ] F005: AgentResponseType / FeedbackType / ToolStepStatus 三个 enum 创建
- [ ] F005: agent_session_event.dart 所有 JSON 字段使用 json_helpers.dart
- [ ] F006: @Deprecated 类及 switch-case 分支移除

## 效率优化安全

- [ ] F007: SharedPreferences 缓存不引入新的初始化时序依赖
- [ ] F008: notifyListeners 修复不影响成功路径
- [ ] F009a: selectDevice 并行化不改变最终状态
- [ ] F009b: _refreshDesktopState 中 syncNativeTerminationState 仍在 keepRunning 之后
- [ ] F010: DesktopWorkspaceController dispose 不遗漏资源
- [ ] F011: LoggerService 节流不影响 pendingCount 最终一致性

## 复用提取

- [ ] F012: 重命名对话框提取后两处调用行为一致
- [ ] F013: 设计 token 不改变 UI 视觉效果

## 大文件拆分

- [ ] F014: side panel 拆分不引入新的 part 文件
- [ ] F015: workspace 拆分提取部分有独立测试

## 回归安全

- [ ] 所有任务完成后 flutter test 全通过（不含预存 desktop_agent_manager_test 失败）
- [ ] 所有任务完成后 flutter analyze 零 error/warning
