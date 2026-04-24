# History Index

> 项目：remote-control
> 用于快速定位历史 session，按需加载详情

## Session 索引

| Session | 时间 | 主题 | 类型 | 关键结论 |
|---------|------|------|------|---------|
| S001 | 2026-03-26 10:00 | 初始规划 | feature | 单 PTY 双端共控基线建立 |
| S002 | 2026-03-26 22:30 | 用户体验优化 | feature | 移动端交互细节优化 |
| S003 | 2026-03-27 10:00 | 调试日志功能 | feature | Agent 调试日志与本地显示 |
| S004 | 2026-03-27 10:45 | Agent 本地显示增强 | feature | Agent 状态本地可视化 |
| S006 | 2026-03-27 16:45 | 共享 PTY 双端共控重构规划 | feature | 共享会话协议重构 |
| S007 | 2026-03-28 01:10 | 移动端输入与交互缺陷修复 | bugfix | 中文 IME、消息发送、TUI 选择修复 |
| S008 | 2026-03-28 04:05 | 移动端软键盘快捷键层规划 | feature | 快捷键动作模型 + Claude Code 预设 |
| S009 | 2026-03-28 23:40 | 快捷项产品化与 Claude 导航语义 | feature | 核心固定区 + 智能区 + 导航语义校准 |
| S010 | 2026-03-28 23:59 | 快捷项收口、主题切换与计划对齐 | feature | 主题三档切换 + 命令面板 |
| S011 | 2026-03-29 01:40 | 单 Agent 多 Terminal 架构升级 | feature | 单设备单 Agent 多 terminal 模型确立 |
| S012 | 2026-03-29 20:10 | 状态语义拆解与后端权威在线态回流 | bugfix | Server 权威在线态 + 三层语义拆解 |
| S014 | 2026-03-29 22:05 | 终端工作台 tab 化与主入口重构 | feature | 主路径改为登录→快照→workspace |
| S015 | 2026-03-28 23:59 | Terminal 创建准入与 closed 清理语义 | bugfix | 准入条件收敛 + closed terminal 退出活动集 |
| S016 | 2026-03-29 02:05 | 顶部状态栏瘦身与 terminal 菜单化 | feature | 轻量状态栏 + 菜单管理 |
| S017 | 2026-03-28 23:58 | 电脑离线后的 terminal 收口 | bugfix | 设备离线 → terminal 全部收口 |
| S018 | 2026-03-29 09:20 | 桌面端 Agent 后台模式 | planning | Agent 独立后台 + 桌面端控制台 |
| S019 | 2026-03-29 10:58 | 桌面 Agent 管理子系统重构 | planning | DesktopAgentManager + DesktopWorkspaceController 分层 |
| S020 | 2026-03-29 12:10 | 关闭最后 terminal 后状态归一化 | bugfix | createFailed 不得持久污染空工作台 |
| S021 | 2026-03-30 10:00 | Agent 终端管理系统性重构 | planning | TTL 解耦 + 本地 HTTP Supervisor + 跨平台路径 |
| S022 | 2026-03-30 15:00 | PTY 进程组清理与资源完整性 | bugfix | os.killpg 进程组清理 + SIGKILL 超时 |
| S023 | 2026-04-07 10:00 | 移动端 WebSocket 生命周期管理 | feature | 后台断开 + 前台重连，仅移动端 |
| S024 | 2026-04-09 11:00 | 同端设备在线数限制 | feature | 同用户同端单 Client + 通知用户选择冲突解决 |
| S025 | 2026-04-10 14:00 | 日志模块接入 + Docker 标准化部署 | infrastructure | Server/Agent 接入 log-service-sdk + Docker 三网模式 |
| S030 | 2026-04-10 16:00 | 用户反馈问题功能 | feature | 设置入口反馈 + 自动采集平台信息 + 自动关联日志 |
| S031 | 2026-04-11 14:00 | SDK 解耦与部署标准化 | infrastructure | log-service-sdk 改为 GitHub pip 安装 + deploy-lib.sh 共享部署库 |
| S032 | 2026-04-12 14:00 | 用户信息 + 反馈修复 | bugfix | 反馈 user_id 修复 + 用户信息页面 + 菜单去重收口 |
| S033 | 2026-04-13 15:30 | 安全加固规划 | planning | 15 个安全问题拆解为 10 个交付任务 |
| S034 | 2026-04-13 16:00 | 安全加固执行 | security | Server/Agent/Client 三端安全加固，10/10 完成 |
| S035 | 2026-04-14 10:00 | 安全加固集成验证 + Session 治理 | security | 三端 E2E 验证 + Session TTL + Stale 清理 + SSL 分层 |
| S036 | 2026-04-15 | IP 直连 + RSA/AES 加密 | feature | 分两期：Phase1 IP 直连（紧急）+ Phase2 RSA+AES 加密（后续） |
| S037 | 2026-04-16 | 终端 P0 稳定性修复规划 | bugfix | 4 个终端体验 P0 任务拆解完成；workflow 收口为 local/local/local；规划审核通过 |
| S039 | 2026-04-17 | 终端交互架构重构规划 | planning | 从终端补丁修复升级为整体交互重构；Agent 主恢复源 + 四层客户端模型 + Desktop 恢复链纳入统一状态机 |
| S040 | 2026-04-22 | 智能终端进入规划 | planning | 在 terminal 创建前加入推荐式与一句话意图式智能，统一收口到 Client 侧 TerminalLaunchPlan 编排 |
| S041 | 2026-04-22 | 智能终端进入规划复审修正 | planning | 补齐直接进入工具语义、RecentLaunchContext 数据源和高风险失败/边界测试 |
| S042 | 2026-04-22 | 设备感知智能终端进入长期路线补全 | planning | 智能识别后续必须基于当前设备项目上下文；LLM 只能在候选事实上做选择，不得发明路径 |
| S043 | 2026-04-24 | Terminal-bound Agent 对话同步长期规划 | planning | Agent conversation 由 Server 按 terminal 一一维护；手机端/桌面端共享事件与 message_history；terminal close 即销毁 |
| S044 | 2026-04-23 | Opik LLM 可观测性集成规划 | planning | Opik self-hosted + logfire + OTLP；Pydantic AI → logfire → OTLP → Opik；Agent 代码不改，纯配置集成 |

