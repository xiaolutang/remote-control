# API 契约

## 契约索引

> 按 CONTRACT-ID 检索，只加载需要的段落。

| CONTRACT | 行号 | 主题 | 关联任务 |
|----------|------|------|---------|
| CONTRACT-001 | 93 | Session 状态查询 | B001, B004, F002, F003 |
| CONTRACT-002 | 130 | Agent WebSocket 连接 | B001, B002, B003, B004 |
| CONTRACT-003 | 198 | Client / View WebSocket 连接 | B001, B002, F002, F003, S002 |
| CONTRACT-004 | 260 | 登录 | B004, F003 |
| CONTRACT-005 | 301 | 刷新 Token | B004 |
| CONTRACT-006 | 522 | 移动端终端快捷键配置 | F007, F008 |
| CONTRACT-007 | 562 | 快捷项配置模型 | F009, F010, F011 |
| CONTRACT-008 | 598 | Claude 导航语义 | F012 |
| CONTRACT-009 | 641 | 主题模式配置 | F013, F014 |
| CONTRACT-010 | 338 | 在线设备列表 | S011, B006, B008, F015, F016 |
| CONTRACT-011 | 366 | 设备 terminal 列表与创建 | S011, B007, B008, F015, F016 |
| CONTRACT-012 | 419 | Terminal Client WebSocket | S011, B009, F015, F016, S012 |
| CONTRACT-013 | 451 | Agent Terminal 生命周期事件 | S011, B009, B011, S012 |
| CONTRACT-014 | 489 | 关闭原因与状态语义 | S011, B006-B011, F015, S012 |
| CONTRACT-015 | 667 | 设备在线与实时视图数 | S013, B012, B013, F017, S014 |
| CONTRACT-016 | 712 | Workspace 初始化与 Tab | S014, F018, F019 |
| CONTRACT-017 | 747 | 创建准入与关闭清理 | S015, B014, B015, F020 |
| CONTRACT-018 | 764 | 桌面端 Agent 恢复前置 | S015, B015, F020 |
| CONTRACT-019 | 780 | 顶部状态栏与菜单 | S016, F021, F022 |
| CONTRACT-020 | 797 | 设备离线 terminal 收口 | S017, B016, B017, F023 |
| CONTRACT-021 | 815 | Agent 后台与退出语义 | S018, B018, F024, F025 |
| CONTRACT-022 | 834 | Agent 管理子系统 | S019, B019, F026, F027 |
| CONTRACT-023 | 853 | 工作台空状态归一化 | S020, F028 |
| CONTRACT-024 | 870 | Agent 本地 HTTP Supervisor | S021, B020, F029 |
| CONTRACT-025 | 929 | Server Agent TTL 机制 | S021, B021 |
| CONTRACT-026 | 963 | 桌面端与手机端行为差异 | S021, F030 |
| CONTRACT-027 | 995 | Agent 生命周期管理 | S024, F032-F044 |
| CONTRACT-028 | 1139 | 登录层 Token 版本与同端限制 | B038, B039, F048, F049, S025 |
| CONTRACT-029 | 45 | 日志集成（SDK + Client 转发） | B043, B044, B045, B046, B047, S028, S029 |
| CONTRACT-030 | 1098 | 同端设备在线数限制（简化为直接踢出） | B036, B042, F050 |
| CONTRACT-031 | 1270 | 安全加固：WS 鉴权消息协议 | B062, B065, B068, F058 |
| CONTRACT-032 | 1310 | 安全加固：认证与密码策略 | B062, B063, B066 |
| CONTRACT-033 | 1350 | 安全加固：CORS + 速率限制 | B064, B067 |
| CONTRACT-034 | 1390 | 安全加固：Redis 密码 + Docker 非 root | B070 |
| CONTRACT-035 | 1420 | 安全加固：Agent 本地 HTTP 认证 | B068 |
| CONTRACT-036 | 1450 | 安全加固：Client 安全存储 | F058 |
| CONTRACT-037 | 1421 | RSA+AES 加密登录/注册 | S063, S064 |
| CONTRACT-038 | 1456 | WebSocket AES 加解密 | S063, S064 |
| CONTRACT-039 | 1491 | 终端恢复状态机与生命周期语义 | S071, S072, F072, F076 |
| CONTRACT-040 | 1519 | Server terminal metadata / ownership / lifecycle truth | B071, F075 |
| CONTRACT-041 | 1560 | Agent terminal snapshot authority | B072, F075 |
| CONTRACT-042 | 1590 | Terminal recovery WebSocket protocol | S072, S073, B071, B072, B073, F071, F072, F075, F076 |
| CONTRACT-043 | 1652 | Claude 智能终端命令编排 | S077, F077, F078, F079, F080, F081 |
| CONTRACT-044 | 1737 | 命令规划 provider 隔离与执行语义 | S078, B074, F086, F082, F083, F084, F085 |
| CONTRACT-045 | TBD | 智能终端助手规划接口（注：F088/F089 为旧聊天流任务已 cancelled，与 R043 新 F088/F089 无关） | S079, S080, B075, B076, F087, F088_old, F089_old, F090, F091, F092 |
| CONTRACT-046 | TBD | 智能终端助手执行结果回写 | B076, B077, F090, F091, F092, F093_old |
| CONTRACT-047 | TBD | ReAct Agent SSE 事件流与只读探索协议 | B078, B079, B080, F095_old, B083, F099, B094, F088, S088, B105, B106, F107, S110 |
| CONTRACT-048 | TBD | Agent usage 汇总 API | B084, F100, B105, B106, S110 |
| CONTRACT-049 | TBD | Terminal-bound Agent conversation 同步与生命周期 | S083, B085, B086, B087, B088, F101, F102, S084, B106, F107, S110 |
| CONTRACT-050 | 2256 | 动态工具注册与调用协议 + 信息型问答结果扩展 + response_type + skill 配置 | B091, B092, B093, B094, F088, S088, B095, F089, B106, F107, S110 |
| CONTRACT-051 | 2610 | Eval 框架核心：Task 定义 + Harness + Grader + 数据模型 | B096, B097, B098, B099, B100, S089, S090, B108 |
| CONTRACT-052 | 2680 | 在线质量指标提取与查询 API | B101, B102, S091 |
| CONTRACT-053 | 2730 | 反馈闭环：Candidate + 回归测试 + CLI | B103, B104, S092 |

## 日志集成

### Client 日志转发到 log-service

| 字段 | 值 |
|------|----|
| ID | CONTRACT-029 |
| Scope | Server（代理转发） |
| Related Tasks | B043, B046, S029 |

#### 日志路径

- 路径 A（Server/Agent 自身日志）：Python logging → log-service-sdk（RemoteLogHandler）→ log-service ingest
- 路径 B（Client 日志代理转发）：Client → POST /api/logs → Server log_api.py → httpx 异步转发 → log-service ingest

#### POST /api/logs 转发行为

- 保存 Redis 后，异步调用 log-service ingest API 转发（httpx.AsyncClient, timeout=3s）
- 转发日志使用 service_name='remote-control', component='client'
- 转发失败不影响 Redis 存储和 API 响应（静默失败，记录本地 warning）

#### log-service-sdk 接入

| 参数 | 值 |
|------|----|
| service_name | remote-control |
| component（Server） | server |
| component（Agent） | agent |
| endpoint 环境变量 | LOG_SERVICE_URL（Docker: http://log-service:8001，Desktop Agent: 可选配置） |

#### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| LOG_SERVICE_URL | http://localhost:8001 | log-service ingest 地址 |
| LOG_LEVEL | INFO | Python logging 级别 |

#### Rules

| Rule | Meaning |
|------|---------|
| SDK for own logs | Server/Agent 使用 log-service-sdk 的 RemoteLogHandler 上报自身日志 |
| httpx for proxy | Server 代理转发 Client 日志使用 httpx.AsyncClient，不使用 SDK |
| SDK silent retry | Server/Agent 自身日志走 SDK，静默重试，不影响业务运行 |
| Proxy best-effort | Client 日志代理转发为 best-effort（一次性，不重试），失败仅记录 warning |
| Desktop Agent optional | Desktop Agent 无需 LOG_SERVICE_URL，未配置时仅本地日志 |
| Auth error passthrough | ErrorHandlerMiddleware 不包装 TokenVerificationError，保持 error_code 透传 |

## 共享会话

### Session 状态查询

| 字段 | 值 |
|------|----|
| ID | CONTRACT-001 |
| Method | GET |
| Path | /api/sessions/{session_id} |
| Auth | Bearer Token |
| Related Tasks | B001, B004, F002, F003 |

#### Response 200

```json
{
  "session_id": "gDgDSu1f1oqnAVeP",
  "owner": "testuser",
  "agent_online": true,
  "views": {
    "mobile": 1,
    "desktop": 1
  },
  "pty": {
    "rows": 40,
    "cols": 120
  },
  "updated_at": "2026-03-27T16:45:00Z"
}
```

#### Errors

| Code | Meaning |
|------|---------|
| 401 | token 无效或过期 |
| 403 | 会话不属于当前用户 |
| 404 | session 不存在 |

### Agent WebSocket 连接

| 字段 | 值 |
|------|----|
| ID | CONTRACT-002 |
| Method | GET |
| Path | /ws/agent |
| Auth | 首条 auth 消息 |
| Related Tasks | B001, B002, B003, B004, B065, B068 |

#### Connected Message

```json
{
  "type": "connected",
  "session_id": "gDgDSu1f1oqnAVeP",
  "owner": "testuser",
  "views": {
    "mobile": 0,
    "desktop": 0
  },
  "timestamp": "2026-03-27T16:45:00Z"
}
```

#### Server -> Agent Messages

```json
{
  "type": "data",
  "source_view": "mobile",
  "payload": "YmFzaAo="
}
```

```json
{
  "type": "resize",
  "source_view": "desktop",
  "rows": 40,
  "cols": 120
}
```

#### Agent -> Server Messages

```json
{
  "type": "data",
  "direction": "output",
  "payload": "G1szMm1vayAbWzBt"
}
```

```json
{
  "type": "ping"
}
```

#### Errors

| Code | Meaning |
|------|---------|
| 4001 | token 无效 |
| 4003 | 无权访问该会话 |
| 4004 | auth 消息格式错误 / terminal 不存在 |
| 4009 | 当前 session 已有活动 agent |

### Client / View WebSocket 连接

| 字段 | 值 |
|------|----|
| ID | CONTRACT-003 |
| Method | GET |
| Path | /ws/client?session_id={id}&view={mobile\|desktop} |
| Auth | 首条 auth 消息 |
| Related Tasks | B001, B002, F002, F003, S002, B065, F058 |

#### Connected Message

```json
{
  "type": "connected",
  "session_id": "gDgDSu1f1oqnAVeP",
  "agent_online": true,
  "view": "mobile",
  "owner": "testuser",
  "timestamp": "2026-03-27T16:45:00Z"
}
```

#### Bidirectional Messages

```json
{
  "type": "data",
  "payload": "aGVsbG8NCg==",
  "timestamp": "2026-03-27T16:45:00Z"
}
```

#### Presence Update

```json
{
  "type": "presence",
  "views": {
    "mobile": 1,
    "desktop": 1
  }
}
```

#### Errors

| Code | Meaning |
|------|---------|
| 401 | token 无效 |
| 403 | 会话不属于当前用户 |
| 404 | 会话不存在 |
| 4503 | 视图数量超过限制 |

## 智能终端助手

### 智能终端助手规划接口

| 字段 | 值 |
|------|----|
| ID | CONTRACT-045 |
| Method | POST |
| Path | /api/runtime/devices/{device_id}/assistant/plan |
| Auth | Bearer Token |
| Related Tasks | S079, S080, B075, B076, F087, F088_old, F089_old, F090, F091, F092 |

#### Request

```json
{
  "intent": "进入 remote-control 修登录问题",
  "conversation_id": "assistant-session-001",
  "message_id": "msg-001",
  "fallback_policy": {
    "allow_claude_cli": true,
    "allow_local_rules": true
  }
}
```

#### Request Rules

| Rule | Meaning |
|------|---------|
| User-scoped throttling | 同一用户对 `assistant/plan` 的调用必须受速率限制保护 |
| Provider timeout bounded | 服务端对外部 LLM/provider 调用必须设置硬超时，超时后返回稳定错误而不是无限等待 |
| Budget aware | 达到当日/当期预算或配额上限时，必须直接返回可解释错误 |
| Fallback friendly | `assistant/plan` 失败时必须允许客户端继续走 `claude_cli` / `local_rules` / 手动创建 |

#### Response 200

```json
{
  "conversation_id": "assistant-session-001",
  "message_id": "msg-001",
  "assistant_messages": [
    {
      "type": "assistant",
      "text": "我先帮你定位目标项目，再生成执行命令。"
    }
  ],
  "trace": [
    {
      "stage": "context",
      "title": "读取上下文",
      "status": "completed",
      "summary": "命中最近项目 remote-control"
    },
    {
      "stage": "planner",
      "title": "调用服务端 LLM",
      "status": "completed",
      "summary": "已生成合法命令序列"
    },
    {
      "stage": "validation",
      "title": "安全校验",
      "status": "completed",
      "summary": "未发现危险命令"
    }
  ],
  "command_sequence": {
    "summary": "进入 remote-control 并启动 Claude",
    "provider": "service_llm",
    "source": "intent",
    "need_confirm": true,
    "steps": [
      {
        "id": "step_1",
        "label": "进入项目目录",
        "command": "cd /Users/demo/project/remote-control"
      },
      {
        "id": "step_2",
        "label": "启动 Claude",
        "command": "claude"
      }
    ]
  },
  "fallback_used": false,
  "fallback_reason": null,
  "limits": {
    "rate_limited": false,
    "budget_blocked": false,
    "provider_timeout_ms": 12000
  },
  "evaluation_context": {
    "matched_candidate_id": "cand_123",
    "memory_hits": 1,
    "tool_calls": 2
  }
}
```

