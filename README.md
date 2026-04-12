# Remote Control

个人版 Claude Code Remote Control 实现，支持从移动设备远程控制本地 CLI 会话。

## 架构

```
┌─────────────┐     WebSocket      ┌─────────────┐     WebSocket      ┌─────────────┐
│   Flutter   │◄──────────────────►│   FastAPI   │◄──────────────────►│   Python    │
│   Client    │                    │   Server    │                    │   Agent     │
│  (Mobile)   │                    │  + Redis    │                    │  + PTY      │
└─────────────┘                    └─────────────┘                    └─────────────┘
```

## 快速开始

### 1. 启动服务器

```bash
# 克隆仓库
cd remote-control

# 启动 Docker 服务
docker-compose up -d

# 检查服务状态
docker-compose ps
curl http://localhost:8000/health
```

### 2. 生成 Token

```bash
# 生成一个新的 session token
curl -X POST http://localhost:8000/api/token
# 返回: {"session_id": "xxx", "token": "eyJ..."}
```

### 3. 启动 Agent (在被控制的机器上)

```bash
cd agent

# 安装依赖
pip install -r requirements.txt

# 启动 Agent
python -m app.cli start --server ws://localhost:8000 --token <YOUR_TOKEN>
```

### 4. 启动 Flutter 客户端 (移动设备)

```bash
cd client

# 安装依赖
flutter pub get

# 运行
flutter run
```

在 App 中输入:
- 服务器地址: `ws://your-server:8000`
- Session ID: 从步骤 2 获取
- Token: 从步骤 2 获取

## 项目结构

```
remote-control/
├── server/           # FastAPI + WebSocket 服务器
│   ├── app/
│   │   ├── __init__.py
│   │   ├── auth.py       # JWT 认证
│   │   ├── session.py    # Redis 会话存储
│   │   ├── ws_agent.py   # Agent WebSocket 处理
│   │   ├── ws_client.py  # Client WebSocket 处理
│   │   ├── history_api.py # 历史记录 API
│   │   └── routes.py     # 路由定义
│   ├── tests/
│   ├── Dockerfile
│   └── requirements.txt
├── agent/            # Python Agent (本地运行)
│   ├── app/
│   │   ├── cli.py        # CLI 入口
│   │   ├── config.py     # 配置管理
│   │   ├── pty_wrapper.py # PTY 包装器
│   │   └── websocket_client.py # WebSocket 客户端
│   └── tests/
├── client/           # Flutter 客户端 (移动端)
│   └── lib/
│       ├── main.dart
│       ├── models/
│       ├── screens/
│       └── services/
└── docker-compose.yml
```

## 功能特性

### 服务器 (Phase 1)
- ✅ FastAPI 项目初始化
- ✅ JWT 认证服务
- ✅ Redis 会话存储
- ✅ WebSocket 路由 - Agent 连接
- ✅ WebSocket 路由 - Client 连接
- ✅ 历史记录 API

### Agent (Phase 2)
- ✅ CLI 入口 (start/status/configure)
- ✅ PTY Wrapper (伪终端包装器)
- ✅ 消息转发 (PTY ↔ WebSocket)
- ✅ 断线重连 (指数退避)

### 客户端 (Phase 3)
- ✅ Flutter 项目初始化
- ✅ WebSocket 服务
- ✅ 终端渲染组件
- ✅ 输入处理
- ✅ 连接管理 UI
- ✅ 配置持久化

## 测试

### 服务器测试
```bash
cd server
pytest tests/ -v
```

### Agent 测试
```bash
cd agent
pytest tests/ -v
```

### Flutter 测试
```bash
cd client
flutter test
```

## 部署到云服务器

1. 修改 `docker-compose.yml` 中的环境变量:
   - `JWT_SECRET`: 设置一个强密码
   - 配置 HTTPS (使用 nginx 反向代理)

2. 构建并启动:
   ```bash
   docker-compose up -d --build
   ```

3. 配置防火墙开放端口 8000 (或通过 nginx 代理)

## 安全注意事项

- 生产环境必须使用 HTTPS/WSS
- JWT_SECRET 必须设置为强密码
- 建议配置 IP 白名单
- Token 有有效期限制 (默认 24 小时)

## License

MIT