## 需求包索引

| 需求包 | 时间范围 | 主题 | 状态 | 归档位置 |
|--------|---------|------|------|---------|
| R041 | 2026-04-23 | react-terminal-agent | **验收未通过** | `_archive/R041_react-terminal-agent/` |
| R042 | 2026-04-23 | opik-llm-observability | **规划中** | `_archive/R042_opik-llm-observability/` |

## 已沉淀到 architecture.md 的决策

- S011: 单 Agent 多 Terminal 模型
- S012: Server 权威在线态
- S015: 创建准入语义、closed terminal 退出活动集
- S017: 设备离线 → terminal 收口
- S018/S019: 桌面端 Agent 控制台 + DesktopAgentManager 分层
- S020: createFailed 归一化规则
- S021: TTL 解耦、本地 HTTP Supervisor、数据流方向
- S022: 进程组清理规则
- S023: 移动端后台断开 WebSocket
- S024: 同端设备在线数限制 + 冲突解决协议
- S032: 反馈 user_id 修复（session_id → 真实用户名）+ 菜单去重收口
- S033: 安全加固 10 任务拆解（JWT/bcrypt/CORS/WS鉴权/速率限制/Agent加固/Client加固/Redis密码/Docker非root）
- S034: bcrypt 密码哈希迁移、CORS 环境变量、WebSocket auth 首条消息鉴权、日志归属校验
- S035: Session TTL 24h + 登录清理 stale session + 设备列表在线优先排序 + SSL debug/release 分层
- S039: Agent 主恢复源、Server 会话时序真相、Client 四层终端模型、exclusive/shared terminal mode、Desktop Agent 恢复链统一状态机
- S043: Server 作为 terminal-bound Agent conversation 权威源；手机端只做同 conversation 视图/输入端；terminal close 销毁 conversation
- R042 归档: Opik LLM 可观测性集成 + Agent 错误体验修复 + SSE 重连/性能收敛。全部 52 任务完成。
