#!/bin/bash
# remote-control 远端一键部署脚本
# 使用方式: ./deploy/remote-deploy.sh [--skip-build]
#
# 前提: 已配置 deploy/.remote.env，远端已部署基础设施（Traefik）
set -euo pipefail

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# 读取配置
ENV_FILE="$SCRIPT_DIR/.remote.env"
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}错误: 未找到 $ENV_FILE${NC}"
    echo -e "${YELLOW}请复制模板并填写: cp deploy/.remote.env.example deploy/.remote.env${NC}"
    exit 1
fi

source "$ENV_FILE"

if [ -z "$REMOTE_HOST" ]; then
    echo -e "${RED}错误: 请在 $ENV_FILE 中填写 REMOTE_HOST${NC}"
    exit 1
fi

REMOTE_USER="${REMOTE_USER:-ubuntu}"
REMOTE_DEPLOY_DIR="${REMOTE_DEPLOY_DIR:-/home/ubuntu/project/remote-control}"
REMOTE_PLATFORM="${REMOTE_PLATFORM:-linux/amd64}"
IMAGE_SERVER="remote-control-server:latest"
IMAGE_AGENT="remote-control-agent:latest"
TMP_FILE="/tmp/rc-images.tar.gz"

echo -e "${BLUE}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       remote-control 远端一键部署                       ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  服务器: ${GREEN}${REMOTE_USER}@${REMOTE_HOST}${NC}"
echo -e "  部署目录: ${GREEN}${REMOTE_DEPLOY_DIR}${NC}"
echo -e "  目标平台: ${GREEN}${REMOTE_PLATFORM}${NC}"
echo ""

# ===== 0. SSH 连通性检查 =====
echo -e "${YELLOW}[0/5] 检查 SSH 连接...${NC}"
if ! ssh -o ConnectTimeout=5 "${REMOTE_USER}@${REMOTE_HOST}" "echo ok" &>/dev/null; then
    echo -e "${RED}错误: 无法连接 ${REMOTE_USER}@${REMOTE_HOST}${NC}"
    exit 1
fi
echo -e "  ${GREEN}SSH 连接正常${NC}"

# ===== 1. 本地构建 =====
if [[ "${1:-}" != "--skip-build" ]]; then
    echo -e "${YELLOW}[1/5] 构建镜像（平台: ${REMOTE_PLATFORM}）...${NC}"
    cd "$PROJECT_DIR"

    for IMG_NAME in server agent; do
        docker buildx build --platform "$REMOTE_PLATFORM" \
            -f "deploy/${IMG_NAME}.Dockerfile" \
            -t "remote-control-${IMG_NAME}:latest" \
            --load .
    done
else
    echo -e "${YELLOW}[1/5] 跳过构建（使用已有镜像）${NC}"
fi

# 检查镜像
for IMG in "$IMAGE_SERVER" "$IMAGE_AGENT"; do
    if ! docker image inspect "$IMG" &>/dev/null; then
        echo -e "${RED}错误: 镜像 $IMG 不存在${NC}"
        exit 1
    fi
done

# ===== 2. 导出镜像 =====
echo -e "${YELLOW}[2/5] 导出镜像...${NC}"
docker save "$IMAGE_SERVER" "$IMAGE_AGENT" | gzip > "$TMP_FILE"
IMAGE_SIZE=$(du -h "$TMP_FILE" | cut -f1)
echo -e "  镜像大小: ${GREEN}${IMAGE_SIZE}${NC}"

# ===== 3. 传输到服务器 =====
echo -e "${YELLOW}[3/5] 传输到服务器...${NC}"
scp -q "$TMP_FILE" "${REMOTE_USER}@${REMOTE_HOST}:/tmp/rc-images.tar.gz"
scp -q "$SCRIPT_DIR/docker-compose.yml" "${REMOTE_USER}@${REMOTE_HOST}:/tmp/rc-compose.yml"
rm -f "$TMP_FILE"

# ===== 4. 远端加载并启动 =====
echo -e "${YELLOW}[4/5] 远端加载并启动...${NC}"
ssh "${REMOTE_USER}@${REMOTE_HOST}" \
    "REMOTE_DEPLOY_DIR='${REMOTE_DEPLOY_DIR}' bash -s" <<'REMOTE_SCRIPT'
set -euo pipefail

echo "  加载镜像..."
docker load < /tmp/rc-images.tar.gz
rm -f /tmp/rc-images.tar.gz

mkdir -p "${REMOTE_DEPLOY_DIR}/deploy"
mv /tmp/rc-compose.yml "${REMOTE_DEPLOY_DIR}/deploy/docker-compose.yml"

cd "${REMOTE_DEPLOY_DIR}"
docker compose -f deploy/docker-compose.yml down 2>/dev/null || true
docker compose -f deploy/docker-compose.yml up -d

echo "  等待服务启动..."
for i in $(seq 1 15); do
    HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' http://localhost/rc/health 2>/dev/null || echo 000)
    if [ "$HTTP_CODE" = "200" ]; then
        echo "  健康检查通过"
        exit 0
    fi
    sleep 2
done
echo "HEALTH_CHECK_FAILED"
REMOTE_SCRIPT

# ===== 5. 输出结果 =====
echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                  部署完成！                              ║${NC}"
echo -e "${GREEN}╠═══════════════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  前端:  http://${REMOTE_HOST}/rc/                        ${NC}"
echo -e "${GREEN}║  健康:  http://${REMOTE_HOST}/rc/health                  ${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
