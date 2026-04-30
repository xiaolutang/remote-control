#!/bin/bash
# =============================================================================
# build-desktop.sh — 联合构建脚本：Agent PyInstaller + Flutter macOS + DMG
# =============================================================================
# 产物：dist/Remote-Control-macOS.dmg
#   内含 rc_client.app/Contents/Resources/agent/rc-agent
#
# 用法：
#   ./build-desktop.sh              # 完整构建
#   ./build-desktop.sh --skip-agent # 跳过 Agent 构建（使用已有 agent/dist/rc-agent）
#   ./build-desktop.sh --skip-flutter # 跳过 Flutter 构建
#   ./build-desktop.sh --dmg-only   # 仅从已有产物生成 DMG
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Colors & Logging
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }
log_step()  { echo -e "\n${BLUE}==> Step $1: $2${NC}"; }

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
AGENT_DIR="$PROJECT_ROOT/agent"
CLIENT_DIR="$PROJECT_ROOT/client"
DIST_DIR="$PROJECT_ROOT/dist"

APP_BUNDLE_NAME="rc_client.app"
FLUTTER_APP_PATH="$CLIENT_DIR/build/macos/Build/Products/Release/$APP_BUNDLE_NAME"
AGENT_BINARY="$AGENT_DIR/dist/rc-agent"
BUNDLE_AGENT_DIR="$FLUTTER_APP_PATH/Contents/Resources/agent"

DMG_NAME="Remote-Control-macOS.dmg"
DMG_VOLUME_NAME="Remote Control"
DMG_OUTPUT="$DIST_DIR/$DMG_NAME"

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
SKIP_AGENT=0
SKIP_FLUTTER=0
DMG_ONLY=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-agent)    SKIP_AGENT=1; shift ;;
        --skip-flutter)  SKIP_FLUTTER=1; shift ;;
        --dmg-only)      DMG_ONLY=1; shift ;;
        -h|--help)
            echo "用法: $0 [--skip-agent] [--skip-flutter] [--dmg-only]"
            echo ""
            echo "选项："
            echo "  --skip-agent    跳过 Agent PyInstaller 构建"
            echo "  --skip-flutter  跳过 Flutter macOS 构建"
            echo "  --dmg-only      仅从已有产物生成 DMG"
            echo "  -h, --help      显示帮助"
            exit 0
            ;;
        *) log_error "未知参数: $1"; exit 1 ;;
    esac
done

# ===========================================================================
# 前置检查
# ===========================================================================
log_step "0" "前置检查 — 验证工具链"

check_tool() {
    local tool="$1"
    local install_hint="$2"
    if command -v "$tool" &>/dev/null; then
        local version
        version=$("$tool" --version 2>/dev/null | head -1 || echo "未知版本")
        log_ok "$tool 可用 ($version)"
        return 0
    else
        log_error "$tool 未找到"
        echo "  安装指引: $install_hint"
        return 1
    fi
}

PREREQ_OK=1

if [[ $DMG_ONLY -eq 0 ]]; then
    if [[ $SKIP_AGENT -eq 0 ]]; then
        check_tool "python3" "https://www.python.org/downloads/" || PREREQ_OK=0
        check_tool "pyinstaller" "python3 -m pip install pyinstaller" || PREREQ_OK=0
    fi
    if [[ $SKIP_FLUTTER -eq 0 ]]; then
        check_tool "flutter" "https://docs.flutter.dev/get-started/install/macos" || PREREQ_OK=0
    fi
fi

# hdiutil 始终需要（即使 --dmg-only）
check_tool "hdiutil" "macOS 内置工具，非 macOS 系统不支持" || PREREQ_OK=0
check_tool "codesign" "安装 Xcode Command Line Tools: xcode-select --install" || PREREQ_OK=0

if [[ $PREREQ_OK -eq 0 ]]; then
    log_error "前置检查失败，请安装缺失的工具后重试"
    exit 1
fi

log_ok "所有前置工具检查通过"

