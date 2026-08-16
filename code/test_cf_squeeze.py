import sys
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "code"))
from technical_indicators import calculate_atr, calculate_ema, calculate_rsi

DB_PATH = str(PROJECT_ROOT / "data/ashare_quant.db")
conn = sqlite3.connect(DB_PATH, timeout=30.0)
df = pd.read_sql("SELECT trade_time as datetime, open, high, low, close, volume, open_interest FROM futures_min_bars WHERE symbol = 'CF_IDX' AND timeframe = '5m' ORDER BY trade_time ASC;", conn)
conn.close()
df["datetime"] = pd.to_datetime(df["datetime"])
df = df[(df["volume"] > 0) & (df["close"] > 0)].sort_values("datetime").reset_index(drop=True)

c = df["close"].astype(float)
h = df["high"].astype(float)
l = df["low"].astype(float)
v = df["volume"].astype(float)

df_temp = pd.DataFrame({"open": df["open"], "high": h, "low": l, "close": c})
atr = calculate_atr(df_temp, 14).fillna(c * 0.008)
df["atr"] = atr

# Range & Momentum Breakout
# Donchian 40 (about 3.3 hours) + Squeeze
donch_hi = h.rolling(40).max().shift(1)
donch_lo = l.rolling(40).min().shift(1)
squeeze = calculate_atr(df_temp, 5).fillna(c * 0.008) / (calculate_atr(df_temp, 30).fillna(c * 0.008) + 1e-8)
vol_burst = v / (v.rolling(30).mean() + 1e-8)

long_signal = (c > donch_hi) & (squeeze < 0.9) & (vol_burst > 1.2)
short_signal = (c < donch_lo) & (squeeze < 0.9) & (vol_burst > 1.2)

print(f"Total bars: {len(df)}, Long signals: {long_signal.sum()}, Short signals: {short_signal.sum()}")

for tp_mult in [2.5, 3.0, 3.5, 4.0, 5.0]:
    for sl_mult in [0.6, 0.8, 1.0]:
        for be_mult in [1.0, 1.5]:
            pos = 0
            entry_p = 0.0
            sl_p = 0.0
            entry_i = 0
            trades = []
            
            closes = df["close"].values
            highs = df["high"].values
            lows = df["low"].values
            atrs = df["atr"].values
            buys = long_signal.values
            sells = short_signal.values
            
            for i in range(len(df)):
                cp = closes[i]
                hp = highs[i]
                lp = lows[i]
                catr = atrs[i]
                
                if pos != 0:
                    h_bars = i - entry_i
                    pnl_atr = (cp - entry_p)/catr if pos == 1 else (entry_p - cp)/catr
                    
                    if pnl_atr >= be_mult:
                        if pos == 1: sl_p = max(sl_p, entry_p + 0.1 * catr)
                        else: sl_p = min(sl_p, entry_p - 0.1 * catr)
                        
                    hit_tp = pnl_atr >= tp_mult
                    hit_sl = (lp <= sl_p) if pos == 1 else (hp >= sl_p)
                    timeout = h_bars >= 40
                    
                    if hit_tp or hit_sl or timeout:
                        exit_p = (entry_p + tp_mult * catr if pos == 1 else entry_p - tp_mult * catr) if hit_tp else (sl_p if hit_sl else cp)
                        pnl = (exit_p - entry_p)*5.0*8 if pos == 1 else (entry_p - exit_p)*5.0*8
                        fee = (entry_p + exit_p)*5.0*8 * 0.00003
                        trades.append(pnl - fee)
                        pos = 0
                        
                if pos == 0:
                    if buys[i]:
                        pos = 1
                        entry_p = cp + 5.0
                        sl_p = entry_p - sl_mult * catr
                        entry_i = i
                    elif sells[i]:
                        pos = -1
                        entry_p = cp - 5.0
                        sl_p = entry_p + sl_mult * catr
                        entry_i = i
                        
            if len(trades) >= 15:
                tr = np.array(trades)
                wins = tr[tr > 0]
                losses = tr[tr <= 0]
                wr = len(wins)/len(tr) * 100.0
                tot_w = np.sum(wins) if len(wins) > 0 else 0.0
                tot_l = abs(np.sum(losses)) if len(losses) > 0 else 1e-6
                pf = tot_w / tot_l
                payoff = (np.mean(wins) / abs(np.mean(losses))) if (len(wins) > 0 and len(losses) > 0) else 0.0
                net = np.sum(tr)
                print(f"TP={tp_mult}, SL={sl_mult}, BE={be_mult} -> 胜率: {wr:.1f}%, 盈亏比(PF): {pf:.2f}, 单笔盈亏比: {payoff:.2f}, 净利润: {net:+,.2f}元, 交易数: {len(tr)}")
