# Claude Code 命令参考

## 常用命令

| 命令 | 说明 |
|------|------|
| `/help` | 查看帮助信息和可用命令 |
| `/clear` | 清除当前对话历史 |
| `/compact` | 压缩对话上下文，释放 token 空间 |
| `/compact [instructions]` | 压缩时保留指定要点 |
| `/cost` | 显示当前会话的 token 用量和费用 |
| `/model` | 切换 AI 模型 |
| `/fast` | 切换快速模式（同一模型，更快输出） |
| `/plan` | 进入计划模式，先规划再实现 |
| `/resume` | 恢复上次的对话会话 |
| `/undo` 或 `/rewind` | 撤销上次操作 |

## 项目与上下文管理

| 命令 | 说明 |
|------|------|
| `/init` | 初始化项目的 CLAUDE.md 配置文件 |
| `/add-dir` | 添加外部目录到当前工作上下文 |
| `/context` | 查看当前上下文使用情况 |
| `/memory` | 编辑 CLAUDE.md 记忆文件 |
| `/config` | 查看/修改 Claude Code 配置 |

## 开发工作流

| 命令 | 说明 |
|------|------|
| `/diff` | 查看当前未提交的代码改动 |
| `/review` | 对 PR 或代码进行 review |
| `/pr-comments` | 查看 PR 评论 |
| `/autofix-pr` | 自动修复 PR 中的问题 |
| `/batch` | 批量执行多个任务 |
| `/loop` | 定时循环执行命令 |
| `/plan` | 进入规划模式 |
| `/tasks` | 管理后台任务 |

## Git 与协作

| 命令 | 说明 |
|------|------|
| `/branch` | 创建新分支 |
| `/commit` | 提交代码（生成规范 commit message） |
| `/export` | 导出对话记录 |
| `/stats` | 查看 Claude Code 使用统计 |

## 调试与诊断

| 命令 | 说明 |
|------|------|
| `/debug` | 调试工具 |
| `/doctor` | 检查 Claude Code 健康状态 |
| `/status` | 查看当前状态 |
| `/permissions` | 管理权限设置 |

## 扩展与集成

| 命令 | 说明 |
|------|------|
| `/mcp` | 管理 MCP 服务器 |
| `/hooks` | 配置 hook 脚本 |
| `/skills` | 管理自定义技能 |
| `/agents` | 管理自定义子代理 |
| `/install-github-app` | 安装 GitHub App 集成 |
| `/voice` | 语音输入模式 |
| `/terminal-setup` | 终端设置（Shift+Enter 换行等） |
| `/keybindings` | 自定义键盘快捷键 |

## 非交互模式（自动化）

```bash
# 管道输入
echo "解释这个函数" | claude

# 直接指定 prompt
claude -p "修复 auth.py 中的 bug"

# 指定输出格式
claude -p "列出 TODO" --output-format json

# 继续上次对话
claude --continue
claude --resume
```

## 常用快捷键

- `Escape` — 中断当前操作
- `Shift+Enter` — 换行（需 /terminal-setup 配置）
- `Ctrl+C` — 取消当前输入
- `@文件名` — 引用文件到对话中
