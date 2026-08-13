"""
A-Share Quantitative Strategy Engine - Futures 15m Portfolio ML Backtest & HTML Report Generator
【15分钟 K线多品种组合机器学习策略回测与 HTML 报告生成器】

核心功能：
1. 提取数据库中各活跃期货品种 15m K线全量数据 (沪银 AG_IDX 使用 V16 原策略，沪铜 CU_IDX 使用 CopperV16Engine 芒格/巴菲特/达利欧专属引擎)。
2. 运行 第一性原理机器学习策略 (Chandelier 悬挂离场 + MTF 宏观共振 + Walk-Forward 绝对隔离)。
3. 聚合成瑞·达利欧 (Ray Dalio) 多资产组合收益率曲线，计算组合起止时间、胜率、盈亏比、最大回撤、交易笔数等。
4. 生成独立可离线浏览的 HTML 交互式可视化报告 (`data/reports/futures_ml_15m_portfolio_report.html`)。
"""

import os
import sys
import json
import sqlite3
import datetime
import warnings
import numpy as np
import pandas as pd
from pathlib import Path

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "code"))

from futures_v16_first_principles_engine import FirstPrinciplesV16Engine
from copper_v16_engine import CopperV16Engine

DB_PATH = str(PROJECT_ROOT / "data/ashare_quant.db")
REPORT_DIR = PROJECT_ROOT / "data/reports"