#### Rules

| Rule | Meaning |
|------|---------|
| Server-side planning | 主规划链路由服务端 LLM 完成，客户端只负责发起、展示、确认与执行 |
| Structured trace only | 返回结构化 `trace` 与 `assistant_messages`，不返回模型原始 chain-of-thought |
| Current-device context only | 输入上下文只能来自当前设备事实、recent terminal、planner memory、候选项目与用户输入 |
| Single execution artifact | 最终执行产物必须收口为 `command_sequence` |
| Explicit confirm required | `need_confirm=true` 时客户端必须等待用户确认后才能创建 terminal 执行 |
| Fallback visible | 若发生 `service_llm -> claude_cli -> local_rules` 回退，必须通过 `fallback_used/fallback_reason` 返回 |
| Rate limit visible | 若触发用户级限流，必须返回稳定的限流错误与可重试信息 |
| Timeout bounded | provider 超时必须在服务端受控时间内失败，不得让客户端无限等待 |
| Budget visible | 若达到预算/配额上限，必须返回明确错误，便于客户端走 fallback 或手动路径 |
| Evaluation trace persisted | 服务端必须为本次规划写入可回放 trace 与评估上下文，供 benchmark / 回放 / 人工验收使用 |

#### Errors

| Code | Meaning |
|------|---------|
| 400 | intent 为空或超出长度限制 |
| 401 | token 无效或过期 |
| 403 | 当前用户无权访问该 device_id |
| 409 | 当前设备未在线，无法生成可执行终端方案 |
| 429 | 用户触发 planner 限流或预算/配额受限 |
| 422 | planner 返回无效命令结构且 fallback 也失败 |
| 504 | provider 调用超时 |
| 503 | 服务端 LLM planner 不可用，且没有可用 fallback |

### 智能终端助手执行结果回写

| 字段 | 值 |
|------|----|
| ID | CONTRACT-046 |
| Method | POST |
| Path | /api/runtime/devices/{device_id}/assistant/executions/report |
| Auth | Bearer Token |
| Related Tasks | B076, B077, F090, F091, F092, F093_old |

#### Request

```json
{
  "conversation_id": "assistant-session-001",
  "message_id": "msg-001",
  "terminal_id": "term_123",
  "execution_status": "succeeded",
  "failed_step_id": null,
  "output_summary": "已进入 remote-control 并启动 Claude",
  "command_sequence": {
    "summary": "进入 remote-control 并启动 Claude",
    "provider": "service_llm",
    "source": "intent",
    "need_confirm": true,
    "steps": [
      {
        "id": "step_1",
        "label": "进入项目目录",
        "command": "cd /Users/demo/project/remote-control"
      },
      {
        "id": "step_2",
        "label": "启动 Claude",
        "command": "claude"
      }
    ]
  }
}
```

#### Response 200

```json
{
  "acknowledged": true,
  "memory_updated": true,
  "evaluation_recorded": true
}
```

#### Rules

| Rule | Meaning |
|------|---------|
| Execution result required | 只有收到执行结果回写后，服务端才允许更新 planner memory 与评估结果 |
| Conversation scoped | 回写必须基于 `conversation_id + message_id + device_id` 关联到单次规划 |
| User-edited sequence wins | 若用户编辑过命令卡片，回写必须以上报的最终 `command_sequence` 为准 |
| Failure visible | 失败时必须携带 `failed_step_id` 与输出摘要，供 trace 回放和失败分类 |
| Idempotent enough | 重复上报同一 `conversation/message` 不得产生重复记忆写入 |

#### Errors

| Code | Meaning |
|------|---------|
| 400 | 缺少执行状态或 command_sequence 结构非法 |
| 401 | token 无效或过期 |
| 403 | 当前用户无权访问该 device_id |
| 404 | 找不到对应的规划会话 |
| 409 | 规划已被新的 message 覆盖或已终态关闭 |

## 认证

### 登录

| 字段 | 值 |
|------|----|
| ID | CONTRACT-004 |
| Method | POST |
| Path | /api/login |
| Auth | None |
| Related Tasks | B004, F003, B056 |

#### Request

```json
{
  "username": "testuser",
  "password": "test123456",
  "view": "mobile"
}
```

#### Response 200

```json
{
  "success": true,
  "message": "登录成功",
  "username": "testuser",
  "session_id": "gDgDSu1f1oqnAVeP",
  "token": "jwt",
  "expires_at": "2026-04-13T16:45:00Z",
  "refresh_token": "jwt",
  "refresh_expires_at": "2026-04-27T16:45:00Z"
}
```

#### Errors

| Code | Meaning |
|------|---------|
| 401 | 用户名或密码错误 |

### 刷新 Token

| 字段 | 值 |
|------|----|
| ID | CONTRACT-005 |
| Method | POST |
| Path | /api/refresh |
| Auth | None |
| Related Tasks | B004 |

#### Request

```json
{
  "refresh_token": "jwt"
}
```

#### Response 200

```json
{
  "success": true,
  "access_token": "jwt",
  "refresh_token": "jwt",
  "expires_in": 86400
}
```

#### Errors

| Code | Meaning |
|------|---------|
| 401 | refresh token 无效或过期 |

## 多 terminal 架构

### 在线设备列表

| 字段 | 值 |
|------|----|
| ID | CONTRACT-010 |
| Method | GET |
| Path | /api/runtime/devices |
| Auth | Bearer Token |
| Related Tasks | S011, B006, B008, F015, F016 |

#### Response 200

```json
{
  "devices": [
    {
      "device_id": "mbp-01",
      "name": "Tang MacBook Pro",
      "owner": "testuser",
      "agent_online": true,
      "last_heartbeat_at": "2026-03-29T01:40:00Z",
      "max_terminals": 5,
      "active_terminals": 2
    }
  ]
}
```

### 设备 terminal 列表与创建

| 字段 | 值 |
|------|----|
| ID | CONTRACT-011 |
| Method | GET / POST |
| Path | /api/runtime/devices/{device_id}/terminals |
| Auth | Bearer Token |
| Related Tasks | S011, B007, B008, F015, F016 |

#### GET Response 200

```json
{
  "device_id": "mbp-01",
  "device_online": true,
  "terminals": [
    {
      "terminal_id": "term-01",
      "title": "Claude / ai_rules",
      "cwd": "/home/user/project/remote-control",
      "status": "attached",
      "views": {
        "mobile": 1,
        "desktop": 1
      },
      "disconnect_reason": null
    }
  ]
}
```

#### POST Request

```json
{
  "title": "Claude / ai_rules",
  "cwd": "/home/user/project/remote-control",
  "command": "claude code",
  "env": {
    "TERM": "xterm-256color"
  }
}
```

#### POST Errors

| Code | Meaning |
|------|---------|
| 403 | 设备不属于当前用户 |
| 409 | 设备离线或 terminal 数量已达上限 |
| 504 | 已通过准入校验，但 Agent 创建 terminal 超时 |

### Terminal Client / View WebSocket

| 字段 | 值 |
|------|----|
| ID | CONTRACT-012 |
| Method | GET |
| Path | /ws/client?device_id={id}&terminal_id={id}&view={mobile\|desktop} |
| Auth | 首条 auth 消息 |
| Related Tasks | S011, B009, F015, F016, S012, B065, F058 |

#### Connected Message

```json
{
  "type": "connected",
  "device_id": "mbp-01",
  "terminal_id": "term-01",
  "device_online": true,
  "terminal_status": "attached",
  "view": "mobile",
  "owner": "testuser",
  "timestamp": "2026-03-29T01:40:00Z"
}
```

#### Errors

| Code | Meaning |
|------|---------|
| 404 | device 或 terminal 不存在 |
| 409 | device offline / terminal closed / terminal unavailable |

### Agent Terminal 生命周期事件

| 字段 | 值 |
|------|----|
| ID | CONTRACT-013 |
| Method | WebSocket Message |
| Path | /ws/agent?token={jwt} |
| Auth | Bearer Token |
| Related Tasks | S011, B009, B011, S012 |

#### Agent -> Server Messages

```json
{
  "type": "terminal_created",
  "terminal_id": "term-01",
  "title": "Claude / ai_rules",
  "cwd": "/home/user/project/remote-control"
}
```

```json
{
  "type": "terminal_closed",
  "terminal_id": "term-01",
  "reason": "terminal_exit"
}
```

```json
{
  "type": "data",
  "terminal_id": "term-01",
  "direction": "output",
  "payload": "YmFzaAo="
}
```

### Device / Terminal 关闭原因与状态语义

| 字段 | 值 |
|------|----|
| ID | CONTRACT-014 |
| Method | Shared State |
| Path | session/device/terminal state |
| Auth | Bearer Token |
| Related Tasks | S011, B006, B007, B009, B010, B011, F015, S012 |

#### Allowed Terminal Status

- `pending`
- `attached`
- `detached`
- `closing`
- `closed`

#### Allowed Disconnect Reasons

- `network_lost`
- `agent_shutdown`
- `terminal_exit`
- `server_forced_close`

#### Rules

- `device_online=false` 时，不允许新建或附着 terminal
- `terminal_status=detached` 且仍在 grace period 时，允许恢复
- `terminal_status=closed` 时，只能查看历史状态，不能重新附着

## 客户端交互契约

### 移动端终端快捷键配置

| 字段 | 值 |
|------|----|
| ID | CONTRACT-006 |
| Scope | Client-side |
| Related Tasks | F007, F008 |

#### Shortcut Profile

```json
{
  "profile_id": "claude_code",
  "platforms": ["android", "ios"],
  "actions": [
    {
      "id": "esc",
      "label": "Esc",
      "type": "sendEscapeSequence",
      "value": "\\u001b"
    },
    {
      "id": "ctrl_c",
      "label": "Ctrl+C",
      "type": "sendControl",
      "value": "c"
    }
  ]
}
```

#### Rules

| Rule | Meaning |
|------|---------|
| Mobile only | 快捷键层只在移动端渲染，桌面端不显示 |
| Reuse transport | 所有快捷键动作复用现有终端输入发送链路，不新增后端协议 |
| Profile based | 当前默认 `claude_code`，后续其他终端通过 profile 扩展 |
| Stable IME | 点击快捷键不得破坏当前软键盘焦点与 IME 输入能力 |

### 快捷项配置模型

| 字段 | 值 |
|------|----|
| ID | CONTRACT-007 |
| Scope | Client-side |
| Related Tasks | F009, F010, F011 |

#### Shortcut Item

```json
{
  "id": "claude_help",
  "label": "/help",
  "source": "builtin",
  "section": "smart",
  "action_type": "sendText",
  "payload": "/help\r",
  "enabled": true,
  "pinned": false,
  "order": 20,
  "use_count": 3,
  "last_used_at": "2026-03-28T23:40:00Z",
  "scope": "project"
}
```

#### Rules

| Rule | Meaning |
|------|---------|
| Core fixed | 核心固定区项目不参与自动重排 |
| Smart ordered | 智能区按 `pinned -> last_used_at -> order` 排序 |
| Source aware | `builtin / user / project` 三类来源共用同一模型 |
| Local persistence | 用户调整结果保存在客户端本地配置 |

### Claude 导航语义

| 字段 | 值 |
|------|----|
| ID | CONTRACT-008 |
| Scope | Client-side |
| Related Tasks | F012 |

#### Navigation Actions

```json
{
  "profile_id": "claude_code",
  "navigation": [
    {
      "id": "prev_item",
      "label": "上一项",
      "action_type": "sendEscapeSequence",
      "payload": "\\u001b[A"
    },
    {
      "id": "next_item",
      "label": "下一项",
      "action_type": "sendEscapeSequence",
      "payload": "\\u001b[B"
    },
    {
      "id": "confirm",
      "label": "确认",
      "action_type": "sendText",
      "payload": "\\r"
    }
  ]
}
```

#### Rules

| Rule | Meaning |
|------|---------|
| User-facing semantics | UI 文案使用 `上一项 / 下一项 / 确认`，不直接暴露底层序列名称 |
| Swappable mapping | 底层映射允许根据 Claude Code 实际行为校准，而不改 UI 语义 |

### 主题模式配置

| 字段 | 值 |
|------|----|
| ID | CONTRACT-009 |
| Scope | Client-side |
| Related Tasks | F013, F014 |

#### Theme Config

```json
{
  "theme_mode": "system",
  "available_modes": ["system", "light", "dark"],
  "entry_points": ["login_screen", "terminal_screen"]
}
```

#### Rules

