# Architecture Context

> 项目：remote-control
> 最后更新：2026-04-13
> 本文件是项目的架构宪法，任何新代码不得违反以下约束。

## 系统拓扑

```
[Agent] ←PTY→ [Terminal Runtime × N]
    ↕ WebSocket
[Server: 设备管理 + Terminal Relay + 认证 + TTL]
    ↕ WebSocket
[Client Flutter]
  ├── mobile：远程终端查看器 + 输入增强
  └── desktop：本机 Agent 控制台 + 终端工作台

数据流方向：Agent PTY → Server → Clients（非直连）
控制面：Desktop ←HTTP→ Agent 本地 Supervisor（端口 18765-18769）
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

## 数据流拓扑

```
日志：Server/Agent → log-service-sdk → log-service | Client → POST /api/logs → Server → log-service
反馈：Client → POST /api/feedback → Server → POST /api/issues → log-service Issues 表
用户：Client → POST /api/login → Server user_api.py → SQLite + Redis session
```

## 关键决策

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
- **Server**：设备注册、terminal 中转、认证、在线态权威、TTL 状态管理
- **Client mobile**：远程 terminal 查看器 + 软键盘快捷键 + 命令面板
- **Client desktop**：本机 Agent 控制台 + terminal 工作台 + 后台运行开关
