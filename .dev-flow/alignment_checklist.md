# Alignment Checklist — R062

## 架构一致性

- [ ] 所有定时任务（一次性 + 每日）统一走 Server REST API，不使用客户端本地 Timer
- [ ] Server 调度使用 asyncio.create_task，不引入 APScheduler 依赖
- [ ] 定时任务发送复用现有 WS DATA 消息通道，不新增消息类型
- [ ] Server 仍然是消息中继中心，Agent 仍是无状态终端代理

## API 契约对齐

- [ ] POST /api/scheduled-tasks 鉴权（async_verify_token）
- [ ] GET /api/scheduled-tasks 支持按 session_id/status 过滤
- [ ] DELETE /api/scheduled-tasks/{id} 仅允许删除本人任务
- [ ] 创建时验证 Agent 在线（409 返回）
- [ ] 每日任务 execute_at 语义：time-of-day + timezone 锚点

## 调度语义

- [ ] 一次性任务：执行后 status=executed
- [ ] 每日任务：执行后计算下次 execute_at（次日同 time-of-day + timezone）
- [ ] 一次性 + Agent 离线：status=expired
- [ ] 每日 + Agent 离线：跳过本轮，保持 pending，execute_at 推到次日
- [ ] WS 发送异常与 Agent 离线同逻辑
- [ ] 过去时间 execute_at：创建时拒绝(400)
- [ ] 每日首次触发：所选 time-of-day 已过今日→首次执行为明日；未过→今日
- [ ] 不包含 cron_expr 字段，不包含 cancelled 状态

## API 行为对齐

- [ ] GET 支持 session_id 过滤
- [ ] GET 支持 status 过滤（pending/executed/expired）
- [ ] GET 支持 session_id + status 组合过滤
- [ ] POST 验证 session 存在（不存在→404）
- [ ] POST 验证 terminal 存在（不存在→404）
- [ ] POST 验证 execute_at 为未来时间（过去→400）
- [ ] Redis 不可用时 fail-closed(503)

## 客户端集成

- [ ] F001: ScheduledTask model + ScheduledTaskService 通过 HttpClientFactory
- [ ] F002: 轮询 30 秒间隔 + 创建后即时刷新
- [ ] F003: 长按发送→菜单→统一走 Server API 创建
- [ ] F004: 列表展示 + 客户端过滤 24 小时
- [ ] 跨设备：Server 单一数据源，天然同步

## 回归安全

- [ ] Server pytest 全通过
- [ ] Client flutter test 全通过
- [ ] Client flutter analyze 零 error/warning