| Rule | Meaning |
|------|---------|
| Persisted locally | 主题模式保存在客户端本地配置 |
| App-wide | 主题切换作用于整个 App，而不是单页面局部状态 |
| Terminal aware | 终端外壳与终端内部主题都必须跟随主题模式变化 |

### 设备在线与实时视图数语义

| 字段 | 值 |
|------|----|
| ID | CONTRACT-015 |
| Scope | Server + Client |
| Related Tasks | S013, B012, B013, F017, S014 |

#### Online Semantics

```json
{
  "device_online": true,
  "meaning": "device_agent_online",
  "definition": "当前电脑上的 Agent 在线，且此设备可以创建并承载 terminal",
  "not_equivalent_to": [
    "desktop_client_open",
    "terminal_view_attached",
    "terminal_runtime_alive"
  ]
}
```

#### Terminal Snapshot Rules

```json
{
  "device_id": "gDgDSu1f1oqnAVeP",
  "terminal_id": "term-1",
  "status": "attached",
  "views": {
    "mobile": 1,
    "desktop": 1
  }
}
```

| Rule | Meaning |
|------|---------|
| Device online authoritative | `device_online` / `agent_online` 只由后端 Agent 连接与心跳维护 |
| View count authoritative | terminal `views` 由服务端当前活跃 ws 连接实时计算，不以客户端缓存或 Redis 历史聚合字段为准 |
| Enter page refresh | 客户端进入 terminal 页前应先拉取当前 terminal 快照 |
| Return page refresh | 客户端从 terminal 页返回列表页时应刷新 device/terminal 列表 |
| Presence incremental | ws `presence` 仅用于后续增量更新，不作为首次进入页面的唯一真相源 |

### Terminal Workspace 初始化与 Tab 语义

| 字段 | 值 |
|------|----|
| ID | CONTRACT-016 |
| Scope | Client-side + Runtime API |
| Related Tasks | S014, F018, F019 |

#### Workspace Snapshot

```json
{
  "device_id": "gDgDSu1f1oqnAVeP",
  "device_online": true,
  "max_terminals": 3,
  "terminals": [
    {
      "terminal_id": "term-1",
      "title": "Claude / ai_rules",
      "status": "attached",
      "updated_at": "2026-03-29T22:05:00Z"
    }
  ],
  "default_terminal_id": "term-1"
}
```

| Rule | Meaning |
|------|---------|
| Direct workspace entry | 登录后优先进入 terminal workspace，而不是先停留在设备/terminal 选择页 |
| Snapshot first | workspace 初始化必须先拉取当前 device + terminal 快照 |
| Default terminal | 若存在 terminal，默认进入最近活跃 terminal；若不存在，展示创建首个 terminal 空态 |
| Tab switching | 现有 terminal 通过 tab 切换；`+` tab 触发创建 terminal |
| Server-authoritative counts | terminal 个数与上限均以后端快照为准 |

### terminal 创建准入与关闭清理语义

| 字段 | 值 |
|------|----|
| ID | CONTRACT-017 |
| Scope | Server + Client |
| Related Tasks | S015, B014, B015, F020 |

#### Rules

| Rule | Meaning |
|------|---------|
| Create eligibility | terminal 创建前置准入只看 `device_online=true` 且 `active_terminals < max_terminals` |
| Execution failure | Agent/PTY 启动失败属于创建执行失败，不属于前置准入条件本身 |
| Server-authoritative limit | `max_terminals` 由服务端内部配置维护，普通 runtime API 不接受客户端修改 |
| Closed cleanup | `terminal_status=closed` 后不再维持活动连接记录，也不再参与活动 terminal 数和视图数统计 |

### 桌面端首个 terminal 的 Agent 恢复前置

| 字段 | 值 |
|------|----|
| ID | CONTRACT-018 |
| Scope | Desktop Client + Local Agent |
| Related Tasks | S015, B015, F020 |

#### Rules

| Rule | Meaning |
|------|---------|
| Desktop bootstrap | 桌面端在本机 Agent 离线且当前 terminal 数为 0 时，创建首个 terminal 前应先尝试恢复或启动本机 Agent |
| Recheck snapshot | Agent 恢复后必须重新查询后端快照，再继续 create_terminal |
| Fallback message | 若 Agent 恢复失败，客户端展示“当前电脑不可创建或承载 terminal，请先启动或重连本机 Agent” |

### Terminal Workspace 顶部状态栏与菜单主路径

| 字段 | 值 |
|------|----|
| ID | CONTRACT-019 |
| Scope | Client-side |
| Related Tasks | S016, F021, F022 |

#### Rules

| Rule | Meaning |
|------|---------|
| Slim header | 顶部只保留电脑在线/离线状态图标、当前 terminal 标题和菜单入口 |
| Menu-owned terminal actions | `新建终端 / 切换终端 / 重命名当前终端 / 关闭当前终端` 通过顶部菜单或面板完成 |
| Content first | 终端内容区优先，不再长期显示整排 tabs 占用垂直空间 |
| Snapshot authoritative | 菜单内 terminal 列表与可创建状态仍以后端快照为准 |

### 设备离线后的 terminal 收口语义

| 字段 | 值 |
|------|----|
| ID | CONTRACT-020 |
| Scope | Server + Agent + Client |
| Related Tasks | S017, B016, B017, F023 |

#### Rules

| Rule | Meaning |
|------|---------|
| Device offline terminal invalidation | 当 `device_online=false` 时，该 device 下的 terminal 不再被视为可运行 terminal |
| Offline close/unavailable convergence | 设备离线后，terminal 必须统一收口为 `closed` 或等价的不可用终态，不能继续以 `attached/detached` 活动态暴露给客户端 |
| No active traces after close | 终端进入 `closed` 或不可用终态后，不再维持活动 ws 连接记录、视图数与活动 terminal 名额 |
| Create gate unchanged | 创建 terminal 的前置准入仍只看 `device_online=true` 且 `active_terminals < max_terminals` |
| Client snapshot filtering | 客户端以后端快照为准，不再在离线时把旧 terminal 视为可连接或可切换的活动 terminal |

### 桌面端 Agent 后台模式与退出语义

| 字段 | 值 |
|------|----|
| ID | CONTRACT-021 |
| Scope | Desktop Client + Local Agent + Server |
| Related Tasks | S018, B018, F024, F025 |

#### Rules

| Rule | Meaning |
|------|---------|
| Desktop-as-console | 桌面端是本机 Agent 控制台，不再只是普通 remote client 视图 |
| Background toggle | 桌面端本地配置提供“退出桌面端后是否保持 Agent 后台运行”的开关 |
| Ownership safe stop | 桌面端退出时，只有在“Agent 由桌面端当前实例拉起”且“后台运行开关关闭”时，才主动停止 Agent |
| External agent preserved | 如果本机 Agent 原本已由外部方式启动，桌面端退出不能误杀该 Agent |
| Graceful desktop exit | 当桌面端决定停止 Agent 时，应优先走优雅下线，缩短手机端看到假在线的时间窗口 |
| Online source unchanged | `电脑在线` 仍然只由服务端感知到的本机 Agent 在线决定，不由桌面 UI 是否打开决定 |

### 桌面 Agent 管理子系统与工作台状态机

| 字段 | 值 |
|------|----|
| ID | CONTRACT-022 |
| Scope | Desktop Client |
| Related Tasks | S019, B019, F026, F027 |

#### Rules

| Rule | Meaning |
|------|---------|
| Agent manager owns lifecycle | 桌面端不得由页面直接决定 Agent 发现、启动、停止与所有权；这些动作必须由独立 `DesktopAgentManager` 统一提供 |
| Workspace state single source | `DesktopWorkspaceController` 必须把 Agent 状态、设备快照、terminal 快照和创建中状态收敛为单一 `WorkspaceState`，页面只读该状态 |
| Stable agent discovery | Agent 发现顺序必须正式化：显式配置路径 / 环境变量 / 固定可发现路径；不得继续把 `Directory.current` 作为主要发现来源 |
| First terminal two-stage flow | `启动本机 Agent` 与 `创建第一个 terminal` 在实现上是两个顺序阶段，可在 UI 上合成为一个动作，但 controller 内部必须先确保 Agent Ready 再 create |
| Desktop-specific empty state | 桌面端 `无可用 terminal + Agent 离线` 时进入 `bootstrappingAgent / readyToCreateFirstTerminal / createFailed` 本机三态，不得退化为移动端远程离线页 |
| External agent preserved | 工作台状态机不得通过 UI 临时状态推断 Agent 所有权；是否可停止 Agent 只由 `DesktopAgentManager` 的托管关系决定 |

### 桌面工作台空状态归一化

| 字段 | 值 |
|------|----|
| ID | CONTRACT-023 |
| Scope | Desktop Client |
| Related Tasks | S020, F028 |

#### Rules

| Rule | Meaning |
|------|---------|
| Failed bootstrap is attempt-scoped | `createFailed` 只能表示当前或最近一次明确 bootstrap 尝试失败，不能作为长期持久状态挂在空工作台上 |
| Normalize after last terminal closed | 当最后一个可用 terminal 被关闭后，工作台必须基于 `AgentState + usableTerminalCount` 重新归一化状态 |
| Empty workspace recovery | 归一化后的空工作台只能进入 `readyToCreateFirstTerminal / bootstrappingAgent / createFailed` 之一 |
| No stale failure carry-over | 历史失败页不得阻止用户重新进入”创建第一个 terminal”路径 |

### Agent 本地 HTTP Supervisor

| 字段 | 值 |
|------|----|
| ID | CONTRACT-024 |
| Scope | Local Agent + Desktop Client |
| Related Tasks | S021, B020, F029, B095, F089 |

#### HTTP Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | 健康检查，返回 `{\"status\": \"ok\"}` |
| GET | /status | 获取 Agent 状态 |
| POST | /stop | 优雅停止 Agent |
| POST | /config | 更新配置（如 keep_running_in_background） |
| GET | /terminals | 获取本地终端列表 |
| GET | /skills | 列出所有已发现 Skill 及启用状态（R043/B095） |
| POST | /skills/toggle | 切换 Skill 启用/禁用（R043/B095） |
| GET | /knowledge | 列出所有知识文件及启用状态（R043/B095） |
| POST | /knowledge/toggle | 切换知识文件启用/禁用（R043/B095） |

#### Port Allocation

| Rule | Value |
|------|-------|
| Default port | 18765 |
| Port range | 18765 - 18769 (5 个候选端口) |
| Bind address | 127.0.0.1 only |

#### State File

| Platform | Path |
|----------|------|
| macOS | `~/Library/Application Support/remote-control/agent-state.json` |
| Linux | `~/.local/share/remote-control/agent-state.json` |
| Windows | `%APPDATA%/remote-control/agent-state.json` |

#### State File Schema

```json
{
  “pid”: 12345,
  “port”: 18765,
  “server_url”: “wss://api.example.com”,
  “device_id”: “dev-xxx”,
  “started_at”: “2026-03-30T10:00:00Z”,
  “keep_running”: true,
  “terminals”: [
    {“id”: “term-1”, “title”: “Build”, “status”: “running”}
  ]
}
```

#### Rules

| Rule | Meaning |
|------|---------|
| HTTP for control only | 本地 HTTP Server 只用于控制面（启动/停止/状态查询/配置），不传输终端数据 |
| Terminal data via server | 终端 I/O 数据仍然通过 WebSocket 连接到远程 Server 中转 |
| Port discovery via file | Flutter UI 优先通过状态文件获取端口，文件不可用时扫描端口范围 |
| Orphan process detection | 通过 PID 检查进程是否存在，处理孤儿状态文件 |

### Server 端 Agent 状态 TTL 机制

| 字段 | 值 |
|------|----|
| ID | CONTRACT-025 |
| Scope | Server |
| Related Tasks | S021, B021 |

#### TTL Configuration

| Parameter | Value | Description |
|-----------|-------|-------------|
| DEVICE_ONLINE_TTL | 90 秒 | 设备在线状态 TTL |
| STALE_GRACE_PERIOD | 30 秒 | stale 状态宽限期 |

#### State Transitions

```
connected → online (TTL 刷新)
online + heartbeat → online (TTL 刷新)
WebSocket 断开 → stale (保留 TTL)
stale + TTL 过期 → offline
stale + 重连 → online (TTL 刷新)
```

#### Rules

| Rule | Meaning |
|------|---------|
| No immediate cleanup | WebSocket 断开时不立即调用 `_cleanup_agent`，而是标记 stale |
| Heartbeat refreshes TTL | Agent 心跳（ping/pong）刷新设备状态 TTL |
| Graceful reconnection | Agent 重连时，如果仍在 TTL 内，可以直接恢复，无需重新注册 |
| Stale → offline | TTL 过期后，设备状态自动变为 offline，terminal 收口为 closed |

### 桌面端与手机端行为差异

| 字段 | 值 |
|------|----|
| ID | CONTRACT-026 |
| Scope | Desktop + Mobile Client |
| Related Tasks | S021, F030 |

#### Behavior Differences

| Feature | Desktop | Mobile |
|---------|---------|--------|
| Agent 位置 | 本地进程 | 远程设备 |
| 后台运行开关 | 有 | 无 |
| Agent 生命周期管理 | 有（启动/停止/检测） | 无 |
| 本地 HTTP 通信 | 有 | 无 |
| 退出时行为 | 根据开关决定是否停止 Agent | 只是断开 WebSocket |
| “电脑在线”含义 | 本机 Agent 在线 | 远程设备 Agent 在线 |

