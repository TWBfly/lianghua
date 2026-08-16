"""
Direct Test on Cotton (CF_IDX) with SC/J/JM High-PF Architecture
"""

import sys
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "code"))
from symbol_strategies.decoupled_5m_symbol_engines import Decoupled5mSymbolStrategyRunner

runner = Decoupled5mSymbolStrategyRunner()

cf_test_configs = [
    {
        "name": "棉花-宏观强过滤1", "category": "软商品", "multiplier": 5.0, "margin": 0.08, "tick_size": 5.0,
        "prob_thresh": 0.28, "target_atr": 3.0, "sl_atr": 0.8, "be_atr": 1.0, "lock_atr": 2.0, "trail_atr": 2.2,
        "max_lots": 8, "max_holding_bars": 30, "fee_rate": 0.00003, "require_macro": True,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    {
        "name": "棉花-宏观强过滤2", "category": "软商品", "multiplier": 5.0, "margin": 0.08, "tick_size": 5.0,
        "prob_thresh": 0.30, "target_atr": 3.2, "sl_atr": 0.8, "be_atr": 1.2, "lock_atr": 2.2, "trail_atr": 2.0,
        "max_lots": 8, "max_holding_bars": 25, "fee_rate": 0.00003, "require_macro": True,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    {
        "name": "棉花-宏观强过滤3", "category": "软商品", "multiplier": 5.0, "margin": 0.08, "tick_size": 5.0,
        "prob_thresh": 0.32, "target_atr": 3.5, "sl_atr": 0.8, "be_atr": 1.2, "lock_atr": 2.4, "trail_atr": 2.0,
        "max_lots": 8, "max_holding_bars": 25, "fee_rate": 0.00003, "require_macro": True,
        "feature_set": ["squeeze_5m", "accel_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    },
    {
        "name": "棉花-波段与量能增强", "category": "软商品", "multiplier": 5.0, "margin": 0.08, "tick_size": 5.0,
        "prob_thresh": 0.30, "target_atr": 3.2, "sl_atr": 0.8, "be_atr": 1.1, "lock_atr": 2.0, "trail_atr": 2.2,
        "max_lots": 8, "max_holding_bars": 30, "fee_rate": 0.00003, "require_macro": True,
        "feature_set": ["fast_trend", "slow_trend", "accel_5m", "squeeze_5m", "vol_burst_5m", "donchian_dist_5m"]
    },
    {
        "name": "棉花-大单边捕获", "category": "软商品", "multiplier": 5.0, "margin": 0.08, "tick_size": 5.0,
        "prob_thresh": 0.28, "target_atr": 3.5, "sl_atr": 0.9, "be_atr": 1.4, "lock_atr": 2.5, "trail_atr": 2.0,
        "max_lots": 8, "max_holding_bars": 35, "horizon": 30, "fee_rate": 0.00003, "require_macro": True,
        "feature_set": ["fast_trend", "slow_trend", "rsi_14_5m", "donchian_dist_5m", "oi_flow_5m", "squeeze_5m"]
    }
]

for idx, cfg in enumerate(cf_test_configs, 1):
    res = runner.run_single_symbol_5m_backtest("CF_IDX", custom_cfg=cfg)
    print(f"[{cfg['name']}]: Trades={res['trades_count']}, WinRate={res['win_rate']}%, ProfitFactor={res['profit_factor']}, Sharpe={res['sharpe_ratio']}, MaxDD={res['max_drawdown_pct']}%, NetPnL={res['total_pnl']:+,.2f}元, Return={res['return_pct']}%")
