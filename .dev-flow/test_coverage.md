# 测试覆盖清单

> 项目：remote-control
> 更新时间：2026-04-12
> 状态：user-info 阶段规划中

## 测试统计

| 模块 | 测试类型 | 数量 | 状态 |
|------|----------|------|------|
| 服务端 | unit, integration | 62 passed | ✅ |
| Agent | unit | 21 passed | ✅ |
| Flutter 客户端 | widget, unit | 15 passed | ✅ |
| Flutter 客户端 (Phase 2) | unit, integration, edge, mock | 已完成 | ✅ |
| Flutter 客户端 (Phase 3) | unit, integration, manual | 已完成 | ✅ |
| Flutter 客户端 (Phase 4) | unit, integration, manual | 已完成 | ✅ |
| Flutter 客户端 (Phase 5) | unit, integration, manual | 已完成 | ✅ |
| 多 terminal 架构 (Phase 6) | unit, integration, manual, e2e | 已完成 | 含真实 e2e/手工联调证据 | ✅ |
| 状态语义收口 (Phase 7) | integration | 已完成 | 含 server/client 定向回归 | ✅ |
| 终端工作台 (Phase 8) | widget, integration | 已完成 | ✅ |
| 创建与关闭语义 (Phase 9) | integration, widget, manual | 已完成 | 含 server/client 定向回归 | ✅ |
| 顶部状态栏瘦身 (Phase 10) | widget, manual | 已完成 | 含 terminal 菜单面板与状态栏回归 | ✅ |
| 设备离线 terminal 收口 (Phase 11) | integration, widget, manual | 已完成 | 含 server 状态机与 workspace 离线回归 | ✅ |
| Agent 本地 Supervisor (Phase 12) | unit, integration | 待开始 | 🔶 |
| Server TTL 机制 (Phase 12) | unit, integration | 待开始 | 🔶 |
| 桌面端平台差异 (Phase 12) | unit, integration | 待开始 | 🔶 |
| PTY 进程组清理 (Phase 14) | unit, integration | 19 passed | ✅ |
| **Agent 生命周期管理 (Phase 15)** | unit, integration, manual | 待开始 | 🔶 |
| **用户信息 (user-info)** | unit, e2e | 待开始 | 🔶 |

## 模块覆盖详情