#### Rules

| Rule | Meaning |
|------|---------|
| Platform detection | 通过 `Platform.isMacOS/isLinux/isWindows` 判断是否为桌面端 |
| Conditional features | 后台运行开关、Agent 管理入口仅在桌面端显示 |
| Shared terminal view | 终端视图组件（xterm）在双端共享，但生命周期管理逻辑不同 |
| Exit semantics | 桌面端退出需考虑 Agent 状态，手机端退出只是断开连接 |

---

## Agent 生命周期管理

### Agent 生命周期统一管理

| 字段 | 值 |
|------|----|
| ID | CONTRACT-027 |
| Scope | Desktop Client |
| Related Tasks | S024, F032-F044 |

#### DesktopAgentManager 接口（extends ChangeNotifier）

```dart
class DesktopAgentManager extends ChangeNotifier {
  /// 登录成功后启动 Agent（原子操作：sync + ensure 不可分割）
  Future<void> onLogin({
    required String serverUrl,
    required String token,
    required String deviceId,
    required String username,
  });

  /// 登出前关闭 Agent，清除凭证和 ownership
  Future<void> onLogout();

  /// App 启动时恢复 Agent（检查 ownership 匹配，复用或重启）
  Future<void> onAppStart({
    required String serverUrl,
    required String token,
    required String username,
    required String deviceId,
  });

  /// App 关闭时根据配置决定是否停止 Agent
  Future<void> onAppClose();

  // --- 公开方法（WorkspaceController 使用）---
  Future<DesktopAgentState> loadState();
  Future<DesktopAgentState> startAgent({required String serverUrl, required String token, required String deviceId, Duration timeout});
}
```

#### DesktopAgentState 枚举

```dart
enum DesktopAgentStateKind {
  unsupported,     // 移动端，不支持
  unconfigured,    // 初始状态
  offline,         // Agent 未运行
  starting,        // 启动中
  managedOnline,   // 本 App 启动并管理
  externalOnline,  // 外部启动的 Agent 在线
  startFailed,     // 启动失败
}
```

#### AgentOwnershipInfo 结构

```dart
class AgentOwnershipInfo {
  final String serverUrl;
  final String username;
  final String deviceId;

  factory AgentOwnershipInfo.fromJson(Map<String, dynamic> json);
  Map<String, dynamic> toJson();
  bool matches(AgentOwnershipInfo other);
}
```

#### 生命周期场景

| 场景 | 触发条件 | Agent 行为 |
|------|----------|------------|
| 登录成功 | 用户完成登录 | 桌面端 syncAndEnsureOnline（原子），移动端 unsupported |
| 退出登录 | 用户点击登出 | 始终关闭 Agent，清除凭证和 ownership |
| App 启动 | 检测到已登录 + ownership 匹配 + Agent 在线 | 复用现有 Agent |
| App 启动 | 检测到已登录 + Agent 不在线 | syncAndEnsureOnline 启动新 Agent |
| 关闭 App | keepAgentRunningInBackground=true | Agent 继续运行 |
| 关闭 App | keepAgentRunningInBackground=false | 关闭 Agent |

#### 不变量

- DesktopAgentManager 是 Agent 生命周期的唯一管理入口
- syncAndEnsureOnline 保证配置同步和进程启动不可分割
- onLogout 使用内部存储的凭证（非空字符串），确保能正确停止 Agent

#### Rules

| Rule | Meaning |
|------|---------|
| Desktop only | Agent 生命周期管理仅适用于桌面端，移动端直接返回 |
| Logout always stops | 退出登录时始终关闭 Agent，因为 token 已失效 |
| Ownership before reuse | 复用 Agent 前必须验证所有权，非当前用户的 Agent 需关闭重建 |
| Timeout handling | Agent 启动/关闭超时后应强制终止进程 |
| State persistence | Agent 所有权信息应持久化到配置文件 |

#### 状态持久化位置

```
macOS:  ~/Library/Application Support/remote-control/agent-ownership.json
Linux:  ~/.local/share/remote-control/agent-ownership.json
Windows: %APPDATA%/remote-control/agent-ownership.json
```

### 同端设备在线数限制

| 字段 | 值 |
|------|----|
| ID | CONTRACT-030 |
| Scope | Server ↔ Client |
| Related Tasks | B036, B042, F050 |
| Status | **Simplified** — 冲突弹窗已移除，改为新设备直接替换旧设备 |

#### 同端设备在线限制

新 Client 通过 `/ws/client` 连接时，Server 检查该 session 下是否已有同 `view_type` 的 Client 连接。如已有，直接发送 `device_kicked` 并 close 旧连接(4011)，无需用户确认。

#### WS 消息

**device_kicked（Server → 旧 Client）**

```json
{
  "type": "device_kicked",
  "reason": "replaced_by_new_device",
  "timestamp": "2026-04-09T11:00:00Z"
}
```

#### WS Close Codes

| Code | 含义 | 接收方 |
|------|------|--------|
| 4011 | 被新设备替换 | 旧 Client |

#### 踢出规则

| 场景 | 结果 |
|------|------|
| 新设备连接 + 旧设备在线 | 发送 device_kicked → close(4011) → 新设备正常连接 |
| 旧设备已断开 | 新设备正常连接（send/close 异常被吞掉） |
| 跨端（mobile + desktop）| 不触发踢出检查 |

以上检查和 Future 创建必须原子化（无 await 插入），防止两个新 Client 同时通过检查。

### 登录层 Token 版本与同端设备限制

| 字段 | 值 |
|------|----|
| ID | CONTRACT-028 |
| Scope | Server ↔ Client |
| Related Tasks | B038, B039, F048, F049, S025 |

#### 核心机制

Redis `token_version:{session_id}:{view_type}` 记录当前版本号。登录时 INCR → 新 JWT 携带版本 → verify_token 校验版本。版本不匹配 → 旧设备 token 失效。

#### JWT Claims 变更

```json
{
  "sub": "session_id",
  "token_version": 2,
  "view_type": "mobile",
  "exp": 1745000000,
  "iat": 1744000000
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| token_version | int | 登录时递增的版本号，verify_token 与 Redis 比对 |
| view_type | string | "mobile" 或 "desktop"，用于定位 Redis key |

#### API 变更

**POST /api/login**

```json
// Request（在 CONTRACT-004 基础上新增 view）
{
  "username": "user1",
  "password": "pass123",
  "view": "mobile"
}

