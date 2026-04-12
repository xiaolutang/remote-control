#!/bin/bash
# Remote Control 部署脚本
# 使用方式: ./deploy.sh [--no-cache]
set -euo pipefail

# ===== 引用共享部署库 =====
INFRA_DIR="${INFRA_DIR:-$(cd "$(dirname "$0")" && pwd)/../../ai_rules/infrastructure}"
source "$INFRA_DIR/deploy-lib.sh"

# ===== 项目声明 =====
PROJECT_NAME="remote-control"
DISPLAY_NAME="Remote Control"
COMPOSE_FILE="docker-compose.prod.yml"
HEALTH_PATH="/rc/health"
ACCESS_URLS=(
  "服务地址|http://localhost/rc/"
  "健康检查|http://localhost/rc/health"
)

# ===== 执行 =====
run_deploy "$@"
