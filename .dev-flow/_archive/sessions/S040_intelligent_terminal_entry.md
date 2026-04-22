# Session S040: 智能终端进入规划

> 日期：2026-04-22
> 状态：已规划，待执行

## 需求来源

用户反馈当前“新建终端”链路在手机端使用成本过高：

- 进入 `Codex / Claude Code` 前没有智能，用户必须自己决定目录、标题和命令
- 手机端长文本输入不方便，不适合先创建裸 shell 再手动输入一长串内容
- 用户希望在“新建终端”后先与系统交互一句，直接以某种方式进入 `Codex / Claude Code`

同时用户确认：

- 原始目标是“一句话交互后直接进入合适工具”
- 推荐式智能不与该目标冲突，可以作为零输入兜底
- 本轮审核链路使用本地审核：`workflow.mode = A`, `review_provider = local`

## 需求澄清结论

- 本轮不做真正长对话代理，也不引入新的服务端 LLM 基础设施
- v1 先交付“轻量智能进入编排”：
  - 推荐式入口：`Claude Code / Codex / Shell / 自定义`
  - 意图式入口：用户输入一句目标，系统生成 terminal 启动方案
  - 高级配置兜底：允许随时编辑 `title / cwd / command`
- 智能必须前移到“创建 terminal”之前，而不是进入 shell 后再补救
- 智能编排只属于 Client；Server/Agent 只负责执行最终 terminal create payload

## 本轮沉淀的关键设计

### 1. TerminalLaunchPlan 作为统一中间层

所有推荐式、意图式、自定义创建，最终都先生成同一个 `TerminalLaunchPlan`：

- `tool`
- `title`
- `cwd`
- `command`
- `source`
- `intent`
- `confidence`
- `requires_manual_confirmation`

### 2. 双模式并行，不互斥

- 推荐式智能解决“我不想输入，只想快速进入”
- 意图式智能解决“我只想说一句目标”
- 两者共存，不互斥

### 3. 高级配置不再是主路径

现有裸表单不是删除，而是降级为高级配置兜底：

- 智能结果不准确时允许覆盖
- 创建失败后允许基于原 plan 继续修正
- 不再让用户一开始就面对三个空白字段

### 4. 保持后端边界稳定

- 不新增 Server/Agent 的自然语言理解职责
- 不修改现有 terminal create API 契约
- v1 的智能完全在 Flutter Client 内完成

## 任务树结论

新增任务：

- `S077` 智能终端进入产品基线
- `F077` 智能创建入口 UI
- `F078` 启动方案推荐服务
- `F079` 一句话意图到 TerminalLaunchPlan
- `F080` 创建链路统一收口
- `F081` 自动化与首用 smoke

## 风险与约束

- `first_use`：手机端首用必须足够直观
- `config`：自动生成的 `cwd / command` 不能静默写错
- 不允许因智能链路阻断手动创建
- runtime selection 与 workspace 两个入口必须共用实现，避免再次分叉

## 执行建议

推荐顺序：

1. `S077`
2. `F078`
3. `F079`
4. `F077`
5. `F080`
6. `F081`

原因：

- 先定 `TerminalLaunchPlan` 和推荐/意图边界，再做 UI，能避免先画界面后返工
- 推荐服务与意图服务先稳定，UI 只消费结果
- 最后统一收口创建链路并补测试，避免两个入口再次分叉

## 本地审核结论

本轮规划按本地审核链路收口，自检结论：

- 用户路径明确
- 架构边界与现有 `Server / Agent / Client` 职责一致
- 未引入新的服务端依赖和高耦合路径
- 任务顺序可执行，且每个任务都可形成独立可验证闭环
