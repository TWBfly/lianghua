"""
A-Share Quantitative Strategy Engine - 15-Symbol Real-Time Futures Live Dashboard & Web Monitor
【第一性原理：15 大商品期货 LightGBM + PPO 实时监控大屏与 K线买卖点精准可视化 UI 服务】
访问地址: http://127.0.0.1:8090
"""

import os
import sys
import json
import time
import psutil
import sqlite3
import datetime
import numpy as np
import pandas as pd
from pathlib import Path
from flask import Flask, jsonify, request, render_template_string

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "code"))

from symbol_strategies.decoupled_symbol_engines import (
    DecoupledSymbolStrategyRunner,
    SYMBOL_CONFIGS,
    DB_PATH
)

app = Flask(__name__)

TRADING_DISABLED_REASON = (
    "15m futures research has not passed the required gates; "
    "legacy live and backtest dashboard sources are isolated"
)


def disabled_response():
    return jsonify({
        "status": "TRADING_DISABLED",
        "disabled_reason": TRADING_DISABLED_REASON,
    }), 503

PID_FILE = PROJECT_ROOT / "data/logs/trader.pid"
LOG_FILE = PROJECT_ROOT / "data/logs/futures_live_trader.log"
STATE_FILE = PROJECT_ROOT / "data/futures_live_state.json"
LIVE_TRADES_FILE = PROJECT_ROOT / "data/futures_live_trades_history.json"

runner = DecoupledSymbolStrategyRunner(db_path=str(DB_PATH))

# 内存缓存回测与交易数据，避免每次请求重复计算
BACKTEST_CACHE = {}


def get_cached_backtest(symbol: str):
    if symbol not in BACKTEST_CACHE:
        try:
            res = runner.run_single_symbol_backtest(symbol)
            BACKTEST_CACHE[symbol] = res
        except Exception as e:
            print(f"回测计算错误 [{symbol}]: {e}")
            return None
    return BACKTEST_CACHE.get(symbol)


def get_trader_status():
    running = False
    pid = None
    cpu_percent = 0.0
    mem_mb = 0.0
    start_time_str = "服务守护运行中"

    # 优先检查 systemctl 或进程名
    try:
        for p in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time', 'memory_info']):
            cmdline = p.info.get('cmdline') or []
            if any('futures_live_trader.py' in arg for arg in cmdline):
                running = True
                pid = p.info['pid']
                proc = psutil.Process(pid)
                cpu_percent = round(proc.cpu_percent(interval=0.05), 1)
                mem_mb = round(proc.memory_info().rss / (1024 * 1024), 1)
                start_time_str = datetime.datetime.fromtimestamp(proc.create_time()).strftime("%Y-%m-%d %H:%M:%S")
                break
    except Exception:
        pass

    state_data = {}
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state_data = json.load(f)
        except Exception:
            pass

    # 汇总各品种状态
    symbols_info = []
    active_positions = 0
    total_unrealized = 0.0

    for sym, cfg in SYMBOL_CONFIGS.items():
        s = state_data.get(sym, {})
        pos = s.get("pos", 0)
        lots = s.get("lots", 0)
        entry_p = s.get("entry_price", 0.0)
        curr_p = s.get("highest_price", entry_p) if pos == 1 else s.get("lowest_price", entry_p)
        
        # 估算浮盈
        unrealized_pnl = 0.0
        if pos == 1 and entry_p > 0:
            unrealized_pnl = (curr_p - entry_p) * cfg["multiplier"] * lots
            active_positions += 1
        elif pos == -1 and entry_p > 0:
            unrealized_pnl = (entry_p - curr_p) * cfg["multiplier"] * lots
            active_positions += 1
        total_unrealized += unrealized_pnl

        symbols_info.append({
            "symbol": sym,
            "name": cfg["name"],
            "category": cfg["category"],
            "pos": pos,
            "lots": lots,
            "entry_price": entry_p,
            "entry_time": s.get("entry_time", "-"),
            "stop_loss": round(s.get("stop_loss", 0.0), 2),
            "highest_price": s.get("highest_price", 0.0),
            "lowest_price": s.get("lowest_price", 0.0),
            "half_locked": s.get("half_locked", False),
            "last_processed_dt": s.get("last_processed_dt", "-"),
            "prob_thresh": cfg["prob_thresh"],
            "unrealized_pnl": round(unrealized_pnl, 2)
        })

    # 计算总体绩效指标
    total_trades_all = 0
    total_wins_all = 0
    total_pnl_all = 0.0

    for sym in SYMBOL_CONFIGS.keys():
        b_res = get_cached_backtest(sym)
        if b_res:
            total_trades_all += b_res["total_trades"]
            total_wins_all += len([t for t in b_res["trades"] if t["pnl_rmb"] > 0])
            total_pnl_all += b_res["net_profit_rmb"]

    overall_win_rate = round(total_wins_all / total_trades_all * 100, 1) if total_trades_all > 0 else 0.0

    return {
        "running": running,
        "pid": pid,
        "cpu_percent": cpu_percent,
        "memory_mb": mem_mb,
        "start_time": start_time_str,
        "server_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "initial_balance": 1000000.0,
        "current_equity": round(1000000.0 + total_pnl_all + total_unrealized, 2),
        "total_unrealized": round(total_unrealized, 2),
        "total_profit": round(total_pnl_all, 2),
        "overall_win_rate": overall_win_rate,
        "total_trades_count": total_trades_all,
        "active_positions": active_positions,
        "total_symbols": len(SYMBOL_CONFIGS),
        "symbols": symbols_info
    }


