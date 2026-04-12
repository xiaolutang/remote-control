# Architecture Context

> 项目：remote-control
> 最后更新：2026-04-09
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
| DesktopAgentManager | Agent 发现/启动/停止/所有权/退出/App 生命周期 | 其他组件不得绕过 DAM 直接操作 Supervisor |
| DesktopWorkspaceController | 工作台状态机（空态/创建链/正常态） | 页面不得直接拼接状态 |

## 不变量

1. 设备在线 = 本机 Agent 在线 = 可创建并承载 terminal
2. 创建准入 = agent_online AND active_terminals < max_terminals（PTY 拉起失败是执行失败，不是准入失败）
3. closed terminal 不参与活动 terminal 数、视图数、创建判断
4. 设备离线 → 该设备所有 terminal 统一收口为不可用/关闭状态
5. Server 是在线态唯一权威源，客户端不得自行推断
6. Workspace 只消费统一 WorkspaceState，不得直接拼接 Agent 状态 + 终端快照 + 临时 UI 状态
7. 最后一个可用 terminal 关闭后，工作台必须重新归一化（不得沿用历史 createFailed）
8. Agent 生命周期与 Terminal 生命周期通过 TTL 解耦（Device TTL = 90s），WebSocket 断开不立即触发离线
9. 终端数据流始终经过 Server 中转，Client 不直连 Agent
10. 移动端 App 进入后台时必须主动断开所有 WebSocket 连接，回到前台时由页面按需重连
11. DesktopAgentManager 是 Agent 生命周期的唯一管理入口，其他组件不得直接调用 DesktopAgentSupervisor 的启停方法
12. Agent 配置同步（syncManagedAgentConfig）与进程启动（ensureAgentOnline）必须原子执行，不可分割
13. 同用户同端（mobile/desktop）同时只允许一个 Client WS 连接，新设备直接替换旧设备（token_version + WS 直接踢出）
14. 同用户同端（mobile/desktop）在 HTTP 登录层只允许最新登录设备的 token 有效，旧设备 token 通过 Redis token_version 机制自动失效
15. token_version 按 session_id + view_type 独立计数，mobile/desktop 互不影响
16. 旧 token 无 token_version 字段时向后兼容，视为有效（平滑迁移）
17. Redis 不可用时 fail-closed：登录/注册返回 503，verify_token 对携带 token_version 的 token 返回 503，旧 token 正常放行
18. 所有受保护路由（HTTP API + WS Client + WS Agent）必须使用 async_verify_token 做鉴权，不得使用同步 verify_token（auth.py 内部调用除外）
19. TokenVerificationError 必须透传到 HTTP 响应层，不得被 catch 后包装为普通 HTTPException（否则 error_code 字段丢失）

## 禁止模式

- ✗ 客户端自行推断设备在线/离线状态
- ✗ 客户端通过 API 修改 max_terminals
- ✗ WebSocket 断开立即判定 Agent 离线（必须走 TTL）
- ✗ Workspace 直接读取 Agent 状态拼接 UI
- ✗ 手机端管理、启动或停止 Agent
- ✗ 桌面端停止"非自己启动"的 Agent（退出登录时例外）
- ✗ createFailed 作为持久状态，terminal 生命周期变化后不清理
- ✗ 只杀死 PTY 直接子进程而不杀进程组（必须 os.killpg）
- ✗ Agent 启动逻辑放在页面 initState 中（应放在 App 级别）
- ✗ 退出登录时不关闭 Agent（必须关闭，因为 token 失效）
- ✗ 移动端在后台维持 WebSocket 心跳（必须后台断开、前台重连）
- ✗ 绕过 DesktopAgentManager 直接调用 DesktopAgentSupervisor 启停 Agent（DAM 是唯一入口）
- ✗ 启动 Agent 前不同步配置文件（sync + start 必须在同一方法内原子执行）
- ✗ 客户端自行踢出同端其他设备（由 Server 通过 token_version + WS 直接踢出）
- ✗ JWT token 不携带 token_version 就声称受登录层保护（必须同时有 Redis 版本校验）
- ✗ refresh token 刷新时递增 token_version（刷新不应使其他设备失效）
- ✗ WS 路由使用同步 verify_token 而非 async_verify_token（被踢设备的旧 token 必须被拒绝，不能通过 WS 重回）
- ✗ catch TokenVerificationError 后包装为普通 HTTPException（丢失 error_code，客户端无法分支处理）

## 日志拓扑

```
路径 A：Server/Agent 自身日志（Python logging 框架）
[Server Python]  → log-service-sdk（RemoteLogHandler）→ http://log-service:8001/api/logs/ingest
[Agent Docker]   → log-service-sdk（RemoteLogHandler）→ http://log-service:8001/api/logs/ingest
[Agent Desktop]  → 本地日志（LOG_SERVICE_URL 未配置时不远程上报）

路径 B：Client 日志代理转发（已有 Redis 存储 + 转发到 log-service）
[Client Flutter] → POST /api/logs {uid=rc_username} → [Server log_api.py]
                                                           ├── Redis 存储（已有）
                                                           └── httpx 异步转发 → log-service ingest API
                                                                  entry.uid = 请求 body uid（客户端从 rc_username 传入）
```

