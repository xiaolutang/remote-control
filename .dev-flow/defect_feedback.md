# Defect Feedback Log

> 记录缺陷逃逸分析、根因反思和规则升级项。

---

## DF-20260408-05

- issue_id: DF-20260408-05
- source: real_use
- related_task: F032, F038
- symptom: Agent 启动后连接 WebSocket 收到 4001 Token 无效
- escape_path: >-
    AgentLifecycleManager.onLoginSuccess() 直接调用 DesktopAgentSupervisor.ensureAgentOnline()，
    未先调用 syncManagedAgentConfig() 写入最新 token。
    单元测试 mock 了 Supervisor，token 写入流程不可见，无法捕获此缺陷。
- fix_level: L2
- root_cause_summary: >-
    两套并行 Agent 管理系统（DesktopAgentManager 和 AgentLifecycleManager），
    各自直接调用 Supervisor 启动 Agent，导致启动逻辑分散在两处。
    ALM 的启动路径遗漏了配置同步步骤。
- root_cause_analysis:
    1. 根因：缺少单一权威入口，启动逻辑分散导致不一致
    2. 同类问题：任何新增的"启动 Agent"路径都可能遗漏 sync 步骤
    3. 统一模式：应合并为单一管理入口，从 API 层面强制 sync + start 绑定
    4. architecture.md 需补充：AgentLifecycleManager 不得直接操作 Supervisor
- upstream_actions:
    - 补 architecture.md 不变量：单一管理入口
    - 补 architecture.md 禁止模式：绕过 DesktopAgentManager 直接操作 Agent
- rules_to_update:
    - xlfoundry-plan: 高风险 auth/startup 任务必须测试 token 完整流转
- owner: xlfoundry-plan
- status: closed

---

## DF-20260408-06 (方法论反思)

- issue_id: DF-20260408-06
- source: audit
- related_task: agent-hardening 规划
- symptom: >-
    规划 Agent 硬化任务时，初始方案是"ALM 委托 DAM + syncAndEnsureOnline 原子方法"，
    本质上是在现有双管理入口上打补丁，没有从根本上消除"两套系统"的问题。
- escape_path: >-
    AI 助手倾向于"最小改动"思维，面对架构问题时先想补丁而不是重新设计。
    产品未发布时恰恰是做正确设计的最佳时机，但"害怕大改"的心理导致方案保守。
- fix_level: L2
- root_cause_summary: >-
    修 bug 思维 vs 架构思维：
    - 修 bug 思维：发现 ALM 忘了 sync → 补上；发现两套系统 → 加中间层
    - 架构思维：问"系统该怎么设计才能让这类 bug 不可能发生"
- root_cause_analysis:
    1. 根因：未从 4 个维度系统分析问题
       - 维度 1 状态所有权：谁拥有 agent 状态？（当前散落在 5 处）
       - 维度 2 不变量强制：API 是否阻止了错误用法？（当前靠约定）
       - 维度 3 层次正确性：ALM 和 DAM 是否在同一层都操作基础设施？（当前是）
       - 维度 4 边界清晰度：同一操作（启动 Agent）是否有两份代码？（当前是）
    2. 正确方法：
       - 单一权威：DesktopAgentManager 成为唯一管理入口（extends ChangeNotifier）
       - API 强制不变量：sync + start 绑定在同一方法内，无法单独调用
       - 消除 ALM：其职责合并进 DAM，消除双路径
       - PID 校验：基础设施层防护
    3. 规则：产品未发布时，优先做正确设计而非最小补丁
- upstream_actions:
    - 补 architecture.md：DesktopAgentManager extends ChangeNotifier，成为唯一 Provider
    - 补 architecture.md：删除 AgentLifecycleManager 的架构角色
    - 规划 agent-hardening phase：4 个任务按依赖顺序执行
- rules_to_update:
    - xlfoundry-plan: 产品未发布时，架构问题应从根因设计，不接受补丁方案
    - xlfoundry-risk: 审查规划方案时，主动质疑"这是补丁还是根因修复"
