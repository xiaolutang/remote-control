# R054 code-quality-consolidation 归档

- 归档时间: 2026-05-06
- 状态: completed
- 总任务: 11
- 分支: chore/R054-code-quality-consolidation
- workflow: skill_orchestrated
- providers: review=codex_plugin, audit=codex_plugin, risk=codex_plugin

## 仓库提交
- remote-control: 22867db (HEAD on chore/R054-code-quality-consolidation)

## Phase 1 (协议层统一)
| 任务 | 描述 | commit |
|------|------|--------|
| S062 | WS 消息类型枚举 + 协议常量统一 | 34cadcb |
| S063 | command_validator 去重 | ed08c21 |

## Phase 2 (session store 优化)
| 任务 | 描述 | commit |
|------|------|--------|
| B055 | session store 热路径优化 | 3d6ba4a |

## Phase 3 (模块结构收敛)
| 任务 | 描述 | commit |
|------|------|--------|
| B056 | agent_request 统一错误处理 + PendingRequestRegistry | a26e56c |
| B057 | ws_agent re-export hub 消除 | 6b74aa5 |
| B058 | ws_client 拆分 | 17f8d98 |
| B058b | user_api 收敛：refresh_token + auth 下沉 | 900a74d |

## Phase 4 (效率优化)
| 任务 | 描述 | commit |
|------|------|--------|
| B059 | 效率优化：心跳 + 连接去重 + history | e21a6bb |
| B060 | SSE stream 缓存优化 | 5420d0f |

## Phase 5 (Agent 清理)
| 任务 | 描述 | commit |
|------|------|--------|
| S064 | Agent 清理：alias shim + _log 提取 + CONFIG_DIR 统一 | 2b9d40e |

## Phase 6 (集成验证)
| 任务 | 描述 | commit |
|------|------|--------|
| S065 | 需求包级集成 smoke 验证 | 0935d3d |

## 后续修复
| 任务 | 描述 | commit |
|------|------|--------|
| fix | 修复 codex review 发现的 4 个 P1 问题 | 22867db |

## 关键交付
- 三端 WS 消息类型枚举统一（server/agent/client 各自 MessageType 定义，替代 40+ 裸字符串）
- command_validator 白名单提取为 shared/command_whitelist.json，消除 80 行重复
- session store 热路径优化：normalize changed 标志避免无效回写、terminal 进程内缓存、user_id 反向索引
- PendingRequestRegistry 统一管理 6 类 pending futures
- ws_agent re-export hub 消除（50+ 符号），ws_client 拆分为 4 个子模块
- user_api 收敛：refresh_token 下沉到 store 层，密码哈希下沉到 infra 层
- 心跳状态变化写入、连接 terminal 去重、history 渐进式读取
- SSE stream 500ms TTL 缓存优化
- Agent 10 个 alias shim 删除、_log 提取、DEFAULT_CONFIG_DIR 统一
