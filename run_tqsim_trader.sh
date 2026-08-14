#!/bin/bash
# 15 大商品期货 TqSim 虚拟盘交易系统启动脚本

PROJECT_DIR="/Users/tang/PycharmProjects/pythonProject/lianghua"
LOG_DIR="$PROJECT_DIR/data/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/futures_live_trader.log"

echo "================================================================================"
echo "🚀 启动【15 大商品期货 LightGBM + PPO 虚拟仿真盘 (TqSim)】实时交易系统..."
echo "================================================================================"
echo "📁 日志输出路径: $LOG_FILE"
echo "📁 状态持久化文件: $PROJECT_DIR/data/futures_live_state.json"
echo "================================================================================"

cd "$PROJECT_DIR"
PYTHONUNBUFFERED=1 python3 code/futures_live_trader.py >> "$LOG_FILE" 2>&1 &
PID=$!
echo "🟢 交易引擎后台运行中，PID: $PID"
echo $PID > "$LOG_DIR/trader.pid"
echo "👉 查看实时交易日志命令: tail -f data/logs/futures_live_trader.log"
