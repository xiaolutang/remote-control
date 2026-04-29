# R049 brainstorm-bug-fixes 归档

- 归档时间: 2026-04-29
- 状态: completed
- 总任务: 3
- 分支: fix/R049-brainstorm-bug-fixes
- workflow: B / skill_orchestrated
- providers: review=codex_plugin, audit=codex_plugin, risk=codex_plugin

## 仓库提交

- remote-control: 81497e0 (HEAD on main)

## Phase 1

| 任务 | 描述 | commit |
|------|------|--------|
| S049 | Fix tool registration name parameter | a498056 |
| F050 | Fix terminal injection truncation with Bracketed Paste Mode | 9414c9e |
| F051 | Fix command and prompt display truncation in chat panel | 95cd417 |

## 关键交付

- Server 内置工具注册显式声明 `name`，修复 LLM 可见工具名错误。
- Client 聊天面板去除命令与 prompt 的 3 行截断，内容可完整查看。
- 终端 prompt 注入链路完成可靠性加固，补齐 Bracketed Paste、可写态检查、PTY 非阻塞重试写入。
- 增加远程 runtime terminal 输入探针，可自动校验生产环境终端输入链路是否真实可用。
