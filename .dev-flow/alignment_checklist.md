# Alignment Checklist — R060

## 架构一致性

- [x] 不涉及 architecture.md 变更
- [x] 不涉及后端改动
- [x] 终端切换仍然是纯客户端行为（selectTerminal + notifyListeners）
- [x] 所有终端 WebSocket 连接同时保持，切换只改显示
- [x] IndexedStack 缓存机制保持不变

## 无 API 契约变更确认

- [x] 后端 4 个 Terminal API 不变（create/list/close/rename）
- [x] 终端切换无独立 API

## 平台分支安全

- [x] F003 仅改桌面端布局（Row[Sidebar, Expanded(body)]），移动端保持不变
- [x] F003 修改 HeaderBar 移除 TerminalTabBar 参数，不影响移动端 HeaderBar
- [x] F004 仅改移动端底部（CompactTabStrip → TerminalPageIndicator），桌面端保持不变
- [x] F003/F004 修改同一文件 terminal_workspace_screen.dart，但各自只改对应平台分支

## 错误反馈策略

- [x] 侧边栏/页码指示器操作失败统一使用 SnackBar（局部提示）
- [x] 不修改现有 errorMessage + MaterialBanner 通道
- [x] 不出现重复提示

## 菜单架构

- [x] Agent 管理/设备编辑保持在 workspace 局部（WorkspaceHeaderBar 设置 PopupMenuButton）
- [x] 不扩展共享 account_menu_actions.dart
- [x] 不泄漏 workspace 专属动作到其他页面

## terminals_changed 同步

- [x] F003 验收条件包含侧边栏 terminals_changed 即时同步
- [x] F004 验收条件包含页码指示器 terminals_changed 即时同步
- [x] 远端关闭当前选中终端 → 自动切换到相邻
- [x] 远端重命名 → 侧边栏/BottomSheet 标题即时刷新

## 组件替换策略

- [x] F001 TerminalSidebar 接口与 TerminalTabBar 一致，无缝替换
- [x] F002 TerminalPageIndicator 接口覆盖 CompactTabStrip 全部能力
- [x] F005 清理旧组件前确认无其他引用
- [x] 旧 widget 测试在 F005 统一清理，不在 F003/F004 中删除
