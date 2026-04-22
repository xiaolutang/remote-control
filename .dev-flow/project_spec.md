# 项目说明

> 项目：remote-control
> 版本：2.14.0-plan

## 目标
- 将当前 remote-control 从”单 PTY、多终端视图、双端共控”升级为”单设备单 Agent、多 terminal、多视图共控”的本地 Claude Code Remote Control。
- 明确 `电脑在线 = 本机 Agent 在线 = 当前电脑可创建并承载 terminal`，其余客户端/视图状态单独命名与展示。
- 明确 `创建 terminal` 的准入条件只由”电脑在线”和”当前 terminal 数未达到服务端上限”决定；桌面端首个 terminal 在本机 Agent 离线时先恢复 Agent 再创建。
- terminal workspace 顶部采用轻量状态栏与菜单化终端管理，尽可能把可见空间留给终端内容本身。
- 电脑离线后，该设备上的 terminal 应统一收口为不可用/关闭状态，不再继续保留活动 terminal 语义。
- 桌面端作为本机 Agent 控制台，支持”退出桌面端后是否让 Agent 继续后台运行”的本地开关。
- 桌面端需进一步收敛为”DesktopAgentManager + DesktopWorkspaceController”的系统结构，避免页面继续直接拼接 Agent 状态、终端快照与临时 UI 状态。
- 关闭最后一个可用 terminal 后，工作台必须重新归一化为空工作台状态；历史 `createFailed` 不得继续污染当前空工作台。
- **新增：Agent 生命周期与 Terminal 生命周期解耦**，WebSocket 断开不立即触发 Agent 离线，采用 TTL 机制。
- **新增：桌面端与手机端行为模式明确区分**，桌面端管理本地 Agent，手机端只是远程查看器。
- **新增：Agent 本地 HTTP Supervisor**，提供控制面 API，处理端口发现与冲突。
- **新增：跨平台状态文件路径**，使用平台标准目录，处理权限和沙盒问题。
- **新增：终端 P0 稳定性修复**，优先收敛 CPR 坐标、渲染闪烁、移动端键盘 resize 干扰和多 terminal 切换白屏。
- **新增：终端交互架构重构**，把 terminal 交互收口为 UI / Coordinator / Transport / Renderer 四层，统一 switch / reconnect / recover 语义，并让 Agent 成为 terminal 内容恢复主权威源。
- **新增：Claude-only 智能终端进入**，在创建 terminal 前提供一句话输入，生成可确认的命令序列，减少手机端输入成本。
- **新增：命令序列执行模型**，智能输出不再是 `TerminalLaunchPlan`，而是用户可审查、可确认的 `CommandSequence`。
- **新增：命令规划 provider 隔离**，产品层只暴露 Claude，但架构层必须隔离 `claude -p`、服务端 LLM 与本地规则，为后续 provider 扩展保留边界。
- **新增：聊天式智能终端助手**，把当前“智能创建弹窗”升级为聊天式交互，展示对话、分析阶段、工具执行轨迹和最终命令卡片。
- **新增：服务端 LLM 规划与上下文记忆**，在服务端聚合当前设备事实、近期项目、历史成功序列与评估日志，作为主规划链路。

