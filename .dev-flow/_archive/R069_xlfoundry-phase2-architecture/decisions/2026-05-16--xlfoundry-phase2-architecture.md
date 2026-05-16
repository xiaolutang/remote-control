---
date: 2026-05-16
type: architecture_discussion
status: decided
requirement_cycle: R069
architecture_impact: true
supersedes: null
---

# xlfoundry Phase 2 架构改造

## 背景

xlfoundry 自动执行时，主 agent 上下文膨胀导致跳过关键步骤（如 Codex review）。同时受到 Anthropic《Harness Design for Long-Running Application Development》文章启发，将 GAN 式生成器-评估器模式引入 xlfoundry 工作流。

## 核心决策

### 1. 生成器-评估器配对

整个系统由三对生成器-评估器组成：

| 生成器 | 评估器 | 协商内容 |
|--------|--------|----------|
| plan | plan-review | 整体拆法、需求覆盖、可行性 |
| implementer | evaluate | sprint contract（具体验收标准） |
| contract negotiate 中的双方 | — | 实现前锁定可测试的契约 |

### 2. 角色改造

**保留**：
- brainstorm（可选前置，不变）
- plan（只管"做什么"，用户视角，不拆前后端，不分配 domain）
- plan-review（变为 plan 的评估器，增加协商机制、评估标准）
- execute（feature 调度器，通过 Agent tool spawn subagent，天然上下文重置）
- implementer（增加 simplify 内部调用 + 按契约实现 + 维护 architecture.md）
- simplify（内容不变，变为 implementer 的内部调用）
- archive（不变）
- risk（按需，不变）

**新增**：
- contract negotiate（implement 前的契约协商环节）
- evaluate（合并 code-review + audit）

**删除**：
- code-review（职责拆入 simplify + evaluate）
- team-orchestrator（execute 内部 Agent tool 替代）

### 3. 单 task 流程

```
contract negotiate（实现者 ↔ 评估者协商契约）
  产出：Sprint Contract + domain + assignee + api_contracts.md 条目
  ↓
implement（按 domain 路由给对应 subagent）
  ├── UI → Gemini implementer（含 simplify 自检）
  └── 后端 → Claude implementer（含 simplify 自检）
  → 结果写入 evidence
  ↓
evaluate（按 domain 路由给对应 subagent）
  ├── 硬性条件：单元测试通过？集成测试通过？→ 任一不通过直接 fail
  ├── 契约评分：按标准逐条打分 → 过阈值才算通过
  └── pass → 继续 / fail → 回到 implement
```

跨域 task 通过 api_contracts.md 文件契约桥接，subagent 之间不直接通信。

### 4. Plan 产物变化

改造前：
```json
{
  "acceptance_criteria": [...],      // 删除
  "implementation_notes": "...",     // 删除
  "test_coverage": [...]             // 移到 contract negotiate
}
```

改造后：
```json
{
  "user_stories": ["用户能看到终端列表，带状态标记"],
  "success_picture": "用户打开终端管理页，看到所有终端的状态一目了然",
  "dependencies": ["F01"],
  "risk_tags": [...]
}
```

Plan 只管用户视角：做什么、成功画面、依赖关系。不涉及 domain 标注、技术拆分、API 契约。
domain 标注和技术拆分由 contract negotiate 环节承接。
API 契约（api_contracts.md）由 implementer 和 evaluate 在实现过程中维护。

### 5. 两层契约

- **api_contracts.md**：前后端之间的协议，由 implementer 和 evaluate 在实现过程中维护
- **sprint contract**：每个 task 内部的验收标准，实现者和评估者在 contract negotiate 环节协商产生

### 5.1. architecture.md 维护

architecture.md 由 implementer 和 evaluate 共同维护，作为代码编写的一环：

| 角色 | 对 architecture.md 的权限 |
|------|--------------------------|
| brainstorm | 只读 |
| plan | 只读 |
| plan-review | 只读，检查冲突 |
| implementer | **可写**（代码变更涉及架构时同步更新） |
| evaluate | **可写**（发现不一致时可修正），并检查 implementer 的更新是否到位 |

