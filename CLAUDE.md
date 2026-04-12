# Remote Control 项目说明

## 项目概述

远程控制终端，支持从手机/桌面端远程访问终端。包含 Server（FastAPI）、Agent（Python CLI）、Client（Flutter）三个模块。

## 标准部署流程

### 前置条件

- 基础设施层已启动：`infrastructure/docker-compose.yml`（Traefik 网关 + 共享服务）
- Docker buildx 已安装（用于 `--build-context` 挂载本地依赖）

### 构建镜像

```bash
# Server（需要挂载 log-service-sdk）
docker buildx build \
  --build-context log-service-sdk=/Users/tangxiaolu/project/log-service/sdks/python \
  -t remote-control-server \
  --load \
  ./server
```

### 启动服务

```bash
# 标准部署（通过 Traefik 网关，地址 ws://localhost/rc）
docker compose -f docker-compose.prod.yml up -d

# 或使用部署脚本
./deploy.sh
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
docker compose -f docker-compose.prod.yml down
```

## 技术栈

- **Server**: Python 3.11, FastAPI, uvicorn, Redis, httpx
- **Agent**: Python CLI, websockets
- **Client**: Flutter 3.6+, Dart

## 项目结构

```
remote-control/
├── server/          # FastAPI 后端
│   ├── app/         # 应用代码
│   ├── tests/       # 服务端测试
│   └── Dockerfile
├── agent/           # 终端代理
│   ├── app/         # Agent 代码
│   └── tests/
├── client/          # Flutter 客户端
│   ├── lib/         # Dart 源码
│   └── test/        # 客户端测试
├── docker-compose.prod.yml  # 标准部署配置
├── deploy.sh        # 部署脚本
└── .dev-flow/       # 开发流程管理
```

## 关键约定

- 所有受保护路由使用 `async_verify_token` 鉴权
- Redis 不可用时 fail-closed 返回 503
- 反馈 API 路径: `/api/feedback`
- 日志通过 `log-service-sdk` 接入
