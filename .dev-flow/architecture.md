# Architecture Context

> 项目：remote-control
> 最后更新：2026-04-17
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

互联网连接必须加密（ws:// 需 RSA+AES，wss:// 由 TLS 保护），本地 localhost 和 Docker 内网无需加密。

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
32. Agent retry 耗尽或收到不可恢复错误（4001/4004/4009）后，进程必须完全退出（cleanup + sys.exit），不留僵尸
33. Flutter 桌面端检测到 managed Agent 离线且旧进程无法恢复时，必须杀旧进程 + 清除 PID + 用新 token 重启
34. Agent 并行任务（PTY读/WS读/心跳）中任一检测到连接断开，必须立即设置 _connected=False，使其他任务退出循环，避免 asyncio.gather 死锁
35. 移动端终端不得将本地 viewport 变化（键盘弹起/收起）升级为全局 PTY resize
36. 多端同时附着到同一 terminal 时，后加入视图的本地 layout/refresh 不得在 multi-view 模式下抢占 shared PTY geometry；共享 PTY 尺寸必须先以既有 terminal 权威值恢复，再决定是否允许单视图本地 resize
37. Client 终端交互必须分为 UI / Coordinator / Transport / Renderer 四层，页面组件不得直接承载恢复策略
38. WebSocket transport 只负责协议消息与连接状态，不得直接承载 xterm renderer 语义
39. terminal 的 switch / reconnect / recover 必须是三个独立事件，不得复用同一套恢复逻辑
40. 同一 client view 同时只能有一个 active terminal transport；inactive terminal 只保留本地 renderer cache，不维持同 view 的额外 live WS
41. Agent 是 terminal 内容恢复的主权威源；Server 维护 metadata / ownership / routing 真相，output history 只可作为诊断级辅助材料，不能与 agent snapshot 形成双主恢复源

## 禁止模式

- ✗ 客户端自行推断设备在线/离线状态
- ✗ WebSocket 断开立即判定 Agent 离线（必须走 TTL）
- ✗ 移动端后台维持 WebSocket 心跳
- ✗ 绕过 DAM 直接操作 Agent Supervisor
- ✗ 在 TerminalScreen / TerminalWorkspaceScreen 中直接编排 reconnect / snapshot 恢复 / geometry owner 策略
- ✗ 让 WebSocketService 同时承担 transport 和 renderer/recovery 职责
- ✗ 把 switch terminal 当作 reconnect 或 recover 处理
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
- ✗ Agent 重连耗尽后进程继续存活（local_server 仍监听视为僵尸进程）

## 数据流