| Module | Task IDs | Test Type | Required Scenarios | Status |
|--------|----------|-----------|--------------------|--------|
| 共享会话契约 | S001 | integration | 正常契约对齐；connected 消息格式 | ✅ |
| 服务端会话状态 | B001,B002,B005 | unit,integration | 多视图附着；输出广播；输入转发；presence 更新；owner 校验 | ✅ |
| Agent 会话管理 | B003,B004 | unit | 单 PTY 生命周期；登录恢复；token 刷新；错误提示 | ✅ |
| Flutter 终端核心 | F001 | widget,unit | ANSI 渲染；连接状态；presence 同步 | ✅ |
| 桌面端终端窗口 | F002 | widget | 本地窗口可见；视图类型区分 | ✅ |
| 移动端双端共控 | F003 | widget,unit | 连接状态；消息转发；重连设置 | ✅ |
| 双端共控主链路 | S002 | integration | Agent 输出广播；Client 输入转发；presence 同步 | ✅ |
| 发布与部署 | S003 | manual | Docker 健康检查；本地发布 | ✅ |
| 移动端输入修复 | F004 | unit,integration,edge,mock | IME 支持；输入发送；边缘场景 | ✅ |
| TUI 触摸选择 | F005 | unit,integration,edge,mock | 选项检测；按钮生成；选择发送 | ✅ |
| 移动端体验优化 | F006 | integration,mock | 键盘布局；焦点管理；双端共控 | ✅ |
| 移动端快捷键模型 | F007 | unit,manual | profile 解析；动作映射；桌面端不显示 | ✅ |
| 移动端快捷键栏 | F008 | integration,manual | 快捷键发送；IME 稳定；真机 Claude smoke | ✅ |
| 快捷项模型与排序 | F009 | unit,manual | source 分类；固定区/智能区排序；最近使用 | ✅ |
| Claude 默认命令包 | F010 | integration,manual | 默认集；用户调整；恢复默认；本地持久化 | ✅ |
| 项目快捷命令 | F011 | integration | 项目级集合；选择发送；项目间隔离 | ✅ |
| Claude 导航语义 | F012 | integration,manual | 上一项/下一项/确认；映射校准；逐项选择 | ✅ |
| 主题模式切换 | F013 | unit,manual | 主题持久化；登录页/终端页入口；三档切换 | ✅ |
| 命令面板与终端主题 | F014 | integration,manual | 单排核心键；更多命令面板；浅色终端可读性与裁字修复 | ✅ |
| 多 terminal 契约基线 | S011 | integration,manual | device/terminal/view 三层契约；在线 gating；关闭原因 | ✅ |
| 设备在线状态 | B006 | unit | device 注册；心跳；在线/离线状态 | ✅ |
| terminal 状态与上限 | B007 | unit | terminal 元数据；上限校验；状态流转 | ✅ |
| 设备与 terminal API | B008 | integration,mock | 在线设备列表；terminal 列表；创建 gating | ✅ |
| terminal 级 relay | B009 | integration,mock | terminal_id 路由；附着 gating；presence | ✅ |
| 关闭原因与 grace period | B010 | unit | network_lost；agent_shutdown；恢复窗口 | ✅ |
| Agent 多 terminal runtime | B011 | unit,mock,manual | 多 PTY runtime；cwd 启动；独立退出 | ✅ |
| 设备/terminal 选择状态 | F015 | unit,mock | 在线 gating；创建/连接状态；错误分支 | ✅ |
| 设备/terminal 选择 UI | F016 | integration,mock,manual | 设备列表；terminal 列表；禁用态与进入终端页 | ✅ |
| 多 terminal 主链路 | S012 | e2e,manual | 不同 cwd terminal；双端附着；grace period 恢复 | ✅ |
| 状态语义基线 | S013 | integration | 电脑在线定义；实时视图数语义；进入页先拉后端 | ✅ |
| 服务端权威在线态与实时视图数 | B012 | integration | runtime 快照、close gating、实时 views 权威来源 | ✅ |
| Agent 在线稳定性 | B013 | unit,manual | ws/agent 稳定；create_failed 分类；close 后再次 create | ✅ |
| 客户端状态文案与刷新 | F017 | widget,integration,manual | 桌面本机工作台；进入/返回刷新；数量不漂移 | ✅ |
| 终端工作台交互基线 | S014 | integration | workspace 主路径；默认 terminal；空态；tab 语义 | ✅ |
| terminal workspace tabs | F018 | widget,integration | 初始化快照；tab 切换；+ 新建；默认 terminal | ✅ |
| 主入口重构与旧页降级 | F019 | integration | 登录后直达 workspace；旧设备页降级；workspace 内完成创建/关闭 | ✅ |
| 创建与关闭语义基线 | S015 | integration | 创建准入语义；closed cleanup；桌面端 Agent 恢复前置 | ✅ |
| 服务端创建准入与公开配置收口 | B014 | integration | 准入只看在线与上限；PATCH device 不再接受 max_terminals；创建失败语义分离 | ✅ |
| Agent 恢复与 closed 清理 | F015 | integration,manual | 首个 terminal 创建前恢复 Agent；closed terminal 不保留活动连接；close 后可重建 | ✅ |
| workspace 创建/关闭交互 | F020 | widget,manual | 服务端权威可创建态；桌面端首个 terminal 自动恢复 Agent；close 后快照立即更新 | ✅ |
| 顶部状态栏瘦身基线 | S016 | integration | 状态图标、当前 terminal 标题、菜单入口与终端内容区优先 | ✅ |
| 顶部状态栏与 terminal 菜单面板 | F021 | widget,manual | 菜单化的新建/切换/重命名/关闭；顶部不再长期显示 tabs | ✅ |
| tabs 降级与菜单主路径回归 | F022 | widget,manual | 菜单主路径稳定；close 后切换；空态与默认 terminal 不回归 | ✅ |
| 设备离线后的 terminal 收口基线 | S017 | integration | device offline 后 terminal 不再以 attached/detached 活动态出现 | ✅ |
| 服务端离线即清理 terminal 活跃态 | B016 | integration | Agent 断开后 terminal 状态收口、views 清理、活动名额释放 | ✅ |
| 首个 terminal 创建与离线恢复链回归 | B017 | integration,manual | offline -> recover Agent -> create 链路稳定；旧 terminal 不阻塞创建 | ✅ |
| 客户端离线展示与 terminal 可用性对齐 | F023 | widget,manual | workspace 离线时不再展示可连接 terminal；菜单与空态按后端快照对齐 | ✅ |
| 桌面 Agent 后台模式基线 | S018 | integration,manual | 后台运行开关；Agent 所有权；退出语义 | ✅ |
| AgentSupervisor 与优雅停机 | B018 | unit,manual | managed/external Agent 区分；重复启动；优雅停机 | ✅ |
| 桌面端后台运行开关 | F024 | widget,manual | 仅桌面端显示；配置持久化；本机 Agent 状态入口 | ✅ |
| 桌面端退出生命周期 | F025 | widget,manual | 退出桌面端后按开关保留或停止 Agent；手机端在线状态同步 | ✅ |
| **Agent 生命周期管理重构** | **S024,F032-F038** | **unit,integration,manual** | **登录启动/登出关闭/App 启动恢复/关闭应用处理** | ⬜ |

