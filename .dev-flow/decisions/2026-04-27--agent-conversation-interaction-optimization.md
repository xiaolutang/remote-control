---
date: 2026-04-27
type: tech_selection
status: decided
requirement_cycle: R047
architecture_impact: true
supersedes: null
---

# 智能体对话交互优化

## 背景

R046 完成了 Agent 自由对话 + deliver_result 工具交付模式，eval 100% 通过。但对话交互体验存在明显痛点：

1. **无流式输出**：assistant_message 在模型完整输出后才推送，用户看到突然出现大段文字
2. **工具探索粗糙**：trace 事件堆在可折叠列表，用户难以理解 Agent 在做什么
3. **状态粒度太粗**：exploring 同时涵盖 thinking / tool_calling / generating 三种阶段
4. **多轮对话节奏弱**：历史 turn 归档后扁平列表，缺乏对话节奏感
5. **已知 Bug**：AI 生成内容发送到终端时可能截断

## 方案对比

### 方案 A: 渐进增强

- 思路：保持现有 SSE 事件模型，修改推送时机和丰富事件数据
- 优势：改动面小，可逐层交付
- 劣势：trace 事件结构性缺陷无法修补，面板状态膨胀难以维护
- 适用条件：快速修补，风险最低

### 方案 B: 阶段驱动交互模型（已选择）

- 思路：引入显式 Phase 概念，重新设计事件模型和面板状态机
- 优势：用户感知清晰（6 阶段），事件模型干净（5 种），Client 状态机重写更清晰
- 劣势：Server + Client 两端核心文件都需改动
- 适用条件：项目未上线，允许一步到位

### 方案 C: 端到端流式重构

- 思路：所有输出都流式，命令执行实时推送，ai_prompt 流式预览
- 优势：体验最佳
- 劣势：工程量最大
- 适用条件：已上线产品需要极致体验时

## 决策

- 选择：方案 B — 阶段驱动交互模型
- 理由：高收益 + 可控风险，phase 概念直觉可理解，项目未上线允许一步到位
- 前提条件：项目未上线，无需向后兼容
- 风险：Server + Client 两端核心改动，需要充分测试

### 子决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| Phase 检测 | Server 自动推断 | 基于 Pydantic AI 事件类型推断，Client 只渲染 |
| 流式粒度 | Token 级 | 实时感最强，SSE 帧数可接受 |
| 迁移策略 | 一步切换 | 项目未上线，无需兼容旧协议 |

## 架构影响

### 新事件模型（替换旧模型）

| 事件 | 替代 | 数据 |
|------|------|------|
| `phase_change` | 新增 | `{phase, description}` |
| `streaming_text` | `assistant_message` | `{text_delta}` |
| `tool_step` | `trace` × 2 | `{tool_name, description, status, result_summary}` |
| `question` | 保留 | 不变 |
| `result` | 保留 | 不变 |
| `error` | 保留 | 不变 |

### 6 个交互阶段

```
THINKING → EXPLORING → ANALYZING → (循环) → RESPONDING → CONFIRMING/RESULT
```

### 涉及文件

- `server/app/agent_session_manager.py` — 新事件类型 + phase 追踪 + streaming_text token 级 emit
- `server/app/terminal_agent.py` — 工具定义增加 description 字段
- `server/app/runtime_api.py` — SSE 端点适配
- `client/lib/models/agent_session_event.dart` — 新 sealed class 子类
- `client/lib/services/agent_session_service.dart` — SSE 解析适配
- `client/lib/widgets/smart_terminal_side_panel_content.dart` — 重写 phase-driven 状态机

## 开放问题

- 命令内容截断 bug 的根因待排查
- Token 级流式推送的性能影响需实测（可能需要 chunk 合并缓冲）

## 后续动作

- 进入 xlfoundry-plan 拆解任务
