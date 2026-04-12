#!/bin/bash
# Remote Control 构建脚本
# 使用方式: ./deploy/build.sh [server|agent|all] [--no-cache]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 解析参数
TARGET="all"
CACHE_FLAG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        server|agent|all) TARGET="$1"; shift ;;
        --no-cache) CACHE_FLAG="--no-cache"; shift ;;
        *) echo "未知参数: $1"; echo "用法: $0 [server|agent|all] [--no-cache]"; exit 1 ;;
    esac
done

build_component() {
    local name=$1
    echo "==> 构建 remote-control-${name}:latest ..."
    docker buildx build \
        -f "$SCRIPT_DIR/${name}.Dockerfile" \
        -t "remote-control-${name}:latest" \
        $CACHE_FLAG \
        --load \
        "$PROJECT_ROOT"
    echo "==> remote-control-${name} 构建完成"
}

case "$TARGET" in
    server) build_component server ;;
    agent) build_component agent ;;
    all) build_component server & PID_S=$!; build_component agent & PID_A=$!; wait $PID_S $PID_A ;;
esac
