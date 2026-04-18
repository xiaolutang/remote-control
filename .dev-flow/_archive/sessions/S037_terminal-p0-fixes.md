# Session S037: 终端 P0 稳定性修复规划

> 日期：2026-04-16
> 状态：规划完成，待执行

## 需求来源

用户在真实使用中发现终端存在 P0 级体验问题，需要优先收敛：

- Codex 在 remote-control 里经常退化成近似单行重绘
- Claude Code 终端虽相对可用，但 CPR/TUI 兼容性也存在风险
- 手机上弹出软键盘会影响桌面端查看同一 terminal 的布局
- 多 terminal 切换后出现白屏，需要手动刷新且不稳定

关联缺陷记录：`DF-20260416-02`

## 需求澄清结论

- 本轮先做终端 P0 修复，不扩成“共享 PTY 语义重构”
- 任务拆解分成两层：
  - 协议兼容：`F067` CPR 坐标修复
  - 视图/状态管理：`F068` 闪烁、`F069` 键盘 resize 隔离、`F070` terminal 缓存复用
- `F070` 依赖 `F069`，其余任务可并行
- 高风险任务 `F069/F070` 保留 `first_use` 风险标签，并要求 smoke

## Workflow 校正

本轮最初把 `workflow.mode = A` 与 `review_provider/audit_provider/risk_provider = codex_plugin` 混写在一起，语义不一致。

按“宿主为主体”的执行链路，已统一校正为：

- `workflow.mode = A`
- `workflow.runtime = skill_orchestrated`
- `workflow.review_provider = local`
- `workflow.audit_provider = local`
- `workflow.risk_provider = local`

## 规划审核记录

- `review_status`: pass
- `reviewed_at`: 2026-04-16
- `review_provider`: local
- `required_changes`: []

### Review Findings

1. 初始规划存在 workflow 路由不一致：`mode=A` 但 provider 写成 `codex_plugin`
2. 初始规划只更新了 `feature_list.json`，未同步 `test_coverage.md`、`alignment_checklist.md`、`project_spec.md`

以上问题已在本 session 内修正后复审，通过。

## 执行建议

- 推荐首个任务：`F067` CPR 坐标修复
- 推荐执行顺序：`F067` → `F068` → `F069` → `F070`
- 当前需求包 branch：`fix/terminal-p0-fixes`
