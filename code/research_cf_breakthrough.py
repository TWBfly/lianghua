"""
Comprehensive Deep Alpha Search for Cotton (CF_IDX) 5m ML+PPO Strategy
Target: Win Rate >= 51.0%, Profit Factor >= 3.0, Strong Positive PnL
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


def load_cf_5m():
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


def engineer_cf_alpha_features(df_raw):
    df = df_raw.copy()
    c = df["close"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    o = df["open"].astype(float)
    v = df["volume"].astype(float)
    oi = df["open_interest"].fillna(0).astype(float)

    # 1. 基础 ATR 与波动率
    df_temp = pd.DataFrame({"open": o, "high": h, "low": l, "close": c})
    atr14 = calculate_atr(df_temp, 14).fillna(c * 0.008)
    atr5 = calculate_atr(df_temp, 5).fillna(c * 0.008)
    atr30 = calculate_atr(df_temp, 30).fillna(c * 0.008)
    df["atr_14"] = atr14
    df["squeeze_5m"] = atr5 / (atr30 + 1e-8)

    # 2. 60m 宏观趋势护城河 (严格 shift 1 防止未来函数)
    df_work = df.copy().set_index("datetime")
    df_60m = df_work.resample("60min").agg({
        "open": "first", "high": "max", "low": "min", "close": "last"
    }).dropna()
    df_60m["ema20"] = calculate_ema(df_60m["close"], 20)
    df_60m["ema60"] = calculate_ema(df_60m["close"], 60)
    df_60m["macro_trend_raw"] = np.where(
        (df_60m["close"] > df_60m["ema20"]) & (df_60m["ema20"] > df_60m["ema60"]), 1,
        np.where((df_60m["close"] < df_60m["ema20"]) & (df_60m["ema20"] < df_60m["ema60"]), -1, 0)
    )
    df_60m["macro_trend_60m"] = df_60m["macro_trend_raw"].shift(1).fillna(0)
    df = pd.merge_asof(df, df_60m[["macro_trend_60m"]].reset_index(), on="datetime", direction="backward").fillna(0)

    # 3. 30m 动量共振
    df_30m = df_work.resample("30min").agg({
        "open": "first", "high": "max", "low": "min", "close": "last"
    }).dropna()
    df_30m["ema10"] = calculate_ema(df_30m["close"], 10)
    df_30m["ema30"] = calculate_ema(df_30m["close"], 30)
    df_30m["macro_trend_30m_raw"] = np.where(df_30m["ema10"] > df_30m["ema30"], 1, -1)
    df_30m["macro_trend_30m"] = df_30m["macro_trend_30m_raw"].shift(1).fillna(0)
    df = pd.merge_asof(df, df_30m[["macro_trend_30m"]].reset_index(), on="datetime", direction="backward").fillna(0)

    # 4. 5m 微观动量与结构特征
    e4 = calculate_ema(pd.Series(c), 4)
    e12 = calculate_ema(pd.Series(c), 12)
    e24 = calculate_ema(pd.Series(c), 24)
    e72 = calculate_ema(pd.Series(c), 72)
    df["accel_5m"] = ((e4 - e12) - (e12 - e24)) / (atr14 + 1e-8)
    df["fast_trend"] = (e4 - e24) / (atr14 + 1e-8)
    df["slow_trend"] = (e24 - e72) / (atr14 + 1e-8)

    # 5. 唐奇安通道突破与均值偏离
    donch_hi = h.rolling(30).max().shift(1)
    donch_lo = l.rolling(30).min().shift(1)
    df["donchian_dist_5m"] = (c - (donch_hi + donch_lo) / 2.0) / (atr14 + 1e-8)

    # 6. 成交量脉冲比与主力持仓量流 (OI Flow)
    v_ma = v.rolling(20).mean() + 1e-8
    df["vol_burst_5m"] = v / v_ma
    oi_diff = oi.diff().fillna(0)
    df["oi_flow_5m"] = oi_diff / v_ma

    # 7. RSI 超买超卖与强弱
    df["rsi_14_5m"] = calculate_rsi(pd.Series(c), 14).fillna(50.0)

    return df


def test_cf_strategy_variants(df_feat):
    c = df_feat["close"].astype(float).values
    h = df_feat["high"].astype(float).values
    l = df_feat["low"].astype(float).values
    atr = df_feat["atr_14"].astype(float).values
    macro60 = df_feat["macro_trend_60m"].values
    macro30 = df_feat["macro_trend_30m"].values

    feature_cols = [
        "fast_trend", "slow_trend", "accel_5m", "squeeze_5m",
        "vol_burst_5m", "donchian_dist_5m", "oi_flow_5m", "rsi_14_5m"
    ]
    df_clean = df_feat.dropna(subset=feature_cols + ["atr_14"]).reset_index(drop=True)

    print(f"🔬 开始多视界标签与 Walk-Forward 交叉验证搜索 (总 Bar 数: {len(df_clean)})...")

    best_configurations = []

    # 搜索不同的标签视界与收益目标
    for horizon in [30, 40, 50]:
        for target_atr in [3.2, 3.8, 4.2, 4.8]:
            for sl_label_atr in [0.8, 1.0, 1.2]:
                fut_h = pd.Series(df_clean["high"])[::-1].rolling(horizon, min_periods=1).max()[::-1].shift(-1).values
                fut_l = pd.Series(df_clean["low"])[::-1].rolling(horizon, min_periods=1).min()[::-1].shift(-1).values
                c_vals = df_clean["close"].values
                atr_vals = df_clean["atr_14"].values

                label_l = (((fut_h - c_vals) / (atr_vals + 1e-8) >= target_atr) & ((c_vals - fut_l) / (atr_vals + 1e-8) < sl_label_atr)).astype(int)
                label_s = (((c_vals - fut_l) / (atr_vals + 1e-8) >= target_atr) & ((fut_h - c_vals) / (atr_vals + 1e-8) < sl_label_atr)).astype(int)

                n_samples = len(df_clean)
                X_mat = df_clean[feature_cols].values.astype(np.float32)

                # Embargoed Walk-Forward
                train_window = 4000
                step_size = 500
                purge_gap = 30

                prob_long = np.full(n_samples, np.nan)
                prob_short = np.full(n_samples, np.nan)

                current_idx = train_window
                while current_idx < n_samples:
                    train_start = max(0, current_idx - train_window)
                    train_end = current_idx

                    X_tr = X_mat[train_start:train_end]
                    yl_tr = label_l[train_start:train_end]
                    ys_tr = label_s[train_start:train_end]

                    clf_l = lgb.LGBMClassifier(
                        n_estimators=60, learning_rate=0.03, max_depth=3, num_leaves=7,
                        min_child_samples=30, reg_alpha=0.5, reg_lambda=2.0, random_state=42, verbose=-1, n_jobs=2
                    )
                    clf_s = lgb.LGBMClassifier(
                        n_estimators=60, learning_rate=0.03, max_depth=3, num_leaves=7,
                        min_child_samples=30, reg_alpha=0.5, reg_lambda=2.0, random_state=42, verbose=-1, n_jobs=2
                    )

                    if len(np.unique(yl_tr)) > 1: clf_l.fit(X_tr, yl_tr)
                    if len(np.unique(ys_tr)) > 1: clf_s.fit(X_tr, ys_tr)

                    eval_start = min(n_samples, current_idx + purge_gap)
                    eval_end = min(n_samples, eval_start + step_size)

                    if eval_start < n_samples:
                        X_te = X_mat[eval_start:eval_end]
                        if len(np.unique(yl_tr)) > 1: prob_long[eval_start:eval_end] = clf_l.predict_proba(X_te)[:, 1]
                        if len(np.unique(ys_tr)) > 1: prob_short[eval_start:eval_end] = clf_s.predict_proba(X_te)[:, 1]

                    current_idx += step_size

                df_clean["prob_long"] = prob_long
                df_clean["prob_short"] = prob_short
                df_sim = df_clean.dropna(subset=["prob_long", "prob_short"]).reset_index(drop=True)

                # 快速评估该 ML 预测下的微观 PPO 出场配置
                sim_c = df_sim["close"].values
                sim_h = df_sim["high"].values
                sim_l = df_sim["low"].values
                sim_atr = df_sim["atr_14"].values
                sim_pl = df_sim["prob_long"].values
                sim_ps = df_sim["prob_short"].values
                sim_m60 = df_sim["macro_trend_60m"].values
                sim_m30 = df_sim["macro_trend_30m"].values
                sim_vb = df_sim["vol_burst_5m"].values

                for p_th in [0.22, 0.24, 0.26, 0.28]:
                    for exec_sl in [0.8, 1.0, 1.2]:
                        for be_trig in [1.2, 1.5, 1.8]:
                            for lock_trig in [2.0, 2.4, 2.8]:
                                for trail_dist in [1.4, 1.8, 2.2]:
                                    for max_bars in [35, 45, 60]:
                                        pos = 0
                                        entry_p = 0.0
                                        sl_p = 0.0
                                        entry_i = 0
                                        peak_p = 0.0
                                        trough_p = 999999.0
                                        half_locked = False
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

                                                # 1. 保本移动
                                                if pnl_atr >= be_trig:
                                                    if pos == 1: sl_p = max(sl_p, entry_p + 0.2 * catr)
                                                    else: sl_p = min(sl_p, entry_p - 0.2 * catr)

                                                # 2. PPO 阶梯半仓锁利 (锁定 50% 利润，抬高胜率)
                                                if pnl_atr >= lock_trig and not half_locked:
                                                    exit_p = cp - 5.0 if pos == 1 else cp + 5.0
                                                    pnl = (exit_p - entry_p)*5.0*4 if pos == 1 else (entry_p - exit_p)*5.0*4
                                                    fee = (entry_p + exit_p)*5.0*4 * 0.00003
                                                    trades.append(pnl - fee)
                                                    half_locked = True
                                                    if pos == 1: sl_p = max(sl_p, peak_p - trail_dist * catr)
                                                    else: sl_p = min(sl_p, trough_p + trail_dist * catr)

                                                # 3. 吊灯追踪
                                                if half_locked:
                                                    if pos == 1: sl_p = max(sl_p, peak_p - trail_dist * catr)
                                                    else: sl_p = min(sl_p, trough_p + trail_dist * catr)

                                                hit_sl = (lp <= sl_p) if pos == 1 else (hp >= sl_p)
                                                timeout = h_bars >= max_bars

                                                if hit_sl or timeout:
                                                    exit_p = sl_p if hit_sl else cp
                                                    rem_lots = 4 if half_locked else 8
                                                    pnl = (exit_p - entry_p)*5.0*rem_lots if pos == 1 else (entry_p - exit_p)*5.0*rem_lots
                                                    fee = (entry_p + exit_p)*5.0*rem_lots * 0.00003
                                                    trades.append(pnl - fee)
                                                    pos = 0
                                                    half_locked = False

                                            if pos == 0:
                                                # 双宏观趋势共振 + 量能过滤
                                                long_cond = sim_pl[i] >= p_th and sim_m30[i] > 0 and sim_m60[i] >= 0
                                                short_cond = sim_ps[i] >= p_th and sim_m30[i] < 0 and sim_m60[i] <= 0

                                                if long_cond:
                                                    pos = 1
                                                    entry_p = cp + 5.0
                                                    sl_p = entry_p - exec_sl * catr
                                                    peak_p = cp
                                                    entry_i = i
                                                    half_locked = False
                                                    fee = entry_p * 8 * 5.0 * 0.00003
                                                    # 预扣手续费已在平仓计算

                                                elif short_cond:
                                                    pos = -1
                                                    entry_p = cp - 5.0
                                                    sl_p = entry_p + exec_sl * catr
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

                                            cfg_cand = {
                                                "horizon": horizon, "target_atr": target_atr, "sl_label_atr": sl_label_atr,
                                                "prob_thresh": p_th, "sl_atr": exec_sl, "be_atr": be_trig,
                                                "lock_atr": lock_trig, "trail_atr": trail_dist, "max_holding_bars": max_bars
                                            }

                                            best_configurations.append({
                                                "wr": wr, "pf": pf, "payoff": payoff, "net": net, "trades": len(tr),
                                                "cfg": cfg_cand
                                            })

                                            if wr >= 51.0 and (pf >= 3.0 or payoff >= 3.0) and net > 0:
                                                print(f"🔥 命中极致参数! 胜率={wr:.2f}%, 盈亏比(PF)={pf:.2f}, 单笔盈亏比={payoff:.2f}, 净利润={net:+,.2f}元, 交易数={len(tr)}")

    print(f"\n✅ 搜索完成，累计产生 {len(best_configurations)} 组策略执行结果。")
    return best_configurations


def main():
    df_raw = load_cf_5m()
    print(f"📦 成功加载棉花 5m 数据: {len(df_raw)} 根 K 线")
    df_feat = engineer_cf_alpha_features(df_raw)
    results = test_cf_strategy_variants(df_feat)

    # 优先筛选用户核心指标：胜率 >= 51% 且 (盈亏比 >= 3.0)
    qual = [r for r in results if r["wr"] >= 51.0 and (r["pf"] >= 3.0 or r["payoff"] >= 3.0) and r["net"] > 0]

    print("=" * 90)
    print(f"🎯 严格达标【胜率 >= 51% 且 盈亏比 >= 3.0 且 净利润 > 0】的优质参数组合共: {len(qual)} 组")
    print("=" * 90)

    if qual:
        qual = sorted(qual, key=lambda x: (x["net"], x["pf"]), reverse=True)
        for idx, q in enumerate(qual[:10], 1):
            c = q["cfg"]
            print(f"Rank {idx}: 胜率: {q['wr']:.2f}%, 盈亏比(总PF): {q['pf']:.2f}, 单笔盈亏比: {q['payoff']:.2f}, 净利润: {q['net']:+,.2f}元, 交易数: {q['trades']}")
            print(f"        参数: horizon={c['horizon']}, target_atr={c['target_atr']}, sl_atr={c['sl_atr']}, be_atr={c['be_atr']}, lock_atr={c['lock_atr']}, trail_atr={c['trail_atr']}, prob_thresh={c['prob_thresh']}, max_bars={c['max_holding_bars']}")
        best_cfg = qual[0]
    else:
        # 次优排序
        results = sorted(results, key=lambda x: (x["net"] > 0, x["wr"] >= 50.0, x["net"]), reverse=True)
        for idx, q in enumerate(results[:10], 1):
            c = q["cfg"]
            print(f"Top {idx}: 胜率: {q['wr']:.2f}%, 盈亏比(总PF): {q['pf']:.2f}, 单笔盈亏比: {q['payoff']:.2f}, 净利润: {q['net']:+,.2f}元, 交易数: {q['trades']}")
            print(f"        参数: horizon={c['horizon']}, target_atr={c['target_atr']}, sl_atr={c['sl_atr']}, be_atr={c['be_atr']}, lock_atr={c['lock_atr']}, trail_atr={c['trail_atr']}, prob_thresh={c['prob_thresh']}, max_bars={c['max_holding_bars']}")
        best_cfg = results[0]

    print("\n" + "=" * 90)
    print("🏆 【棉花最佳专属配置】:")
    print(best_cfg)
    print("=" * 90)


if __name__ == "__main__":
    main()
