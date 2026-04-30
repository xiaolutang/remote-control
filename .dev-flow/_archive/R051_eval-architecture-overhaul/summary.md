# R051 eval-architecture-overhaul 归档

- 归档时间: 2026-04-30
- 状态: completed
- 总任务: 11
- 分支: feat/R051-eval-architecture-overhaul
- workflow: mode=B / runtime=skill_orchestrated
- providers: codex_plugin/codex_plugin/codex_plugin

## 仓库提交
- remote-control: aa9c84f (HEAD on main)

## Phase 1 (架构修正 + 断链修复)
| 任务 | 描述 | commit |
|------|------|--------|
| S052 | 配套产物刷新（前置） | 400906e |
| B051 | Session 生命周期改为 per-terminal + 单元测试 | 8c41d0b |
| F053 | 客户端 token 展示适配 per-terminal session + 测试 | c99dffa |

## Phase 2 (评估补全 + 断链修复)
| 任务 | 描述 | commit |
|------|------|--------|
| B052 | Feedback→Eval 闭环 + Quality Monitor 自动触发 | f8a460b |
| B053 | Eval HTML 报告生成器 | 7de5480 |
| B054 | 不变量 Grader + 多轮状态一致性测试 | 23e02c1 |
| B055 | 效率指标补全（n_turns、n_toolcalls、延迟） | 7de5480 |
| F054 | Agent 面板回答质量反馈按钮 + widget 测试 | 07c63fb |

## Phase 3 (清理 + 收敛)
| 任务 | 描述 | commit |
|------|------|--------|
| B056 | Balanced Problem Sets + Production Path Testing | f60d07f |
| S051 | 信号处理器 + cleanup 命令 + evals.db 保留策略 | f60d07f |
| S053 | Eval CLI 文档补全 | f60d07f |

## Phase 4 (simplify 收敛 + 技术债务)
| 提交 | 描述 |
|------|------|
| 47b3d7e | simplify 全面收敛 — 并发优化、代码去重、批量写入 |
| ad6481f | simplify 收敛修复 — 消除冗余代码和低效模式 |
| 040dc4a | 结构化并发 — create_task 替换为 asyncio.gather |
| eb49b7e | 补齐 gather 结构化并发回归测试 |
| 96f86f6 | 修复 codex review 第 2 轮发现的 3 个问题 |
| eb5af0c | 解决 3 项技术债务（事件钩子、DB 命名、SSE 推送） |
| f16d5a9 | 新增评估体系架构决策记录 |

## 关键交付
- Session 生命周期从 per-question 改为 per-terminal，消除重复 session 创建
- Feedback→Eval 闭环：用户反馈自动转为 eval candidate，quality monitor 自动触发
- Eval HTML 报告生成器（CLI report/compare/regression-only）
- InvariantGrader + 5 个反向测试 YAML task
- App→Evals 依赖改为事件钩子解耦
- 218 个服务端测试全部通过
