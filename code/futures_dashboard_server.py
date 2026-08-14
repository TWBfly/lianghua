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
import subprocess
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

PID_FILE = PROJECT_ROOT / "data/logs/trader.pid"
LOG_FILE = PROJECT_ROOT / "data/logs/futures_live_trader.log"
STATE_FILE = PROJECT_ROOT / "data/futures_live_state.json"

runner = DecoupledSymbolStrategyRunner(db_path=str(DB_PATH))


def is_process_running(pid: int) -> bool:
    try:
        p = psutil.Process(pid)
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except Exception:
        return False


def get_trader_status():
    running = False
    pid = None
    cpu_percent = 0.0
    mem_mb = 0.0
    start_time_str = "未启动"
    
    if PID_FILE.exists():
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
            if is_process_running(pid):
                running = True
                p = psutil.Process(pid)
                cpu_percent = round(p.cpu_percent(interval=0.05), 1)
                mem_mb = round(p.memory_info().rss / (1024 * 1024), 1)
                start_time_str = datetime.datetime.fromtimestamp(p.create_time()).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            running = False

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
    for sym, cfg in SYMBOL_CONFIGS.items():
        s = state_data.get(sym, {})
        pos = s.get("pos", 0)
        if pos != 0:
            active_positions += 1
        symbols_info.append({
            "symbol": sym,
            "name": cfg["name"],
            "category": cfg["category"],
            "pos": pos,
            "lots": s.get("lots", 0),
            "entry_price": s.get("entry_price", 0.0),
            "entry_time": s.get("entry_time", "-"),
            "stop_loss": round(s.get("stop_loss", 0.0), 2),
            "highest_price": s.get("highest_price", 0.0),
            "half_locked": s.get("half_locked", False),
            "last_processed_dt": s.get("last_processed_dt", "-"),
            "prob_thresh": cfg["prob_thresh"],
            "trail_atr": cfg.get("trail_atr", 3.5),
            "be_atr": cfg.get("be_atr", 1.8)
        })

    return {
        "running": running,
        "pid": pid,
        "cpu_percent": cpu_percent,
        "memory_mb": mem_mb,
        "start_time": start_time_str,
        "server_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "active_positions": active_positions,
        "total_symbols": len(SYMBOL_CONFIGS),
        "symbols": symbols_info
    }


@app.route("/api/status")
def api_status():
    return jsonify(get_trader_status())


@app.route("/api/logs")
def api_logs():
    lines = []
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                all_lines = f.readlines()
                lines = all_lines[-80:]  # 最近 80 行
        except Exception as e:
            lines = [f"读取日志错误: {e}"]
    return jsonify({"logs": "".join(lines)})


