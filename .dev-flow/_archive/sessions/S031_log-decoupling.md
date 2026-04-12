# S031: 日志模块解耦

> 日期：2026-04-12
> 阶段：log-decoupling
> 状态：规划完成

## 背景

log-service-sdk 作为第三方依赖引入 remote-control，后续可能变更或被替换。当前 SDK 在 Server 和 Agent 各有一处直接 import，代码几乎一模一样，耦合度虽低但存在重复。

## 需求

将 SDK 使用收口到适配层（log_adapter.py），使得 SDK 变更或替换时只需修改适配层。

## 方案

- 每个模块（server/agent）各创建一个 log_adapter.py
- 提供 init_logging() / close_logging() 两个函数
- 消费方不再直接 import log_service_sdk
- 不引入 Protocol/Interface 抽象（过度设计）

## 任务

| ID | 模块 | 任务 |
|----|------|------|
| B054 | server | 创建 log_adapter.py + 重构 __init__.py |
| B055 | agent | 创建 log_adapter.py + 重构 cli.py |
| S031 | shared | 适配层测试 |

## 决策记录

- 否决 Protocol 抽象：只有 1 个实现，过度设计
- 否决共享适配层文件：server/agent 是独立模块，各有不同默认值
- 不改 Client 路径：Client 日志走 httpx 转发，不涉及 SDK
