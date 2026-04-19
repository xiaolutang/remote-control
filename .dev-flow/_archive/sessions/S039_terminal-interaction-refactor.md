# Session S039: 终端交互架构重构规划

> 日期：2026-04-17
> 状态：已完成，已合并 main

## 需求来源

用户在真实使用中持续反馈终端问题，即使经过整日修复后，仍然存在以下剩余现象：

- `Codex` 高频刷新、切换 terminal、刷新页面时，内容仍偶发丢失或恢复不完整
- `Claude` 在双端 attach、桌面 refresh、手机输入删除等场景下，暴露出几何与恢复链路问题
- app 前后台切换、app 重启、网络异常恢复、agent 与 server 断连等场景，当前没有统一恢复模型

用户明确要求：不要继续按症状补丁修复，而是从后端、客户端、桌面端、agent 整体重构终端交互架构。

## 需求澄清结论

- 本轮不再把问题拆成 `Codex bug` 或 `Claude bug` 分别处理，而是升级为 `terminal-interaction-refactor`
- 当前系统的核心问题不是单个协议实现，而是职责混叠：
  - UI / Coordinator / Transport / Renderer 未拆分
  - agent snapshot / server history / client local renderer cache 三套恢复源边界不清
  - switch / reconnect / recover 三种事件语义混用
  - desktop agent lifecycle 与 terminal recovery 没有并入统一状态机
- 重构目标：
  - Agent 成为 terminal 内容恢复主权威源
  - Server 收口为 metadata / ownership / routing / epoch 真相
  - Client 重构为 UI / Coordinator / Transport / Renderer 四层
  - terminal 模式显式区分 `exclusive` 与 `shared`

## 本轮沉淀的关键设计

### 1. 四层客户端模型

- UI Layer：`TerminalScreen / TerminalWorkspaceScreen`
- Coordinator Layer：`TerminalSessionCoordinator`
- Transport Layer：`WebSocketService`
- Renderer Layer：`RendererAdapter + xterm`

### 2. 恢复语义正式化

- `snapshot` 绑定 `terminal_id + attach_epoch + recovery_epoch + pty`
- `snapshot_complete` 前 live output 只缓冲，不直接渲染
- local renderer cache 只做本地 continuity，不做跨端真相

### 3. terminal 模式显式区分

- `exclusive`：默认用于 `Codex` 这类高频增量交互 terminal
- `shared`：默认用于 `Claude` / shell 这类多端观察终端

### 4. Desktop Agent 恢复模型

- agent 与 server 断开后，terminal 先进入 `recoverable`
- TTL 内优先恢复，不立刻 `closed`
- TTL 超时后再正式收口为 `closed`
- 桌面端必须区分“agent 进程还活着但网络断了”和“agent 进程已死，需要本地重启”

## 任务树结论

新增重构任务：

- `S071` 终端交互架构基线
- `S072` 恢复语义与模式基线
- `S073` 协议兼容迁移与灰度切换
- `B071` Server 状态中心收瘦
- `B072` Agent 主权威恢复源
- `B073` 恢复协议升级
- `F071` Client Transport 收瘦
- `F072` Client Coordinator 状态机
- `F073` Renderer 隔离
- `F074` UI 瘦身迁移
- `F075` 桌面端 Agent 断连恢复编排
- `F076` 客户端生命周期恢复编排

## 复审补强

针对第一次 plan review 提出的缺口，本 session 已追加以下补强：

- 在 `api_contracts.md` 中补齐：
  - `CONTRACT-039` 终端恢复状态机与生命周期语义
  - `CONTRACT-040` Server terminal metadata / ownership / lifecycle truth
  - `CONTRACT-041` Agent terminal snapshot authority
  - `CONTRACT-042` Terminal recovery WebSocket protocol
- 单列 `S073` 兼容迁移任务，明确新旧协议共存窗口、发布顺序与回退策略
- 将 server recoverable/offline_expired 状态模型显式纳入 `B071`
- 将 app foreground / cold start / network restore 显式拆为 `F076`

## 执行建议

- 推荐先执行：`S071 -> S072 -> B071/B072 -> B073`
- 之后进入 `F071 -> F072 -> F073 -> F074`
- 桌面端恢复链单列为 `F075`，在协议与 coordinator 基线稳定后推进

## 关联缺陷

- `DF-20260417-01`: 真实使用中 `Claude` 双端 refresh / full-screen TUI 恢复缺口
- `DF-20260417-02`: 客户端架构职责混叠，补丁修复持续外溢，需升级为整体交互重构

## 遗留问题

### Codex 终端刷新后内容丢失（未解决）

**现象**：Codex 终端刷新/切换后内容丢失，只剩空白。Claude Code 终端无此问题。

**根因分析**：
- recovery 流程依赖服务端发送 `snapshot_complete` 触发 `finishRecovery()`
- 如果 Agent snapshot 请求超时（1.5s）且回退 history 为空，`snapshot_complete` 虽然会到达，但无实际数据
- Codex 使用 TUI（alternate screen buffer），idle 状态下无持续输出，恢复后无法自动填充内容
- Claude Code 持续产生输出，即使 snapshot 不完整也会被新输出覆盖

**已做保护**：添加 5 秒 recovery 超时，防止终端永久卡在 recovering 状态。

**待深入排查方向**：
1. Agent 对 Codex TUI alternate screen buffer 的 snapshot 捕获可靠性
2. 服务端 snapshot fallback（history）对 alternate buffer 的兼容性
3. 客户端 `applySnapshot` 对 `active_buffer` 字段的处理（当前忽略，一律写 main buffer）
4. `snapshot_start` 消息是否应携带恢复语义信息供客户端预处理

**优先级**：P1 — v1 主打 Claude Code 兼容，Codex 兼容性后续专项排查。

### DesktopAgentManager 双实例问题（已知，未修）

- 全局 Provider 实例与 `DesktopAgentBootstrapService` 创建的临时实例并存
- F075 recovery state machine 中 `onAgentDisconnect`/`onAgentReconnected` 未被调用（dead code）
- 三个独立状态机（TerminalSessionState / DesktopAgentRecoveryState / ConnectionStatus）缺乏协调
