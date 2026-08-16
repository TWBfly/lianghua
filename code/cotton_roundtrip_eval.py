"""
Comprehensive Optimization for Cotton (CF_IDX) 5m:
Evaluating round-trip performance, Win Rate >= 51%, and Profit Factor >= 3.0
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


def engineer_cotton_features(df_raw):
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
    atr20 = calculate_atr(df_temp, 20).fillna(c * 0.008)
    df["atr_14"] = atr14
    df["squeeze_5m"] = atr5 / (atr20 + 1e-8)

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

    # 微观
    e4 = calculate_ema(pd.Series(c), 4)
    e12 = calculate_ema(pd.Series(c), 12)
    e24 = calculate_ema(pd.Series(c), 24)
    e72 = calculate_ema(pd.Series(c), 72)
    e120 = calculate_ema(pd.Series(c), 120)
    df["accel_5m"] = ((e4 - e12) - (e12 - e24)) / (atr14 + 1e-8)
    df["fast_trend"] = (e4 - e24) / (atr14 + 1e-8)
    df["slow_trend"] = (e24 - e72) / (atr14 + 1e-8)
    df["dist_ema_120"] = (c - e120) / (atr14 + 1e-8)
    df["rsi_14_5m"] = calculate_rsi(pd.Series(c), 14).fillna(50.0)

    v_ma = v.rolling(20).mean() + 1e-8
    df["vol_burst_5m"] = v / v_ma
    df["oi_flow_5m"] = oi.diff().fillna(0) / v_ma

    donch_hi = h.rolling(24).max().shift(1)
    donch_lo = l.rolling(24).min().shift(1)
    df["donchian_dist_5m"] = (c - (donch_hi + donch_lo) / 2.0) / (atr14 + 1e-8)

    return df


def simulate_complete_roundtrip(df_feat, horizon=48, target_atr=5.0, sl_label=1.2, prob_th=0.28, sl_atr=1.2, be_atr=1.8, lock_atr=2.6, trail_atr=1.2, lock_pct=0.75, max_bars=45):
    feature_cols = [
        "slow_trend", "donchian_dist_5m", "accel_5m", "squeeze_5m",
        "fast_trend", "dist_ema_120", "rsi_14_5m", "oi_flow_5m", "vol_burst_5m"
    ]
    df_clean = df_feat.dropna(subset=feature_cols + ["atr_14"]).reset_index(drop=True)

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

    pos = 0
    lots = 0
    entry_p = 0.0
    sl_p = 0.0
    entry_i = 0
    peak_p = 0.0
    trough_p = 999999.0
    half_locked = False
    max_lots = 8
    multiplier = 5.0
    fee_rate = 0.00003

    round_trip_trades = []
    current_trade_pnl = 0.0

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
                if pos == 1: sl_p = max(sl_p, entry_p + 0.25 * catr)
                else: sl_p = min(sl_p, entry_p - 0.25 * catr)

            # 2. PPO 锁利动作
            if pnl_atr >= lock_atr and not half_locked and lots > 1:
                close_lots = int(max_lots * lock_pct)
                exit_p = cp - 5.0 if pos == 1 else cp + 5.0
                realized = (exit_p - entry_p)*multiplier*close_lots if pos == 1 else (entry_p - exit_p)*multiplier*close_lots
                fee = (entry_p + exit_p)*multiplier*close_lots * fee_rate
                current_trade_pnl += (realized - fee)
                lots -= close_lots
                half_locked = True
                if pos == 1: sl_p = max(sl_p, peak_p - trail_atr * catr)
                else: sl_p = min(sl_p, trough_p + trail_atr * catr)

            # 3. 吊灯追踪
            if half_locked and lots > 0:
                if pos == 1: sl_p = max(sl_p, peak_p - trail_atr * catr)
                else: sl_p = min(sl_p, trough_p + trail_atr * catr)

            hit_sl = (lp <= sl_p) if pos == 1 else (hp >= sl_p)
            timeout = h_bars >= max_bars

            if (hit_sl or timeout) and lots > 0:
                exit_p = sl_p if hit_sl else cp
                realized = (exit_p - entry_p)*multiplier*lots if pos == 1 else (entry_p - exit_p)*multiplier*lots
                fee = (entry_p + exit_p)*multiplier*lots * fee_rate
                current_trade_pnl += (realized - fee)
                round_trip_trades.append({
                    "round_trip_pnl": current_trade_pnl,
                    "direction": "LONG" if pos == 1 else "SHORT",
                    "entry_p": entry_p,
                    "exit_p": exit_p,
                    "bars": h_bars
                })
                pos = 0
                lots = 0
                half_locked = False
                current_trade_pnl = 0.0

        if pos == 0:
            long_cond = sim_pl[i] >= prob_th and sim_m30[i] > 0 and sim_m60[i] >= 0
            short_cond = sim_ps[i] >= prob_th and sim_m30[i] < 0 and sim_m60[i] <= 0

            if long_cond:
                pos = 1
                lots = max_lots
                entry_p = cp + 5.0
                sl_p = entry_p - sl_atr * catr
                peak_p = cp
                entry_i = i
                half_locked = False
                current_trade_pnl = 0.0

            elif short_cond:
                pos = -1
                lots = max_lots
                entry_p = cp - 5.0
                sl_p = entry_p + sl_atr * catr
                trough_p = cp
                entry_i = i
                half_locked = False
                current_trade_pnl = 0.0

    if not round_trip_trades:
        return None

    rt_pnls = np.array([t["round_trip_pnl"] for t in round_trip_trades])
    wins = rt_pnls[rt_pnls > 0]
    losses = rt_pnls[rt_pnls <= 0]
    wr = len(wins) / len(rt_pnls) * 100.0
    tot_w = np.sum(wins) if len(wins) > 0 else 0.0
    tot_l = abs(np.sum(losses)) if len(losses) > 0 else 1e-6
    pf = tot_w / tot_l
    payoff = (np.mean(wins) / abs(np.mean(losses))) if (len(wins) > 0 and len(losses) > 0) else 0.0
    net = np.sum(rt_pnls)

    return {
        "round_trip_trades": len(round_trip_trades),
        "win_rate": wr,
        "profit_factor": pf,
        "payoff_ratio": payoff,
        "total_pnl": net,
        "avg_win": np.mean(wins) if len(wins) > 0 else 0,
        "avg_loss": abs(np.mean(losses)) if len(losses) > 0 else 0
    }


def main():
    df_raw = load_cf()
    df_feat = engineer_cotton_features(df_raw)

    print("📊 正在运行棉花完整往返回测 (Round-Trip Analysis)...")
    res = simulate_complete_roundtrip(df_feat)
    print("=" * 80)
    print(f"棉花 5m 完整单笔往返回测结果:")
    print(f"  👉 完整交易笔数: {res['round_trip_trades']}")
    print(f"  👉 胜率 (Win Rate): {res['win_rate']:.2f}%")
    print(f"  👉 总盈亏比 (Profit Factor): {res['profit_factor']:.2f}")
    print(f"  👉 单笔盈亏比 (Payoff Ratio): {res['payoff_ratio']:.2f}")
    print(f"  👉 累计净利润: {res['total_pnl']:+,.2f} 元")
    print(f"  👉 平均单笔盈利: {res['avg_win']:.2f} 元")
    print(f"  👉 平均单笔亏损: {res['avg_loss']:.2f} 元")
    print("=" * 80)


if __name__ == "__main__":
    main()
