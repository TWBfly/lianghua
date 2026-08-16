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
o = df["open"].astype(float)
v = df["volume"].astype(float)

df_temp = pd.DataFrame({"open": o, "high": h, "low": l, "close": c})
atr = calculate_atr(df_temp, 14).fillna(c * 0.008)
df["atr"] = atr

# EMAs
df["ema_5"] = calculate_ema(pd.Series(c), 5)
df["ema_20"] = calculate_ema(pd.Series(c), 20)
df["ema_60"] = calculate_ema(pd.Series(c), 60)
df["dist_ema_5"] = (c - df["ema_5"]) / (atr + 1e-8)
df["dist_ema_20"] = (c - df["ema_20"]) / (atr + 1e-8)
df["dist_ema_60"] = (c - df["ema_60"]) / (atr + 1e-8)
df["rsi_14"] = calculate_rsi(pd.Series(c), 14).fillna(50.0)
df["vol_burst"] = v / (v.rolling(20).mean() + 1e-8)

feature_cols = ["dist_ema_5", "dist_ema_20", "dist_ema_60", "rsi_14", "vol_burst"]
df_clean = df.dropna(subset=feature_cols + ["atr"]).copy().reset_index(drop=True)
X = df_clean[feature_cols].values

all_records = []
for horizon in [15, 30]:
    for target_r in [1.5, 2.0, 2.5]:
        for sl_r in [0.6, 0.8]:
            fut_h = pd.Series(h)[::-1].rolling(horizon, min_periods=1).max()[::-1].shift(-1)
            fut_l = pd.Series(l)[::-1].rolling(horizon, min_periods=1).min()[::-1].shift(-1)
            
            y_l = (((fut_h - c) / (atr + 1e-8) >= target_r) & ((c - fut_l) / (atr + 1e-8) < sl_r)).astype(int).values
            y_s = (((c - fut_l) / (atr + 1e-8) >= target_r) & ((fut_h - c) / (atr + 1e-8) < sl_r)).astype(int).values
            
            train_n = int(len(df_clean) * 0.5)
            clf_l = lgb.LGBMClassifier(n_estimators=30, max_depth=2, num_leaves=4, learning_rate=0.03, random_state=42, verbose=-1)
            clf_s = lgb.LGBMClassifier(n_estimators=30, max_depth=2, num_leaves=4, learning_rate=0.03, random_state=42, verbose=-1)
            
            clf_l.fit(X[:train_n], y_l[:train_n])
            clf_s.fit(X[:train_n], y_s[:train_n])
            
            test_X = X[train_n+20:]
            test_df = df_clean.iloc[train_n+20:].copy().reset_index(drop=True)
            test_df["prob_l"] = clf_l.predict_proba(test_X)[:, 1]
            test_df["prob_s"] = clf_s.predict_proba(test_X)[:, 1]
            
            for p_th in [0.20, 0.25, 0.30]:
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
                    all_records.append({
                        "wr": wr, "pf": pf, "payoff": payoff, "net": net, "n": len(tr),
                        "horizon": horizon, "tp": target_r, "sl": sl_r, "p_th": p_th
                    })

all_records = sorted(all_records, key=lambda x: x["net"], reverse=True)
print(f"Total combinations evaluated: {len(all_records)}")
for r in all_records[:8]:
    print(f"H={r['horizon']}, TP={r['tp']}, SL={r['sl']}, P_TH={r['p_th']} -> 胜率: {r['wr']:.1f}%, 盈亏比(PF): {r['pf']:.2f}, 单笔盈亏比: {r['payoff']:.2f}, 净利润: {r['net']:+,.2f}元, 交易数: {r['n']}")
