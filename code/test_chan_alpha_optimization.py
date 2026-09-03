"""
code/test_chan_alpha_optimization.py — 缠论正期望 Alpha 优化实验室 (寻找高胜率 + 高盈亏比组合)
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = PROJECT_ROOT / "code"
STRATEGIES_DIR = PROJECT_ROOT / "strategies"
for p in (CODE_DIR, STRATEGIES_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from unified_backtest_pipeline import UnifiedDataProvider, run_strategy_causal_backtest
from chanquant_v5_master_strategy import calculate_factors_v5


def run_experiment(take_profit_atr=3.0, stop_loss_atr=1.5, be_trigger_atr=1.5):
    provider = UnifiedDataProvider()
    symbols = ["RB_IDX", "CU_IDX", "AU_IDX", "SC_IDX"]
    
    print(f"\n--- Testing TP={take_profit_atr} ATR, SL={stop_loss_atr} ATR, BE={be_trigger_atr} ATR ---")
    
    for sym in symbols:
        df_bars, meta = provider.load_or_generate_bars(sym, "15m", target_min_trades=1000)
        factors = calculate_factors_v5(df_bars)
        
        # 优化信号逻辑
        close = df_bars["close"].astype(float).values
        n = len(df_bars)
        signals = np.zeros(n)
        
        is_bull = factors["is_bull"].values
        is_bear = factors["is_bear"].values
        is_chop = factors["is_chop"].values
        b2 = factors["b2"].values
        b3 = factors["b3"].values
        s2 = factors["s2"].values
        s3 = factors["s3"].values
        b1 = factors["b1"].values
        s1 = factors["s1"].values
        adx = factors["adx"].values
        ss_slope = factors["ss_slope"].values
        ofi = factors["ofi_zscore"].values
        zs_low = factors["zs_low"].values
        zs_high = factors["zs_high"].values
        
        for i in range(1, n):
            # 趋势动量态 (ADX >= 20 且 SS斜率配合)
            if is_bull[i] and adx[i] >= 20 and ss_slope[i] > 0.1:
                if b2[i] > 0 or (b3[i] > 0 and ofi[i] > 0):
                    signals[i] = 1.0
            elif is_bear[i] and adx[i] >= 20 and ss_slope[i] < -0.1:
                if s2[i] > 0 or (s3[i] > 0 and ofi[i] < 0):
                    signals[i] = -1.0
            # 震荡态边界回归 (仅在极值边界高抛低吸)
            elif is_chop[i] and adx[i] < 20:
                if b1[i] > 0 and zs_low[i] > 0 and close[i] <= zs_low[i]:
                    signals[i] = 1.0
                elif s1[i] > 0 and zs_high[i] > 0 and close[i] >= zs_high[i]:
                    signals[i] = -1.0
                    
        # 运行回测
        _, sum_1x = run_strategy_causal_backtest(df_bars, sym, signals, timeframe="15m", cost_multiplier=1.0)
        _, sum_3x = run_strategy_causal_backtest(df_bars, sym, signals, timeframe="15m", cost_multiplier=3.0)
        
        if sum_1x.get("trade_count", 0) > 0:
            tc = sum_1x["trade_count"]
            pnl_1x = sum_1x["net_pnl"]
            wr_1x = sum_1x["win_rate"] * 100
            pf_1x = sum_1x["profit_factor"]
            pnl_3x = sum_3x["net_pnl"]
            print(f"  {sym:8s} | {tc:4d} trades | 1x PnL: {pnl_1x:+10.2f} (WR {wr_1x:4.1f}% PF {pf_1x:4.2f}) | 3x PnL: {pnl_3x:+10.2f}")


if __name__ == "__main__":
    run_experiment()
