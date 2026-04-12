# S032: 用户信息 + 反馈修复规划

## 日期
2026-04-12

## 背景
调查反馈 API 的 user_id 传递问题时发现：
1. feedback_api.py 使用 `payload.get("session_id", "")` 取 user_id — JWT payload 的 key 是 "sub" 不是 "session_id"，且语义上是随机 session_id 不是用户名
2. 客户端已有 rc_username 本地存储，但 LoginResponse 不返回 username
3. 用户需要个人信息页面，展示用户名、登录时间、平台信息

## 需求确认
- 用户信息页面：用户名 + 登录时间 + 设备/平台信息 + 反馈入口 + 退出登录
- 入口：设置菜单中的"个人信息"
- 菜单去重：反馈和退出从菜单移至个人信息页面

## 决策
1. **反馈 user_id 修复**：Server 端通过 session_id 查 session 记录获取真实 user_id，不依赖客户端传递
2. **LoginResponse 增强**：新增 username 字段，方便客户端确认用户名
3. **用户信息本地存储**：login_time 在客户端登录成功后本地记录，不需要新增 Server 端点
4. **菜单简化**：设置菜单只保留"主题"和"个人信息"

## 任务拆解
- B056: 修复反馈 user_id + LoginResponse 增强（server, P0）
- F054: 用户信息本地存储与服务（client, P1）
- F055: 用户信息页面 UI（client, P1）
- F056: 菜单去重 + 个人信息入口（client, P1）
- S032: 集成测试（shared, P1）