## 范围
- 包含：
  - **用户反馈问题功能**：App 和桌面端设置入口，用户提交反馈（分类+描述），自动采集平台信息和近期日志
  - **日志模块接入**：Server + Agent 接入 log-service-sdk，Server 转发 Client 日志到 log-service
  - **请求日志中间件**：Server 添加 RequestID + RequestLogging + ErrorHandler 中间件
  - **关键模块结构化日志**：ws_agent/ws_client/auth/session 补充含 uid/session_id 的日志
  - **Docker 标准化部署**：创建 docker-compose.prod.yml，接入 gateway + infra-network + rc-network 三网模式
  - 单设备单 Agent 作为设备级执行主体
  - Agent 下多个 terminal 的生命周期管理
  - terminal 级 `cwd / command / env / title` 元数据
  - 服务端设备在线感知、terminal 列表与连接资格校验
  - 服务端 terminal 中转与多视图同步
  - Agent 登录恢复、配置稳定化与多 terminal runtime
  - Flutter 终端核心统一用于移动端与桌面端
  - 客户端 terminal workspace 主入口与 tab 切换
  - 电脑端本地终端窗口
  - 手机端与电脑端同时连接同一个 terminal
  - 移动端软键盘快捷键层与 `claude_code` 预设
  - Claude Code 默认热门命令包与用户可调整快捷项
  - 当前项目快捷命令选择
  - `核心固定区 + 智能区` 排序策略
  - Claude Code 导航语义校准为 `上一项 / 下一项 / 确认`
  - Claude 智能终端创建入口：一句话意图输入 + 轻量快捷提示
  - 聊天式智能终端助手：对话流、分析阶段、工具轨迹、命令卡片、确认执行
  - `CommandSequence` 预览：展示最终命令、分析摘要与确认动作
  - 用户确认后创建 terminal，并在同一 shell session 中执行命令序列
  - 高级配置兜底：允许用户手动调整 terminal 标题、启动 shell 和执行命令
  - `PlannerService` 抽象：`service_llm` 主路径 + `claude_cli` / `local_rules` fallback
  - 服务端上下文聚合：当前设备事实、recent terminal、pinned projects、planner memory、评估日志
  - 服务端 planner 防护：用户级限流、provider timeout、预算/配额错误语义
  - provider 不可用时稳定回退，不阻断手动创建
  - 当前设备事实约束：命令序列只能基于当前设备上下文、近期记忆与 shell 可发现命令生成
  - 执行结果回写：planner memory 与评估日志只基于真实执行结果更新
  - 智能体评估：benchmark 数据集、回放评测、trace 指标、真实设备验收
  - 手动主题切换与主题持久化
  - 移动端 `更多` 命令面板与终端浅深色主题适配
  - terminal 关闭原因与短线 grace period 语义
  - 每设备最大 terminal 数限制
  - 后端权威的 terminal 实时视图数与进入页刷新策略
  - 桌面端本机 Agent 在线态与工作台语义
  - 创建 terminal 的准入语义与桌面端 Agent 预启动
  - `closed terminal` 退出活动连接集合，仅保留轻量历史记录
  - 顶部状态栏瘦身、terminal 菜单化切换与新建/关闭入口
  - 设备离线后 terminal 统一收口为不可用/关闭状态
  - 桌面端 AgentSupervisor、本机 Agent 状态探测与后台运行开关
  - 本地 Docker 验收与云端发布清单
  - 终端 P0 稳定性修复：CPR 兼容、渲染闪烁、移动端键盘 resize 隔离、终端切换白屏
  - 终端交互架构重构：恢复语义、epoch、exclusive/shared 模式、client lifecycle recovery、desktop agent 恢复链
- 不包含：
  - 远程桌面 / 屏幕采集 / 视频流
  - 多个独立 Agent 实例调度
  - 文件传输
  - Web 公网终端页面
  - 多工具并列选择型智能入口（`Claude / Codex / Shell / 自定义`）
  - 完整公开通用聊天助手能力（开放问答、任意联网搜索、原始推理全文展示）
  - 服务端持久化完整本地文件树或源码索引