- owner: xlfoundry-plan
- status: open

---

## 架构师思维检查清单（从本次反思提炼）

当遇到"修了一个 bug 又发现同类 bug"时，按以下顺序思考：

1. **状态所有权**：当前有几个人能回答"系统现在什么状态"？
   - 如果 > 1 个人，说明状态散落，需要合并
2. **不变量强制**：关键约束是靠注释/约定，还是靠 API/类型系统？
   - 如果靠约定，迟早会被违反
3. **层次正确性**：上层是否直接操作了基础设施？
   - 如果是，中间层的存在就没有意义
4. **操作唯一性**：同一个操作有几份实现代码？
   - 如果 > 1 份，迟早会不一致
5. **产品阶段判断**：产品是否已发布？
   - 未发布 → 优先正确设计
   - 已发布 → 优先安全补丁 + 规划技术债偿还

---

## DF-20260409-01

- issue_id: DF-20260409-01
- source: real_use
- related_task: B036
- symptom: Agent 离线时，iOS 和 Android 同时登录未触发同端设备限制逻辑
- escape_path: >-
    Agent 离线 → 终端全部 closed → 客户端无法建立 WS 连接 →
    WS 层冲突检测永远不触发 → 两个移动设备可同时登录
- fix_level: L2
- root_cause_summary: >-
    设计缺陷。同端限制只在 WS 连接层（ws_client.py）实现，
    但该机制要求客户端能成功建立 WS 连接才能触发冲突检测。
    当 Agent 离线时所有终端 closed，客户端跳过 WS 连接创建，冲突检测完全失效。
- root_cause_analysis:
    1. 根因：并发限制只在连接层实现，未在更上层（登录层）有兜底
    2. 同类问题：任何依赖 WS 连接才能触发的安全机制，在 Agent 离线时都失效
    3. 统一模式：并发限制必须在登录层（HTTP）实现，WS 层作为实时冲突解决的补充
    4. architecture.md 需补充：登录层 token_version 机制不变量
- upstream_actions:
    - 新增 B038: 登录层 token_version 机制
    - 新增 B039: 登录层限制单元测试
    - 新增 F048: 客户端登录 view 参数 + 401 被踢处理
    - 新增 F049: 客户端单元测试
    - 新增 S025: 集成测试与端到端验证
    - 更新 architecture.md 不变量 #15-17 和禁止模式
- rules_to_update:
    - xlfoundry-plan: 并发限制不应只在连接层实现，必须在更上层（登录层）有兜底
- owner: xlfoundry-plan
- status: planned

---

## DF-20260409-02

- issue_id: DF-20260409-02
- source: real_use
- related_task: B036
- symptom: WS 层 is_agent_connected 门控阻止了 Agent 离线时的冲突检测
- escape_path: >-
    is_agent_connected(session_id) 返回 False →
    直接返回（reject code 4009）→ 冲突检测代码不执行
- fix_level: L1
- root_cause_summary: >-
    代码笔误级别。is_agent_connected 检查位置过早，作为致命门控阻断了整个冲突检测流程。
    Agent 在线状态应是信息字段而非门控条件。
- upstream_actions:
    - 已修复：ws_client.py 中移除 is_agent_connected 致命门控，改为信息字段
    - 已补充：5 个 Agent 离线回归测试
- rules_to_update: []
- owner: xlfoundry-execute
- status: closed

---

## DF-20260409-03

- issue_id: DF-20260409-03
- source: real_use
- related_task: B038, B039
- symptom: >-
    B039 的 35 个单元测试全部通过，但 Docker 部署后旧设备 token 调用 /api/runtime/devices 仍返回 200，
    登录层同端限制不生效。
- escape_path: >-
    测试只验证了 auth.py 层的 async_verify_token 函数级正确性（版本比对 → 抛出 TOKEN_REPLACED），
    未验证 runtime_api.py / log_api.py / user_api.py 是否真正调用了 async_verify_token。
    这三个文件仍使用同步 verify_token（只做 JWT 解码，不走 Redis 版本校验），
    导致旧 token 经由 runtime API 绕过了整个版本校验机制。
