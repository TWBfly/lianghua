import sys
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path
import lightgbm as lgb

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

# 1. Macro Trend (Daily/4H proxy: 60m EMA20 vs EMA60)
df_work = df.copy().set_index("datetime")
df_60m = df_work.resample("60min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
df_60m["ema20"] = calculate_ema(df_60m["close"], 20)
df_60m["ema60"] = calculate_ema(df_60m["close"], 60)
df_60m["macro_long"] = (df_60m["close"] > df_60m["ema20"]) & (df_60m["ema20"] > df_60m["ema60"])
df_60m["macro_short"] = (df_60m["close"] < df_60m["ema20"]) & (df_60m["ema20"] < df_60m["ema60"])
df_60m["macro_state"] = np.where(df_60m["macro_long"], 1, np.where(df_60m["macro_short"], -1, 0))
df_60m["macro_trend"] = df_60m["macro_state"].shift(1).fillna(0)
df = pd.merge_asof(df, df_60m[["macro_trend"]].reset_index(), on="datetime", direction="backward").fillna(0)

# 2. Micro Pullback (5m 回踩均线 + KDJ/RSI 超卖反弹)
df["ema20_5m"] = calculate_ema(pd.Series(c), 20)
df["dist_ema20"] = (c - df["ema20_5m"]) / (atr + 1e-8)
df["rsi_7"] = calculate_rsi(pd.Series(c), 7).fillna(50.0)

# Pullback Signal:
# Long: 60m 宏观多头中，5m 回踩 EMA20 附近 (dist_ema20 <= 0.3 且 RSI7 <= 45)，然后收出阳线 (close > open)
# Short: 60m 宏观空头中，5m 反弹 EMA20 附近 (dist_ema20 >= -0.3 且 RSI7 >= 55)，然后收出阴线 (close < open)
df["pullback_buy"] = (df["macro_trend"] == 1) & (df["dist_ema20"] <= 0.4) & (df["dist_ema20"] >= -0.8) & (df["rsi_7"] <= 45) & (c > df["open"])
df["pullback_sell"] = (df["macro_trend"] == -1) & (df["dist_ema20"] >= -0.4) & (df["dist_ema20"] <= 0.8) & (df["rsi_7"] >= 55) & (c < df["open"])

# Test Pullback Strategy
for tp_atr in [1.5, 2.0, 2.5, 3.0]:
    for sl_atr in [0.4, 0.5, 0.6, 0.7]:
        for be_atr in [0.6, 0.8, 1.0]:
            for max_hold in [15, 25, 35]:
                pos = 0
                entry_p = 0.0
                sl_p = 0.0
                entry_i = 0
                trades = []
                
                closes = df["close"].values
                highs = df["high"].values
                lows = df["low"].values
                atrs = df["atr"].values
                buys = df["pullback_buy"].values
                sells = df["pullback_sell"].values
                
                for i in range(len(df)):
                    cp = closes[i]
                    hp = highs[i]
                    lp = lows[i]
                    catr = atrs[i]
                    
                    if pos != 0:
                        h_bars = i - entry_i
                        pnl_atr = (cp - entry_p)/catr if pos == 1 else (entry_p - cp)/catr
                        
                        # Break-even
                        if pnl_atr >= be_atr:
                            if pos == 1: sl_p = max(sl_p, entry_p + 0.1 * catr)
                            else: sl_p = min(sl_p, entry_p - 0.1 * catr)
                        
                        hit_tp = pnl_atr >= tp_atr
                        hit_sl = (lp <= sl_p) if pos == 1 else (hp >= sl_p)
                        timeout = h_bars >= max_hold
                        
                        if hit_tp or hit_sl or timeout:
                            exit_p = (entry_p + tp_atr * catr if pos == 1 else entry_p - tp_atr * catr) if hit_tp else (sl_p if hit_sl else cp)
                            pnl = (exit_p - entry_p)*5.0*8 if pos == 1 else (entry_p - exit_p)*5.0*8
                            fee = (entry_p + exit_p)*5.0*8 * 0.00003
                            trades.append(pnl - fee)
                            pos = 0
                            
                    if pos == 0:
                        if buys[i]:
                            pos = 1
                            entry_p = cp + 5.0
                            sl_p = entry_p - sl_atr * catr
                            entry_i = i
                        elif sells[i]:
                            pos = -1
                            entry_p = cp - 5.0
                            sl_p = entry_p + sl_atr * catr
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
                    if wr >= 48.0 or pf >= 2.0 or net > 0:
                        print(f"🌟 Pullback Strategy: 胜率={wr:.1f}%, 盈亏比(PF)={pf:.2f}, 单笔盈亏比={payoff:.2f}, 净利润={net:+,.2f}元, 交易数={len(tr)}, 参数: tp={tp_atr}, sl={sl_atr}, be={be_atr}, hold={max_hold}")