// Response 200（LoginResponse 含 username 字段，参见 CONTRACT-004）
{
  "success": true,
  "message": "登录成功",
  "username": "user1",
  "session_id": "gDgDSu1f1oqnAVeP",
  "token": "jwt",
  "expires_at": "2026-04-16T00:00:00Z",
  "refresh_token": "jwt",
  "refresh_expires_at": "2026-05-09T00:00:00Z"
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| view | 否 | "mobile"(默认) 或 "desktop"。非法/未知值按 mobile 处理 |

> 注：B056 新增 `username` 字段到 LoginResponse，login 和 register 响应均携带。CONTRACT-004 已更新为当前结构。

**POST /api/register** — 同样支持 view 参数。响应结构与 login 基本一致（含 username 字段），但不含 refresh_token / refresh_expires_at（注册不生成 refresh token）：

```json
// Request
{
  "username": "newuser",
  "password": "test123456",
  "view": "mobile"
}

// Response 200
{
  "success": true,
  "message": "注册成功",
  "username": "newuser",
  "session_id": "gDgDSu1f1oqnAVeP",
  "token": "jwt",
  "expires_at": "2026-04-13T16:45:00Z"
}
```

**POST /api/refresh** — 不递增 token_version，使用 Redis 当前版本写入新 token

#### 401 结构化错误码（仅适用于 token 校验类 401）

> **适用范围**：仅在 `verify_token` 校验 token 时生效。登录接口 `/api/login` 的凭证错误 401 不含 error_code，仍沿用现有 `{detail: "用户名或密码错误"}` 格式。

受保护接口中 token 校验失败时，401 响应包含 `error_code` 字段，客户端按 error_code 分支：

| error_code | 含义 | detail（参考文案） | 客户端行为 |
|------------|------|-------------------|-----------|
| TOKEN_REPLACED | 被其他设备登录替换 | Token 已在其他设备登录 | 显示「您已在其他设备登录」→ 跳转登录页 |
| TOKEN_EXPIRED | JWT 自然过期 | Token 已过期 | 显示「登录已过期」→ 跳转登录页 |
| TOKEN_INVALID | JWT 签名/格式无效 | Token 无效 | 显示「登录已过期」→ 跳转登录页 |

```json
// 被踢示例
{
  "detail": "Token 已在其他设备登录",
  "error_code": "TOKEN_REPLACED"
}

// 过期示例
{
  "detail": "Token 已过期",
  "error_code": "TOKEN_EXPIRED"
}
```

#### Redis Key 设计

| Key | 类型 | 说明 |
|-----|------|------|
| `token_version:{session_id}:mobile` | int | 移动端当前版本号 |
| `token_version:{session_id}:desktop` | int | 桌面端当前版本号 |

#### Fail-Closed 策略

| 场景 | 行为 |
|------|------|
| Redis INCR 失败（登录/注册） | 返回 503 Service Unavailable，不签发 token |
| Redis GET 失败（verify_token） | 返回 503，不区分有无 token_version（fail-closed） |
| Redis GET 失败（refresh） | 返回 503，不签发新 token |

#### Token 版本校验（B062 加固后）

| 场景 | 行为 |
|------|------|
| 无 token_version 的旧 access token | 返回 401 TOKEN_INVALID（不再兼容放行） |
| token_version 与 Redis 匹配 | 正常通过 |
| token_version 与 Redis 不匹配 | 返回 401 TOKEN_REPLACED |
| 旧 refresh token（无 view_type） | 刷新时按 mobile 处理，新 token 使用 Redis 当前 mobile 版本 |
| Server 重启（Redis 数据丢失） | token_version 从 0 开始，旧 token 的 token_version 字段不存在或为旧值 → 按 TOKEN_REPLACED 处理（安全侧） |

---

## 安全加固

### WS 鉴权消息协议

| 字段 | 值 |
|------|----|
| ID | CONTRACT-031 |
| Scope | Server + Agent + Client |
| Related Tasks | B062, B065, B068, F058 |

#### WS Auth 消息格式

连接建立后，客户端/Agent 必须在 5 秒内发送首条 auth 消息：

```json
{
  "type": "auth",
  "token": "jwt_access_token"
}
```

#### WS Auth Close Codes

| Code | 含义 |
|------|------|
| 4001 | token 无效（签名错误、格式错误） |
| 4002 | 超时未发送 auth 消息（5 秒） |
| 4003 | 消息大小超过限制 |
| 4004 | auth 消息格式错误 / 期望 auth 消息 |

#### Rules

| Rule | Meaning |
|------|---------|
| First message auth | 连接后首条消息必须是 auth，否则关闭连接 |
| No URL query token | token 不允许通过 URL query 参数传递（architecture.md 不变量 #17） |
| 5s timeout | 5 秒内未收到有效 auth → close(4002) |
| MAX_WS_MESSAGE_SIZE | 默认 1MB，可通过环境变量配置 |

### 认证与密码策略

| 字段 | 值 |
|------|----|
| ID | CONTRACT-032 |
| Scope | Server |
| Related Tasks | B062, B063, B066 |

#### JWT Secret 约束

| Rule | Meaning |
|------|---------|
| JWT_SECRET 必填 | 环境变量缺失 → 服务启动失败（raise），不允许随机回退 |
| token_version 必填 | 无 token_version 的 JWT → 401 TOKEN_INVALID |
| 错误脱敏 | JWT 验证错误统一返回 "Token 无效" 或 "Token 已过期"，不暴露解码异常详情 |

#### 密码策略

| Rule | Meaning |
|------|---------|
| bcrypt for new | 新注册用户使用 bcrypt 哈希 |
| Auto-migrate | 旧 SHA-256 哈希登录成功后自动迁移为 bcrypt |
| 日志归属 | log_api 使用 get_current_user_id，查询非自己 session → 403 |

### CORS + 速率限制

| 字段 | 值 |
|------|----|
| ID | CONTRACT-033 |
| Scope | Server |
| Related Tasks | B064, B067 |

#### CORS 约束

| Rule | Meaning |
|------|---------|
| CORS_ORIGINS 必填 | 未设置 → allow_origins=[]，阻止所有跨域 |
| 禁止通配符 | 不允许 CORS_ORIGINS=* |
| 逗号分隔 | 多域名通过逗号分隔配置 |

#### 速率限制

| Rule | Meaning |
|------|---------|
| IP based | 基于 IP 的每分钟请求计数 |
| Default 10/min | 默认每 IP 每分钟 10 次登录/注册请求 |
| 429 + Retry-After | 超限返回 429 + Retry-After 头 |
| Fail-open | 限流计数 Redis 操作失败时不额外拦截（仅限流 fail-open）；认证/session Redis 失败仍返回 503 |

### Redis 密码 + Docker 非 root

| 字段 | 值 |
|------|----|
| ID | CONTRACT-034 |
| Scope | Docker 部署 |
| Related Tasks | B070 |

#### Rules

| Rule | Meaning |
|------|---------|
| REDIS_PASSWORD 必填 | Redis 启动使用 --requirepass |
| Server 密码连接 | Server 连接 Redis 时传入密码 |
| Docker 非 root | server/agent 容器以 appuser 非 root 运行 |
| Volume 权限 | 非 root 用户可写入 /data/ 目录 |

### Agent 本地 HTTP 认证

| 字段 | 值 |
|------|----|
| ID | CONTRACT-035 |
| Scope | Local Agent |
| Related Tasks | B068 |

#### Rules

| Rule | Meaning |
|------|---------|
| Token auth | 所有本地 HTTP 端点需要 Bearer token |
| Auto-generate | token 在 Agent 启动时自动生成 |
| Config file | token 写入配置文件，外部进程需读取配置获取 |
| Input validation | terminal 创建前校验 command（非空字符串）、cwd（绝对路径或 None）、env（值为字符串） |

### Client 安全存储

| 字段 | 值 |
|------|----|
| ID | CONTRACT-036 |
| Scope | Client |
| Related Tasks | F058 |

#### Rules

| Rule | Meaning |
|------|---------|
| flutter_secure_storage | 密码、access_token、refresh_token 使用 flutter_secure_storage |
| SharedPreferences only | 用户名、login_time 可保留在 SharedPreferences |
| Auto-migrate | 首次启动时从 SharedPreferences 迁移密码到 flutter_secure_storage + 清除旧值 |

### RSA+AES 加密登录/注册

| 字段 | 值 |
|------|----|
| ID | CONTRACT-037 |
| Scope | Client, Agent, Server |
| Related Tasks | S063, S064 |

#### Protocol

```
Client/Agent                         Server
    |                                    |
    |  GET /api/public-key               |
    |  ← {public_key_pem}                |
    |                                    |
    |  本地存储公钥 PEM (TOFU)            |
    |  后续连接比对公钥，变更则拒绝(ws://) |
    |                                    |
    |  本地生成 AES-256 密钥 (32 bytes)   |
    |  RSA-OAEP-SHA256 加密 AES 密钥      |
    |                                    |
    |  POST /api/login (或 /api/register) |
    |  ws://: {username, password_encrypted}  (RSA-OAEP-SHA256 加密密码)
    |  wss://: {username, password}          (TLS 保护，明文密码)
    |  ← {token, session_id, ...}         |
```

#### Rules

| Rule | Meaning |
|------|---------|
| 公钥端点 | GET /api/public-key 返回 PEM（含模数、指数）；ws:// 必须获取成功才允许登录，wss:// 获取失败可回退明文（不变量 #29） |
| TOFU | Agent/Client 首次存储公钥 PEM，后续比对完整公钥，变更则拒绝连接（ws:// 强制，wss:// 依赖 TLS 证书验证） |
| 密码加密 | ws://: password_encrypted = RSA-OAEP-SHA256(public_key, password_utf8) → base64；wss://: 明文 password（TLS 保护） |
| AES 密钥交换 | WebSocket auth 消息携带 encrypted_aes_key = RSA-OAEP-SHA256(public_key, aes_key) → base64 |
| 加密判断 | ws:// 必须加密（不变量 #27），wss:// 不加密（TLS 已保护，不变量 #29） |

### WebSocket AES 加解密

| 字段 | 值 |
|------|----|
| ID | CONTRACT-038 |
| Scope | Client, Agent, Server |
| Related Tasks | S063, S064 |

#### Protocol

```
Agent/Client                         Server
    |                                    |
    |  WS auth: {type:"auth", token,     |
    |   encrypted_aes_key: "base64..."}  |
    |  ← {type:"connected", ...}         |
    |                                    |
    |  后续消息:                          |
    |  {encrypted:true, iv:"base64",     |
    |   data:"base64"}                   |
    |  ← 解密 → 处理 → 加密 → 返回        |
```

#### Rules

| Rule | Meaning |
|------|---------|
| 加密算法 | AES-256-GCM（12 字节 IV，每次随机） |
| 明文消息 | auth（含 JWT token，AES 密钥交换前无法加密）、connected、ping、pong 不加密。auth 中的 encrypted_aes_key 由 RSA-OAEP 保护 |
| 加密消息 | data, resize, create_terminal 等业务消息必须加密 |
| 密钥绑定 | AES 密钥绑定 session，WS 断开时销毁（clear_aes_key） |
| 加密失败 | 加密失败时断开连接（Agent/Client 侧），解密失败静默丢弃并记录日志（Server 侧）。不得降级为明文发送（禁止模式 #105） |
| 双向加密 | Server→Agent/Client 和 Agent/Client→Server 均使用同一 AES 密钥 |

### 终端恢复状态机与生命周期语义

| 字段 | 值 |
|------|----|
| ID | CONTRACT-039 |
| Scope | Client, Desktop, Server, Agent |
| Related Tasks | S071, S072, F072, F076 |

#### States

```text
terminal lifecycle:
inactive -> connecting -> recovering -> live
live -> reconnecting -> recovering -> live
live -> switched_away (inactive local cache only)
live -> detached_recoverable -> closed
```

#### Rules

| Rule | Meaning |
|------|---------|
| switch != reconnect | terminal 切换只影响 UI 与 active binding，不自动创建恢复会话 |
| reconnect != recover | transport 重连成功后，仍需显式 recover 才能进入 live |
| local cache scope | local renderer cache 只用于单端 continuity，不作为跨端恢复真相 |
| exclusive/shared mode | terminal 必须显式或默认落在 `exclusive` / `shared` 模式之一；Codex 默认 exclusive，Claude/shell 默认 shared |
| lifecycle recovery | foreground resume、cold start、network restore 三类场景都必须走统一恢复状态机，而不是页面层临时兜底 |

### Server terminal metadata / ownership / lifecycle truth

| 字段 | 值 |
|------|----|
| ID | CONTRACT-040 |
| Scope | Server |
| Related Tasks | B071, F075 |

#### Terminal Metadata

```json
{
  "terminal_id": "term_123",
  "status": "live|detached_recoverable|recovering|closed",
  "views": {"mobile": 1, "desktop": 0},
  "pty": {"rows": 40, "cols": 120},
  "geometry_owner_view": "desktop",
  "attach_epoch": 12,
  "recovery_epoch": 7
}
```

#### Session / Device State

```json
{
  "agent_online": true,
  "device_state": "online|offline_recoverable|offline_expired"
}
```

#### Rules

| Rule | Meaning |
|------|---------|
| server truth | Server 维护 metadata / ownership / routing / epoch 真相，不维护 terminal 内容真相 |
| recoverable offline | agent 断开后先进入 `offline_recoverable`，TTL 超时后才进入 `offline_expired` |
| terminal recoverable | agent 断开后 terminal 先进入 `detached_recoverable`，不立刻 closed |
| owner enforcement | 只有 geometry owner 对应视图可以发全局 resize |
| cleanup | cleanup 路径不得再次隐式推导 attached/detached，必须依据显式字段 |

### Agent terminal snapshot authority

| 字段 | 值 |
|------|----|
| ID | CONTRACT-041 |
| Scope | Agent |
| Related Tasks | B072, F075 |

#### Snapshot Semantics

```json
{
  "terminal_id": "term_123",
  "attach_epoch": 12,
  "recovery_epoch": 7,
  "pty": {"rows": 40, "cols": 120},
  "active_buffer": "main|alt",
  "payload": "..."
}
```

#### Rules

| Rule | Meaning |
|------|---------|
| authoritative recovery source | Agent 是 terminal 内容恢复主权威源 |
| per-terminal isolation | 每个 terminal 独立 snapshot 生命周期，close/recreate 不得污染彼此 |
| no dual primary | Server output history 只能做诊断或极端降级兜底，不能与 Agent snapshot 双主并存 |
| buffer semantics | snapshot 至少要能恢复 terminal 当前可见状态，短期允许输出回放包，长期演进到 screen state + diff |

### Terminal recovery WebSocket protocol

| 字段 | 值 |
|------|----|
| ID | CONTRACT-042 |
| Scope | Client, Server, Agent |
| Related Tasks | S072, S073, B071, B072, B073, F071, F072, F075, F076 |

#### Connected

```json
{
  "type": "connected",
  "terminal_id": "term_123",
  "view_id": "desktop",
  "pty": {"rows": 40, "cols": 120},
  "geometry_owner_view": "desktop",
  "attach_epoch": 12,
  "recovery_epoch": 7
}
```

#### Recovery Boundary

```json
{"type": "snapshot_start", "terminal_id": "term_123", "attach_epoch": 12, "recovery_epoch": 7}
{"type": "snapshot_chunk", "terminal_id": "term_123", "attach_epoch": 12, "recovery_epoch": 7, "payload": "..."}
{"type": "snapshot_complete", "terminal_id": "term_123", "attach_epoch": 12, "recovery_epoch": 7}
```

#### Live Output

```json
{
  "type": "output",
  "terminal_id": "term_123",
  "attach_epoch": 12,
  "payload": "..."
}
```

#### Rules

| Rule | Meaning |
|------|---------|
| connected != recovered | `connected` 只表示 transport ready，不表示 terminal 已恢复完成 |
| buffering before complete | `snapshot_complete` 前 live output 只允许缓冲，不允许直接写 renderer |
| epoch drop | 旧 `attach_epoch` / `recovery_epoch` 的 snapshot/output/resize 必须被丢弃 |
| compatibility window | 迁移期允许 server 做双协议兼容，但必须有明确灰度与回退策略 |
| cold start | 冷启动恢复必须依赖权威 snapshot，而不是旧 local cache |

## 智能终端进入

### 智能终端创建编排

| 字段 | 值 |
|------|----|
| ID | CONTRACT-043 |
| Scope | Client orchestration |
| Related Tasks | S077, F077, F078, F079, F080, F081 |

#### CommandSequence

```json
{
  "summary": "进入 remote-control 并启动 Claude Code",
  "provider": "service_llm",
  "source": "intent",
  "need_confirm": true,
  "steps": [
    {
      "id": "step_1",
      "label": "确认当前目录",
      "command": "pwd"
    },
    {
      "id": "step_2",
      "label": "查找项目目录",
      "command": "find ~/project -maxdepth 4 -type d -name remote-control 2>/dev/null | head -n 1"
    },
    {
      "id": "step_3",
      "label": "进入项目目录",
      "command": "cd /Users/demo/project/remote-control"
    },
    {
      "id": "step_4",
      "label": "启动 Claude Code",
      "command": "claude"
    }
  ]
}
```

#### Fields

| Field | Meaning |
|-------|---------|
| `summary` | 对即将执行动作的用户可读摘要 |
| `provider` | 生成该序列的 planner：`service_llm` / `claude_cli` / `local_rules` |
| `source` | 生成来源：`intent` / `suggested_prompt` / `manual_edit` |
| `need_confirm` | 是否需要在执行前显式确认；当前 AI 生成序列一律为 `true` |
| `steps[]` | 顺序执行的命令步骤 |

#### CommandStep

```json
{
  "id": "step_2",
  "label": "查找项目目录",
  "command": "find ~/project -maxdepth 4 -type d -name remote-control 2>/dev/null | head -n 1"
}
```

| Field | Meaning |
|-------|---------|
| `id` | 稳定步骤标识，供编辑和回放使用 |
| `label` | 面向用户的步骤说明 |
| `command` | 单条 shell 命令，不包含隐藏副作用 |

#### ManualFallbackDraft

```json
{
  "title": "Claude / My Mac",
  "shell": "/bin/zsh",
  "commands": [
    "cd /Users/demo/project/remote-control",
    "claude"
  ]
}
```

`ManualFallbackDraft` 用于高级配置兜底。用户可以直接修改标题、shell 和命令步骤；一旦用户编辑，最终执行必须以用户编辑后的结果为准。

#### Rules

| Rule | Meaning |
|------|---------|
| client executes, server may plan | terminal 创建与命令执行闭环由 Client 协调；规划结果可以来自服务端 planner 或本地 fallback |
| claude only product surface | 产品主路径只展示 Claude 模式，不在 UI 层暴露多工具选择 |
| command sequence only | AI 输出统一为 `CommandSequence`，不再使用 `TerminalLaunchPlan` 作为主契约 |
| confirm before execute | 所有 AI 生成序列都必须先展示给用户确认，再执行 |
| editable fallback required | 任意 planner 结果都必须可回退到手动编辑命令步骤 |
| one create path | runtime selection 与 workspace 两条路径最终必须收口到同一个 create + execute 主链路 |
| explainable output | provider、summary、steps 必须对用户可见，不允许黑盒执行 |

### 命令规划 provider 隔离与执行语义

| 字段 | 值 |
|------|----|
| ID | CONTRACT-044 |
| Scope | Planner abstraction + terminal execution |
| Related Tasks | S078, B074, F086, F082, F083, F084, F085 |

#### CommandPlannerRequest

```json
{
  "device_id": "dev_123",
  "intent": "进入 remote-control 项目修改登录问题",
  "recent_terminals": [
    {
      "cwd": "/Users/demo/project/remote-control",
      "title": "Claude / remote-control"
    }
  ],
  "default_shell": "/bin/zsh"
}
```

#### PlannerResult

```json
{
  "provider": "service_llm",
  "fallback_used": false,
  "sequence": {
    "summary": "进入 remote-control 并启动 Claude Code",
    "provider": "service_llm",
    "source": "intent",
    "need_confirm": true,
    "steps": [
      {
        "id": "step_1",
        "label": "确认当前目录",
        "command": "pwd"
      },
      {
        "id": "step_2",
        "label": "进入项目目录",
        "command": "cd /Users/demo/project/remote-control"
      },
      {
        "id": "step_3",
        "label": "启动 Claude Code",
        "command": "claude"
      }
    ]
  }
}
```

#### Planner Provider

| Provider | Meaning |
|----------|---------|
| `service_llm` | 通过服务端受控 LLM planner 生成命令序列，带结构化 trace、限流和 timeout 防护 |
| `claude_cli` | 通过隔离的 `ClaudeCliCommandPlanner` 调用 `claude -p` 生成命令序列 |
| `local_rules` | 通过本地规则模板与 recent terminal 上下文生成命令序列 |

#### Execution Semantics

| Rule | Meaning |
|------|---------|
| same shell session | 所有步骤必须在同一个 terminal shell session 中执行，保证 `cd` 等上下文对后续步骤生效 |
| sequential execution | 按 `steps[]` 顺序执行，不允许乱序或并发注入 |
| fail fast | 任一步失败时停止后续步骤，并向用户展示失败输出 |
| visible output | 执行过程中命令与输出对用户可见，不允许隐藏执行 |
| guarded payload allowed | 执行层可以把步骤编译成受控 shell payload，但用户预览的仍然是原始步骤列表 |

#### PlannerCoordinator Rules

| Rule | Meaning |
|------|---------|
| provider isolated | UI 只能依赖 `CommandPlanner` / `PlannerCoordinator`，不得直接调用 `claude -p` |
| current device facts only | planner 输入只能使用当前设备事实、recent terminal 上下文和用户输入 |
| no path invention | provider 不得发明无法由当前设备事实或 shell 发现命令支撑的路径 |
| fallback required | `service_llm` 不可用/限流/超时/非法输出时先回退 `claude_cli`，再回退 `local_rules` |
| server creds first | 服务端 LLM provider 凭证优先保存在服务端；客户端只保存开发态 fallback 所需的本地配置 |
| server planning allowed | Server 可以做自然语言规划，但不得绕过当前设备事实约束；Agent 仍只负责 terminal 生命周期与执行承载 |

## ReAct 智能终端代理

### Agent SSE 事件流与 Token 统计

| 字段 | 值 |
|------|----|
| ID | CONTRACT-047 |
| Scope | Server Agent SSE → Client |
| Related Tasks | B078, B079, B080, F095_old, B083, F099, B094, F088, S088, B105, B106, F107, S110 |

#### SSE Event Types

| Event | Direction | Description |
|-------|-----------|-------------|
| `phase_change` | Server → Client | Agent 交互阶段切换（THINKING / EXPLORING / ANALYZING / RESPONDING / CONFIRMING / RESULT） |
| `streaming_text` | Server → Client | Agent 模型逐 token 文本回复（用户可见助手消息，非 chain-of-thought） |
| `tool_step` | Server → Client | Agent 工具调用步骤（含 tool_name / status / description / result_summary） |
| `question` | Server → Client | Agent 向用户提问（含选项） |
| `result` | Server → Client | Agent 最终结果（response_type 区分 command/message/ai_prompt + token 统计） |
| `error` | Server → Client | 错误/超时/取消事件 |

#### Streaming Text Event Schema

```json
{
  "event_type": "streaming_text",
  "text_delta": "我来帮你检查一下当前目录结构和项目情况..."
}
```

| Rule | Meaning |
|------|---------|
| User-facing only | 只包含模型主动对用户说的话，不含 chain-of-thought |
| Server-side filter | 服务端检测并截断可能的 CoT 标记（如"一步步思考"、"推理过程"），不纯依赖 SYSTEM_PROMPT |
| Presentation | 客户端渲染为对话过程气泡；与 message 类型 result（结构化结果卡片）区分展示 |
| Conversation persistence | conversation projection 可基于 streaming_text / tool_step / phase_change 重建当前轮展示状态 |
| Resume support | resume_stream 支持回放缓存的 streaming_text 事件 |
| Mobile sync | conversation stream 同步（mobile SSE）包含 streaming_text / tool_step |
| Compatibility | 旧 `assistant_message` / `trace` 事件只作兼容输入，当前 client 解析时稳定忽略且不 crash |

#### Result Event Schema

```json
{
  "response_type": "command",
  "summary": "进入 remote-control 并启动 Claude Code",
  "steps": [
    {"id": "step_1", "label": "确认当前目录", "command": "pwd"},
    {"id": "step_2", "label": "进入项目目录", "command": "cd ~/project/remote-control"}
  ],
  "provider": "agent",
  "source": "recommended",
  "need_confirm": true,
  "aliases": {"~/project/remote-control": "remote-control"},
  "ai_prompt": "",
  "usage": {
    "input_tokens": 1520,
    "output_tokens": 380,
    "total_tokens": 1900,
    "requests": 3,
    "model_name": "deepseek-chat"
  }
}
```

#### Usage Sub-object Fields

| Field | Type | Meaning |
|-------|------|---------|
| `input_tokens` | int | 输入 token 数（含 system prompt + tools + user input） |
| `output_tokens` | int | 输出 token 数（含 tool calls + final result） |
| `total_tokens` | int | 总 token 数 |
| `requests` | int | LLM API 请求次数 |
| `model_name` | string | 使用的模型名称 |

#### Backward Compatibility

| Rule | Meaning |
|------|---------|
| `usage` nullable | 旧 Server 不推送 `usage`，Client 解析时 `json['usage']` 为 null |
| graceful absence | `usage` 为 null 时 Client 不展示 token 统计 UI |
| AgentSession.result unchanged | `AgentSession.result` 保持 `AgentResult` 类型，usage 仅存在于 SSE payload |
| `response_type` nullable | 旧 Server 不推送 `response_type`，Client 解析时默认 `'command'`（向后兼容） |
| `ai_prompt` nullable | 旧 Server 不推送 `ai_prompt`，Client 解析时默认空字符串 |

#### response_type 语义

| response_type | summary | steps | ai_prompt | need_confirm | 渲染方式 |
|---------------|---------|-------|-----------|-------------|---------|
| `message` | 知识问答/使用建议全文 | `[]` | `""` | `false` | 结构化结果卡片（可折叠），无执行按钮；与 streaming_text 对话气泡区分 |
| `command` | 命令序列描述 | 含 shell 命令 | `""` | `true` | 命令卡片 + 确认执行（现有行为） |
| `ai_prompt` | prompt 用途说明 | `[]` | prompt 文本 | `true` | prompt 预览卡片 + 注入终端按钮 |

#### Rules

| Rule | Meaning |
|------|---------|
| SSE only | Token usage 仅通过 SSE result 事件推送，不持久化到 session 对象 |
| Model from config | `model_name` 取自 `planner_model()` 配置，不从 LLM 响应推断 |
| Error cumulative | Agent 运行异常（error/timeout/cancel）时 `usage` 返回已累积的 token 用量（来自 AgentDeps 逐轮回调累积），不再全 0；`model_name` 为实际使用的模型名称。只有从未调用 LLM 时才返回全 0 |
| No sensitive data | usage 不包含 prompt 内容、响应内容或任何用户数据 |

---

### CONTRACT-048: Agent Usage Summary API

| 字段 | 值 |
|------|---|
| ID | CONTRACT-048 |
| 关联任务 | B084, F100, B105, B106, S110 |
| 方法 | `GET /api/agent/usage/summary` |
| 认证 | `async_verify_token` 必需 |

#### Query Parameters

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| device_id | string | 是 | 当前设备 ID；API 同时返回该设备的汇总和用户级总汇总 |

#### Response 200

```json
{
  "device": {
    "total_sessions": 3,
    "total_input_tokens": 5230,
    "total_output_tokens": 1200,
    "total_tokens": 6430,
    "total_requests": 8,
    "latest_model_name": "deepseek-chat"
  },
  "user": {
    "total_sessions": 12,
    "total_input_tokens": 28450,
    "total_output_tokens": 8300,
    "total_tokens": 36750,
    "total_requests": 45,
    "latest_model_name": "deepseek-chat"
  }
}
```

#### Response 400

缺少 device_id 参数。

#### Response 401

未认证。

#### Rules

| Rule | Meaning |
|------|---------|
| User-scoped | 只返回当前认证用户的 usage，不得跨用户查询 |
| Dual scope | device scope 按 device_id 过滤，user scope 聚合用户所有设备，一次返回 |
| device_id required | device_id 必传，确保前端始终能拿到双 scope |
| Zero defaults | 无记录时返回全零汇总（不返回 404） |
| Write before push | usage 必须先落库再发 SSE result 事件 |
| Error cumulative in summary | Agent 运行异常（error/timeout/cancel）时，已累积的 usage（来自 AgentDeps 逐轮回调）仍须落库并计入 summary 聚合，不得丢弃；只有从未调用 LLM 时才返回全 0 |
| Retry usage preserved | 重试场景下 usage 累积不重置，retry 后保留之前累积的 token 用量并体现在 summary 中 |

---

### CONTRACT-049: Terminal-bound Agent Conversation

| 字段 | 值 |
|------|---|
| ID | CONTRACT-049 |
| 关联任务 | S083, B085, B086, B087, B088, F101, F102, S084, B106, F107, S110 |
| Scope | Server + Client mobile + Client desktop + Agent |
| 认证 | `async_verify_token` 必需 |

#### Core Rule

Agent conversation 与 terminal 一一对应：同一 `user_id + device_id + terminal_id` 只能有一个 active conversation。手机端和桌面端都是该 conversation 的视图/输入端；所有 ReAct 工具调用仍由 Server 调度到承载 terminal 的桌面设备 Agent 执行。

#### APIs

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/runtime/devices/{device_id}/terminals/{terminal_id}/assistant/agent/run` | 在 terminal conversation 中追加用户输入并启动/继续 Agent SSE |
| POST | `/api/runtime/devices/{device_id}/terminals/{terminal_id}/assistant/agent/{session_id}/respond` | 回答该 terminal conversation 中指定 session 的 Agent question |
| POST | `/api/runtime/devices/{device_id}/terminals/{terminal_id}/assistant/agent/{session_id}/cancel` | 取消该 terminal conversation 的指定 active Agent session |
| GET | `/api/runtime/devices/{device_id}/terminals/{terminal_id}/assistant/agent/{session_id}/resume` | 恢复并回放该 terminal conversation 中指定 session 的 SSE 事件 |
| GET | `/api/runtime/devices/{device_id}/terminals/{terminal_id}/assistant/conversation` | 获取 conversation 元数据与事件投影 |
| GET | `/api/runtime/devices/{device_id}/terminals/{terminal_id}/assistant/conversation/stream?after_index=N` | SSE 增量订阅 N 之后的 conversation events |

#### Request Identity Fields

| 字段 | 位置 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | respond/cancel/resume path | 是 | 指定正在回答、取消或恢复的 Agent session；Server 必须校验其归属当前 terminal conversation |
| `client_event_id` | run/respond body | 是 | 客户端生成的幂等 key；同一 conversation 内重复提交同一 key 必须返回已写入事件，不得重复追加 |
| `question_id` | respond body | 是 | Agent question 事件的稳定 ID；同一 `question_id` 只能接受一次有效 answer |
| `answer` | respond body | 是 | 用户选择或输入的回答 |

#### Conversation Response

```json
{
  "conversation_id": "conv_terminal_abc",
  "device_id": "device-1",
  "terminal_id": "terminal-1",
  "status": "active",
  "next_event_index": 4,
  "active_session_id": "agent-session-1",
  "events": [
    {"event_index": 0, "event_id": "evt-0", "type": "user_intent", "role": "user", "client_event_id": "m-1", "payload": {"text": "进入 remote-control"}},
    {"event_index": 1, "event_id": "evt-1", "type": "question", "role": "assistant", "question_id": "q-1", "session_id": "agent-session-1", "payload": {"text": "请选择项目", "options": ["remote-control"]}},
    {"event_index": 2, "event_id": "evt-2", "type": "answer", "role": "user", "client_event_id": "m-2", "question_id": "q-1", "session_id": "agent-session-1", "payload": {"text": "remote-control"}},
    {"event_index": 3, "event_id": "evt-3", "type": "result", "role": "assistant", "session_id": "agent-session-1", "payload": {"summary": "进入项目并启动 Claude"}}
  ]
}
```

#### Event Types

| Event | Meaning |
|-------|---------|
| `user_intent` | 用户发起的新目标 |
| `phase_change` | Agent 会话阶段切换事件，用于 UI 驱动状态展示 |
| `streaming_text` | Agent 模型中间文本回复（用户可见助手消息，SSE event_type='streaming_text'） |
| `answer` | 用户对 Agent question 的回答 |
| `tool_step` | Agent 只读工具调用步骤摘要（含 running/done/error 状态） |
| `question` | Agent 需要用户补充选择或信息 |
| `result` | Agent 最终结果（response_type 区分 command/message/ai_prompt）与 usage |
| `error` | Agent 错误、超时、取消或关闭 |
| `closed` | terminal 已关闭，conversation 不再可写 |

#### Rules

| Rule | Meaning |
|------|---------|
| Server authoritative | Server conversation events 是下一轮 `message_history` 的唯一权威来源 |
| Client cache only | 客户端本地历史只能做渲染缓存，不得拼接成下一轮 AI prompt 的权威上下文 |
| Terminal scoped | conversation 不得跨 terminal 复用；terminal A 的历史不得进入 terminal B |
| Multi-client sync | 任一客户端追加的 question/answer/result 事件，其他客户端 fetch/stream 后必须可见 |
| Signal-only history | 重建下一轮 `message_history` 时只使用 user_intent / question / answer / tool_step / result 5 类信号事件；streaming_text / phase_change 仅用于展示，不进入 LLM 历史 |
| Close destroys | terminal close、设备离线收口为 closed、登出或权限失效时，Server 必须销毁 conversation 并取消 active Agent session |
| Closed rejection | closed terminal 的 run/respond/resume/fetch 返回 404/410 或稳定 `closed_terminal` 错误 |
| Mobile no tools | 手机端可输入和展示同一 conversation，但不得拥有本地 ReAct 工具运行时或执行探索命令 |
| Sensitive data | events 不保存完整本地文件树、敏感文件内容或模型原始 chain-of-thought |
| Idempotent write | `client_event_id` 在同一 conversation 内唯一；重复提交同一 key 返回原事件，不新增 event_index |
| Single answer | 同一 `question_id` 只能写入一次 answer；重复相同 `client_event_id` 幂等返回，其他客户端再次回答返回 409 `question_already_answered` |
| Ordered append | event append 必须在事务/锁内分配 `event_index`，避免多客户端并发写入重复或乱序 |

#### Close Teardown

terminal close 的对外语义是 conversation 已销毁，不再可恢复。实现顺序必须可通知正在订阅的客户端：

1. append ephemeral `closed` event 并广播给 active conversation stream。
2. 取消该 terminal conversation 的 active Agent session。
3. 标记 conversation `status=closed`，拒绝新的 run/respond/resume。
4. 在 stream fanout 完成后删除 events，或保留不超过 30 秒 tombstone 只用于返回 410 `closed_terminal`，不得再返回历史事件。

#### Error Semantics

| 场景 | 响应 |
|------|------|
| closed terminal fetch/run/respond/resume | 410 `closed_terminal`；若 tombstone 已清理可返回 404 |
| session 不属于当前 terminal conversation | 404，不泄漏真实 session 归属 |
| question 已被其他客户端回答 | 409 `question_already_answered` |
| 重复 `client_event_id` | 200/201 返回原事件，不重复写入 |

---

### CONTRACT-050: Dynamic Tool Registration & Invocation Protocol

| 字段 | 值 |
|------|---|
| ID | CONTRACT-050 |
| 关联任务 | B089, B091, B092, B093, S085, S086, S087, B094, F088, S088, B095, F089, B106, F107, S110 |
| Scope | Server + Agent |
| 认证 | Agent WS 已认证 |

#### Core Rule

Agent 设备在启动时和工具变更时，通过 WebSocket 向 Server 上报可用工具目录。Server 在创建 Agent 会话时将动态工具注入 Pydantic AI Agent。所有工具调用（built-in 和 dynamic）均通过现有 WebSocket 链路路由到 Agent 设备执行，结果原路返回。

**Built-in 工具注册权威**：`execute_command`、`ask_user` 由 Server 端始终注册。`lookup_knowledge` 为 R043 新增 built-in，需要 Agent 版本支持（通过 tool_catalog_snapshot 中 kind=builtin 声明确认）；旧 Agent 连接时 Server 不注册 lookup_knowledge，仅提供 execute_command/ask_user。动态工具（`kind: dynamic`）通过 catalog 上报并注入。

**MCP 工具与 execute_command 的本质区别**：动态 MCP 工具不执行 shell 命令，只返回结构化数据（如 git status 文本、文件列表等）。它们不经过 `command_validator` 白名单校验，因为它们根本不接触 PTY/shell。MCP 工具的输入输出通过 MCP 协议约束，由 MCP Server 自行定义 schema。这与 built-in `execute_command` 的白名单+元字符+敏感路径三重防护是不同的安全层。

#### Info-Only Result Extension

R043 新增"信息型问答"旅程：用户询问工具使用方式或知识问题，Agent 调用 `lookup_knowledge` 后直接在 `result` 的 `summary` 中回答，`response_type` 为 `"message"`，`steps` 为空数组。此形态复用现有 `result` 事件类型，无需新增事件：

```json
{
  "event_index": 3,
  "event_id": "evt-3",
  "type": "result",
  "role": "assistant",
  "session_id": "agent-session-1",
  "payload": {
    "response_type": "message",
    "summary": "Claude Code 使用技巧：1. 用 claude 启动... 2. ...",
    "steps": [],
    "need_confirm": false,
    "aliases": {},
    "ai_prompt": "",
    "usage": {...}
  }
}
```

| Rule | Meaning |
|------|---------|
| response_type=`message` | 信息型问答使用 `response_type: "message"`，客户端渲染为结构化结果卡片（可折叠）；与 `streaming_text` 对话气泡区分 |
| steps=[] allowed | `steps` 为空数组表示纯信息回答，客户端直接展示 summary |
| No confirmation needed | `need_confirm=false` 时客户端不展示确认/执行按钮 |
| Same event format | message/command/ai_prompt result 使用完全相同的事件结构，通过 `response_type` 区分渲染 |
| Backward compatible | 旧 Server 不推送 `response_type` 时，Client 默认为 `"command"` |

#### Tool Catalog

**Snapshot 上报**（Agent 启动或全量同步时）：

```json
{
  "type": "tool_catalog_snapshot",
  "tools": [
    {
      "name": "lookup_knowledge",
      "kind": "builtin",
      "description": "检索本地知识文件，返回匹配内容",
      "parameters": {
        "type": "object",
        "properties": {
          "query": {"type": "string", "description": "检索关键词"}
        },
        "required": ["query"]
      }
    },
    {
      "name": "git_helper.status",
      "kind": "dynamic",
      "skill": "git_helper",
      "description": "查看当前 git 仓库状态",
      "parameters": {
        "type": "object",
        "properties": {},
        "required": []
      },
      "capability": "read_only"
    }
  ]
}
```

**Delta 上报**（R043 阶段不实现 delta，仅预留协议格式供后续扩展。当前工具变更通过重启 Agent + 重新上报 snapshot 实现）：

```json
{
  "type": "tool_catalog_delta",
  "added": [],
  "removed": []
}
```

#### Tool Call Payload

Server → Agent（LLM 决定调用工具后）：

```json
{
  "type": "tool_call",
  "call_id": "tc-abc123",
  "tool_name": "lookup_knowledge",
  "arguments": {"query": "Claude Code 使用技巧"}
}
```

Agent → Server（成功）：

```json
{
  "type": "tool_result",
  "call_id": "tc-abc123",
  "status": "success",
  "result": "## Claude Code 使用技巧\n..."
}
```

Agent → Server（失败）：

```json
{
  "type": "tool_result",
  "call_id": "tc-abc123",
  "status": "error",
  "error": "MCP Server git_helper 已退出",
  "fallback_hint": "retry_without_tool"
}
```

#### Priority & Namespacing

| Rule | Meaning |
|------|---------|
| Built-in first | `execute_command`、`ask_user`、`lookup_knowledge` 为 built-in，同名冲突时 built-in 胜出 |
| Dynamic namespaced | 动态工具必须以 `skill_name.tool_name` 格式上报，禁止覆盖 built-in 命名空间 |
| Skill isolation | 不同 skill 的工具互不干扰，一个 skill 崩溃不影响其他 skill 和 built-in |
| No anonymous tools | 所有动态工具必须有 `skill` 字段，用于溯源和生命周期管理 |
| Parameters required | 所有工具（built-in 和 dynamic）必须携带 `parameters` JSON Schema，用于 Server 端参数校验和 Pydantic AI 签名注册 |

#### Capability Boundary

本阶段动态工具能力限定为**只读/信息型**：

| Capability | Meaning | 当前阶段 |
|------------|---------|----------|
| `read_only` | 只读命令，不修改文件系统或系统状态 | **允许** |
| `info_only` | 纯信息查询，无副作用 | **允许** |
| `write` | 可能修改文件系统 | **禁止** |
| `network` | 可能发起外部网络请求 | **禁止** |
| `execute` | 可能执行任意命令 | **禁止** |

**信任模型**：MCP Skill 由用户在 Agent 设备本地手工安装（将 skill 文件放入 skills/ 目录并编辑 skill-registry.json），属于受信扩展。`capability` 字段仅用于 Server 端注册筛选和 UI 展示，不作为运行时安全边界。真正的命令安全由 built-in `execute_command` 的 `command_validator` 白名单保障。动态 MCP 工具不执行 shell 命令，只返回结构化数据。

| Rule | Meaning |
|------|---------|
| Phase restriction | R043 阶段只允许 `read_only` 和 `info_only` capability 的动态工具注册 |
| Reject on registration | Server 收到 `capability: write/network/execute` 的工具时，拒绝注册并返回 warning |
| Trust boundary | 本地安装 skill 为受信扩展，capability 仅做注册筛选，不做运行时 sandbox |
| Desktop-only UI | Skill 管理 UI 仅限桌面端（F089），通过 Agent 本地 HTTP API 管理；手机端不显示入口。用户也可手工操作 skills/ 目录和 skill-registry.json |
| No shell execution | 动态 MCP 工具不执行 shell 命令，只返回结构化数据给 LLM |
| Future extension | 后续需求包可通过 capability metadata + 用户确认门禁扩展写操作工具 |
| Built-in exempt | `execute_command` 等 built-in 工具不受此限制，遵循现有 command_validator 白名单 |

#### Parameter Validation

| 场景 | 响应 |
|------|------|
| 参数类型不匹配 schema | Agent 返回 `tool_result.status=error`，error 包含 "invalid_args" + 具体字段名 |
| 缺少 required 参数 | Agent 返回 `tool_result.status=error`，error 包含 "invalid_args:missing_required" + 字段名 |
| Schema 不合法（注册时） | Server 忽略该工具，记录 warning，不阻塞其他工具注册 |
| Unknown extra params | Agent 忽略多余字段，只提取 schema 中定义的参数 |

#### Tool Result Payload Size

R043 阶段动态工具结果统一为**文本格式**。若 MCP Server 返回结构化数据（JSON 对象/数组），Agent 端负责序列化为文本字符串后再填充 `tool_result.result`。序列化规则：

| MCP 返回类型 | 序列化方式 |
|-------------|-----------|
| 纯文本 | 直接使用，无需转换 |
| JSON 对象/数组 | `json.dumps(data, ensure_ascii=False)` 序列化为字符串 |
| 其他类型 | `str(data)` 强制转文本 |

此规则保证 `tool_result.result` 始终为 string 类型，Server 端和客户端无需区分动态工具的结果格式。

动态工具返回的 `tool_result.result` 存在大小限制：

| 规则 | 值 |
|------|---|
| 单个 tool_result.result 上限 | 64 KB（65536 bytes） |
| 超出时截断 | Agent 端截断并在末尾追加 `[已截断，原始大小 N bytes]` |
| WS 帧上限 | WebSocket 单帧上限 1 MB；单个 tool_result.result 远低于此限制，无需 WS 层分片 |
| Built-in 豁免 | `execute_command`/`ask_user` 不受此限制，遵循现有协议；`lookup_knowledge` 有独立裁剪规则（3 文件/2000 字符） |

截断示例：

```json
{
  "type": "tool_result",
  "call_id": "tc-abc123",
  "status": "success",
  "result": "...前 65536 bytes...[已截断，原始大小 131072 bytes]",
  "truncated": true,
  "original_size": 131072
}
```

| 字段 | 说明 |
|------|------|
| `truncated` | 可选 boolean，true 表示已截断 |
| `original_size` | 可选 int，截断前的原始字节数 |

#### Timeout & Error Semantics

| 场景 | 响应 |
|------|------|
| 工具调用超时（默认 30s） | Server 向 LLM 返回 `tool_result.status=error`，不阻塞 Agent 循环 |
| MCP Server 崩溃 | 该 skill 的 pending calls 返回 error；该 skill 工具在下次 Agent 重启后不再上报 |
| Agent 断连 | Server 清理该 Agent 的全部动态工具，active sessions 的 pending calls 返回 error |
| 工具不存在 | Agent 返回 `tool_result.status=error`，error 包含 "tool not found" |
| 动态工具注册失败（schema 不合法） | Server 忽略该工具，记录 warning，不阻塞其他工具注册 |

#### Agent Disconnect Cleanup

1. Agent WebSocket 断开时，Server 立即将该 Agent 的所有动态工具标记为 stale。
2. Active Agent sessions 中若有 pending dynamic tool calls，立即返回 timeout error 给 LLM。
3. 新 Agent session 不再看到已断连 Agent 的工具。
4. Agent 重连后需重新上报 `tool_catalog_snapshot`。

#### Delta Update Semantics

R043 阶段不实现 `tool_catalog_delta`。工具变更通过 Agent 重启 + 重新上报 `tool_catalog_snapshot` 实现。每次新 Agent session 创建时使用最新的 snapshot。已存在的 active session 继续使用创建时的工具快照，不热更新、不重建。后续需求包可扩展 delta 增量同步。

#### Cold Start & Snapshot Timing

| 场景 | 行为 |
|------|------|
| Agent 已连接、snapshot 已到达 | 正常注册 built-in + 动态工具 |
| Agent 已连接、snapshot 未到达 | Session 仅注册 built-in 工具（execute_command/ask_user），不等待 snapshot；动态工具在该 session 中不可用 |
| Agent 未连接 | Session 仅注册 built-in 工具，行为与当前 R041 一致 |

规则：**不阻塞、不等待**。Session 创建时使用当前已有 snapshot；若 snapshot 为空则降级为 built-in-only。Agent 后续上报 snapshot 后，新创建的 session 将获得完整工具集。已存在的 active session 不热更新。

#### Trace Boundaries

| Rule | Meaning |
|------|---------|
| Unified tool_step | 动态工具调用产生与 built-in 相同格式的 `tool_step` 事件，包含 tool_name、status 和耗时 |
| Skill attribution | `tool_step.tool_name` 包含 skill 前缀（如 `git_helper.status`），便于追踪 |
| No internal leak | `tool_step` 不暴露 MCP Server 内部协议细节，只展示工具名、参数摘要和结果摘要 |
| Error traceable | 工具调用失败的 `tool_step` 必须包含 error category（timeout / crash / not_found / invalid_args） |

#### Mixed-Intent Result Semantics

当 LLM 在同一轮中同时产出知识回答和命令步骤时，`steps` 非空，行为与普通命令结果一致：

| 字段 | 规则 |
|------|------|
| `steps` | 非空时包含命令序列，与普通命令结果格式完全一致 |
| `need_confirm` | 必须为 `true`（有命令就必须确认） |
| `summary` | 同时包含知识回答摘要和命令说明 |
| Client rendering | 与现有命令结果渲染逻辑一致：展示 summary + 确认/执行按钮 |
| Authority | `steps` 为执行权威，summary 为辅助说明 |

不定义新的 result 类型，混合意图就是普通命令结果（summary 中多了知识内容）。

#### Skill Manifest & Registry Schema

**skill.json**（单个 Skill 描述文件，位于 `skills/<skill_name>/skill.json`）：

```json
{
  "name": "git_helper",
  "version": "1.0.0",
  "description": "Git 仓库辅助工具",
  "command": "python",
  "args": ["-m", "git_helper_mcp"],
  "transport": "stdio",
  "timeout": 30
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | 是 | Skill 名称，用于 namespaced 工具前缀（`name.tool_name`） |
| `version` | 是 | 语义化版本号 |
| `description` | 是 | Skill 用途描述 |
| `command` | 是 | MCP Server 启动命令 |
| `args` | 否 | 启动参数列表 |
| `transport` | 是 | 通信方式，R043 仅支持 `stdio` |
| `timeout` | 否 | 单次工具调用超时（秒），默认 30 |

**Malformed 判定**：缺少 `name`/`command`/`transport` 任一字段，或 `transport` 不是 `stdio`，视为 malformed，跳过并记录 warning。

**skill-registry.json**（全局注册表，位于 Agent 数据目录下）：

```json
{
  "skills": [
    {"name": "git_helper", "enabled": true},
    {"name": "code_review", "enabled": false}
  ]
}
```

| 字段 | 说明 |
|------|------|
| `skills` | 数组，每项含 `name` 和 `enabled` |
| 缺失 | 视为空列表（全启用） |
| 格式损坏 | 视为空列表，记录 warning |

#### Tool Catalog Registration Limits

| 约束 | 值 | 超限处理 |
|------|---|----------|
| 最大工具数 | 50（单次 snapshot） | 超出部分忽略，记录 warning |
| 单工具 description 长度 | 500 字符 | 截断 |
| 单工具 parameters schema 大小 | 4 KB | 超出拒绝注册该工具 |
| 单次 snapshot payload 大小 | 256 KB | 超出拒绝整个 snapshot |

#### lookup_knowledge Degradation Matrix

| 场景 | 用户可见行为 | 内部处理 |
|------|------------|---------|
| Agent 支持 + 知识命中 | summary 包含知识回答，steps 视意图决定 | 正常调用 lookup_knowledge |
| Agent 支持 + 知识未命中 | summary 说明"未找到相关知识" + 正常命令/回答 | lookup_knowledge 返回空结果，LLM 继续正常处理 |
| Agent 不支持（旧版本） | 正常 Agent 行为，无知识增强 | Server 不注册 lookup_knowledge，LLM 不调用 |
| Snapshot 未到达（冷启动） | 仅 built-in 工具可用 | Session 降级为 built-in-only |
| Agent 离线 | 无法创建 Agent session | 现有离线提示行为 |

R043 不允许模型在 lookup_knowledge 不可用时自行编造知识内容。

#### Product Boundary: Codex Mapping

`Codex CLI → codex` 映射仅用于知识说明场景（用户问"Codex 怎么用"）。R043 不生成 `codex` 执行命令，不修改架构中"Claude 模式为唯一执行后端"的不变量。如果用户说"用 Codex 打开"，Agent 应解释 Codex CLI 的安装和使用方式，不生成可执行命令步骤。

### CONTRACT-051: Eval Framework Core

| 字段 | 值 |
|------|-----|
| ID | CONTRACT-051 |
| 关联任务 | B096, B097, B098, B099, B100, S089, S090, B108 |
| 模块 | server/evals |

#### Eval Task Definition (YAML → EvalTaskDef)

```yaml
id: string              # 唯一标识
category: string        # intent_classification | command_generation | knowledge_retrieval | safety | multi_turn
description: string     # 任务描述
input:
  intent: string        # 用户意图
  context:
    cwd: string         # 模拟工作目录
    device_online: bool # 设备在线状态
    mock_tool_responses:  # execute_command 的模拟返回
      "command": "mock output"
expected:
  response_type: [string]     # 可接受的 response_type 列表
  steps_contain: [string]     # steps 应包含的模式
  steps_not_contain: [string] # steps 不应包含的模式
graders: [string]             # 使用的 grader 名称列表
metadata:
  source: string       # 来源（R043_known_failure / daily_usage / user_feedback）
  difficulty: string   # easy | medium | hard
  tags: [string]
  reference_solution: string  # 参考答案
```

#### Eval Trial 数据模型

| 字段 | 类型 | 说明 |
|------|------|------|
| trial_id | str | UUID |
| task_id | str | 关联 EvalTaskDef.id |
| run_id | str | 关联 EvalRun |
| transcript | JSON | 完整 LLM 交互记录（请求/响应/工具调用/返回） |
| agent_result | JSON | 最终 AgentResult |
| duration_ms | int | 执行耗时 |
| token_usage | JSON | {input_tokens, output_tokens, total_tokens} |
| created_at | datetime | 创建时间 |

#### Eval Grader Result 数据模型

| 字段 | 类型 | 说明 |
|------|------|------|
| grader_id | str | UUID |
| trial_id | str | 关联 trial |
| grader_type | str | response_type_match / command_safety / steps_structure / contains_command / tool_call_order / llm_judge |
| passed | bool | 是否通过 |
| score | float | 0.0-1.0 |
| details | JSON | 详细评分信息 |

#### 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| EVAL_AGENT_MODEL | 是 | 被测 Agent 模型名 |
| EVAL_AGENT_BASE_URL | 是 | 被测 Agent API 地址 |
| EVAL_AGENT_API_KEY | 是 | 被测 Agent API 密钥 |
| EVAL_JUDGE_MODEL | 否 | LLM Judge 模型名，未配置跳过 Judge grader |
| EVAL_JUDGE_BASE_URL | 否 | 默认复用 EVAL_AGENT_BASE_URL |
| EVAL_JUDGE_API_KEY | 否 | 默认复用 EVAL_AGENT_API_KEY |

缺失必填项时 eval CLI/harness 报错退出，不复用 ASSISTANT_LLM_* 变量。

#### Eval 数据库 Schema（6 张表）

| 表名 | 用途 | 关键字段 |
|------|------|---------|
| eval_task_defs | YAML 加载的 task 定义 | id, category, description, input_json, expected_json, graders_json, metadata_json |
| eval_trials | 单次执行记录 | trial_id, task_id, run_id, transcript_json, agent_result_json, duration_ms, token_usage_json |
| eval_grader_results | grader 输出 | grader_id, trial_id, grader_type, passed, score, details_json |
| eval_runs | 批量运行 | run_id, started_at, completed_at, total_tasks, passed_tasks, config_json |
| quality_metrics | 在线质量指标 | metric_id, session_id, user_id, device_id, metric_name, value, computed_at |
| eval_task_candidates | 反馈闭环 candidate | candidate_id, source_feedback_id, suggested_intent, suggested_category, suggested_expected_json, status, reviewed_by, reviewed_at |

Harness 支持两种 task 来源：1) YAML 目录批量加载 2) evals.db 中 status=approved 的 candidate（由反馈闭环审批后写入）。两者合并后执行。

