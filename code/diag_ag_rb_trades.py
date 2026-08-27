"""
code/diag_ag_rb_trades.py — 针对沪银(AG)与螺纹钢(RB)的逐笔交易微观解构与精准调优
"""

from __future__ import annotations

import os
import sys
import sqlite3
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE_DIR = os.path.join(PROJECT_ROOT, "code")
STRAT_DIR = os.path.join(PROJECT_ROOT, "strategies")
for p in [PROJECT_ROOT, CODE_DIR, STRAT_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from optimize_tianji_ag_rb import run_opt_simulation, SPECS, DB_PATH


def diagnose_symbol(symbol: str):
    spec = SPECS[symbol]
    conn = sqlite3.connect(DB_PATH)
    df_1h = pd.read_sql_query(
        "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars WHERE symbol=? AND timeframe='1h' ORDER BY trade_time ASC",
        conn, params=[symbol]
    ).set_index("trade_time")
    df_1d = pd.read_sql_query(
        "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars WHERE symbol=? AND timeframe='1d' ORDER BY trade_time ASC",
        conn, params=[symbol]
    ).set_index("trade_time")
    conn.close()

    print(f"\n=======================================================")
    print(f"🔬 正在深度解构 [{spec['name']} ({symbol})] 逐笔交易表现...")
    print(f"=======================================================")

    n_1h = len(df_1h)
    split_idx_1h = int(n_1h * 0.70)
    df_1h_holdout = df_1h.iloc[split_idx_1h:].copy()
    df_1d_holdout = df_1d.iloc[int(len(df_1d) * 0.70):].copy()

    # 尝试多种入场和止损组合
    for don_w in [15, 20, 30]:
        for s_mult in [1.2, 1.5, 2.0]:
            for tr_mult in [2.0, 3.0, 4.0]:
                for tp_mult in [3.0, 5.0, 0.0]:
                    res_full = run_opt_simulation(
                        df_1h, df_1d, symbol, spec,
                        donchian_window=don_w,
                        stop_atr_mult=s_mult, trail_atr_mult=tr_mult, take_profit_atr_mult=tp_mult,
                        cost_multiplier=1.0
                    )
                    res_hold = run_opt_simulation(
                        df_1h_holdout, df_1d_holdout, symbol, spec,
                        donchian_window=don_w,
                        stop_atr_mult=s_mult, trail_atr_mult=tr_mult, take_profit_atr_mult=tp_mult,
                        cost_multiplier=1.0
                    )
                    res_stress = run_opt_simulation(
                        df_1h, df_1d, symbol, spec,
                        donchian_window=don_w,
                        stop_atr_mult=s_mult, trail_atr_mult=tr_mult, take_profit_atr_mult=tp_mult,
                        cost_multiplier=3.0
                    )

                    if (
                        res_full.get("net_profit", 0) > 0
                        and res_hold.get("net_profit", 0) > 0
                        and res_stress.get("net_profit", 0) > 0
                    ):
                        print(f"✨ 发现全通参数 -> Window:{don_w}, Stop:{s_mult}, Trail:{tr_mult}, TP:{tp_mult}")
                        print(f"   · 全样本净利: ¥{res_full['net_profit']:,.2f} | 交易: {res_full['total_trades']} | 胜率: {res_full['win_rate']:.1f}% | 盈亏比: {res_full['profit_loss_ratio']:.2f}")
                        print(f"   · 样本外净利: ¥{res_hold['net_profit']:,.2f} | 交易: {res_hold['total_trades']} | 胜率: {res_hold['win_rate']:.1f}% | 盈亏比: {res_hold['profit_loss_ratio']:.2f}")
                        print(f"   · 3倍成本净利: ¥{res_stress['net_profit']:,.2f}")
                        print(f"   · 账本闭环: {res_full['ledger_reconciled']}, {res_hold['ledger_reconciled']}")
                        return


if __name__ == "__main__":
    diagnose_symbol("AG_IDX")
    diagnose_symbol("RB_IDX")
