# Defect Feedback

## Defect — R067 auth 弹窗仍有短暂闪烁

- issue_id: R067-D1
- source: real_use
- related_task: F001
- symptom: 修复后不再稳定黑屏，但被踢/token 过期路径仍会闪烁几下，随后背景变为透明且稳定
- escape_path: F001 主要锁定 controller teardown 期间 `_authDialogShowing` 守卫，未覆盖 UI 层同步 `showDialog` 在多次 `notifyListeners` / rebuild / route 插入动画之间的重复调度风险
- fix_level: L2
- root_cause_summary: UI 层直接在 controller listener 中同步调用 `showDialog`，当认证事件和连接状态通知在同一轮 UI 更新内密集到达时，overlay route 可能出现短时间重复插入/动画抖动
- upstream_actions:
  - 将 auth dialog 展示改为 post-frame 单次调度
  - 增加 `_authDialogScheduled` 与 `_authDialogMounted` 双守卫，dialog Future 完成后统一复位 UI 守卫
  - 保留 controller teardown 后 `clearAuthDialog()` 的根因修复
- rules_to_update:
  - 建议认证/导航类 UI 测试补充 widget 层 route/overlay 单实例断言
- owner: client
- status: fixed_pending_review

---

## Defect 1: 刷新终端时选中态乱串

- issue_id: F009
- source: real_use
- related_task: F008
- symptom: 用户点击刷新按钮后，当前选中的终端切换到其他终端
- escape_path: 现有测试使用 _FakeWorkspaceController，其 selectedTerminal 直接返回 _findTerminal 结果，不经过 _resolveSelectedTerminalId 副作用逻辑。真实 DesktopWorkspaceController.selectedTerminal getter 每次调用都会修改 _selectedTerminalId，在 loadDevices 异步替换 terminals 期间可能回退到第一个终端。
- fix_level: L2
- root_cause_summary: selectedTerminal getter 违反 getter 无副作用原则，_resolveSelectedTerminalId 在 terminals 列表被异步替换时可能因找不到当前 ID 而回退到第一个终端。状态管理分散：_selectedTerminalId 的解析散落在 getter 中而非数据变更点。
- upstream_actions:
  - 修复 F009：将 selectedTerminal getter 改为纯读取，数据变更点显式调用 _resolveSelectedTerminalId
  - 补充 F010 测试：刷新保持、loading 共存、Provider 隔离
- rules_to_update:
  - 建议在 architecture.md 不变量中追加：getter 不得修改内部状态
  - 建议测试模板增加：controller 状态管理测试必须覆盖异步数据替换场景
- owner: client
- status: open

## Defect 2: 多终端 IndexedStack 测试覆盖不足

- issue_id: F010
- source: audit
- related_task: F008
- symptom: 缺少 3 类关键测试场景：刷新保持、多终端输出隔离、loading 与 IndexedStack 共存
- escape_path: F008 实现了 IndexedStack 缓存机制，代码审查和调查确认隔离设计正确（Provider 作用域 + 独立 WebSocketService + 独立 StreamController），但没有自动化测试保障回归
- fix_level: L1
- root_cause_summary: F008 只添加了 IndexedStack 功能测试，未覆盖刷新时选中态保持和多终端隔离的边界条件
- upstream_actions:
  - 补充 F010 测试用例
- rules_to_update:
  - 建议测试模板增加：状态缓存类功能（IndexedStack/PageView 等）必须测试刷新/重载场景
- owner: client
- status: open

---

## Defect 3: SSE conversation/stream busy-loop 导致 CPU 持续高占用

- issue_id: OPS-001
- source: real_use
- detected_at: 2026-05-17
- related_task: N/A（独立运维问题，非特定 feature 任务产生）
- risk_tags: network, performance, startup

### 现象

远程服务器（4C/4G 腾讯云，IP: 111.229.125.161）CPU 持续 30-40%，rc-server 容器单进程 CPU 占用 89%。同时服务器内存 3.6G 已用 2G，Swap 已用 1.15G，可用物理内存仅 ~240M，导致 SSE 连接在内存压力下频繁断连。

