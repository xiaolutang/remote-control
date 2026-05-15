# Remote Control 项目规格

## 当前范围：R067 认证弹窗重入修复

被踢/Token 过期后弹窗重复弹出，黑色闪烁，登录按钮无效。

### 背景

桌面端双实例场景：测试包登录后踢掉正式包，正式包弹窗闪烁，点击登录无效。

根因（Claude Code + Codex 双重确认）：
- `confirmDeviceKicked` / `confirmTokenExpired` 中 `clearAuthDialog()` 先于 `disconnectAll()` / `performSessionTeardown()` 调用
- disconnect 触发 `_onStatusChanged`，`lastCloseCode` 仍为 4011/4001
- `_authDialogShowing` 已清零，守卫失效 → `_onDeviceKicked()` 再次触发
- `showDialog` 堆叠 → 多个 modal barrier 叠加 → 黑色闪烁
- `Navigator.pushAndRemoveUntil` 被新弹窗打断 → 登录按钮无效

### 修复方案

将 `clearAuthDialog()` 移到 `disconnectAll()` / `performSessionTeardown()` 之后，确保守卫在 teardown 期间始终有效。

### 范围（1 Phase，2 任务）

- **Phase 1** — 客户端修复（F001 + F002）

### 产品定义

| 维度 | 修复前 | 修复后 |
|------|--------|--------|
| 被踢弹窗 | 重复弹出 + 黑色闪烁 | 只弹一次 |
| Token 过期弹窗 | 可能重复弹出 | 只弹一次 |
| 确定按钮 | 无效（Navigator 被打断） | 正常跳转登录页 |

### 目标平台

- Server: 不改动
- Client: macOS（桌面端）+ iOS/Android（移动端）
- Agent: 不改动
