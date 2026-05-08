# Remote Control 架构宪法

## 系统拓扑

```text
Flutter Client ──WS──► FastAPI Server ──WS──► Python Agent ──PTY──► Shell
    (手机/桌面)          (Redis+SQLite)         (本地进程)
```

- Client 通过 WebSocket 连接 Server，不直连 Agent（终端数据面）
- 桌面端 Client 通过 localhost HTTP 控制本地 Agent 进程生命周期（进程管理控制面例外）
- Server 负责认证、会话管理、终端 I/O 中继
- Agent 管理本地 PTY 进程，通过 Server 回传输入输出
- 桌面端 Client 内嵌 DesktopAgentSupervisor 自动管理本地 Agent 生命周期

## 权威边界

- 用户数据持久化：SQLite（Server 端 `/data/users.db`）
- 会话/Token 管理：Redis
- Agent 配置：JSON 文件（桌面端通过 `--config` 传入 `managed-agent/config.json`；独立部署时使用 `~/.rc-agent/config.json`）
- Agent 数据目录：统一从 `--config` 参数的父目录派生（skills/、user_knowledge/），不引入独立状态根
- 客户端环境配置：SharedPreferences（Dart）

## 不变量

- 所有受保护路由必须通过 `async_verify_token` 鉴权
- Redis 不可用时 fail-closed 返回 503，不降级
- Agent 启动必须先 login 获取 token，再 run
- WebSocket 消息格式遵循 `type` + `data` 结构
- 桌面端 Agent 管理由 DesktopAgentSupervisor 统一调度
- Docker 部署通过 `deploy/` 目录统一管理

## 禁止模式

- Client 不直连 Agent 终端数据面（必须经过 Server 中继）；桌面本地进程管理控制面除外
- 不在代码中硬编码密码、域名、内部 IP
- 不在 CI/CD 中 source .env 文件（使用 grep 安全解析）
- 不在 main 分支直接开发功能（使用 feat/ 分支）
- Agent 不依赖系统 Python（打包后必须可独立运行）

## 模块边界政策

- **ws 子模块直接从 store 层 import**：ws 子模块（agent_connection、agent_request、agent_cleanup、agent_message_handler）直接从 `app.store.session` 导入 store 函数，禁止通过 ws_agent 入口模块 re-export 中转
- **ws_agent.py 只做 handler 注册和生命周期管理**：入口模块只含 `agent_websocket_handler`、`_heartbeat_checker` 等函数，以及从子模块导入 handler 所需的符号
- **测试 mock 路径指向实际使用模块**：`patch("module.func")` 中的 `module` 必须是函数被 `from ... import` 导入的目标模块，而非源模块或中转模块

## 关键决策与理由

| 决策 | 理由 |
|------|------|
| FastAPI + SQLite + Redis | 轻量级全栈，单机部署友好 |
| WebSocket 全链路 | 终端 I/O 实时双向通信需求 |
| Click CLI Agent | 单文件入口，CLI 可测试 |
| PyInstaller 打包 Agent | 免除用户安装 Python 依赖 |
| macOS .app bundle 内嵌 Agent | 一键安装体验，.dmg 拖拽安装 |
