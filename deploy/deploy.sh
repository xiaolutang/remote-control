#!/bin/bash
# Remote Control 部署脚本
# 使用方式: ./deploy/deploy.sh [--no-cache] [--dev]
#
# 模式:
#   默认       — 使用 deploy/docker-compose.yml（生产，需 Traefik 网关）
#   --dev      — 使用 deploy/docker-compose.dev.yml（自包含，直接暴露端口）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

# 默认使用生产 compose 文件
COMPOSE_FILE="deploy/docker-compose.yml"
BUILD_CACHE_FLAG=""

# ===== 解析参数 =====
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-cache) BUILD_CACHE_FLAG="--no-cache"; shift ;;
        --dev) COMPOSE_FILE="deploy/docker-compose.dev.yml"; shift ;;
        -h|--help)
            echo "用法: $0 [--no-cache] [--dev]"
            echo ""
            echo "选项:"
            echo "  --no-cache   无缓存构建 Docker 镜像"
            echo "  --dev        使用自包含 compose（不依赖 Traefik）"
            exit 0
            ;;
        *) echo "未知参数: $1"; echo "用法: $0 [--no-cache] [--dev]"; exit 1 ;;
    esac
done

cd "$PROJECT_ROOT"

# ===== 检查 .env 文件 =====
if [[ ! -f "$ENV_FILE" ]]; then
    echo "错误: 未找到 .env 文件"
    echo "请复制 .env.example 并填写配置: cp .env.example .env"
    exit 1
fi

# ===== 检查必需环境变量（安全解析，不 source .env） =====
# 从 .env 中提取变量值，避免 shell 注入风险
get_env_var() {
    local name="$1"
    # 读取 KEY=VALUE 行，跳过注释和空行
    grep -E "^${name}=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d'=' -f2-
}

JWT_SECRET_VAL=$(get_env_var "JWT_SECRET")
if [[ -z "$JWT_SECRET_VAL" ]]; then
    echo "错误: JWT_SECRET 未设置"
    echo "请在 .env 中设置 JWT_SECRET（可用: openssl rand -hex 32）"
    exit 1
fi

REDIS_PASSWORD_VAL=$(get_env_var "REDIS_PASSWORD")
if [[ -z "$REDIS_PASSWORD_VAL" ]]; then
    echo "错误: REDIS_PASSWORD 未设置"
    echo "请在 .env 中设置 REDIS_PASSWORD"
    exit 1
fi

# ===== 构建镜像 =====
echo "==> 构建镜像..."
bash "$SCRIPT_DIR/build.sh" $BUILD_CACHE_FLAG

# ===== 启动服务 =====
echo "==> 启动服务 (compose: $COMPOSE_FILE)..."
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d

# ===== 等待健康检查 =====
echo "==> 等待服务就绪..."
max_wait=60
elapsed=0
while [[ $elapsed -lt $max_wait ]]; do
    if docker exec rc-server python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" &>/dev/null; then
        echo "==> 服务已就绪!"
        echo ""
        DIRECT_PORT=$(get_env_var "RC_DIRECT_PORT")
        echo "服务地址:"
        echo "  HTTP API:    http://localhost:${DIRECT_PORT:-8880}/"
        echo "  WebSocket:   ws://localhost:${DIRECT_PORT:-8880}"
        echo "  健康检查:    http://localhost:${DIRECT_PORT:-8880}/health"
        echo ""
        if [[ "$COMPOSE_FILE" == *"dev"* ]]; then
            echo "客户端连接: ENV=direct, host=localhost, port=${DIRECT_PORT:-8880}"
        else
            echo "客户端连接: ENV=local, wss://localhost/rc"
        fi
        exit 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
done

echo "警告: 服务未在 ${max_wait}s 内就绪，请检查日志:"
echo "  docker compose -f $COMPOSE_FILE logs"
exit 1
