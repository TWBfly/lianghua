"""
Verify exact alignment of decoupled_5m_symbol_engines with Option 1
"""

import sys
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path
import lightgbm as lgb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "code"))
from symbol_strategies.decoupled_5m_symbol_engines import Decoupled5mSymbolStrategyRunner

runner = Decoupled5mSymbolStrategyRunner()
custom_cfg = {
    "name": "棉花", "category": "软商品", "multiplier": 5.0, "margin": 0.08, "tick_size": 5.0,
    "prob_thresh": 0.23, "target_atr": 4.8, "sl_atr": 1.2, "be_atr": 1.8, "lock_atr": 1.8, "trail_atr": 2.5,
    "max_lots": 8, "max_holding_bars": 45, "horizon": 40, "fee_rate": 0.00003, "require_macro": True,
    "feature_set": ["fast_trend", "slow_trend", "accel_5m", "squeeze_5m", "vol_burst_5m", "donchian_dist_5m", "oi_flow_5m", "rsi_14_5m"]
}

r = runner.run_single_symbol_5m_backtest("CF_IDX", custom_cfg=custom_cfg)
print("=" * 80)
print(f"CF_IDX Alignment Test:")
print(f"  👉 回测起始时间: {r['start_time']}")
print(f"  👉 回测结束时间: {r['end_time']}")
print(f"  👉 首次交易时间: {r['first_trade_time']}")
print(f"  👉 末次交易时间: {r['last_trade_time']}")
print(f"  👉 交易笔数: {r['trades_count']}")
print(f"  👉 胜率: {r['win_rate']}%")
print(f"  👉 盈亏比: {r['profit_factor']}")
print(f"  👉 净利润: {r['total_pnl']:+,} 元")
print("=" * 80)
