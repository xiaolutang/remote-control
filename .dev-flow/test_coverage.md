# 测试覆盖清单

> 项目：remote-control
> 更新时间：2026-04-25
> 状态：R043 已归档；`agent-eval-system`（R044）为当前活跃需求周期

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
| **用户信息 (user-info)** | unit, e2e | 已完成 | ✅ |
| **部署标准化 (deploy-standardization)** | manual, L3 | 已完成 | ✅ |
| **安全加固 (security-hardening)** | unit, integration, manual | 待开始 | 🔶 |
| **环境选择 (env-selector)** | unit | 24 passed | ✅ |
| **终端 P0 修复 (terminal-p0-fixes)** | unit, widget, integration, smoke | 已完成 | ✅ |
| **终端交互架构重构 (terminal-interaction-refactor)** | design, unit, integration, widget, smoke | 已完成 | ✅ |
| **智能终端进入 (intelligent-terminal-entry)** | design, unit, widget, integration, manual | 已完成 | ✅ |
| **命令规划隔离 (planner-provider-isolation)** | design, unit, integration, manual | 已完成 | ✅ |
| **聊天式智能终端助手 (chat-terminal-assistant)** | design, contract, unit, integration, manual, smoke | 前置基线已收口，剩余验收并入当前阶段 | 🔶 |
| **ReAct 智能体 (react-terminal-agent)** | design, unit, integration, widget, manual, smoke | 执行中 | 🔶 |
| **Terminal-bound Agent 对话同步 (react-terminal-agent patch)** | contract, unit, integration, widget, e2e, smoke | 已规划 | ⬜ |
| **Agent 知识增强 (agent-knowledge)** | unit, integration, smoke | 已完成 | ✅ |
| **Agent 评估体系 (agent-eval-system)** | unit, integration | 已规划 | ⬜ |

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
| 反馈 user_id 修复 + LoginResponse | B056 | unit | feedback user_id 为真实用户名；session 查无→401；session user_id 为空→401；token 无效→401；归属不匹配→404；login/register 响应含 username | ✅ |
| 用户信息本地存储 | F054 | unit | UserInfoService 读写；rc_login_time 保存/清理；autoLogin 不覆写；username 来自 rc_username | ✅ |
| 用户信息页面 | F055 | unit | 页面显示用户名/时间；时间格式化；反馈→FeedbackScreen；退出→logoutAndNavigate | ✅ |
| 菜单去重 | F056 | unit | 三处菜单不含反馈/退出；三处含个人信息入口；导航到 UserProfileScreen | ✅ |
| 集成测试 | S032 | e2e | 真实 user_id 链路；不同用户隔离；前端菜单结构检查 | ✅ |

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

### 终端交互架构重构（terminal-interaction-refactor phase）

| Module | Task IDs | Test Type | Required Scenarios | Status |
|--------|----------|-----------|--------------------|--------|
| 终端交互架构基线 | S071 | design | 四层职责边界；状态源矩阵；switch/reconnect/recover 状态机 | 🔶 |
| 恢复语义与模式基线 | S072 | design | snapshot/local cache/live output 边界；attach/recovery epoch；exclusive/shared mode | 🔶 |
| 协议兼容迁移与灰度切换 | S073 | design | 新旧恢复协议共存窗口；发布顺序；回退策略；灰度验证点 | 🔶 |
| Server 状态中心收瘦 | B071 | integration | metadata/ownership/pty/routing 真相；history 不再做 attach 主恢复源 | 🔶 |
| Agent 主权威恢复源 | B072 | unit,integration | per-terminal snapshot 生命周期；close/recreate 不污染旧 snapshot | 🔶 |
| 恢复协议升级 | B073 | integration,smoke | connected -> snapshot_start/chunk/complete -> live；空 snapshot 边界 | 🔶 |
| Client Transport 收瘦 | F071 | unit | transport events 标准化；不再承载恢复策略 | ✅ 33/33 |
| Client Coordinator 状态机 | F072 | unit,integration,smoke | switch/reconnect/recover 分离；单 active transport；Codex/Claude 切换恢复 | ✅ 60/60 (smoke 待 F074 集成) |
| Renderer 隔离 | F073 | unit | RendererAdapter；snapshot/live apply 路径统一 | 🔶 |
| UI 瘦身迁移 | F074 | widget,smoke | 页面只做展示/焦点/快捷键/IME；不再直接管 recover | 🔶 |
| 桌面端 Agent 断连恢复编排 | F075 | integration,smoke | agent 断连 TTL 恢复；app 前后台；app 重启；agent 重启与 terminal 恢复 | 🔶 |
| 客户端生命周期恢复编排 | F076 | integration,smoke | foreground/cold start/network restore 统一恢复链 | 🔶 |
| 智能终端进入产品基线 | S077 | design | Claude-only 入口；`CommandSequence` 字段稳定；先确认后执行 | 🔶 |
| 智能创建入口 UI | F077 | widget,manual | 单输入框；命令步骤预览；确认按钮；移动端首用理解成本 | 🔶 |
| 输入辅助与默认提示 | F078 | unit | recent terminal 提示；默认文案；空缓存/坏缓存回退 | 🔶 |
| 一句话意图编排 | F079 | unit,integration | 短句 -> `CommandSequence`；确认分支；边界输入；无新服务端 LLM 依赖 | 🔶 |
| 创建链路统一收口 | F080 | integration | runtime/workspace 双入口共用 createTerminal + execute sequence；offline/上限/5xx 失败保留输入 | 🔶 |
| 智能终端进入验证 | F081 | widget,integration,manual | 命令预览/确认/手动回退三链路；手机端 Claude 首用 smoke | 🔶 |

