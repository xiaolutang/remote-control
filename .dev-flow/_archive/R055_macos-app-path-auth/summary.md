# R055: macOS .app PATH 修复 + Auth 调查优化

**状态**: active
**分支**: feat/R055-macos-app-path-auth

## 概述

修复 macOS .app 从 Finder 启动时 PATH 缺失导致终端找不到命令的关键 Bug，同时对 Auth 连接流程增加耗时观测并做防御性超时优化。

## 任务概览

| ID | Phase | 名称 | 优先级 |
|----|-------|------|--------|
| S301 | 0 | 创建 env_compat.py PATH 修复模块 | P0 |
| S302 | 0 | 集成 PATH 修复到 cli.py | P0 |
| S303 | 0 | env_compat 单元测试 | P0 |
| S304 | 1 | Auth 流程耗时日志 | P1 |
| S305 | 1 | Auth 超时值防御性降低 | P1 |

## Sessions

- S001: 需求规划（2026-05-06）
