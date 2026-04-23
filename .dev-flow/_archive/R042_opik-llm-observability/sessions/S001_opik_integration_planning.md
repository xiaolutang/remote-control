# S001: Opik LLM 可观测性集成规划

> 日期：2026-04-23
> 类型：规划

## 背景

R041 验收未通过，原因之一是"模型交互过程不可观测"——无法看到 Agent 与 LLM 的原始请求/响应/tool call，难以排查模型行为。

## 需求

集成 Opik（Comet 出品，Apache 2.0）LLM 可观测性平台到 Server，用于开发调试时观察 Agent 与大模型的完整交互过程。

## 技术选型

- **Opik** self-hosted Docker 部署，UI 在 http://localhost:5173
- 集成链路：`Pydantic AI → logfire → OpenTelemetry OTLP → Opik`
- **关键发现**：Pydantic AI 的 tracing 不通过 `opik` SDK，而是通过 `logfire` + OpenTelemetry OTLP 协议
- Agent 业务代码无需修改，只需 3 行配置代码 + 2 个环境变量

## 集成架构

```
Server (Pydantic AI Agent)
  └── logfire.instrument_pydantic_ai()  ← 自动拦截 agent 调用
        └── OpenTelemetry OTLP
              └── Opik (localhost:5173/api/v1/private/otel)
```

## 范围

- Server 端 logfire 配置（条件启用，不影响无 Opik 时的运行）
- Opik Docker Compose 独立部署文件
- OTEL 环境变量配置
- 端到端 smoke 验证

## 不包含

- 前端 UI 改动
- 手机端可观测
- 生产环境外部访问

## 运行模式

- workflow: A (local/local/local)
- runtime: skill_orchestrated
- review_provider: codex_plugin（沿用 R041 配置）
