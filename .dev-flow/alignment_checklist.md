# 前后端对齐清单

| Module | Feature | Contract | Backend | Frontend | Integration | Notes |
|--------|---------|----------|---------|----------|-------------|-------|
| 共享会话 | Session 状态模型 | CONTRACT-001 | completed | completed | completed | mobile/desktop presence 已统一 |
| 中转链路 | Agent 连接 | CONTRACT-002 | completed | not_applicable | completed | owner / views 元数据已补齐 |
| 中转链路 | Client/View 连接 | CONTRACT-003 | completed | completed | completed | mobile 与 desktop 复用同一协议 |
| 认证 | 登录 | CONTRACT-004 | completed | completed | completed | 复用现有账号体系 |
| 认证 | Refresh Token | CONTRACT-005 | completed | not_applicable | completed | Agent 自动恢复已落地 |
| Agent | 单 PTY 生命周期 | CONTRACT-002 | completed | not_applicable | completed | 宿主终端镜像污染已隔离 |
| Client | Flutter 共享终端核心 | CONTRACT-003 | not_applicable | completed | completed | xterm 已统一用于 mobile/desktop |
| Desktop | 本地终端窗口 | CONTRACT-001, CONTRACT-003 | not_applicable | completed | completed | 桌面端窗口已接入共享会话 |
| Mobile | 双端共控交互 | CONTRACT-003, CONTRACT-004 | not_applicable | completed | completed | 关键键位、重连和 IME 主链路已稳定 |
| Mobile | 终端快捷键动作模型 | CONTRACT-006 | not_applicable | completed | completed | 默认 `claude_code` profile 已落地 |
| Mobile | 软键盘快捷键栏 | CONTRACT-003, CONTRACT-006 | not_applicable | completed | completed | 仅移动端显示，且不破坏 IME 焦点 |
| Mobile | 快捷项配置与排序 | CONTRACT-007 | not_applicable | completed | completed | 核心固定区 + 智能区排序已落地 |
| Mobile | Claude 默认命令包 | CONTRACT-006, CONTRACT-007 | not_applicable | completed | completed | 默认集、显示/隐藏、排序、恢复默认与持久化已落地 |
| Mobile | 项目快捷命令 | CONTRACT-007 | not_applicable | completed | completed | 当前项目命令维护、展示与发送已落地 |
| Mobile | Claude 导航语义 | CONTRACT-008 | not_applicable | completed | completed | 导航语义与底层映射已解耦，支持标准/应用模式 |
| Mobile | 主题模式切换 | CONTRACT-009 | not_applicable | completed | completed | 支持 system/light/dark 与本地持久化 |
| Mobile | 命令面板与终端主题 | CONTRACT-006, CONTRACT-007, CONTRACT-009 | not_applicable | completed | completed | `更多` 命令面板、浅色终端主题与裁字修复已落地 |
| 集成 | 双端共控主链路 | CONTRACT-001..005 | completed | completed | completed | 本地 Docker + Android + macOS 已联调 |
| 多 terminal | 设备在线状态 | CONTRACT-010, CONTRACT-014 | completed | completed | completed | device 默认结构、兼容归一化、metadata/上限 helper 与真实 offline gating 已落地 |
| 多 terminal | terminal 列表与创建 | CONTRACT-011 | completed | completed | completed | 新增 /api/runtime/devices/{device_id}/terminals，在线 gating、agent 创建下发与真实 e2e 验证已落地 |
| 多 terminal | 在线设备 discovery | CONTRACT-010 | completed | completed | completed | 新增 /api/runtime/devices，客户端已接入在线设备列表与真实 offline gating 验证 |
| 多 terminal | terminal 级 WebSocket 附着 | CONTRACT-012 | completed | completed | completed | ws client 已支持 device_id/terminal_id，并在真实双视图 attach 中验证 connected 首包与 terminal 级隔离 |
| 多 terminal | Agent terminal 生命周期事件 | CONTRACT-013 | completed | completed | completed | 真实链路验证 terminal_exit 回写 closed；agent_shutdown 回写 detached/offline gating |
| 多 terminal | 关闭原因与状态语义 | CONTRACT-014 | completed | completed | completed | terminal_exit 与 device offline 均已在真实链路校验 |
| 状态语义收口 | 设备在线定义与实时视图数 | CONTRACT-015 | completed | completed | completed | "电脑在线 = 本机 Agent 在线 = 当前可创建 terminal"；runtime terminal views 改为后端实时连接数权威来源 |
| 状态语义收口 | Agent 在线稳定性与 create_failed | CONTRACT-010, CONTRACT-013, CONTRACT-014, CONTRACT-015 | completed | not_applicable | completed | create_terminal / attach 均以活跃 Agent 连接为准；Agent ping 会回写设备心跳；agent 断开时 create 被收口为 device_offline |
| 状态语义收口 | 桌面本机工作台文案与实时刷新 | CONTRACT-010, CONTRACT-011, CONTRACT-015 | not_applicable | completed | completed | 桌面端改为"本机电脑在线/离线"；进入 terminal 页先拉快照，返回列表后刷新 devices/terminals |
| 终端工作台 | workspace 初始化与 tab 语义 | CONTRACT-015, CONTRACT-016 | not_applicable | completed | completed | 登录后直接进入 terminal workspace，先拉快照再确定默认 terminal |
| 终端工作台 | workspace tabs 与 + 新建 | CONTRACT-011, CONTRACT-016 | not_applicable | completed | completed | terminal 页顶部切换现有 terminal，并通过 `+` 创建新 terminal |
| 终端工作台 | 主入口重构与旧列表页降级 | CONTRACT-010, CONTRACT-016 | not_applicable | completed | completed | 设备/terminal 选择页不再作为默认主路径，仅保留后备/调试用途 |
| 创建与关闭语义 | terminal 创建准入与 closed 清理基线 | CONTRACT-017, CONTRACT-018 | completed | completed | completed | 已将创建前置准入收敛为"电脑在线 + 未达上限"，并固化 closed terminal 退出活动连接集合的语义 |
| 创建与关闭语义 | 服务端公开 max_terminals 入参收口 | CONTRACT-011, CONTRACT-017 | completed | not_applicable | completed | 普通 runtime device 更新接口不再接受 max_terminals；客户端仍可读取服务端返回的上限展示 |
| 创建与关闭语义 | 桌面端首个 terminal 的 Agent 恢复前置 | CONTRACT-018 | completed | completed | completed | 桌面端在 Agent 离线且 terminal 为 0 时，可先尝试恢复本机 Agent，再继续创建第一个 terminal |
| 创建与关闭语义 | workspace 创建/关闭交互对齐 | CONTRACT-017, CONTRACT-018 | not_applicable | completed | completed | workspace 空态、创建与 close 后刷新已对齐服务端权威语义；terminal_closed 时客户端会断开旧 ws |
| 终端工作台瘦身 | 顶部状态栏与 terminal 菜单主路径 | CONTRACT-019 | not_applicable | completed | completed | 顶部已收敛为状态图标 + 当前 terminal 标题 + 菜单入口，terminal 管理动作统一收纳进菜单面板 |
| 终端工作台瘦身 | tabs 交互降级与菜单主路径回归 | CONTRACT-019 | not_applicable | completed | completed | 常驻 tabs 已移除，菜单主路径下的 create/switch/rename/close 与空态逻辑已通过 widget 回归 |
| 设备离线收口 | 设备离线后的 terminal 统一不可用语义 | CONTRACT-020 | completed | completed | completed | 设备离线后 terminal 统一收口为 closed/unavailable 语义，创建准入仍只看在线与上限 |
| 设备离线收口 | 服务端离线清理 terminal 活跃态 | CONTRACT-020 | completed | not_applicable | completed | Agent 断开后 terminal 收口为 closed，views/grace 清理且活动名额释放 |
| 设备离线收口 | 客户端离线展示与 terminal 可用性对齐 | CONTRACT-020 | not_applicable | completed | completed | workspace 离线时不再展示可切换 terminal，标题和空态均按后端快照对齐 |
| 桌面 Agent 后台模式 | 桌面端 Agent 后台模式与退出语义 | CONTRACT-021 | completed | completed | completed | 已固化"桌面控制台 + Agent 独立后台服务 + 退出时可选保活"的语义与风险边界 |
| 桌面 Agent 后台模式 | AgentSupervisor 与优雅停机链路 | CONTRACT-018, CONTRACT-021 | completed | completed | completed | 已区分 managed Agent 与外部已存在 Agent，避免误杀与重复启动 |
| 桌面 Agent 后台模式 | 桌面端后台运行开关与本机 Agent 状态入口 | CONTRACT-021 | not_applicable | completed | completed | 仅桌面端提供本地开关与状态入口，移动端不展示 |
| 桌面 Agent 后台模式 | 桌面端退出生命周期与在线语义对齐 | CONTRACT-021 | completed | completed | completed | 退出桌面端后需按开关行为保持或停止 Agent，并让手机端在线状态快速收口 |
| 桌面 Agent 管理子系统 | Agent 管理子系统与工作台状态机基线 | CONTRACT-021, CONTRACT-022 | completed | completed | completed | 已正式拆分 DesktopAgentManager 与 DesktopWorkspaceController 的职责边界 |
| 桌面 Agent 管理子系统 | 稳定 Agent 发现链 | CONTRACT-021, CONTRACT-022 | completed | completed | completed | 已去除对 Directory.current 的主路径依赖，引入正式发现模型 |
| 桌面 Agent 管理子系统 | 单一 WorkspaceState | CONTRACT-022 | not_applicable | completed | completed | header、空态、按钮可用性统一由 WorkspaceState 驱动 |
| 桌面 Agent 管理子系统 | 首个 terminal 创建链收口 | CONTRACT-018, CONTRACT-022 | completed | completed | completed | 已保证"先 Agent Ready 再 create"并与手机端在线状态一致 |
| Agent 本地 Supervisor | Agent 本地 HTTP Server | CONTRACT-024 | completed | not_applicable | completed | Agent 启动时同时启动本地 HTTP 服务，提供控制面 API |
| Agent 本地 Supervisor | 状态文件持久化与端口发现 | CONTRACT-024 | completed | not_applicable | completed | 使用平台标准目录存储状态，处理端口冲突和孤儿进程 |
| Server TTL 机制 | Agent 状态 TTL 与 stale 语义 | CONTRACT-025 | completed | not_applicable | completed | WebSocket 断开不立即清理，等待 TTL 过期 |
| 平台差异 | 桌面端与手机端行为模式区分 | CONTRACT-026 | not_applicable | completed | completed | 桌面端管理本地 Agent，手机端只是远程查看器 |
| **Agent 生命周期管理** | **登录启动 Agent** | **CONTRACT-027** | **not_applicable** | **pending** | **pending** | **登录成功后桌面端启动 Agent，移动端不启动** |
| **Agent 生命周期管理** | **登出关闭 Agent** | **CONTRACT-027** | **not_applicable** | **pending** | **pending** | **退出登录时始终关闭 Agent** |
| **Agent 生命周期管理** | **App 启动恢复 Agent** | **CONTRACT-027** | **not_applicable** | **pending** | **pending** | **App 启动时恢复已登录用户的 Agent** |
| **Agent 生命周期管理** | **关闭应用处理 Agent** | **CONTRACT-027** | **not_applicable** | **pending** | **pending** | **根据 keepAgentRunningInBackground 开关决定** |
| **Agent 生命周期管理** | **Agent 所有权判断** | **CONTRACT-027** | **not_applicable** | **pending** | **pending** | **判断 Agent 是否属于当前用户** |
| **日志集成** | **Server SDK + 中间件接入** | **CONTRACT-029** | **completed** | **not_applicable** | **completed** | **Server log-service-sdk + 请求中间件 + auth 错误透传** |
| **日志集成** | **Server 结构化日志** | **CONTRACT-029** | **completed** | **not_applicable** | **completed** | **WS/Auth/Session 模块结构化日志** |
| **日志集成** | **Client 日志代理转发** | **CONTRACT-029** | **completed** | **not_applicable** | **completed** | **log_api.py 异步转发到 log-service** |
| **日志集成** | **Agent SDK 接入** | **CONTRACT-029** | **completed** | **not_applicable** | **completed** | **Agent log-service-sdk + Desktop 可选配置** |
| **日志集成** | **Docker 标准化 + E2E 验证** | **CONTRACT-029** | **completed** | **pending** | **pending** | **三网模式 + Traefik + 三端日志可见（smoke 需手动验证）** |
| **用户信息** | **修复反馈 user_id + LoginResponse 增强** | **CONTRACT-004** | **pending** | **not_applicable** | **pending** | **B056: feedback_api 通过 session 记录获取真实 user_id；LoginResponse 新增 username** |
| **用户信息** | **用户信息本地存储** | — | **not_applicable** | **pending** | **pending** | **F054: UserInfoService + rc_login_time 保存/清理** |
| **用户信息** | **用户信息页面** | — | **not_applicable** | **pending** | **pending** | **F055: UserProfileScreen 含反馈+退出入口** |
| **用户信息** | **菜单去重 + 个人信息入口** | — | **not_applicable** | **pending** | **pending** | **F056: 三处菜单移除反馈/退出，统一收口到个人信息页** |
| **用户信息** | **集成测试** | **CONTRACT-004** | **pending** | **pending** | **pending** | **S032: 端到端验证反馈 user_id + 前端菜单去重检查** |
