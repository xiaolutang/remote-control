---
date: 2026-05-12
type: requirement_clarification
status: decided
requirement_cycle: R062
architecture_impact: false
supersedes: 2026-05-12--scheduled-terminal-tasks
---

# 定时终端任务 — 统一 Server 路径

## 背景

初版规划将一次性任务放客户端本地 Timer、每日重复放 Server APScheduler。Plan review 发现路由冲突、跨设备同步和 UI dispatch 问题，统一收敛为 Server 单一路径。

## 核心定义

**一句话**：定时给终端发消息 = 延迟发送终端输入

不是任务编排系统，不是 cron 替代品，只是"用户现在想输入的文本，改到未来某个时刻自动输入"。

## 产品决策

### 入口

输入框 → 长按发送按钮 → 弹出"定时发送"选项 → 选择时间 → 确认

不做独立的"定时任务管理"页面，入口嵌入终端交互流程中。

### 展示

定时任务创建后，目标终端输入区上方立即出现小标签（显示时间和命令摘要），可点击取消。客户端在创建成功后立即刷新列表，不依赖轮询。

### 前提条件

Agent 和终端必须在线才能创建定时任务。离线时直接提示"终端不在线"，不创建不排队。

### 形态

| 类型 | 场景 | 存储 | 调度方 |
|------|------|------|--------|
| 一次性 | "30分钟后跑一下" | Server SQLite | Server asyncio 后台协程 |
| 每日重复 | "每天凌晨3点执行" | Server SQLite | Server asyncio 后台协程 |

**统一路径**：所有任务（一次性 + 每日）都走 Server REST API 创建 → Server SQLite 存储 → Server asyncio 后台协程调度 → WS DATA 消息发送。

不做 cron 表达式、不做条件触发。

### 每日任务契约

- 创建时提交 `execute_at`（ISO 8601 带时区）作为每日触发时间锚点
- Server 仅使用 `execute_at` 的 time-of-day + timezone 部分
- 执行成功后，计算下一个 `execute_at = 当前日期 + 1天 + time-of-day + timezone`
- 执行时 Agent 离线：**跳过本轮**，状态保持 `pending`，不标记 `expired`
- 一次性任务执行时 Agent 离线：标记 `expired`

### 执行结果

不追踪。定时任务只是按时发文本，命令执行成功/失败是终端的事，用户看终端输出即可。

### 离线策略

- 创建时：Agent 不在线 → 拒绝创建（409）
- 执行时 Agent 掉线：一次性标记过期，每日重复跳过本轮
- 客户端关闭/换设备：所有任务在 Server，跨设备天然同步

### 自动清理

- Server 端不负责自动清理（范围外）
- 客户端展示时过滤掉 executed/expired 超过 24 小时的任务

## 技术方案

### Server 端

- 新增 `scheduled_tasks` 表（SQLite）
- asyncio.create_task 后台协程轮询调度（不引入 APScheduler）
- 新增 REST API：`POST /api/scheduled-tasks`、`GET /api/scheduled-tasks`、`DELETE /api/scheduled-tasks/{id}`
- 复用现有 WS DATA 消息通道发送

### Client 端

- 所有任务通过 Server REST API 创建和管理
- 客户端轮询 pending 任务列表（30 秒间隔），展示定时标签
- 创建成功后立即触发一次列表刷新（不等轮询）
- Agent 离线时禁用创建入口

## 架构影响

无。不涉及 architecture.md 变更。Server 仍然是消息中继中心，Agent 仍是无状态终端代理。

## 后续动作

- 进入 xlfoundry-plan 拆解任务
