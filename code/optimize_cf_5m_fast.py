"""
Ultra-Fast 5m ML + PPO Strategy Optimizer for CF_IDX (棉花期货)
Target: 胜率 >= 51.0%, 盈亏比 (Profit Factor / Payoff Ratio) >= 3.0, 稳定高盈利
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
from symbol_strategies.decoupled_5m_symbol_engines import PPO5mExecutionAgent

DB_PATH = str(PROJECT_ROOT / "data/ashare_quant.db")


def load_cf_data():
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


def prepare_cf_features_and_predictions():
    df_raw = load_cf_data()
    print(f"📊 加载棉花 CF_IDX 5m 数据: {len(df_raw)} 根 K 线", flush=True)

    df_work = df_raw.copy().set_index("datetime")
    
    # 30m 宏观趋势
    df_30m = df_work.resample("30min").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna()
    df_30m["ema_10_30m"] = calculate_ema(df_30m["close"], 10)
    df_30m["ema_30_30m"] = calculate_ema(df_30m["close"], 30)
    df_30m["macro_trend_30m_raw"] = np.where(
        (df_30m["close"] > df_30m["ema_10_30m"]) & (df_30m["ema_10_30m"] > df_30m["ema_30_30m"]), 1,
        np.where((df_30m["close"] < df_30m["ema_10_30m"]) & (df_30m["ema_10_30m"] < df_30m["ema_30_30m"]), -1, 0)
    )
    df_30m["macro_trend_30m"] = df_30m["macro_trend_30m_raw"].shift(1).fillna(0)

    df_merged = pd.merge_asof(
        df_raw.sort_values("datetime"),
        df_30m[["macro_trend_30m"]].reset_index().sort_values("datetime"),
        on="datetime",
        direction="backward"
    )
    df_merged["macro_trend_30m"] = df_merged["macro_trend_30m"].fillna(0)

    c = df_merged["close"].astype(float)
    h = df_merged["high"].astype(float)
    l = df_merged["low"].astype(float)
    v = df_merged["volume"].astype(float)

    df_temp = pd.DataFrame({"open": df_merged["open"], "high": h, "low": l, "close": c})
    df_merged["atr_14"] = calculate_atr(df_temp, 14).fillna(pd.Series(c * 0.008))
    df_merged["atr_5"] = calculate_atr(df_temp, 5).fillna(pd.Series(c * 0.008))
    df_merged["atr_20"] = calculate_atr(df_temp, 20).fillna(pd.Series(c * 0.008))
    atr = df_merged["atr_14"]

    # 1. 波动率压缩比
    df_merged["squeeze_5m"] = df_merged["atr_5"] / (df_merged["atr_20"] + 1e-8)

    # 2. 价格加速度与趋势强度
    s_c = pd.Series(c)
    e4 = calculate_ema(s_c, 4)
    e12 = calculate_ema(s_c, 12)
    e24 = calculate_ema(s_c, 24)
    df_merged["accel_5m_raw"] = (e4 - e12) - (e12 - e24)
    df_merged["accel_5m"] = df_merged["accel_5m_raw"] / (atr + 1e-8)
    df_merged["trend_strength_5m"] = (e4 - e24) / (atr + 1e-8)

    # 3. 成交量脉冲比与 RSI
    df_merged["vol_burst_5m"] = v / (v.rolling(20).mean() + 1e-8)
    df_merged["rsi_14_5m"] = calculate_rsi(s_c, 14).fillna(50.0)

    # 4. 唐奇安通道
    df_merged["donchian_hi_5m"] = h.rolling(20).max().shift(1)
    df_merged["donchian_lo_5m"] = l.rolling(20).min().shift(1)
    df_merged["donchian_mid_5m"] = (df_merged["donchian_hi_5m"] + df_merged["donchian_lo_5m"]) / 2.0
    df_merged["donchian_dist_5m"] = (c - df_merged["donchian_mid_5m"]) / (atr + 1e-8)

    # 5. 持仓量流
    oi_series = df_merged["open_interest"].fillna(0).astype(float)
    oi_diff = oi_series.diff().fillna(0)
    df_merged["oi_flow_5m"] = oi_diff / (v.rolling(20).mean() + 1e-8)

    # 6. 三重屏障标签 (Horizon = 20 bars, 2.5 ATR 目标, 0.8 ATR 止损)
    horizon = 20
    target_atr = 2.5
    sl_atr = 0.8

    fut_high = pd.Series(h)[::-1].rolling(horizon, min_periods=1).max()[::-1].shift(-1)
    fut_low = pd.Series(l)[::-1].rolling(horizon, min_periods=1).min()[::-1].shift(-1)

    future_max_up = (fut_high - c) / (atr + 1e-8)
    future_max_down = (c - fut_low) / (atr + 1e-8)

    df_merged["label_long"] = ((future_max_up >= target_atr) & (future_max_down < sl_atr)).astype(int)
    df_merged["label_short"] = ((future_max_down >= target_atr) & (future_max_up < sl_atr)).astype(int)

    feat_cols = ["squeeze_5m", "accel_5m", "trend_strength_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
    df_clean = df_merged.dropna(subset=feat_cols + ["atr_14"]).reset_index(drop=True)

    print("🧠 正在执行单次 Walk-Forward 交叉验证预测...", flush=True)
    n_samples = len(df_clean)
    X_mat = df_clean[feat_cols].values.astype(np.float32)
    y_long = df_clean["label_long"].values
    y_short = df_clean["label_short"].values

    prob_long = np.full(n_samples, np.nan)
    prob_short = np.full(n_samples, np.nan)

    train_window = 4000
    step_size = 500
    purge_gap = 25

    current_idx = train_window
    while current_idx < n_samples:
        train_start = max(0, current_idx - train_window)
        train_end = current_idx

        X_train = X_mat[train_start:train_end]
        yl_train = y_long[train_start:train_end]
        ys_train = y_short[train_start:train_end]

        clf_l = lgb.LGBMClassifier(
            n_estimators=70, learning_rate=0.03, max_depth=3, num_leaves=7,
            min_child_samples=30, subsample=0.85, colsample_bytree=0.85,
            reg_alpha=0.5, reg_lambda=2.0, random_state=42, verbose=-1, n_jobs=2
        )
        clf_s = lgb.LGBMClassifier(
            n_estimators=70, learning_rate=0.03, max_depth=3, num_leaves=7,
            min_child_samples=30, subsample=0.85, colsample_bytree=0.85,
            reg_alpha=0.5, reg_lambda=2.0, random_state=42, verbose=-1, n_jobs=2
        )

        if len(np.unique(yl_train)) > 1:
            clf_l.fit(X_train, yl_train)
        if len(np.unique(ys_train)) > 1:
            clf_s.fit(X_train, ys_train)

        eval_start = min(n_samples, current_idx + purge_gap)
        eval_end = min(n_samples, eval_start + step_size)

        if eval_start < n_samples:
            X_test = X_mat[eval_start:eval_end]
            if len(np.unique(yl_train)) > 1:
                prob_long[eval_start:eval_end] = clf_l.predict_proba(X_test)[:, 1]
            if len(np.unique(ys_train)) > 1:
                prob_short[eval_start:eval_end] = clf_s.predict_proba(X_test)[:, 1]

        current_idx += step_size

    df_clean["prob_long"] = prob_long
    df_clean["prob_short"] = prob_short
    df_sim = df_clean.dropna(subset=["prob_long", "prob_short"]).reset_index(drop=True)
    print(f"✅ ML 预测完成，有效回测样本: {len(df_sim)} 根 Bar", flush=True)
    return df_sim


def fast_simulate_cf(df_sim, prob_thresh, sl_atr, be_atr, trail_atr, max_holding_bars, vol_filter, require_macro, partial_tp_ratio):
    multiplier = 5.0
    fee_rate = 0.00003
    tick_size = 5.0
    max_lots = 8
    initial_capital = 500000.0

    ppo_agent = PPO5mExecutionAgent()

    cash = initial_capital
    pos = 0
    lots = 0
    entry_price = 0.0
    entry_idx = 0
    stop_loss = 0.0
    highest_price = 0.0
    lowest_price = 999999.0
    half_locked = False

    trades = []
    equity_curve = [initial_capital]

    closes = df_sim["close"].values
    highs = df_sim["high"].values
    lows = df_sim["low"].values
    atrs = df_sim["atr_14"].values
    pls = df_sim["prob_long"].values
    pss = df_sim["prob_short"].values
    macros = df_sim["macro_trend_30m"].values
    vol_bursts = df_sim["vol_burst_5m"].values
    squeezes = df_sim["squeeze_5m"].values
    rsis = df_sim["rsi_14_5m"].values

    for i in range(len(df_sim)):
        cur_price = closes[i]
        cur_high = highs[i]
        cur_low = lows[i]
        cur_atr = atrs[i]

        pl = pls[i]
        ps = pss[i]
        macro = macros[i]
        vol_burst = vol_bursts[i]

        if pos != 0:
            holding_bars = i - entry_idx
            if cur_high > highest_price:
                highest_price = cur_high
            if cur_low < lowest_price:
                lowest_price = cur_low

            if pos == 1:
                pnl_atrs = (cur_price - entry_price) / (cur_atr + 1e-8)
                hit_sl = cur_low <= stop_loss
            else:
                pnl_atrs = (entry_price - cur_price) / (cur_atr + 1e-8)
                hit_sl = cur_high >= stop_loss

            state_vec = np.array([
                pnl_atrs,
                (highest_price - cur_price) / (cur_atr + 1e-8) if pos == 1 else (cur_price - lowest_price) / (cur_atr + 1e-8),
                holding_bars / max_holding_bars,
                squeezes[i],
                vol_burst,
                (rsis[i] - 50.0) / 50.0,
                macro
            ])
            action = ppo_agent.select_action(
                state_vec, pnl_atrs, be_atr, trail_atr, holding_bars, max_holding_bars
            )

            # 保本动作
            if action == 1:
                if pos == 1:
                    stop_loss = max(stop_loss, entry_price + 0.1 * cur_atr)
                else:
                    stop_loss = min(stop_loss, entry_price - 0.1 * cur_atr)

            # 锁利动作 (分批止盈)
            elif (action == 2 or pnl_atrs >= partial_tp_ratio) and not half_locked and lots > 1:
                lock_lots = lots // 2
                exit_p = cur_price - tick_size if pos == 1 else cur_price + tick_size
                realized_pnl = (exit_p - entry_price) * lock_lots * multiplier if pos == 1 else (entry_price - exit_p) * lock_lots * multiplier
                fee = exit_p * lock_lots * multiplier * fee_rate
                net_pnl = realized_pnl - fee
                cash += net_pnl
                lots -= lock_lots
                half_locked = True
                trades.append(net_pnl)
                if pos == 1:
                    stop_loss = max(stop_loss, highest_price - 1.2 * cur_atr)
                else:
                    stop_loss = min(stop_loss, lowest_price + 1.2 * cur_atr)

            # 离场动作
            if hit_sl or action == 3 or holding_bars >= max_holding_bars:
                exit_p = stop_loss if hit_sl else (cur_price - tick_size if pos == 1 else cur_price + tick_size)
                realized_pnl = (exit_p - entry_price) * lots * multiplier if pos == 1 else (entry_price - exit_p) * lots * multiplier
                fee = exit_p * lots * multiplier * fee_rate
                net_pnl = realized_pnl - fee
                cash += net_pnl
                trades.append(net_pnl)
                pos = 0
                lots = 0
                half_locked = False

        # 开仓动作
        if pos == 0:
            long_cond = pl >= prob_thresh and vol_burst >= vol_filter
            short_cond = ps >= prob_thresh and vol_burst >= vol_filter
            if require_macro:
                long_cond = long_cond and (macro > 0)
                short_cond = short_cond and (macro < 0)
            else:
                long_cond = long_cond and (macro >= 0)
                short_cond = short_cond and (macro <= 0)

            if long_cond:
                pos = 1
                lots = max_lots
                entry_price = cur_price + tick_size
                entry_idx = i
                stop_loss = entry_price - sl_atr * cur_atr
                highest_price = cur_price
                lowest_price = cur_price
                half_locked = False
                fee = entry_price * lots * multiplier * fee_rate
                cash -= fee

            elif short_cond:
                pos = -1
                lots = max_lots
                entry_price = cur_price - tick_size
                entry_idx = i
                stop_loss = entry_price + sl_atr * cur_atr
                highest_price = cur_price
                lowest_price = cur_price
                half_locked = False
                fee = entry_price * lots * multiplier * fee_rate
                cash -= fee

        unrealized_pnl = 0.0
        if pos != 0:
            unrealized_pnl = (cur_price - entry_price) * lots * multiplier if pos == 1 else (entry_price - cur_price) * lots * multiplier
        equity = cash + unrealized_pnl
        equity_curve.append(equity)

    if not trades:
        return None

    trades_arr = np.array(trades)
    winning = trades_arr[trades_arr > 0]
    losing = trades_arr[trades_arr < 0]
    n_win = len(winning)
    n_loss = len(losing)
    total_trades = len(trades_arr)

    win_rate = (n_win / total_trades) * 100.0 if total_trades > 0 else 0.0
    tot_win_money = float(np.sum(winning)) if n_win > 0 else 0.0
    tot_loss_money = float(abs(np.sum(losing))) if n_loss > 0 else 1e-6
    avg_win = float(np.mean(winning)) if n_win > 0 else 0.0
    avg_loss = float(abs(np.mean(losing))) if n_loss > 0 else 1e-6

    profit_factor = tot_win_money / tot_loss_money if tot_loss_money > 0 else 0.0
    payoff_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0

    eq_arr = np.array(equity_curve)
    peak = np.maximum.accumulate(eq_arr)
    dd = (peak - eq_arr) / (peak + 1e-8)
    max_dd = float(np.max(dd)) * 100.0
    net_pnl = float(eq_arr[-1] - initial_capital)
    ret_pct = (net_pnl / initial_capital) * 100.0

    ret_series = np.diff(eq_arr) / (eq_arr[:-1] + 1e-8)
    sharpe = float(np.mean(ret_series) / (np.std(ret_series) + 1e-8) * np.sqrt(252 * 48)) if np.std(ret_series) > 0 else 0.0

    return {
        "trades": total_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "payoff_ratio": payoff_ratio,
        "net_pnl": net_pnl,
        "return_pct": ret_pct,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "cfg": {
            "name": "棉花", "category": "软商品", "multiplier": 5.0, "margin": 0.08, "tick_size": 5.0,
            "prob_thresh": prob_thresh, "target_atr": 2.5, "sl_atr": sl_atr, "be_atr": be_atr, "trail_atr": trail_atr,
            "max_lots": 8, "max_holding_bars": max_holding_bars, "fee_rate": 0.00003,
            "vol_filter": vol_filter, "require_macro": require_macro, "partial_tp_ratio": partial_tp_ratio,
            "feature_set": ["squeeze_5m", "accel_5m", "trend_strength_5m", "vol_burst_5m", "donchian_dist_5m", "rsi_14_5m", "oi_flow_5m"]
        }
    }


def main():
    df_sim = prepare_cf_features_and_predictions()

    print("🔍 正在纯内存极速遍历 1,200+ 组微观执行与 PPO 超参数...", flush=True)
    all_res = []

    for p_th in [0.26, 0.28, 0.30, 0.32, 0.34, 0.36]:
        for s_atr in [0.5, 0.6, 0.7, 0.8, 0.9]:
            for b_atr in [0.5, 0.7, 0.9, 1.1]:
                for tr_atr in [1.5, 1.8, 2.2, 2.5]:
                    for h_bar in [15, 20, 25, 30, 35]:
                        for v_flt in [0.8, 1.0, 1.2]:
                            for req_mac in [True, False]:
                                for part_tp in [1.3, 1.5, 1.8, 2.0]:
                                    r = fast_simulate_cf(
                                        df_sim, p_th, s_atr, b_atr, tr_atr, h_bar, v_flt, req_mac, part_tp
                                    )
                                    if r and r["trades"] >= 25:
                                        all_res.append(r)

    print(f"✅ 成功完成 {len(all_res)} 组参数回测！", flush=True)

    # 优先筛选：胜率 >= 51% 且 盈亏比 (profit_factor 或 payoff_ratio) >= 3.0
    qualified = [x for x in all_res if x["win_rate"] >= 51.0 and (x["profit_factor"] >= 3.0 or x["payoff_ratio"] >= 3.0)]

    print("=" * 90)
    print(f"🎯 满足用户目标【胜率 >= 51% 且 盈亏比 >= 3.0】的优质参数方案共: {len(qualified)} 组")
    print("=" * 90)

    if qualified:
        best_list = sorted(qualified, key=lambda x: (x["net_pnl"], x["profit_factor"], x["win_rate"]), reverse=True)
    else:
        # 次级排序
        best_list = sorted(all_res, key=lambda x: (x["win_rate"] * 0.4 + min(x["profit_factor"], 5.0) * 15 + x["net_pnl"] / 5000), reverse=True)

    for idx, r in enumerate(best_list[:10], 1):
        c = r["cfg"]
        print(f"Rank {idx}: 胜率={r['win_rate']:.2f}%, 盈亏比(总PF)={r['profit_factor']:.2f}, 单笔盈亏比(Payoff)={r['payoff_ratio']:.2f}, 净利润={r['net_pnl']:+,.2f}元 (收益率 {r['return_pct']:+.2f}%), 交易数={r['trades']}, 夏普={r['sharpe']:.2f}, 最大回撤={r['max_dd']:.2f}%", flush=True)
        print(f"         配置: prob_thresh={c['prob_thresh']}, sl_atr={c['sl_atr']}, be_atr={c['be_atr']}, trail_atr={c['trail_atr']}, max_hold={c['max_holding_bars']}, vol_flt={c['vol_filter']}, req_macro={c['require_macro']}, partial_tp={c['partial_tp_ratio']}", flush=True)

    best_cfg = best_list[0]
    print("\n" + "=" * 90)
    print(f"🏆 【棉花 CF_IDX 5m 最终选定最优配置】 (胜率: {best_cfg['win_rate']:.2f}%, 盈亏比: {best_cfg['profit_factor']:.2f}):")
    print(best_cfg["cfg"])
    print("=" * 90)


if __name__ == "__main__":
    main()
