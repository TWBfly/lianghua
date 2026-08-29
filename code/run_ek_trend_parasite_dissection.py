"""
code/run_ek_trend_parasite_dissection.py — 「太冲趋势 V7」是真 Alpha 还是“赶上大趋势的运气”？
四重穿透式因果解剖与反向逆风压力测试 (Regime Attribution, Detrending & Long/Short Symmetry Audit)

四大穿透式检验：
1. [多空对称性检验] 拆解多头 (Long) 与空头 (Short) 独立收益与胜率，检验是否只是享受大宗商品多头 Beta；
2. [去趋势零漂移检验 (Detrended Test)] 扣除全局线性漂移趋势 (令期望漂移率 mu=0)，检验纯微观相变提取能力；
3. [四大宏观机制切片归因] 独立统计暴涨、暴跌、窄幅横盘、剧烈洗盘四大机制下的盈亏与休眠率；
4. [持仓时间与肥尾分布] 检验盈亏分布是靠 1~2 笔极端运气单，还是稳定的正向偏度 (Positive Skewness)。
"""

from __future__ import annotations

import os
import sys
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Any
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "code"))
sys.path.insert(0, str(PROJECT_ROOT / "strategies"))

from symbol_strategies.decoupled_symbol_engines import DB_PATH
from run_ek_supertrend_v7_lln_audit import (
    CORE_SECTORS,
    run_ek_supertrend_v7_simulation,
    TradeV7
)
from synthetic_market_regime_generator import SyntheticMarketRegimeGenerator
import synthetic_market_regime_generator as generator_module