### 根因分析

`server/app/api/agent_api.py` 第 88-158 行的 `_event_stream()` 生成器存在 busy-loop 问题：

```python
async def _event_stream():
    while True:
        if await http_request.is_disconnected():
            break

        # ❌ 每轮循环都执行完整数据库查询链
        projection = await _build_agent_conversation_projection(
            user_id=user_id, device_id=device_id, terminal_id=terminal_id,
            after_index=last_index,
        )

        if projection.events:
            for event in projection.events:
                last_index = max(last_index, event.event_index)
                yield "event: conversation_event\ndata: ...\n\n"
            continue  # 有事件时立即进入下一轮

        # 没有新事件时等待 Queue（最多 1 秒）
        try:
            event = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            yield ": keepalive\n\n"
            continue  # ← 1秒后回到 while True 顶部，再次查数据库
```

三个问题叠加：

1. **每秒查一次数据库**：即使完全没有新事件，也在不停地 SELECT（conversations + events + feedback_status），每轮循环涉及 2-3 次 SQLite 查询 + 1 次 Redis 查询 + 内存遍历
2. **TTL 缓存被绕过**：`_build_agent_conversation_projection` 的 500ms TTL 缓存只在 `after_index=None`（全量查询）时生效。stream 端点传了 `after_index=last_index`，缓存无效，每次直接打数据库
3. **多终端放大**：每个打开的 terminal 面板都维持一个 SSE 连接，N 个终端 = N 倍消耗

### 关键文件

| 文件 | 作用 |
|------|------|
| `server/app/api/agent_api.py` (77-164行) | conversation stream SSE 端点 — CPU 消耗主因 |
| `server/app/api/agent_conversation_helpers.py` | `_build_agent_conversation_projection` 投影构建 + TTL 缓存 |
| `server/app/store/conversation_store.py` (179-219行) | `list_agent_conversation_events` SQLite 查询 |
| `server/app/infra/event_bus.py` | 进程内事件总线 + Queue 订阅机制 |

### 修复建议

**核心改动**：先等 Queue 通知，收到事件后再查数据库推送，而非每轮无脑查。Queue 里已有完整事件，当前代码却忽略它每次去数据库重查。

```python
# 建议改为：
while True:
    # 先等 Queue 通知（适当超时，如 30 秒）
    try:
        event = await asyncio.wait_for(queue.get(), timeout=30.0)
    except asyncio.TimeoutError:
        yield ": keepalive\n\n"
        continue
    # 收到事件后直接从 Queue 事件推送，无需再查数据库
    yield "event: conversation_event\ndata: ...\n\n"
```

**次要优化**：
- keepalive 间隔从 1 秒延长到 15-30 秒（SSE 标准推荐值）
- 让 TTL 缓存对 `after_index` 路径也生效
- 考虑用现有 WebSocket 通道替代独立 SSE 连接，减少连接数

### 服务器现场数据（2026-05-17 13:22 CST）

```
CPU: rc-server 89.15%, 总体 39%
内存: 3659M total, 2077M used, Swap 1151M used
容器: ragdemo 503M, rc-redis 470M, rc-server 215M, neo4j 94M, traefik 81M, qdrant 10M, new-api 33M
Docker: 7 容器运行中
磁盘: 40G 用了 20G (51%)，当天已清理 ~10G 悬空镜像
```

- fix_level: L2
- root_cause_summary: SSE stream 端点的 `_event_stream()` 采用 busy-loop 模式，每轮都查数据库 + 1秒 keepalive，伪装成 SSE 实质是 1 秒轮询。TTL 缓存因 after_index 参数被完全绕过。Queue 订阅机制已就绪但未被有效利用。
- upstream_actions:
  - 重构 `_event_stream()` 为事件驱动模式：等 Queue → 推送，而非轮询数据库
  - TTL 缓存扩展到 after_index 路径
  - keepalive 间隔调至 15-30 秒