#### R046 Eval Extension: deliver_result 完成判定

| Rule | Meaning |
|------|---------|
| deliver_result as completion | harness 将 `deliver_result` 工具调用识别为 Agent 完成信号，等同于旧版 `_extract_final_result` 输出完成 |
| Incomplete on no delivery | LLM 未调用 `deliver_result` 时 trial 状态为 `incomplete`（区分于 `fail`），不参与 pass@k 计算 |
| tool_call_order exclusion | `tool_call_order` grader 排除 `deliver_result` 工具调用，不计入工具调用序列评分 |
| Prompt alignment | eval harness 使用的 SYSTEM_PROMPT 与生产 Agent prompt 对齐（含 deliver_result 工具描述） |

### CONTRACT-052: Online Quality Metrics

| 字段 | 值 |
|------|-----|
| ID | CONTRACT-052 |
| 关联任务 | B101, B102, S091 |
| 模块 | server/evals |

#### Quality Metrics 数据模型

| 指标 | 类型 | 计算来源 |
|------|------|---------|
| response_type_accuracy | float | agent_conversation_events 中 result 事件的 response_type 与 intent 匹配度 |
| tool_usage_efficiency | float | 工具调用次数 / 解决问题所需轮数 |
| command_safety_rate | float | 生成命令通过 command_validator 的比例 |
| ask_user_frequency | float | ask_user 工具调用次数 / 总轮数 |
| token_efficiency | float | total_tokens / 任务复杂度（按 category 分桶） |

