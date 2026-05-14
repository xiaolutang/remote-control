# R064 desktop-cleanup-agent-aware 归档

- 归档时间: 2026-05-15
- 状态: completed
- 总任务: 2
- 分支: fix/R064-desktop-cleanup-agent-aware
- workflow: mode B / skill_orchestrated
- providers: codex_plugin (review/audit/risk)

## 仓库提交
- remote-control: b123642 (HEAD on fix/R064-desktop-cleanup-agent-aware)

## Phase 1: 客户端核心修复 + 测试
| 任务 | 描述 | commit |
|------|------|--------|
| F001 | cleanup 服务增加 Agent 在线感知 | ba3e861 |
| F002 | 补充 Agent 在线/离线场景的单元测试 | b123642 |

## 关键交付
- DesktopStartupTerminalCleanupService.cleanup() 新增 agentOnline 参数，Agent 在线时跳过清理
- AppStartupCoordinator 启动流程调整：先 listDevices 获取 agentOnline 状态，再传给 cleanup
- listDevices 失败时优雅降级为原行为，AuthException rethrow 保持登录回退路径
- 14 个单元测试全部通过（6 cleanup + 8 coordinator）
- 网络请求总数不变（listDevices 时序前移 + 复用结果）
