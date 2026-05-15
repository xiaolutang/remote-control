# Remote Control 项目规格

## 当前范围：R065 侧边栏浮层化

桌面端 TerminalSidebar hover 展开时挤压右侧终端，导致 xterm 内容重排/滚动。

### 背景

当前 `TerminalWorkspaceScreen` 使用 Row 布局：`[Sidebar(48→160px)] [Expanded(Terminal)]`。Sidebar hover 展开时宽度从 48px 变为 160px，右侧终端区域随之收窄 112px，触发 xterm 重排。

### 修复方案

将桌面端布局改为 Stack：终端区域用 `Padding(left: 48)` 固定起始位置，Sidebar 浮在 Stack 上层。展开时终端宽度不变。

### 范围（1 Phase，1 任务）

- **Phase 1** — 客户端布局改造（F001）：Row → Stack

### 产品定义

| 维度 | 决策 |
|------|------|
| 收起态 | Sidebar 48px 占位，终端从 48px 开始 |
| 展开态 | Sidebar 160px 浮层，覆盖终端左侧 112px |
| 终端宽度 | 始终 = 窗口宽度 - 48px（不随 hover 变化） |
| 动画 | 200ms AnimatedContainer，行为不变 |
| 移动端 | 不受影响（无 Sidebar） |

### 目标平台

- Server: 不改动
- Client: macOS arm64（桌面端）
- Agent: 不改动
