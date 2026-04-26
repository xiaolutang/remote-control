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
| **用户信息** | **修复反馈 user_id + LoginResponse 增强** | **CONTRACT-004** | **completed** | **not_applicable** | **completed** | **B056: feedback_api 通过 session 记录获取真实 user_id；LoginResponse 新增 username** |
| **用户信息** | **用户信息本地存储** | — | **not_applicable** | **completed** | **completed** | **F054: UserInfoService + rc_login_time 保存/清理** |
| **用户信息** | **用户信息页面** | — | **not_applicable** | **completed** | **completed** | **F055: UserProfileScreen 含反馈+退出入口** |
| **用户信息** | **菜单去重 + 个人信息入口** | — | **not_applicable** | **completed** | **completed** | **F056: 三处菜单移除反馈/退出，统一收口到个人信息页** |
| **用户信息** | **集成测试** | **CONTRACT-004** | **completed** | **completed** | **completed** | **S032: 端到端验证反馈 user_id + 前端菜单去重检查** |
| **部署标准化** | **多阶段 Dockerfile** | — | **completed** | **not_applicable** | **completed** | **S034: deploy/ 目录 + server/agent 两阶段构建** |
| **部署标准化** | **build.sh + compose 迁移** | — | **completed** | **not_applicable** | **completed** | **S035: 构建脚本 + compose 文件统一到 deploy/** |
| **部署标准化** | **deploy.sh + 清理 + CLAUDE.md** | — | **completed** | **not_applicable** | **completed** | **S036: 部署脚本迁移 + 旧文件删除 + 文档更新** |
| **安全加固** | **JWT Secret 加固 + 旧 token 拒绝** | **CONTRACT-031, CONTRACT-032** | **pending** | **not_applicable** | **pending** | **B062: JWT_SECRET 必填 + 无 token_version 拒绝** |
| **安全加固** | **密码哈希迁移到 bcrypt** | **CONTRACT-032** | **pending** | **not_applicable** | **pending** | **B063: bcrypt 新注册 + SHA-256 自动迁移** |
| **安全加固** | **CORS 收紧** | **CONTRACT-033** | **pending** | **not_applicable** | **pending** | **B064: CORS_ORIGINS 环境变量，禁止通配符** |
| **安全加固** | **WebSocket 鉴权重构** | **CONTRACT-031** | **pending** | **pending** | **pending** | **B065: 首条 auth 消息认证 + 消息大小限制** |
| **安全加固** | **日志 API 归属校验 + 错误脱敏** | **CONTRACT-032** | **pending** | **not_applicable** | **pending** | **B066: get_current_user_id + JWT 错误脱敏** |
| **安全加固** | **登录/注册速率限制** | **CONTRACT-033** | **pending** | **not_applicable** | **pending** | **B067: IP 速率限制 10/min + fail-open** |
| **安全加固** | **Agent 安全加固** | **CONTRACT-031, CONTRACT-035** | **not_applicable** | **not_applicable** | **pending** | **B068: WS auth 适配 + 命令校验 + 本地 HTTP 认证** |
| **安全加固** | **Client 安全加固** | **CONTRACT-031, CONTRACT-036** | **not_applicable** | **pending** | **pending** | **F058: WS auth 适配 + flutter_secure_storage** |
| **安全加固** | **Redis 密码保护 + Docker 非 root** | **CONTRACT-034** | **pending** | **not_applicable** | **pending** | **B070: Redis --requirepass + 非 root 容器** |
| **安全加固** | **安全加固集成验证** | **CONTRACT-031..036** | **pending** | **pending** | **pending** | **S038: 端到端全链路安全加固验证** |
| **环境选择** | **环境模型与选择服务** | — | **not_applicable** | **completed** | **completed** | **F059: AppEnvironment 枚举 + EnvironmentService 纯状态服务 + ConfigService 委托** |
| **IP 直连** | **本地 URL 修复 + 直连端口暴露** | **CONTRACT-037, CONTRACT-038** | **completed** | **completed** | **completed** | **S063: ws:// URL 格式 + Docker 端口映射 8880 + RSA+AES 加密（符合不变量 #27）** |
| **IP 直连** | **直连端口部署验证 + 线上适配** | **CONTRACT-037, CONTRACT-038** | **pending** | **pending** | **pending** | **S064: 线上防火墙开放 + 真机直连 smoke + Agent 注册验证** |
| **终端 P0 修复** | **CPR 坐标修复：0-based → 1-based** | **—** | **not_applicable** | **pending** | **pending** | **F067: xterm fork emitter 的 CSI 6n 响应改为 ANSI 1-based，修复 Codex TUI 退化** |
| **终端 P0 修复** | **渲染闪烁修复：移除多余 setState** | **—** | **not_applicable** | **pending** | **pending** | **F068: 终端输出只走 Terminal/RenderTerminal 通知链，不重建外层 widget tree** |
| **终端 P0 修复** | **移动端键盘 resize 隔离** | **—** | **not_applicable** | **pending** | **pending** | **F069: 移动端软键盘不得把本地 viewport 变化升级为全局 PTY resize（对应不变量 #35）** |
| **终端 P0 修复** | **终端切换白屏修复** | **—** | **not_applicable** | **pending** | **pending** | **F070: TerminalSessionManager 缓存 Terminal 实例，切换复用 buffer/state，登出时清空缓存** |
| **终端交互架构重构** | **架构基线：单 Transport + 单 Coordinator + 单权威恢复源** | **CONTRACT-039** | **pending** | **pending** | **pending** | **S071: 四层职责边界、状态源矩阵、switch/reconnect/recover 状态机** |
| **终端交互架构重构** | **恢复语义与模式基线** | **CONTRACT-039, CONTRACT-042** | **pending** | **pending** | **pending** | **S072: snapshot/local cache/live output 边界 + attach/recovery epoch + exclusive/shared mode** |
| **终端交互架构重构** | **协议兼容迁移与灰度切换** | **CONTRACT-042** | **pending** | **pending** | **pending** | **S073: 新旧恢复协议双栈窗口、发布顺序、回退与灰度验证点** |
| **终端交互架构重构** | **Server 状态中心收瘦** | **CONTRACT-040** | **pending** | **not_applicable** | **pending** | **B071: Server 只维护 metadata / ownership / pty / routing 真相，history 不再做主恢复源** |
| **终端交互架构重构** | **Agent 主权威恢复源** | **CONTRACT-041** | **pending** | **not_applicable** | **pending** | **B072: Agent 维护 per-terminal authoritative snapshot，attach 恢复优先走 agent** |
| **终端交互架构重构** | **恢复协议升级** | **CONTRACT-042** | **pending** | **pending** | **pending** | **B073: snapshot / snapshot_complete / live output 边界明确** |
| **终端交互架构重构** | **Client Transport 收瘦** | **CONTRACT-042** | **not_applicable** | **completed** | **completed** | **F071: WebSocketService 收口为纯 transport events；eventStream 标准化输出；epoch 丢弃；旧 stream deprecated** |
| **终端交互架构重构** | **Client Coordinator 状态机** | **CONTRACT-039, CONTRACT-042** | **not_applicable** | **completed** | **completed** | **F072: TerminalSessionState 枚举 + 状态机入口 + activeTerminalKey + 60/60 测试** |
| **终端交互架构重构** | **Renderer 隔离** | **CONTRACT-039** | **not_applicable** | **pending** | **pending** | **F073: xterm renderer handle 下沉，UI 不再直接操纵恢复语义** |
| **终端交互架构重构** | **UI 瘦身迁移** | **CONTRACT-039** | **not_applicable** | **pending** | **pending** | **F074: TerminalScreen / Workspace 只负责展示、焦点、快捷键、IME** |
| **终端交互架构重构** | **桌面端 Agent 断连恢复编排** | **CONTRACT-040, CONTRACT-041, CONTRACT-042** | **pending** | **pending** | **pending** | **F075: agent 断连 recoverable/TTL/重启恢复 与 app lifecycle 编排统一** |
| **终端交互架构重构** | **客户端生命周期恢复编排** | **CONTRACT-039, CONTRACT-042** | **not_applicable** | **pending** | **pending** | **F076: foreground/cold start/network restore 统一恢复状态机** |
| **智能终端进入** | **产品基线：Claude-only + CommandSequence** | **CONTRACT-043** | **not_applicable** | **completed** | **completed** | **S077: 主流程改为一句话输入 -> 命令序列预览 -> 用户确认执行** |
| **智能终端进入** | **智能创建入口 UI** | **CONTRACT-043** | **not_applicable** | **pending** | **pending** | **F077: 单输入框、命令步骤预览、确认按钮和高级配置兜底** |
| **智能终端进入** | **输入辅助与默认提示** | **CONTRACT-043** | **not_applicable** | **pending** | **pending** | **F078: 基于 recent terminal 的轻量提示与默认文本，不再走多工具推荐** |
| **智能终端进入** | **一句话意图到 CommandSequence** | **CONTRACT-043** | **not_applicable** | **pending** | **pending** | **F079: 短句解析为可执行命令步骤，输出 provider/source/need_confirm** |
| **智能终端进入** | **统一创建并执行命令序列** | **CONTRACT-043, CONTRACT-044** | **not_applicable** | **pending** | **pending** | **F080: runtime selection 与 workspace 共用 create terminal + execute sequence 主链路** |
| **智能终端进入** | **自动化与首用 smoke** | **CONTRACT-043, CONTRACT-044** | **not_applicable** | **pending** | **pending** | **F081: 确认执行、失败停止、手动回退与手机端首用验证** |
| **命令规划隔离** | **provider 隔离基线** | **CONTRACT-044** | **not_applicable** | **completed** | **completed** | **S078: `CommandPlanner` / `PlannerCoordinator` / fallback 规则与执行语义收口** |
| **命令规划隔离** | **本地 planner bridge** | **CONTRACT-044** | **pending** | **not_applicable** | **pending** | **B074: 在当前设备侧调用 Claude CLI 或本地规则，不让 Server 解析自然语言** |
| **命令规划隔离** | **planner 状态与失败反馈 UI** | **CONTRACT-044** | **not_applicable** | **pending** | **pending** | **F086: 展示 provider、fallback、不可用原因，但不在主 UI 暴露 provider 选择** |
| **命令规划隔离** | **命令序列预览状态与用户编辑** | **CONTRACT-043, CONTRACT-044** | **not_applicable** | **pending** | **pending** | **F082: 用户可改写步骤/标题/命令，最终执行结果以用户编辑为准** |
| **命令规划隔离** | **Claude CLI planner provider** | **CONTRACT-044** | **not_applicable** | **pending** | **pending** | **F083: `ClaudeCliCommandPlanner` 负责把自然语言转换为命令序列** |
| **命令规划隔离** | **planner coordinator 与 fallback** | **CONTRACT-043, CONTRACT-044** | **not_applicable** | **pending** | **pending** | **F084: `claude -p` 不可用、超时或违规时稳定回退 `local_rules`** |
| **命令规划隔离** | **端到端回归与真实设备 smoke** | **CONTRACT-043, CONTRACT-044** | **not_applicable** | **pending** | **pending** | **F085: 真机/桌面端验证 `pwd -> find -> cd -> claude` 等链路** |
| **ReAct 智能体** | **Agent SSE 会话管理** | **CONTRACT-047** | **completed** | **not_applicable** | **completed** | **B080: `/assistant/agent/run|respond|cancel|resume`、SSE 事件流与断连恢复已落地** |
| **ReAct 智能体** | **Agent SSE 事件模型** | **CONTRACT-047** | **not_applicable** | **completed** | **completed** | **F095_old: SSE event 解析、四种事件类型、会话恢复与降级逻辑已接上服务端** |
| **ReAct 智能体** | **Agent token usage 追踪** | **CONTRACT-047** | **completed** | **not_applicable** | **completed** | **B083: AgentRunOutcome、SSE result usage 字段与恢复回放已验证通过** |
| **ReAct 智能体** | **Token 统计展示** | **CONTRACT-047** | **not_applicable** | **completed** | **completed** | **F099: usage 字段解析与兼容已完成；消息级展示已在 F100 收敛为底部汇总入口** |
| **ReAct 智能体** | **Agent usage 持久化与汇总 API** | **CONTRACT-048** | **completed** | **not_applicable** | **completed** | **B084: agent_usage_records 表、双 scope 汇总 API、usage 先落库再发 SSE 已落地并通过定向测试** |
| **ReAct 智能体** | **Token 汇总 Toast 浮层** | **CONTRACT-048** | **not_applicable** | **completed** | **completed** | **F100: 底部 Token 图标、Toast 浮层、3 秒自动消失、结果后自动刷新与失败降级均已落地** |
| **Terminal-bound Agent 对话** | **契约与生命周期基线** | **CONTRACT-049** | **pending** | **pending** | **pending** | **S083: conversation 与 terminal 一一对应，terminal close 即销毁** |
| **Terminal-bound Agent 对话** | **持久化模型与权限校验** | **CONTRACT-049** | **completed** | **not_applicable** | **completed** | **B085: agent_conversations/events 表、event_index、幂等写入、重复回答冲突、tombstone cleanup 与 user/device/terminal 隔离已通过数据库定向测试** |
| **Terminal-bound Agent 对话** | **run/respond/resume terminal 绑定** | **CONTRACT-049** | **completed** | **not_applicable** | **completed** | **B086: terminal-scoped run/respond/cancel/resume 已落地，旧无 terminal API 稳定拒绝，question_id/client_event_id 幂等与冲突语义已通过集成测试** |
| **Terminal-bound Agent 对话** | **fetch/stream 多端同步 API** | **CONTRACT-049** | **completed** | **pending** | **completed** | **B087: GET/stream conversation 投影已落地，空投影、after_index 增量和 device/terminal 权限边界已通过集成测试** |
| **Terminal-bound Agent 对话** | **message_history 与 close cleanup** | **CONTRACT-049** | **completed** | **not_applicable** | **completed** | **B088: 从服务端 events 重建 message_history，terminal close 关闭 conversation、fanout closed event 并取消 active session** |
| **Terminal-bound Agent 对话** | **客户端服务端投影接入** | **CONTRACT-049** | **not_applicable** | **completed** | **completed** | **F101: 智能面板进入 terminal 后先加载服务端 conversation projection，按 events 回放本地渲染缓存；run/respond/resume 走 terminal-scoped API，conversation_id 以服务端 fetch/session_created 返回值为准，terminal 切换会清空并重载缓存** |
| **Terminal-bound Agent 对话** | **双端同步 UI 与关闭清理** | **CONTRACT-049** | **not_applicable** | **completed** | **completed** | **F102: 智能面板在无 active session 时订阅 terminal conversation stream，远端新增的 question/answer/result 会实时同步到当前端；terminal closed 会清空智能对话 UI、展示关闭态并禁用智能输入** |
| **Terminal-bound Agent 对话** | **全链路验收** | **CONTRACT-049** | **in_progress** | **in_progress** | **pending** | **S084: 服务端集成与 Flutter 定向验证已通过，Android + macOS 本地真机 smoke 进行中，待补手工场景结果与关闭/隔离截图证据** |
| **Agent 知识增强** | **Agent prompt 增强 Claude Code 知识 + Vibe Coding** | **CONTRACT-050** | **pending** | **completed** | **pending** | **B089: SYSTEM_PROMPT 新增工具知识映射、信息型问答旅程边界、场景化建议规则；前端已支持 steps=[] 展示（现有 AgentResult 渲染逻辑覆盖）** |
| **Agent 知识增强** | **Agent 端 lookup_knowledge 工具 + 知识文件** | **CONTRACT-050** | **pending** | **not_applicable** | **pending** | **B091: 内置知识文件 + 用户自定义目录 + WebSocket 消息处理 + 关键词匹配** |
| **Agent 知识增强** | **MCP Client 框架** | **CONTRACT-050** | **pending** | **not_applicable** | **pending** | **B092: Skill 发现/启停、MCP Server 生命周期、工具注册与调用中转、namespaced 上报** |
| **Agent 知识增强** | **Server 端动态工具注册** | **CONTRACT-050** | **pending** | **not_applicable** | **pending** | **B093: 接收 Agent 工具目录、注入 Pydantic AI、built-in 优先、断连清理、capability 限制** |
| **Agent 知识增强** | **Server 端测试** | **CONTRACT-050** | **pending** | **not_applicable** | **pending** | **S085: prompt 增强 + 用户旅程边界 + 动态工具注册 + 优先级 + 断连清理测试** |
| **Agent 知识增强** | **Agent 端测试** | **CONTRACT-050** | **pending** | **not_applicable** | **pending** | **S086: 知识检索 + 内置文件完整性 + MCP Client 生命周期 + snapshot 重启生效测试** |
| **Agent 知识增强** | **配套产物更新** | **CONTRACT-050** | **pending** | **not_applicable** | **pending** | **S087: test_coverage.md + alignment_checklist.md 更新** |
| **R043 增量: response_type** | **AgentResult 三类型 + SYSTEM_PROMPT 松绑** | **CONTRACT-047, CONTRACT-050** | **done** | **done** | **done** | **B094: response_type(message/command/ai_prompt) + ai_prompt 字段 + SYSTEM_PROMPT 松绑** |
| **R043 增量: response_type** | **Client 三类型渲染 + ai_prompt 注入** | **CONTRACT-047, CONTRACT-050** | **done** | **done** | **done** | **F088: 三类型渲染 + ai_prompt stdin 注入 + 编辑重发修复** |
| **R043 增量: response_type** | **测试覆盖 + 产物更新** | **CONTRACT-047, CONTRACT-050** | **done** | **done** | **done** | **S088: Server + Client 三类型测试 + alignment/test_coverage 更新** |
| **R043 增量: skill 配置** | **Agent HTTP Skill/Knowledge 管理 API** | **CONTRACT-024, CONTRACT-050** | **done** | **not_applicable** | **done** | **B095: GET/POST /skills + /knowledge 端点 + toggle** |
| **R043 增量: skill 配置** | **Desktop 客户端 Skill 配置面板** | **CONTRACT-024, CONTRACT-050** | **not_applicable** | **done** | **done** | **F089: 桌面端菜单入口 + SkillConfigScreen + 开关 + 重启提示** |
| **Agent 评估体系** | **Eval 数据模型 + SQLite schema** | **CONTRACT-051** | **done** | **not_applicable** | **done** | **B096: 6 张表 + Pydantic 模型 + 配置检查，56 测试通过** |
| **Agent 评估体系** | **Eval Harness + Code Graders** | **CONTRACT-051** | **done** | **not_applicable** | **done** | **B097-B098: harness + 5 种 code grader，105 测试通过** |
| **Agent 评估体系** | **初始 Task 数据集 + LLM-as-Judge** | **CONTRACT-051** | **done** | **not_applicable** | **done** | **B099-B100: 30 个 eval task + Judge grader，83 测试通过** |
| **Agent 评估体系** | **在线质量指标提取与 API** | **CONTRACT-052** | **done** | **not_applicable** | **done** | **B101-B102: 质量指标持久化 + REST API，72 测试通过** |
| **Agent 评估体系** | **反馈闭环 + 回归测试** | **CONTRACT-053** | **done** | **not_applicable** | **done** | **B103-B104: 反馈→eval task + 回归运行器，62 测试通过** |
| **智能面板收敛 R045** | **conversation_reset pendingReset** | **—** | **not_applicable** | **completed** | **completed** | **F093: SSE 活跃时 pendingReset 机制，client-only, no contract change** |
| **智能面板收敛 R045** | **_activeSessionId 服务端投影** | **—** | **not_applicable** | **passed** | **passed** | **F094: 从 projection.activeSessionId 恢复，client-only, no contract change** |
| **智能面板收敛 R045** | **问答回答编辑测试** | **—** | **not_applicable** | **passed** | **passed** | **F095: _submitAnswerEdit 测试覆盖 + sublist clamp 保护，client-only, no contract change** |
| **智能面板收敛 R045** | **Planner 降级路径清理** | **—** | **not_applicable** | **completed** | **completed** | **F096: 废弃 planner 降级，移除 _resolveViaPlanner/_buildPlannerBody/_buildPreviewCard 等 ~250 行死代码，architecture.md 三层→两层** |
| **智能面板收敛 R045** | **配套产物更新** | **—** | **not_applicable** | **not_applicable** | **pending** | **S093: test_coverage + alignment 更新** |
| **Agent 评估体系** | **评估体系测试覆盖** | **CONTRACT-051..053** | **done** | **not_applicable** | **done** | **S089-S092: 框架/Grader/质量/反馈测试，355 总测试通过** |
| **R046 文档基线** | **文档基线验证** | **CONTRACT-047..051** | **not_applicable** | **not_applicable** | **completed** | **S104: architecture.md/api_contracts.md/test_coverage.md/alignment_checklist.md 基线已验证一致（8 条 acceptance criteria 全部 pass + 7 轮 review 修复）** |
| **R046 Agent 架构** | **自由对话+deliver_result 工具** | **CONTRACT-047, CONTRACT-048** | **completed** | **not_applicable** | **completed** | **B105: output_type=str + deliver_result 工具 + ResultDelivered 异常 + usage 累积回调。162 测试全通过** |
| **R046 Agent 循环** | **assistant_message SSE 事件** | **CONTRACT-047, CONTRACT-048, CONTRACT-049** | **completed** | **not_applicable** | **completed** | **B106: assistant_message SSE + CoT 过滤兜底 + ResultDelivered 路径 + planner 代码移除。70 测试全通过（23 新增）** |
| **R046 客户端** | **assistant_message + ai_prompt 验证** | **CONTRACT-047, CONTRACT-049, CONTRACT-050** | **not_applicable** | **completed** | **completed** | **F107: 四通道 SSE/projection/resume/widget assistant_message + ai_prompt 注入 + _TurnEventType 交错渲染 + answer-edit 保护。102 测试全通过** |
| **R046 Eval** | **deliver_result 对齐 + grader 兼容** | **CONTRACT-051** | **pending** | **not_applicable** | **pending** | **B108: harness 添加 deliver_result + 负向测试 + tool_call_order 排除** |
| **R046 评估** | **基线评估+迭代优化 → 50%** | **CONTRACT-051** | **pending** | **not_applicable** | **pending** | **S109: 基线记录 + 2-3 轮迭代 + ai_prompt 用例修复** |
| **R046 测试** | **Server+Client 测试更新** | **CONTRACT-047..051** | **pending** | **not_applicable** | **pending** | **S110: deliver_result + assistant_message + 重试 usage + 过滤兜底测试** |
| **R046 文档** | **事后精细校准** | **CONTRACT-047..051** | **not_applicable** | **not_applicable** | **pending** | **S111: CONTRACT-047/048/049/050/051 最终校准（实现后代码与文档一致性验证，不含 S104 已验证的基线内容）** |
