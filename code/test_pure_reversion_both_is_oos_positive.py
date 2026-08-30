"""
code/test_pure_reversion_both_is_oos_positive.py
"""

import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "data/ashare_quant.db"
ACTIVE_CONTRACT_SPECS = {
    "AG_IDX": {"multiplier": 15.0, "tick": 1.0, "fee_rate": 0.00005, "margin_rate": 0.12},
    "AU_IDX": {"multiplier": 1000.0, "tick": 0.02, "fee_rate": 0.00002, "margin_rate": 0.10},
    "SC_IDX": {"multiplier": 1000.0, "tick": 0.1, "fee_rate": 0.00005, "margin_rate": 0.10},
    "RB_IDX": {"multiplier": 10.0, "tick": 1.0, "fee_rate": 0.0001, "margin_rate": 0.10},
    "TA_IDX": {"multiplier": 5.0, "tick": 2.0, "fee_rate": 0.00003, "margin_rate": 0.08},
    "MA_IDX": {"multiplier": 10.0, "tick": 1.0, "fee_rate": 0.00004, "margin_rate": 0.09},
    "P_IDX":  {"multiplier": 10.0, "tick": 2.0, "fee_rate": 0.00004, "margin_rate": 0.09},
}

def test_reversion():
    with sqlite3.connect(DB_PATH) as conn:
        for sym in ["P_IDX", "TA_IDX", "SC_IDX", "MA_IDX", "RB_IDX", "AU_IDX"]:
            df = pd.read_sql_query(f"SELECT trade_time, open, high, low, close, volume FROM futures_min_bars WHERE symbol='{sym}' AND timeframe='30m' ORDER BY trade_time ASC;", conn)
            c = df["close"].values
            o = df["open"].values
            h = df["high"].values
            l = df["low"].values
            n = len(df)
            
            # Bollinger Bands / Moving Average Reversion + Stop
            period = 20
            sma = pd.Series(c).rolling(period).mean().bfill().values
            std = pd.Series(c).rolling(period).std().bfill().values + 1e-8
            upper = sma + 2.0 * std
            lower = sma - 2.0 * std
            atr = pd.Series(h - l).rolling(14).mean().bfill().values
            
            spec = ACTIVE_CONTRACT_SPECS[sym]
            mult = spec["multiplier"]
            tick = spec["tick"]
            fee_rate = spec["fee_rate"]
            
            split = int(n * 0.7)
            for mode, (start_i, end_i) in [("IS", (50, split)), ("OOS", (split, n-1)), ("FULL", (50, n-1))]:
                pos = 0
                entry_p = 0.0
                stop_p = 0.0
                pnl = 0.0
                trades = 0
                wins = 0
                
                for i in range(start_i, end_i):
                    next_o = o[i+1]
                    # Exit logic
                    if pos == 1:
                        if c[i] >= sma[i]: # Reversion target reached
                            exit_p = next_o - tick
                            net = (exit_p - entry_p) * mult - (entry_p + exit_p) * mult * fee_rate
                            pnl += net
                            trades += 1
                            if net > 0: wins += 1
                            pos = 0
                        elif l[i] <= stop_p: # Hard stop
                            exit_p = min(stop_p, o[i]) - tick
                            net = (exit_p - entry_p) * mult - (entry_p + exit_p) * mult * fee_rate
                            pnl += net
                            trades += 1
                            if net > 0: wins += 1
                            pos = 0
                    elif pos == -1:
                        if c[i] <= sma[i]:
                            exit_p = next_o + tick
                            net = (entry_p - exit_p) * mult - (entry_p + exit_p) * mult * fee_rate
                            pnl += net
                            trades += 1
                            if net > 0: wins += 1
                            pos = 0
                        elif h[i] >= stop_p:
                            exit_p = max(stop_p, o[i]) + tick
                            net = (entry_p - exit_p) * mult - (entry_p + exit_p) * mult * fee_rate
                            pnl += net
                            trades += 1
                            if net > 0: wins += 1
                            pos = 0
                    
                    # Entry logic
                    if pos == 0 and i < end_i - 1:
                        if c[i] < lower[i] and c[i-1] >= lower[i-1]: # Oversold breakout
                            pos = 1
                            entry_p = next_o + tick
                            stop_p = entry_p - 2.0 * atr[i]
                        elif c[i] > upper[i] and c[i-1] <= upper[i-1]: # Overbought breakout
                            pos = -1
                            entry_p = next_o - tick
                            stop_p = entry_p + 2.0 * atr[i]
                            
                wr = (wins / max(1, trades)) * 100.0
                print(f"{sym:<8} | {mode:<4} | 交易: {trades:<4} | 胜率: {wr:5.1f}% | 净利润: ¥{pnl:+12,.2f}")

test_reversion()
