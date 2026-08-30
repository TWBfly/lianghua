"""
code/test_taiwei_micro_tp_grid.py — 测试太微小波相变高胜率微观出场模型
"""

import sys
import math
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "code"))
sys.path.insert(0, str(PROJECT_ROOT / "strategies"))

from test_taiwei_refined_engine import precompute_taiwei_dataset, run_fast_simulation

def main():
    timeframes = ["5m", "15m", "30m"]
    symbols = ["AG_IDX", "AU_IDX", "CU_IDX", "SC_IDX", "RB_IDX", "TA_IDX", "MA_IDX", "LC_IDX", "SN_IDX", "P_IDX"]

    print("⏳ 预计算特征流...")
    dataset = precompute_taiwei_dataset(timeframes, symbols)
    print(f"✅ 特征预计算完成: {len(dataset)} 个数据集")

    results = []
    for tf in timeframes:
        for tp in [0.6, 0.8, 1.0, 1.2, 1.5]:
            for sl in [0.6, 0.8, 1.0, 1.2]:
                for be in [0.4, 0.6, 0.8, 1.0]:
                    tot_pnl = 0.0
                    tot_trades = 0
                    tot_wins = 0

                    for sym in symbols:
                        if (sym, tf) not in dataset:
                            continue
                        pnl, tr_cnt, w_cnt = run_fast_simulation(dataset[(sym, tf)], tp, sl, be)
                        tot_pnl += pnl
                        tot_trades += tr_cnt
                        tot_wins += w_cnt

                    wr = tot_wins / max(1, tot_trades) * 100.0 if tot_trades > 0 else 0.0
                    results.append({
                        "tf": tf, "tp": tp, "sl": sl, "be": be,
                        "pnl": tot_pnl, "trades": tot_trades, "wr": wr
                    })

    df_res = pd.DataFrame(results).sort_values("pnl", ascending=False)
    print("\n🏆 太微策略全周期与参数扫描 Top 20 结果:")
    print(df_res.head(20).to_string(index=False))

    print("\n📊 各周期最佳表现对比:")
    for tf in timeframes:
        sub = df_res[df_res["tf"] == tf].iloc[0]
        print(f"  ├─ 周期 [{tf:<4}]: 最佳净利 ¥{sub['pnl']:+10,.2f} | 胜率: {sub['wr']:4.1f}% | 交易: {sub['trades']} 笔 | 参数 (TP={sub['tp']}, SL={sub['sl']}, BE={sub['be']})")


if __name__ == "__main__":
    main()