def generate_portfolio_html_report():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    engine_v16 = FirstPrinciplesV16Engine(db_path=DB_PATH)
    engine_cu = CopperV16Engine(db_path=DB_PATH)

    # 包含数据活跃度较高的 12 大热门期货品种
    target_symbols = [
        {"symbol": "AG_IDX", "name": "沪银",   "category": "贵金属"},
        {"symbol": "CU_IDX", "name": "沪铜",   "category": "有色工业"},
        {"symbol": "RB_IDX", "name": "螺纹钢", "category": "黑色建筑"},
        {"symbol": "I_IDX",  "name": "铁矿石", "category": "黑色原材料"},
        {"symbol": "SA_IDX", "name": "纯碱",   "category": "化工高波"},
        {"symbol": "SC_IDX", "name": "原油",   "category": "能源化工"},
        {"symbol": "MA_IDX", "name": "甲醇",   "category": "化工原料"},
        {"symbol": "TA_IDX", "name": "PTA",    "category": "纺织化工"},
        {"symbol": "M_IDX",  "name": "豆粕",   "category": "农产品"},
        {"symbol": "SN_IDX", "name": "沪锡",   "category": "有色稀缺"},
        {"symbol": "LC_IDX", "name": "碳酸锂", "category": "新能源电池"},
        {"symbol": "J_IDX",  "name": "焦炭",   "category": "双焦能源"}
    ]

    symbol_results = []
    all_trades = []
    portfolio_eq_curves = {}
    min_len = 999999999

    overall_start_dt = "9999-12-31 23:59:59"
    overall_end_dt = "1970-01-01 00:00:00"

    print("=" * 90)
    print("🚀 启动 15m 期货 K线多品种组合机器学习策略回测与 HTML 报告生成...")
    print("=" * 90)

    for item in target_symbols:
        sym = item["symbol"]
        name = item["name"]
        cat = item["category"]

        if sym == "CU_IDX":
            res = engine_cu.run_backtest(initial_capital=1000000.0, prob_thresh=0.60, trail_mult=2.8, mode="high_pl")
        else:
            res = engine_v16.run_15m_first_principles_backtest(symbol=sym, initial_capital=1000000.0)

        if "error" not in res and res.get("total_trades", 0) >= 0:
            res["name"] = name
            res["category"] = cat
            symbol_results.append(res)

            if res["start_time"] < overall_start_dt:
                overall_start_dt = res["start_time"]
            if res["end_time"] > overall_end_dt:
                overall_end_dt = res["end_time"]

            eq = res.pop("equity_curve")
            dt_list = res.pop("datetime_list")
            trades = res.pop("trades")

            portfolio_eq_curves[sym] = eq
            min_len = min(min_len, len(eq))

            for t in trades:
                t["symbol"] = sym
                t["symbol_name"] = name
                all_trades.append(t)

            print(f"  ├─ [{sym:<8} {name}] 起止: {res['start_time'][:10]} ~ {res['end_time'][:10]} | 收益: {res['total_return_pct']:>6.2f}% | 胜率: {res['win_rate_pct']:>5.1f}% | 盈亏比: {res['profit_loss_ratio']:>4.2f}:1 | 撤回: {res['max_drawdown_pct']:>5.2f}% | 交易: {res['total_trades']:>3}笔")
        else:
            err_msg = res.get("error", "数据量不足")
            print(f"  ├─ [{sym:<8} {name}] 跳过: {err_msg}")

    if not symbol_results:
        print("❌ 未能获取有效的品种回测结果！")
        return

    # ── 聚合多资产 Ray Dalio 圣杯组合收益率 ──────────────────────────────────
    portfolio_eq = np.zeros(min_len)
    for sym, eq in portfolio_eq_curves.items():
        portfolio_eq += np.array(eq[-min_len:]) / len(portfolio_eq_curves)

    init_cap = portfolio_eq[0]
    final_cap = portfolio_eq[-1]
    net_profit = final_cap - init_cap
    tot_return = (final_cap - init_cap) / init_cap * 100.0

    peak = np.maximum.accumulate(portfolio_eq)
    drawdowns = np.where(peak > 0, (peak - portfolio_eq) / peak, 0.0)
    port_max_dd = float(np.max(drawdowns) * 100.0)

    # 组合交易汇总
    port_total_trades = sum(r["total_trades"] for r in symbol_results)
    port_wins = sum(int(r["win_rate_pct"] * r["total_trades"] / 100.0) for r in symbol_results)
    port_win_rate = (port_wins / port_total_trades * 100.0) if port_total_trades > 0 else 0.0

    tot_win_pnl = sum(sum(t["pnl_rmb"] for t in [tr for tr in all_trades if tr["pnl_rmb"] > 0]) for _ in [1])
    tot_loss_pnl = abs(sum(sum(t["pnl_rmb"] for t in [tr for tr in all_trades if tr["pnl_rmb"] < 0]) for _ in [1]))
    port_pl_ratio = (tot_win_pnl / tot_loss_pnl) if tot_loss_pnl > 0 else 0.0

    bar_ret = np.diff(portfolio_eq) / (portfolio_eq[:-1] + 1e-8)
    port_sharpe = (np.mean(bar_ret) / (np.std(bar_ret) + 1e-8)) * np.sqrt(9324) if len(bar_ret) > 1 and np.std(bar_ret) > 0 else 0.0

    portfolio_summary = {
        "start_time": overall_start_dt,
        "end_time": overall_end_dt,
        "initial_capital": round(init_cap, 2),
        "final_equity": round(final_cap, 2),
        "net_profit_rmb": round(net_profit, 2),
        "total_return_pct": round(tot_return, 2),
        "win_rate_pct": round(port_win_rate, 1),
        "profit_loss_ratio": round(port_pl_ratio, 2),
        "max_drawdown_pct": round(port_max_dd, 2),
        "total_trades": port_total_trades,
        "sharpe_ratio": round(float(port_sharpe), 2),
        "valid_symbols_count": len(symbol_results)
    }

    print("\n" + "=" * 90)
    print("🏆 15m 期货多品种组合回测结果汇总:")
    print(f"  ├─ 回测起止时间: {portfolio_summary['start_time']} 至 {portfolio_summary['end_time']}")
    print(f"  ├─ 组合初始资金: ¥{portfolio_summary['initial_capital']:,.2f}")
    print(f"  ├─ 组合期末权益: ¥{portfolio_summary['final_equity']:,.2f} (净利润: ¥{portfolio_summary['net_profit_rmb']:+,.2f})")
    print(f"  ├─ 组合累计收益率: {portfolio_summary['total_return_pct']:+.2f}%")
    print(f"  ├─ 🏆 组合胜率: {portfolio_summary['win_rate_pct']}%")
    print(f"  ├─ 🏆 组合盈亏比: {portfolio_summary['profit_loss_ratio']}:1")
    print(f"  ├─ 🏆 组合最大回撤: {portfolio_summary['max_drawdown_pct']}%")
    print(f"  ├─ 组合总交易笔数: {portfolio_summary['total_trades']} 笔")
    print(f"  ├─ 组合夏普比率: {portfolio_summary['sharpe_ratio']}")
    print("=" * 90)

    # ── 生成高档黑金风格 HTML 交互式报告 ──────────────────────────────────────
    html_content = generate_html_template(portfolio_summary, symbol_results, portfolio_eq.tolist())

    html_file = REPORT_DIR / "futures_ml_15m_portfolio_report.html"
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"\n🎉 详细 HTML 回测报告已成功导出至:\n{html_file.resolve()}")
    return portfolio_summary, str(html_file.resolve())


