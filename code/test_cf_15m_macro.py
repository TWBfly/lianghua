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

# 15m resample
df_work = df.copy().set_index("datetime")
df_15m = df_work.resample("15min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
df_temp15 = pd.DataFrame({"open": df_15m["open"], "high": df_15m["high"], "low": df_15m["low"], "close": df_15m["close"]})
df_15m["atr_15m"] = calculate_atr(df_temp15, 14).fillna(df_15m["close"] * 0.008)
df_15m["ema_12"] = calculate_ema(df_15m["close"], 12)
df_15m["ema_26"] = calculate_ema(df_15m["close"], 26)
df_15m["macd_15m"] = (df_15m["ema_12"] - df_15m["ema_26"]) / (df_15m["atr_15m"] + 1e-8)
df_15m["rsi_15m"] = calculate_rsi(df_15m["close"], 14).fillna(50.0)

# Merge 15m shift(1)
df_15m_shift = df_15m[["macd_15m", "rsi_15m", "atr_15m"]].shift(1).dropna().reset_index()
df = pd.merge_asof(df, df_15m_shift, on="datetime", direction="backward").fillna(0)

# 5m features
df_temp = pd.DataFrame({"open": df["open"], "high": h, "low": l, "close": c})
atr = calculate_atr(df_temp, 14).fillna(c * 0.008)
df["atr"] = atr
df["rsi_5m"] = calculate_rsi(pd.Series(c), 14).fillna(50.0)
df["mom_5m"] = (c - c.shift(4)) / (atr + 1e-8)

# Label: 2.0 ATR target, 0.6 ATR stop loss
fut_h = pd.Series(h)[::-1].rolling(24, min_periods=1).max()[::-1].shift(-1)
fut_l = pd.Series(l)[::-1].rolling(24, min_periods=1).min()[::-1].shift(-1)
df["label_l"] = (((fut_h - c) / (atr + 1e-8) >= 2.0) & ((c - fut_l) / (atr + 1e-8) < 0.6)).astype(int)
df["label_s"] = (((c - fut_l) / (atr + 1e-8) >= 2.0) & ((fut_h - c) / (atr + 1e-8) < 0.6)).astype(int)

feats = ["macd_15m", "rsi_15m", "rsi_5m", "mom_5m"]
df_c = df.dropna(subset=feats + ["atr"]).reset_index(drop=True)

# Train ML
train_n = int(len(df_c) * 0.5)
clf_l = lgb.LGBMClassifier(n_estimators=40, max_depth=2, num_leaves=4, learning_rate=0.03, random_state=42, verbose=-1)
clf_s = lgb.LGBMClassifier(n_estimators=40, max_depth=2, num_leaves=4, learning_rate=0.03, random_state=42, verbose=-1)
clf_l.fit(df_c[feats].values[:train_n], df_c["label_l"].values[:train_n])
clf_s.fit(df_c[feats].values[:train_n], df_c["label_s"].values[:train_n])

test_df = df_c.iloc[train_n+20:].copy().reset_index(drop=True)
test_df["prob_l"] = clf_l.predict_proba(test_df[feats].values)[:, 1]
test_df["prob_s"] = clf_s.predict_proba(test_df[feats].values)[:, 1]

print(f"Long label positive rate: {df_c['label_l'].mean():.3f}, Short label: {df_c['label_s'].mean():.3f}")
print("Testing High Precision Thresholds on Cotton 5m...")

for p_th in [0.20, 0.23, 0.26, 0.28, 0.30]:
    for tp in [1.5, 2.0, 2.5]:
        for sl in [0.5, 0.6, 0.8]:
            for be in [0.6, 0.8]:
                pos = 0
                entry_p = 0.0
                sl_p = 0.0
                entry_i = 0
                trades = []
                
                closes = test_df["close"].values
                highs = test_df["high"].values
                lows = test_df["low"].values
                atrs = test_df["atr"].values
                pls = test_df["prob_l"].values
                pss = test_df["prob_s"].values
                
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
                            
                        hit_tp = pnl_atr >= tp
                        hit_sl = (lp <= sl_p) if pos == 1 else (hp >= sl_p)
                        timeout = h_bars >= 24
                        
                        if hit_tp or hit_sl or timeout:
                            exit_p = (entry_p + tp * catr if pos == 1 else entry_p - tp * catr) if hit_tp else (sl_p if hit_sl else cp)
                            pnl = (exit_p - entry_p)*5.0*8 if pos == 1 else (entry_p - exit_p)*5.0*8
                            fee = (entry_p + exit_p)*5.0*8 * 0.00003
                            trades.append(pnl - fee)
                            pos = 0
                            
                    if pos == 0:
                        if pls[i] >= p_th:
                            pos = 1
                            entry_p = cp + 5.0
                            sl_p = entry_p - sl * catr
                            entry_i = i
                        elif pss[i] >= p_th:
                            pos = -1
                            entry_p = cp - 5.0
                            sl_p = entry_p + sl * catr
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
                    if wr >= 40.0 or pf >= 1.5:
                        print(f"🎯 P_TH={p_th}, TP={tp}, SL={sl}, BE={be} -> 胜率: {wr:.1f}%, 盈亏比(PF): {pf:.2f}, 单笔盈亏比: {payoff:.2f}, 净利润: {net:+,.2f}元, 交易数: {len(tr)}")
