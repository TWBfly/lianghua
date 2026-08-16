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

# Multi-timeframe trend: 30m EMA 20 vs 60
df_work = df.copy().set_index("datetime")
df_30m = df_work.resample("30min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
df_30m["ema20"] = calculate_ema(df_30m["close"], 20)
df_30m["ema60"] = calculate_ema(df_30m["close"], 60)
df_30m["macro_trend"] = np.where(df_30m["ema20"] > df_30m["ema60"], 1, np.where(df_30m["ema20"] < df_30m["ema60"], -1, 0))
df_30m["macro_trend_shift"] = df_30m["macro_trend"].shift(1).fillna(0)
df = pd.merge_asof(df, df_30m[["macro_trend_shift"]].reset_index(), on="datetime", direction="backward").fillna(0)

# Intraday 5m Momentum Flow
df["ema10_5m"] = calculate_ema(pd.Series(c), 10)
df["ema30_5m"] = calculate_ema(pd.Series(c), 30)
df["short_trigger"] = (df["macro_trend_shift"] == -1) & (c < df["ema10_5m"]) & (df["ema10_5m"] < df["ema30_5m"]) & (c < df["open"]) & (c == l.rolling(3).min())
df["long_trigger"] = (df["macro_trend_shift"] == 1) & (c > df["ema10_5m"]) & (df["ema10_5m"] > df["ema30_5m"]) & (c > df["open"]) & (c == h.rolling(3).max())

print(f"Long triggers: {df['long_trigger'].sum()}, Short triggers: {df['short_trigger'].sum()}")

# Test Short-Only vs Long-Only vs Both with PPO trailing
for mode in ["SHORT_ONLY", "LONG_ONLY", "BOTH"]:
    for tp_atr in [2.5, 3.5, 4.5]:
        for sl_atr in [0.6, 0.8, 1.0]:
            for be_atr in [0.8, 1.2]:
                pos = 0
                entry_p = 0.0
                sl_p = 0.0
                entry_i = 0
                peak_p = 0.0
                trough_p = 999999.0
                trades = []
                
                closes = df["close"].values
                highs = df["high"].values
                lows = df["low"].values
                atrs = df["atr"].values
                longs = df["long_trigger"].values
                shorts = df["short_trigger"].values
                
                for i in range(len(df)):
                    cp = closes[i]
                    hp = highs[i]
                    lp = lows[i]
                    catr = atrs[i]
                    
                    if pos != 0:
                        h_bars = i - entry_i
                        peak_p = max(peak_p, hp)
                        trough_p = min(trough_p, lp)
                        pnl_atr = (cp - entry_p)/catr if pos == 1 else (entry_p - cp)/catr
                        
                        # Break-even
                        if pnl_atr >= be_atr:
                            if pos == 1: sl_p = max(sl_p, entry_p + 0.1 * catr)
                            else: sl_p = min(sl_p, entry_p - 0.1 * catr)
                            
                        # Trailing
                        if pnl_atr >= be_atr + 1.0:
                            if pos == 1: sl_p = max(sl_p, peak_p - 1.8 * catr)
                            else: sl_p = min(sl_p, trough_p + 1.8 * catr)
                            
                        hit_tp = pnl_atr >= tp_atr
                        hit_sl = (lp <= sl_p) if pos == 1 else (hp >= sl_p)
                        timeout = h_bars >= 40
                        
                        if hit_tp or hit_sl or timeout:
                            exit_p = (entry_p + tp_atr * catr if pos == 1 else entry_p - tp_atr * catr) if hit_tp else (sl_p if hit_sl else cp)
                            pnl = (exit_p - entry_p)*5.0*8 if pos == 1 else (entry_p - exit_p)*5.0*8
                            fee = (entry_p + exit_p)*5.0*8 * 0.00003
                            trades.append(pnl - fee)
                            pos = 0
                            
                    if pos == 0:
                        if mode in ["LONG_ONLY", "BOTH"] and longs[i]:
                            pos = 1
                            entry_p = cp + 5.0
                            sl_p = entry_p - sl_atr * catr
                            peak_p = cp
                            entry_i = i
                        elif mode in ["SHORT_ONLY", "BOTH"] and shorts[i]:
                            pos = -1
                            entry_p = cp - 5.0
                            sl_p = entry_p + sl_atr * catr
                            trough_p = cp
                            entry_i = i
                            
                if len(trades) >= 20:
                    tr = np.array(trades)
                    wins = tr[tr > 0]
                    losses = tr[tr <= 0]
                    wr = len(wins)/len(tr) * 100.0
                    tot_w = np.sum(wins) if len(wins) > 0 else 0.0
                    tot_l = abs(np.sum(losses)) if len(losses) > 0 else 1e-6
                    pf = tot_w / tot_l
                    payoff = (np.mean(wins) / abs(np.mean(losses))) if (len(wins) > 0 and len(losses) > 0) else 0.0
                    net = np.sum(tr)
                    if wr >= 45.0 or pf >= 1.8 or net > 0:
                        print(f"Mode={mode}, TP={tp_atr}, SL={sl_atr}, BE={be_atr} -> 胜率: {wr:.1f}%, 盈亏比(PF): {pf:.2f}, 单笔盈亏比: {payoff:.2f}, 净利润: {net:+,.2f}元, 交易数: {len(tr)}")
