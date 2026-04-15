#!/bin/bash
# Remote Control 部署脚本
# 使用方式: ./deploy/deploy.sh [--no-cache]
set -euo pipefail

# ===== 引用共享部署库 =====
INFRA_DIR="${INFRA_DIR:-$(cd "$(dirname "$0")" && pwd)/../../ai_rules/infrastructure}"
source "$INFRA_DIR/deploy-lib.sh"

# ===== 项目声明 =====
PROJECT_NAME="remote-control"
DISPLAY_NAME="Remote Control"
COMPOSE_FILE="deploy/docker-compose.yml"
HEALTH_PATH="/rc/health"
ACCESS_URLS=(
  "服务地址|https://rc.xiaolutang.top/rc/"
  "健康检查|https://rc.xiaolutang.top/rc/health"
)

# ===== 自定义构建 =====
custom_build() {
    bash "$(cd "$(dirname "$0")" && pwd)/build.sh" $BUILD_CACHE_FLAG
}

# ===== 执行 =====
run_deploy "$@"
