# Session S025: 日志模块接入 + Docker 标准化部署

> 日期：2026-04-10
> 状态：规划中

## 需求来源

用户提出：remote-control 基本功能开发完成，需要接入日志模块方便后续排查问题。

## 需求澄清记录

### Q1: 接入范围
- **结论**：Server + Agent + Client 三端
- **架构模式**：后端统一接入 log-service，客户端对接自己的后端
  - Client (Flutter) → Server POST /api/logs → Redis（已有）+ 转发到 log-service（新增）
  - Server (Python) → log-service-sdk 直接上报
  - Agent (Python) → log-service-sdk 直接上报

### Q2: 中间件
- **结论**：Server 加请求日志中间件（RequestID + RequestLogging + ErrorHandler），Agent 不需要
- 参考 PGA 的 `personal-growth-assistant/backend/app/middleware/__init__.py`

### Q3: Docker 部署
- **结论**：日志接入 + Docker 标准化一起做
- 创建 docker-compose.prod.yml，加入 gateway + infra-network + rc-network 三网模式
- 配置 LOG_SERVICE_URL=http://log-service:8001
- 参考 PGA `docker-compose.prod.yml` 三网模式

### Q4: Flutter Client
- **结论**：Client 也接入 log-service，但通过 Server 转发，不改 Client 代码

### Q5: Workflow 模式
- **结论**：XLFoundry-B（codex/codex/codex）

## 关键参考

- PGA 日志接入：`personal-growth-assistant/backend/app/main.py`
- Python SDK README：`log-service/sdks/python/README.md`
- log-service API：`POST /api/logs/ingest`
- Docker 三网模式：PGA `docker-compose.prod.yml` 为标准范例

## 技术决策

1. 使用 `log-service-sdk` Python SDK，不自己造轮子
2. Server lifespan 中调用 `setup_remote_logging()` 一行接入
3. Agent 在 CLI run 命令中初始化，离线时 SDK 静默重试不影响运行
4. Client 日志通过 Server 转发，不创建 Dart SDK
5. Docker 标准化参考 PGA 三网模式
6. Server 中间件参考 PGA 实现（RequestID + RequestLogging + ErrorHandler）

## 架构影响

- remote-control 需加入 `infra-network` 外部网络
- `architecture.md` 新增：日志上报路径拓扑、log-service 连接不变量
- `project_spec.md` 扩展范围包含日志接入和 Docker 标准化

## Review 状态

- **review_provider**: codex
- **review_status**: fail → 修复中 → 等待重新审核
- **review_provider**: codex_plugin
- **reviewed_at**: 2026-04-10T08:22:48Z
- **required_changes**:
  1. B046 绕过 SDK 路径（架构冲突）→ 已修复：architecture.md 明确区分路径 A（SDK）和路径 B（httpx 代理转发）
  2. B044 中间件可能吞掉认证错误语义 → 已修复：补充 auth 错误透传验收条件和测试
  3. Agent 日志配置路径缺失（Desktop 无法访问 Docker 网络）→ 已修复：B047 补充 Desktop Agent 无 LOG_SERVICE_URL 时仅本地日志
  4. 配套产物未更新 → 已修复：api_contracts.md、test_coverage.md、alignment_checklist.md 补充日志集成条目

### Codex Plugin 审核记录

第一次审核（2026-04-10T15:54+08:00）：审核了错误的计划文件（根目录 Docker 标准化 B01-B07），未审核 remote-control 日志集成任务。
第二次审核（2026-04-10T16:09+08:00）：同样审核了错误的计划文件。
第三次审核（2026-04-10T08:22:48Z）：通过显式路径成功审核了 remote-control 日志集成计划（B043-B047, S028-S029），结果 fail，发现 4 个问题。

### 前置本地审核（已作废，仅供参考）

本地 subagent 做了初步审核，结果 conditional_pass，发现 2 个问题已修复：
1. B044 test_tasks 与 acceptance_criteria 矛盾（/health 路径跳过日志 vs 期望产生日志）
2. B044 健康检查路径应为 /health（非 /api/health）

但这不是正式审核结果，正式审核需等待 codex 外部审核回流。
