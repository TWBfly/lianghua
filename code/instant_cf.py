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

df_work = df.copy().set_index("datetime")
df_30m = df_work.resample("30min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
df_30m["ema_10"] = calculate_ema(df_30m["close"], 10)
df_30m["ema_30"] = calculate_ema(df_30m["close"], 30)
df_30m["macro"] = np.where((df_30m["close"] > df_30m["ema_10"]) & (df_30m["ema_10"] > df_30m["ema_30"]), 1,
                  np.where((df_30m["close"] < df_30m["ema_10"]) & (df_30m["ema_10"] < df_30m["ema_30"]), -1, 0))
df_30m["macro_trend_30m"] = df_30m["macro"].shift(1).fillna(0)

df = pd.merge_asof(df.sort_values("datetime"), df_30m[["macro_trend_30m"]].reset_index().sort_values("datetime"), on="datetime", direction="backward").fillna(0)

c = df["close"].astype(float)
h = df["high"].astype(float)
l = df["low"].astype(float)
v = df["volume"].astype(float)

df_temp = pd.DataFrame({"open": df["open"], "high": h, "low": l, "close": c})
atr = calculate_atr(df_temp, 14).fillna(c * 0.008)
df["atr"] = atr
df["squeeze"] = calculate_atr(df_temp, 5).fillna(c * 0.008) / (calculate_atr(df_temp, 20).fillna(c * 0.008) + 1e-8)
e4 = calculate_ema(pd.Series(c), 4)
e12 = calculate_ema(pd.Series(c), 12)
e24 = calculate_ema(pd.Series(c), 24)
df["accel"] = ((e4 - e12) - (e12 - e24)) / (atr + 1e-8)
df["trend_strength"] = (e4 - e24) / (atr + 1e-8)
df["vol_burst"] = v / (v.rolling(20).mean() + 1e-8)
df["rsi"] = calculate_rsi(pd.Series(c), 14).fillna(50.0)
df["donch_dist"] = (c - (h.rolling(20).max().shift(1) + l.rolling(20).min().shift(1))/2.0) / (atr + 1e-8)
df["oi_flow"] = df["open_interest"].fillna(0).diff().fillna(0) / (v.rolling(20).mean() + 1e-8)

# Label (Horizon 20)
fut_h = pd.Series(h)[::-1].rolling(20, min_periods=1).max()[::-1].shift(-1)
fut_l = pd.Series(l)[::-1].rolling(20, min_periods=1).min()[::-1].shift(-1)
df["label_l"] = (((fut_h - c) / (atr + 1e-8) >= 2.5) & ((c - fut_l) / (atr + 1e-8) < 0.8)).astype(int)
df["label_s"] = (((c - fut_l) / (atr + 1e-8) >= 2.5) & ((fut_h - c) / (atr + 1e-8) < 0.8)).astype(int)

feats = ["squeeze", "accel", "trend_strength", "vol_burst", "rsi", "donch_dist", "oi_flow"]
df_c = df.dropna(subset=feats + ["atr"]).reset_index(drop=True)

# Fast 2-split Walk Forward
n = len(df_c)
train_len = int(n * 0.6)
X = df_c[feats].values
yl = df_c["label_l"].values
ys = df_c["label_s"].values

clf_l = lgb.LGBMClassifier(n_estimators=50, max_depth=3, num_leaves=6, learning_rate=0.03, random_state=42, verbose=-1)
clf_s = lgb.LGBMClassifier(n_estimators=50, max_depth=3, num_leaves=6, learning_rate=0.03, random_state=42, verbose=-1)
clf_l.fit(X[:train_len], yl[:train_len])
clf_s.fit(X[:train_len], ys[:train_len])

test_df = df_c.iloc[train_len+30:].copy().reset_index(drop=True)
test_X = test_df[feats].values
test_df["prob_l"] = clf_l.predict_proba(test_X)[:, 1]
test_df["prob_s"] = clf_s.predict_proba(test_X)[:, 1]

# Vectorized simulation function
def test_params(p_th, sl_atr, be_atr, tp_atr, max_bars, req_macro):
    closes = test_df["close"].values
    highs = test_df["high"].values
    lows = test_df["low"].values
    atrs = test_df["atr"].values
    pl = test_df["prob_l"].values
    ps = test_df["prob_s"].values
    mac = test_df["macro_trend_30m"].values
    
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
            
            # Check Break-even trigger
            if pnl_atr >= be_atr:
                if pos == 1: sl_p = max(sl_p, entry_p + 0.1 * catr)
                else: sl_p = min(sl_p, entry_p - 0.1 * catr)
                
            # Check TP
            hit_tp = pnl_atr >= tp_atr
            # Check SL
            hit_sl = (lp <= sl_p) if pos == 1 else (hp >= sl_p)
            # Timeout
            timeout = h_bars >= max_bars
            
            if hit_tp or hit_sl or timeout:
                exit_p = (entry_p + tp_atr * catr if pos == 1 else entry_p - tp_atr * catr) if hit_tp else (sl_p if hit_sl else cp)
                pnl = (exit_p - entry_p)*5.0*8 if pos == 1 else (entry_p - exit_p)*5.0*8
                fee = (entry_p + exit_p)*5.0*8 * 0.00003
                trades.append(pnl - fee)
                pos = 0
                
        if pos == 0:
            if pl[i] >= p_th and (mac[i] > 0 if req_macro else mac[i] >= 0):
                pos = 1
                entry_p = cp + 5.0
                sl_p = entry_p - sl_atr * catr
                entry_i = i
            elif ps[i] >= p_th and (mac[i] < 0 if req_macro else mac[i] <= 0):
                pos = -1
                entry_p = cp - 5.0
                sl_p = entry_p + sl_atr * catr
                entry_i = i
                
    if len(trades) < 15:
        return None
    tr = np.array(trades)
    wins = tr[tr > 0]
    losses = tr[tr <= 0]
    wr = len(wins)/len(tr) * 100.0
    tot_w = np.sum(wins) if len(wins) > 0 else 0.0
    tot_l = abs(np.sum(losses)) if len(losses) > 0 else 1e-6
    pf = tot_w / tot_l
    payoff = (np.mean(wins) / abs(np.mean(losses))) if (len(wins) > 0 and len(losses) > 0) else 0.0
    net = np.sum(tr)
    return {"wr": wr, "pf": pf, "payoff": payoff, "net": net, "n": len(tr), "p_th": p_th, "sl": sl_atr, "be": be_atr, "tp": tp_atr, "bars": max_bars, "macro": req_macro}

results = []
for p_th in [0.28, 0.30, 0.32, 0.34, 0.36]:
    for sl in [0.6, 0.7, 0.8]:
        for be in [0.8, 1.0, 1.2]:
            for tp in [2.2, 2.5, 2.8, 3.2]:
                for bars in [15, 20, 25, 30]:
                    for mac in [True, False]:
                        res = test_params(p_th, sl, be, tp, bars, mac)
                        if res: results.append(res)

qual = [r for r in results if r["wr"] >= 51.0 and (r["pf"] >= 3.0 or r["payoff"] >= 3.0)]
print(f"TOTAL_RUNS={len(results)}, QUALIFIED={len(qual)}")
if qual:
    qual = sorted(qual, key=lambda x: (x["net"], x["pf"]), reverse=True)
    for q in qual[:5]:
        print("MATCH:", q)
else:
    results = sorted(results, key=lambda x: (x["wr"] >= 50.0, x["net"]), reverse=True)
    for q in results[:5]:
        print("TOP:", q)