# ===========================================================================
# Step 1: PyInstaller 打包 Agent
# ===========================================================================
if [[ $DMG_ONLY -eq 0 && $SKIP_AGENT -eq 0 ]]; then
    log_step "1" "PyInstaller 打包 Agent"

    cd "$AGENT_DIR"

    log_info "安装 Agent 依赖..."
    python3 -m pip install -r requirements.txt -q

    log_info "执行 pyinstaller rc-agent.spec..."
    python3 -m PyInstaller rc-agent.spec --noconfirm --clean

    if [[ ! -f "$AGENT_BINARY" ]]; then
        log_error "Agent 二进制构建失败: $AGENT_BINARY 不存在"
        exit 1
    fi

    AGENT_SIZE=$(du -h "$AGENT_BINARY" | cut -f1)
    log_ok "Agent 打包完成: $AGENT_BINARY ($AGENT_SIZE)"

    cd "$PROJECT_ROOT"
else
    if [[ $DMG_ONLY -eq 1 || $SKIP_AGENT -eq 1 ]]; then
        if [[ -f "$AGENT_BINARY" ]]; then
            log_warn "跳过 Agent 构建，使用已有: $AGENT_BINARY"
        else
            log_error "Agent 二进制不存在且跳过了构建: $AGENT_BINARY"
            exit 1
        fi
    fi
fi

# ===========================================================================
# Step 2: Flutter build macOS
# ===========================================================================
if [[ $DMG_ONLY -eq 0 && $SKIP_FLUTTER -eq 0 ]]; then
    log_step "2" "Flutter build macOS (Release)"

    cd "$CLIENT_DIR"

    log_info "获取 Flutter 依赖..."
    flutter pub get

    log_info "执行 flutter build macos --release..."
    flutter build macos --release

    if [[ ! -d "$FLUTTER_APP_PATH" ]]; then
        log_error "Flutter 构建失败: $FLUTTER_APP_PATH 不存在"
        exit 1
    fi

    log_ok "Flutter macOS 构建完成: $FLUTTER_APP_PATH"

    cd "$PROJECT_ROOT"
else
    if [[ $DMG_ONLY -eq 1 || $SKIP_FLUTTER -eq 1 ]]; then
        if [[ -d "$FLUTTER_APP_PATH" ]]; then
            log_warn "跳过 Flutter 构建，使用已有: $FLUTTER_APP_PATH"
        else
            log_error "Flutter .app 不存在且跳过了构建: $FLUTTER_APP_PATH"
            exit 1
        fi
    fi
fi

# ===========================================================================
# Step 3: 复制 rc-agent 到 .app bundle
# ===========================================================================
log_step "3" "复制 Agent 到 .app bundle"

mkdir -p "$BUNDLE_AGENT_DIR"
cp "$AGENT_BINARY" "$BUNDLE_AGENT_DIR/rc-agent"
log_ok "复制完成: $BUNDLE_AGENT_DIR/rc-agent"

# ===========================================================================
# Step 4: chmod +x
# ===========================================================================
log_step "4" "设置执行权限"

chmod +x "$BUNDLE_AGENT_DIR/rc-agent"
log_ok "chmod +x 完成"

# ===========================================================================
# Step 5: Ad-hoc code signing
# ===========================================================================
log_step "5" "Ad-hoc code signing (.app bundle)"

codesign --force --deep --sign - "$FLUTTER_APP_PATH"
log_ok "Ad-hoc code signing 完成"

# ===========================================================================
# Step 6: 生成 DMG
# ===========================================================================
log_step "6" "生成 DMG"

mkdir -p "$DIST_DIR"

# 创建临时 staging 目录
DMG_STAGING=$(mktemp -d)
trap 'rm -rf "$DMG_STAGING"' EXIT

log_info "DMG staging: $DMG_STAGING"

# 创建 Applications 符号链接
ln -s /Applications "$DMG_STAGING/Applications"

# 复制 .app 到 staging
cp -R "$FLUTTER_APP_PATH" "$DMG_STAGING/"

