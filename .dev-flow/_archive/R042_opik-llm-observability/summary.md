# R042: opik-llm-observability

> 状态：**规划中** (2026-04-23)
> 分支：`feat/R042-opik-llm-observability`

## 范围

Server 端集成 Opik LLM 可观测性平台（self-hosted Docker），通过 logfire + OpenTelemetry OTLP 桥接 Pydantic AI Agent 的 tracing，用于开发调试时观察模型交互过程。

## 技术方案

- 集成链路：Pydantic AI → logfire → OpenTelemetry OTLP → Opik
- Agent 代码无需修改，只需入口配置 + 环境变量
- 条件启用：OTEL_EXPORTER_OTLP_ENDPOINT 未设置时不影响运行