## 用户路径
1. 用户在电脑上启动 Agent，服务端将该电脑注册为一个在线设备。
2. 用户在客户端登录后先获取当前设备与 terminal 快照，并直接进入 terminal workspace。
3. workspace 顶部以轻量状态栏展示当前 terminal，并通过菜单完成切换与新建；默认进入最近活跃 terminal。
4. 每个 terminal 可在独立目录下运行 Claude Code / shell，手机端和电脑端可同时附着到同一个 terminal。
5. 电脑在线只表示本机 Agent 在线且可创建/承载 terminal；桌面客户端打开本身不代表设备在线。
6. 创建 terminal 的前置准入条件只看 `agent_online=true` 且 `active_terminals < max_terminals`；Agent/PTY 拉起失败属于执行失败，不属于准入条件本身。
7. 桌面端在本机 Agent 离线且 terminal 数为 0 时，优先恢复/启动本机 Agent，再创建第一个 terminal。
8. 设备离线后，该设备上的 terminal 统一收口为不可用/关闭状态，不再允许 attach、输入或继续参与活动 terminal 语义。
9. `closed terminal` 不再维持活动连接记录，也不再参与视图数、活动 terminal 数与创建判断。
10. terminal workspace 顶部只保留电脑在线/离线状态图标、当前 terminal 标题和菜单入口，不再长期占用一整排 tabs。
11. terminal 的切换、新建、重命名和关闭通过顶部菜单/面板承载，终端内容区尽可能最大化。
12. workspace 初始化、terminal 切换、创建/关闭 terminal 时，客户端先向后端刷新 terminal 快照，再由 ws presence 做增量更新。
13. 当设备离线、terminal 关闭、短线重连或 token 失效时，客户端可获得明确反馈并恢复。
14. 用户可在 App 内切换 `system / light / dark` 主题，并在移动端通过命令面板访问非核心快捷项。
15. 桌面端退出时是否保留本机 Agent 继续后台运行，由本地配置决定；只有桌面端自己拉起的 Agent 才能被其退出流程主动停止。
16. 桌面端工作台页面只消费统一的 `WorkspaceState`；Agent 发现、启动、停止、所有权与退出语义由独立的 Agent 管理子系统统一提供。
17. 当最后一个可用 terminal 被关闭后，工作台必须重新判断 `AgentState + usableTerminalCount`，回到 `readyToCreateFirstTerminal / bootstrappingAgent / createFailed` 之一，不能延续历史失败标记。
18. 在 terminal 中运行 Codex、Claude Code、vim、top 等 TUI 程序时，终端协议行为必须保持兼容，不得因 CPR 或本地重绘问题退化。
19. 移动端软键盘弹起/收起只影响本地视图，不得改变共享 PTY 的全局尺寸，也不得干扰桌面端正在查看的同一 terminal。
20. 多 terminal 切换必须保留各自 buffer/scrollback，切回已存在 terminal 时不得出现白屏等待远端重新推流。
21. app 从后台回前台、app 被杀后重启、网络异常恢复、agent 与 server 断连恢复必须走统一 terminal recovery 状态机，不再依赖页面层或临时刷新补偿。
22. 用户点击“新建终端”后，应进入聊天式 Claude 智能助手：输入框、对话区、分析阶段、工具轨迹和命令卡片，不再先暴露多工具选项。
23. 用户输入一句目标后，系统先展示“已接收目标 -> 读取上下文 -> 调用规划器 -> 安全校验 -> 生成命令”的可观测过程，再给出 `CommandSequence`。
24. `CommandSequence` 仍是唯一执行产物；用户确认后，系统创建 terminal，并在同一个 shell session 中顺序执行这些命令；任一步失败时停止后续步骤。
25. 如果智能生成不准确，用户必须能在同一入口中改写命令、重新生成或退回“直接进入 Claude”，不得被智能链路阻塞。
26. 智能规划必须优先基于当前设备事实、recent terminal 上下文、planner memory 与 shell 可发现命令；不允许直接臆测本地目录结构。
27. 产品层当前只展示 Claude 模式，但底层规划器必须允许未来切换到其他 provider，而不改 UI 主流程。
28. 服务端 LLM 是默认主规划链路；`claude_cli` 与 `local_rules` 作为 fallback。用户点击“开始智能创建”即视为本次规划的显式授权，不再要求预先打开开关。
29. 聊天流中只展示结构化分析摘要、工具执行结果和状态轨迹，不展示模型原始 chain-of-thought。
30. 智能体评估必须可回放、可量化、可跨设备对比；每次规划至少记录输入、上下文摘要、trace、最终命令、fallback 与执行结果。
31. 命令执行结束后，客户端必须把执行结果、失败步骤、输出摘要与最终状态回写服务端，再由服务端决定是否更新 planner memory 与评估日志。

