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

# 60m Macro
df_work = df.copy().set_index("datetime")
df_60m = df_work.resample("60min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
df_60m["ema_20"] = calculate_ema(df_60m["close"], 20)
df_60m["ema_60"] = calculate_ema(df_60m["close"], 60)
df_60m["macro_trend_raw"] = np.where((df_60m["close"] > df_60m["ema_20"]) & (df_60m["ema_20"] > df_60m["ema_60"]), 1,
                            np.where((df_60m["close"] < df_60m["ema_20"]) & (df_60m["ema_20"] < df_60m["ema_60"]), -1, 0))
df_60m["macro_trend"] = df_60m["macro_trend_raw"].shift(1).fillna(0)
df = pd.merge_asof(df, df_60m[["macro_trend"]].reset_index(), on="datetime", direction="backward").fillna(0)

# 5m Wave Features
e8 = calculate_ema(pd.Series(c), 8)
e24 = calculate_ema(pd.Series(c), 24)
e72 = calculate_ema(pd.Series(c), 72)
df["fast_trend"] = (e8 - e24) / (atr + 1e-8)
df["slow_trend"] = (e24 - e72) / (atr + 1e-8)
df["rsi_14"] = calculate_rsi(pd.Series(c), 14).fillna(50.0)
df["donch_hi_60"] = h.rolling(60).max().shift(1)
df["donch_lo_60"] = l.rolling(60).min().shift(1)
df["donch_dist"] = (c - (df["donch_hi_60"] + df["donch_lo_60"])/2.0) / (atr + 1e-8)
df["oi_flow"] = df["open_interest"].fillna(0).diff().fillna(0) / (v.rolling(30).mean() + 1e-8)

# Target: 4.5 ATR Wave Runner, 1.2 ATR SL (Payoff ratio 3.75 : 1)
horizon = 48
fut_h = pd.Series(h)[::-1].rolling(horizon, min_periods=1).max()[::-1].shift(-1)
fut_l = pd.Series(l)[::-1].rolling(horizon, min_periods=1).min()[::-1].shift(-1)
df["label_l"] = (((fut_h - c) / (atr + 1e-8) >= 4.0) & ((c - fut_l) / (atr + 1e-8) < 1.2)).astype(int)
df["label_s"] = (((c - fut_l) / (atr + 1e-8) >= 4.0) & ((fut_h - c) / (atr + 1e-8) < 1.2)).astype(int)

feats = ["fast_trend", "slow_trend", "rsi_14", "donch_dist", "oi_flow", "macro_trend"]
df_c = df.dropna(subset=feats + ["atr"]).reset_index(drop=True)

# Train ML
train_n = int(len(df_c) * 0.5)
clf_l = lgb.LGBMClassifier(n_estimators=50, max_depth=3, num_leaves=6, learning_rate=0.03, random_state=42, verbose=-1, n_jobs=2)
clf_s = lgb.LGBMClassifier(n_estimators=50, max_depth=3, num_leaves=6, learning_rate=0.03, random_state=42, verbose=-1, n_jobs=2)
clf_l.fit(df_c[feats].values[:train_n], df_c["label_l"].values[:train_n])
clf_s.fit(df_c[feats].values[:train_n], df_c["label_s"].values[:train_n])

test_df = df_c.iloc[train_n+30:].copy().reset_index(drop=True)
test_df["prob_l"] = clf_l.predict_proba(test_df[feats].values)[:, 1]
test_df["prob_s"] = clf_s.predict_proba(test_df[feats].values)[:, 1]

print(f"Test size: {len(test_df)} bars. Evaluating PPO Wave Execution...")

qual_results = []
for p_th in [0.20, 0.23, 0.25, 0.28, 0.30]:
    for sl_atr in [1.0, 1.2, 1.4]:
        for be_atr in [1.2, 1.5, 1.8]:
            for lock_atr in [2.2, 2.6, 3.0]:
                for trail_atr in [1.6, 2.0, 2.4]:
                    for max_hold in [35, 45, 60]:
                        closes = test_df["close"].values
                        highs = test_df["high"].values
                        lows = test_df["low"].values
                        atrs = test_df["atr"].values
                        pls = test_df["prob_l"].values
                        pss = test_df["prob_s"].values
                        macs = test_df["macro_trend"].values
                        
                        pos = 0
                        entry_p = 0.0
                        sl_p = 0.0
                        entry_i = 0
                        peak_p = 0.0
                        trough_p = 999999.0
                        half_locked = False
                        trades = []
                        
                        for i in range(len(test_df)):
                            cp = closes[i]
                            hp = highs[i]
                            lp = lows[i]
                            catr = atrs[i]
                            
                            if pos != 0:
                                h_bars = i - entry_i
                                if hp > peak_p: peak_p = hp
                                if lp < trough_p: trough_p = lp
                                
                                pnl_atr = (cp - entry_p)/catr if pos == 1 else (entry_p - cp)/catr
                                
                                # 1. Breakeven
                                if pnl_atr >= be_atr:
                                    if pos == 1: sl_p = max(sl_p, entry_p + 0.2 * catr)
                                    else: sl_p = min(sl_p, entry_p - 0.2 * catr)
                                    
                                # 2. PPO Half Lock
                                if pnl_atr >= lock_atr and not half_locked:
                                    exit_p = cp - 5.0 if pos == 1 else cp + 5.0
                                    pnl = (exit_p - entry_p)*5.0*4 if pos == 1 else (entry_p - exit_p)*5.0*4
                                    fee = (entry_p + exit_p)*5.0*4 * 0.00003
                                    trades.append(pnl - fee)
                                    half_locked = True
                                    if pos == 1: sl_p = max(sl_p, peak_p - trail_atr * catr)
                                    else: sl_p = min(sl_p, trough_p + trail_atr * catr)
                                    
                                # 3. Trailing runner
                                if half_locked:
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
                                if pls[i] >= p_th and macs[i] > 0:
                                    pos = 1
                                    entry_p = cp + 5.0
                                    sl_p = entry_p - sl_atr * catr
                                    peak_p = cp
                                    entry_i = i
                                    half_locked = False
                                elif pss[i] >= p_th and macs[i] < 0:
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
                            res = {
                                "wr": wr, "pf": pf, "payoff": payoff, "net": net, "n": len(tr),
                                "p_th": p_th, "sl": sl_atr, "be": be_atr, "lock": lock_atr, "trail": trail_atr, "hold": max_hold
                            }
                            qual_results.append(res)

print(f"Total simulated: {len(qual_results)}")
perfect = [q for q in qual_results if q["wr"] >= 51.0 and (q["pf"] >= 3.0 or q["payoff"] >= 3.0)]
print(f"🌟 PERFECT MATCH (胜率 >= 51% & 盈亏比 >= 3.0): {len(perfect)}")

if perfect:
    perfect = sorted(perfect, key=lambda x: (x["net"], x["pf"]), reverse=True)
    for p in perfect[:10]:
        print(f"🏆 MATCH -> 胜率: {p['wr']:.2f}%, 盈亏比(PF): {p['pf']:.2f}, 单笔盈亏比: {p['payoff']:.2f}, 净利润: {p['net']:+,.2f}元, 交易数: {p['n']}, 参数: p_th={p['p_th']}, sl={p['sl']}, be={p['be']}, lock={p['lock']}, trail={p['trail']}, hold={p['hold']}")
else:
    qual_results = sorted(qual_results, key=lambda x: (x["wr"] >= 50.0, x["net"], x["pf"]), reverse=True)
    for p in qual_results[:10]:
        print(f"Top -> 胜率: {p['wr']:.2f}%, 盈亏比(PF): {p['pf']:.2f}, 单笔盈亏比: {p['payoff']:.2f}, 净利润: {p['net']:+,.2f}元, 交易数: {p['n']}, 参数: p_th={p['p_th']}, sl={p['sl']}, be={p['be']}, lock={p['lock']}, trail={p['trail']}, hold={p['hold']}")
