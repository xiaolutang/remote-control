#!/bin/bash
# remote-control 远端一键部署
# 使用方式: ./deploy/remote-deploy.sh [--skip-build] [--no-cache]
#
# 服务器配置共享: ai_rules/infrastructure/.remote.env
set -euo pipefail

# 加载共享部署库 + 服务器配置
INFRA_DIR="$(cd "$(dirname "$0")" && pwd)/../../ai_rules/infrastructure"
source "${INFRA_DIR}/deploy-lib.sh"
_load_remote_env

# 项目参数
PROJECT_NAME="remote-control"
COMPOSE_FILE="deploy/docker-compose.yml"
HEALTH_PATH="/rc/health"
DISPLAY_NAME="remote-control"
REMOTE_DEPLOY_DIR="/home/ubuntu/project/remote-control"
IMAGES=("remote-control-server:latest" "remote-control-agent:latest")
ACCESS_URLS=(
  "前端|https://rc.xiaolutang.top/rc/"
  "健康|https://rc.xiaolutang.top/rc/health"
)

# 自定义构建：两个镜像分别构建
custom_remote_build() {
  for IMG_NAME in server agent; do
    docker buildx build --platform "$REMOTE_PLATFORM" \
      -f "deploy/${IMG_NAME}.Dockerfile" \
      -t "remote-control-${IMG_NAME}:latest" \
      $BUILD_CACHE_FLAG --load .
  done
}

run_remote_deploy "$@"