- fix_level: L2
- root_cause_summary: >-
    测试验证了"锁是好的"，但没验证"门装了锁"。
    B038 只实现了 async_verify_token 机制，没有一条验收条件要求"所有受保护 API 必须改用 async_verify_token"。
    B039 只测 auth.py 函数级正确性，未做路由级集成验证。
- root_cause_analysis:
    1. 根因：任务拆解只覆盖了机制的实现者（auth.py），没有覆盖机制的消费者（runtime_api/log_api/user_api）
    2. 同类问题：任何新增的鉴权/安全机制，如果只测机制本身而不测"是否被所有入口接入"，都会出现同样的逃逸
    3. 统一模式：新机制实现后，必须有"接入验证"测试，确保所有消费方正确接入
    4. architecture.md 需补充：HTTP API 必须使用 async_verify_token，禁止同步 verify_token
- upstream_actions:
    - 已修复：runtime_api.py / log_api.py 改用 async_verify_token
    - 已修复：user_api.py 不再吞掉 TokenVerificationError
    - 已补测试：4 个 HTTP E2E 集成测试 + 4 个路由接入扫描测试
    - 已更新：architecture.md 不变量 #19-20 + 禁止模式
- rules_to_update:
    - xlfoundry-plan: test-tasks 模板补"机制消费方接入验证"检查项
    - xlfoundry-audit: 补"新机制是否被所有调用方接入"检查维度
- owner: xlfoundry-plan
- status: closed

---

## DF-20260409-04

- issue_id: DF-20260409-04
- source: real_use
- related_task: B036, B038
- symptom: >-
    iOS 被 Android 踢下线后，iOS 的 WS 自动重连用旧 token 成功，
    触发 WS 层冲突检测，又把 Android 踢了（互踢乒乓）。
- escape_path: >-
    WS Client 路由使用同步 verify_token（只做 JWT 解码，不查 Redis token_version），
    被踢设备的旧 token（JWT 本身未过期，24h 有效期）仍能通过 WS 重连。
    HTTP API 已在 DF-20260409-03 中改用 async_verify_token，
    但 WS 路由被 architecture.md 不变量 #19 显式豁免（"WS 路由除外"），
    形成了"HTTP 严格、WS 宽松"的分裂状态。
- fix_level: L2
- root_cause_summary: >-
    设计缺陷。后端存在两套 token 校验逻辑：
    async_verify_token（查 Redis 版本）用于 HTTP API，
    verify_token（只做 JWT 解码）用于 WS 路由。
    WS 路由被显式豁免，但被踢设备的旧 token 能通过 WS 重回并踢掉新设备。
    与 DF-20260409-03 同类（机制实现者已就位，但消费方未全覆盖）。
- root_cause_analysis:
    1. 根因：token_version 机制只覆盖了 HTTP 层，未覆盖 WS 层
    2. 同类问题：任何安全机制的覆盖范围不完整，都会形成绕过路径
    3. 统一模式：所有 token 校验必须走同一条代码路径（async_verify_token），
       不允许 HTTP 和 WS 有不同的校验严格度
    4. architecture.md 不变量 #19 的 "WS 路由除外" 是错误的豁免，需删除
- upstream_actions:
    - 新增 B040: WS 路由改用 async_verify_token
    - 新增 B041: 单元测试
    - 新增 S026: 集成测试
    - 更新 architecture.md 不变量 #19 + 禁止模式
- rules_to_update:
    - xlfoundry-plan: 新增安全机制时，验收条件必须覆盖所有路由类型（HTTP + WS），不能只覆盖 HTTP
- owner: xlfoundry-plan
- status: planned

---

## DF-20260412-01: 转发 URL 路径错误 + 静默失败

