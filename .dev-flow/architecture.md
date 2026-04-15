# Architecture Context

> 项目：remote-control
> 最后更新：2026-04-15
> 本文件是项目的架构宪法，任何新代码不得违反以下约束。

## 系统拓扑

```
用户桌面电脑                              云端服务器（Docker）
├── Desktop Client ─── 互联网 ───→ Server (Traefik/TLS 或直连端口)
├── Local Agent ───── 互联网 ───→ Server    ├── Server: 认证 + Terminal Relay + TTL
└── Client ←HTTP localhost─→ Agent         ├── Redis: session/token/aes_key
                                            └── SQLite: 用户持久化

用户手机
└── Mobile Client ─── 互联网 ───→ Server

数据流方向：Agent PTY → Server → Clients（非直连，Server 中转）
控制面：Desktop ←HTTP localhost→ Agent 本地 Supervisor（端口 18765-18769）
Agent 主要模式：跑在用户本地电脑上，通过互联网 WebSocket 连接 Server
Docker Agent（辅助）：与 Server 同一 docker-compose，走 Docker 内网（仅测试/自托管场景）
```

## 网络安全边界

```
                互联网（需加密）
    ┌─────────────────────────────────────┐
    │  Mobile Client ──→ Server           │
    │  Desktop Client ──→ Server          │
    │  Local Agent ──→ Server             │  ← 都走互联网！
    └─────────────────────────────────────┘

    本地（无需加密）
    Desktop Client ←→ Local Agent (localhost:18765)

    Docker 内网（无需加密）
    Server ←→ Docker Agent (rc-network，仅辅助场景)
```

## 权威边界

| 谁拥有 | 管什么 | 谁不能管 |
|--------|--------|---------|
| Server | 设备在线态、terminal 列表、max_terminals、在线数、认证 | 客户端不得自行推断 |
| Agent | PTY 进程生命周期、terminal cwd/command/env、进程组清理 | 客户端不得直接操作 PTY |
| Client mobile | UI 状态、主题偏好 | 不得管理 Agent、不得修改 max_terminals |
| Client desktop | UI 状态 + 本地 Agent 配置 + 后台运行开关 | 只管理自己启动的 Agent |
| DesktopAgentManager | Agent 发现/启动/停止/所有权/退出/App 生命周期 | 其他组件不得绕过 DAM |
| DesktopWorkspaceController | 工作台状态机（空态/创建链/正常态） | 页面不得直接拼接状态 |

## 不变量

1. 设备在线 = 本机 Agent 在线 = 可创建并承载 terminal
2. 创建准入 = agent_online AND active_terminals < max_terminals
3. closed terminal 不参与活动 terminal 数、视图数、创建判断
4. 设备离线 → 该设备所有 terminal 统一收口为不可用/关闭状态
5. Server 是在线态唯一权威源，客户端不得自行推断
6. Workspace 只消费统一 WorkspaceState，不得直接拼接
7. Agent 生命周期与 Terminal 生命周期通过 TTL 解耦（90s）
8. 终端数据流始终经过 Server 中转
9. 同用户同端只允许一个 Client WS 连接，新设备直接替换旧设备
10. token_version 按 session_id + view_type 独立计数
11. 所有 token 必须携带 token_version，无 token_version 直接拒绝
12. Redis 不可用时 fail-closed（登录/注册 503，verify_token 503）
13. 所有受保护路由必须使用 async_verify_token
14. JWT_SECRET 环境变量必填，不允许硬编码或随机回退
15. 密码必须使用 bcrypt，旧 SHA-256 登录时自动迁移
16. CORS origins 通过 CORS_ORIGINS 环境变量配置，禁止 *
17. WS 认证通过首条消息传递 token，禁止 URL query 参数
18. WS 消息大小限制 1MB（MAX_WS_MESSAGE_SIZE 可配置）
19. 登录/注册端点基于 IP 速率限制（默认 10 次/分钟）
20. 日志 API 必须校验 session 归属，使用 get_current_user_id
21. JWT 验证错误脱敏，不返回解码异常详情
22. Redis 必须密码认证；Docker 容器必须非 root
23. Agent 本地 HTTP 端点必须认证
24. Client 敏感数据（密码/token）用 flutter_secure_storage
25. serverUrl 的单一真相源是 EnvironmentService，AppConfig 不持久化 serverUrl
26. 环境切换编排由 UI/协调层触发（DAM.onLogout → 断终端 → AuthService.logout → 更新环境），EnvironmentService 不做任何副作用
27. ws:// 直连路径必须使用应用层加密（RSA+AES），不得明文传输密码和终端数据（Client 和 Agent 均适用）。唯一例外：WS 首条 auth 消息（携带 JWT token）在 AES 密钥交换完成前无法加密，由 JWT 短时效 + RSA-OAEP 加密的 AES 密钥共同保障安全
28. AES 密钥绑定 WS 连接，每次 WebSocket 连接生成独立 AES-256 密钥，连接断开时销毁（clear_aes_key）
29. TLS 路径（wss://）不加应用层加密，由传输层保护
30. 本地环境 URL 格式为 `ws://{host}:{port}`（无 /rc 前缀，直连 Server）
31. Agent 主要运行在用户本地电脑上，通过互联网连接 Server（非 Docker 内网）

