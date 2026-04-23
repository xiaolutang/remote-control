# S002: R041 验收 session

> 日期：2026-04-23
> 类型：验收 + 热修复

## 验收过程

1. 更换 LLM 模型：`MiniMax-M2.1` → `qwen3-vl-flash-2026-01-22`（MiniMax token 耗尽）
2. 重建部署 server Docker 镜像（旧镜像缺少 agent conversation 路由）
3. 双端（macOS + Android）启动测试
4. 发现双端消息同步 bug

## 发现的问题

### 问题 1：双端 conversation stream 事件不推送

- **现象**：桌面端发消息，手机端看不到
- **根因**：`agent_session_manager._emit_session_event` 持久化事件到 DB 并推给 SSE 发起方，但未调用 `_publish_conversation_stream_event` 通知 conversation stream 订阅者
- **修复**：在 `_emit_session_event` 中增加懒导入 `_publish_conversation_stream_event` 调用

### 问题 2：桌面端 SSE 流结束后丢失后续消息

- **现象**：agent run 完成后桌面端不再接收新消息
- **根因**：`_startAgentSession` 取消 `_conversationStreamSubscription`，SSE `onDone` 未重启
- **修复**：`onDone` 回调中加入 `_restartConversationStreamForCurrentScope()`

### 问题 3：模型交互不可观测

- **现象**：无法看到大模型的请求/响应/tool call 细节
- **影响**：无法判断模型行为是否符合预期，难以调试 prompt 和工具调用
- **状态**：未修复，需新增需求

## 修复文件

- `server/app/agent_session_manager.py` — `_emit_session_event` 增加 conversation stream 推送
- `client/lib/widgets/smart_terminal_side_panel_content.dart` — SSE `onDone` 重启 conversation stream
- `deploy/.env` — LLM 模型更换

## 验收结论

**未通过**。同步 bug 已修复但未完成验证；模型交互可观测性缺失。
