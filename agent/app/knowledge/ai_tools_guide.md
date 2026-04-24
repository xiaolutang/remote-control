# AI 编程工具使用指南

## Claude Code

Claude Code 是 Anthropic 推出的 AI 编程工具，通过终端交互辅助编程。

### 安装

```bash
npm install -g @anthropic-ai/claude-code
```

### 验证安装

```bash
which claude
claude --version
```

### 核心用法

1. **交互模式**：在项目目录运行 `claude`，进入对话式编程
2. **管道模式**：`echo "指令" | claude` 或 `claude -p "指令"`
3. **恢复会话**：`claude --resume` 继续上次对话

### 适用场景

- 代码重构和优化
- Bug 定位和修复
- 测试编写
- 代码审查
- 新功能开发

## Codex CLI

Codex CLI 是 OpenAI 推出的命令行 AI 编程工具。

### 注意

Codex CLI 主要用于本地 AI 辅助编程，当前版本作为信息参考，不作为远程终端推荐工具。

### 适用场景

- 了解不同 AI 编程工具的特点
- 对比选择适合的 AI 编程方案
