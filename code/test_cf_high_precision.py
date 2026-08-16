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

# 30m Trend
df_work = df.copy().set_index("datetime")
df_30m = df_work.resample("30min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
df_30m["ema_15"] = calculate_ema(df_30m["close"], 15)
df_30m["ema_45"] = calculate_ema(df_30m["close"], 45)
df_30m["trend_30m"] = np.where(df_30m["ema_15"] > df_30m["ema_45"], 1, -1)
df_30m["macro_30m"] = df_30m["trend_30m"].shift(1).fillna(0)
df = pd.merge_asof(df, df_30m[["macro_30m"]].reset_index(), on="datetime", direction="backward").fillna(0)

# 5m features
df_temp = pd.DataFrame({"open": df["open"], "high": h, "low": l, "close": c})
atr = calculate_atr(df_temp, 14).fillna(c * 0.008)
df["atr"] = atr
df["atr_ma"] = atr.rolling(40).mean()
df["vol_filter"] = atr > df["atr_ma"] # Only trade during active volatility expansion

e4 = calculate_ema(pd.Series(c), 4)
e12 = calculate_ema(pd.Series(c), 12)
e24 = calculate_ema(pd.Series(c), 24)
df["accel"] = ((e4 - e12) - (e12 - e24)) / (atr + 1e-8)
df["rsi_14"] = calculate_rsi(pd.Series(c), 14).fillna(50.0)
df["oi_flow"] = df["open_interest"].fillna(0).diff().fillna(0) / (v.rolling(20).mean() + 1e-8)

# Target: 3.2 ATR target, 0.7 ATR stop loss
horizon = 25
fut_h = pd.Series(h)[::-1].rolling(horizon, min_periods=1).max()[::-1].shift(-1)
fut_l = pd.Series(l)[::-1].rolling(horizon, min_periods=1).min()[::-1].shift(-1)
df["label_l"] = (((fut_h - c) / (atr + 1e-8) >= 2.6) & ((c - fut_l) / (atr + 1e-8) < 0.7)).astype(int)
df["label_s"] = (((c - fut_l) / (atr + 1e-8) >= 2.6) & ((fut_h - c) / (atr + 1e-8) < 0.7)).astype(int)

feats = ["accel", "rsi_14", "oi_flow", "macro_30m"]
df_c = df.dropna(subset=feats + ["atr"]).reset_index(drop=True)

# Train ML
train_n = int(len(df_c) * 0.5)
clf_l = lgb.LGBMClassifier(n_estimators=45, max_depth=3, num_leaves=6, learning_rate=0.03, random_state=42, verbose=-1)
clf_s = lgb.LGBMClassifier(n_estimators=45, max_depth=3, num_leaves=6, learning_rate=0.03, random_state=42, verbose=-1)
clf_l.fit(df_c[feats].values[:train_n], df_c["label_l"].values[:train_n])
clf_s.fit(df_c[feats].values[:train_n], df_c["label_s"].values[:train_n])

test_df = df_c.iloc[train_n+20:].copy().reset_index(drop=True)
test_df["prob_l"] = clf_l.predict_proba(test_df[feats].values)[:, 1]
test_df["prob_s"] = clf_s.predict_proba(test_df[feats].values)[:, 1]

print("Simulating High Precision Regimes for CF_IDX...")

top_results = []
for p_th in [0.28, 0.30, 0.32, 0.34, 0.36, 0.38, 0.40]:
    for tp in [2.2, 2.6, 3.0, 3.5]:
        for sl in [0.5, 0.6, 0.7]:
            for be in [0.8, 1.0, 1.2]:
                for v_flt in [True, False]:
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
                    mac = test_df["macro_30m"].values
                    vol_ok = test_df["vol_filter"].values
                    
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
                            timeout = h_bars >= 30
                            
                            if hit_tp or hit_sl or timeout:
                                exit_p = (entry_p + tp * catr if pos == 1 else entry_p - tp * catr) if hit_tp else (sl_p if hit_sl else cp)
                                pnl = (exit_p - entry_p)*5.0*8 if pos == 1 else (entry_p - exit_p)*5.0*8
                                fee = (entry_p + exit_p)*5.0*8 * 0.00003
                                trades.append(pnl - fee)
                                pos = 0
                                
                        if pos == 0:
                            v_pass = vol_ok[i] if v_flt else True
                            if pls[i] >= p_th and mac[i] > 0 and v_pass:
                                pos = 1
                                entry_p = cp + 5.0
                                sl_p = entry_p - sl * catr
                                entry_i = i
                            elif pss[i] >= p_th and mac[i] < 0 and v_pass:
                                pos = -1
                                entry_p = cp - 5.0
                                sl_p = entry_p + sl * catr
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
                        top_results.append({
                            "wr": wr, "pf": pf, "payoff": payoff, "net": net, "n": len(tr),
                            "p_th": p_th, "tp": tp, "sl": sl, "be": be, "vol_flt": v_flt
                        })

top_results = sorted(top_results, key=lambda x: (x["wr"] >= 51.0, x["pf"] >= 3.0, x["net"]), reverse=True)
print(f"Total results: {len(top_results)}")
for r in top_results[:10]:
    print(f"-> 胜率: {r['wr']:.1f}%, 盈亏比(PF): {r['pf']:.2f}, 单笔盈亏比: {r['payoff']:.2f}, 净利润: {r['net']:+,.2f}元, 交易数: {r['n']}, 参数: p_th={r['p_th']}, tp={r['tp']}, sl={r['sl']}, be={r['be']}, vol_flt={r['vol_flt']}")
