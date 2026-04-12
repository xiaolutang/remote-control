# Session S024: 同端设备在线数限制

> 时间：2026-04-09
> 类型：feature
> 状态：规划完成，待执行

## 用户需求

同一个用户按客户端类型分类，移动端只能有一个设备在线，桌面端也只能有一个设备在线。

## 澄清过程

### Q1: 「设备在线」的具体含义？

> A: Client WebSocket 连接就算设备在线。移动端 Client WS 连接也算「移动端设备在线」。同用户同时只能有 1 个手机 + 1 个桌面 Client 连着。

### Q2: 同端新设备上线时对旧设备的处理？

> A: 通知用户选择。新设备上线时通知两端，由用户在旧设备上确认「让位」或在新设备上等待。

## 需求总结

| 场景 | 行为 |
|------|------|
| **无冲突** | 新 Client 正常连接 |
| **同端冲突 + 用户让位** | 旧设备断开，新设备连接成功 |
| **同端冲突 + 用户拒绝** | 新设备收到「旧设备拒绝让位」，旧设备保持在线 |
| **同端冲突 + 超时（15s）** | 默认新设备优先，旧设备被断开 |
| **旧设备掉线** | 新设备直接连接 |
| **跨端（mobile + desktop）** | 允许同时在线 |

## 冲突解决协议

```
新 Client 连接 → Server 检测同端冲突
  ├─ 无冲突 → 正常连接
  └─ 有冲突 → Server 发 device_conflict 给旧 Client
       ├─ 旧 Client 弹窗让用户选择
       │    ├─ 让位 → Server 断开旧 Client，接受新 Client
       │    └─ 拒绝 → Server 拒绝新 Client（code=4010）
       └─ 超时 15s → 默认新设备优先，断开旧 Client
```

## 涉及组件

- `ws_client.py` — Client 连接管理，冲突检测与解决
- `client/lib/services/` — WS 消息处理
- `client/lib/screens/` — 冲突通知 UI、被踢下线 UI

## 架构约束检查

1. ✅ 不变量 5：Server 是在线态唯一权威源 → 冲突判断由 Server 决定
2. ✅ 不变量 10：移动端后台断开 WebSocket → 兼容，后台断开自然释放名额
3. ✅ 新增不变量：同用户同端同时只允许一个 Client WS 连接

## WS 协议扩展

| 消息类型 | 方向 | 用途 |
|---------|------|------|
| `device_conflict` | Server → 旧 Client | 通知有新设备请求连接 |
| `conflict_response` | 旧 Client → Server | 用户选择（yield/reject）|
| `conflict_pending` | Server → 新 Client | 通知正在等待旧设备确认 |
| `device_kicked` | Server → 旧 Client | 通知已被新设备替换 |

| WS Close Code | 含义 |
|---------------|------|
| 4010 | 旧设备拒绝让位 |
| 4011 | 被新设备替换 |
| 4012 | 冲突解决超时 |
