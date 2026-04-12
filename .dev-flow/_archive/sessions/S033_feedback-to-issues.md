# S033: 反馈存储迁移到 log-service Issues API

## 日期
2026-04-12

## 背景
真实使用测试发现反馈页面提示成功但 log-service 网页无内容，排查发现：
1. L1: 转发 URL 写错 /api/ingest → 应为 /api/logs/ingest
2. L2: best-effort 转发没有 raise_for_status()，404 被静默吞掉
3. 测试 mock 了转发函数本身，URL 路径从未被断言

修复 URL 后追问"为什么要用 Redis"，反思反馈存储设计：
- Redis 是易失存储，反馈数据不应放在内存里
- 既然要转发到 log-service，存两份是冗余
- log-service 已有完整的 Issues API（POST/GET/PATCH /api/issues）

## 决策
1. **Layer 1**: 修复 URL + raise_for_status + 测试（代码已完成）
2. **Layer 2**: 反馈存储从 Redis 迁移到 log-service Issues API
   - 提交反馈 → POST /api/issues（持久化，非 best-effort）
   - 查询反馈 → GET /api/issues/{id}
   - 删除 Redis 反馈存储代码
   - 客户端 API 契约不变

## 任务拆解
- B057: 修复转发 URL + raise_for_status + 测试修正（P0, 代码已完成）
- B058: 反馈提交迁移到 log-service Issues API（P1）
- B059: 反馈查询迁移 + Redis 清理（P1）
- S033: 集成测试 + 部署验证（P1）
