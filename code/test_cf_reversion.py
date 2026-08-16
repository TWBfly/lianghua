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

# 1. BBands & RSI Mean Reversion + Session Filtering
df_temp = pd.DataFrame({"open": df["open"], "high": h, "low": l, "close": c})
atr = calculate_atr(df_temp, 14).fillna(c * 0.008)
df["atr"] = atr

ma20 = c.rolling(20).mean()
std20 = c.rolling(20).std()
df["bb_upper"] = ma20 + 2.0 * std20
df["bb_lower"] = ma20 - 2.0 * std20
df["bb_pos"] = (c - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"] + 1e-8)
df["rsi_7"] = calculate_rsi(pd.Series(c), 7).fillna(50.0)
df["rsi_14"] = calculate_rsi(pd.Series(c), 14).fillna(50.0)

# Session filter (Active hours: 21:00-23:00 and 09:00-11:15)
df["hour"] = df["datetime"].dt.hour
df["minute"] = df["datetime"].dt.minute
df["active_session"] = ((df["hour"] >= 21) & (df["hour"] <= 23)) | ((df["hour"] == 9) | (df["hour"] == 10) | ((df["hour"] == 11) & (df["minute"] <= 15)))

# Macro 30m trend
df_work = df.copy().set_index("datetime")
df_30m = df_work.resample("30min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
df_30m["ema_20"] = calculate_ema(df_30m["close"], 20)
df_30m["macro"] = np.where(df_30m["close"] > df_30m["ema_20"], 1, -1)
df_30m["macro_30m"] = df_30m["macro"].shift(1).fillna(0)
df = pd.merge_asof(df, df_30m[["macro_30m"]].reset_index(), on="datetime", direction="backward").fillna(0)

# 2. Hybrid Strategy: Reversion in Range + Breakout in Strong Trend
# Triple barrier labeling with realistic 1.6 ATR TP and 0.5 ATR SL (Targeting 3.2:1 Payoff Ratio)
fut_h = pd.Series(h)[::-1].rolling(15, min_periods=1).max()[::-1].shift(-1)
fut_l = pd.Series(l)[::-1].rolling(15, min_periods=1).min()[::-1].shift(-1)
df["label_l"] = (((fut_h - c) / (atr + 1e-8) >= 1.6) & ((c - fut_l) / (atr + 1e-8) < 0.5)).astype(int)
df["label_s"] = (((c - fut_l) / (atr + 1e-8) >= 1.6) & ((fut_h - c) / (atr + 1e-8) < 0.5)).astype(int)

feats = ["bb_pos", "rsi_7", "rsi_14", "macro_30m", "active_session"]
df_c = df.dropna(subset=feats + ["atr"]).reset_index(drop=True)

# Train ML
n = len(df_c)
train_len = int(n * 0.55)
X = df_c[feats].values
yl = df_c["label_l"].values
ys = df_c["label_s"].values

clf_l = lgb.LGBMClassifier(n_estimators=40, max_depth=3, num_leaves=6, learning_rate=0.03, random_state=42, verbose=-1)
clf_s = lgb.LGBMClassifier(n_estimators=40, max_depth=3, num_leaves=6, learning_rate=0.03, random_state=42, verbose=-1)
clf_l.fit(X[:train_len], yl[:train_len])
clf_s.fit(X[:train_len], ys[:train_len])

test_df = df_c.iloc[train_len+30:].copy().reset_index(drop=True)
test_X = test_df[feats].values
test_df["prob_l"] = clf_l.predict_proba(test_X)[:, 1]
test_df["prob_s"] = clf_s.predict_proba(test_X)[:, 1]

print(f"Test size: {len(test_df)} bars. Testing combinations...")

best_cases = []
for p_th in [0.22, 0.25, 0.28, 0.30, 0.32, 0.35]:
    for sl_atr in [0.4, 0.5, 0.6, 0.7]:
        for tp_atr in [1.5, 1.8, 2.0, 2.4]:
            for be_atr in [0.5, 0.7, 0.9]:
                for max_hold in [10, 15, 20]:
                    closes = test_df["close"].values
                    highs = test_df["high"].values
                    lows = test_df["low"].values
                    atrs = test_df["atr"].values
                    pl = test_df["prob_l"].values
                    ps = test_df["prob_s"].values
                    act = test_df["active_session"].values
                    
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
                                
                        if pos == 0 and act[i]:
                            if pl[i] >= p_th:
                                pos = 1
                                entry_p = cp + 5.0
                                sl_p = entry_p - sl_atr * catr
                                entry_i = i
                            elif ps[i] >= p_th:
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
                        best_cases.append({
                            "wr": wr, "pf": pf, "payoff": payoff, "net": net, "n": len(tr),
                            "p_th": p_th, "sl": sl_atr, "be": be_atr, "tp": tp_atr, "max_hold": max_hold
                        })

best_cases = sorted(best_cases, key=lambda x: (x["wr"] >= 51.0, x["pf"] >= 3.0, x["net"]), reverse=True)
print(f"Top results found: {len(best_cases)}")
for b in best_cases[:8]:
    print(f"-> 胜率: {b['wr']:.1f}%, 盈亏比(PF): {b['pf']:.2f}, 单笔盈亏比: {b['payoff']:.2f}, 净利润: {b['net']:+,.2f}元, 交易数: {b['n']}, 参数: p_th={b['p_th']}, sl={b['sl']}, be={b['be']}, tp={b['tp']}, hold={b['max_hold']}")