# 如果存在旧 DMG，先删除
if [[ -f "$DMG_OUTPUT" ]]; then
    rm -f "$DMG_OUTPUT"
    log_info "删除旧 DMG: $DMG_OUTPUT"
fi

# 生成 DMG
hdiutil create \
    -volname "$DMG_VOLUME_NAME" \
    -srcfolder "$DMG_STAGING" \
    -ov \
    -format UDZO \
    "$DMG_OUTPUT"

DMG_SIZE=$(du -h "$DMG_OUTPUT" | cut -f1)
log_ok "DMG 生成完成: $DMG_OUTPUT ($DMG_SIZE)"

# 清理 staging
rm -rf "$DMG_STAGING"

# ===========================================================================
# Step 7: 自动化验证
# ===========================================================================
log_step "7" "自动化验证"

VERIFY_OK=1

# --- 验证 1: .app bundle 内 rc-agent 存在且有执行权限 ---
log_info "验证 1: .app bundle 内 rc-agent 存在且有执行权限"
if [[ -f "$BUNDLE_AGENT_DIR/rc-agent" ]]; then
    if [[ -x "$BUNDLE_AGENT_DIR/rc-agent" ]]; then
        log_ok "rc-agent 存在且有执行权限"
    else
        log_error "rc-agent 存在但无执行权限"
        VERIFY_OK=0
    fi
else
    log_error "rc-agent 不存在于 $BUNDLE_AGENT_DIR"
    VERIFY_OK=0
fi

# --- 验证 2: codesign --verify ---
log_info "验证 2: codesign --verify"
if codesign --verify --deep --strict "$FLUTTER_APP_PATH" 2>/dev/null; then
    log_ok "codesign --verify 通过"
else
    log_error "codesign --verify 失败"
    VERIFY_OK=0
fi

# --- 验证 3: hdiutil attach 后验证 DMG 内容 ---
log_info "验证 3: DMG 内容完整性验证"
DMG_MOUNT=$(mktemp -d)

if hdiutil attach "$DMG_OUTPUT" -mountpoint "$DMG_MOUNT" -nobrowse -quiet; then
    # 检查 .app 存在
    if [[ -d "$DMG_MOUNT/$APP_BUNDLE_NAME" ]]; then
        log_ok "DMG 内含 $APP_BUNDLE_NAME"
    else
        log_error "DMG 内未找到 $APP_BUNDLE_NAME"
        VERIFY_OK=0
    fi

    # 检查 rc-agent 存在且可执行
    DMG_AGENT="$DMG_MOUNT/$APP_BUNDLE_NAME/Contents/Resources/agent/rc-agent"
    if [[ -f "$DMG_AGENT" ]]; then
        if [[ -x "$DMG_AGENT" ]]; then
            log_ok "DMG 内 rc-agent 存在且有执行权限"
        else
            log_error "DMG 内 rc-agent 无执行权限"
            VERIFY_OK=0
        fi
    else
        log_error "DMG 内未找到 rc-agent: $DMG_AGENT"
        VERIFY_OK=0
    fi

    # 检查 Applications 符号链接
    if [[ -L "$DMG_MOUNT/Applications" ]]; then
        log_ok "DMG 内 Applications 符号链接存在"
    else
        log_error "DMG 内 Applications 符号链接缺失"
        VERIFY_OK=0
    fi

    # 卸载 DMG
    hdiutil detach "$DMG_MOUNT" -quiet
else
    log_error "无法挂载 DMG 进行验证"
    VERIFY_OK=0
fi

# 清理临时挂载点
rm -rf "$DMG_MOUNT" 2>/dev/null || true

# ===========================================================================
# 结果
# ===========================================================================
echo ""
echo "============================================================"
if [[ $VERIFY_OK -eq 1 ]]; then
    log_ok "所有验证通过"
    echo ""
    log_ok "产物: $DMG_OUTPUT ($DMG_SIZE)"
    echo "============================================================"
    exit 0
else
    log_error "部分验证失败，请检查上方日志"
    echo "============================================================"
    exit 1
fi