## 禁止模式

- ✗ 客户端自行推断设备在线/离线状态
- ✗ WebSocket 断开立即判定 Agent 离线（必须走 TTL）
- ✗ 移动端后台维持 WebSocket 心跳
- ✗ 绕过 DAM 直接操作 Agent Supervisor
- ✗ JWT Secret 硬编码/空值/随机回退
- ✗ 密码使用无盐哈希（SHA-256/MD5）
- ✗ CORS allow_origins=*
- ✗ WS 通过 URL query 传认证 token
- ✗ 登录/注册无速率限制
- ✗ Redis 无密码 / Docker 以 root 运行
- ✗ Agent 本地 HTTP 无认证
- ✗ Client SharedPreferences 明文存密码/token
- ✗ JWT 错误返回具体异常详情
- ✗ 日志 API 用 get_current_payload 而非 get_current_user_id
- ✗ EnvironmentService 直接调用 AuthService.logout / DesktopAgentManager（纯状态服务不得有副作用）
- ✗ LoginScreen/TerminalWorkspaceScreen 通过构造参数传 serverUrl（改为从 EnvironmentService 读取）
- ✗ ws:// 连接明文传输密码或终端数据（Client 和 Agent 均适用，必须经过 RSA+AES 加密）

## 数据流拓扑

```
日志：Server/Agent → log-service-sdk → log-service | Client → POST /api/logs → Server → log-service
反馈：Client → POST /api/feedback → Server → POST /api/issues → log-service Issues 表
用户：Client → POST /api/login → Server user_api.py → SQLite + Redis session
加密(ws://)：Client/Agent → GET /api/public-key → RSA 公钥 → 本地生成 AES → 加密登录 → Redis 存储 AES → WS 加解密
Agent 注册：Local Agent → ws://server/ws/agent → Server（互联网，ws:// 时需加密）
数据流：Agent PTY → Server 中转 → Clients（Agent 和 Client 都通过互联网连接 Server）
```

## 关键决策

| 决策 | 为什么 | 否决方案 |
|------|--------|---------|
| 环境选择在登录页 | 用户必须先选定环境再登录，切换 = 登出 | 全局设置页 |
| 线上 URL 编译时固定 | 只有部署方知道线上地址，用户无需关心 | 运行时远程获取 |
| 本地 host+port 可编辑 | 开发时 IP 变化频繁，端口因部署不同 | 完整 URL 编辑 |
| EnvironmentService 独立服务 | 单一职责，可被 ConfigService / AuthService / AgentSupervisor 复用 | 直接在 ConfigService 加逻辑 |
| RSA+AES 混合加密 | RSA 解决密钥分发，AES 解决对称加密性能，接近自建 TLS | 预共享密钥 |
| 直连暴露 Server 端口 | 不修改共享 Traefik，零影响其他项目 | 修改 Traefik 添加非 TLS 入口 |
| 本地 URL 无 /rc 前缀 | 直连 Server 不走 Traefik striprefix | Server 加 /rc 路由前缀 |
| 加密按连接协议判断 | ws:// 必须加密，wss:// 不加密（TLS 已保护） | 全部加密 |

| 决策 | 为什么 | 否决方案 |
|------|--------|---------|
| TTL 判定离线（90s） | 网络抖动不应立即断开 | 心跳超时即断 |
| 桌面管 Agent / 手机只看 | 本地 Agent 只能被本机控制 | 双端都能管理 |
| Server 中转数据流 | 多端同步、权限控制 | Client 直连 Agent |
| bcrypt 密码 | 抗暴力破解，自动加盐 | SHA-256 无盐 |
| WS auth 首条消息 | 避免 token 出现在 URL/日志 | URL query 参数 |
| Redis 密码 | 共享网络不能仅靠隔离 | 纯网络隔离 |
| Docker 非 root | 限制逃逸影响面 | root 运行 |
| IP 速率限制 | 防暴力破解，fail-open | 无限制 |

## 模块职责

- **Agent**：PTY 管理，terminal 多实例隔离，进程组清理，本地 HTTP 控制面
- **Server**：设备注册、terminal 中转、认证、在线态权威、TTL 状态管理、RSA 密钥管理与 AES 会话密钥存储
- **Client mobile**：远程 terminal 查看器 + 软键盘快捷键 + 命令面板
- **Client desktop**：本机 Agent 控制台 + terminal 工作台 + 后台运行开关