#### 终端交互重构关键场景

- [ ] switch terminal 不触发 recover，不覆盖 local renderer cache
- [ ] reconnect 必须生成新的 `attach_epoch`
- [ ] `snapshot_complete` 前 live output 只缓冲
- [ ] 旧 `attach_epoch/recovery_epoch` 的迟到消息被丢弃
- [ ] 兼容迁移窗口内新旧 client/desktop 与 server/agent 有明确降级路径
- [ ] `Codex` 在 exclusive 模式下切换/刷新不再丢内容
- [ ] `Claude` 在 shared 模式下双端 attach 后布局与恢复一致
- [ ] app 从后台回前台后 active terminal 正确 recover
- [ ] app 被杀后重启，通过 Agent 权威 snapshot 恢复 terminal
- [ ] agent 与 server 断连后进入 recoverable，不立刻 closed；TTL 超时后再 closed

### 智能终端进入（intelligent-terminal-entry phase）

| Module | Task IDs | Test Type | Required Scenarios | Status |
|--------|----------|-----------|--------------------|--------|
| 智能终端进入产品基线 | S077 | design | Claude-only 主路径；`CommandSequence`；确认后执行；高级配置兜底 | 🔶 |
| 智能创建入口 UI | F077 | widget,manual | 单输入框、命令步骤预览、确认按钮、移动端小屏稳定 | 🔶 |
| 输入辅助与默认提示 | F078 | unit | recent terminal 提示；默认文案；空历史/坏缓存安全回退 | 🔶 |
| 一句话意图编排 | F079 | unit,integration | 自然语言转 `CommandSequence`；步骤可读；超长/特殊字符输入安全处理 | 🔶 |
| 创建与执行链路收口 | F080 | integration | workspace/runtime 两入口一致；创建 terminal 后执行同一命令序列；失败保留输入 | 🔶 |
| 自动化与首用 smoke | F081 | widget,integration,manual | 确认执行、失败停后续步骤、手动回退、手机端首用不依赖长输入 | 🔶 |

### 命令规划隔离（planner-provider-isolation phase）

| Module | Task IDs | Test Type | Required Scenarios | Status |
|--------|----------|-----------|--------------------|--------|
| provider 隔离基线 | S078 | design | `CommandPlanner` / `PlannerCoordinator` 边界；product 与 provider 解耦 | 🔶 |
| 本地 planner bridge | B074 | integration | 当前设备侧调用 Claude CLI；Server/Agent 不解析自然语言 | 🔶 |
| planner 状态与失败反馈 UI | F086 | widget,integration | 展示 provider/fallback/unavailable 原因；主 UI 不暴露 provider 选择 | 🔶 |
| 命令序列预览与用户编辑 | F082 | unit,integration | 用户编辑步骤后执行以编辑结果为准；确认态稳定 | 🔶 |
| Claude CLI planner provider | F083 | unit,integration | `claude -p` 输出归一化为 `CommandSequence`；命令越界被拦截 | 🔶 |
| planner coordinator 与 fallback | F084 | unit,integration | `claude -p` 不可用/超时/违规时回退 `local_rules` | 🔶 |
| 端到端回归与真实设备 smoke | F085 | integration,manual | macOS/Android 真机验证确认执行与 fallback 链路 | 🔶 |

#### 智能终端进入关键测试场景

- [ ] 输入“进入 remote-control 项目修登录问题”后可生成 `pwd -> find -> cd -> claude` 这类 `CommandSequence`
- [ ] 命令预览包含 `summary/provider/steps/need_confirm`，且用户确认前不会执行
- [ ] 高级配置或手动编辑步骤后，最终执行使用用户编辑结果，而不是覆盖回 planner 原结果
- [ ] runtime selection 与 workspace 两个入口的创建和执行行为一致
- [ ] `createTerminal` 在 `offline` / `terminal 上限` / `5xx` 下都会保留原输入与命令序列
- [ ] 执行时 `cd` 对后续步骤生效，证明所有步骤处于同一个 shell session
- [ ] 任一步返回失败时停止后续步骤，不会继续执行 `claude`
- [ ] `claude` 命令不存在时，用户仍留在 shell 且能看到失败回显
- [ ] 手机端首用场景中，用户不必手输完整 `cwd/command`

