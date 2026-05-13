# Alignment Checklist — R063 Agent 定时任务

## 架构一致性

- [ ] AgentResult 调度字段（schedule_at/repeat_type）仅限 command 类型，message/ai_prompt 不允许携带
- [ ] schedule_at 必须是带时区的绝对 ISO 8601，不允许相对时间
- [ ] repeat_type 仅允许 once/daily
- [ ] schedule_at 和 repeat_type 必须同时存在或同时为空
- [ ] 复用 R062 ScheduledTaskStore 和 ScheduledTaskService，不新建存储层

## Agent 工具对齐

- [ ] list_scheduled_tasks 查询范围 = user_id + device_id + terminal_id（terminal 级隔离）
- [ ] cancel_scheduled_task 三重校验 = user_id + device_id + terminal_id
- [ ] session_id 命名映射：闭包使用 device_id 作为 store 的 session_id，非 AgentDeps.session_id
- [ ] System Prompt 注入当前时间（server UTC+8）+ 定时任务能力说明

## SSE 事件对齐

- [ ] agent_session_runner.py result_event_data 包含 schedule_at/repeat_type
- [ ] 缺失调度字段时 SSE 事件与 R062 完全一致（向后兼容）

## 客户端对齐

- [ ] F001: AgentResultEvent 保留非法值为原始字符串，由 F002 降级处理
- [ ] F002: text_content 由 steps 的 command 字段用 \r 拼接（非 _compileSteps 的 shell 模式）
- [ ] F002: repeatType 字符串转 ScheduledTaskRepeatType 枚举，非法值降级为 once
- [ ] F002: 创建成功后通过 onScheduledTaskCreated 回调通知父组件刷新 poller
- [ ] F002: SmartTerminalSidePanel 新增 onScheduledTaskCreated 回调，父组件持有 ScheduledTaskPoller
- [ ] F002: 移动端无 poller 时回调为 no-op，不报错

## 回归安全

- [ ] Server pytest: R063 专项覆盖 S001 校验 + B001 工具/越权
- [ ] Client flutter test: F001 解析 + F002 卡片/回调/降级
- [ ] 现有 Agent 对话功能不受影响（schedule_at=null 时行为不变）
