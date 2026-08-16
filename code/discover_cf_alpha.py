import sys
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path
import lightgbm as lgb
from sklearn.ensemble import RandomForestClassifier

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
o = df["open"].astype(float)
v = df["volume"].astype(float)

df_temp = pd.DataFrame({"open": o, "high": h, "low": l, "close": c})
atr = calculate_atr(df_temp, 14).fillna(c * 0.008)
df["atr"] = atr

# Rich Feature Set
# 1. EMAs & Price ratios
for period in [5, 10, 20, 40, 80, 160]:
    df[f"ema_{period}"] = calculate_ema(pd.Series(c), period)
    df[f"dist_ema_{period}"] = (c - df[f"ema_{period}"]) / (atr + 1e-8)

# 2. Daily/Session context
df["hour"] = df["datetime"].dt.hour
df["day_of_week"] = df["datetime"].dt.dayofweek

# 3. RSIs & Oscillators
df["rsi_6"] = calculate_rsi(pd.Series(c), 6).fillna(50.0)
df["rsi_14"] = calculate_rsi(pd.Series(c), 14).fillna(50.0)
df["rsi_24"] = calculate_rsi(pd.Series(c), 24).fillna(50.0)

# 4. Volatility & Breakout
df["donch_hi_20"] = (h.rolling(20).max().shift(1) - c) / (atr + 1e-8)
df["donch_lo_20"] = (c - l.rolling(20).min().shift(1)) / (atr + 1e-8)
df["squeeze"] = calculate_atr(df_temp, 5).fillna(c * 0.008) / (calculate_atr(df_temp, 30).fillna(c * 0.008) + 1e-8)
df["vol_burst"] = v / (v.rolling(20).mean() + 1e-8)

# 5. Consecutive bars / Candlestick patterns
df["body"] = (c - o) / (atr + 1e-8)
df["upper_shadow"] = (h - np.maximum(c, o)) / (atr + 1e-8)
df["lower_shadow"] = (np.minimum(c, o) - l) / (atr + 1e-8)

# 6. Multi-Horizon Labeling (Try horizon 12, 20, 30, 45)
feature_cols = [
    "dist_ema_5", "dist_ema_10", "dist_ema_20", "dist_ema_40", "dist_ema_80", "dist_ema_160",
    "rsi_6", "rsi_14", "rsi_24", "donch_hi_20", "donch_lo_20", "squeeze", "vol_burst",
    "body", "upper_shadow", "lower_shadow", "hour", "day_of_week"
]

print("Features built. Scanning labeling horizons...")

for horizon in [12, 20, 30, 45]:
    for target_r in [1.8, 2.2, 2.6, 3.0]:
        for sl_r in [0.6, 0.8, 1.0]:
            fut_h = pd.Series(h)[::-1].rolling(horizon, min_periods=1).max()[::-1].shift(-1)
            fut_l = pd.Series(l)[::-1].rolling(horizon, min_periods=1).min()[::-1].shift(-1)
            
            y_l = (((fut_h - c) / (atr + 1e-8) >= target_r) & ((c - fut_l) / (atr + 1e-8) < sl_r)).astype(int).values
            y_s = (((c - fut_l) / (atr + 1e-8) >= target_r) & ((fut_h - c) / (atr + 1e-8) < sl_r)).astype(int).values
            
            df_clean = df.dropna(subset=feature_cols + ["atr"]).copy().reset_index(drop=True)
            X = df_clean[feature_cols].values
            
            n = len(df_clean)
            train_n = int(n * 0.5)
            
            # Fast LightGBM
            clf_l = lgb.LGBMClassifier(n_estimators=40, max_depth=3, num_leaves=6, learning_rate=0.03, random_state=42, verbose=-1)
            clf_s = lgb.LGBMClassifier(n_estimators=40, max_depth=3, num_leaves=6, learning_rate=0.03, random_state=42, verbose=-1)
            
            clf_l.fit(X[:train_n], y_l[:train_n])
            clf_s.fit(X[:train_n], y_s[:train_n])
            
            test_X = X[train_n+20:]
            test_df = df_clean.iloc[train_n+20:].copy().reset_index(drop=True)
            test_df["prob_l"] = clf_l.predict_proba(test_X)[:, 1]
            test_df["prob_s"] = clf_s.predict_proba(test_X)[:, 1]
            
            for p_th in [0.22, 0.26, 0.30, 0.35]:
                for be in [0.6, 1.0]:
                    closes = test_df["close"].values
                    highs = test_df["high"].values
                    lows = test_df["low"].values
                    atrs = test_df["atr"].values
                    pls = test_df["prob_l"].values
                    pss = test_df["prob_s"].values
                    
                    pos = 0
                    entry_p = 0.0
                    sl_p = 0.0
                    entry_i = 0
                    trades = []
                    
                    for i in range(len(test_df)):
                        cp = closes[i]
                        hp = highs[i]
                        lp = lows[i]
                        catr = atrs[i]
                        
                        if pos != 0:
                            h_bars = i - entry_i
                            pnl_atr = (cp - entry_p)/catr if pos == 1 else (entry_p - cp)/catr
                            if pnl_atr >= be:
                                if pos == 1: sl_p = max(sl_p, entry_p + 0.1 * catr)
                                else: sl_p = min(sl_p, entry_p - 0.1 * catr)
                                
                            hit_tp = pnl_atr >= target_r
                            hit_sl = (lp <= sl_p) if pos == 1 else (hp >= sl_p)
                            timeout = h_bars >= horizon
                            
                            if hit_tp or hit_sl or timeout:
                                exit_p = (entry_p + target_r * catr if pos == 1 else entry_p - target_r * catr) if hit_tp else (sl_p if hit_sl else cp)
                                pnl = (exit_p - entry_p)*5.0*8 if pos == 1 else (entry_p - exit_p)*5.0*8
                                fee = (entry_p + exit_p)*5.0*8 * 0.00003
                                trades.append(pnl - fee)
                                pos = 0
                                
                        if pos == 0:
                            if pls[i] >= p_th:
                                pos = 1
                                entry_p = cp + 5.0
                                sl_p = entry_p - sl_r * catr
                                entry_i = i
                            elif pss[i] >= p_th:
                                pos = -1
                                entry_p = cp - 5.0
                                sl_p = entry_p + sl_r * catr
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
                        if wr >= 45.0 and pf >= 1.2:
                            print(f"🔥 H={horizon}, TP={target_r}, SL={sl_r}, P_TH={p_th}, BE={be} -> 胜率: {wr:.1f}%, PF: {pf:.2f}, Payoff: {payoff:.2f}, 净利润: {net:+,.2f}元, 交易数: {len(tr)}")