evaluate 的 Hard Gates 增加：architecture.md 一致性检查。改了代码但没更新 architecture.md → fail。

### 6. Sprint Contract 格式

```markdown
# Sprint Contract: {taskId}

## Task Reference
- task_id: R069-02
- domain: client-ui | backend | integration
- assignee: gemini | claude

## Implementation Scope
（实现者描述要做什么）

## Hard Gates（硬性条件，binary）
- [ ] unit_test_pass: 单元测试通过
- [ ] integration_test_pass: 集成测试通过（如适用）
- [ ] simplify_pass: 自检通过

## Scored Criteria（评分项，按标准打分）

### C1: 功能完整性（阈值: 4/5）
（具体检查项）

### C2: 视觉/代码质量（阈值: 3/5）
（具体检查项，UI task 看视觉，backend task 看代码质量）

### C3: 交互/错误处理（阈值: 3/5）
（具体检查项）
```

UI task 和 backend task 使用相同的契约格式，但 Scored Criteria 的维度不同：
- UI task：功能完整性 / 视觉质量 / 交互质量 / 平台适配
- Backend task：API 正确性 / 错误处理 / 代码质量

### 7. Evaluate 的验收逻辑

硬性条件（binary，不过直接 fail）：
- 单元测试通过
- 集成测试通过
- simplify 自检通过
- architecture.md 一致性（改了架构必须同步更新）

契约评分（按标准打分，过阈值通过）：
- sprint contract 逐条验收
- 测试维度覆盖（happy path / failure / boundary / first_use）
- 运行态可用性（高风险 task）

### 8. UI 验收：评估器自己操作应用截图

评估器（而非实现者）负责启动应用、导航、截图、评估。这是 Harness Design 文章的做法——评估器用 Playwright 自己操作页面。

**UI task 的 evaluate 流程**：
1. 读取 sprint contract + 代码 diff
2. 自己启动应用（flutter run / Playwright）
3. 自己导航到目标页面、构造不同状态、截图
4. 看截图 + 对照设计参考文档 → 逐条评分
5. 输出结论

**后端 task 的 evaluate 流程**：
1. 读取 sprint contract + 代码 diff
2. 自己跑 API 测试验证（curl / httpx）
3. 看试结果 + 代码 → 逐条评分
4. 输出结论

关键区别：评估者自己决定截什么、测什么。想看空状态就清空数据，想看加载态就模拟慢网络。比实现者"摆拍"截图可靠。

### 9. 编排方式

采用 Claude Code Agent tool subagent 模式，不需要外部 Python 编排器。

execute 作为主 agent，通过 Agent tool spawn 独立 subagent，天然实现上下文重置：

```
execute（主 agent，上下文只存调度状态）
  │
  ├─ Agent tool → contract-negotiate subagent（干净上下文）
  │   返回：sprint contract + domain + assignee
  │
  ├─ 按 domain 路由：
  │   ├─ domain=client-ui → Agent tool → Gemini implementer subagent
  │   └─ domain=backend → Agent tool → Claude implementer subagent
  │   内部调用 simplify，维护 architecture.md
  │   返回：结构化 evidence 摘要
  │
  ├─ 按 domain 路由：
  │   ├─ domain=client-ui → Agent tool → Gemini evaluate subagent
  │   └─ domain=backend → Agent tool → Claude evaluate subagent
  │   返回：pass / fail + findings
  │
  │ 主 agent 只跟踪：哪些 feature done / pending / 当前结果
  │ 上下文增长缓慢（只有结构化摘要，不是完整对话）
  │ 跨域 task 通过 api_contracts.md 文件契约桥接
```

上下文重置靠 subagent 天然实现，无需外部机制。

### 10. 多模型路由与域内角色拆分

