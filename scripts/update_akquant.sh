#!/usr/bin/env bash
# ==============================================================================
# update_akquant.sh — AKQuant 上游代码自动更新与状态同步脚本
#
# 使用方法：
#   ./scripts/update_akquant.sh
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AKQUANT_DIR="$PROJECT_ROOT/akquant"

echo "========================================================"
echo "          AKQuant 上游更新与解耦同步工具                "
echo "========================================================"

if [ ! -d "$AKQUANT_DIR/.git" ]; then
    echo "❌ 错误: 未在 $AKQUANT_DIR 检测到有效的 git 仓库！"
    echo "正在尝试重新克隆..."
    git clone https://github.com/akfamily/akquant "$AKQUANT_DIR"
fi

cd "$AKQUANT_DIR"

echo "📦 正在拉取 upstream/origin 最新提交..."
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git fetch origin
git pull origin "$CURRENT_BRANCH"

COMMIT_HASH=$(git rev-parse --short HEAD)
COMMIT_MSG=$(git log -1 --pretty=%B | head -n 1)
LATEST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "None")

echo "--------------------------------------------------------"
echo "✅ AKQuant 代码库更新完成！"
echo "   分支: $CURRENT_BRANCH"
echo "   最新标签: $LATEST_TAG"
echo "   最新 Commit: $COMMIT_HASH ($COMMIT_MSG)"
echo "--------------------------------------------------------"

echo "💡 提示: 若需构建本地 Rust 高性能扩展，可在有网络或安装环境后运行:"
echo "   1. 使用 Pip 直接安装发布版本 (推荐):"
echo "      pip install akquant --upgrade"
echo "   2. 或进入 akquant 目录本地编译:"
echo "      cd akquant && maturin develop --release"
echo "========================================================"
