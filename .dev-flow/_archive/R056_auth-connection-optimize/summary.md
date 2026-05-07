# R056 auth-connection-optimize 归档

- 归档时间: 2026-05-07
- 状态: completed
- 总任务: 2
- 分支: feat/R056-auth-connection-optimize (已合并 main)
- workflow: B/skill_orchestrated
- providers: codex_plugin/codex_plugin/codex_plugin

## 仓库提交
- remote-control: e22a264 (Merge branch 'feat/R056-auth-connection-optimize')

## Phase 0-1
| 任务 | 描述 | commit |
|------|------|--------|
| S401 | AuthService 共享 ClientSession + 公钥守卫 | a693cd3 |
| S402 | R056 测试验证 + project_spec 更新 | 5700097 |

## 关键交付
- AuthService 懒加载共享 ClientSession，verify/refresh/login 复用同一 session，减少 TCP/TLS 握手
- login() 增加 has_public_key 守卫，跳过重复公钥拉取
- AuthService 实现 __aenter__/__aexit__，确保所有路径都关闭 session
- 最坏路径从 4 次独立连接降至 2 次（AuthService 共享 1 次 + fetch_public_key 1 次）