@app.route("/api/status")
def api_status():
    return disabled_response()


@app.route("/api/logs")
def api_logs():
    return disabled_response()
    lines = []
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                all_lines = f.readlines()
                lines = all_lines[-100:]  # 最近 100 行
        except Exception as e:
            lines = [f"读取日志错误: {e}"]
    return jsonify({"logs": "".join(lines)})


@app.route("/api/kline")
def api_kline():
    return disabled_response()
    symbol = request.args.get("symbol", "AG_IDX")
    if symbol not in SYMBOL_CONFIGS:
        return jsonify({"error": f"未知品种 {symbol}"}), 400

    cfg = SYMBOL_CONFIGS[symbol]
    try:
        df_15m = runner.load_symbol_data(symbol)
        df_merged = runner.compute_features_and_labels(df_15m, cfg)
        
        # 取最近 200 根 15m K线进行高精度展示
        recent_df = df_merged.tail(200).copy().reset_index(drop=True)
        
        res = get_cached_backtest(symbol)
        trades = res["trades"] if res else []
        
        categories = recent_df["datetime"].dt.strftime("%Y-%m-%d %H:%M").tolist()
        k_values = recent_df[["open", "close", "low", "high"]].values.tolist()
        volumes = recent_df["volume"].tolist()
        squeezes = [round(float(x), 3) if not np.isnan(x) else 1.0 for x in recent_df["squeeze"].tolist()]
        atr_14 = [round(float(x), 2) if not np.isnan(x) else 0.0 for x in recent_df["atr_14"].tolist()]

        # 筛选落在当前窗口内的交易标记点
        recent_start_dt = recent_df["datetime"].iloc[0].strftime("%Y-%m-%d %H:%M:%S")
        recent_end_dt = recent_df["datetime"].iloc[-1].strftime("%Y-%m-%d %H:%M:%S")

        trade_markers = []
        for t in trades:
            e_dt = t.get("entry_dt", "")
            x_dt = t.get("exit_dt", "")
            e_dt_short = e_dt[:16] if len(e_dt) >= 16 else e_dt
            x_dt_short = x_dt[:16] if len(x_dt) >= 16 else x_dt

            # 开仓买入点标注
            if e_dt and recent_start_dt <= e_dt <= recent_end_dt:
                trade_markers.append({
                    "coord": [e_dt_short, t.get("entry_price", 0.0)],
                    "value": "🟢 买多" if "LONG" in t.get("type", "") else "🔴 买空",
                    "action": "ENTRY",
                    "side": t.get("pos_side", ""),
                    "price": t.get("entry_price", 0.0),
                    "time": e_dt,
                    "reason": t.get("entry_reason", "模型多指标共振开仓"),
                    "lots": t.get("lots", 1),
                    "itemStyle": {"color": "#3fb950" if "LONG" in t.get("type", "") else "#f85149"}
                })

            # 平仓卖出点标注
            if x_dt and recent_start_dt <= x_dt <= recent_end_dt:
                pnl = t.get("pnl_rmb", 0.0)
                is_lock = "PPO_LOCK" in t.get("type", "")
                val_str = "🟡 减半锁利" if is_lock else ("🎯 止盈" if pnl > 0 else "🛑 止损")
                color = "#d29922" if is_lock else ("#3fb950" if pnl > 0 else "#da3633")

                trade_markers.append({
                    "coord": [x_dt_short, t.get("exit_price", 0.0)],
                    "value": val_str,
                    "action": "EXIT",
                    "side": t.get("pos_side", ""),
                    "price": t.get("exit_price", 0.0),
                    "time": x_dt,
                    "reason": t.get("exit_reason", "触发自适应出场"),
                    "pnl": pnl,
                    "return_pct": t.get("return_pct", 0.0),
                    "lots": t.get("lots", 1),
                    "itemStyle": {"color": color}
                })

        return jsonify({
            "symbol": symbol,
            "name": cfg["name"],
            "category": cfg["category"],
            "categories": categories,
            "k_values": k_values,
            "volumes": volumes,
            "squeezes": squeezes,
            "atr_14": atr_14,
            "trade_markers": trade_markers,
            "summary": {
                "win_rate": res["win_rate_pct"] if res else 0.0,
                "pl_ratio": res["profit_loss_ratio"] if res else 0.0,
                "return_pct": res["total_return_pct"] if res else 0.0,
                "net_profit": res["net_profit_rmb"] if res else 0.0,
                "trades_count": res["total_trades"] if res else 0,
                "max_dd": res["max_drawdown_pct"] if res else 0.0,
                "sharpe": res["sharpe_ratio"] if res else 0.0
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/trades")
def api_trades():
    return disabled_response()
    symbol_filter = request.args.get("symbol", "ALL")
    all_trades = []

    symbols_to_query = [symbol_filter] if symbol_filter in SYMBOL_CONFIGS else list(SYMBOL_CONFIGS.keys())

    for sym in symbols_to_query:
        b_res = get_cached_backtest(sym)
        if b_res:
            all_trades.extend(b_res["trades"])

    # 按平仓时间/开仓时间倒序排列（最近的排最前）
    all_trades = sorted(all_trades, key=lambda x: x.get("exit_dt") or x.get("entry_dt") or "", reverse=True)

    # 限制返回前 150 条以保证流畅
    return jsonify({
        "total": len(all_trades),
        "trades": all_trades[:150]
    })


@app.route("/api/trader/restart", methods=["POST"])
def api_trader_restart():
    return disabled_response()


DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>天勤量化 · 15大商品期货 15m 机器学习仿真交易大屏</title>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
  <style>
    :root {
      --bg: #090d13;
      --card-bg: #111722;
      --card-inner: #17202e;
      --border: #232f3e;
      --border-focus: #388bfd;
      --text: #c5d1de;
      --text-bright: #ffffff;
      --text-muted: #7d8b99;
      --green: #238636;
      --green-bright: #3fb950;
      --green-glow: rgba(63, 185, 80, 0.15);
      --red: #da3633;
      --red-bright: #f85149;
      --red-glow: rgba(248, 81, 73, 0.15);
      --blue: #58a6ff;
      --gold: #d29922;
      --purple: #bc8cff;
      --accent: #1f6feb;
    }
    * { margin: 0; padding: 0; box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif; }
    body { background: var(--bg); color: var(--text); padding: 16px; font-size: 13px; min-height: 100vh; }

    /* 顶部导航栏 */
    .top-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 20px; background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px; margin-bottom: 16px; }
    .header-title { display: flex; align-items: center; gap: 12px; }
    .header-title h1 { font-size: 18px; font-weight: 700; color: var(--text-bright); letter-spacing: 0.5px; }
    .badge-live { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; padding: 3px 10px; border-radius: 20px; font-weight: 600; background: var(--green-glow); color: var(--green-bright); border: 1px solid rgba(63, 185, 80, 0.4); }
    .pulse-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--green-bright); box-shadow: 0 0 8px var(--green-bright); animation: pulse 1.6s infinite; }
    @keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.3; transform: scale(1.3); } }

    .header-actions { display: flex; align-items: center; gap: 10px; }
    .btn { background: var(--card-inner); border: 1px solid var(--border); color: var(--text-bright); padding: 6px 14px; border-radius: 6px; font-size: 12px; cursor: pointer; transition: all 0.2s; font-weight: 500; display: inline-flex; align-items: center; gap: 6px; }
    .btn:hover { background: var(--accent); border-color: var(--blue); }
    .btn-primary { background: #1f6feb; border-color: #388bfd; }
    .btn-primary:hover { background: #388bfd; }

    /* 核心数据卡片栏 */
    .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-bottom: 16px; }
    .stat-card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px; }
    .stat-label { font-size: 11px; color: var(--text-muted); margin-bottom: 4px; display: flex; justify-content: space-between; }
    .stat-val { font-size: 20px; font-weight: 700; color: var(--text-bright); font-family: "JetBrains Mono", "SF Mono", Consolas, monospace; }
    .stat-val.pos { color: var(--green-bright); }
    .stat-val.neg { color: var(--red-bright); }

    /* 主布局容器 */
    .main-layout { display: grid; grid-template-columns: 320px 1fr; gap: 16px; margin-bottom: 16px; }
    @media (max-width: 1280px) { .main-layout { grid-template-columns: 1fr; } }

    .panel { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; display: flex; flex-direction: column; }
    .panel-header { padding: 10px 16px; background: rgba(255,255,255,0.02); border-bottom: 1px solid var(--border); font-weight: 600; color: var(--text-bright); display: flex; justify-content: space-between; align-items: center; font-size: 13px; }

    /* 左侧品种列表 */
    .symbol-list { overflow-y: auto; max-height: 720px; }
    .symbol-card { padding: 12px 14px; border-bottom: 1px solid var(--border); cursor: pointer; transition: all 0.15s; display: flex; justify-content: space-between; align-items: center; }
    .symbol-card:hover { background: rgba(88, 166, 255, 0.05); }
    .symbol-card.active { background: rgba(31, 111, 235, 0.15); border-left: 3px solid var(--blue); }
    .sym-name-box { display: flex; flex-direction: column; gap: 2px; }
    .sym-title { font-weight: 600; color: var(--text-bright); font-size: 14px; }
    .sym-code { font-size: 11px; color: var(--text-muted); font-family: monospace; }
    .sym-tag { font-size: 10px; padding: 2px 6px; border-radius: 4px; background: var(--card-inner); color: var(--text-muted); margin-left: 6px; }
    .pos-pill { font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 12px; }
    .pos-pill.long { background: var(--green-glow); color: var(--green-bright); border: 1px solid var(--green); }
    .pos-pill.short { background: var(--red-glow); color: var(--red-bright); border: 1px solid var(--red); }
    .pos-pill.none { background: rgba(255,255,255,0.04); color: var(--text-muted); }

    /* 右侧 K 线大屏 */
    .chart-container { width: 100%; height: 500px; }
    .chart-info-bar { display: flex; gap: 20px; padding: 8px 16px; background: var(--card-inner); border-bottom: 1px solid var(--border); font-size: 12px; }
    .chart-info-item span { color: var(--text-muted); margin-right: 4px; }
    .chart-info-item b { color: var(--text-bright); font-family: monospace; }

    /* 交易流水与原因展示表 */
    .table-container { width: 100%; overflow-x: auto; max-height: 400px; }
    table.data-table { width: 100%; border-collapse: collapse; text-align: left; font-size: 12px; }
    table.data-table th { background: rgba(255,255,255,0.03); padding: 10px 12px; border-bottom: 1px solid var(--border); color: var(--text-muted); font-weight: 600; position: sticky; top: 0; z-index: 2; }
    table.data-table td { padding: 9px 12px; border-bottom: 1px solid var(--border); white-space: nowrap; }
    table.data-table tr:hover td { background: rgba(255,255,255,0.02); }

    .tag-dir { display: inline-block; padding: 2px 6px; border-radius: 4px; font-weight: 600; font-size: 11px; }
    .tag-dir.long { background: var(--green-glow); color: var(--green-bright); }
    .tag-dir.short { background: var(--red-glow); color: var(--red-bright); }
    .tag-pnl.win { color: var(--green-bright); font-weight: 700; font-family: monospace; }
    .tag-pnl.loss { color: var(--red-bright); font-weight: 700; font-family: monospace; }

    .reason-box { font-size: 11px; color: var(--text); background: rgba(255,255,255,0.03); padding: 4px 8px; border-radius: 4px; border: 1px solid rgba(255,255,255,0.05); max-width: 320px; white-space: normal; line-height: 1.4; }
    .reason-box b { color: var(--blue); }
    .reason-box.exit b { color: var(--gold); }

    /* 日志控制台模态框 */
    .log-terminal { background: #06090e; color: #7ee787; font-family: "JetBrains Mono", Consolas, monospace; font-size: 11px; padding: 12px; border-radius: 6px; max-height: 220px; overflow-y: auto; white-space: pre-wrap; line-height: 1.5; border: 1px solid var(--border); }
  </style>
</head>
<body>

  <!-- 顶部导航 -->
  <div class="top-header">
    <div class="header-title">
      <h1>📊 15大商品期货 15m 机器学习仿真交易大屏</h1>
      <span class="badge-live"><span class="pulse-dot"></span> <span id="engineStatus">TqSim 仿真运行中</span></span>
      <span style="font-size: 12px; color: var(--text-muted);" id="serverTime"></span>
    </div>
    <div class="header-actions">
      <button class="btn" onclick="refreshAll()"><span style="color: var(--blue);">🔄</span> 刷新数据</button>
      <button class="btn btn-primary" onclick="restartEngine()">重启交易引擎</button>
    </div>
  </div>

  <!-- 全局统计卡片 -->
  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-label">账户初始资金 (TqSim)</div>
      <div class="stat-val" id="initBalance">¥1,000,000</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">当前账户动态净值</div>
      <div class="stat-val pos" id="currentEquity">¥1,000,000</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">15品种综合胜率</div>
      <div class="stat-val pos" id="winRate">-%</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">活跃持仓品种数</div>
      <div class="stat-val" id="activePosCount" style="color: var(--blue);">0 / 15</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">交易总次数 (Walk-Forward)</div>
      <div class="stat-val" id="totalTrades">0 次</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">当前持仓浮动盈亏</div>
      <div class="stat-val" id="unrealizedPnl">¥0.00</div>
    </div>
  </div>

  <!-- 主屏布局: 左侧品种选择 + 右侧 K 线买卖点大屏 -->
  <div class="main-layout">
    
    <!-- 左侧品种列表 -->
    <div class="panel">
      <div class="panel-header">
        <span>📈 15 大期货主力品种监控</span>
        <span style="font-size: 11px; color: var(--text-muted);">15分钟周期</span>
      </div>
      <div class="symbol-list" id="symbolList">
        <!-- 动态渲染 -->
      </div>
    </div>

    <!-- 右侧图表与指标区 -->
    <div class="panel">
      <div class="panel-header">
        <span id="chartTitle">K 线买卖点与特征共振可视化</span>
        <div style="font-size: 11px; color: var(--text-muted); display: flex; gap: 14px;">
          <span>🟢 买多 / 🔴 买空</span>
          <span>🟡 PPO 减半锁利</span>
          <span>🎯 移动止盈 / 🛑 硬止损</span>
        </div>
      </div>

      <!-- 单品种回测与统计详情条 -->
      <div class="chart-info-bar" id="chartInfoBar">
        <div class="chart-info-item"><span>品种胜率:</span> <b id="symWinRate">-%</b></div>
        <div class="chart-info-item"><span>盈亏比:</span> <b id="symPLRatio">-</b></div>
        <div class="chart-info-item"><span>策略总收益:</span> <b id="symReturn">-%</b></div>
        <div class="chart-info-item"><span>最大回撤:</span> <b id="symMaxDD">-%</b></div>
        <div class="chart-info-item"><span>夏普比率:</span> <b id="symSharpe">-</b></div>
      </div>

      <!-- ECharts 主图 -->
      <div class="chart-container" id="klineChart"></div>
    </div>

  </div>

  <!-- 底部交易明细与买卖原因分析流水表 -->
  <div class="panel" style="margin-bottom: 16px;">
    <div class="panel-header">
      <span>📝 交易开平仓流水与【买卖原因】深度解析</span>
      <div style="display: flex; gap: 8px;">
        <button class="btn" style="padding: 3px 8px;" onclick="loadTrades('ALL')">全部品种</button>
        <button class="btn" style="padding: 3px 8px;" onclick="loadTrades(currentSymbol)">当前选中品种</button>
      </div>
    </div>
    <div class="table-container">
      <table class="data-table">
        <thead>
          <tr>
            <th>品种</th>
            <th>方向</th>
            <th>开仓时间</th>
            <th>开仓价</th>
            <th style="min-width: 260px;">🟢 买入 / 开仓原因 (模型特征解析)</th>
            <th>平仓时间</th>
            <th>平仓价</th>
            <th style="min-width: 260px;">🔴 卖出 / 平仓原因 (PPO & 止损止盈)</th>
            <th>手数</th>
            <th>盈亏(元)</th>
            <th>收益率</th>
          </tr>
        </thead>
        <tbody id="tradesTableBody">
          <tr><td colspan="11" style="text-align: center; color: var(--text-muted); padding: 20px;">正在加载交易流水...</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- 实时运行日志终端 -->
  <div class="panel">
    <div class="panel-header">
      <span>🖥️ TqSdk 实时事件驱动运行日志 (futures_live_trader.log)</span>
      <span style="font-size: 11px; color: var(--text-muted);">自动监听 15m Bar 完结事件</span>
    </div>
    <div style="padding: 12px;">
      <div class="log-terminal" id="logTerminal">正在读取实时日志...</div>
    </div>
  </div>

  <script>
    let currentSymbol = "AG_IDX";
    let chartInstance = null;

    // 初始化 ECharts
    function initChart() {
      const dom = document.getElementById("klineChart");
      chartInstance = echarts.init(dom, 'dark');
      window.addEventListener("resize", () => chartInstance.resize());
    }

    // 格式化数字
    function formatMoney(num) {
      return '¥' + Number(num).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    // 加载全局状态
    async function loadStatus() {
      try {
        const res = await fetch("/api/status");
        const data = await res.json();

        document.getElementById("serverTime").innerText = "服务器时间: " + data.server_time;
        document.getElementById("engineStatus").innerText = data.running ? `TqSim 运行中 (PID: ${data.pid || '-'})` : "交易引擎未启动";
        document.getElementById("currentEquity").innerText = formatMoney(data.current_equity);
        document.getElementById("winRate").innerText = data.overall_win_rate + '%';
        document.getElementById("activePosCount").innerText = `${data.active_positions} / ${data.total_symbols}`;
        document.getElementById("totalTrades").innerText = data.total_trades_count + ' 次';
        
        const unPnlElem = document.getElementById("unrealizedPnl");
        unPnlElem.innerText = formatMoney(data.total_unrealized);
        unPnlElem.className = 'stat-val ' + (data.total_unrealized >= 0 ? 'pos' : 'neg');

        // 渲染品种列表
        const listContainer = document.getElementById("symbolList");
        listContainer.innerHTML = data.symbols.map(s => {
          let posClass = 'none';
          let posText = '空仓';
          if (s.pos === 1) {
            posClass = 'long';
            posText = `多 ${s.lots}手`;
          } else if (s.pos === -1) {
            posClass = 'short';
            posText = `空 ${s.lots}手`;
          }

          return `
            <div class="symbol-card ${s.symbol === currentSymbol ? 'active' : ''}" onclick="selectSymbol('${s.symbol}')">
              <div class="sym-name-box">
                <div class="sym-title">${s.name} <span class="sym-tag">${s.category}</span></div>
                <div class="sym-code">${s.symbol}</div>
              </div>
              <span class="pos-pill ${posClass}">${posText}</span>
            </div>
          `;
        }).join('');

      } catch (err) {
        console.error("加载状态异常:", err);
      }
    }

    // 选择品种
    function selectSymbol(sym) {
      currentSymbol = sym;
      document.querySelectorAll(".symbol-card").forEach(el => el.classList.remove("active"));
      loadStatus();
      loadKline(currentSymbol);
      loadTrades(currentSymbol);
    }

    // 加载 K 线与买卖点标注
    async function loadKline(sym) {
      if (!chartInstance) initChart();
      chartInstance.showLoading({ color: '#58a6ff', maskColor: 'rgba(9, 13, 19, 0.8)' });

      try {
        const res = await fetch(`/api/kline?symbol=${sym}`);
        const data = await res.json();
        chartInstance.hideLoading();

        if (data.error) {
          alert("加载 K 线失败: " + data.error);
          return;
        }

        document.getElementById("chartTitle").innerText = `📈 【${data.name} (${data.symbol})】15m K线买卖点与特征指标`;
        document.getElementById("symWinRate").innerText = data.summary.win_rate + '%';
        document.getElementById("symPLRatio").innerText = data.summary.pl_ratio;
        document.getElementById("symReturn").innerText = '+' + data.summary.return_pct + '%';
        document.getElementById("symMaxDD").innerText = data.summary.max_dd + '%';
        document.getElementById("symSharpe").innerText = data.summary.sharpe;

        // 构建买卖标记点
        const markPointData = data.trade_markers.map(m => {
          return {
            name: m.value,
            coord: m.coord,
            value: m.value,
            itemStyle: m.itemStyle,
            tooltip: {
              formatter: () => {
                if (m.action === "ENTRY") {
                  return `
                    <div style="font-size:12px; line-height:1.6;">
                      <b style="color:${m.itemStyle.color};">${m.value} [开仓]</b><br/>
                      <b>时间:</b> ${m.time}<br/>
                      <b>价格:</b> ${m.price}<br/>
                      <b>手数:</b> ${m.lots} 手<br/>
                      <hr style="border:0;border-top:1px solid #444;margin:4px 0;"/>
                      <b style="color:#58a6ff;">🟢 买入原因:</b><br/>
                      <span style="color:#c5d1de;">${m.reason}</span>
                    </div>
                  `;
                } else {
                  return `
                    <div style="font-size:12px; line-height:1.6;">
                      <b style="color:${m.itemStyle.color};">${m.value} [平仓]</b><br/>
                      <b>时间:</b> ${m.time}<br/>
                      <b>价格:</b> ${m.price}<br/>
                      <b>盈亏:</b> <span style="color:${m.pnl >= 0 ? '#3fb950':'#f85149'};">${m.pnl > 0 ? '+':''}${m.pnl} 元 (${m.return_pct}%)</span><br/>
                      <hr style="border:0;border-top:1px solid #444;margin:4px 0;"/>
                      <b style="color:#d29922;">🔴 卖出原因:</b><br/>
                      <span style="color:#c5d1de;">${m.reason}</span>
                    </div>
                  `;
                }
              }
            }
          };
        });

        const option = {
          backgroundColor: '#111722',
          animation: false,
          tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'cross' },
            backgroundColor: '#17202e',
            borderColor: '#30363d',
            textStyle: { color: '#c5d1de' }
          },
          axisPointer: { link: [{ xAxisIndex: 'all' }] },
          grid: [
            { left: '4%', right: '3%', top: '8%', height: '52%' },
            { left: '4%', right: '3%', top: '64%', height: '14%' },
            { left: '4%', right: '3%', top: '81%', height: '12%' }
          ],
          xAxis: [
            { type: 'category', data: data.categories, scale: true, boundaryGap: false, axisLine: { lineStyle: { color: '#30363d' } } },
            { type: 'category', gridIndex: 1, data: data.categories, axisLabel: { show: false } },
            { type: 'category', gridIndex: 2, data: data.categories, axisLabel: { show: false } }
          ],
          yAxis: [
            { scale: true, splitArea: { show: false }, splitLine: { lineStyle: { color: '#1c2430' } } },
            { gridIndex: 1, scale: true, splitLine: { show: false } },
            { gridIndex: 2, scale: true, splitLine: { show: false } }
          ],
          dataZoom: [
            { type: 'inside', xAxisIndex: [0, 1, 2], start: 40, end: 100 },
            { type: 'slider', xAxisIndex: [0, 1, 2], top: '95%', height: 16 }
          ],
          series: [
            {
              name: '15m K线',
              type: 'candlestick',
              data: data.k_values,
              itemStyle: {
                color: '#f85149',
                color0: '#3fb950',
                borderColor: '#f85149',
                borderColor0: '#3fb950'
              },
              markPoint: {
                data: markPointData,
                symbolSize: 45
              }
            },
            {
              name: '成交量',
              type: 'bar',
              xAxisIndex: 1,
              yAxisIndex: 1,
              data: data.volumes,
              itemStyle: { color: '#1f6feb' }
            },
            {
              name: 'Squeeze 挤压比',
              type: 'line',
              xAxisIndex: 2,
              yAxisIndex: 2,
              data: data.squeezes,
              lineStyle: { color: '#d29922', width: 1.5 }
            }
          ]
        };

        chartInstance.setOption(option, true);

      } catch (err) {
        console.error("加载 K 线异常:", err);
      }
    }

    // 加载交易流水与原因表
    async function loadTrades(sym) {
      try {
        const res = await fetch(`/api/trades?symbol=${sym}`);
        const data = await res.json();

        const tbody = document.getElementById("tradesTableBody");
        if (!data.trades || data.trades.length === 0) {
          tbody.innerHTML = `<tr><td colspan="11" style="text-align: center; color: var(--text-muted); padding: 20px;">暂无 ${sym} 交易记录</td></tr>`;
          return;
        }

        tbody.innerHTML = data.trades.map(t => {
          const isLong = (t.pos_side || "").includes("多") || (t.type || "").includes("LONG");
          const pnlClass = t.pnl_rmb >= 0 ? 'win' : 'loss';
          const pnlSign = t.pnl_rmb > 0 ? '+' : '';

          return `
            <tr>
              <td><b>${t.name || '-'}</b> <span style="font-size:10px; color:var(--text-muted);">${t.symbol || ''}</span></td>
              <td><span class="tag-dir ${isLong ? 'long' : 'short'}">${t.pos_side || (isLong ? '做多' : '做空')}</span></td>
              <td>${t.entry_dt || '-'}</td>
              <td style="font-family:monospace;">${t.entry_price || '-'}</td>
              <td>
                <div class="reason-box">
                  ${t.entry_reason ? t.entry_reason.replace(/\\+/g, '<br/><b>+</b> ') : '模型特征共振开仓'}
                </div>
              </td>
              <td>${t.exit_dt || '-'}</td>
              <td style="font-family:monospace;">${t.exit_price || '-'}</td>
              <td>
                <div class="reason-box exit">
                  <b>${t.exit_reason || '动态止盈止损触发'}</b>
                </div>
              </td>
              <td>${t.lots || 1}手</td>
              <td class="tag-pnl ${pnlClass}">${pnlSign}${t.pnl_rmb}</td>
              <td class="tag-pnl ${pnlClass}">${pnlSign}${t.return_pct}%</td>
            </tr>
          `;
        }).join('');

      } catch (err) {
        console.error("加载交易表异常:", err);
      }
    }

    // 读取日志
    async function loadLogs() {
      try {
        const res = await fetch("/api/logs");
        const data = await res.json();
        const term = document.getElementById("logTerminal");
        term.innerText = data.logs || "暂无日志输出";
        term.scrollTop = term.scrollHeight;
      } catch (err) {
        console.error("加载日志异常:", err);
      }
    }

    // 重启引擎
    async function restartEngine() {
      if (!confirm("确定要重启天勤量化交易引擎吗？")) return;
      try {
        const res = await fetch("/api/trader/restart", { method: "POST" });
        const data = await res.json();
        if (data.status === "restarted") {
          alert("✅ 交易引擎重启成功！");
          refreshAll();
        } else {
          alert("❌ 重启失败: " + (data.error || "未知错误"));
        }
      } catch (err) {
        alert("请求异常: " + err);
      }
    }

    // 全量刷新
    function refreshAll() {
      loadStatus();
      loadKline(currentSymbol);
      loadTrades(currentSymbol);
      loadLogs();
    }

    // 页面加载启动
    window.onload = function() {
      initChart();
      refreshAll();
      // 定时 15 秒自动刷新
      setInterval(loadStatus, 15000);
      setInterval(loadLogs, 15000);
    };
  </script>
</body>
</html>
"""


@app.route("/")
def index():
    return disabled_response()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8090, debug=False)
