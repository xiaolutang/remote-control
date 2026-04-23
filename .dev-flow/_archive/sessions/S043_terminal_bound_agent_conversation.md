# Session S043: Terminal-bound Agent 对话同步长期规划

> 日期：2026-04-24
> 状态：已规划，待执行

## 需求来源

用户确认：

- 手机端没有自己的 ReAct 工具，工具都在桌面设备 Agent 侧执行
- 手机端和桌面端本质上应维护同一个 terminal 的同一套智能对话
- Agent 对话必须和 terminal 一一对应
- terminal 关闭时，对应的智能对话也必须销毁，不能继续维持或复用旧上下文

## 架构结论

1. Server 是 Agent conversation 的权威源。

客户端本地历史只做渲染缓存，不能再作为下一轮 AI 上下文的权威来源。

2. Conversation 绑定 terminal。

同一 `user_id + device_id + terminal_id` 只有一个 active conversation；手机端和桌面端都是该 conversation 的视图/输入端。

3. 手机端可以参与对话，但不执行工具。

手机端可以发起目标、回答 Agent 追问、展示 trace/result；只读探索命令仍由 Server 调度到承载 terminal 的桌面设备 Agent 执行。

4. Server 从 conversation events 重建 `message_history`。

下一轮 ReAct Agent 调用必须继承同 terminal 的历史事件，例如用户前面已经选择过项目，后续说“这个项目”时 AI 应能基于服务端历史理解。

5. terminal close 即 conversation close/destroy。

terminal 被用户关闭、设备离线收口为 closed、登出或权限失效时，Server 必须先广播 ephemeral `closed` 事件给 active stream，再取消 active Agent session，进入不超过 30 秒的 closed tombstone，随后删除历史事件；对外拒绝后续 run/respond/resume/fetch。

6. 多端写入必须幂等。

run/respond 需要 `client_event_id`，respond 需要 `question_id`。同一 `client_event_id` 重试不得产生重复事件；同一 `question_id` 只能成功回答一次，多端并发第二个回答返回 409。

## 规划结果

新增 `CONTRACT-049` 和 8 个任务：

- `S083`：契约与生命周期基线
- `B085`：conversation 持久化模型与权限校验
- `B086`：run/respond/resume/cancel 绑定 terminal conversation
- `B087`：conversation fetch/stream 多端同步 API
- `B088`：服务端 `message_history` 重建与 terminal close 销毁
- `F101`：客户端接入服务端 conversation 投影
- `F102`：手机端/桌面端同步 UI 与关闭清理
- `S084`：本地 Docker + macOS + Android 全链路验收

## 风险与测试重点

- `auth`：跨用户、跨 device、跨 terminal 的 conversation 必须隔离
- `network`：SSE 断连、resume、fetch/stream 增量必须稳定
- `first_use`：无历史、无 active conversation、首次打开智能面板必须是空投影而不是旧本地缓存
- `mobile`：移动端智能输入框不得和正常 terminal 输入/软键盘处理冲突
- `lifecycle`：terminal close 后旧 session、旧 answer、旧 resume 都必须失败
- `concurrency`：多端同时回答同一个 Agent question 只能成功一次
- `idempotency`：弱网重复提交同一个 client event 不能产生重复 answer

## 后续执行入口

推荐从 `S083` 开始，先锁定 CONTRACT-049 与状态机，再执行服务端存储/API，最后接前端投影和多端 smoke。
