# Review Handoff: remote-control 日志集成 + Docker 标准化

> 生成时间：2026-04-10T14:40:00+08:00
> 状态：等待外部 Codex 审核

---

## Workflow 配置

```json
{
  "name": "logging-integration",
  "mode": "B",
  "review_provider": "codex",
  "audit_provider": "codex",
  "risk_provider": "codex"
}
```

---

## feature_list.json 摘要

### 新增 Phase: logging-integration（7 个任务，全部 pending）

| ID | Module | Name | Priority | Verification | Risk Tags |
|----|--------|------|----------|-------------|-----------|
| B043 | server | Server 接入 log-service-sdk | high | L2 | config |
| B044 | server | Server 请求日志中间件 | high | L2 | - |
| B045 | server | 关键业务模块结构化日志 | medium | L2 | - |
| B046 | server | 转发 Client 日志到 log-service | high | L2 | network |
| B047 | agent | Agent 接入 log-service-sdk | high | L2 | config, network |
| S028 | shared | Docker 标准化部署 | high | L3 | network, first_use |
| S029 | shared | 端到端验证 | medium | L4 | network |

### 依赖图

```
B043 ──┬──→ B044 ──→ B045
       ├──→ B046 ──┐
       └───────────┼──→ S028 ──→ S029
B047 ─────────────┴───────────────↗
```

### 关键并行点
- B043 (Server SDK) 和 B047 (Agent SDK) 无依赖，可并行
- B044→B045 和 B046 之间无依赖，可并行

---

## 架构约束摘要

来源：`remote-control/.dev-flow/architecture.md`

### 日志拓扑（新增）
```
[Client Flutter] → POST /api/logs → [Server]
                                           ├── Redis 存储（已有）
                                           └── 转发到 log-service（新增）
[Server Python]  → log-service-sdk → http://log-service:8001
[Agent Python]   → log-service-sdk → http://log-service:8001
```

### 相关不变量
- #5: Server 是在线态唯一权威源
- #9: 终端数据流始终经过 Server 中转
- #17: Redis 不可用时 fail-closed

### 关键决策
- log-service-sdk 统一日志（一行接入，非阻塞批量上报）
- Client 日志经 Server 转发（不创建 Dart SDK）
- Docker 三网模式（gateway + infra-network + rc-network）

---

## 需要重点挑战的维度

### 1. 用户路径完整性

**路径 A：运维部署**
```
首次部署 remote-control → docker-compose.prod.yml → 加入 gateway + infra-network
→ deploy.sh 构建启动 → Traefik 路由生效 → log-service 连通
```
挑战点：S028 是否覆盖了从零开始的首次部署？已有 docker-compose.yml（开发用）的兼容性？

**路径 B：开发排查日志**
```
发现问题 → 打开 logs-ui → 按 service_name=remote-control 过滤
→ 按 component 区分 server/agent/client → 按 request_id 关联同一请求
```
挑战点：B044 的 RequestID 是否贯穿 WS 连接？（WS 不经过 HTTP 中间件，是否有 request_id？）

**路径 C：Agent 离线/弱网场景**
```
Agent 启动 → log-service 不可达 → SDK 静默重试 → Agent 正常运行
→ 网络恢复 → SDK 自动恢复上报
```
挑战点：Agent 长时间离线时队列是否会内存溢出？SDK batch_size=50 + flush_interval=2s 是否足够？

### 2. 任务缝隙

- B043→B046：Client 日志转发是否需要日志格式适配？（Client 上报的是 Redis 格式，log-service 需要的是 IngestLogEntry 格式）
- B047：Agent 的 `config.py` 是否需要新增 `log_service_url` 字段？还是纯环境变量？
- S028：Traefik 路由前缀 `/rc/` 是否需要与 Client 的 API base_url 协调？Client 当前硬编码的 server URL 是否需要改？
- B043 和 B047 的 SDK 依赖路径：local editable 还是 pip install？开发环境和生产环境如何统一？

### 3. 失败分支

- B046：log-service 转发失败时是静默丢弃还是本地缓存重试？
- S028：deploy.sh 失败时是否有回滚机制？
- B047：Agent 进程被 SIGKILL（非 SIGTERM）时 atexit 不触发，队列中的日志是否丢失？
- B043：Server 优雅关闭（docker stop）时 lifespan 是否确保 handler.close() 被调用？

### 4. 首用场景

- S028：全新服务器首次部署（无 gateway 网络、无 infra-network、无旧容器）
- B043：首次配置 LOG_SERVICE_URL（可能忘记配，默认 localhost:8001 在容器内不可达）
- B047：Agent 首次运行，没有 LOG_SERVICE_URL 环境变量

---

## 审核期望输出

```json
{
  "status": "pass | conditional_pass | fail",
  "findings": ["发现1", "发现2", ...],
  "required_changes": ["必须修改1", "必须修改2", ...],
  "reviewed_at": "ISO8601 timestamp"
}
```

- `status=pass`：无需修改，可进入执行
- `status=conditional_pass`：有建议但非阻塞
- `status=fail`：有阻塞问题，必须修改后重新审核
