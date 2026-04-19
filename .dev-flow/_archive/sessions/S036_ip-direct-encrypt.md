# S036: IP 直连 + RSA/AES 应用层加密

> 时间：2026-04-15
> 类型：feature + infrastructure
> 状态：completed (S063)

## 背景

线上 TLS 证书不稳定导致用户无法通过 `wss://rc.xiaolutang.top/rc` 登录。需要一个长期保留的 IP 直连方案，绕过 TLS 依赖。

## 需求确认

- **定位**：长期保留，不是临时应急
- **加密方案**：RSA + AES 混合加密（用户确认）
- **部署方式**：直接暴露 Server 端口，不修改共享 Traefik（避免影响其他项目）
- **用户体验**：登录时自动生成 AES 密钥，会话期间复用，用户无感知

## 实际架构认知（已纠正）

### 核心发现：Agent 跑在用户本地，走互联网连接 Server

```
用户桌面电脑                              云端服务器（Docker）
├── Desktop Client ─── 互联网 ───→ Server
├── Local Agent ───── 互联网 ───→ Server
└── Client ←HTTP localhost─→ Agent

用户手机
└── Mobile Client ─── 互联网 ───→ Server
```

**关键**：Agent 的主要运行模式是用户本地电脑上的 Python 进程，通过互联网 WebSocket 连接 Server。docker-compose 里的 Agent 只是辅助部署（测试/自托管场景）。

### 网络安全边界

| 路径 | 网络 | 安全机制 | ws:// 时是否需要加密 |
|------|------|---------|-------------------|
| Mobile Client → Server | 互联网 | TLS 或 RSA+AES | **是** |
| Desktop Client → Server | 互联网 | TLS 或 RSA+AES | **是** |
| Local Agent → Server | **互联网** | TLS 或 RSA+AES | **是** |
| Desktop Client → Local Agent | localhost | 本机回环 | 否 |
| Server → Docker Agent | Docker 内网 | 网络隔离 | 否 |

**Agent 也需要加密**：因为 Local Agent 通过互联网连接 Server，ws:// 时与 Client 一样面临明文传输风险。

## 技术方案

### 握手流程（Client 和 Agent 通用）

```
Client/Agent                          Server
  │── GET /api/public-key ──────────→ │  ① 获取 RSA 公钥
  │←─ {n, e} ────────────────────────│
  │  ② 本地生成随机 AES-256 密钥      │
  │  ③ RSA-OAEP 加密(AES 密钥)       │
  │  ④ AES-GCM 加密(密码/凭证)       │
  │── POST /api/login ─────────────→ │  ⑤ 发送密文
  │   {encrypted_key, encrypted_data, │  ⑥ RSA 解密 → 得到 AES 密钥
  │    nonce}                         │  ⑦ 存入 Redis: aes_key:{session_id}
  │←─ AES-GCM 加密(token, session) ──│  ⑧ 用 AES 加密响应
  │                                    │
  │══ WebSocket ═════════════════════│
  │  auth 明文(token)                  │  ⑨ auth 后查 Redis 取 AES 密钥
  │  后续消息全部 AES-GCM 加密         │  ⑩ 双向加解密
```

### 加密参数

| 参数 | 值 |
|------|-----|
| RSA | 2048-bit, OAEP + SHA-256 |
| AES | 256-bit, GCM 模式 |
| Nonce | 96-bit 随机，每条消息独立 |
| 编码 | 二进制数据 base64 编码在 JSON 中 |

### 密钥生命周期

- AES 密钥在每次 WebSocket 连接时独立生成，绑定连接对象
- Agent 和 Client 各自独立协商 AES 密钥（per-connection）
- WS 断开时销毁（clear_aes_key），不复用跨连接
- RSA 公钥通过 TOFU 机制本地持久化，跨会话复用

### 加密覆盖范围

- **Client 加密**：登录/注册 HTTP API + Client WebSocket 消息
- **Agent 加密**：登录 HTTP API + Agent WebSocket 消息
- **Server 中转**：收到加密 Client 消息 → 解密 → 明文转发给 Agent（内网或已加密）
- **Agent 和 Client 各自独立协商 AES 密钥**

### 部署方案

- docker-compose: server 增加 ports 映射 `${RC_DIRECT_PORT:-8080}:8000`
- 不修改 Traefik，零影响其他项目
- 客户端/Agent 本地 URL 格式：`ws://{ip}:{port}`（无 `/rc` 前缀，直连不走 Traefik striprefix）

### 向后兼容

- TLS 路径（production 环境）仍走 `wss://rc.xiaolutang.top/rc`，无需加密
- 只有 `ws://` 连接才触发加密流程
- 通过 `X-Encryption: rsa-aes` 请求头区分加密/明文模式

## 分期策略

**Phase 1: IP 直连**（立即，先用起来）
- 只有用户一个人使用，安全风险可控
- 改动：URL 修复 + 端口暴露，极小改动量
- 目标：绕过 TLS 让应用跑起来
- 风险：明文传输（密码、token、终端数据），仅单人使用可接受

**Phase 2: RSA+AES 加密**（后续迭代）
- 用户范围扩大前必须完成
- 改动：服务端加密基础设施 + Client 加密 + Agent 加密
- 目标：应用层加密保护明文传输
- 加密范围：Client ↔ Server、Agent ↔ Server（两端都需要）

## 勘误（2026-04-15 更新）

> 以下内容已过时，以当前 `feature_list.json` 活跃任务 S063/S064 为准。

1. **端口**：本文档默认端口 8080，已统一修改为 **8880**（8080 被线上 Tomcat 占用）
2. **Phase 1/Phase 2 分期已合并**：RSA+AES 加密已在当前迭代同步实现完成（Server crypto.py + Agent crypto.py + Client crypto_service.dart），不存在"Phase 1 明文可接受"阶段。直连路径从第一天起就使用应用层加密，符合 architecture.md 不变量 #27
3. **加密失败策略**：加密失败不降级为明文，而是断开连接（符合禁止模式 #105）

## 执行模式

- workflow_mode: A（本地执行）
- workflow_runtime: skill_orchestrated