#### API Endpoints

**GET /api/eval/quality/metrics**

| 参数 | 类型 | 说明 |
|------|------|------|
| start_time | ISO datetime | 起始时间 |
| end_time | ISO datetime | 结束时间 |
| user_id | string | 用户过滤 |
| device_id | string | 设备过滤 |
| category | string | 指标类别过滤 |

响应: `{ "metrics": [{metric_name, value, sample_size, time_window}], "total": N }`

认证: `async_verify_token` 必需。

**GET /api/eval/quality/summary**

| 参数 | 类型 | 说明 |
|------|------|------|
| window | string | day / week / month |
| start_time | ISO datetime | 起始时间 |
| end_time | ISO datetime | 结束时间 |

响应: `{ "windows": [{window_start, window_end, metrics: {name: value}}] }`

认证: `async_verify_token` 必需。

注意：质量查询 API 不依赖模型环境变量，不返回 503。数据来源是已持久化的指标记录。

### CONTRACT-053: Feedback Loop & Regression

| 字段 | 值 |
|------|-----|
| ID | CONTRACT-053 |
| 关联任务 | B103, B104, S092 |
| 模块 | server/evals |

#### 反馈→Candidate 流程

1. 用户提交反馈 → feedback API 正常保存
2. 异步触发：LLM 分析反馈摘要（脱敏后），判断是否为 Agent 质量问题
3. 如果是 → 生成 candidate eval task 写入 `eval_task_candidates` 表
4. 反馈内容不直接进入 eval 系统，只传递脱敏摘要和分类信息

