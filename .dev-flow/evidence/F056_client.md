# F056: 菜单去重 + 个人信息入口

## Task Snapshot

- ID: F056
- Phase: user-info
- Module: client
- Status: completed

## Execution Evidence

### 实现摘要

1. **terminal_workspace_screen.dart**: `_WorkspaceHeaderBar` 菜单从（主题 + 反馈问题 + 退出登录）改为（主题 + 个人信息），移除 `onFeedback`/`onLogout` 回调，新增 `onProfile` 回调。
2. **runtime_selection_screen.dart**: `_MenuAction` 枚举从 `{theme, feedback, logout}` 改为 `{theme, profile}`，菜单项对应更新。
3. **terminal_screen.dart**: 菜单从（主题 + 退出登录）改为（主题 + 个人信息），删除 `_logout` 方法，新增 `_navigateToProfile` 方法。

### 质量门

- **Flutter analyze**: 0 errors, 0 warnings（3 个 pre-existing info）
- **xlfoundry-simplify**: 通过

### 验收条件检查

| # | 验收条件 | 状态 |
|---|---------|------|
| 1 | _WorkspaceHeaderBar 菜单只有：主题 + 个人信息 | ✅ |
| 2 | RuntimeSelectionScreen 菜单只有：主题 + 个人信息 | ✅ |
| 3 | terminal_screen.dart 菜单：退出登录替换为个人信息入口 | ✅ |
| 4 | 点击个人信息 → 导航到 UserProfileScreen | ✅ |
| 5 | 退出登录和反馈问题只能从 UserProfileScreen 触发 | ✅ |
| 6 | logout 时清理 rc_login_time | ✅（F054 已实现）|

## Audit Result

- status: done
- commit_ready: true
