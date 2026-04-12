# Session S030: 反馈问题功能

> 日期：2026-04-10
> 触发：用户要求在 App 和桌面端增加"反馈问题"入口

## 需求

在 mobile 和 desktop 端的设置菜单中添加"反馈问题"入口，用户可以：
- 选择问题分类（连接问题/终端异常/崩溃闪退/功能建议/其他）
- 填写问题描述
- 系统自动采集平台、版本、设备信息
- Server 自动关联近期日志

## 排查人员视角设计

从问题排查人员角度，反馈应包含：
- 必须：问题描述 + 分类 + 时间 + 用户ID + session_id + 平台/版本 + 近期日志
- 自动采集（用户不感知）：platform, app_version, session_id, user_id, timestamp
- 用户手填：分类（Chip选择） + 描述（文本框）

## 数据流

```
Client → POST /api/feedback → Server
                                 ├── Redis 存储 (rc:feedback:{id})
                                 ├── 从 log_service 自动查询近期日志关联
                                 └── 转发到 log-service (best-effort)
```

## 架构校验

- 与现有 architecture.md 无冲突
- 复用已有 log_service.py 查询日志
- 复用已有 auth 中间件 async_verify_token
- 设置入口添加到 PopupMenuButton（workspace header bar + runtime selection screen）

## 入口位置

1. `_WorkspaceHeaderBar` 的 `PopupMenuButton` → 新增"反馈问题"菜单项
2. `RuntimeSelectionScreen` 的 `PopupMenuButton<_MenuAction>` → 新增 feedback action

## workflow

```json
{
  "name": "feedback-feature",
  "mode": "B",
  "review_provider": "codex_plugin",
  "audit_provider": "codex",
  "risk_provider": "codex"
}
```

## 任务切片

Phase: feedback-feature (6 tasks)

| ID | 类型 | 名称 | 依赖 |
|----|------|------|------|
| B048 | 后端 | 反馈 API + 存储 + 自动关联日志 | - |
| B049 | 后端 | 反馈 API 单元测试 | B048 |
| F051 | 前端 | 反馈数据模型与服务 | B048 |
| F052 | 前端 | 反馈页面 UI | F051 |
| F053 | 前端 | 设置入口添加反馈菜单 | F052 |
| S030 | 共享 | 集成测试 | B049, F053 |