#### 命令规划隔离关键测试场景

- [ ] `claude -p` 输出可以稳定归一化为 `CommandSequence`
- [ ] `claude -p` 不可用、超时、空输出或非法输出时会稳定回退 `local_rules`
- [ ] provider 返回危险命令、越界路径或不可解释步骤时，不会直接执行
- [ ] UI 不暴露 provider 选择，但调试信息能显示当前使用的 provider/fallback
- [ ] planner 不会依赖开发机固定目录；不同用户机器上都通过 shell 发现步骤定位项目
- [ ] 真机与桌面端联调时，用户确认后能成功进入 Claude，失败链路也能回退手动创建

### 聊天式智能终端助手（chat-terminal-assistant phase，前置基线）

| Module | Task IDs | Test Type | Required Scenarios | Status |
|--------|----------|-----------|--------------------|--------|
| 产品与评估基线 | S079, S080 | design | 聊天流 + 命令卡片；结构化 trace；评估指标与人工验收口径 | S079 ✅ / S080 ⬜ |
| 服务端 planner / memory / 回写契约 | B075, B076, B077 | integration,contract,unit | `assistant/plan`、`executions/report`、memory 只在真实回写后更新 | ✅ |
| 桌面空终端与侧滑面板骨架 | F094, F087 | widget,integration,manual | 空终端创建；侧滑面板入口；桌面/移动端分流稳定 | ✅ |
| 旧聊天流 UI / fallback / 注入链路 | F088_old, F089_old, F090, F093 | widget,integration | 已被 `react-terminal-agent` 收口替代，不再继续执行。注：F088/F089 已在 R043 增量中复用为新任务 | cancelled |
| benchmark 与真机验收 | F091, F092 | unit,integration,manual,smoke | benchmark 数据集；trace 回放；全链路人工验收 | ⬜ |

### ReAct 智能体（react-terminal-agent phase，当前执行阶段）

| Module | Task IDs | Test Type | Required Scenarios | Status |
|--------|----------|-----------|--------------------|--------|
| 架构与只读探索基线 | S081 | design | 权威边界、只读探索安全边界、三层降级策略 | ✅ |
| 只读探索协议与 Agent 核心 | B078, B079 | unit,integration | execute_command 白名单；Pydantic AI Agent；攻击向量拦截 | ✅ |
| Agent 会话与 SSE 事件流 | B080, F095 | unit,integration | run/respond/cancel/resume；事件解析；断连恢复；降级到 planner | ✅ |
| 侧滑面板 Agent 交互与命令注入 | F096, F097, F098 | widget,integration | exploring/asking/result/error；命令注入；执行结果回写与别名保存 | ✅ |
| Agent 集成测试 | S082 | integration,manual | Happy path；安全边界；mobile 回归；per-device 隔离 | ✅ |
| Token usage SSE 与前端兼容 | B083, F099 | unit,widget | SSE result usage；前端解析与兼容展示 | ✅ |
| usage 汇总 API 与 Toast 浮层 | B084, F100 | unit,integration,widget | usage 落库；双 scope 汇总；Toast 浮层与自动刷新 | B084 ✅ / F100 ✅ |
| Terminal-bound conversation 契约 | S083 | contract | conversation 与 terminal 一一对应；close 即销毁；手机端无本地工具 | ⬜ |
| conversation 持久化与权限 | B085 | unit,integration | agent_conversations/events；event_index；跨用户/跨 terminal 隔离；client_event_id 幂等；question_id 冲突；tombstone cleanup | ✅ 29/29 |
| Agent API terminal 绑定 | B086 | integration | run/respond/resume/cancel 绑定 device_id + terminal_id + session_id；旧 conversation_id 不作权威；question_id/client_event_id 幂等与冲突 | ✅ 7/7 targeted, 129/129 regression |
| conversation fetch/stream | B087 | integration | GET 投影；SSE after_index；多端新增事件可见；无 conversation 空投影；权限边界 | ✅ 4 targeted, 133/133 regression |
| message_history 与 close cleanup | B088 | integration | server events 重建 message_history；terminal close 删除 conversation 并取消 session；closed fetch 410；closed stream fanout | ✅ 4 targeted, 137/137 regression |
| 客户端服务端投影 | F101 | widget,unit | 智能面板加载 server events；本地 history 仅做渲染缓存；active question 恢复；terminal 切换隔离；conversation_id 复用服务端权威值 | ✅ `test/services/agent_session_service_test.dart` + `test/widgets/smart_terminal_side_panel_agent_test.dart` passed |
| 双端同步 UI | F102 | widget,manual | Android/macOS 同 terminal 对话同步；closed 后禁用智能输入；不冲突正常终端输入 | ✅ widget: `test/services/agent_session_service_test.dart` + `test/widgets/smart_terminal_side_panel_agent_test.dart` passed; manual smoke deferred to `S084` |
| 全链路验收 | S084 | e2e,smoke | 本地 Docker + macOS + Android；权限隔离；多 terminal 隔离；close 销毁 | 🔄 automated: `server/tests/test_integration.py` targeted 7 passed + Flutter smart-panel tests passed; manual Android/macOS smoke in progress |