#### Candidate 数据模型

| 字段 | 类型 | 说明 |
|------|------|------|
| candidate_id | str | UUID |
| source_feedback_id | str | 来源反馈 ID（仅存引用，不存原始内容） |
| suggested_intent | str | LLM 建议的测试意图 |
| suggested_category | str | LLM 建议的 task 类别 |
| suggested_expected | JSON | LLM 建议的期望结果 |
| status | str | pending / approved / rejected |
| reviewed_by | str | 审核人 |
| reviewed_at | datetime | 审核时间 |
| created_at | datetime | 创建时间 |

#### 审核 API

**GET /api/eval/candidates** — 列出 candidate（需认证）
**POST /api/eval/candidates/{id}/approve** — 批准（转为正式 eval task，可被 harness 加载）
**POST /api/eval/candidates/{id}/reject** — 拒绝

#### 回归测试 CLI

```bash
python -m evals run --tasks dir --trials N
python -m evals regression --baseline run_id
python -m evals trend --window week
```

#### 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| EVAL_FEEDBACK_MODEL | 否 | 反馈分析模型，未配置跳过自动转换 |
| EVAL_FEEDBACK_BASE_URL | 否 | 默认复用 EVAL_AGENT_BASE_URL |
| EVAL_FEEDBACK_API_KEY | 否 | 默认复用 EVAL_AGENT_API_KEY |