def generate_html_template(summary, symbol_results, portfolio_eq):
    """构建响应式高品质 HTML 报告页面"""
    eq_sample = portfolio_eq[::max(1, len(portfolio_eq) // 200)]
    eq_json = json.dumps([round(v, 2) for v in eq_sample])

    rows_html = ""
    for r in symbol_results:
        ret_cls = "pos" if r["total_return_pct"] >= 0 else "neg"
        rows_html += f"""
        <tr>
            <td><strong>{r['name']}</strong> ({r['symbol']})</td>
            <td><span class="badge">{r['category']}</span></td>
            <td>{r['start_time'][:10]} ~ {r['end_time'][:10]}</td>
            <td class="{ret_cls}">{r['total_return_pct']:+.2f}%</td>
            <td><strong>{r['win_rate_pct']}%</strong></td>
            <td><strong>{r['profit_loss_ratio']}:1</strong></td>
            <td class="neg">{r['max_drawdown_pct']:.2f}%</td>
            <td>{r['total_trades']} 笔</td>
            <td>¥{r['avg_win_rmb']:,.2f}</td>
            <td>¥{r['avg_loss_rmb']:,.2f}</td>
            <td>{r['sharpe_ratio']}</td>
        </tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>期货机器学习 15m 多品种组合回测报告</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {{
            --bg-color: #0b0f19;
            --card-bg: #141c2e;
            --border-color: #23314d;
            --text-main: #f0f4fc;
            --text-sub: #94a3b8;
            --primary: #3b82f6;
            --green: #10b981;
            --red: #ef4444;
            --gold: #f59e0b;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            margin: 0;
            padding: 30px 40px;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 20px;
            margin-bottom: 30px;
        }}
        .title h1 {{
            font-size: 26px;
            margin: 0 0 8px 0;
            color: #ffffff;
            letter-spacing: 0.5px;
        }}
        .title p {{
            margin: 0;
            color: var(--text-sub);
            font-size: 14px;
        }}
        .badge-v16 {{
            background: linear-gradient(135deg, #3b82f6, #8b5cf6);
            color: white;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 600;
        }}
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 35px;
        }}
        .metric-card {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 20px;
            transition: transform 0.2s;
        }}
        .metric-card:hover {{
            transform: translateY(-2px);
        }}
        .metric-label {{
            font-size: 13px;
            color: var(--text-sub);
            margin-bottom: 8px;
        }}
        .metric-val {{
            font-size: 24px;
            font-weight: 700;
            color: #ffffff;
        }}
        .pos {{ color: var(--green) !important; }}
        .neg {{ color: var(--red) !important; }}
        .gold {{ color: var(--gold) !important; }}
        
        .chart-container {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 35px;
        }}
        .chart-header {{
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 20px;
            color: #ffffff;
        }}
        
        .table-container {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 24px;
            overflow-x: auto;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
            font-size: 14px;
        }}
        th {{
            background-color: #1e293b;
            color: var(--text-sub);
            padding: 14px 16px;
            font-weight: 600;
            border-bottom: 1px solid var(--border-color);
        }}
        td {{
            padding: 14px 16px;
            border-bottom: 1px solid var(--border-color);
        }}
        tr:hover td {{
            background-color: #1a2438;
        }}
        .badge {{
            background-color: #1e293b;
            color: var(--primary);
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 12px;
        }}
    </style>
</head>
<body>

    <div class="header">
        <div class="title">
            <h1>📊 期货机器学习 15m 多品种组合回测报告 (V16 第一性原理版)</h1>
            <p>评估区间: <strong>{summary['start_time']}</strong> 至 <strong>{summary['end_time']}</strong> | 包含 <strong>{summary['valid_symbols_count']}</strong> 个高活跃品种组合对冲</p>
        </div>
        <div class="badge-v16">V16 第一性原理引擎</div>
    </div>

    <div class="metrics-grid">
        <div class="metric-card">
            <div class="metric-label">组合累计收益率</div>
            <div class="metric-val pos">{summary['total_return_pct']:+.2f}%</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">🏆 组合胜率 (Win Rate)</div>
            <div class="metric-val gold">{summary['win_rate_pct']}%</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">🏆 组合盈亏比 (PL Ratio)</div>
            <div class="metric-val gold">{summary['profit_loss_ratio']}:1</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">🏆 组合最大回撤 (Max DD)</div>
            <div class="metric-val neg">{summary['max_drawdown_pct']:.2f}%</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">组合交易总笔数</div>
            <div class="metric-val">{summary['total_trades']} 笔</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">年化夏普比率 (Sharpe)</div>
            <div class="metric-val">{summary['sharpe_ratio']}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">期末总权益</div>
            <div class="metric-val">¥{summary['final_equity']:,.2f}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">累计净利润</div>
            <div class="metric-val pos">¥{summary['net_profit_rmb']:+,.2f}</div>
        </div>
    </div>

    <div class="chart-container">
        <div class="chart-header">📈 组合资金权益曲线 (Mark-to-Market 逐Bar估值)</div>
        <canvas id="equityChart" height="90"></canvas>
    </div>

    <div class="table-container">
        <div class="chart-header">📋 各品种 15m K线机器学习回测明细表</div>
        <table>
            <thead>
                <tr>
                    <th>品种名称</th>
                    <th>板块分类</th>
                    <th>回测时间段</th>
                    <th>累计收益率</th>
                    <th>交易胜率</th>
                    <th>盈亏比</th>
                    <th>最大回撤</th>
                    <th>交易笔数</th>
                    <th>均盈利</th>
                    <th>均亏损</th>
                    <th>夏普比率</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
    </div>

    <script>
        const ctx = document.getElementById('equityChart').getContext('2d');
        const eqData = {eq_json};
        const labels = eqData.map((_, i) => i);
        
        const gradient = ctx.createLinearGradient(0, 0, 0, 400);
        gradient.addColorStop(0, 'rgba(59, 130, 246, 0.4)');
        gradient.addColorStop(1, 'rgba(59, 130, 246, 0.0)');

        new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: labels,
                datasets: [{{
                    label: '组合资金权益 (RMB)',
                    data: eqData,
                    borderColor: '#3b82f6',
                    borderWidth: 2,
                    backgroundColor: gradient,
                    fill: true,
                    tension: 0.1,
                    pointRadius: 0
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{
                    legend: {{ display: false }}
                }},
                scales: {{
                    x: {{ display: false }},
                    y: {{
                        grid: {{ color: '#1e293b' }},
                        ticks: {{ color: '#94a3b8' }}
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>
"""
    return html


if __name__ == "__main__":
    generate_portfolio_html_report()