#### Terminal-bound Agent 对话关键测试场景

- [ ] 手机端发起 Agent 对话后，桌面端打开同一 terminal 能看到相同 `user_intent/question/answer/result` 事件
- [ ] 桌面端回答 Agent 选项后，手机端刷新或订阅能看到该回答与后续 result
- [x] 用户第一轮选择过项目后，第二轮输入“这个项目”时，服务端传给 `run_agent` 的 `message_history` 包含上一轮选择
- [ ] terminal close 后，conversation events 被删除或标记不可用，旧 `respond/resume/fetch` 返回 closed/not_found 稳定错误
- [x] terminal A/B 同时存在时，A 的对话历史不会进入 B 的 `message_history`
- [x] 未授权用户不能 fetch/stream/respond 其他用户的 terminal conversation
- [ ] respond/cancel/resume 必须校验 terminal-scoped `session_id`；其他 terminal 的 session_id 返回 404
- [ ] 弱网重复提交同一 `client_event_id` 不会追加重复 answer 事件
- [ ] 手机端和桌面端同时回答同一 `question_id` 时，只有第一个成功，第二个返回 409 `question_already_answered`
- [ ] terminal close 先广播 `closed` 给 active stream，再取消 session 并进入短 tombstone；tombstone 期间 fetch 不返回历史
- [ ] 移动端智能输入框弹出软键盘时不影响正常 terminal 输入焦点，不触发全局 PTY resize
- [ ] 手机端不启动、不展示、不调用任何本地 ReAct 工具运行时；工具执行仍走 Server → 桌面设备 Agent

#### 聊天式智能终端助手关键测试场景

- [ ] 输入“进入 remote-control 修登录问题”后，对话流会展示“读取上下文 -> 调用 LLM -> 安全校验 -> 生成命令”阶段
- [ ] 聊天流只展示结构化分析摘要和工具结果，不展示模型原始 chain-of-thought
- [ ] 同一个目标在命中 recent project、pinned project、无记忆三种上下文下，最终命令序列按预期分化
- [ ] `service_llm` 成功时，命令卡片来自服务端规划结果；`claude_cli`/`local_rules` fallback 时，聊天流会显示明确回退节点
- [ ] `assistant/plan` 触发限流、预算/配额受限、provider timeout 时，客户端能收到稳定错误并继续 fallback 或手动创建
- [ ] 命令卡片支持编辑，用户编辑后的命令序列才是最终执行产物
- [ ] 用户确认后，聊天流会追加“创建 terminal / 执行命令 / 已进入 Claude”状态，而不是静默跳转
- [ ] `cd` 对后续 `claude` 生效，证明仍在同一个 shell session 中执行
- [ ] 执行完成后会调用 `executions/report` 回写最终状态；服务端只在回写成功后更新 planner memory
- [ ] 同一句输入在不同设备上会依据各自 planner memory / current-device context 生成不同命令，不会串用其他设备历史
- [ ] benchmark 数据集能输出至少这些指标：命中率、fallback 率、命令安全拦截率、执行成功率、平均规划耗时
- [ ] 每次规划都能被 trace 回放，支持人工核对“输入 -> 上下文 -> trace -> 命令 -> 执行结果”

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

### 部署标准化（deploy-standardization phase）

| Module | Task IDs | Test Type | Required Scenarios | Status |
|--------|----------|-----------|--------------------|--------|
| 多阶段 Dockerfile | S034 | manual, L3 | server/agent 构建成功；runtime 无 gcc | ✅ |
| build.sh + compose | S035 | manual, L3 | build.sh all/server/agent/--no-cache；compose 引用镜像 | ✅ |
| deploy.sh + 清理 | S036 | manual, L3 | 旧文件已删除；deploy.sh 端到端；.dockerignore 完整 | ✅ |

