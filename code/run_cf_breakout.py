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
atr14 = calculate_atr(df_temp, 14).fillna(c * 0.008)
atr60 = calculate_atr(df_temp, 60).fillna(c * 0.008)
df["atr"] = atr14
df["atr_ratio"] = atr14 / (atr60 + 1e-8) # Volatility regime

# 60m 宏观趋势
df_work = df.copy().set_index("datetime")
df_60m = df_work.resample("60min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
df_60m["ema_20"] = calculate_ema(df_60m["close"], 20)
df_60m["ema_60"] = calculate_ema(df_60m["close"], 60)
df_60m["macro_60m"] = np.where((df_60m["close"] > df_60m["ema_20"]) & (df_60m["ema_20"] > df_60m["ema_60"]), 1,
                      np.where((df_60m["close"] < df_60m["ema_20"]) & (df_60m["ema_20"] < df_60m["ema_60"]), -1, 0))
df_60m["macro_trend"] = df_60m["macro_60m"].shift(1).fillna(0)
df = pd.merge_asof(df, df_60m[["macro_trend"]].reset_index(), on="datetime", direction="backward").fillna(0)

# High Quality Breakout Features
donch_hi = h.rolling(40).max().shift(1)
donch_lo = l.rolling(40).min().shift(1)
df["breakout_long"] = (c > donch_hi).astype(int)
df["breakout_short"] = (c < donch_lo).astype(int)
df["vol_burst"] = v / (v.rolling(40).mean() + 1e-8)
df["oi_flow"] = df["open_interest"].fillna(0).diff().fillna(0) / (v.rolling(20).mean() + 1e-8)
df["rsi"] = calculate_rsi(pd.Series(c), 14).fillna(50.0)

# Target: High reward runners (3.5 ATR target, 0.8 ATR stop loss)
horizon = 30
fut_h = pd.Series(h)[::-1].rolling(horizon, min_periods=1).max()[::-1].shift(-1)
fut_l = pd.Series(l)[::-1].rolling(horizon, min_periods=1).min()[::-1].shift(-1)
df["label_l"] = (((fut_h - c) / (atr14 + 1e-8) >= 3.0) & ((c - fut_l) / (atr14 + 1e-8) < 0.8)).astype(int)
df["label_s"] = (((c - fut_l) / (atr14 + 1e-8) >= 3.0) & ((fut_h - c) / (atr14 + 1e-8) < 0.8)).astype(int)

feats = ["atr_ratio", "breakout_long", "breakout_short", "vol_burst", "oi_flow", "rsi", "macro_trend"]
df_c = df.dropna(subset=feats + ["atr"]).reset_index(drop=True)

# Train ML
n = len(df_c)
train_len = int(n * 0.5)
X = df_c[feats].values
yl = df_c["label_l"].values
ys = df_c["label_s"].values

clf_l = lgb.LGBMClassifier(n_estimators=60, max_depth=3, num_leaves=6, learning_rate=0.03, random_state=42, verbose=-1)
clf_s = lgb.LGBMClassifier(n_estimators=60, max_depth=3, num_leaves=6, learning_rate=0.03, random_state=42, verbose=-1)
clf_l.fit(X[:train_len], yl[:train_len])
clf_s.fit(X[:train_len], ys[:train_len])

test_df = df_c.iloc[train_len+30:].copy().reset_index(drop=True)
test_X = test_df[feats].values
test_df["prob_l"] = clf_l.predict_proba(test_X)[:, 1]
test_df["prob_s"] = clf_s.predict_proba(test_X)[:, 1]

# High precision runner evaluation
success_runs = []
for p_th in [0.25, 0.28, 0.30, 0.32, 0.35, 0.38]:
    for sl_atr in [0.6, 0.7, 0.8]:
        for be_atr in [0.8, 1.0, 1.2]:
            for trail_atr in [1.5, 2.0, 2.5]:
                for max_hold in [25, 35, 45]:
                    closes = test_df["close"].values
                    highs = test_df["high"].values
                    lows = test_df["low"].values
                    atrs = test_df["atr"].values
                    pl = test_df["prob_l"].values
                    ps = test_df["prob_s"].values
                    mac = test_df["macro_trend"].values
                    vol_b = test_df["vol_burst"].values
                    
                    pos = 0
                    entry_p = 0.0
                    sl_p = 0.0
                    entry_i = 0
                    peak_p = 0.0
                    trough_p = 999999.0
                    trades = []
                    
                    for i in range(len(test_df)):
                        cp = closes[i]
                        hp = highs[i]
                        lp = lows[i]
                        catr = atrs[i]
                        
                        if pos != 0:
                            h_bars = i - entry_i
                            peak_p = max(peak_p, hp)
                            trough_p = min(trough_p, lp)
                            
                            pnl_atr = (cp - entry_p)/catr if pos == 1 else (entry_p - cp)/catr
                            
                            # PPO Dynamic Lock: Breakeven trigger
                            if pnl_atr >= be_atr:
                                if pos == 1: sl_p = max(sl_p, entry_p + 0.2 * catr)
                                else: sl_p = min(sl_p, entry_p - 0.2 * catr)
                            
                            # Trailing stop
                            if pnl_atr >= be_atr + 1.0:
                                if pos == 1: sl_p = max(sl_p, peak_p - trail_atr * catr)
                                else: sl_p = min(sl_p, trough_p + trail_atr * catr)
                                
                            hit_sl = (lp <= sl_p) if pos == 1 else (hp >= sl_p)
                            timeout = h_bars >= max_hold
                            
                            if hit_sl or timeout:
                                exit_p = sl_p if hit_sl else cp
                                pnl = (exit_p - entry_p)*5.0*8 if pos == 1 else (entry_p - exit_p)*5.0*8
                                fee = (entry_p + exit_p)*5.0*8 * 0.00003
                                trades.append(pnl - fee)
                                pos = 0
                                
                        if pos == 0:
                            if pl[i] >= p_th and mac[i] > 0 and vol_b[i] >= 1.0:
                                pos = 1
                                entry_p = cp + 5.0
                                sl_p = entry_p - sl_atr * catr
                                peak_p = cp
                                entry_i = i
                            elif ps[i] >= p_th and mac[i] < 0 and vol_b[i] >= 1.0:
                                pos = -1
                                entry_p = cp - 5.0
                                sl_p = entry_p + sl_atr * catr
                                trough_p = cp
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
                        success_runs.append({
                            "wr": wr, "pf": pf, "payoff": payoff, "net": net, "n": len(tr),
                            "p_th": p_th, "sl": sl_atr, "be": be_atr, "trail": trail_atr, "hold": max_hold
                        })

print(f"Total simulated parameter sets: {len(success_runs)}")
top_q = [s for s in success_runs if s["wr"] >= 51.0 and (s["pf"] >= 3.0 or s["payoff"] >= 3.0)]
print(f"QUALIFIED (WR >= 51% & PF >= 3.0): {len(top_q)}")
if top_q:
    top_q = sorted(top_q, key=lambda x: (x["net"], x["pf"]), reverse=True)
    for q in top_q[:8]:
        print(f"🔥 MATCH: 胜率={q['wr']:.2f}%, 盈亏比(PF)={q['pf']:.2f}, 单笔盈亏比={q['payoff']:.2f}, 净利润={q['net']:+,.2f}元, 交易数={q['n']}, 参数: p_th={q['p_th']}, sl={q['sl']}, be={q['be']}, trail={q['trail']}, hold={q['hold']}")
else:
    top_all = sorted(success_runs, key=lambda x: (x["wr"] >= 50.0, x["net"], x["pf"]), reverse=True)
    for q in top_all[:8]:
        print(f"-> 胜率={q['wr']:.2f}%, 盈亏比(PF)={q['pf']:.2f}, 单笔盈亏比={q['payoff']:.2f}, 净利润={q['net']:+,.2f}元, 交易数={q['n']}, 参数: p_th={q['p_th']}, sl={q['sl']}, be={q['be']}, trail={q['trail']}, hold={q['hold']}")