@app.route("/api/kline")
def api_kline():
    symbol = request.args.get("symbol", "AG_IDX")
    if symbol not in SYMBOL_CONFIGS:
        return jsonify({"error": f"未知品种 {symbol}"}), 400

    cfg = SYMBOL_CONFIGS[symbol]
    try:
        df_15m = runner.load_symbol_data(symbol)
        df_merged = runner.compute_features_and_labels(df_15m, cfg)
        # 获取最近 150 根 15m K线
        recent_df = df_merged.tail(150).copy().reset_index(drop=True)
        
        # 回测获取此品种的真实交易信号点
        res = runner.run_single_symbol_backtest(symbol)
        trades = res["trades"]
        
        # 构建图表数据
        categories = recent_df["datetime"].dt.strftime("%m-%d %H:%M").tolist()
        k_values = recent_df[["open", "close", "low", "high"]].values.tolist()
        volumes = recent_df["volume"].tolist()
        squeezes = [round(float(x), 3) if not np.isnan(x) else 1.0 for x in recent_df["squeeze"].tolist()]
        atr_14 = [round(float(x), 2) if not np.isnan(x) else 0.0 for x in recent_df["atr_14"].tolist()]

        # 筛选落在当前窗口的交易标记
        recent_start_dt = recent_df["datetime"].iloc[0]
        recent_end_dt = recent_df["datetime"].iloc[-1]
        
        filtered_trades = []
        for t in trades:
            e_dt = pd.to_datetime(t["entry_dt"]) if t.get("entry_dt") else None
            x_dt = pd.to_datetime(t["exit_dt"]) if t.get("exit_dt") else None
            if (e_dt and recent_start_dt <= e_dt <= recent_end_dt) or (x_dt and recent_start_dt <= x_dt <= recent_end_dt):
                filtered_trades.append({
                    "entry_dt": e_dt.strftime("%m-%d %H:%M") if e_dt else "",
                    "exit_dt": x_dt.strftime("%m-%d %H:%M") if x_dt else "",
                    "pnl_rmb": round(t.get("pnl_rmb", 0.0), 2),
                    "type": t.get("type", "TRADE")
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
            "trades": filtered_trades,
            "summary": {
                "win_rate": res["win_rate_pct"],
                "pl_ratio": res["profit_loss_ratio"],
                "return_pct": res["total_return_pct"],
                "trades_count": res["total_trades"],
                "max_dd": res["max_drawdown_pct"]
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/trader/<action>", methods=["POST"])
def api_trader_control(action):
    if action == "start":
        script = str(PROJECT_ROOT / "run_tqsim_trader.sh")
        subprocess.Popen(["bash", script], cwd=str(PROJECT_ROOT))
        time.sleep(1.0)
        return jsonify({"status": "started"})
    elif action == "stop":
        if PID_FILE.exists():
            try:
                with open(PID_FILE, "r") as f:
                    pid = int(f.read().strip())
                if is_process_running(pid):
                    p = psutil.Process(pid)
                    p.terminate()
                PID_FILE.unlink(missing_ok=True)
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        return jsonify({"status": "stopped"})
    return jsonify({"error": "invalid action"}), 400


DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>15大商品期货 LightGBM + PPO 实时交易监控看板</title>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
  <style>
    :root {
      --bg: #0d1117;
      --card-bg: #161b22;
      --border: #30363d;
      --text: #c9d1d9;
      --text-bright: #f0f6fc;
      --text-muted: #8b949e;
      --green: #238636;
      --green-bright: #3fb950;
      --red: #da3633;
      --red-bright: #f85149;
      --blue: #58a6ff;
      --gold: #d29922;
      --accent: #1f6feb;
    }
    * { margin: 0; padding: 0; box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
    body { background: var(--bg); color: var(--text); padding: 20px; font-size: 14px; }
    
    .header { display: flex; justify-content: space-between; align-items: center; padding-bottom: 16px; border-bottom: 1px solid var(--border); margin-bottom: 20px; }
    .header h1 { font-size: 20px; color: var(--text-bright); display: flex; align-items: center; gap: 10px; }
    .live-badge { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; padding: 4px 10px; border-radius: 20px; font-weight: 600; }
    .live-badge.running { background: rgba(35, 134, 54, 0.2); color: var(--green-bright); border: 1px solid var(--green); }
    .live-badge.stopped { background: rgba(218, 54, 51, 0.2); color: var(--red-bright); border: 1px solid var(--red); }
    .pulse-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--green-bright); box-shadow: 0 0 8px var(--green-bright); animation: pulse 1.5s infinite; }
    @keyframes pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.4; transform: scale(1.2); } }
    
    .stats-bar { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin-bottom: 20px; }
    .stat-card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 14px; }
    .stat-label { font-size: 12px; color: var(--text-muted); margin-bottom: 6px; }
    .stat-val { font-size: 20px; font-weight: 700; color: var(--text-bright); font-family: "JetBrains Mono", monospace; }
    
    .main-grid { display: grid; grid-template-columns: 360px 1fr; gap: 20px; }
    @media (max-width: 1200px) { .main-grid { grid-template-columns: 1fr; } }
    
    .panel { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; display: flex; flex-direction: column; }
    .panel-header { padding: 12px 16px; background: rgba(255,255,255,0.02); border-bottom: 1px solid var(--border); font-weight: 600; color: var(--text-bright); display: flex; justify-content: space-between; align-items: center; }
    
    .symbol-list { overflow-y: auto; max-height: 680px; }
    .symbol-item { padding: 12px 16px; border-bottom: 1px solid var(--border); cursor: pointer; transition: background 0.15s; display: flex; justify-content: space-between; align-items: center; }
    .symbol-item:hover { background: rgba(88, 166, 255, 0.06); }
    .symbol-item.active { background: rgba(88, 166, 255, 0.12); border-left: 3px solid var(--blue); }
    .sym-name { font-weight: 600; color: var(--text-bright); }
    .sym-code { font-size: 11px; color: var(--text-muted); }
    .pos-tag { padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 600; font-family: monospace; }
    .pos-long { background: rgba(35, 134, 54, 0.2); color: var(--green-bright); border: 1px solid var(--green); }
    .pos-short { background: rgba(218, 54, 51, 0.2); color: var(--red-bright); border: 1px solid var(--red); }
    .pos-flat { background: rgba(139, 148, 158, 0.15); color: var(--text-muted); }
    
    #kline-chart { width: 100%; height: 500px; }
    
    .log-box { background: #000; color: #7ee787; font-family: "JetBrains Mono", monospace; font-size: 11px; padding: 12px; height: 180px; overflow-y: auto; white-space: pre-wrap; line-height: 1.4; border-top: 1px solid var(--border); }
    
    .btn { padding: 6px 14px; border-radius: 6px; font-size: 12px; font-weight: 600; cursor: pointer; border: 1px solid transparent; transition: all 0.2s; }
    .btn-start { background: var(--green); color: #fff; }
    .btn-start:hover { background: var(--green-bright); }
    .btn-stop { background: var(--red); color: #fff; }
    .btn-stop:hover { background: var(--red-bright); }
  </style>
</head>
<body>

  <div class="header">
    <h1>
      <span>📊 15大商品期货 LightGBM + PPO 真实交易监控大屏</span>
      <div id="live-indicator" class="live-badge running">
        <div class="pulse-dot"></div>
        <span id="live-text">LIVE ACTIVE (后台监听中)</span>
      </div>
    </h1>
    <div style="display: flex; gap: 10px; align-items: center;">
      <span id="server-time" style="color: var(--text-muted); font-family: monospace; font-size: 12px;">--:--:--</span>
      <button id="btn-toggle" class="btn btn-stop" onclick="toggleTrader()">停止引擎</button>
    </div>
  </div>

  <div class="stats-bar">
    <div class="stat-card">
      <div class="stat-label">系统进程 PID / CPU</div>
      <div class="stat-val" id="stat-pid">PID: -- | CPU: 0%</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">虚拟账户总权益 (TqSim)</div>
      <div class="stat-val" style="color: var(--gold);">¥1,000,000.00</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">当前活跃持仓品种</div>
      <div class="stat-val" id="stat-active-pos" style="color: var(--blue);">0 / 15 个</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">选中品种实战胜率 / 盈亏比</div>
      <div class="stat-val" id="stat-sym-metric" style="color: var(--green-bright);">--% | --:1</div>
    </div>
  </div>

  <div class="main-grid">
    <!-- 左侧 15 大品种列表 -->
    <div class="panel">
      <div class="panel-header">
        <span>📋 15 大品种实时持仓矩阵</span>
        <span style="font-size: 11px; color: var(--text-muted);">15m 逐根收盘判定</span>
      </div>
      <div class="symbol-list" id="symbol-list-container">
        <!-- 动态生成 -->
      </div>
    </div>

    <!-- 右侧 K线买卖点与动态图表 -->
    <div class="panel">
      <div class="panel-header">
        <div style="display: flex; align-items: center; gap: 10px;">
          <span id="chart-title" style="font-size: 16px; font-weight: 700; color: var(--text-bright);">沪银 (AG_IDX) 15m K线买卖点精准透视</span>
          <span id="chart-cat-tag" style="font-size: 11px; padding: 2px 8px; border-radius: 12px; background: rgba(88,166,255,0.15); color: var(--blue);">贵金属</span>
        </div>
        <div style="font-size: 12px; color: var(--text-muted);" id="last-bar-time">最新 Bar: --</div>
      </div>

      <!-- ECharts K线容器 -->
      <div id="kline-chart"></div>

      <!-- 下方实时运行与撮合日志窗口 -->
      <div class="panel-header" style="border-top: 1px solid var(--border);">
        <span>🖥️ 实时撮合与事件驱动日志流 (Live Stream)</span>
        <span style="font-size: 11px; color: var(--text-muted);">自动刷新</span>
      </div>
      <div class="log-box" id="log-box">正在加载实时交易流...</div>
    </div>
  </div>

  <script>
    let currentSymbol = "AG_IDX";
    let chartInstance = null;
    let isRunning = false;

    // 初始化 ECharts 图表
    function initChart() {
      chartInstance = echarts.init(document.getElementById('kline-chart'), 'dark');
      window.addEventListener('resize', () => chartInstance.resize());
    }

    // 格式化数字
    function fNum(n) { return (n || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }

    // 渲染 K 线与买卖点标记
    function renderKLine(data) {
      document.getElementById('chart-title').innerText = `${data.name} (${data.symbol}) 15m K线买卖点精准透视`;
      document.getElementById('chart-cat-tag').innerText = data.category;
      document.getElementById('stat-sym-metric').innerText = `${data.summary.win_rate}% | ${data.summary.pl_ratio}:1`;
      
      if (data.categories.length > 0) {
        document.getElementById('last-bar-time').innerText = `最新 Bar: ${data.categories[data.categories.length - 1]}`;
      }

      // 构建买卖点 MarkPoint
      const markPoints = [];
      data.trades.forEach(t => {
        if (t.entry_dt) {
          const idx = data.categories.indexOf(t.entry_dt);
          if (idx !== -1) {
            markPoints.push({
              name: '开仓',
              coord: [t.entry_dt, data.k_values[idx][1]],
              value: t.type.includes('LONG') ? '▲ 多' : '▼ 空',
              itemStyle: { color: t.type.includes('LONG') ? '#3fb950' : '#f85149' }
            });
          }
        }
        if (t.exit_dt) {
          const idx = data.categories.indexOf(t.exit_dt);
          if (idx !== -1) {
            markPoints.push({
              name: '平仓',
              coord: [t.exit_dt, data.k_values[idx][1]],
              value: t.pnl_rmb >= 0 ? `+¥${t.pnl_rmb}` : `-¥${Math.abs(t.pnl_rmb)}`,
              itemStyle: { color: t.pnl_rmb >= 0 ? '#d29922' : '#8b949e' }
            });
          }
        }
      });

      const option = {
        backgroundColor: '#161b22',
        animation: false,
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'cross' },
          backgroundColor: '#0d1117',
          borderColor: '#30363d',
          textStyle: { color: '#c9d1d9', fontSize: 12 }
        },
        grid: [
          { left: '50px', right: '30px', top: '30px', height: '55%' },
          { left: '50px', right: '30px', top: '68%', height: '22%' }
        ],
        xAxis: [
          { type: 'category', data: data.categories, scale: true, boundaryGap: false, axisLine: { lineStyle: { color: '#30363d' } } },
          { type: 'category', gridIndex: 1, data: data.categories, scale: true, boundaryGap: false, axisLabel: { show: false }, axisLine: { lineStyle: { color: '#30363d' } } }
        ],
        yAxis: [
          { scale: true, splitArea: { show: false }, splitLine: { lineStyle: { color: '#21262d' } }, axisLine: { lineStyle: { color: '#30363d' } } },
          { scale: true, gridIndex: 1, splitNumber: 2, axisLabel: { show: false }, axisLine: { show: false }, splitLine: { show: false } }
        ],
        dataZoom: [
          { type: 'inside', xAxisIndex: [0, 1], start: 60, end: 100 },
          { show: true, xAxisIndex: [0, 1], type: 'slider', top: '92%', height: '16px', borderColor: '#30363d' }
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
              data: markPoints,
              symbolSize: 45,
              label: { fontSize: 10, fontWeight: 'bold' }
            }
          },
          {
            name: '成交量',
            type: 'bar',
            xAxisIndex: 1,
            yAxisIndex: 1,
            data: data.volumes,
            itemStyle: { color: '#58a6ff' }
          }
        ]
      };

      chartInstance.setOption(option);
    }

    // 加载品种 K 线数据
    function loadKLine(symbol) {
      currentSymbol = symbol;
      fetch(`/api/kline?symbol=${symbol}`)
        .then(r => r.json())
        .then(d => {
          if (!d.error) renderKLine(d);
        });
    }

    // 轮询系统状态
    function pollStatus() {
      fetch('/api/status')
        .then(r => r.json())
        .then(d => {
          isRunning = d.running;
          document.getElementById('server-time').innerText = d.server_time;
          
          const ind = document.getElementById('live-indicator');
          const txt = document.getElementById('live-text');
          const btn = document.getElementById('btn-toggle');
          
          if (d.running) {
            ind.className = 'live-badge running';
            txt.innerText = `LIVE ACTIVE (PID: ${d.pid} | CPU: ${d.cpu_percent}%)`;
            btn.className = 'btn btn-stop';
            btn.innerText = '停止引擎';
            document.getElementById('stat-pid').innerText = `PID: ${d.pid} | 内存: ${d.memory_mb}MB`;
          } else {
            ind.className = 'live-badge stopped';
            txt.innerText = 'ENGINE STOPPED (已停止)';
            btn.className = 'btn btn-start';
            btn.innerText = '启动引擎';
            document.getElementById('stat-pid').innerText = '未运行';
          }

          document.getElementById('stat-active-pos').innerText = `${d.active_positions} / ${d.total_symbols} 个`;

          // 渲染左侧列表
          const container = document.getElementById('symbol-list-container');
          container.innerHTML = d.symbols.map(s => {
            let posTag = '<span class="pos-tag pos-flat">空仓</span>';
            if (s.pos === 1) posTag = `<span class="pos-tag pos-long">多 ${s.lots}手</span>`;
            if (s.pos === -1) posTag = `<span class="pos-tag pos-short">空 ${s.lots}手</span>`;
            
            const activeCls = s.symbol === currentSymbol ? 'active' : '';
            return `
              <div class="symbol-item ${activeCls}" onclick="loadKLine('${s.symbol}')">
                <div>
                  <div class="sym-name">${s.name}</div>
                  <div class="sym-code">${s.symbol} · ${s.category}</div>
                </div>
                <div style="text-align: right;">
                  ${posTag}
                  <div style="font-size: 11px; color: var(--text-muted); margin-top: 3px;">止损: ${s.stop_loss || '--'}</div>
                </div>
              </div>
            `;
          }).join('');
        });

      // 刷新日志
      fetch('/api/logs')
        .then(r => r.json())
        .then(d => {
          const box = document.getElementById('log-box');
          box.innerText = d.logs;
          box.scrollTop = box.scrollHeight;
        });
    }

    function toggleTrader() {
      const action = isRunning ? 'stop' : 'start';
      fetch(`/api/trader/${action}`, { method: 'POST' })
        .then(r => r.json())
        .then(() => pollStatus());
    }

    window.onload = () => {
      initChart();
      loadKLine(currentSymbol);
      pollStatus();
      setInterval(pollStatus, 2000); // 2秒实时心跳轮询
    };
  </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


if __name__ == "__main__":
    port = 8090
    print("=" * 80)
    print(f"🚀 启动 15 大商品期货实时监控大屏 Web UI Server...")
    print(f"👉 浏览器访问: http://127.0.0.1:{port}")
    print("=" * 80)
    app.run(host="0.0.0.0", port=port, debug=False)