#### 部署验证场景
- [x] `docker build -f deploy/server.Dockerfile .` 构建成功（2026-04-13 验证，325MB）
- [x] `docker build -f deploy/agent.Dockerfile .` 构建成功（2026-04-13 验证，288MB）
- [x] `docker run --rm --entrypoint which remote-control-server:latest gcc` 返回非零（2026-04-13 验证）
- [x] `./deploy/build.sh` 构建两个镜像均成功（2026-04-13 验证）
- [x] `./deploy/build.sh server` 只构建 server（2026-04-13 验证）
- [x] `./deploy/build.sh nonexistent` 无效参数正确拒绝 exit 1（2026-04-13 验证）
- [x] `./deploy/deploy.sh` 端到端部署成功（2026-04-13 验证）
- [x] `curl http://localhost/rc/health` 返回 200（2026-04-13 验证）

### PTY 进程组清理（Phase 14）(原文)
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

### 安全加固（security-hardening phase）

| Module | Task IDs | Test Type | Required Scenarios | Status |
|--------|----------|-----------|--------------------|--------|
| JWT Secret 加固 | B062 | unit | JWT_SECRET 未设置→启动抛异常；无 token_version→401；匹配 Redis→通过；不匹配→401 TOKEN_REPLACED | ⬜ |
| 密码哈希迁移 | B063 | unit | 新注册→bcrypt；旧 SHA-256 登录→自动迁移；并发迁移不报错 | ⬜ |
| CORS 收紧 | B064 | unit | CORS_ORIGINS 空→拒绝；配置域名→通过；非配置域名→拒绝 | ⬜ |
| WebSocket 鉴权重构 | B065 | unit,integration | auth 消息→成功；无效 token→关闭；超时→关闭；超大消息→关闭；auth 格式错误→关闭；URL query token→不验证 | ⬜ |
| 日志归属校验 + 错误脱敏 | B066 | unit | 查自己日志→成功；查他人→403；JWT 错误→脱敏信息 | ⬜ |
| 速率限制 | B067 | unit | 10次内→成功；第11次→429；限流 Redis 失败→不限速；认证 Redis 失败→503 | ⬜ |
| Agent 安全加固 | B068 | unit,integration | WS auth 适配；命令/cwd/env 校验；本地 HTTP 认证；配置文件生成/损坏恢复 | ⬜ |
| Client 安全加固 | F058 | unit,integration | WS auth 适配；密码迁移到 flutter_secure_storage；旧 SharedPreferences 清理；自动登录失败回退 | ⬜ |
| Redis 密码 + Docker 非 root | B070 | integration,manual | Redis 密码认证；非 root 运行；REDIS_PASSWORD 缺失→报错；volume 权限 | ⬜ |
| 安全加固集成验证 | S038 | integration,manual | 全链路注册→登录→WS→terminal→关闭；bcrypt 验证；速率限制；WS auth；脱敏；Redis 密码；非 root；CORS | ⬜ |

### 环境选择（env-selector phase）

| Module | Task IDs | Test Type | Required Scenarios | Status |
|--------|----------|-----------|--------------------|--------|
| 环境模型与选择服务 | F059 | unit | 默认环境、serverUrl 生成、持久化、首次安装/损坏数据、输入校验(host/port)、无副作用依赖 | ✅ |

### IP 直连绕过 TLS（ip-direct phase）

