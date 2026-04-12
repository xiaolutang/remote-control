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