- source: real_use
- related_task: B048, B046
- symptom: 反馈页面提示成功，但 log-service 网页中看不到反馈内容
- escape_path:
    - 转发函数被 mock 绕过，URL 路径从未被断言
    - httpx 收到 404 不抛异常（未调用 raise_for_status），best-effort 吞掉错误
    - log_api._forward_to_log_service 零测试（mock 路径本身也是错的 _get_http_client → get_shared_http_client）
    - 无端到端集成验证
- fix_level: L2
- root_cause_summary:
    - L1 路径笔误：/api/ingest 应为 /api/logs/ingest（两处）
    - L2 设计缺陷：best-effort 外部调用没有 response.raise_for_status()，HTTP 错误（404）被静默忽略
    - 同类风险：所有调用外部服务的 best-effort 转发都存在类似问题（不检查 response status、路径硬编码、mock 绕过真实链路）
- upstream_actions:
    - 修正 feedback_api.py:205 和 log_api.py:272 的 /api/ingest → /api/logs/ingest
    - 两处补 response.raise_for_status()
    - 补 URL 断言测试 + 404 触发 warning 测试
    - 修正已有测试的 mock 路径（_get_http_client → get_shared_http_client）
- rules_to_update:
    - xlfoundry-plan: best-effort 外部调用必须验证 URL 路径 + 检查 response status
    - xlfoundry-plan: test-scenario-catalog.md 补"外部服务路径验证"模式
- owner: xlfoundry-execute
- status: closed

---

## DF-20260415-01

- issue_id: DF-20260415-01
- source: real_use
- related_task: S063
- symptom: 服务器重新部署后，桌面 Agent 永久离线，刷新无法恢复
- escape_path: >-
    1. Agent run() retry 耗尽后 break 退出循环，但 asyncio event loop 继续运行，
       local_server HTTP 仍在监听 → 进程不退出 → 僵尸
    2. Flutter getStatus() 用 PID 存活判断 managedByDesktop，不检查 Server agent_online
    3. ensureAgentOnline() 发现 managed PID 存在 → 等待超时 → 不杀旧进程不重启
    4. max_retries 配置源不一致：Python 默认 60、CLI 默认 5、Flutter config 写 5
- fix_level: L2
- root_cause_summary: >-
    Agent 重连耗尽后进程不退出（local_server 保持监听），Flutter 看到进程存活就认为 Agent 还在工作。
    两层都缺少失败后的清理和自愈逻辑。
- root_cause_analysis:
    1. 根因：进程所有权/退出回收/离线重启链路没有形成可验证的不变量
    2. 同类问题：任何"检测到异常但只等不处理"的模式都有相同风险
    3. 统一模式：Agent 必须保证退出干净，Client 必须保证检测到异常后能自愈
    4. architecture.md 补充：不变量 #32（进程退出）和 #33（客户端自愈）
- upstream_actions:
    - 新增 S065: Agent 重连韧性 L2 修复
    - 更新 architecture.md 不变量 #32/#33 + 禁止模式
- rules_to_update:
    - xlfoundry-plan: 高风险 startup/network 任务必须测试进程退出路径
    - xlfoundry-risk: 审查"检测→等待→放弃"链路时，必须追问"放弃后有没有清理和自愈"
- owner: xlfoundry-plan
- status: open

---

## DF-20260416-01

- issue_id: DF-20260416-01
- source: real_use
- related_task: S065
- symptom: 服务器重启后 Agent 收到 1012 (service restart) 断连，进程永久挂起不退出也不重连
- escape_path: >-
    1. test_reconnect.py 7 个测试全是属性断言（默认值/自定义值/退避公式），没有验证断连后的实际重连行为
    2. test_agent_connection_stability.py 只测长连接存活，不测断连恢复
    3. asyncio.gather 死锁未被任何测试覆盖
- fix_level: L2
- root_cause_summary: >-
    _connect_and_run() 内部三个并行任务（PTY读/WS读/心跳）使用 asyncio.gather 协调，
    但任务间缺少断连信号传播。WS 读和心跳检测到断连后只 break 不设置 _connected=False，
    导致 PTY 读任务永远循环（while self._running and self._connected）。gather 死锁，run() 无法进入重试。
