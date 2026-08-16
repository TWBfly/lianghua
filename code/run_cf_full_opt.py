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

# 30m Macro
df_work = df.copy().set_index("datetime")
df_30m = df_work.resample("30min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
df_30m["ema_10"] = calculate_ema(df_30m["close"], 10)
df_30m["ema_30"] = calculate_ema(df_30m["close"], 30)
df_30m["macro"] = np.where(df_30m["ema_10"] > df_30m["ema_30"], 1, -1)
df_30m["macro_30m"] = df_30m["macro"].shift(1).fillna(0)
df = pd.merge_asof(df, df_30m[["macro_30m"]].reset_index(), on="datetime", direction="backward").fillna(0)

# Feature engineering
e4 = calculate_ema(pd.Series(c), 4)
e12 = calculate_ema(pd.Series(c), 12)
e24 = calculate_ema(pd.Series(c), 24)
df["accel"] = ((e4 - e12) - (e12 - e24)) / (atr + 1e-8)
df["trend_strength"] = (e4 - e24) / (atr + 1e-8)
df["squeeze"] = calculate_atr(df_temp, 5).fillna(c * 0.008) / (calculate_atr(df_temp, 20).fillna(c * 0.008) + 1e-8)
df["rsi"] = calculate_rsi(pd.Series(c), 14).fillna(50.0)
df["vol_burst"] = v / (v.rolling(20).mean() + 1e-8)
df["oi_flow"] = df["open_interest"].fillna(0).diff().fillna(0) / (v.rolling(20).mean() + 1e-8)

# Triple barrier labeling
fut_h = pd.Series(h)[::-1].rolling(20, min_periods=1).max()[::-1].shift(-1)
fut_l = pd.Series(l)[::-1].rolling(20, min_periods=1).min()[::-1].shift(-1)
df["label_l"] = (((fut_h - c) / (atr + 1e-8) >= 2.2) & ((c - fut_l) / (atr + 1e-8) < 0.7)).astype(int)
df["label_s"] = (((c - fut_l) / (atr + 1e-8) >= 2.2) & ((fut_h - c) / (atr + 1e-8) < 0.7)).astype(int)

feats = ["squeeze", "accel", "trend_strength", "rsi", "vol_burst", "oi_flow"]
df_c = df.dropna(subset=feats + ["atr"]).reset_index(drop=True)

# Walk Forward Prediction across entire dataset
n_samples = len(df_c)
X_mat = df_c[feats].values.astype(np.float32)
yl = df_c["label_l"].values
ys = df_c["label_s"].values

prob_long = np.full(n_samples, np.nan)
prob_short = np.full(n_samples, np.nan)

train_window = 3500
step_size = 500
current_idx = train_window

while current_idx < n_samples:
    train_start = max(0, current_idx - train_window)
    train_end = current_idx
    X_tr = X_mat[train_start:train_end]
    yl_tr = yl[train_start:train_end]
    ys_tr = ys[train_start:train_end]
    
    clf_l = lgb.LGBMClassifier(n_estimators=50, learning_rate=0.03, max_depth=3, num_leaves=6, random_state=42, verbose=-1, n_jobs=2)
    clf_s = lgb.LGBMClassifier(n_estimators=50, learning_rate=0.03, max_depth=3, num_leaves=6, random_state=42, verbose=-1, n_jobs=2)
    if len(np.unique(yl_tr)) > 1: clf_l.fit(X_tr, yl_tr)
    if len(np.unique(ys_tr)) > 1: clf_s.fit(X_tr, ys_tr)
    
    eval_start = min(n_samples, current_idx + 25)
    eval_end = min(n_samples, eval_start + step_size)
    if eval_start < n_samples:
        X_te = X_mat[eval_start:eval_end]
        if len(np.unique(yl_tr)) > 1: prob_long[eval_start:eval_end] = clf_l.predict_proba(X_te)[:, 1]
        if len(np.unique(ys_tr)) > 1: prob_short[eval_start:eval_end] = clf_s.predict_proba(X_te)[:, 1]
    current_idx += step_size

df_c["prob_long"] = prob_long
df_c["prob_short"] = prob_short
df_sim = df_c.dropna(subset=["prob_long", "prob_short"]).reset_index(drop=True)

print(f"Total Walk-Forward Bars for CF_IDX: {len(df_sim)}")

# Grid Search
records = []
for p_th in [0.24, 0.26, 0.28, 0.30, 0.32, 0.34]:
    for sl_atr in [0.5, 0.6, 0.7, 0.8]:
        for be_atr in [0.6, 0.8, 1.0, 1.2]:
            for trail_atr in [1.5, 2.0, 2.5]:
                for max_hold in [15, 20, 25, 30]:
                    closes = df_sim["close"].values
                    highs = df_sim["high"].values
                    lows = df_sim["low"].values
                    atrs = df_sim["atr"].values
                    pl = df_sim["prob_long"].values
                    ps = df_sim["prob_short"].values
                    mac = df_sim["macro_30m"].values
                    
                    pos = 0
                    entry_p = 0.0
                    sl_p = 0.0
                    entry_i = 0
                    peak_p = 0.0
                    trough_p = 999999.0
                    half_locked = False
                    trades = []
                    
                    for i in range(len(df_sim)):
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
                            
                            # Half lock at 1.8 ATR
                            if pnl_atr >= 1.8 and not half_locked:
                                exit_p = cp - 5.0 if pos == 1 else cp + 5.0
                                pnl = (exit_p - entry_p)*5.0*4 if pos == 1 else (entry_p - exit_p)*5.0*4
                                fee = (entry_p + exit_p)*5.0*4 * 0.00003
                                trades.append(pnl - fee)
                                half_locked = True
                                if pos == 1: sl_p = max(sl_p, peak_p - trail_atr * catr)
                                else: sl_p = min(sl_p, trough_p + trail_atr * catr)
                                
                            hit_sl = (lp <= sl_p) if pos == 1 else (hp >= sl_p)
                            timeout = h_bars >= max_hold
                            
                            if hit_sl or timeout:
                                exit_p = sl_p if hit_sl else cp
                                rem_lots = 4 if half_locked else 8
                                pnl = (exit_p - entry_p)*5.0*rem_lots if pos == 1 else (entry_p - exit_p)*5.0*rem_lots
                                fee = (entry_p + exit_p)*5.0*rem_lots * 0.00003
                                trades.append(pnl - fee)
                                pos = 0
                                half_locked = False
                                
                        if pos == 0:
                            if pl[i] >= p_th and mac[i] > 0:
                                pos = 1
                                entry_p = cp + 5.0
                                sl_p = entry_p - sl_atr * catr
                                peak_p = cp
                                entry_i = i
                                half_locked = False
                            elif ps[i] >= p_th and mac[i] < 0:
                                pos = -1
                                entry_p = cp - 5.0
                                sl_p = entry_p + sl_atr * catr
                                trough_p = cp
                                entry_i = i
                                half_locked = False
                                
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
                        records.append({
                            "wr": wr, "pf": pf, "payoff": payoff, "net": net, "n": len(tr),
                            "p_th": p_th, "sl": sl_atr, "be": be_atr, "trail": trail_atr, "hold": max_hold
                        })

print(f"Total simulated configurations: {len(records)}")
qual = [r for r in records if r["wr"] >= 51.0 and (r["pf"] >= 3.0 or r["payoff"] >= 3.0)]
print(f"🎯 达成目标 (胜率 >= 51% 且 盈亏比 >= 3.0) 的配置数: {len(qual)}")

if qual:
    qual = sorted(qual, key=lambda x: (x["net"], x["pf"]), reverse=True)
    for q in qual[:10]:
        print(f"🔥 QUALIFIED -> 胜率: {q['wr']:.2f}%, 盈亏比(PF): {q['pf']:.2f}, 单笔盈亏比: {q['payoff']:.2f}, 净利润: {q['net']:+,.2f}元, 交易数: {q['n']}, 参数: p_th={q['p_th']}, sl={q['sl']}, be={q['be']}, trail={q['trail']}, hold={q['hold']}")
else:
    records = sorted(records, key=lambda x: (x["wr"] >= 50.0, x["pf"] >= 2.5, x["net"]), reverse=True)
    for q in records[:10]:
        print(f"-> 胜率: {q['wr']:.2f}%, 盈亏比(PF): {q['pf']:.2f}, 单笔盈亏比: {q['payoff']:.2f}, 净利润: {q['net']:+,.2f}元, 交易数: {q['n']}, 参数: p_th={q['p_th']}, sl={q['sl']}, be={q['be']}, trail={q['trail']}, hold={q['hold']}")