### 日志集成（logging-integration phase）

| Module | Task IDs | Test Type | Required Scenarios | Status |
|--------|----------|-----------|--------------------|--------|
| Server SDK 接入 | B043 | unit,integration | SDK 初始化/启动不可达/默认 URL/handler.close() | ✅ |
| Server 请求中间件 | B044 | unit,integration | 请求日志/Request-ID/异常堆栈/health 跳过/auth 错误透传 | ✅ |
| Server 结构化日志 | B045 | unit,integration | Agent/Client WS 日志/auth 失败日志/并发不阻塞 | ✅ |
| Server Client 日志转发 | B046 | unit,integration | 转发成功/Redis 不影响/SSE 不影响/转发失败静默 | ✅ |
| Agent SDK 接入 | B047 | unit,integration | SDK 初始化/WS 日志/PTY 日志/不可达正常/Desktop 无 LOG_SERVICE_URL | ✅ |
| Docker 标准化 | S028 | integration,manual | deploy 构建启动/health 200/无端口映射/首次部署/Traefik 路由 | ✅ |
| E2E 验证 | S029 | manual,e2e | 三端日志可见/service_name 过滤/Docker+Traefik 正常/重启恢复 | ✅ |
| **日志集成 (Phase logging-integration)** | **unit,integration,manual** | **已完成** | ✅ |

### 用户信息（user-info phase）

| Module | Task IDs | Test Type | Required Scenarios | Status |
|--------|----------|-----------|--------------------|--------|
| 反馈 user_id 修复 + LoginResponse | B056 | unit | feedback user_id 为真实用户名；session 查无→401；session user_id 为空→401；token 无效→401；归属不匹配→404；login/register 响应含 username | ⬜ |
| 用户信息本地存储 | F054 | unit | UserInfoService 读写；rc_login_time 保存/清理；autoLogin 不覆写；username 来自 rc_username | ⬜ |
| 用户信息页面 | F055 | unit | 页面显示用户名/时间；时间格式化；反馈→FeedbackScreen；退出→logoutAndNavigate | ⬜ |
| 菜单去重 | F056 | unit | 三处菜单不含反馈/退出；三处含个人信息入口；导航到 UserProfileScreen | ⬜ |
| 集成测试 | S032 | e2e | 真实 user_id 链路；不同用户隔离；前端菜单结构检查 | ⬜ |

## 关键测试场景覆盖

### Agent 生命周期管理（Phase 15 - 新增）

#### 单元测试（F036）
| 场景 | 描述 | 状态 |
|------|------|------|
| onLoginSuccess-desktop | 桌面端登录成功启动 Agent | ⬜ |
| onLoginSuccess-mobile | 移动端不启动 Agent | ⬜ |
| onLogout | 退出登录关闭 Agent | ⬜ |
| onAppStart-alreadyRunning-sameUser | App 启动恢复已运行的 Agent（同用户） | ⬜ |
| onAppStart-alreadyRunning-differentUser | App 启动关闭旧 Agent 并启动新 Agent | ⬜ |
| onAppStart-notRunning | App 启动启动新 Agent | ⬜ |
| onAppClose-keepRunning | 关闭应用（开关=true）Agent 继续运行 | ⬜ |
| onAppClose-stopRunning | 关闭应用（开关=false）Agent 关闭 | ⬜ |
| ownershipCheck | 判断 Agent 是否属于当前用户 | ⬜ |
| timeout-handling | 启动/关闭超时处理 | ⬜ |

