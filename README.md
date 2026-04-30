# Remote Control

[English](README_EN.md)

远程控制终端 —— 通过手机或桌面端远程访问和管理终端会话。基于 Flutter、FastAPI 和 Python 构建。

## 功能特性

- **Flutter 客户端** — 跨平台终端工作台，支持 Android、iOS、macOS、Windows、Linux
- **FastAPI 服务端** — 用户认证、设备管理、终端路由、WebSocket 中继
- **Python Agent** — 本地 PTY 管理、命令执行、WebSocket 通信
- **桌面端 Agent 管理** — 桌面客户端自动管理本地 Agent 进程生命周期
- **终端状态同步** — 退出、恢复、重连时保持一致的终端状态
- **Docker 部署** — 容器化服务端和 Agent，一键启动
- **端到端加密** — RSA + AES 加密保障终端数据传输安全

## 架构

```text
┌─────────────┐     WebSocket      ┌─────────────┐     WebSocket      ┌─────────────┐
│   Flutter   │◄──────────────────►│   FastAPI   │◄──────────────────►│   Python    │
│   Client    │                    │   Server    │                    │   Agent     │
│  手机/桌面端                     │  + Redis    │                    │  + PTY      │
└─────────────┘                    └─────────────┘                    └─────────────┘
```

Flutter 客户端通过 WebSocket 连接 FastAPI 服务端。服务端负责认证客户端、通过 Redis 管理会话，并将终端 I/O 中继到运行在目标机器上的 Python Agent。每个 Agent 管理本地 PTY 进程，通过服务端回传输入输出。

## 快速开始

### 前置条件

- [Docker](https://docs.docker.com/get-docker/)（含 Docker Compose v2 和 Buildx）
- 终端 / 命令行

### 1. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，设置必填项：

```bash
# 生成随机密钥：
openssl rand -hex 32
```

将 `JWT_SECRET` 和 `REDIS_PASSWORD` 设置为强随机值。

### 2. 构建并启动服务

```bash
./deploy/deploy.sh --dev
```

自动构建 Docker 镜像并启动自包含开发环境（Server + Redis，无需 Traefik）。启动成功后输出：

```text
==> 服务已就绪!
  HTTP API:    http://localhost:8880/
  WebSocket:   ws://localhost:8880
  健康检查:    http://localhost:8880/health
```

验证健康检查：

```bash
curl http://localhost:8880/health
```

### 3. 注册用户

```bash
curl -X POST http://localhost:8880/api/register \
  -H "Content-Type: application/json" \
  -d '{"username": "myuser", "password": "mypassword"}'
```

### 4. 运行客户端

```bash
cd client
flutter pub get
flutter run -d macos    # 或: flutter run -d windows, flutter run -d linux
```

客户端中选择 **直连** 模式，输入服务端 IP（如 `localhost`）和端口（`8880`），使用注册的账号登录。

### 5. 连接 Agent（桌面端可选）

桌面端会自动管理本地 Agent。远程机器可独立运行 Agent：

```bash
cd agent
pip install -r requirements.txt
python -m app.cli login --server http://YOUR_SERVER_IP:8880
python -m app.cli run
```

详见 [agent/README.md](agent/README.md)。

## 项目结构

```text
remote-control/
├── deploy/                     # Docker 与部署
│   ├── docker-compose.dev.yml  # 自包含开发环境
│   ├── docker-compose.yml      # 生产环境（Traefik 网关）
│   ├── server.Dockerfile       # Server 多阶段构建
│   ├── agent.Dockerfile        # Agent 多阶段构建
│   ├── build.sh                # 构建镜像
│   └── deploy.sh               # 部署入口
├── server/                     # FastAPI 后端
│   ├── app/                    # 应用代码
│   └── tests/                  # 服务端测试
├── agent/                      # 终端代理
│   ├── app/                    # Agent 代码
│   └── tests/                  # Agent 测试
├── client/                     # Flutter 客户端
│   ├── lib/                    # Dart 源码
│   └── test/                   # 客户端测试
├── .env.example                # 环境变量模板
└── CLAUDE.md                   # 项目约定
```

## 配置

所有配置通过环境变量管理，复制 `.env.example` 到 `.env` 并填写：

| 变量 | 必填 | 说明 |
|------|------|------|
| `JWT_SECRET` | 是 | JWT 签名密钥，使用 `openssl rand -hex 32` 生成 |
| `REDIS_PASSWORD` | 是 | Redis 密码 |
| `LLM_API_KEY` | 否 | LLM API 密钥（Agent AI 功能必需） |
| `LLM_BASE_URL` | 否 | LLM API 地址（OpenAI 兼容） |
| `LLM_MODEL` | 否 | LLM 模型名称 |
| `CORS_ORIGINS` | 否 | CORS 允许来源（逗号分隔） |
| `RC_DIRECT_PORT` | 否 | 开发模式服务端口（默认 `8880`） |
| `LOG_LEVEL` | 否 | 日志级别（默认 `INFO`） |
| `JWT_EXPIRY_HOURS` | 否 | JWT 过期时间（默认 `168` 即 7 天） |

Agent 独立部署（Docker）时额外配置：

| 变量 | 说明 |
|------|------|
| `AGENT_USERNAME` | Agent 登录用户名 |
| `AGENT_PASSWORD` | Agent 登录密码 |

## 开发指南

### 运行测试

```bash
# 服务端测试
cd server && pytest tests/ -v

# Agent 测试
cd agent && pytest tests/ -v

# 客户端测试
cd client && flutter test
```

### 手动启动开发环境

```bash
# 构建镜像
./deploy/build.sh

# 启动
docker compose --env-file .env -f deploy/docker-compose.dev.yml up -d

# 查看日志
docker compose -f deploy/docker-compose.dev.yml logs -f

# 停止
docker compose -f deploy/docker-compose.dev.yml down
```

### Docker 中运行独立 Agent

```bash
docker compose --env-file .env -f deploy/docker-compose.dev.yml \
  --profile standalone-agent up -d agent
```

确保 `.env` 中配置了有效的 `AGENT_USERNAME` 和 `AGENT_PASSWORD`。

### 生产部署

生产环境使用 `docker-compose.yml` 配合 Traefik 网关，详见 `deploy/docker-compose.yml`。

## 技术栈

- **客户端**: Flutter 3.6+, Dart, Provider, xterm
- **服务端**: Python 3.11, FastAPI, uvicorn, Redis, SQLite (aiosqlite), httpx
- **Agent**: Python 3.11, Click, websockets, PTY
- **部署**: Docker, Docker Compose, Traefik（生产）

## 安全

- 生产环境务必使用 HTTPS/WSS（通过反向代理或网关）
- `JWT_SECRET` 设置为强随机值，不要使用默认值
- 通过防火墙或网络策略限制访问
- 不要将开发配置暴露到公网
- 漏洞报告详见 [SECURITY.md](SECURITY.md)

## 贡献

开发环境搭建、代码风格和 PR 流程详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

本项目基于 MIT 许可证开源，详见 [LICENSE](LICENSE)。
