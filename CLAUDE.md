# Remote Control

远程控制终端，支持从手机/桌面端远程访问终端。包含 Server（FastAPI）、Agent（Python CLI）、Client（Flutter）三个模块。

## 技术栈

- **Server**: Python 3.11, FastAPI, uvicorn, Redis, SQLite (aiosqlite), httpx
- **Agent**: Python CLI, websockets
- **Client**: Flutter 3.6+, Dart

## 项目结构

```
remote-control/
├── deploy/                   # Docker 与部署
│   ├── server.Dockerfile     # Server 多阶段构建
│   ├── agent.Dockerfile      # Agent 多阶段构建
│   ├── docker-compose.yml    # 生产编排
│   ├── build.sh              # 标准化构建（server/agent/all）
│   └── deploy.sh             # 部署入口
├── server/                   # FastAPI 后端
│   ├── app/                  # 应用代码
│   └── tests/                # 服务端测试
├── agent/                    # 终端代理
│   ├── app/                  # Agent 代码
│   └── tests/
└── client/                   # Flutter 客户端
    ├── lib/                  # Dart 源码
    └── test/                 # 客户端测试
```

## 标准部署流程

前置：基础设施层已启动（`infrastructure/docker-compose.yml`），Docker buildx 已安装。

```bash
./deploy/build.sh            # 构建全部镜像
./deploy/build.sh server     # 构建单个
./deploy/deploy.sh           # 启动（wss://localhost/rc）
```

默认不启动 `rc-agent` 容器。需独立 Agent 时启用 `--profile standalone-agent`，并在 `.env` 配置 `AGENT_USERNAME` / `AGENT_PASSWORD`。

- HTTP API: `https://localhost/rc/` | WebSocket: `wss://localhost/rc`
- 必需环境变量: `JWT_SECRET`

## 关键约定

- 所有受保护路由使用 `async_verify_token` 鉴权
- Redis 不可用时 fail-closed 返回 503
- 用户数据持久化到 SQLite，session/token 用 Redis
- 反馈 API: `/api/feedback`，日志通过 `log-service-sdk` 接入