#### 集成测试（F037）
| 场景 | 描述 | 状态 |
|------|------|------|
| login-logout-flow | 完整登录登出流程 | ⬜ |
| app-restart-logged-in | App 重启后恢复登录态和 Agent | ⬜ |
| app-restart-logged-out | App 重启后无登录态 | ⬜ |
| background-switch | 后台运行开关切换 | ⬜ |
| cross-platform | 跨平台行为一致性 | ⬜ |

#### 端到端测试（F038 - 手动）
| 场景 | 验证点 | 状态 |
|------|------|------|
| 真实登录流程 | 真实登录后检查 Agent 进程 | ⬜ |
| 真实登出流程 | 登出后检查 Agent 进程不存在 | ⬜ |
| 真实重启流程 | 重启 App 后 Agent 恢复 | ⬜ |
| 真实关闭流程（开关=false） | 关闭 App 后 Agent 进程不存在 | ⬜ |
| 真实关闭流程（开关=true） | 关闭 App 后 Agent 进程仍存在 | ⬜ |

### CONTRACT-002: Agent Connected 消息
- [x] 消息包含 type, session_id, owner, views, timestamp
- [x] 视图计数正确统计 mobile/desktop

### CONTRACT-003: Client Connected 消息
- [x] 消息包含 type, session_id, agent_online, view, owner, timestamp
- [x] view 参数区分 mobile/desktop

### 多视图 Presence 同步
- [x] get_view_counts 正确返回各视图连接数
- [x] _broadcast_presence 广播到所有客户端和 Agent

### 消息双向转发
- [x] Agent 输出广播到所有客户端
- [x] Client 输入转发到 Agent，包含 source_view

### 移动端快捷键层
- [x] `claude_code` profile 的动作集合与顺序稳定
- [x] 快捷键只在移动端展示，桌面端不渲染
- [x] Esc/Tab/Ctrl/方向键通过现有输入链路发送到终端
- [x] 点击快捷键后中文 IME 和软键盘焦点保持正常

### 快捷项产品化
- [x] 核心固定区与智能区排序策略覆盖
- [x] 默认命令包配置持久化覆盖
- [x] 项目快捷命令选择与发送覆盖
- [x] Claude 导航语义与映射切换覆盖

### 主题与命令面板抛光
- [x] App 内手动切换 `system / light / dark`
- [x] 主题模式本地持久化
- [x] 移动端 `更多` 命令面板展示 Claude 默认命令
- [x] 浅色主题下终端正文可读且左上角不再裁字

### 多 terminal 架构自动化优先策略
- [ ] 先完成 device/terminal 状态模型单元测试
- [ ] 先完成 device/terminal discovery 与 attach gating 的 mock/integration 测试
- [ ] 先完成 Agent multi-terminal runtime 的 mock PTY 测试
- [ ] 再进行真实 PTY 与 Android/macOS 手工 smoke

### 状态语义收口（Phase 7）
- [x] `device_online` 只绑定本机 Agent 在线，不与桌面客户端是否打开混淆
- [x] terminal `views` 由服务端当前活跃连接数提供，不再信任 Redis 历史字段
- [x] 进入 terminal 页与返回列表页时先查后端快照，再依赖 presence 增量更新
- [x] 关闭一个 terminal 后，只要 Agent 在线，仍可继续创建新 terminal

### 终端工作台重构（Phase 8）
- [x] 登录后直接进入 terminal workspace，而不是先停留在设备与 terminal 选择页
- [x] workspace 初始化会先拉取 device + terminal 快照，并选中默认 terminal
- [x] terminal 页顶部 tabs 支持切换、`+` 新建和关闭后同步刷新
- [x] 旧设备/terminal 选择页降级为后备入口，不再充当主路径

### 创建与关闭语义收口（Phase 9）
- [x] 创建 terminal 的前置准入条件只保留"电脑在线 + 当前 terminal 数小于服务端上限"
- [x] 普通 runtime device 更新接口不再接受 `max_terminals`
- [x] 桌面端在本机 Agent 离线且 terminal 数为 0 时，先恢复 Agent 再创建第一个 terminal
- [x] closed terminal 不再维持活动连接记录，也不再参与活动 terminal 数和视图数统计

### 顶部状态栏瘦身（Phase 10）
- [x] 顶部只保留电脑在线/离线状态图标、当前 terminal 标题和菜单入口
- [x] `新建终端` 与 `terminal 切换` 收纳到菜单/面板，不再长期显示 tabs
- [x] terminal 内容区获得更多垂直空间

