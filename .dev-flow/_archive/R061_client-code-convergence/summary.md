# R061 client-code-convergence 归档

- 归档时间: 2026-05-12
- 状态: completed
- 总任务: 16
- 分支: chore/R061-client-convergence
- workflow: mode=B | runtime=skill_orchestrated | review_provider=codex_plugin | audit_provider=codex_plugin
- providers: codex_plugin/codex_plugin/codex_plugin

## 仓库提交
- remote-control: d44ec39 (HEAD on chore/R061-client-convergence)

## Phase 1 (navigation + widgets + models + services 迁移)
| 任务 | 描述 | commit |
|------|------|--------|
| F001 | 迁移 account_menu_action_handler 到 navigation 层 | f978a94 |
| F002 | 迁移 showThemePickerSheet 到 widgets 层 | 528c593 |
| F003 | 迁移 models/ 中 IconData 到 widgets 层 extension | 1344fb5 |
| F004 | 去除 logout_helper/env_switch_coordinator BuildContext 依赖 | 3e92032 |

## Phase 2 (类型收敛)
| 任务 | 描述 | commit |
|------|------|--------|
| F005 | 字符串分派收敛为 enum | 447cf4b |
| F006 | 清理 @Deprecated AgentTraceEvent + AgentAssistantMessageEvent | 0263c6d |

## Phase 3 (性能 + 服务层收敛)
| 任务 | 描述 | commit |
|------|------|--------|
| F007 | SharedPreferences 缓存层 | 538d1c8 |
| F008 | 修复 RuntimeSelectionController 双重 notifyListeners | 28d7bce |
| F009a | 并行化 selectDevice 中独立网络请求 | ea7b6b0 |
| F009b | 并行化 _refreshDesktopState | ea7b6b0 |
| F010 | DesktopWorkspaceController dispose + 状态缓存 | 05140e0 |
| F011 | LoggerService notifyListeners 节流 | 3be60e4 |

## Phase 4 (组件提取)
| 任务 | 描述 | commit |
|------|------|--------|
| F012 | 提取重命名对话框 + SnackBar helper | 3c13dc1 |
| F013 | 提取设计 token 到 design_tokens.dart | 8500c0d |

## Phase 5 (大文件拆分)
| 任务 | 描述 | commit |
|------|------|--------|
| F014 | 拆分 smart_terminal_side_panel 组合体 | 5e85644 |
| F015 | 拆分 terminal_workspace_screen | 15e40de |

## 收敛修复（code-review 驱动）
| commit | 描述 |
|--------|------|
| 5674429 | isPrivateIp 纯函数提取，测试环境隔离 |
| 31b49e1 | Codex review 三轮修复 |
| 4464216 | Codex review 二轮修复 |
| ad004c4 | Codex review 修复 — trim/缓存/集成测试 |
| b99a24b | 修复 3 个预存测试失败 |
| d7d57ed | 系统性防御性 JSON 解析 — 终版 |
| 74e1217 | 系统性防御性 JSON 解析 |
| 785c35c | 系统性防御化 JSON 反序列化 — 全量 raw cast 消除 |
| d44ec39 | 零值 round-trip + 容器级 cast 消除 + 回归测试 |

## 关键交付
- 全量 raw cast 消除：~140 处 `as Type?` 替换为类型安全的 json_helpers + is Type 守卫
- 零值 round-trip 修复：maxRetries=0、Duration.zero 不再被误替换为默认值
- enum 收敛：AgentResponseType / FeedbackType / ToolStepStatus 替代字符串分派
- 服务层解耦：去除 4 个文件的 BuildContext 依赖，SharedPreferences 缓存层，notifyListeners 节流
- 组件提取：设计 token、重命名对话框、SnackBar helper 独立复用
- 大文件拆分：smart_terminal_side_panel 3570→拆分后主文件 ~1500 行，terminal_workspace_screen 1100→600 行
