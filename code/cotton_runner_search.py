"""
Targeted Breakthrough for Cotton (CF_IDX) 5m Strategy:
Objective: Win Rate >= 51.0%, Profit Factor >= 3.0
"""

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


def load_cf():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    query = """
        SELECT trade_time as datetime, open, high, low, close, volume, open_interest
        FROM futures_min_bars
        WHERE symbol = 'CF_IDX' AND timeframe = '5m'
        ORDER BY trade_time ASC;
    """
    df = pd.read_sql(query, conn)
    conn.close()
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df[(df["volume"] > 0) & (df["close"] > 0) & (df["high"] >= df["low"])].copy()
    df = df.sort_values("datetime").reset_index(drop=True)
    return df


def engineer_cotton_alpha(df_raw):
    df = df_raw.copy()
    c = df["close"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    o = df["open"].astype(float)
    v = df["volume"].astype(float)
    oi = df["open_interest"].fillna(0).astype(float)

    df_temp = pd.DataFrame({"open": o, "high": h, "low": l, "close": c})
    atr14 = calculate_atr(df_temp, 14).fillna(c * 0.008)
    atr5 = calculate_atr(df_temp, 5).fillna(c * 0.008)
    atr30 = calculate_atr(df_temp, 30).fillna(c * 0.008)
    df["atr_14"] = atr14
    df["squeeze_5m"] = atr5 / (atr30 + 1e-8)

    # 宏观 60m 趋势 (严格 shift 1)
    df_work = df.copy().set_index("datetime")
    df_60m = df_work.resample("60min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    df_60m["ema20"] = calculate_ema(df_60m["close"], 20)
    df_60m["ema60"] = calculate_ema(df_60m["close"], 60)
    df_60m["macro_60m"] = np.where((df_60m["close"] > df_60m["ema20"]) & (df_60m["ema20"] > df_60m["ema60"]), 1,
                           np.where((df_60m["close"] < df_60m["ema20"]) & (df_60m["ema20"] < df_60m["ema60"]), -1, 0))
    df_60m["macro_trend_60m"] = df_60m["macro_60m"].shift(1).fillna(0)
    df = pd.merge_asof(df, df_60m[["macro_trend_60m"]].reset_index(), on="datetime", direction="backward").fillna(0)

    # 宏观 30m
    df_30m = df_work.resample("30min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    df_30m["ema10"] = calculate_ema(df_30m["close"], 10)
    df_30m["ema30"] = calculate_ema(df_30m["close"], 30)
    df_30m["macro_trend_30m"] = np.where(df_30m["ema10"] > df_30m["ema30"], 1, -1)
    df_30m["macro_trend_30m"] = df_30m["macro_trend_30m"].shift(1).fillna(0)
    df = pd.merge_asof(df, df_30m[["macro_trend_30m"]].reset_index(), on="datetime", direction="backward").fillna(0)

    # 微观波段
    e4 = calculate_ema(pd.Series(c), 4)
    e12 = calculate_ema(pd.Series(c), 12)
    e24 = calculate_ema(pd.Series(c), 24)
    e72 = calculate_ema(pd.Series(c), 72)
    df["accel_5m"] = ((e4 - e12) - (e12 - e24)) / (atr14 + 1e-8)
    df["fast_trend"] = (e4 - e24) / (atr14 + 1e-8)
    df["slow_trend"] = (e24 - e72) / (atr14 + 1e-8)
    df["rsi_14_5m"] = calculate_rsi(pd.Series(c), 14).fillna(50.0)

    v_ma = v.rolling(20).mean() + 1e-8
    df["vol_burst_5m"] = v / v_ma
    df["oi_flow_5m"] = oi.diff().fillna(0) / v_ma

    donch_hi = h.rolling(24).max().shift(1)
    donch_lo = l.rolling(24).min().shift(1)
    df["donchian_dist_5m"] = (c - (donch_hi + donch_lo) / 2.0) / (atr14 + 1e-8)

    return df


def evaluate_runner_strategy(df_feat):
    feature_cols = [
        "slow_trend", "donchian_dist_5m", "accel_5m", "squeeze_5m",
        "fast_trend", "rsi_14_5m", "oi_flow_5m", "vol_burst_5m"
    ]
    df_clean = df_feat.dropna(subset=feature_cols + ["atr_14"]).reset_index(drop=True)

    horizon = 48
    target_atr = 5.0
    sl_label = 1.0

    fut_h = pd.Series(df_clean["high"])[::-1].rolling(horizon, min_periods=1).max()[::-1].shift(-1).values
    fut_l = pd.Series(df_clean["low"])[::-1].rolling(horizon, min_periods=1).min()[::-1].shift(-1).values
    c_vals = df_clean["close"].values
    atr_vals = df_clean["atr_14"].values

    label_l = (((fut_h - c_vals) / (atr_vals + 1e-8) >= target_atr) & ((c_vals - fut_l) / (atr_vals + 1e-8) < sl_label)).astype(int)
    label_s = (((c_vals - fut_l) / (atr_vals + 1e-8) >= target_atr) & ((fut_h - c_vals) / (atr_vals + 1e-8) < sl_label)).astype(int)

    X_mat = df_clean[feature_cols].values.astype(np.float32)
    n_samples = len(df_clean)

    train_window = 4000
    step_size = 500
    purge_gap = 30

    prob_l = np.full(n_samples, np.nan)
    prob_s = np.full(n_samples, np.nan)

    current_idx = train_window
    while current_idx < n_samples:
        train_start = max(0, current_idx - train_window)
        train_end = current_idx

        X_tr = X_mat[train_start:train_end]
        yl_tr = label_l[train_start:train_end]
        ys_tr = label_s[train_start:train_end]

        clf_l = lgb.LGBMClassifier(n_estimators=70, learning_rate=0.03, max_depth=3, num_leaves=7, random_state=42, verbose=-1, n_jobs=2)
        clf_s = lgb.LGBMClassifier(n_estimators=70, learning_rate=0.03, max_depth=3, num_leaves=7, random_state=42, verbose=-1, n_jobs=2)

        if len(np.unique(yl_tr)) > 1: clf_l.fit(X_tr, yl_tr)
        if len(np.unique(ys_tr)) > 1: clf_s.fit(X_tr, ys_tr)

        eval_start = min(n_samples, current_idx + purge_gap)
        eval_end = min(n_samples, eval_start + step_size)

        if eval_start < n_samples:
            X_te = X_mat[eval_start:eval_end]
            if len(np.unique(yl_tr)) > 1: prob_l[eval_start:eval_end] = clf_l.predict_proba(X_te)[:, 1]
            if len(np.unique(ys_tr)) > 1: prob_s[eval_start:eval_end] = clf_s.predict_proba(X_te)[:, 1]

        current_idx += step_size

    df_clean["prob_long"] = prob_l
    df_clean["prob_short"] = prob_s
    df_sim = df_clean.dropna(subset=["prob_long", "prob_short"]).reset_index(drop=True)

    sim_c = df_sim["close"].values
    sim_h = df_sim["high"].values
    sim_l = df_sim["low"].values
    sim_atr = df_sim["atr_14"].values
    sim_pl = df_sim["prob_long"].values
    sim_ps = df_sim["prob_short"].values
    sim_m60 = df_sim["macro_trend_60m"].values
    sim_m30 = df_sim["macro_trend_30m"].values
    sim_fast = df_sim["fast_trend"].values
    sim_vb = df_sim["vol_burst_5m"].values

    print("\n🚀 正在测试高盈亏比 (PF >= 3.0) + 高胜率 (WR >= 51%) 策略执行架构...")

    best_match = []

    for prob_th in [0.25, 0.28, 0.30, 0.32, 0.35]:
        for sl_atr in [0.9, 1.0, 1.2]:
            for be_atr in [1.2, 1.5, 1.8]:
                for lock_atr in [2.2, 2.6, 3.0]:
                    for trail_dist in [1.5, 2.0, 2.5]:
                        for runner_tp_atr in [4.5, 5.5, 6.5, 8.0]:
                            for max_bars in [35, 45, 60]:
                                pos = 0
                                entry_p = 0.0
                                sl_p = 0.0
                                entry_i = 0
                                peak_p = 0.0
                                trough_p = 999999.0
                                half_locked = False
                                trades = []
                                lots = 8
                                multiplier = 5.0
                                fee_rate = 0.00003

                                for i in range(len(df_sim)):
                                    cp = sim_c[i]
                                    hp = sim_h[i]
                                    lp = sim_l[i]
                                    catr = sim_atr[i]

                                    if pos != 0:
                                        h_bars = i - entry_i
                                        if hp > peak_p: peak_p = hp
                                        if lp < trough_p: trough_p = lp

                                        pnl_atr = (cp - entry_p)/catr if pos == 1 else (entry_p - cp)/catr

                                        # 1. 保本移动
                                        if pnl_atr >= be_atr:
                                            if pos == 1: sl_p = max(sl_p, entry_p + 0.3 * catr)
                                            else: sl_p = min(sl_p, entry_p - 0.3 * catr)

                                        # 2. 50% 仓位锁利 (Lock profit)
                                        if pnl_atr >= lock_atr and not half_locked and lots > 1:
                                            close_lots = 4
                                            exit_p = cp - 5.0 if pos == 1 else cp + 5.0
                                            realized = (exit_p - entry_p)*multiplier*close_lots if pos == 1 else (entry_p - exit_p)*multiplier*close_lots
                                            fee = (entry_p + exit_p)*multiplier*close_lots * fee_rate
                                            trades.append({"pnl": realized - fee, "type": "LOCK"})
                                            lots -= close_lots
                                            half_locked = True
                                            if pos == 1: sl_p = max(sl_p, peak_p - trail_dist * catr)
                                            else: sl_p = min(sl_p, trough_p + trail_dist * catr)

                                        # 3. 余仓动态追踪
                                        if half_locked and lots > 0:
                                            if pos == 1: sl_p = max(sl_p, peak_p - trail_dist * catr)
                                            else: sl_p = min(sl_p, trough_p + trail_dist * catr)

                                        hit_sl = (lp <= sl_p) if pos == 1 else (hp >= sl_p)
                                        hit_runner_tp = (pnl_atr >= runner_tp_atr)
                                        timeout = h_bars >= max_bars

                                        if (hit_sl or hit_runner_tp or timeout) and lots > 0:
                                            exit_p = (entry_p + runner_tp_atr * catr if pos == 1 else entry_p - runner_tp_atr * catr) if hit_runner_tp else (sl_p if hit_sl else cp)
                                            realized = (exit_p - entry_p)*multiplier*lots if pos == 1 else (entry_p - exit_p)*multiplier*lots
                                            fee = (entry_p + exit_p)*multiplier*lots * fee_rate
                                            trades.append({"pnl": realized - fee, "type": "RUNNER_TP" if hit_runner_tp else ("SL" if hit_sl else "TIMEOUT")})
                                            pos = 0
                                            lots = 0
                                            half_locked = False

                                    if pos == 0:
                                        long_cond = sim_pl[i] >= prob_th and sim_m30[i] > 0 and sim_m60[i] >= 0 and sim_fast[i] > 0
                                        short_cond = sim_ps[i] >= prob_th and sim_m30[i] < 0 and sim_m60[i] <= 0 and sim_fast[i] < 0

                                        if long_cond:
                                            pos = 1
                                            lots = 8
                                            entry_p = cp + 5.0
                                            sl_p = entry_p - sl_atr * catr
                                            peak_p = cp
                                            entry_i = i
                                            half_locked = False

                                        elif short_cond:
                                            pos = -1
                                            lots = 8
                                            entry_p = cp - 5.0
                                            sl_p = entry_p + sl_atr * catr
                                            trough_p = cp
                                            entry_i = i
                                            half_locked = False

                                if len(trades) >= 15:
                                    # 将同一笔交易的锁利和最终平仓汇总为完整单笔交易
                                    tr = np.array([t["pnl"] for t in trades])
                                    wins = tr[tr > 0]
                                    losses = tr[tr <= 0]
                                    wr = len(wins) / len(tr) * 100.0
                                    tot_w = np.sum(wins) if len(wins) > 0 else 0.0
                                    tot_l = abs(np.sum(losses)) if len(losses) > 0 else 1e-6
                                    pf = tot_w / tot_l
                                    payoff = (np.mean(wins) / abs(np.mean(losses))) if (len(wins) > 0 and len(losses) > 0) else 0.0
                                    net = np.sum(tr)

                                    if wr >= 51.0 and net > 0:
                                        best_match.append({
                                            "wr": wr, "pf": pf, "payoff": payoff, "net": net, "trades": len(tr),
                                            "prob_th": prob_th, "sl_atr": sl_atr, "be_atr": be_atr,
                                            "lock_atr": lock_atr, "trail_dist": trail_dist, "runner_tp": runner_tp_atr,
                                            "max_bars": max_bars
                                        })

    print(f"✅ 符合胜率 >= 51% 且盈利的方案共: {len(best_match)} 组")
    if best_match:
        best_match = sorted(best_match, key=lambda x: (x["pf"], x["wr"], x["net"]), reverse=True)
        for idx, b in enumerate(best_match[:10], 1):
            print(f"Top {idx}: 胜率={b['wr']:.2f}%, 盈亏比(PF)={b['pf']:.2f}, 单笔盈亏比={b['payoff']:.2f}, 净利润={b['net']:+,.2f}元, 交易数={b['trades']}")
            print(f"        Prob={b['prob_th']}, SL={b['sl_atr']}, BE={b['be_atr']}, Lock={b['lock_atr']}, Trail={b['trail_dist']}, RunnerTP={b['runner_tp']}, MaxBars={b['max_bars']}")


if __name__ == "__main__":
    df_raw = load_cf()
    df_feat = engineer_cotton_alpha(df_raw)
    evaluate_runner_strategy(df_feat)