## 技术约束
- 后端与 Agent：Python + FastAPI + WebSocket + PTY
- 客户端：Flutter，共享移动端与桌面端代码
- 终端渲染：`xterm`
- 部署：Docker Compose（标准化：Traefik 网关 + 三网模式）
- 日志：log-service-sdk（Python SDK）→ 基础设施层 log-service（SQLite）
- 认证：账号登录 + Access Token / Refresh Token
- 智能终端进入 v2 以服务端 LLM 为主规划器，采用 OpenAI-compatible API；`claude_cli` 与 `local_rules` 作为 fallback
- 产品主流程只面向 Claude，但规划实现必须通过 provider abstraction 隔离 `service_llm` / `claude_cli` / `local_rules`
- 智能规划输出统一为 `CommandSequence`；执行前必须显式确认，执行时保证同一 shell session、顺序执行、失败即停
- LLM provider 凭证优先保存在服务端受控环境变量；客户端只保留调试/开发态 fallback 所需的本机配置，不下发到 Agent
- planner 输入只能来自当前设备事实、recent terminal 上下文、planner memory、候选项目与用户输入；禁止上传完整本地文件树，禁止生成无法被 shell 发现命令支撑的路径
- 智能创建过程需要结构化 trace（阶段、工具、摘要、fallback），供聊天 UI 展示和评估回放使用
- 服务端 `assistant/plan` 必须定义用户级限流、provider timeout、预算/配额和稳定错误语义；超限/超时不能阻断用户回退到本地 fallback 或手动创建
- planner memory 与评估日志只能在收到执行结果回写后更新；命令卡片生成成功不等于规划成功
- 当前验收基线：本地 Docker + Android 真机 + macOS 本地桌面端
- 本轮执行顺序：优先完成可 mock 的逻辑、状态机、协议和选择流程测试，再进入真实 PTY 与手工 smoke
- 桌面端后台 Agent 模式需优先完成本地配置、生命周期和“自己启动/外部已存在”所有权逻辑，再进入真实桌面退出 smoke
- 桌面端 Agent 启动链需采用正式的发现/配置模型；开发态允许显式 Agent 路径或环境变量，产品态应支持内置 Agent 或固定可发现路径

## 交付边界
- 后端：
  - 设备状态、terminal 状态、附着信息、消息转发、认证与归属校验
  - 服务端 LLM planner API、上下文聚合、planner memory、trace、执行结果回写与评估日志
- Agent：
  - 多 terminal PTY 生命周期、配置与登录恢复、宿主终端隔离
- 前端：
  - 共享终端组件、terminal workspace 主入口、桌面端本地窗口、移动端交互完善、移动端快捷键层、快捷项配置与项目命令、主题模式切换、命令面板与终端主题适配
  - 聊天式智能终端助手 UI、分析轨迹、工具消息、命令卡片、确认执行、高级配置兜底
  - `PlannerService` 协调层、provider fallback、失败反馈、trace 展示与当前设备事实约束
- 桌面控制台：
  - 本机 Agent 状态探测、后台运行开关、退出桌面端后的 Agent 生命周期控制
  - `DesktopAgentManager` 统一负责 Agent 发现/启动/停止/所有权/退出语义
  - `DesktopWorkspaceController` 统一负责工作台状态机、首个 terminal 创建链与桌面空态
- 集成：
  - 多 terminal 主链路、在线 gating、关闭原因、重连、尺寸同步、关键键位、后端权威状态刷新、桌面端 Agent 后台模式、Agent 发现模型与云端发布验证
  - 智能体 benchmark、trace 回放、真实设备对比验收与 fallback 评估
