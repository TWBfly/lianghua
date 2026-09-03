#!/usr/bin/env bash
# 一键启动 Tauri + TradingView 量化交易工作站开发环境
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="${SCRIPT_DIR}/desktop"

echo "========================================================"
echo "  🔮 启动【天极·太冲·归元】Tauri 量化交易工作站 (Dev Mode) "
echo "========================================================"

cd "${DESKTOP_DIR}"

if [ "$1" == "web" ]; then
    echo "🌐 以纯浏览器模式启动 (端口 1420)..."
    pnpm dev
else
    echo "🖥️  以原生 macOS 桌面模式启动 (Tauri 2.0 + HMR 热重载)..."
    pnpm tauri dev
fi
