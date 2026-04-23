# S001: ReAct 智能体架构设计

> 日期：2026-04-23
> 状态：已完成

## 讨论内容

从无状态 planner 升级为 ReAct 智能体的架构设计和规划。

### 核心决策

1. **框架选型**：Pydantic AI — 模型无关（兼容 Dashscope/MiniMax）、类型安全、轻量
2. **Agent 模式**：ReAct（Think → Act → Observe）循环
3. **工具设计**：
   - `execute_command`：只读命令，白名单 + shell 元字符拦截 + 敏感路径过滤
   - `ask_user`：选项 + 自由输入混合模式，SSE 推送 + HTTP 回调
4. **记忆设计**：
   - 全局持久：项目别名（SQLite，跨终端跨会话）
   - 终端级：对话历史（内存）
   - 临时：探索过程（不存储）
5. **手机端策略**：保持现有无状态 planner 不变，Agent 仅桌面端侧滑面板
6. **降级策略**：ReAct Agent → 无状态 planner → local_rules

### 审核历史

| 轮次 | 审核方 | 状态 | 关键发现 |
|------|--------|------|---------|
| 1 | 本地 | conditional_pass | 手机端缺失、F088 替代、WS 协议未独立 |
| 2 | 本地 | conditional_pass | 依赖管理、转换逻辑、断连恢复 |
| 3 | 本地 | pass | 0 个问题 |
| 4 | Codex Plugin | fail | 黑名单不安全（→ 改白名单）、契约缺失、测试不足 |
| 5 | 本地 | conditional_pass | 命令替换/解释器/元字符绕过 |
| 6 | 本地 | conditional_pass | SSH 路径、find 子串匹配 |
| 7 | 本地 | pass | 0 个问题 |

### 安全模型最终方案

白名单 + shell 元字符拦截 + 敏感路径过滤三重防护，27 个攻击向量全部被拦截。

### 产出文件

- `.dev-flow/feature_list.json` — R041 活跃，10 个新任务
- `.dev-flow/architecture.md` — 不变量 #47/#54 更新，权威边界新增