- Gemini 负责 UI 类 task（domain=client-ui）
- Claude 负责逻辑类 task（domain=backend / integration）
- Gemini CLI 的 `-p` 模式已验证支持 skill 触发（2026-05-16 实测通过）
- UI 验收由 Gemini 独立评估器 subagent 执行（截图 + 对照设计参考）
- 后端验收由 Claude evaluate 执行（API 测试 + 代码审查）

#### 域内角色拆分

implementer 和 evaluate 内部按 domain 分为两个子角色：

| 域 | implementer | evaluate |
|------|-------------|----------|
| client-ui | Gemini subagent | Gemini 独立评估器 subagent（自操作应用截图） |
| backend / integration | Claude subagent | Claude subagent（API 测试 + 代码审查） |

路由发生在 execute 层面：读取 Sprint Contract 的 domain + assignee，选择对应的 subagent。

#### 跨域通信：文件契约

所有 subagent 之间通过文件契约通信（读写 `.dev-flow/` 下的结构化文件），不依赖进程间直接对话。

混合任务（同时涉及 UI 和后端）的处理：
- **不需要拆分**，contract negotiate 协商时产出 api_contracts.md 条目
- UI subagent 读取 api_contracts.md → 按约定调用接口
- 后端 subagent 读取 api_contracts.md → 按约定实现接口
- 两边各自按契约独立实现和验收

规则：一个 task 只属于一个 domain，但可以通过 api_contracts.md 与其他域的 task 约定接口。

### 11. Simplify 的定位

- 内容不变
- 从"条件触发"变为 implementer 的必经内部调用
- fail 后统一回到 implement（不回到 simplify）

### 12. 评估器双模式支持

plan-review 和 evaluate 均支持两种运行模式，由 feature_list.json 的 workflow 配置决定：

| 评估器 | Claude 内部模式（local） | Codex Plugin 模式（codex_plugin） |
|--------|------------------------|-----------------------------------|
| plan-review | Agent tool → plan-review subagent | execute 触发 Codex plugin 调用 |
| evaluate | Agent tool → evaluate subagent | execute 触发 Codex plugin 调用 |

配置格式：
```json
{
  "workflow": {
    "plan_review_provider": "local" | "codex_plugin",
    "evaluate_provider": "local" | "codex_plugin"
  }
}
```

与现有 review_provider / audit_provider / risk_provider 机制一致，平滑过渡。

## 开放问题

1. evaluate 的评分阈值和少样本校准集
2. Gemini 路由的 skill 完整流程需要进一步测试
3. contract negotiate 的协商轮次上限（建议 2 轮）
4. Flutter 应用的截图自动化方案（evaluate 如何启动应用并截图）
5. 网页场景下 Playwright 截图 + 设计规范对照的具体实现

### plan-review 评估标准（初稿，待历史数据校准）

硬性条件（binary）：
- A1: 每个 feature 有 user_stories
- A2: 每个 feature 有 success_picture（1-2 句成功状态描述）
- A3: dependency 无循环
- A4: 不违反 architecture.md
- A5: 有依赖时说明理由

评分项（按阈值）：
- B1: 需求覆盖（阈值 4/5）— 原始需求每条用户行为是否被覆盖，失败路径、状态转换是否完整
- B2: 拆解粒度（阈值 3/5）— 每个 feature 是否是用户可感知的完整行为，有无太大该拆或太小该合并
- B3: 可验证性（阈值 3/5）— 成功画面是否具体到能转化为测试，边界场景是否覆盖
- B4: 依赖合理性（阈值 3/5）— 标注的依赖是否真实，能并行的是否被错误串行
- B5: 野心与可行性平衡（阈值 3/5）— 功能范围是否合理，有无过度设计或明显遗漏

校准方法：拿 R059（UI 密集型）和 R057（纯后端）跑评估，与用户判断对比，分歧处调优。

## 后续动作

- [ ] 用历史需求包校准 plan-review 评估标准
- [ ] 测试 Gemini skill 完整调用流程（含 UI 实现 + evaluate 截图验收）
- [ ] 设计 Flutter 截图自动化方案（evaluate subagent 如何操作应用）
- [ ] 进入 xlfoundry-plan 拆解第一步实现任务
