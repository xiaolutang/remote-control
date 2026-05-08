# S001 R057 规划 session

- 日期: 2026-05-08
- 模式: B (codex_plugin/skill_orchestrated)

## 需求讨论

用户要求：项目代码优化、技术债务处理。选择全面清理（20+ 任务）。

## 扫描结果摘要

三模块并行扫描，发现：
- Server: 10 处静默异常、13 处 f-string 日志、4 处重复代码、多处硬编码配置
- Agent: cli.py 30 行重复、双轨日志、4 个 Config 死字段、verify_token hack
- Client: 37 处 catch(_)、50+ debugPrint、10 处硬编码 URL、deprecated 迁移未完成

## 任务拆解

22 个任务，5 个 Phase：
- Phase 0: Server 异常 + 日志 + 重复代码 + 配置（4）
- Phase 1: Agent 日志 + 重复代码 + Config（5）
- Phase 2: Client 异常处理（3）
- Phase 3: Client 代码质量（5）
- Phase 4: 测试补充 + 全局验证（5）

## 决策

- 聚焦范围：静默异常、日志统一、重复代码、死代码/deprecated（4 方向全选）
- 规模：全面（20+ 任务）
