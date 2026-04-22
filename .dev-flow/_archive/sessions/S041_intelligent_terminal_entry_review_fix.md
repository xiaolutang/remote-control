# Session S041: 智能终端进入规划复审修正

> 日期：2026-04-22
> 状态：已规划修正，待复审

## 来源

`S040` 的本地 plan review 给出 3 个阻塞问题：

1. 未定义“如何真正直接进入 Claude/Codex”的执行语义
2. “最近工具/最近计划”缺少权威数据源设计
3. `F078/F079/F080` 的高风险测试设计偏 happy path，未覆盖失败/空数据/边界

## 本轮修正

### 1. 补齐直接进入工具的执行语义

在 `CONTRACT-043` 中新增：

- `entry_strategy`
- `post_create_input`

并明确：

- `claude_code` / `codex` 默认使用 `shell_bootstrap`
- v1 为保持 Server/Agent 创建契约不变，先创建 shell，再由 Client 在 terminal 连接成功后自动发送 `claude\n` / `codex\n`
- `shell` 使用 `direct_exec`

### 2. 补齐最近工具的权威数据源

新增 `RecentLaunchContext`：

- 属于 Client 本地持久化
- 记录 `last_tool / last_cwd / last_successful_plan`
- 不依赖 runtime terminal metadata 或标题/命令字符串反推

### 3. 重写高风险测试重点

为 `F078/F079/F080` 补齐：

- 空缓存 / 损坏缓存 / 未知 tool 回退
- 超长输入 / 特殊字符 / 模糊路径线索
- `offline / terminal 上限 / server 5xx`
- `requires_manual_confirmation`
- bootstrap 命令不存在时的可见失败与 shell 保留

## 结论

本轮修正后，规划已补齐：

- 主目标“直接进入 Claude/Codex”的可执行语义
- 推荐服务依赖的数据源真相
- 高风险任务的失败/空数据/边界测试设计