| Module | Task IDs | Test Type | Required Scenarios | Status |
|--------|----------|-----------|--------------------|--------|
| 本地 URL 修复 + 直连端口 | S063 | unit, integration | URL 格式修正(ws://)；端口映射配置；RSA+AES 加密链路；HTTP URL 转换 | ✅ |
| 直连端口部署验证 | S064 | integration, manual | 线上端口可达；真机直连登录；Agent 注册；TLS 环境不受影响 | ⬜ |

#### IP 直连关键测试场景

##### S063 失败分支
- [x] RC_DIRECT_PORT 未注入时使用默认 8880
- [x] RC_DIRECT_PORT 指定已被占用端口时 Server 启动失败
- [x] ws:// 连接超时（防火墙未开放）客户端提示明确
- [x] ws:// → http:// URL 转换异常处理
- [x] 环境切换（local→direct→production）时旧 WS 连接正确断开

##### S064 线上 smoke
- [ ] 真机直连 IP:8880 → 登录成功 → 终端收发
- [ ] 桌面端直连 IP:8880 → 登录成功 → 终端收发
- [ ] Agent 注册正常 → 设备在线
- [ ] TLS 线上环境同时可用

### 终端 P0 修复（terminal-p0-fixes phase）

| Module | Task IDs | Test Type | Required Scenarios | Status |
|--------|----------|-----------|--------------------|--------|
| CPR 坐标修复 | F067 | unit,smoke | CSI 6n 响应严格 1-based；Codex/Claude Code TUI 不退化；vim/top 回归 | ⬜ |
| 渲染闪烁修复 | F068 | unit,integration | 移除多余 setState；高频输出无闪烁；输入输出链路不回归 | ⬜ |
| 移动端键盘 resize 隔离 | F069 | unit,integration,smoke | 移动端弹收键盘不触发全局 PTY resize；桌面端布局不受影响；提示符仍可见 | ⬜ |
| 终端切换白屏修复 | F070 | unit,integration,smoke | Terminal 实例缓存复用；切换无白屏；登出/换用户缓存清空 | ⬜ |

#### 终端 P0 关键测试场景

##### F067 协议兼容
- [ ] `cursorPosition(0, 0) -> ESC[1;1R`
- [ ] `cursorPosition(5, 3) -> ESC[6;4R`
- [ ] 连续 CSI 6n 响应保持 1-based，无状态泄漏
- [ ] Codex/Claude Code/vim/top 不出现单行重绘退化

##### F069 首次使用与状态同步
- [ ] 手机弹键盘时不发送 resize 到远端 PTY
- [ ] 手机收键盘时不发送 resize 到远端 PTY
- [ ] 手机连续弹收键盘 3 次，桌面端布局保持稳定
- [ ] 移动端输入仍可用，底部提示符不被键盘永久遮挡

##### F070 缓存生命周期
- [ ] terminal A -> B -> A 快速切换 3 次无白屏
- [ ] 切回 A 时 scrollback 仍在
- [ ] disconnectAll/logout/session reset 后 Terminal 缓存清空
- [ ] 切换到断开终端时展示明确状态，不展示空白页

### 终端交互架构重构（terminal-interaction-refactor phase）

| Module | Task IDs | Test Type | Required Scenarios | Status |
|--------|----------|-----------|--------------------|--------|
| 架构基线与状态机 | S071 | design | 四层职责边界；状态源矩阵；switch/reconnect/recover 状态机 | ⬜ |
| Server 状态中心收瘦 | B071 | integration | metadata/ownership/pty 真相；history 降级为诊断用途 | ⬜ |
| Agent 主权威恢复源 | B072 | unit,integration | per-terminal snapshot 生命周期；snapshot_request 主路径 | ⬜ |
| 恢复协议升级 | B073 | integration,smoke | snapshot/snapshot_complete/live 边界；刷新后一致性 | ⬜ |
| Client Transport 收瘦 | F071 | unit | protocol events only；不承载 renderer/recovery 语义 | ⬜ |
| Client Coordinator 状态机 | F072 | unit,integration,smoke | 单 active transport；switch/reconnect/recover 分离 | ⬜ |
| Renderer 隔离 | F073 | unit | xterm handle 收口；snapshot/live apply 路径统一 | ⬜ |
| UI 瘦身迁移 | F074 | widget,manual | TerminalScreen/Workspace 只做展示与交互 | ⬜ |

#### 终端交互架构重构关键测试场景

##### S071 设计验收
- [ ] 输出四层职责图（UI / Coordinator / Transport / Renderer）
- [ ] 输出状态源矩阵（PTY / metadata / local renderer）
- [ ] 输出 switch / reconnect / recover 状态机

##### B073 恢复协议
- [ ] `connected -> snapshot* -> snapshot_complete -> live output` 顺序明确
- [ ] 空 snapshot 时仍发送 `snapshot_complete`
- [ ] 刷新后桌面端与移动端内容不再长期偏离

##### F072 Coordinator
- [ ] 同一 client view 同时只有一个 active terminal transport
- [ ] switch terminal 不触发 snapshot 覆盖已有 renderer
- [ ] reconnect 才进入 recovering
- [ ] Codex 高频刷新与切换场景内容不再明显丢失

### Agent 评估体系（agent-eval-system phase，R044）

| Module | Task IDs | Test Type | Required Scenarios | Status |
|--------|----------|-----------|--------------------|--------|
| Eval 数据模型 + SQLite | B096, S089 | unit | 模型序列化；SQLite CRUD；配置缺失拦截 | B096 ✅ 56/56; S089 ✅ 验收通过 |
| Eval Harness 核心 | B097, S089 | unit, integration | YAML 加载；mock transport；transcript 收集；pass@k/pass^k | B097 ✅ 56/56 |
| Code-based Graders | B098, S090 | unit | 5 种 grader pass/fail；command_safety 复用验证 | B098 ✅ 49/49 |
| 初始 Task 数据集 | B099 | unit | 30 个 YAML 格式校验；加载集成 | ⬜ |
| LLM-as-Judge | B100, S090 | unit, integration | prompt 输出格式；JSON 解析容错；未配置降级 | ⬜ |
| 质量指标提取 | B101, S091 | unit | 5 类指标计算准确性；批量提取；历史回溯 | ⬜ |
| 质量指标 API | B102, S091 | unit, integration | 过滤/聚合；认证拦截；evals.db 不可达时返回 500 | ⬜ |
| 反馈→Eval Task | B103, S092 | unit, integration | 反馈→candidate 流程；未配置降级；审核 API | ⬜ |
| 回归测试 + CLI | B104, S092 | unit, integration | 回归检测；趋势查询；CLI 子命令；配置缺失提示 | ⬜ |

#### Agent 评估体系关键测试场景

##### B097 Harness
- [ ] YAML task 正确加载为 EvalTaskDef
- [ ] mock transport 按预定义响应返回
- [ ] 单 trial 完整 transcript 收集（LLM 请求/响应 + 工具调用/返回 + AgentResult）
- [ ] pass@1 = 60% 时 pass@5 应接近 100%（数学验证）
- [ ] EVAL_AGENT_MODEL/BASE_URL/API_KEY 缺失时 raise 明确错误，不复用 ASSISTANT_LLM_*
- [ ] mock transport 不触达真实设备（无真实 WebSocket 连接）
- [ ] LLM 超时/5xx/畸形响应：harness 捕获异常并标记 trial 为 error，不 crash
- [ ] 单 trial 失败不阻塞后续 trial 执行

##### B098 Code Graders
- [ ] response_type_match: acceptable_types=["command","ai_prompt"] → command 通过
- [ ] response_type_match: acceptable_types=["message"] → command 失败
- [ ] command_safety: 白名单命令通过，`rm -rf` 失败，`sudo` 失败
- [ ] contains_command: steps 包含 "claude" 通过，不包含 "rm" 通过
- [ ] steps_structure: 空 steps 失败，非 shell 命令失败

##### B100 LLM Judge
- [ ] Judge prompt 输出合法 JSON（relevance/completeness/safety/helpfulness）
- [ ] JSON 解析失败时 grader 返回 error 而非 crash
- [ ] EVAL_JUDGE_MODEL 未配置时返回 skipped
- [ ] EVAL_JUDGE_BASE_URL/API_KEY 默认复用 EVAL_AGENT_BASE_URL/API_KEY
- [ ] LLM Judge 超时/5xx：grader 捕获异常并返回 error，不阻塞其他 grader
- [ ] LLM 返回非法 JSON 或截断响应：grader 降级返回 error 而非 crash

##### B101 质量指标
- [ ] 构造已知 session，验证 5 类指标计算正确
- [ ] batch 提取不影响在线 Agent 性能
- [ ] 历史数据可回溯提取
- [ ] quality_monitor 只读 agent_conversation_events 元数据，不读对话文本
- [ ] 指标只写 evals.db，不写 app.db

##### B102 质量指标 API
- [ ] 查询已持久化指标，不依赖模型环境变量
- [ ] 未认证请求返回 401
- [ ] evals.db 不可达时返回 500 + 明确错误

##### B103 反馈闭环
- [ ] 反馈→candidate 只传脱敏摘要，不传原始反馈文本
- [ ] candidate 的 source_feedback_id 仅存引用 ID
- [ ] approved candidate 可被 harness 加载执行
- [ ] EVAL_FEEDBACK_MODEL 未配置时跳过自动转换
- [ ] 异步分析超时/LLM 5xx：分析失败不阻塞反馈保存，记录 warning
- [ ] LLM 畸形响应：解析失败时跳过 candidate 生成，不 crash

### Agent 知识增强（agent-knowledge phase）

| Module | Task IDs | Test Type | Required Scenarios | Status |
|--------|----------|-----------|--------------------|--------|
| Agent prompt 增强 | B089 | unit, integration | SYSTEM_PROMPT 含 lookup_knowledge 描述 + Claude Code 映射 + 信息型问答边界 + lookup_knowledge 跨端集成验证（in S085） | ⬜ |
| lookup_knowledge 工具 | B091 | unit, smoke | 知识检索命中/未命中/空目录 + 内置文件完整性 + 用户自定义文件 + built-in catalog entry 上报 | ⬜ |
| MCP Client 框架 | B092 | unit, integration, smoke | Skill 注册表 + MCP Server 生命周期 + 工具调用中转 + snapshot 重启生效 | ⬜ |
| Server 动态工具注册 | B093 | unit, integration, smoke | 工具注册/注入/路由 + built-in 优先 + 断连清理 + capability 限制 + payload 截断 + 版本前提 | ⬜ |
| Server 端测试 | S085 | unit, integration, smoke | prompt 增强 + 旅程边界 + 降级 + 动态工具 + 优先级 + 断连 + payload 截断 + 冷启动降级 + 混合意图单轮 + 跨端信息型问答 + client steps=[] 回归 | ⬜ |
| Agent 端测试 | S086 | unit, integration | 知识检索 + MCP Client + snapshot 重启生效 + malformed 处理 + built-in catalog entry | ⬜ |

#### Agent 知识增强关键测试场景

##### B091 知识检索 smoke
- [ ] query='Claude Code' 返回使用技巧内容
- [ ] query='重构' 返回场景建议内容
- [ ] query='不存在的主题' 返回'未找到相关知识'
- [ ] 用户自定义文件被正确检索
- [ ] 禁用知识文件不参与检索
- [ ] 首次启动 user_knowledge/ 不存在时自动创建空目录

##### B092 MCP Client smoke
- [ ] Agent 启动时发现 skills/ 目录下已启用 Skill
- [ ] 启动 MCP Server 子进程并获取工具列表
- [ ] 工具列表通过 WebSocket 上报给 Server（namespaced）
- [ ] MCP Server 崩溃不影响 Agent 主进程和内置工具
- [ ] Agent 重连后重新上报 tool_catalog_snapshot
- [ ] 首次启动 skills/ 不存在时自动创建空目录
- [ ] 非 namespaced 工具（无 skill 前缀）被拒绝上报
- [ ] skill 启用/禁用后下次 Agent 启动时上报更新后的 tool_catalog_snapshot

##### B093 动态工具注册 smoke
- [ ] Server 接收 tool_catalog_snapshot 后正确存储
- [ ] 创建 Agent session 时动态工具注入 Pydantic AI
- [ ] LLM 调用动态工具 → WebSocket 路由到 Agent → 返回结果
- [ ] Agent 断开后动态工具被清理
- [ ] capability=write 的工具被拒绝注册
- [ ] capability=network/execute 的工具被拒绝注册
- [ ] 非法 schema 工具被忽略并记录 warning
- [ ] 缺少 required 参数 → 返回 invalid_args
- [ ] Agent 断连时 pending dynamic tool calls 立即返回 timeout error
- [ ] 动态工具调用 trace 含 skill attribution
- [ ] MCP Server 启动失败时跳过并记录 error，不阻塞 Agent 主流程

### R043 增量：response_type 三类型（agent-knowledge phase）

| Module | Task IDs | Test Type | Required Scenarios | Status |
|--------|----------|-----------|--------------------|--------|
| AgentResult response_type | B094 | unit, integration | response_type 三类型模型 + SYSTEM_PROMPT 松绑 + SSE event 含 response_type + ai_prompt | ✅ |
| Client 三类型渲染 | F088 | unit, widget | AgentResultEvent 解析 + 三类型渲染 + ai_prompt stdin 注入 + 编辑重发 | ✅ |
| 测试覆盖 + 产物更新 | S088 | unit, integration, widget | Server 三类型 result 构建 + SSE 推送 + Client 解析/渲染 + ai_prompt 注入 + 跨端同步 | ✅ |

#### R043 增量 response_type 关键测试场景

##### B094 AgentResult + SYSTEM_PROMPT
- [ ] response_type='command' 默认值向后兼容
- [ ] response_type='message' 时 steps=[], need_confirm=false
- [ ] response_type='ai_prompt' 时 ai_prompt 非空, steps=[]
- [ ] SYSTEM_PROMPT 不含"禁止输出纯文本"
- [ ] SYSTEM_PROMPT 含 response_type 选择指导
- [ ] SSE result event 含 response_type 和 ai_prompt 字段

##### F088 Client 三类型渲染
- [ ] AgentResultEvent.fromJson 正确解析三种 response_type
- [ ] response_type 缺失时默认 'command'
- [ ] response_type='message' 渲染为卡片，无执行按钮
- [ ] response_type='ai_prompt' 渲染为预览卡片，有注入按钮
- [ ] ai_prompt 确认后 stdin 注入 + panel idle 回归
- [ ] 所有类型 result 状态下可编辑再次发送

### R043 增量：Skill 配置入口（agent-knowledge phase）

| Module | Task IDs | Test Type | Required Scenarios | Status |
|--------|----------|-----------|--------------------|--------|
| Agent HTTP Skill/Knowledge API | B095 | unit | GET/POST /skills + /knowledge 端点 + toggle + auth + 边界 | ⬜ |
| Desktop Skill 配置面板 | F089 | widget | 列表渲染 + 开关交互 + 重启提示 + 桌面端独占 + 错误降级 | ⬜ |

#### R043 增量 Skill 配置关键测试场景

##### B095 HTTP 端点
- [ ] GET /skills 返回 skill 列表
- [ ] POST /skills/toggle 更新 registry
- [ ] GET /knowledge 返回知识文件列表
- [ ] POST /knowledge/toggle 更新 config
- [ ] 无 auth token 返回 401
- [ ] skills/ 目录为空时返回空列表
- [ ] skill-registry.json 损坏时不崩溃

##### F089 Desktop 配置面板
- [ ] skill 列表和开关正确渲染
- [ ] 开关切换触发 API 调用
- [ ] 变更后显示重启提示
- [ ] 仅桌面端显示菜单入口
- [ ] Agent 离线时显示错误提示
- [ ] skill/knowledge 列表为空时显示空状态
