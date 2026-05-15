# R066 terminal-scroll-preservation 归档

- 归档时间: 2026-05-15
- 状态: completed
- 总任务: 2
- 分支: fix/R066-terminal-scroll-preservation
- workflow: A/skill_orchestrated

## 仓库提交

| 任务 | 描述 | commit |
|------|------|--------|
| F001 | 重连时保持 TerminalView mounted | a4945bf |
| F002 | scroll 保持 widget test | 4bb303b |

## 关键交付

- 修复 WebSocket 重连时终端 scroll 跳顶问题：Consumer builder 始终构建 TerminalView + Stack overlay 遮罩
- 移除 _shouldFollowSharedPty 的 status!=connected 早期返回，autoResize 不再受连接状态干扰
- 根因：Claude Code + Codex 双重验证确认

## 缺陷信息

- fix_level: L2（设计缺陷）
- root_cause: Consumer<WebSocketService> 在 reconnecting/connecting 时替换 TerminalView 为 _buildCenteredMessage，Flutter 销毁 TerminalViewState
- source: real_use（生产环境实际遇到）