- root_cause_analysis:
    1. 根因：并行任务间缺少断连信号传播机制（实现遗漏，非需求遗漏）
    2. 同类问题：任何使用 asyncio.gather 协调多个长期运行任务的场景，都需要退出信号传播
    3. 统一模式：任何检测到连接断开的任务，必须在 break 前设置 self._connected = False
    4. architecture.md 需补充：Agent 并行任务断连信号传播不变量 (#34)
- upstream_actions:
    - 新增 S066: Agent 1012 重连阻塞修复
    - 更新 architecture.md 不变量 #34
    - 补 5 个断连信号传播测试
- rules_to_update:
    - xlfoundry-plan: asyncio.gather 并行任务的测试必须覆盖"部分任务退出后 gather 是否完成"
    - xlfoundry-risk: 审查并行任务协调时，必须检查任务间是否有退出信号传播
- owner: xlfoundry-execute
- status: closed

---

## DF-20260416-02

- issue_id: DF-20260416-02
- source: real_use
- related_task: mobile-terminal, xterm-fork, multi-view-terminal
- symptom: >-
    1. 在 remote-control 里运行 Codex 时，终端界面经常退化成近似单行重绘；
       Claude Code 相对可用，但也存在终端兼容性疑点。
    2. 手机上弹出软键盘后，桌面端正在查看的同一 terminal 布局也会跟着变化。
- escape_path: >-
    1. Client 端使用本地 override 的 xterm.dart fork，终端协议实现已脱离上游；
       但当前缺少针对 CPR/alt-screen/resize/TUI 的兼容性回归测试。
    2. xterm fork 中 CPR（CSI 6n）响应直接返回内部 0-based cursorX/cursorY，
       可能产生非法的 ESC[0;0R，现代 TUI 探测时会发生退化。
    3. 移动端 TerminalView 尺寸变化会直接触发 onResize → WebSocket resize →
       Server 转发 → Agent PTY resize；系统没有区分"本地 viewport 变化"和"共享 PTY 全局尺寸变化"。
- fix_level: L2
- root_cause_summary: >-
    这是两个层次混在一起的问题：
    - L1 协议兼容风险：xterm fork 已承接终端协议实现责任，但缺少最小协议回归保护；
      Codex 比 Claude Code 更依赖完整 TUI/终端能力探测，因此更容易把 CPR 等协议瑕疵打出来。
    - L2 语义建模缺陷：当前 terminal 是共享裸 PTY，resize 没有 owner 概念，
      谁最后发送 resize，谁就改掉所有视图共享的 PTY 尺寸。
- root_cause_analysis:
    1. 根因：终端协议层和多端共享语义层没有清晰分层
    2. 同类问题：任何继续直接共享裸 PTY 的方案，都会反复遇到"谁拥有尺寸"、"谁的 viewport 生效"、"移动端键盘是否应影响全局布局"等问题
    3. 统一模式：
       - xterm fork 只负责输入法/平台接入和终端协议兼容
       - remote-control 协议层负责 terminal size ownership，不得把本地键盘/viewport 变化直接升级成全局 PTY resize
    4. 待验证假设：
       - CPR 0-based 响应是 Codex 单行退化的高概率根因之一
       - 即便修复 CPR，当前共享裸 PTY + 无 owner resize 设计仍会持续给移动端带来布局干扰
- upstream_actions:
    - 记录为后续优化项，不在本轮直接修复
    - 后续补最小回归测试：CPR、alt-screen、resize owner、Codex/Claude Code smoke
    - 后续评估两类方案：
      A. 继续共享单 PTY，但引入 resize owner / 主控端语义
      B. 引入 tmux/screen 作为会话层，降低多视图共享终端的尺寸冲突
- rules_to_update:
    - xlfoundry-plan: 终端/PTY 相关需求必须区分"协议兼容"与"多端共享语义"两类任务
    - xlfoundry-risk: 评审移动端终端功能时，必须检查软键盘/viewport 变化是否会影响共享 PTY 全局状态
- owner: xlfoundry-plan
- status: open