- rules_to_update:
  - 建议在测试目录中增加：SSE/stream 端点必须有空闲时的 CPU/数据库查询频率测试
  - 建议在 architecture.md 中追加：SSE 端点不得使用 busy-loop + 数据库轮询模式，必须基于事件通知
- owner: server
- status: fixed

- issue_id: OPS-002
- source: real_use
- detected_at: 2026-05-17
- related_task: N/A（与 OPS-001 关联，SSE 断连 + 重连机制共同导致）
- risk_tags: network, first_use, startup

### 现象

用户在使用 remote-control 桌面端时，客户端报错：

```
ClientException with SocketConnection failed (OS Error: Too many open files, errno = 24),
address = 111.229.125.161, port = 8880,
uri=http://111.229.125.161:8880/api/runtime/devices
```

此时用户正在使用 2/10 terminals，Agent 处于托管中状态。

### 根因分析

1. 服务端因 OPS-001 的内存压力导致 SSE 连接频繁断开（日志中出现 `connection closed`）
2. 客户端 `agent_session_service.dart` 的 `streamConversationResilient` 包装层自动重连（指数退避：2s → 4s → 8s → 16s → 32s，最多 5 次）
3. 重连时旧 SSE 连接未完全释放（HTTP 连接未正确 close），新旧连接叠加
4. 每个 terminal 面板都维持独立的 SSE 连接（`streamConversation`），加上重连产生的新连接，文件描述符持续增长
5. 最终撑爆客户端进程的 fd 限制，导致所有网络请求失败

### 关键文件

| 文件 | 作用 |
|------|------|
| `client/lib/services/agent_session_service.dart` (72-201行) | SSE 客户端 + `streamConversationResilient` 自动重连 |
| `client/lib/widgets/agent_panel_handlers.dart` (57行) | 面板 SSE 流管理，`_loadConversationProjection` |

### 修复建议

1. **重连前确保旧连接完全关闭**：在 `streamConversationResilient` 重连逻辑中，先 cancel/abort 上一个 HTTP 请求
2. **连接生命周期与 Widget 绑定**：确保 panel dispose 时彻底关闭 SSE 连接，而不仅是取消订阅
3. **连接数监控**：在客户端增加活跃 SSE 连接数日志，超过阈值时告警
4. **配合 OPS-001 修复**：服务端空闲时不再每秒发送 keepalive，内存压力降低后断连频率会大幅下降

### 服务端现场数据（确认服务端 fd 正常）

```
rc-server 进程: 14 个 fd, 6 个 TCP 连接（established）
系统 fd: 2016 used / unlimited total
docker fd limit: 1048576
```

问题确认为客户端侧 fd 泄漏，服务端连接数正常。

- fix_level: L2
- root_cause_summary: SSE 重连机制未确保旧连接完全释放，在高频断连场景下（由 OPS-001 的内存压力触发），新旧连接叠加导致客户端进程 fd 耗尽。服务端连接数正常（6 个），问题在客户端侧。
- upstream_actions:
  - 重构 SSE 重连逻辑：重连前先 abort 旧连接，确保 fd 释放
  - 面板 dispose 时彻底关闭 SSE 连接
  - 增加客户端 SSE 连接数监控日志
  - 配合 OPS-001 修复以降低断连频率
- rules_to_update:
  - 建议在测试目录中增加：SSE/WebSocket 重连场景必须验证旧连接是否完全释放
  - 建议在 architecture.md 中追加：长连接重连前必须显式关闭旧连接
- owner: client
- status: fixed

### Review #1 (2026-05-11)

- review_provider: codex_plugin
- review_status: conditional_pass
- reviewed_at: 2026-05-10T18:57:05+0800
- required_changes:
  1. F009 与决策记录冲突 → 已更新决策记录
  2. 关闭最后 Tab → 空状态 → 再次创建路径 → 已补充到 F009 acceptance_criteria
  3. F006 network/startup 失败分支不足 → 已补充 5xx/超时测试
  4. F006 移动端执行环境不清晰 → 已补充环境说明
