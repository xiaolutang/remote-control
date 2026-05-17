# R070 SSE 性能修复 + 桌面端 Agent 生命周期修复 归档

- 归档时间: 2026-05-17
- 状态: completed
- 总任务: 5
- 分支: fix/R070-sse-perf-desktop-lifecycle
- workflow: mode=A | runtime=skill_orchestrated | evaluate_provider=local | risk_provider=local

## 仓库提交

- ec326a5 (HEAD on main)

## Phase 0: Architecture
| 任务 | 描述 | commit |
|------|------|--------|
| B070-000 | Architecture 不变量追加 | 861d9ae |

## Phase 1: SSE 修复
| 任务 | 描述 | commit |
|------|------|--------|
| B070-001 | SSE stream 事件驱动重构 | 5a7b4a8 |
| F070-002 | SSE 重连连接泄漏修复 | 693322a |

## Phase 2: 桌面端修复
| 任务 | 描述 | commit |
|------|------|--------|
| F070-003 | 桌面端 Agent 生命周期修复 | acff594 |

## Phase 3: 验证
| 任务 | 描述 | commit |
|------|------|--------|
| B070-004 | 端到端验证 + 回归测试 | 773ba71 |

## Simplify 修复
| 任务 | 描述 | commit |
|------|------|--------|
| simplify | 移除 SSE responseRef/onCancel + 测试对齐 | a084f26 |

## 关键交付
- SSE stream 从 busy-loop 改为 Queue 事件驱动，CPU 从 89% 降至 <5%
- 移除导致运行时 crash 的 SSE onCancel（单订阅 Stream 限制）
- handleViewDispose 不再停止 Agent，新增 handleAppExit 处理 App 级退出
- architecture.md 追加 3 条禁止模式
- defect_feedback.md OPS-001/OPS-002 状态更新为 fixed