日志/反馈：Client → Server → log-service | 加密(ws://)：Client/Agent → RSA 公钥 → AES → WS 加解密
Agent 注册：Local Agent → ws://server/ws/agent | 数据流：Agent PTY → Server 中转 → Clients

## 关键决策

| 决策 | 为什么 | 否决方案 |
|------|--------|---------|
| 环境选择在登录页 | 用户必须先选定环境再登录，切换 = 登出 | 全局设置页 |
| 线上 URL 编译时固定 | 只有部署方知道线上地址，用户无需关心 | 运行时远程获取 |
| 本地 host+port 可编辑 | 开发时 IP 变化频繁，端口因部署不同 | 完整 URL 编辑 |
| RSA+AES 混合加密 | RSA 解决密钥分发，AES 解决对称加密性能 | 预共享密钥 |
| 直连暴露 Server 端口 | 不修改共享 Traefik，零影响其他项目 | 修改 Traefik 添加非 TLS 入口 |
| 加密按连接协议判断 | ws:// 必须加密，wss:// 不加密（TLS 已保护） | 全部加密 |
| TTL 判定离线（90s） | 网络抖动不应立即断开 | 心跳超时即断 |
| 桌面管 Agent / 手机只看 | 本地 Agent 只能被本机控制 | 双端都能管理 |
| Server 中转数据流 | 多端同步、权限控制 | Client 直连 Agent |
| Agent 进程退出不留僵尸 | 重连耗尽后完全退出，由 Flutter 负责重启 | Agent 无限重试或进程残留 |
| Agent 作为恢复主源 | 避免 server history / agent snapshot / client local state 三套恢复真相并存 | Server output history 做 attach 主恢复源 |

## 模块职责

- **Agent**：PTY 管理，terminal 多实例隔离，进程组清理，本地 HTTP 控制面
- **Server**：设备注册、terminal 中转、认证、在线态权威、TTL 状态管理、RSA 密钥管理与 AES 会话密钥存储
- **Client mobile**：远程 terminal 查看器 + 软键盘快捷键 + 命令面板
- **Client desktop**：本机 Agent 控制台 + terminal 工作台 + 后台运行开关

## Terminal 交互目标分层

### UI Layer

- `TerminalScreen` / `TerminalWorkspaceScreen`
- 只负责展示、terminal 选择、焦点、快捷键、IME、布局
- 不直接决定 snapshot 覆盖、reconnect 恢复、geometry owner 策略

### Coordinator Layer

- `TerminalSessionCoordinator`（当前 `TerminalSessionManager` 的目标演进方向）
- 负责 terminal cache、active transport、switch/reconnect/recover 状态机
- 是唯一允许决定 snapshot/live merge、恢复边界、单 view active transport 策略的层
- 内部必须再分为两个子职责，不得继续长成新的上帝类：
  - `TerminalLifecycleCoordinator`：attach / detach / switch / reconnect / active transport 所有权
  - `TerminalRecoveryCoordinator`：snapshot / snapshot_complete / live output 合并、恢复边界、epoch 校验

### Transport Layer

- `WebSocketService`（收瘦后）
- 只负责 WS connect/reconnect/send/receive 和协议事件流
- 输出标准化 terminal events，不直接感知 xterm 本地状态

### Renderer Layer

- 本地 `xterm Terminal` 与后续可能的 renderer handle
- 只负责 local screen buffer、cursor、alt/main buffer 与字节写入
- 不直接接触 websocket 或业务策略
- 客户端必须通过 `RendererAdapter` 包装具体 xterm 实现，对上暴露稳定接口，避免 session/recovery 逻辑直接耦合具体 `xterm Terminal` API

## Terminal 恢复语义

### 恢复源优先级

1. **Agent authoritative snapshot**
   - terminal 恢复的唯一主源
   - attach / reconnect / follower re-enter 都优先向 Agent 请求
2. **Server metadata**
   - 只提供 terminal status / views / geometry owner / pty / recovery_epoch 等控制面真相
   - 不作为 terminal 内容主恢复源
3. **Server output history**
   - 仅用于诊断、审计或极端降级兜底
   - 不得与 Agent snapshot 同时承担 attach 主恢复职责
4. **Client local renderer cache**
   - 仅用于本地 UI 快速切换和短期 continuity
   - 不能向其他客户端传播，也不能被当成跨端真相

### Snapshot 精确定义

`snapshot` 必须指代 **Agent 基于单个 terminal 当前状态导出的恢复包**，不是模糊的“最近输出”。

最低语义要求：

- 绑定单个 `terminal_id`
- 绑定单次恢复会话的 `recovery_epoch`
- 绑定当前 `pty(rows, cols)`
- 明确来源于 `main` 或 `alt` buffer 的当前活动状态
- 包含恢复边界：`snapshot_start ... snapshot_chunk* ... snapshot_complete`
- `snapshot_complete` 之前，客户端不得把 buffered live output 直接写入 renderer

短期允许的实现：

- `snapshot` 可以是“可重建当前 terminal 显示的输出回放包”

长期目标：

- 演进到“screen state + diff”，而不是无限依赖原始输出回放

### Local Cache 精确定义

`local renderer cache` 指客户端单端本地内存中的 renderer 状态：

- local screen buffer
- cursor / scrollback / alt-main buffer
- 当前 renderer 绑定的 `pty` 视图

用途只限于：

- terminal A / B 页面切换后快速恢复本地显示
- reconnect 前短时 continuity

禁止用途：

- 作为跨端同步真相
- 覆盖来自更新 `recovery_epoch` 的权威恢复包
- 在 UI 层直接被清空或重建

## Terminal 时序与 Epoch 机制

每个 terminal 恢复与 live 数据流必须显式绑定以下身份：

- `terminal_id`
- `view_id`（mobile / desktop / terminal-bound transport）
- `attach_epoch`
- `recovery_epoch`

约束：

- 旧 `attach_epoch` 的 `snapshot` / `output` / `resize` 到达时必须被丢弃
- 同一 `recovery_epoch` 内，`snapshot_complete` 之前的 live output 只允许缓冲，不允许直接渲染
- `snapshot_complete` 之后，buffered live output 按顺序回放，再进入 live
- `switch` 只切换 active binding，不创建新的 `recovery_epoch`，除非 transport 确实重连
- `reconnect` 必须生成新的 `attach_epoch`

## Terminal 模式

shared terminal 必须显式区分两种模式，不能用一套策略硬套所有终端：

### Exclusive Mode

- terminal 在单端为主的高频交互场景下运行
- 典型对象：`codex`
- 特征：
  - owner 端优先
  - follower 端默认 observer，不主动抢 geometry
  - 恢复策略更保守，优先保本地 continuity

### Shared Mode

- terminal 在多端共同观察/接管的场景下运行
- 典型对象：普通 shell、`claude` 辅助观察
- 特征：
  - geometry owner 明确
  - follower 端严格跟随 PTY 与 snapshot 恢复
  - attach / re-enter 行为以一致性为先

如果产品层未显式指定，默认策略：

- 高频增量交互型 terminal 默认 `exclusive`
- 只读观察或低频命令型 terminal 默认 `shared`

## Terminal 恢复状态机

```text
idle -> connecting -> recovering -> live
live -> reconnecting -> recovering -> live
live -> switched_away (inactive cache only)
```

约束：

- `switch`：只切 UI 与 active transport，不覆盖 local renderer cache
- `reconnect`：transport 断线后的连接恢复，不等于 UI 切换
- `recover`：仅用于用权威 snapshot 恢复 inactive 或断线后的 terminal 状态
- `recovering` 细分为：
  - `awaiting_connected`
  - `awaiting_snapshot`
  - `buffering_live_output`
  - `snapshot_completed`
- 只有进入 `live` 后，renderer 才可视为与当前 transport 对齐

## Server / Agent 时序真相

### Server 必须维护的控制面真相

- terminal metadata：status / views / pty / geometry_owner_view
- 当前 active transport routing
- attach / recovery epoch 分发边界
- 哪个 snapshot 流属于哪个 attach/recovery 周期

### Agent 必须维护的内容面真相

- terminal runtime
- 当前 terminal 可恢复 snapshot
- snapshot 与 live output 的顺序边界
- terminal 当前活动 buffer 语义（至少能恢复当前显示状态）

Server 不是 terminal 内容真相，但必须是 **会话时序真相**；Agent 不是 routing 真相，但必须是 **terminal 内容恢复真相**。

## Terminal 恢复协议迁移策略

### 兼容窗口

- Server 必须先进入“双协议兼容窗口”
- 在兼容窗口内：
  - 新协议：`snapshot_start / snapshot_chunk / snapshot_complete + attach_epoch/recovery_epoch`
  - 旧协议：原有 `snapshot` / `output` 流保持可消费
- 兼容窗口结束条件：
  - Agent 已切到新恢复协议
  - Desktop / Mobile 主客户端已切到新 coordinator
  - 关键 smoke（Codex / Claude / foreground / cold start / network restore）通过

### 发布顺序

1. **Server first**
   - 先支持双协议与 epoch 字段
   - 不立即移除旧恢复路径
2. **Agent second**
   - 切到 authoritative snapshot + `snapshot_complete`
   - 在兼容窗口内保留向旧 client 降级的能力
3. **Client third**
   - 先落 `WebSocketService` 纯 transport
   - 再落 `Coordinator`
   - 最后收 UI / lifecycle / desktop recovery
4. **Cutover**
   - 只有当三端 smoke 通过后，才移除旧恢复协议消费逻辑

### 降级与回退

- 新 client 连接旧 server / old agent：
  - 必须进入降级路径
  - 不消费不存在的 `snapshot_complete/epoch`
  - recover 语义退化为旧模型，但不得 crash
- 旧 client 连接新 server：
  - Server 在兼容窗口内继续提供旧恢复语义
- 任一阶段 smoke 失败时：
  - 不推进 cutover
  - 保持 server 双协议窗口
  - 回退最近一层 client/agent 变更，而不是继续叠补丁

### 灰度验证点

- `Codex` 高频刷新 + switch/re-enter
- `Claude` 双端 attach + refresh
- app foreground resume
- app cold start recover
- network lost / restore
- agent lost / TTL recover / desktop restart
