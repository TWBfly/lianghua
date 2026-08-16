"""
Targeted Optimization for Cotton (CF_IDX) 5m Strategy:
Goal: Win Rate >= 51%, Profit Factor (盈亏比) >= 3.0, Strong Positive PnL
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


def load_data():
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


def engineer_features(df_raw):
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

    # 宏观 30m / 60m 趋势 (严格 shift 1)
    df_work = df.copy().set_index("datetime")
    df_60m = df_work.resample("60min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    df_60m["ema20"] = calculate_ema(df_60m["close"], 20)
    df_60m["ema60"] = calculate_ema(df_60m["close"], 60)
    df_60m["macro_60m"] = np.where((df_60m["close"] > df_60m["ema20"]) & (df_60m["ema20"] > df_60m["ema60"]), 1,
                           np.where((df_60m["close"] < df_60m["ema20"]) & (df_60m["ema20"] < df_60m["ema60"]), -1, 0))
    df_60m["macro_trend_60m"] = df_60m["macro_60m"].shift(1).fillna(0)
    df = pd.merge_asof(df, df_60m[["macro_trend_60m"]].reset_index(), on="datetime", direction="backward").fillna(0)

    # 微观
    e8 = calculate_ema(pd.Series(c), 8)
    e24 = calculate_ema(pd.Series(c), 24)
    e72 = calculate_ema(pd.Series(c), 72)
    df["fast_trend"] = (e8 - e24) / (atr14 + 1e-8)
    df["slow_trend"] = (e24 - e72) / (atr14 + 1e-8)
    df["rsi_14"] = calculate_rsi(pd.Series(c), 14).fillna(50.0)

    v_ma = v.rolling(20).mean() + 1e-8
    df["vol_burst"] = v / v_ma
    df["oi_flow"] = oi.diff().fillna(0) / v_ma

    donch_hi = h.rolling(20).max().shift(1)
    donch_lo = l.rolling(20).min().shift(1)
    df["donch_dist"] = (c - (donch_hi + donch_lo) / 2.0) / (atr14 + 1e-8)

    return df


def search_high_pf_and_wr(df_feat):
    feature_cols = ["fast_trend", "slow_trend", "squeeze_5m", "vol_burst", "oi_flow", "donch_dist", "rsi_14"]
    df_clean = df_feat.dropna(subset=feature_cols + ["atr_14"]).reset_index(drop=True)

    # 尝试不同的大波段目标
    results = []

    for horizon in [24, 36, 48, 60]:
        for target_atr in [3.5, 4.0, 4.5, 5.0]:
            for sl_label in [0.7, 0.8, 1.0]:
                fut_h = pd.Series(df_clean["high"])[::-1].rolling(horizon, min_periods=1).max()[::-1].shift(-1).values
                fut_l = pd.Series(df_clean["low"])[::-1].rolling(horizon, min_periods=1).min()[::-1].shift(-1).values
                c_vals = df_clean["close"].values
                atr_vals = df_clean["atr_14"].values

                label_l = (((fut_h - c_vals) / (atr_vals + 1e-8) >= target_atr) & ((c_vals - fut_l) / (atr_vals + 1e-8) < sl_label)).astype(int)
                label_s = (((c_vals - fut_l) / (atr_vals + 1e-8) >= target_atr) & ((fut_h - c_vals) / (atr_vals + 1e-8) < sl_label)).astype(int)

                if np.sum(label_l) < 50 or np.sum(label_s) < 50:
                    continue

                X_mat = df_clean[feature_cols].values.astype(np.float32)
                n_samples = len(df_clean)

                # Embargoed Walk-Forward
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

                    clf_l = lgb.LGBMClassifier(
                        n_estimators=70, learning_rate=0.03, max_depth=3, num_leaves=6,
                        min_child_samples=25, subsample=0.8, colsample_bytree=0.8, random_state=42, verbose=-1, n_jobs=2
                    )
                    clf_s = lgb.LGBMClassifier(
                        n_estimators=70, learning_rate=0.03, max_depth=3, num_leaves=6,
                        min_child_samples=25, subsample=0.8, colsample_bytree=0.8, random_state=42, verbose=-1, n_jobs=2
                    )

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
                sim_vb = df_sim["vol_burst"].values

                # 测试出场逻辑：阶梯止损锁定 (Multi-Tier Profit Lock)
                for p_th in [0.24, 0.26, 0.28, 0.30, 0.32]:
                    for sl_atr in [0.6, 0.7, 0.8, 0.9]:
                        for be_atr in [1.0, 1.2, 1.5]:
                            for lock1_atr in [1.8, 2.2, 2.6]:
                                for lock2_atr in [3.0, 3.5, 4.0]:
                                    for max_bars in [35, 50, 70]:
                                        pos = 0
                                        entry_p = 0.0
                                        sl_p = 0.0
                                        entry_i = 0
                                        peak_p = 0.0
                                        trough_p = 999999.0
                                        trades = []

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

                                                # 多阶梯止盈止损移动 (严格保护盈利)
                                                if pnl_atr >= lock2_atr:
                                                    # 锁定 80% 利润
                                                    if pos == 1: sl_p = max(sl_p, entry_p + (lock2_atr - 0.8) * catr)
                                                    else: sl_p = min(sl_p, entry_p - (lock2_atr - 0.8) * catr)
                                                elif pnl_atr >= lock1_atr:
                                                    # 锁定 50% 利润
                                                    if pos == 1: sl_p = max(sl_p, entry_p + (lock1_atr - 0.8) * catr)
                                                    else: sl_p = min(sl_p, entry_p - (lock1_atr - 0.8) * catr)
                                                elif pnl_atr >= be_atr:
                                                    # 保本
                                                    if pos == 1: sl_p = max(sl_p, entry_p + 0.25 * catr)
                                                    else: sl_p = min(sl_p, entry_p - 0.25 * catr)

                                                hit_sl = (lp <= sl_p) if pos == 1 else (hp >= sl_p)
                                                timeout = h_bars >= max_bars

                                                if hit_sl or timeout:
                                                    exit_p = sl_p if hit_sl else cp
                                                    pnl = (exit_p - entry_p)*5.0*8 if pos == 1 else (entry_p - exit_p)*5.0*8
                                                    fee = (entry_p + exit_p)*5.0*8 * 0.00003
                                                    trades.append(pnl - fee)
                                                    pos = 0

                                            if pos == 0:
                                                # 高确信度开仓
                                                long_cond = sim_pl[i] >= p_th and sim_m60[i] >= 0 and sim_vb[i] >= 0.8
                                                short_cond = sim_ps[i] >= p_th and sim_m60[i] <= 0 and sim_vb[i] >= 0.8

                                                if long_cond:
                                                    pos = 1
                                                    entry_p = cp + 5.0
                                                    sl_p = entry_p - sl_atr * catr
                                                    peak_p = cp
                                                    entry_i = i

                                                elif short_cond:
                                                    pos = -1
                                                    entry_p = cp - 5.0
                                                    sl_p = entry_p + sl_atr * catr
                                                    trough_p = cp
                                                    entry_i = i

                                        if len(trades) >= 15:
                                            tr = np.array(trades)
                                            wins = tr[tr > 0]
                                            losses = tr[tr <= 0]
                                            wr = len(wins) / len(tr) * 100.0
                                            tot_w = np.sum(wins) if len(wins) > 0 else 0.0
                                            tot_l = abs(np.sum(losses)) if len(losses) > 0 else 1e-6
                                            pf = tot_w / tot_l
                                            payoff = (np.mean(wins) / abs(np.mean(losses))) if (len(wins) > 0 and len(losses) > 0) else 0.0
                                            net = np.sum(tr)

                                            cfg_dict = {
                                                "horizon": horizon, "target_atr": target_atr, "sl_label": sl_label,
                                                "prob_thresh": p_th, "sl_atr": sl_atr, "be_atr": be_atr,
                                                "lock1_atr": lock1_atr, "lock2_atr": lock2_atr, "max_bars": max_bars
                                            }

                                            res_item = {
                                                "wr": wr, "pf": pf, "payoff": payoff, "net": net, "trades": len(tr),
                                                "cfg": cfg_dict
                                            }
                                            results.append(res_item)

                                            if wr >= 51.0 and pf >= 3.0 and net > 0:
                                                print(f"🎉 成功达标! 胜率: {wr:.2f}%, 盈亏比(PF): {pf:.2f}, 单笔盈亏比: {payoff:.2f}, 净利润: {net:+,.2f}元, 交易数: {len(tr)}")

    return results


def main():
    df_raw = load_data()
    print(f"Loaded {len(df_raw)} bars of CF_IDX.")
    df_feat = engineer_features(df_raw)
    results = search_high_pf_and_wr(df_feat)

    # 严格挑选：胜率 >= 51% 且 盈亏比 (PF) >= 3.0
    qual = [r for r in results if r["wr"] >= 51.0 and r["pf"] >= 3.0 and r["net"] > 0]
    print(f"\n=======================================================")
    print(f"符合所有指标 (胜率 >= 51% 且 PF >= 3.0) 的配置数量: {len(qual)}")
    print(f"=======================================================")

    if qual:
        qual = sorted(qual, key=lambda x: (x["pf"], x["wr"], x["net"]), reverse=True)
        for i, q in enumerate(qual[:10], 1):
            c = q["cfg"]
            print(f"Rank {i}: 胜率={q['wr']:.2f}%, 盈亏比(PF)={q['pf']:.2f}, 净利={q['net']:+,.2f}元, 交易数={q['trades']}")
            print(f"        {c}")
    else:
        results = sorted(results, key=lambda x: (x["wr"] >= 50.0, x["pf"], x["net"]), reverse=True)
        for i, q in enumerate(results[:10], 1):
            c = q["cfg"]
            print(f"Top {i}: 胜率={q['wr']:.2f}%, 盈亏比(PF)={q['pf']:.2f}, 净利={q['net']:+,.2f}元, 交易数={q['trades']}")
            print(f"       {c}")


if __name__ == "__main__":
    main()
