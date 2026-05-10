# Alignment Checklist — R059

## 架构一致性

- [x] 不涉及 architecture.md 变更
- [x] 不涉及后端改动
- [x] 终端切换仍然是纯客户端行为（selectTerminal + notifyListeners）
- [x] 所有终端 WebSocket 连接同时保持，切换只改显示

## 无 API 契约变更确认

- [x] 后端 4 个 Terminal API 不变（create/list/close/rename）
- [x] 终端切换无独立 API

## 平台分支安全

- [x] F002 仅改桌面端 HeaderBar，移动端保持 expand_more 菜单不变
- [x] F002 不修改 _showTerminalMenu，不移除任何菜单项
- [x] F003 为移动端添加底部 Tab 栏，提供终端操作替代入口
- [x] F004 在两端 Tab 栏都就绪后才从 _showTerminalMenu 移除终端 CRUD
- [x] F004 移动端 expand_more 因菜单空化而条件隐藏（F003 已提供替代入口）
- [x] TerminalScreen bottomChrome slot 为 null 时完全不影响现有布局

## 错误反馈策略

- [x] Tab 操作失败（创建/重命名/关闭）统一使用 SnackBar（局部提示）
- [x] 不修改现有 errorMessage + MaterialBanner 通道
- [x] 不出现重复提示

## 菜单架构

- [x] Agent 管理/设备编辑保持在 workspace 局部（WorkspaceHeaderBar PopupMenuButton）
- [x] 不扩展共享 account_menu_actions.dart
- [x] 不泄漏 workspace 专属动作到其他页面

## terminals_changed 同步

- [x] F002/F003 验收条件包含 terminals_changed 事件即时同步
- [x] 远端关闭当前选中终端 → 自动切换到相邻
- [x] 远端重命名 → Tab 标题即时刷新
- [x] F006 集成测试覆盖远端同步路径

## F007/F008 验收缺陷修复

- [x] F007 依赖 F001（核心 widget），不依赖集成层
- [x] F008 依赖 F003（移动端集成）+ F004（上下文菜单）+ F007（样式先行）
- [x] F008 使用 IndexedStack 替换 KeyedSubtree，终端切换不再触发 State 重建
- [x] F008 CompactTabStrip 从 bottomChrome 移到 IndexedStack 外层，保持移动端功能
- [x] F006 集成测试依赖 F007+F008，确保回归验证
- [x] F008 标记 risk_tags: first_use, startup，补充冷启动和空工作区首次创建测试

## F009/F010 刷新选中态修复 + 测试补充

- [x] F009 修复 selectedTerminal getter 副作用，改为纯读取 + 数据变更点显式解析
- [x] F009 刷新（loadDevices）后选中终端 ID 不变
- [x] F009 排序变化导致终端位置移动时选中 ID 不变（IndexedStack index 跟随）
- [x] F009 原选中终端刷新后被关闭 → 自动切换到第一个未关闭终端
- [x] F010 测试覆盖 loading + IndexedStack 共存（loadingDevices/loadingTerminals + terminal!=null）
- [x] F010 测试覆盖多终端 Provider 作用域隔离（各自持有独立 WebSocketService）
- [x] F010 测试覆盖刷新后 selectedIndex 跟随 terminalId（不跟随位置）
- [x] F006 依赖 F009，集成测试包含刷新保持回归

## Codex Plan Review 回归处理

- [x] RC1: 决策记录更新 — DesktopWorkspaceController 从"不变"改为"微调"（F009 修复 getter 副作用）
- [x] RC2: F009 补充"关闭最后 Tab → 空状态 → 再次创建"验收和测试
- [x] RC3: F006 补充 5xx/超时失败分支测试
- [x] RC4: F006 补充移动端执行环境说明（远程路径复用桌面端 device）