- 两条路径职责不同：路径 A 是 Python logging handler 自动上报；路径 B 是 Server 代理转发 Client 日志
- 路径 B 的 entry 带 uid 字段（= user_id/username），使 log-service 可按用户维度查询日志
- 反馈关联日志通过 GET /api/logs?uid={user_id}&service_name=remote-control&component=client 查询
- log-service 归 infrastructure/ 管理，通过 infra-network 可达
- Server 请求中间件自动记录每个 HTTP 请求
- Agent 离线时 SDK 静默重试，不影响 Agent 运行
- Desktop Agent 无需直连 log-service，本地日志即可
- Client 不直连 log-service，通过 Server 转发

## 用户信息流

```
[Client login] → POST /api/login → [Server user_api.py]
                                          └── LoginResponse 新增 username 字段
[Client] → SharedPreferences 存储 rc_username + rc_login_time + rc_token
[Client UserProfileScreen] → 显示本地用户信息 → 操作：反馈 / 退出
```

- 用户信息（username、login_time、platform）由客户端本地存储和展示
- 反馈 API 通过 session 记录获取真实 user_id，不依赖客户端传递
- 设置菜单只保留"主题"和"个人信息"，反馈和退出移至个人信息页面

## 反馈数据流

```
[Client Flutter] → POST /api/feedback → [Server feedback_api.py]
                                            ├── category→severity 映射
                                            ├── 从 log-service 获取近期日志关联
                                            └── POST /api/issues → log-service（持久化）

[Client Flutter] → GET /api/feedback/{id} → [Server feedback_api.py]
                                                  └── GET /api/issues/{id} → log-service
```

- 反馈入口统一收口到 UserProfileScreen（从三处菜单的"个人信息"进入），不再直接暴露在设置菜单
- 反馈 API 通过 JWT sub (session_id) 查 session 记录获取真实 user_id，不使用 payload 中的 session_id 字段
- 用户只填分类（Chip）+ 描述（文本框），其余自动采集
- 反馈存储在 log-service Issues 表（持久化），不再使用 Redis
- category→severity 映射：connection=high, terminal=medium, crash=critical, suggestion=low, other=low
- 反馈提交调用外部 log-service，失败返回 503（非 best-effort，反馈是重要数据）
- 客户端 API 契约不变，Server 做翻译层

## 关键决策与理由

| 决策 | 为什么 | 否决的方案 |
|------|--------|-----------|
| TTL 判定离线（90s） | 网络抖动不应立即断开 Agent | 心跳超时即断 |
| DesktopAgentManager 独立 | Agent 生命周期和工作台状态职责不同 | 页面直接管 Agent |
| DesktopAgentManager extends ChangeNotifier | 单一权威 + 状态一致，消除 ALM/DAM 双路径 | ALM 和 DAM 并行调用 Supervisor |
| 桌面管 Agent / 手机只看 | 本地 Agent 只能被本机控制 | 双端都能管理 |
| Server 中转数据流 | 多端同步、权限控制、离线查看 | Client 直连 Agent |
| Agent 本地 HTTP Supervisor | 控制面与数据面分离，端口发现 | 只靠 WebSocket |
| os.killpg 进程组清理 | 防止孤儿进程泄漏 | 只 kill 直接子进程 |
| 移动端后台断开 WebSocket | 节省电量和网络资源，避免被系统杀掉 | 后台维持心跳保活 |
| 同端同用户单 Client 在线 | 防止多设备混乱、数据冲突、会话状态不一致 | 允许多设备同时在线 |
| 新设备直接替换旧设备 | token_version 机制已保证登录层安全，WS 层无需再弹窗确认 | 冲突解决通知用户选择 |
| 登录层 token_version 机制 | 覆盖 Agent 离线 / 终端 closed 场景，不依赖 WS 连接 | 只靠 WS 层冲突检测 |
| token_version 按端独立计数 | 桌面和手机是不同使用场景，不应互踢 | 全局单一版本号 |
| log-service-sdk 统一 Server/Agent 自身日志 | 一行代码接入，非阻塞批量上报，SDK 静默重试 | 自建日志上报 |
| Client 日志经 Server httpx 转发 | 不创建 Dart SDK，复用现有 LoggerService + Server 异步代理转发 | Client 直连 log-service 或用 SDK 转发 |
| Docker 三网模式 | gateway(对外) + infra-network(共享服务) + rc-network(项目私有) | 直接端口映射 |

## 模块职责一句话

- **Agent**：PTY 进程管理，terminal 多实例隔离，进程组完整清理，本地 HTTP 控制面
- **Server**：设备注册、terminal 中转、认证、在线态权威、TTL 状态管理
- **Client mobile**：远程 terminal 查看器 + 软键盘快捷键层 + 命令面板
- **Client desktop**：本机 Agent 控制台 + terminal 工作台 + 后台运行开关
- **DesktopAgentManager**：Agent 生命周期唯一权威（extends ChangeNotifier，发现/启动/停止/所有权/后台/退出/登录登出/App 生命周期）
- **DesktopWorkspaceController**：工作台状态机（空态/创建链/正常态/失败归一化）

## 状态文件路径

```
macOS:  ~/Library/Application Support/remote-control/
Linux:  ~/.local/share/remote-control/
Windows: %APPDATA%/remote-control/
```