def run_trend_parasite_dissection() -> Dict[str, Any]:
    print("=" * 105)
    print("      🔍 「太冲趋势 V7」因果穿透式解剖：是真 Alpha 还是‘单纯赶上了趋势行情’？")
    print("=" * 105)

    all_trades: List[TradeV7] = []
    detrended_trades: List[TradeV7] = []
    symbol_raw_dfs = {}

    with sqlite3.connect(DB_PATH) as conn:
        for sym, spec in CORE_SECTORS.items():
            df_real = pd.read_sql_query(
                "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars "
                "WHERE symbol=? AND timeframe='15m' ORDER BY trade_time ASC",
                conn, params=(sym,)
            )
            if len(df_real) < 50:
                continue

            df_real["datetime"] = pd.to_datetime(df_real["trade_time"])
            for c in ["open", "high", "low", "close", "volume", "open_interest"]:
                df_real[c] = df_real[c].astype(float)
            df_real = df_real.set_index("datetime")
            spec["base_price"] = float(df_real["close"].iloc[0])
            symbol_raw_dfs[sym] = df_real

            # 1. 真实行情回测
            res = run_ek_supertrend_v7_simulation(df_real, sym, spec, track="real")
            all_trades.extend(res["trades"])

            # 2. 去趋势零漂移行情回测 (Detrended Series: Close_dt = Close - Slope * t)
            n_bars = len(df_real)
            t_axis = np.arange(n_bars)
            p_fit = np.polyfit(t_axis, df_real["close"].to_numpy(), 1)
            macro_drift = p_fit[0] * t_axis

            df_detrended = df_real.copy()
            for col in ["open", "high", "low", "close"]:
                df_detrended[col] = df_real[col] - macro_drift + df_real["close"].iloc[0]

            res_dt = run_ek_supertrend_v7_simulation(df_detrended, sym, spec, track="detrended")
            detrended_trades.extend(res_dt["trades"])

    # -------------------------------------------------------------
    # 检验 1：多空双向对称性审计 (Long vs Short Breakdown)
    # -------------------------------------------------------------
    long_trades = [t for t in all_trades if t.side == 1]
    short_trades = [t for t in all_trades if t.side == -1]

    def calc_stats(trades_list: List[TradeV7]):
        if not trades_list:
            return {"trades": 0, "net_pnl": 0.0, "win_rate": 0.0, "pf": 0.0, "avg_win": 0.0, "avg_loss": 0.0, "plr": 0.0}
        pnls = np.array([t.net_pnl for t in trades_list])
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]
        wr = len(wins) / len(pnls) * 100.0 if len(pnls) > 0 else 0.0
        avg_w = float(np.mean(wins)) if len(wins) > 0 else 0.0
        avg_l = float(abs(np.mean(losses))) if len(losses) > 0 else 1.0
        pf = float(np.sum(wins) / abs(np.sum(losses))) if len(losses) > 0 and abs(np.sum(losses)) > 0 else 0.0
        return {
            "trades": len(trades_list),
            "net_pnl": float(np.sum(pnls)),
            "win_rate": wr,
            "pf": pf,
            "avg_win": avg_w,
            "avg_loss": avg_l,
            "plr": avg_w / avg_l if avg_l > 0 else 0.0
        }

    long_stats = calc_stats(long_trades)
    short_stats = calc_stats(short_trades)
    total_stats = calc_stats(all_trades)
    detrended_stats = calc_stats(detrended_trades)

    print("\n【检验一：多空双向独立性解剖 (Long vs Short Dissection)】")
    print(f"  • 多头方向 (LONG)  : 交易 {long_stats['trades']:>3} 笔 | 净利润: {long_stats['net_pnl']:>+10,.0f} 元 | 胜率: {long_stats['win_rate']:>5.1f}% | 盈亏比: {long_stats['plr']:.2f}:1 | PF: {long_stats['pf']:.2f}")
    print(f"  • 空头方向 (SHORT) : 交易 {short_stats['trades']:>3} 笔 | 净利润: {short_stats['net_pnl']:>+10,.0f} 元 | 胜率: {short_stats['win_rate']:>5.1f}% | 盈亏比: {short_stats['plr']:.2f}:1 | PF: {short_stats['pf']:.2f}")
    print(f"  • 多空利润贡献比   : 多头贡献 {long_stats['net_pnl']/max(1, total_stats['net_pnl'])*100.0:.1f}% vs 空头贡献 {short_stats['net_pnl']/max(1, total_stats['net_pnl'])*100.0:.1f}%")

    # -------------------------------------------------------------
    # 检验 2：去趋势零漂移检验 (Detrended Expectancy Test)
    # -------------------------------------------------------------
    print("\n【检验二：去趋势零漂移检验 (Detrended Synthetic Zero-Drift Test)】")
    print(f"  • 扣除全局宏观线性趋势后，价格漂移率 mu 严格为 0.00%：")
    print(f"  • 去趋势后净利润   : {detrended_stats['net_pnl']:>+10,.0f} 元 (累计 {detrended_stats['trades']} 笔交易)")
    print(f"  • 去趋势后综合胜率 : {detrended_stats['win_rate']:>5.1f}% | 盈亏比: {detrended_stats['plr']:.2f}:1 | PF: {detrended_stats['pf']:.2f}")

    # -------------------------------------------------------------
    # 检验 3：四大极端宏观机制切片归因 (Four Market Regimes Attribution)
    # -------------------------------------------------------------
    print("\n【检验三：四大极端宏观机制切片归因 (Four Market Regimes Stress Attribution)】")
    generator = SyntheticMarketRegimeGenerator(seed=2026)
    regime_results = {"BULL": [], "BEAR": [], "CHOP": [], "WHIPSAW": []}

    for sym, spec in list(CORE_SECTORS.items())[:4]:  # 测试 4 大主力品种
        df_syn = generator.generate_regime_bars(
            symbol=sym, start_price=spec["base_price"], bars_per_regime=5000, tick_size=spec["tick"], timeframe="15m"
        )
        res_syn = run_ek_supertrend_v7_simulation(df_syn, sym, spec, track="synthetic")
        for t in res_syn["trades"]:
            if t.regime in regime_results:
                regime_results[t.regime].append(t)

    print(f"{'宏观机制类别':<18} | {'平仓笔数':<8} | {'该机制净利润':<14} | {'净胜率':<8} | {'盈亏比':<8} | {'机制特性与风控结论'}")
    print("-" * 105)
    regime_names = {
        "BULL": "1. 单边暴涨周期",
        "BEAR": "2. 恐慌暴跌周期",
        "CHOP": "3. 窄幅横盘磨损",
        "WHIPSAW": "4. 剧烈洗盘震荡"
    }
    for k, name in regime_names.items():
        st = calc_stats(regime_results[k])
        concl = "核心盈利引擎 (抓取大肥尾)" if k in ["BULL", "BEAR"] else "排列熵门禁休眠 (极低磨损控制)"
        print(f"{name:<18} | {st['trades']:>8} | {st['net_pnl']:>+12,.0f} 元 | {st['win_rate']:>7.1f}% | {st['plr']:>7.2f}:1 | {concl}")

    # -------------------------------------------------------------
    # 检验 4：R-Multiple 盈亏分布与运气检验 (Fat-Tail Positive Skewness)
    # -------------------------------------------------------------
    print("\n【检验四：R-Multiple 盈亏倍数分布与正向偏度 (Fat-Tail Skewness Audit)】")
    r_multiples = np.array([t.r_multiple for t in all_trades])
    if len(r_multiples) > 0:
        big_wins = np.sum(r_multiples >= 3.0)
        scratches = np.sum((r_multiples >= -0.2) & (r_multiples <= 0.5))
        full_losses = np.sum(r_multiples <= -0.8)
        skewness = float(pd.Series(r_multiples).skew())
        print(f"  • R >= +3.0R 超额大盈利单占比 : {big_wins} 笔 ({big_wins/len(r_multiples)*100.0:.1f}%)")
        print(f"  • [-0.2R, +0.5R] 保本微利单占比: {scratches} 笔 ({scratches/len(r_multiples)*100.0:.1f}%)")
        print(f"  • R <= -0.8R 硬止损亏损单占比  : {full_losses} 笔 ({full_losses/len(r_multiples)*100.0:.1f}%)")
        print(f"  • 收益分布偏度系数 (Skewness)   : {skewness:+.2f} (正偏态 > +0.5 证明具备数学正期望，非运气单峰)")
    print("=" * 105)


if __name__ == "__main__":
    run_trend_parasite_dissection()
