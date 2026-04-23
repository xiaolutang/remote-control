# R041: react-terminal-agent

> 状态：**验收未通过** (2026-04-23)
> 分支：`feat/R041-react-terminal-agent`

## 范围

Server Terminal-bound ReAct Agent：Pydantic AI agent 循环 + SSE 流式推送 + 探索命令 + 双端 conversation 同步 + Token usage 追踪。

## 任务统计

| 状态 | 数量 |
|------|------|
| completed | 44 |
| pending | 2 |
| in_progress | 1 |
| cancelled | 4 |
| **总计** | **51** |

## 验收结果：未通过

### 已完成功能

- ReAct Agent 循环（Pydantic AI + terminal-bound session）
- SSE 流式推送（trace / question / result / error）
- 探索命令（只读白名单 + shell 元字符拦截）
- Agent conversation 持久化（SQLite）
- Conversation projection API（双端拉取同一权威 conversation）
- Token usage 追踪与 SSE 推送
- 客户端 Token 统计展示（可折叠卡片 + 历史气泡）
- Agent 会话断连恢复（resume）
- 用户回复（respond）、取消（cancel）

### 未通过原因

1. **双端消息同步 bug**：桌面端发起的 agent run 事件未推送到 conversation stream 订阅者，手机端收不到实时消息
   - 根因：`agent_session_manager._emit_session_event` 缺少 `_publish_conversation_stream_event` 调用
   - 已修复但未验证

2. **桌面端 SSE 流结束后不接收后续消息**：SSE 流关闭后 conversation stream 订阅未重启
   - 根因：`_startAgentSession` 的 `onDone` 回调缺少重启逻辑
   - 已修复但未验证

3. **模型交互过程不可观测**：无法看到大模型的原始交互过程（请求/响应/tool call），难以排查模型行为是否符合预期

### 遗留修复（已提交代码未验证）

- `server/app/agent_session_manager.py`：`_emit_session_event` 增加 `_publish_conversation_stream_event`
- `client/lib/widgets/smart_terminal_side_panel_content.dart`：SSE `onDone` 增加 `_restartConversationStreamForCurrentScope()`

### 后续需求

- 新需求：模型交互过程可观测性（trace/debug UI 或日志）
- 新需求：双端消息同步验收（含回归测试）

## 模型配置

- 当前：`qwen3-vl-flash-2026-01-22`（DashScope 兼容 API）
- 前一模型：`MiniMax-M2.1`（token 用尽已更换）

## 快照

- 完整任务列表：`feature_list.snapshot.json`
- 架构设计 session：`sessions/S001_agent_architecture_design.md`
