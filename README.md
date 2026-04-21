# Remote Control

Remote Control 是一个面向个人开发者和小团队的远程终端控制系统。它把 Flutter 客户端、FastAPI 服务端、Python Agent 连接在一起，让你可以从移动端或桌面端访问和管理远程 CLI 会话。

当前公开版本：`release_1.0.0`

## Features

- Flutter 客户端，支持终端工作区与会话管理
- FastAPI + Redis 服务端，负责认证、设备、终端与消息路由
- Python Agent，负责本地 PTY、命令执行与 WebSocket 通信
- 桌面端 Agent 生命周期管理
- 终端退出、恢复、重连状态同步
- Docker 化部署与远端一键发布脚本

## Architecture

```text
┌─────────────┐     WebSocket      ┌─────────────┐     WebSocket      ┌─────────────┐
│   Flutter   │◄──────────────────►│   FastAPI   │◄──────────────────►│   Python    │
│   Client    │                    │   Server    │                    │   Agent     │
│  Mobile/Desktop                 │  + Redis    │                    │  + PTY      │
└─────────────┘                    └─────────────┘                    └─────────────┘
```

## Release 1.0.0

`release_1.0.0` 是第一个公开版本，当前重点覆盖：

- 桌面端终端工作区
- 本地 Agent 启停、退出与恢复
- 终端状态一致性与重连编排
- 服务端 / Agent 分离部署
- 基础生产链路自测

## Tech Stack

- Client: Flutter, Dart, Provider, xterm
- Server: Python, FastAPI, Redis, SQLite
- Agent: Python, Click, websockets, PTY
- Deploy: Docker, Docker Compose, Traefik

## Quick Start

### Prerequisites

- Flutter 3.6+
- Dart SDK 3.6+
- Python 3.11+
- Docker / Docker Compose

### 1. Start Server

```bash
./deploy/build.sh
./deploy/deploy.sh
curl http://localhost/rc/health
```

服务默认地址：

- HTTP API: `http://localhost/rc/`
- WebSocket: `ws://localhost/rc`
- Health: `http://localhost/rc/health`

### 2. Run Client

macOS 桌面端：

```bash
cd client
flutter pub get
flutter run -d macos
```

其他 Flutter 目标平台：

```bash
cd client
flutter pub get
flutter run
```

### 3. Run Standalone Agent

如果你要在被控机器上单独运行 Agent：

```bash
cd agent
pip install -r requirements.txt
python -m app.cli login --server http://localhost/rc --username YOUR_USERNAME
python -m app.cli run
```

对于桌面客户端场景，项目也支持由客户端侧自动管理本地 Agent 生命周期。

## Deployment

本地标准部署：

```bash
./deploy/build.sh
./deploy/deploy.sh
```

远端服务器部署：

```bash
./deploy/remote-deploy.sh
```

如果只想重发已有镜像：

```bash
./deploy/remote-deploy.sh --skip-build
```

## Development

### Client

```bash
cd client
flutter pub get
flutter test
flutter build macos
```

### Server

```bash
cd server
pytest tests/ -v
```

### Agent

```bash
cd agent
pytest tests/ -v
```

### Production Path Probe

```bash
cd client
./run_production_e2e.sh --server-ip YOUR_SERVER_IP
```

或：

```bash
cd client
RC_TEST_SERVER_IP=YOUR_SERVER_IP dart run tool/production_network_e2e.dart
```

## Project Structure

```text
remote-control/
├── client/      Flutter client
├── server/      FastAPI server
├── agent/       Python terminal agent
├── deploy/      Dockerfiles and deploy scripts
├── tests/       Cross-module or helper tests
├── README.md
└── CLAUDE.md
```

## Security Notes

- 生产环境请使用 HTTPS / WSS
- `JWT_SECRET` 必须替换为强随机值
- 建议通过网关、反向代理或防火墙限制来源访问
- 不要把开发环境配置直接带入公网

## Roadmap

- 更完整的 Linux / Windows 桌面支持
- 更清晰的权限与凭据管理模块
- 更强的终端恢复与多端协同能力
- 更完善的集成测试与发布验证

## Contributing

欢迎提交 Issue 和 PR。

提交前请确保：

- 变更范围聚焦
- 相关测试通过
- README / 脚本 / 配置说明与代码保持一致

## License

MIT
