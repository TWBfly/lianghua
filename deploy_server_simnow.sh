#!/usr/bin/env bash
# deploy_server_simnow.sh — 一键部署与后台挂机启动脚本 (支持 Linux 服务器与 macOS)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "================================================================================"
echo "🚀 [Lianghua x vn.py x SimNow] 服务器自动化部署与虚拟盘挂机启动器"
echo "================================================================================"

# 1. 检查 Python 与依赖
if ! command -v python3 &>/dev/null; then
    echo "❌ 错误: 未检测到 python3，请先安装 Python 3.10+"
    exit 1
fi

echo "✅ Python 环境就绪: $(python3 -V)"

# 2. 检查 .env 配置文件
if [ ! -f ".env" ]; then
    echo "⚠️ 警告: 未找到 .env 文件，正在从模板生成..."
    cat <<EOF > .env
SIMNOW_USER=your_simnow_account
SIMNOW_PASSWORD=your_simnow_password
SIMNOW_BROKER=9999
SIMNOW_APPID=simnow_client_test
SIMNOW_AUTHCODE=0000000000000000
SIMNOW_MD_ADDRESS=tcp://180.168.146.187:10211
SIMNOW_TD_ADDRESS=tcp://180.168.146.187:10201
EOF
    echo "✅ .env 文件已生成，请配置账户后重新执行"
fi

# 3. 创建数据与日志目录
mkdir -p data/logs

# 4. 检查是否已有挂机进程在运行
PID=$(pgrep -f "run_simnow_paper_trader.py" || true)
if [ -n "$PID" ]; then
    echo "🔄 检测到已有挂机进程运行中 (PID: $PID)，正在平滑重启..."
    kill -15 "$PID" 2>/dev/null || true
    sleep 2
fi

# 5. 后台启动挂机守护进程
echo "🟢 正在启动 SimNow 24h 虚拟盘挂机守护引擎..."
nohup python3 code/run_simnow_paper_trader.py --symbol ag2612.SHFE --strategy tianji > data/logs/simnow_daemon_stdout.log 2>&1 &
NEW_PID=$!

echo "================================================================================"
echo "🎉 挂机守护进程已成功在后台启动！"
echo "  ├─ 进程 PID:    $NEW_PID"
echo "  ├─ 实时日志:    tail -f data/logs/vnpy_paper_trader.log"
echo "  ├─ 交易台账:    cat data/logs/vnpy_daily_trades.csv"
echo "  └─ 状态文件:    cat data/vnpy_paper_state.json"
echo "================================================================================"
