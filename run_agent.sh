#!/bin/bash

# Run Agent from agent directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/agent"

# 服务器地址（可通过环境变量覆盖）
SERVER_URL="${SERVER_URL:-ws://localhost:8888}"
SERVER_HTTP="${SERVER_URL/ws:/http:}"

# 凭据从环境变量读取
AGENT_USERNAME="${AGENT_USERNAME:-demo}"
AGENT_PASSWORD="${AGENT_PASSWORD:-}"

if [ -z "$AGENT_PASSWORD" ]; then
  echo "Error: AGENT_PASSWORD environment variable is required"
  exit 1
fi

# Get token from login
RESPONSE=$(curl -s -X POST "$SERVER_HTTP/api/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"$AGENT_USERNAME\", \"password\": \"$AGENT_PASSWORD\"}")

TOKEN=$(echo $RESPONSE | python3 -c "import sys, json; print(json.load(sys.stdin)['token'])")

echo "Token: ${TOKEN:0:50}..."

# Start agent
python3 -m app.main start \
  --server "$SERVER_URL" \
  --token "$TOKEN" \
  --command "/bin/bash"
