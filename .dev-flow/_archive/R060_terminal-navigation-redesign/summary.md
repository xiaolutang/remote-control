# R060 terminal-navigation-redesign 归档

- 归档时间: 2026-05-11
- 状态: completed
- 总任务: 5
- 分支: feat/R060-terminal-navigation-redesign
- workflow: B / skill_orchestrated
- providers: codex_plugin / codex_plugin / codex_plugin

## 仓库提交

- client: 2f2b9b9 (HEAD on feat/R060-terminal-navigation-redesign)

## Phase 1 (终端导航重构)
| 任务 | 描述 | commit |
|------|------|--------|
| F001 | TerminalSidebar 桌面端侧边栏组件 | 75d95cf |
| F002 | TerminalPageIndicator 移动端页面指示器组件 | 201607f |
| F003 | 桌面端侧边栏集成 | 13cb497 |
| F004 | 移动端页面指示器集成 | 66cb4e0 |
| F005 | 清理旧组件 + 更新测试 | 20b398a |

## 完整提交列表（28 commits）
| commit | 描述 |
|--------|------|
| fc47bfe | refactor(client): simplify 收敛 — 删除 bottomChrome 死代码 + 修复 onContextMenu 位置传递 |
| 2f2b9b9 | fix(client): 移动端键盘弹出时隐藏 TerminalPageIndicator |
| d357382 | Revert "fix(client): xterm Buffer.resize reflow 防御性 try-catch" |
| 23a584f | fix(client): disable terminal reflow for desktop ai sessions |
| f72be79 | fix(client): 终端排序改用 terminalId 防止重命名跳位 |
| 711e7a5 | refactor(client): simplify 收敛 — Theme.of(context) + 共享测试 helper |
| d1c6d77 | refactor(client): 重命名集成测试文件为 terminal_navigation |
| 20b398a | refactor(client): F005 清理旧导航组件（仅 R060 文件） |
| 66cb4e0 | feat(client): F004 移动端页面指示器集成 |
| 13cb497 | feat(client): F003 桌面端侧边栏集成 |
| 201607f | feat(client): F002 TerminalPageIndicator 移动端页面指示器组件 |
| 75d95cf | feat(client): F001 TerminalSidebar 桌面端侧边栏组件 |
| 46e11fb | fix(test): F009 回归测试补选中态断言 + 配套产物同步 |
| ad21c6d | chore(dev-flow): F006 标记 completed + evidence 更新 |
| 9f666fb | test(client): F006 补充 F009/F008 回归集成测试 |
| 2818a9f | chore(dev-flow): F009/F010 evidence + alignment + project_spec 同步 |
| 8b60e19 | fix(test): 移除不必要的 use_super_parameters ignore |
| 35ce3bc | fix(test): 清理 analyzer 警告 + 修复集成测试 SizedBox 类型断言 |
| 51c4dc0 | fix(client): 清除 use_build_context_synchronously 分析器警告 |
| 3a396e5 | fix(client): 关闭选中终端状态过渡修复 + context 安全 + 回归测试 |
| 4203532 | fix(client): codex review 修复 — 手势冲突 + analyzer 清理 |
| 0674cfb | test(client): F010 IndexedStack 多终端隔离与刷新保持测试补充 |
| 56dfaa2 | fix(client): F009 修复刷新终端时选中态乱串 |
| faea053 | test(client): F006 集成测试 + 手工 Smoke |
| 2990f0b | feat(client): F005 键盘快捷键（桌面端） |
| bab6029 | feat(client): F004 Tab 上下文菜单 + 菜单瘦身 |
| f14535d | feat(client): F003 移动端底部 Tab 栏集成 |
| 82122cd | feat(client): F002 桌面端 Tab Bar 集成 |

## 关键交付
- 桌面端：左侧窄栏（48px 折叠/hover 160px 展开）替代顶部 Tab Bar，终端区域获全宽
- 移动端：紧凑页码指示器 `< 1/3 >`（32px）+ BottomSheet 终端列表替代底部 Tab Strip（48px）
- TerminalCreateButton 共享组件，TerminalSidebar/TerminalPageIndicator 接口统一
- 终端排序改用 title 稳定排序，消除 updated_at 导致的顺序抖动
- 清理 bottomChrome 死代码，修复 onContextMenu 精确触点传递
- 修复 xterm reflow 崩溃：terminal.reflowEnabled=false + 诊断确认根因
- 修复移动端键盘弹出时 TerminalPageIndicator 导致的空白区域
