# R067 auth-dialog-reentry-fix 归档

- 归档时间: 2026-05-15
- 状态: completed
- 总任务: 2
- 分支: fix/R067-auth-dialog-reentry-fix
- workflow: A/skill_orchestrated
- providers: review=local, audit=local, risk=local

## 仓库提交

- remote-control: 07dc02b (HEAD on fix/R067-auth-dialog-reentry-fix)

## Phase 1 (F001-F002)

| 任务 | 描述 | commit |
|------|------|--------|
| F001 | 修复 auth 弹窗重入 bug | 9f8636a |
| F002 | auth 弹窗重入测试与 managed agent 泄漏修复 | 07dc02b |

## 关键交付

- 修复被踢和 token 过期后的认证弹窗重入，避免重复 modal barrier 导致闪烁和按钮失效。
- 将认证弹窗展示收敛为 post-frame 单实例调度，避免状态回调期间重复 showDialog。
- 修复桌面端 managed agent 关闭泄漏：退出时按当前 managed config 扫描并清理 orphan/重复 agent。
- Dart supervisor 与 macOS native 退出兜底均在 kill 前复核 PID 归属，避免误杀外部 agent 或 PID 复用目标。
- 产物已生成：macOS DMG 与 Android APK 均完成 release 构建。

## 验证

- flutter test test/services/desktop_agent_supervisor_test.dart
- flutter test test/services/desktop_termination_snapshot_service_test.dart
- flutter test test/services/auth_dialog_reentry_test.dart
- swiftc -parse client/macos/Runner/AppDelegate.swift
- ./build-desktop.sh
- flutter build apk --release
