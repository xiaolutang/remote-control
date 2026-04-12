# 需求记录

> 项目：remote-control
> 状态：规划中
> 最后更新：2026-03-31
> 版本说明：本文件记录需求对话历史、澄清问题、用户回答和会话结论。

---

## Session 5: Agent 生命周期管理重构

**时间**：2026-03-31
**状态**：已确认，待拆解

### 用户输入

> 规划 Agent 生命周期管理重构：
> 1. App 启动时，如果已登录则恢复 Agent
> 2. 登录成功时启动 Agent
> 3. 退出登录时始终关闭 Agent
> 4. 关闭应用时根据 keepAgentRunningInBackground 开关决定是否关闭 Agent

### 澄清问题与回答

**Q1: 退出登录时，如果 Agent 是外部启动的（命令行、其他进程）→ 是否也关闭？**

> A: 关闭，正常情况下都应该由桌面端拉起。

**Q2: App 启动恢复 Agent 时，如果 Agent 已在运行（外部启动）→ 复用还是重启？**

> A: 如果是当前用户的复用，不是则关闭然后新建一个。

### 需求总结

| 场景 | Agent 处理 |
|------|------------|
| **退出登录** | 始终关闭 Agent（无论谁启动的） |
| **App 启动（已登录）** | Agent 运行中 + 当前用户 → 复用 |
| **App 启动（已登录）** | Agent 运行中 + 非当前用户 → 关闭 + 新建 |
| **App 启动（已登录）** | Agent 未运行 → 启动 |
| **关闭应用（开关=true）** | Agent 继续运行 |
| **关闭应用（开关=false）** | 关闭 Agent |

### 涉及组件

- `AgentLifecycleManager`（新建）- 全局 Agent 生命周期管理
- `DesktopAgentSupervisor` - Agent 进程管理
- `DesktopAgentManager` - Agent 配置管理
- `AuthService` - 认证服务（logout 需关闭 Agent）
- `ConfigService` - 配置管理
- `terminal_workspace_screen` - 移除 Agent 启动逻辑
- `main.dart` - App 级别初始化

### 平台差异

- 桌面端：需要管理本地 Agent
- 移动端：不需要 Agent，连接远程 Agent

### 架构约束检查

对照 `architecture.md` 检查：

1. ✅ **不变量 5**：Server 是在线态唯一权威源 → 仍然遵守
2. ✅ **禁止模式 5**：手机端不管理、启动或停止 Agent → 移动端不启动 Agent
3. ✅ **禁止模式 6**：桌面端停止"非自己启动"的 Agent → 退出登录时例外（需要关闭所有）
4. ⚠️ **需要新增**：Agent 启动时记录用户标识，用于判断"当前用户"

### 风险点

1. **跨进程状态一致性**：Agent 配置文件与 Desktop 的 SharedPreferences 可能不同步
2. **超时处理**：Agent 关闭超时如何处理？强制 kill？
3. **移动端兼容**：移动端代码路径不能触发 Agent 管理
4. **测试复杂性**：进程管理测试需要 mock

### 用户确认

> ✅ 需求已确认，进入任务拆解

---

## 当前生效结论

- 当前范围：设备在线感知 + 单 Agent 多 Terminal + Server 中转 + Flutter mobile/desktop 终端视图
- 当前约束：本地 Docker + Android 真机 + macOS 本地桌面端作为当前验收基线；不做远程桌面/屏幕采集
- 当前基线版本：v2.13.0-plan
- 上一轮完成：69 个任务已完成（61 completed + 8 cancelled）