### 桌面 Agent 后台模式（Phase 12）
- [x] 桌面端与 Agent 生命周期职责分离，桌面端成为本机 Agent 控制台
- [x] `后台保持电脑在线` 开关可本地持久化，并仅在桌面端展示
- [x] 只有桌面端自己拉起的 Agent 会在退出桌面端且开关关闭时被停止
- [x] 外部已存在 Agent 时，桌面端退出不会误杀 Agent
- [x] 退出桌面端后手机端在线状态按开关语义变化，减少假在线窗口

### 桌面 Agent 管理子系统（Phase 13）
- [x] Agent 发现顺序正式化，显式路径/环境变量/固定可发现路径覆盖清晰
- [x] `DesktopAgentManager` 单元测试覆盖 managed/external/startFailed 与单实例保护
- [x] `DesktopWorkspaceController` widget/state 测试覆盖 header/body/action 同一状态源
- [x] "启动本机 Agent -> 创建第一个 terminal" 两阶段链路有自动化覆盖
- [x] macOS 真机 smoke 覆盖桌面端首次启动、失败重试与手机端在线状态一致性

### 桌面空工作台归一化（Phase 13 Patch）
- [x] 关闭最后一个 terminal 后，历史 `createFailed` 不会继续污染空工作台
- [x] 空工作台会重新回到 `readyToCreateFirstTerminal / bootstrappingAgent / createFailed` 的当前态
- [x] 自动化覆盖"关闭最后一个 terminal -> 再次创建第一个 terminal"的回归路径

### Agent 本地 HTTP Supervisor（Phase 12）
- [x] Agent 启动时成功绑定端口 18765-18769 之一
- [x] GET /health 返回正确响应
- [x] GET /status 返回完整 Agent 状态
- [x] POST /stop 能触发优雅关闭
- [x] POST /config 能更新 keep_running 配置
- [x] 状态文件写入平台标准目录
- [x] 端口冲突时能正确处理

### Server 端 Agent 状态 TTL 机制（Phase 12）
- [x] WebSocket 断开时 Agent 状态标记为 stale
- [x] 心跳刷新 Agent 状态 TTL
- [x] TTL 过期后状态自动变为 offline
- [x] Agent 重连时能恢复在线状态

### 桌面端平台差异（Phase 12）
- [x] 桌面端（macOS/Linux/Windows）识别为本地 Agent 主机
- [x] 手机端（iOS/Android）识别为远程查看器
- [x] 后台运行开关只在桌面端显示
- [x] 手机端退出只断开 WebSocket，不影响远程 Agent
- [x] 桌面端退出根据开关决定是否停止 Agent

### Agent 终端管理系统性重构（Phase 12 集成）
- [x] Agent 重连后能恢复到正确状态
- [x] 桌面端关闭最后一个 terminal 后能再次创建
- [x] 手机端能正确显示远程设备的 Agent 状态
- [x] 状态文件孤儿进程检测和清理

### PTY 进程组清理（Phase 14）
- [x] **B032 进程组清理**：PTYWrapper.stop() 使用 os.killpg() 杀死整个进程组
  - [x] 杀死进程组时所有子孙进程都收到信号
  - [x] 进程组不存在时错误被正确处理（不抛异常）
  - [x] 不再残留孤儿进程
- [x] **B033 超时强制终止**：SIGTERM 发送后 3 秒超时，发送 SIGKILL
  - [x] 正常终止时不触发 SIGKILL
  - [x] 超时后发送 SIGKILL 到整个进程组
  - [x] SIGKILL 后进程被 waitpid 正确回收
  - [x] 强制终止失败时记录错误日志
- [x] **B034 资源清理完整性**：确保 fd、异步任务、内存完整清理
  - [x] 关闭 fd 前先取消正在运行的异步读取任务
  - [x] master_fd 和 slave_fd 都被正确关闭
  - [x] 清理后 self.master_fd/slave_fd/pid/_running 都被重置
  - [x] 多次调用 stop() 不会出错
- [x] **B035 集成测试**：覆盖多层子进程和异常场景
  - [x] 多层子进程场景（shell -> bash -> sleep）能全部清理
  - [x] shell 脚本创建子进程的场景
  - [x] SIGTERM 被忽略时 SIGKILL 能强制终止
  - [x] 网络断开触发的终端关闭流程
  - [x] Agent 断开后的终端清理
