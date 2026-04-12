#!/bin/bash

# 在前台启动 Agent，可以直接看到终端输出
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/agent"

# 服务器地址（可通过环境变量覆盖）
SERVER_URL="${SERVER_URL:-ws://localhost:8888}"

echo "=========================================="
echo "  Remote Control Agent - 前台模式"
echo "=========================================="
echo ""
echo "服务器: $SERVER_URL"
echo ""
echo "启动后你将看到:"
echo "  - PTY 终端输出（本地命令结果）"
echo "  - [remote] 标记的远程输入（来自手机）"
echo ""
echo "按 Ctrl+C 退出"
echo "=========================================="
echo ""

PYTHONPATH="$SCRIPT_DIR/agent" python3 -m app.cli run
