# Remote Control 项目规格

## 当前范围：R063 对话 Agent 定时任务能力

让 AI 对话 Agent 支持定时任务场景：用户通过自然语言描述定时意图 → Agent 识别并返回带调度信息的命令结果 → 用户确认 → 创建定时任务。Agent 还能查询和取消已有定时任务。

### 背景

R062 已完成终端定时任务基础设施（REST API + 调度器 + 客户端 UI）。本轮复用这些基础设施，将其接入对话 Agent 的工具链。

### 范围（2 个 Phase，4 个任务）

- **Phase 1** — 服务端（S001-B001）：AgentResult 扩展调度字段 + 新增 list/cancel 工具 + System Prompt 更新
- **Phase 2** — 客户端（F001-F002）：事件模型扩展 + 定时确认 UI

### 产品定义

| 维度 | 决策 |
|------|------|
| 入口 | 用户对 Agent 说"每天凌晨3点拉代码" → Agent 自动识别 |
| 确认 | Agent 返回带 schedule_at 的 command → 用户点确认 |
| 查询 | Agent 可查询当前终端的定时任务列表 |
| 取消 | Agent 可取消指定 task_id 的定时任务 |
| 复用 | 复用 R062 的 ScheduledTaskStore 和 ScheduledTaskService |

### 用户路径

1. 用户在 Agent 面板说"明天早上8点运行部署脚本"
2. Agent 识别定时意图，使用 deliver_result 返回 command + schedule_at
3. 客户端展示"定时任务确认"卡片（时间 + 命令 + 确认按钮）
4. 用户点击确认 → 调 ScheduledTaskService.create() → SnackBar 提示成功
5. 用户后续可问 Agent "我有哪些定时任务" → Agent 调 list_scheduled_tasks 查询

### 依赖

- R062 定时任务基础设施（已完成归档）

## 目标平台

- Server: Docker (Linux x86_64)
- Client: macOS arm64 + Android
- Agent: 不改动
