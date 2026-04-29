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
# 标准部署（通过 Traefik 网关，地址 wss://localhost/rc）
./deploy/deploy.sh

# 或手动启动
docker compose -f deploy/docker-compose.yml up -d
```

补充约定：

- 默认 compose 不启动 `rc-agent` 容器
- 桌面端默认依赖 client 侧 managed-agent
- 如需独立 Agent 容器，显式启用 profile：

```bash
docker compose --env-file .env -f deploy/docker-compose.yml --profile standalone-agent up -d agent
```

- 启用前需要在 `.env` 配置真实可登录的 `AGENT_USERNAME` / `AGENT_PASSWORD`

### 服务地址

- HTTP API: `https://localhost/rc/`
- WebSocket: `wss://localhost/rc`
- 健康检查: `https://localhost/rc/health`

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

## Eval CLI

评估框架 CLI，位于 `server/evals/`，入口 `python -m evals`。

### 环境变量

| 变量 | 必需 | 说明 |
|------|------|------|
| `EVAL_AGENT_MODEL` | 是 | 模型名称（fallback `LLM_MODEL`） |
| `EVAL_AGENT_BASE_URL` | 是 | LLM API 地址（fallback `LLM_BASE_URL`） |
| `EVAL_AGENT_API_KEY` | 是 | LLM API 密钥（fallback `LLM_API_KEY`） |
| `EVAL_JUDGE_MODEL` | 否 | 评判模型（默认 `gpt-5.4`） |
| `EVAL_JUDGE_BASE_URL` | 否 | Judge 独立 API 地址（fallback EVAL_AGENT_BASE_URL） |
| `EVAL_JUDGE_API_KEY` | 否 | Judge 独立 API 密钥（fallback EVAL_AGENT_API_KEY） |

### 子命令

**run** — 运行评估任务，保存结果到 evals.db

```bash
# unit 模式（直接调 LLM，快速迭代）
python -m evals run --mode unit --tasks server/evals/tasks --trials 1

# integration 模式（Docker 构建 + 真实 HTTP API）
python -m evals run --mode integration --tasks server/evals/tasks \
  --base-url http://localhost:8880 --trials 1
```

**regression** — 运行任务并与 baseline 对比，检测退化

```bash
python -m evals regression --baseline <run_id> --tasks server/evals/tasks --trials 1
```

**trend** — 查询历史 pass_rate 趋势

```bash
# 全部 run 趋势
python -m evals trend --limit 20

# 按 task 过滤
python -m evals trend --task-id ic_basic_greeting --limit 10
```

**report** — 生成 eval HTML 报告（含对比、趋势图）

```bash
# 生成单次报告
python -m evals report -o eval_report.html

# 对比两次 run
python -m evals report --compare <baseline_id> <current_id> -o report.html

# 只输出退化项
python -m evals report --compare <baseline_id> <current_id> --regression-only
```

**cleanup** — 清理旧 eval run，保留最近 N 次（活跃 run 不受影响）

```bash
python -m evals cleanup --keep-last 10
```

### 公共参数（仅 run 和 regression）

- `--db` — evals.db 路径（默认 `/data/evals.db`）
- `--mode unit|integration` — 运行模式（默认 `unit`，regression 不支持 integration）
- `--trials N` — 每个 task 重复次数（默认 1）

## 关键约定

- 所有受保护路由使用 `async_verify_token` 鉴权
- Redis 不可用时 fail-closed 返回 503
- 用户数据（账号、设备）持久化到 SQLite，session/token 用 Redis
- 反馈 API 路径: `/api/feedback`
- 日志通过 `log-service-sdk` 接入
