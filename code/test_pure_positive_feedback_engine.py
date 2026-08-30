"""
code/test_pure_positive_feedback_engine.py — 探索全样本全红正反馈策略引擎
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path

DB_PATH = "data/ashare_quant.db"
ACTIVE_CONTRACT_SPECS = {
    "AG_IDX": {"multiplier": 15.0, "tick": 1.0, "fee_rate": 0.00005, "margin_rate": 0.12},
    "AU_IDX": {"multiplier": 1000.0, "tick": 0.02, "fee_rate": 0.00002, "margin_rate": 0.10},
    "LC_IDX": {"multiplier": 1.0, "tick": 50.0, "fee_rate": 0.00008, "margin_rate": 0.15},
    "SN_IDX": {"multiplier": 1.0, "tick": 10.0, "fee_rate": 0.00005, "margin_rate": 0.12},
    "CU_IDX": {"multiplier": 5.0, "tick": 10.0, "fee_rate": 0.00005, "margin_rate": 0.10},
    "SC_IDX": {"multiplier": 1000.0, "tick": 0.1, "fee_rate": 0.00005, "margin_rate": 0.10},
    "RB_IDX": {"multiplier": 10.0, "tick": 1.0, "fee_rate": 0.0001, "margin_rate": 0.10},
    "TA_IDX": {"multiplier": 5.0, "tick": 2.0, "fee_rate": 0.00003, "margin_rate": 0.08},
    "MA_IDX": {"multiplier": 10.0, "tick": 1.0, "fee_rate": 0.00004, "margin_rate": 0.09},
    "P_IDX":  {"multiplier": 10.0, "tick": 2.0, "fee_rate": 0.00004, "margin_rate": 0.09},
}

def test_trend_and_mean_reversion():
    with sqlite3.connect(DB_PATH) as conn:
        for sym in ["AU_IDX", "AG_IDX", "TA_IDX", "P_IDX", "SC_IDX", "MA_IDX"]:
            df = pd.read_sql_query(f"SELECT trade_time, open, high, low, close, volume FROM futures_min_bars WHERE symbol='{sym}' AND timeframe='30m' ORDER BY trade_time ASC;", conn)
            c = df["close"].values
            o = df["open"].values
            h = df["high"].values
            l = df["low"].values
            n = len(df)
            
            # Simple, robust Donchian/Kalman/EMA crossover + ATR Trailing Stop
            # Let's test a zero-lag Ehlers SuperSmoother
            a1 = np.exp(-1.414 * 3.14159 / 12.0)
            b1 = 2 * a1 * np.cos(1.414 * 180 / 12.0 * 3.14159 / 180.0)
            c2 = b1
            c3 = -a1 * a1
            c1 = 1 - c2 - c3
            filt = np.zeros(n)
            filt[0] = c[0]
            filt[1] = c[1]
            for t in range(2, n):
                filt[t] = c1 * (c[t] + c[t-1]) / 2.0 + c2 * filt[t-1] + c3 * filt[t-2]
            
            atr = pd.Series(h - l).rolling(14).mean().bfill().values
            
            # Test IS and OOS
            split = int(n * 0.7)
            for mode, (start_i, end_i) in [("IS", (50, split)), ("OOS", (split, n-1))]:
                pos = 0
                entry_p = 0.0
                stop_p = 0.0
                pnl = 0.0
                trades = 0
                wins = 0
                spec = ACTIVE_CONTRACT_SPECS[sym]
                mult = spec["multiplier"]
                tick = spec["tick"]
                fee_rate = spec["fee_rate"]
                
                for i in range(start_i, end_i):
                    # Check exit
                    next_o = o[i+1]
                    if pos == 1:
                        if l[i] <= stop_p: # Stop out
                            exit_p = min(stop_p, o[i]) - tick
                            net = (exit_p - entry_p) * mult - (entry_p + exit_p) * mult * fee_rate
                            pnl += net
                            trades += 1
                            if net > 0: wins += 1
                            pos = 0
                        elif filt[i] < filt[i-1]: # Trend reversal
                            exit_p = next_o - tick
                            net = (exit_p - entry_p) * mult - (entry_p + exit_p) * mult * fee_rate
                            pnl += net
                            trades += 1
                            if net > 0: wins += 1
                            pos = 0
                        else:
                            # Trailing stop
                            stop_p = max(stop_p, h[i] - 2.5 * atr[i])
                    elif pos == -1:
                        if h[i] >= stop_p:
                            exit_p = max(stop_p, o[i]) + tick
                            net = (entry_p - exit_p) * mult - (entry_p + exit_p) * mult * fee_rate
                            pnl += net
                            trades += 1
                            if net > 0: wins += 1
                            pos = 0
                        elif filt[i] > filt[i-1]:
                            exit_p = next_o + tick
                            net = (entry_p - exit_p) * mult - (entry_p + exit_p) * mult * fee_rate
                            pnl += net
                            trades += 1
                            if net > 0: wins += 1
                            pos = 0
                        else:
                            stop_p = min(stop_p, l[i] + 2.5 * atr[i])
                    
                    # Check entry
                    if pos == 0 and i < end_i - 1:
                        if filt[i] > filt[i-1] and filt[i-1] <= filt[i-2] and c[i] > filt[i]:
                            pos = 1
                            entry_p = next_o + tick
                            stop_p = entry_p - 2.0 * atr[i]
                        elif filt[i] < filt[i-1] and filt[i-1] >= filt[i-2] and c[i] < filt[i]:
                            pos = -1
                            entry_p = next_o - tick
                            stop_p = entry_p + 2.0 * atr[i]
                
                wr = (wins / max(1, trades)) * 100.0
                print(f"{sym:<8} | {mode:<4} | 交易: {trades:<4} | 胜率: {wr:5.1f}% | 净利润: ¥{pnl:+12,.2f}")

test_trend_and_mean_reversion()
