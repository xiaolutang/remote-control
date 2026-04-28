# R048 architecture-deep-cleanup 归档

- 归档时间: 2026-04-28
- 状态: completed
- 总任务: 20
- 分支: feat/R048-architecture-deep-cleanup
- workflow: B / skill_orchestrated
- providers: review=codex_plugin, audit=codex_plugin, risk=codex_plugin

## 仓库提交

- remote-control: 9b718ae (HEAD on feat/R048-architecture-deep-cleanup)

## Phase 9-11

| 范围 | 描述 | commit |
|------|------|--------|
| Phase 9 | B201-B206, S206-S208: Agent/Server 深度拆分、Docker 集成 smoke、托管链路 smoke | d261dc4..4561bcb |
| Phase 10 | F211-F213: Client terminal session / WebSocket service 拆分与编译验证 | ce3618d..5c8c1de |
| Phase 11 | B214-B220, S216, S221: 对话历史预算、integration eval 自动拉起 Agent、真实场景 smoke | 9b718ae |

## 关键交付

- Agent 代码按 `core/transport/tools/security` 分层，`websocket_client` 与消息处理职责拆开。
- Server `session.py`、`ws_agent.py`、`agent_session_manager.py`、`terminal_agent.py` 完成深拆分并恢复 Docker 标准发布链路。
- Client `terminal_session_manager.dart` 与 `websocket_service.dart` 拆分为协调、恢复、连接管理、消息解析等独立模块。
- 对话历史从事件条数裁剪切换为 token 预算控制，`conversation_store` 支持 `event_types` 查询过滤。
- integration eval 打通真实 Agent 自启动、SSE 协议、多轮上下文和 grader 补强，真实环境 smoke 完成验收。
