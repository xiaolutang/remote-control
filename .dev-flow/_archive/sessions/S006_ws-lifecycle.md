# Session 6: 移动端 WebSocket 生命周期管理

**时间**：2026-04-07
**状态**：已确认，待执行

## 用户输入

> 在手机上会一直维持 socket 连接对吗？
> 担心手机端在后台时仍然维持 WebSocket 连接导致耗电和被系统杀掉

## 澄清问题与回答

**Q: 具体关心的问题是什么？**
> A: 耗电 / 后台保活

**Q: 倾向哪种方案？**
> A: 后台断开 + 前台重连（推荐）

## 需求总结

| 场景 | 行为 |
|------|------|
| App 进入后台（paused/inactive） | 主动断开所有 WebSocket 连接，保留 session 元数据 |
| App 回到前台（resumed） | 不自动重连，由 TerminalSessionManager 对之前活跃的 service 调用 connect() |
| App 被系统杀死 | 正常冷启动流程 |
| 桌面端 | 不受影响 |
| 退出登录 | 已有 disconnectAll()，不变 |

## 关键设计点

1. `TerminalSessionManager` 实现 `WidgetsBindingObserver`
2. 新增 `pauseAll()` / `resumeAll()` 方法
3. 仅移动端注册 observer
4. `TerminalScreen` 已有 `_onStatusChanged` 监听，无需额外 UI 改动

## 架构约束检查

1. ✅ 不变量 5：Server 是在线态唯一权威源 → 仍然遵守
2. ✅ 禁止模式 5：手机端不管理 Agent → 只管 WebSocket 连接，不碰 Agent
3. ✅ 新增不变量 10：移动端后台必须断开 WebSocket
4. ✅ 新增禁止模式：移动端在后台维持心跳

## 用户确认

> ✅ 需求已确认，开始拆解

## 产出任务

- F039: TerminalSessionManager 添加 App 生命周期感知
- F040: 单元测试：WebSocket 生命周期管理
