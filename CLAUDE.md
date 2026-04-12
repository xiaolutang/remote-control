# Remote Control 项目说明

## 项目概述

远程控制终端，支持从手机/桌面端远程访问终端。包含 Server（FastAPI）、Agent（Python CLI）、Client（Flutter）三个模块。

## 标准部署流程

### 前置条件

- 基础设施层已启动：`infrastructure/docker-compose.yml`（Traefik 网关 + 共享服务）
- Docker buildx 已安装

### 构建镜像

```bash
# 构建全部
./deploy/build.sh

# 构建单个
./deploy/build.sh server
./deploy/build.sh agent

# 无缓存构建
./deploy/build.sh --no-cache
```

### 启动服务

```bash
# 标准部署（通过 Traefik 网关，地址 ws://localhost/rc）
./deploy/deploy.sh

# 或手动启动
docker compose -f deploy/docker-compose.yml up -d
```

### 服务地址

- HTTP API: `http://localhost/rc/`
- WebSocket: `ws://localhost/rc`
- 健康检查: `http://localhost/rc/health`

### 必需环境变量

在 `.env` 文件或环境变量中设置：
- `JWT_SECRET` — JWT 签名密钥（必填）

### 停止服务

```bash
docker compose -f deploy/docker-compose.yml down
```

## 技术栈

- **Server**: Python 3.11, FastAPI, uvicorn, Redis, SQLite (aiosqlite), httpx
- **Agent**: Python CLI, websockets
- **Client**: Flutter 3.6+, Dart

## 项目结构

```
remote-control/
├── deploy/                   # Docker 与部署（集中管理）
│   ├── server.Dockerfile     # Server 多阶段构建
│   ├── agent.Dockerfile      # Agent 多阶段构建
│   ├── docker-compose.yml    # 生产编排（image 引用）
│   ├── build.sh              # 标准化构建（server/agent/all）
│   └── deploy.sh             # 部署入口（custom_build → build.sh）
├── .dockerignore              # 构建排除规则（build context 为根目录）
├── server/                   # FastAPI 后端
│   ├── app/                  # 应用代码
│   │   ├── database.py       # SQLite 数据库层（用户持久化）
│   │   └── ...               # 其他模块
│   └── tests/                # 服务端测试
├── agent/                    # 终端代理
│   ├── app/                  # Agent 代码
│   └── tests/
├── client/                   # Flutter 客户端
│   ├── lib/                  # Dart 源码
│   └── test/                 # 客户端测试
└── .dev-flow/                # 开发流程管理
```

## 关键约定

- 所有受保护路由使用 `async_verify_token` 鉴权
- Redis 不可用时 fail-closed 返回 503
- 用户数据（账号、设备）持久化到 SQLite，session/token 用 Redis
- 反馈 API 路径: `/api/feedback`
- 日志通过 `log-service-sdk` 接入
