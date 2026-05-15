# Remote Control 项目规格

## 当前范围：R066 终端 scroll 保持

WebSocket 重连时终端内容滚动到顶部。

### 背景

`terminal_screen.dart:467` 的 `Consumer<WebSocketService>` 在 `reconnecting`/`connecting` 状态时返回 `_buildCenteredMessage` 替代 `TerminalView`，Flutter 销毁 `TerminalViewState`（含 `ViewportOffset`/scroll position）。重连成功后新建 TerminalView，scroll offset 从 0 开始。

根因已由 Claude Code + Codex xlfoundry-code-review 双重确认。

### 修复方案

三层修复：
1. **核心**：Consumer builder 始终构建 TerminalView（terminal 非空时），重连消息用 Stack overlay 覆盖
2. **防护**：`shouldAutoResize` 在重连期间不切换，避免 `markNeedsLayout` 链路
3. **清理**：移除 debug print（render.dart、desktop_workspace_controller.dart）

### 范围（1 Phase，2 任务）

- **Phase 1** — 客户端修复（F001 + F002）

### 产品定义

| 维度 | 决策 |
|------|------|
| 连接中 | TerminalView 保持 mounted + 半透明遮罩 + "正在连接..." |
| 重连中 | TerminalView 保持 mounted + 半透明遮罩 + "正在重连..." |
| 首次连接 | terminal=null 时仍显示 connecting message |
| 正常连接 | 无遮罩，行为不变 |
| scroll | 重连前后 scroll 位置保持一致 |

### 目标平台

- Server: 不改动
- Client: macOS arm64（桌面端）+ iOS/Android（移动端）
- Agent: 不改动
