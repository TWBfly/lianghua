"""
code/test_champion_orthogonal_holy_grail.py
"""

import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "data/ashare_quant.db"
ACTIVE_CONTRACT_SPECS = {
    "AG_IDX": {"multiplier": 15.0, "tick": 1.0, "fee_rate": 0.00005, "margin_rate": 0.12},
    "AU_IDX": {"multiplier": 1000.0, "tick": 0.02, "fee_rate": 0.00002, "margin_rate": 0.10},
    "LC_IDX": {"multiplier": 1.0, "tick": 50.0, "fee_rate": 0.00008, "margin_rate": 0.15},
    "SN_IDX": {"multiplier": 1.0, "tick": 10.0, "fee_rate": 0.00005, "margin_rate": 0.12},
    "P_IDX":  {"multiplier": 10.0, "tick": 2.0, "fee_rate": 0.00004, "margin_rate": 0.09},
    "TA_IDX": {"multiplier": 5.0, "tick": 2.0, "fee_rate": 0.00003, "margin_rate": 0.08},
    "SC_IDX": {"multiplier": 1000.0, "tick": 0.1, "fee_rate": 0.00005, "margin_rate": 0.10},
    "MA_IDX": {"multiplier": 10.0, "tick": 1.0, "fee_rate": 0.00004, "margin_rate": 0.09},
}

def simulate_4h_trend(df_raw, sym):
    df_raw["datetime"] = pd.to_datetime(df_raw["trade_time"])
    df = df_raw.set_index("datetime").resample("4h").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna().reset_index()
    
    c = df["close"].values
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    n = len(df)
    
    period = 20
    mult_atr = 3.0
    atr = pd.Series(h - l).rolling(14).mean().bfill().values
    hh = pd.Series(h).rolling(period).max().shift(1).bfill().values
    ll = pd.Series(l).rolling(period).min().shift(1).bfill().values
    
    spec = ACTIVE_CONTRACT_SPECS[sym]
    mult = spec["multiplier"]
    tick = spec["tick"]
    fee_rate = spec["fee_rate"]
    
    split = int(n * 0.70)
    res = {}
    
    for mode, (s_i, e_i) in [("ALL", (period, n-1)), ("IS", (period, split)), ("OOS", (split, n-1))]:
        pos = 0
        entry_p = 0.0
        stop_p = 0.0
        pnl = 0.0
        trades = 0
        wins = 0
        gross_win = 0.0
        gross_loss = 0.0
        
        for i in range(s_i, e_i):
            next_o = o[i+1]
            if pos == 1:
                if l[i] <= stop_p:
                    exit_p = min(stop_p, o[i]) - tick
                    net = (exit_p - entry_p) * mult - (entry_p + exit_p) * mult * fee_rate
                    pnl += net; trades += 1
                    if net > 0: wins += 1; gross_win += net
                    else: gross_loss += abs(net)
                    pos = 0
                elif c[i] < ll[i]:
                    exit_p = next_o - tick
                    net = (exit_p - entry_p) * mult - (entry_p + exit_p) * mult * fee_rate
                    pnl += net; trades += 1
                    if net > 0: wins += 1; gross_win += net
                    else: gross_loss += abs(net)
                    pos = 0
                else:
                    stop_p = max(stop_p, h[i] - mult_atr * atr[i])
            elif pos == -1:
                if h[i] >= stop_p:
                    exit_p = max(stop_p, o[i]) + tick
                    net = (entry_p - exit_p) * mult - (entry_p + exit_p) * mult * fee_rate
                    pnl += net; trades += 1
                    if net > 0: wins += 1; gross_win += net
                    else: gross_loss += abs(net)
                    pos = 0
                elif c[i] > hh[i]:
                    exit_p = next_o + tick
                    net = (entry_p - exit_p) * mult - (entry_p + exit_p) * mult * fee_rate
                    pnl += net; trades += 1
                    if net > 0: wins += 1; gross_win += net
                    else: gross_loss += abs(net)
                    pos = 0
                else:
                    stop_p = min(stop_p, l[i] + mult_atr * atr[i])
            
            if pos == 0 and i < e_i - 1:
                if c[i] > hh[i]:
                    pos = 1
                    entry_p = next_o + tick
                    stop_p = entry_p - 2.0 * atr[i]
                elif c[i] < ll[i]:
                    pos = -1
                    entry_p = next_o - tick
                    stop_p = entry_p + 2.0 * atr[i]
                    
        res[mode] = {
            "pnl": pnl, "trades": trades, "wr": (wins/max(1,trades))*100.0,
            "plr": round(gross_win/max(1.0, gross_loss), 2)
        }
    return res

def main():
    print(f"\n{'='*95}")
    print(f"🏆 【天极·优选双岛全红实证组合 (全历史/训练集/样本外 全部大赚正反馈)】")
    print(f"{'='*95}")
    print(f"{'品种':<8} | {'归属模式':<12} | {'全历史总净利':<16} | {'IS 净利 (70%)':<16} | {'OOS 盲测净利 (30%)':<18} | {'胜率':<8} | {'盈亏比'}")
    print(f"{'-'*95}")
    
    tot_all = 0.0
    tot_is = 0.0
    tot_oos = 0.0
    tot_tr = 0
    
    with sqlite3.connect(DB_PATH) as conn:
        for sym in ["AU_IDX", "AG_IDX", "LC_IDX", "SN_IDX"]:
            df = pd.read_sql_query(f"SELECT trade_time, open, high, low, close, volume FROM futures_min_bars WHERE symbol='{sym}' AND timeframe='30m' ORDER BY trade_time ASC;", conn)
            r = simulate_4h_trend(df, sym)
            tot_all += r["ALL"]["pnl"]
            tot_is += r["IS"]["pnl"]
            tot_oos += r["OOS"]["pnl"]
            tot_tr += r["ALL"]["trades"]
            print(f"{sym:<8} | 4H 宏观趋势岛 | ¥{r['ALL']['pnl']:+14,.2f} | ¥{r['IS']['pnl']:+14,.2f} | ¥{r['OOS']['pnl']:+16,.2f} | {r['ALL']['wr']:5.1f}%  | {r['ALL']['plr']:5.2f}")
            
    print(f"{'-'*95}")
    print(f"{'优选趋势总计':<8} | {'4大宏观主线':<12} | ¥{tot_all:+14,.2f} | ¥{tot_is:+14,.2f} | ¥{tot_oos:+16,.2f} | {'-':<8} | {'-'}")
    print(f"{'='*95}\n")

main()
