# S001: R055 需求规划 Session

**日期**: 2026-05-06
**状态**: planning

## 需求来源

正式安装到 Mac 的 .app 程序两个生产问题：
1. 终端找不到 `claude` 命令（PATH 缺失）
2. Agent 登录后等待时间长

## 需求澄清

### PATH 缺失（确定性 Bug）
macOS .app 从 Finder 启动时继承 launchd 的最小 PATH（`/usr/bin:/bin:/usr/sbin:/sbin`），不含 homebrew 路径。
需要 agent 启动时检测并补全 PATH。

### Auth 连接缓慢（需调查）
原方案认为"降低超时值"是核心修复。经分析：
- 超时是上限，不是实际耗时。Server 可达时每个 HTTP 调用 <200ms
- 70s 最坏情况只在 Server 完全不可达时发生
- 降超时只在 Server 不可达时让"失败来得更快"，对正常体验无帮助

**决策**：
- 降超时作为防御性改善保留（无害）
- 增加 auth 流程耗时日志，定位真实瓶颈
- 不宣称降超时"解决连接缓慢"

## 工作流

- mode: B
- runtime: skill_orchestrated
- review_provider: codex_plugin
- audit_provider: codex_plugin
- risk_provider: codex_plugin

## Codex Plan Review (Round 1)

**结论**: fail
**时间**: 2026-05-06T17:01:32+08:00
**provider**: codex_plugin

### 审核发现（7 项）

1. **journey/HIGH**: 无任务覆盖 .app 真实启动链路验证
2. **seam/HIGH**: Smoke 测试没有归属到具体任务
3. **test/HIGH**: S304/S305 有 network risk 但无 test_tasks
4. **architecture/HIGH**: logger.info 不会出现在桌面端可观测日志中
5. **seam/MEDIUM**: 超时降低后状态转换无人兜底
6. **feasibility/MEDIUM**: PATH 检测用精确匹配太脆弱
7. **test/MEDIUM**: S303 缺少边界 case

### 修复措施

- **Finding 1+2**: 新增 S306 手工 smoke 任务，绑定两个 smoke 场景
- **Finding 3**: S304 补充 test_tasks（成功/失败/超时日志），S305 补充 test_tasks（fallback 不变、超时值确认）
- **Finding 4**: S304 改用 `_log()` 输出到 stderr（桌面端捕获），AuthService/crypto 用 logger.info
- **Finding 5**: S305 description 显式说明状态转换不变
- **Finding 6**: S301 触发条件改为"缺失关键用户空间路径"（非精确匹配）
- **Finding 7**: S303 扩展到 7 个测试场景，增加部分 PATH、$SHELL 缺失、空 PATH 等

## Codex Plan Review (Round 2)

**结论**: conditional_pass
**时间**: 2026-05-06T09:06:17Z
**provider**: codex_plugin

### 审核发现（4 项）

1. **test/MEDIUM**: S302 无 test_tasks，startup 风险无自动化验证
2. **architecture/HIGH**: AuthService/crypto 用 logger.info 在 .app 场景不可见
3. **test/MEDIUM**: S304 缺 refresh 分支耗时日志测试
4. **test/HIGH**: S305 未覆盖完整 fallback 状态机（refresh→login→error）

### 修复措施

- S302: 补充 3 个 test_tasks（run/start 调用验证、调用顺序验证）
- S304: 统一改为 _log() 输出到 stderr，补充 refresh 和 pubkey 耗时测试
- S305: 补充完整状态机测试（refresh→login、login→error）

## 任务拆解

6 个任务，Phase 0（PATH 修复，3 个）+ Phase 1（Auth 优化 + Smoke，3 个）。
