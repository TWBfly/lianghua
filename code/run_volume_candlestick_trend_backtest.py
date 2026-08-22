"""
code/run_volume_candlestick_trend_backtest.py — SuperTrend 与 AlphaTrend 深度融合【成交量 + K线微观形态 + 筹码增仓 + 机器学习】全量对照回测引擎

实验对照组设计：
1. Baseline V1: 纯原始信号 (固定 2.5 ATR 止损)
2. Filtered V2: 基础三层过滤 (宏观 EMA20 + Squeeze + ADX)
3. Volume-Candlestick V3 (VCP): 大实体突破 + 拒斥影线过滤 + 成交量爆发 (>=1.3x) + 主动增仓确认 (OI Flow) + 动态保本锁定 (Break-Even Lock)
4. ML-Enhanced V4 (VCP + LightGBM): V3 深度形态 + Walk-Forward LightGBM 二阶元概率门控与置信度头寸缩放 (Bet Sizing)
"""

import sys
import sqlite3
import argparse
import warnings
from pathlib import Path
import numpy as np
import pandas as pd
import lightgbm as lgb

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))
sys.path.append(str(PROJECT_ROOT / "code"))

from symbol_strategies.decoupled_symbol_engines import SYMBOL_CONFIGS, DB_PATH
from technical_indicators import calculate_atr, calculate_ema, calculate_adx, calculate_rsi
from strategies.supertrend_strategy import calculate_signal as calc_supertrend_sig
from strategies.alphatrend_strategy import calculate_signal as calc_alphatrend_sig
from strategies.trend_volume_candlestick_master import (
    compute_supertrend_vcp_signals,
    compute_alphatrend_vcp_signals,
    compute_candlestick_patterns,
    compute_volume_oi_features
)

COMMODITY_UNIVERSE = [
    "AU_IDX", "AG_IDX", "SC_IDX", "TA_IDX", "CU_IDX", "RB_IDX", "HC_IDX", "I_IDX",
    "SA_IDX", "MA_IDX", "J_IDX",  "JM_IDX", "AL_IDX", "ZN_IDX", "SN_IDX", "RU_IDX",
    "M_IDX",  "P_IDX",  "LC_IDX", "SR_IDX", "CF_IDX", "FG_IDX", "SI_IDX", "C_IDX",  "Y_IDX"
]


def load_symbol_data(symbol: str, timeframe: str) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(
            "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars "
            "WHERE symbol=? AND timeframe=? ORDER BY trade_time ASC",
            conn, params=(symbol, timeframe)
        )
    if len(df) > 0:
        df["datetime"] = pd.to_datetime(df["trade_time"])
        for col in ["open", "high", "low", "close", "volume", "open_interest"]:
            df[col] = df[col].astype(float)
    return df


def simulate_vcp_strategy(
    df: pd.DataFrame, signals: pd.Series, cfg: dict,
    use_ml_meta: bool = False,
    meta_thresh: float = 0.52,
    enable_be_lock: bool = True,
    chandelier_atr_mult: float = 3.0,
    initial_balance: float = 1000000.0
) -> dict:
    """真实逐 Bar 量价形态趋势撮合仿真引擎 (含动态保本与 ML 概率缩放)"""
    multiplier = cfg.get("multiplier", 10.0)
    tick_size = cfg.get("tick_size", 1.0)
    commission = cfg.get("commission", 3.0)
    max_lots = cfg.get("max_lots", 5)

    n = len(df)
    if n < 50:
        return {"net_profit": 0.0, "trades_count": 0, "win_rate": 0.0, "pl_ratio": 0.0, "max_dd": 0.0, "sharpe": 0.0, "trades": [], "filtered_by_ml": 0}

    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    dts = df["trade_time"].values
    sig_vals = signals.values
    prob_vals = df["meta_prob"].values if "meta_prob" in df.columns else np.full(n, 1.0)
    atr_vals = calculate_atr(df, 14).fillna(method="bfill").values

    pos = 0  # 1=Long, -1=Short, 0=Flat
    lots = 0
    entry_p = 0.0
    entry_dt = ""
    trailing_stop = 0.0
    highest_p = 0.0
    lowest_p = float("inf")
    be_locked = False

    trades = []
    equity_curve = [initial_balance]
    current_equity = initial_balance
    filtered_by_ml = 0

    for i in range(1, n):
        curr_sig = sig_vals[i - 1]
        curr_prob = prob_vals[i - 1]
        curr_open = opens[i]
        curr_high = highs[i]
        curr_low = lows[i]
        curr_atr = max(2.0, atr_vals[i - 1])

        # 1. 持仓出场与动态保本/跟踪止损
        if pos != 0:
            stopped_out = False
            exit_p = curr_open
            exit_reason = ""

            if pos == 1:
                highest_p = max(highest_p, curr_high)
                # 动态保本触发: 浮盈达到 0.7 ATR 时，将止损上移至成本线 + 0.1 ATR
                if enable_be_lock and not be_locked and curr_high >= entry_p + 0.7 * curr_atr:
                    trailing_stop = max(trailing_stop, entry_p + 0.1 * curr_atr)
                    be_locked = True

                # Chandelier 动态跟踪止损
                new_stop = highest_p - chandelier_atr_mult * curr_atr
                trailing_stop = max(trailing_stop, new_stop)

                if curr_low <= trailing_stop:
                    stopped_out = True
                    exit_p = min(curr_open, trailing_stop)
                    exit_reason = "保本止损" if be_locked and exit_p >= entry_p else "Chandelier 跟踪止损"

            elif pos == -1:
                lowest_p = min(lowest_p, curr_low)
                # 动态保本
                if enable_be_lock and not be_locked and curr_low <= entry_p - 0.7 * curr_atr:
                    trailing_stop = min(trailing_stop, entry_p - 0.1 * curr_atr)
                    be_locked = True

                # Chandelier 动态跟踪止损
                new_stop = lowest_p + chandelier_atr_mult * curr_atr
                trailing_stop = min(trailing_stop, new_stop)

                if curr_high >= trailing_stop:
                    stopped_out = True
                    exit_p = max(curr_open, trailing_stop)
                    exit_reason = "保本止损" if be_locked and exit_p <= entry_p else "Chandelier 跟踪止损"

            if stopped_out:
                pnl = (exit_p - entry_p) * multiplier * lots if pos == 1 else (entry_p - exit_p) * multiplier * lots
                pnl -= (commission * lots * 2 + tick_size * multiplier * lots)
                current_equity += pnl
                trades.append({
                    "entry_dt": entry_dt, "exit_dt": dts[i], "side": "LONG" if pos == 1 else "SHORT",
                    "entry_p": entry_p, "exit_p": exit_p, "lots": lots, "pnl": pnl, "reason": exit_reason
                })
                pos = 0
                lots = 0
                be_locked = False

        # 2. 开仓与信号翻转逻辑
        if curr_sig != 0 and ((curr_sig == 1 and pos != 1) or (curr_sig == -1 and pos != -1)):
            # ML Meta-Filter 过滤拦截
            if use_ml_meta and (np.isnan(curr_prob) or curr_prob < meta_thresh):
                filtered_by_ml += 1
            else:
                # 平掉旧仓位
                if pos != 0:
                    exit_p = curr_open + (tick_size if pos == -1 else -tick_size)
                    pnl = ((entry_p - exit_p) if pos == -1 else (exit_p - entry_p)) * multiplier * lots
                    pnl -= (commission * lots + tick_size * multiplier * lots)
                    current_equity += pnl
                    trades.append({
                        "entry_dt": entry_dt, "exit_dt": dts[i], "side": "LONG" if pos == 1 else "SHORT",
                        "entry_p": entry_p, "exit_p": exit_p, "lots": lots, "pnl": pnl, "reason": "信号翻转平仓"
                    })

                # 计算开仓头寸与置信度缩放 (Lopez de Prado Bet Sizing)
                entry_p = curr_open + (tick_size if curr_sig == 1 else -tick_size)
                stop_dist = chandelier_atr_mult * curr_atr
                base_lots = max(1, min(max_lots, int((initial_balance * 0.01) / (stop_dist * multiplier + 1e-6))))

                if use_ml_meta and not np.isnan(curr_prob):
                    bet_scale = max(1.0, min(1.8, 1.0 + (curr_prob - 0.5) * 3.0))
                    calc_lots = max(1, int(base_lots * bet_scale))
                else:
                    calc_lots = base_lots

                pos = curr_sig
                lots = calc_lots
                entry_dt = dts[i]
                highest_p = curr_high if curr_sig == 1 else 0.0
                lowest_p = curr_low if curr_sig == -1 else float("inf")
                trailing_stop = entry_p - stop_dist if curr_sig == 1 else entry_p + stop_dist
                be_locked = False

        # 资金曲线记录
        unrealized = 0.0
        if pos == 1:
            unrealized = (closes[i] - entry_p) * multiplier * lots
        elif pos == -1:
            unrealized = (entry_p - closes[i]) * multiplier * lots
        equity_curve.append(current_equity + unrealized)

    # 统计核心指标
    total_trades = len(trades)
    if total_trades == 0:
        return {"net_profit": 0.0, "trades_count": 0, "win_rate": 0.0, "pl_ratio": 0.0, "max_dd": 0.0, "sharpe": 0.0, "trades": [], "filtered_by_ml": filtered_by_ml}

    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
    win_rate = len(wins) / total_trades * 100.0
    net_profit = sum(t["pnl"] for t in trades)
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = abs(np.mean(losses)) if losses else 1.0
    pl_ratio = (avg_win / avg_loss) if avg_loss > 0 else 99.0

    eq_arr = np.array(equity_curve)
    peaks = np.maximum.accumulate(eq_arr)
    dds = (peaks - eq_arr) / peaks * 100.0
    max_dd = np.max(dds) if len(dds) > 0 else 0.0

    returns = np.diff(eq_arr) / eq_arr[:-1]
    sharpe = (np.mean(returns) / (np.std(returns) + 1e-8)) * np.sqrt(252 * 16) if len(returns) > 10 else 0.0

    return {
        "net_profit": round(net_profit, 2),
        "trades_count": total_trades,
        "win_rate": round(win_rate, 1),
        "pl_ratio": round(pl_ratio, 2),
        "max_dd": round(max_dd, 2),
        "sharpe": round(sharpe, 2),
        "filtered_by_ml": filtered_by_ml,
        "trades": trades
    }


def train_vcp_meta_model(df_feat: pd.DataFrame, sig_col: str, feature_cols: list, train_window: int = 2500, step_size: int = 500) -> np.ndarray:
    """基于量价微观形态特征训练 Walk-Forward LightGBM Meta 模型"""
    n = len(df_feat)
    prob_meta = np.full(n, np.nan)
    high_arr = df_feat["high"].values
    low_arr = df_feat["low"].values
    close_arr = df_feat["close"].values
    atr_arr = df_feat["atr_14"].values
    sigs = df_feat[sig_col].values

    # 1. 生成三连屏障 Meta 标签
    meta_labels = np.full(n, np.nan)
    for i in range(n - 15):
        sig = sigs[i]
        if sig == 0:
            continue
        p0 = close_arr[i]
        atr = max(2.0, float(atr_arr[i]))
        sl = p0 - 2.5 * atr if sig == 1 else p0 + 2.5 * atr

        hit = 0
        for b in range(1, 15):
            h_b, l_b = high_arr[i + b], low_arr[i + b]
            if sig == 1:
                if l_b <= sl:
                    hit = 0
                    break
                if h_b >= p0 + 2.5 * atr:
                    hit = 1
                    break
            else:
                if h_b >= sl:
                    hit = 0
                    break
                if l_b <= p0 - 2.5 * atr:
                    hit = 1
                    break
        meta_labels[i] = hit

    df_feat["vcp_meta_label"] = meta_labels
    valid_idx = np.where(~np.isnan(meta_labels))[0]

    if len(valid_idx) < 10:
        prob_meta[valid_idx] = 0.50
        return prob_meta

    X_all = df_feat[feature_cols].values.astype(np.float32)
    y_all = meta_labels

    current_idx = train_window
    while current_idx < n:
        train_mask = (valid_idx < current_idx)
        train_sample_idx = valid_idx[train_mask]

        if len(train_sample_idx) >= 10 and len(np.unique(y_all[train_sample_idx])) > 1:
            X_tr = X_all[train_sample_idx]
            y_tr = y_all[train_sample_idx].astype(int)

            clf = lgb.LGBMClassifier(
                n_estimators=35, learning_rate=0.03, max_depth=3, num_leaves=6,
                min_child_samples=4, class_weight="balanced", random_state=42, verbose=-1, n_jobs=1
            )
            clf.fit(X_tr, y_tr)

            test_start = current_idx
            test_end = min(n, current_idx + step_size)
            test_mask = (valid_idx >= test_start) & (valid_idx < test_end)
            test_sample_idx = valid_idx[test_mask]

            if len(test_sample_idx) > 0:
                prob_meta[test_sample_idx] = clf.predict_proba(X_all[test_sample_idx])[:, 1]

        current_idx += step_size

    prob_meta[np.isnan(prob_meta) & ~np.isnan(meta_labels)] = 0.50
    return prob_meta


def run_vcp_benchmark(timeframe: str):
    print("\n" + "=" * 155)
    print(f"🔥 【SuperTrend 与 AlphaTrend 量价形态与微观筹码深度进化实证】—— 周期: {timeframe}")
    print("=" * 155)
    print(f"{'品种':<10} | {'-- ST 基线 (V1) --':<24} | {'-- ST量价形态 (V3) -':<24} | {'- ST量价+ML (V4) -':<26} | {'- AT量价+ML (V4) -':<24}")
    print(f"{'':10} | {'净利':>10} {'胜率':>6} {'笔数':>5} | {'净利':>10} {'胜率':>6} {'笔数':>5} | {'净利':>10} {'胜率':>6} {'笔数':>5} {'过滤':>4} | {'净利':>10} {'胜率':>6} {'笔数':>5}")
    print("-" * 155)

    totals = {"st_v1": 0.0, "st_v3": 0.0, "st_v4": 0.0, "at_v4": 0.0}
    trade_counts = {"st_v1": 0, "st_v3": 0, "st_v4": 0, "at_v4": 0}
    st_filtered_total = 0

    feature_cols = [
        "body_ratio", "upper_shadow_ratio", "lower_shadow_ratio", "vol_ratio", "oi_flow", "adx", "squeeze", "macro_trend"
    ]

    for sym in COMMODITY_UNIVERSE:
        df_raw = load_symbol_data(sym, timeframe)
        if len(df_raw) < 100:
            continue

        cfg = SYMBOL_CONFIGS.get(sym, {"name": sym, "multiplier": 10.0})
        name = cfg.get("name", sym)

        # 1. 计算形态与量价特征
        kp = compute_candlestick_patterns(df_raw)
        vp = compute_volume_oi_features(df_raw)
        df_feat = df_raw.copy()
        df_feat["body_ratio"] = kp["body_ratio"]
        df_feat["upper_shadow_ratio"] = kp["upper_shadow_ratio"]
        df_feat["lower_shadow_ratio"] = kp["lower_shadow_ratio"]
        df_feat["vol_ratio"] = vp["vol_ratio"]
        df_feat["oi_flow"] = vp["oi_flow"]
        df_feat["atr_14"] = calculate_atr(df_raw, 14).fillna(method="bfill")
        df_feat["adx"] = calculate_adx(df_raw, 14).fillna(0)

        atr_7 = calculate_atr(df_raw, 7).fillna(method="bfill").values
        atr_28 = calculate_atr(df_raw, 28).fillna(method="bfill").values
        df_feat["squeeze"] = np.where(atr_28 > 0, atr_7 / (atr_28 + 1e-8), 1.0)

        # 宏观趋势
        from run_alphatrend_supertrend_backtest import compute_macro_trend, simulate_trend_strategy_v1
        macro_freq = "120min" if timeframe == "30m" else "60min"
        macro_t = compute_macro_trend(df_raw, macro_freq)
        df_feat["macro_trend"] = macro_t

        # 2. 生成 ST-VCP 与 AT-VCP 信号
        df_st_vcp = compute_supertrend_vcp_signals(df_feat, period=10, multiplier=3.0)
        df_at_vcp = compute_alphatrend_vcp_signals(df_feat, period=14, multiplier=1.618)

        # 3. 运行 V1 基线 (SuperTrend V1)
        st_sig_v1 = calc_supertrend_sig(df_raw, period=10, multiplier=3.0)
        res_st_v1 = simulate_trend_strategy_v1(df_raw, st_sig_v1, cfg)

        # 4. 运行 V3 (纯量价形态确认 + 动态保本)
        res_st_v3 = simulate_vcp_strategy(df_st_vcp, df_st_vcp["st_vcp_sig"], cfg, use_ml_meta=False, enable_be_lock=True)

        # 5. 训练并运行 V4 (量价形态 + Walk-Forward LightGBM)
        prob_st = train_vcp_meta_model(df_st_vcp, "st_vcp_sig", feature_cols, train_window=2500, step_size=500)
        df_st_vcp["meta_prob"] = prob_st
        res_st_v4 = simulate_vcp_strategy(df_st_vcp, df_st_vcp["st_vcp_sig"], cfg, use_ml_meta=True, meta_thresh=0.52, enable_be_lock=True)

        prob_at = train_vcp_meta_model(df_at_vcp, "at_vcp_sig", feature_cols, train_window=2500, step_size=500)
        df_at_vcp["meta_prob"] = prob_at
        res_at_v4 = simulate_vcp_strategy(df_at_vcp, df_at_vcp["at_vcp_sig"], cfg, use_ml_meta=True, meta_thresh=0.52, enable_be_lock=True)

        totals["st_v1"] += res_st_v1["net_profit"]
        totals["st_v3"] += res_st_v3["net_profit"]
        totals["st_v4"] += res_st_v4["net_profit"]
        totals["at_v4"] += res_at_v4["net_profit"]

        trade_counts["st_v1"] += res_st_v1["trades_count"]
        trade_counts["st_v3"] += res_st_v3["trades_count"]
        trade_counts["st_v4"] += res_st_v4["trades_count"]
        trade_counts["at_v4"] += res_at_v4["trades_count"]
        st_filtered_total += res_st_v4.get("filtered_by_ml", 0)

        sym_str = f"{name}({sym[:2]})"
        fmt_v1 = f"¥{res_st_v1['net_profit']:>+8,.0f} {res_st_v1['win_rate']:>5.1f}% {res_st_v1['trades_count']:>4d}"
        fmt_v3 = f"¥{res_st_v3['net_profit']:>+8,.0f} {res_st_v3['win_rate']:>5.1f}% {res_st_v3['trades_count']:>4d}"
        fmt_v4 = f"¥{res_st_v4['net_profit']:>+8,.0f} {res_st_v4['win_rate']:>5.1f}% {res_st_v4['trades_count']:>4d} {res_st_v4['filtered_by_ml']:>4d}"
        fmt_at = f"¥{res_at_v4['net_profit']:>+8,.0f} {res_at_v4['win_rate']:>5.1f}% {res_at_v4['trades_count']:>4d}"

        print(f"{sym_str:<10} | {fmt_v1} | {fmt_v3} | {fmt_v4} | {fmt_at}")

    print("=" * 155)
    print(f"🏆 【{timeframe} 深度量价形态与机器学习进化大盘汇总】:")
    print(f"  1. 原始 SuperTrend 基线 (V1)    : 总净利 ¥{totals['st_v1']:>+12,.2f} | 交易 {trade_counts['st_v1']:>4d} 笔")
    print(f"  2. 量价形态+保本锁定 (ST-VCP V3) : 总净利 ¥{totals['st_v3']:>+12,.2f} | 交易 {trade_counts['st_v3']:>4d} 笔")
    print(f"  3. 量价形态+ML二阶元门控 (ST V4) : 总净利 ¥{totals['st_v4']:>+12,.2f} | 交易 {trade_counts['st_v4']:>4d} 笔 | ML过滤 {st_filtered_total} 笔")
    print(f"  4. 量价形态+ML二阶元门控 (AT V4) : 总净利 ¥{totals['at_v4']:>+12,.2f} | 交易 {trade_counts['at_v4']:>4d} 笔")
    print("=" * 155)

    return {
        "timeframe": timeframe,
        "st_v1": totals["st_v1"], "st_v3": totals["st_v3"],
        "st_v4": totals["st_v4"], "at_v4": totals["at_v4"]
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeframe", type=str, default="all", choices=["10m", "15m", "30m", "all"])
    args = parser.parse_args()

    if args.timeframe == "all":
        results = {}
        for tf in ["10m", "15m", "30m"]:
            results[tf] = run_vcp_benchmark(tf)

        print("\n" + "🔥" * 40)
        print("📊 全周期【量价K线形态+机器学习】跨时代对比总览:")
        for tf, r in results.items():
            print(f"  • {tf:4s}: 原始ST基线 ¥{r['st_v1']:>+11,.0f} -> 量价形态V3 ¥{r['st_v3']:>+11,.0f} -> 量价+ML (ST V4) ¥{r['st_v4']:>+11,.0f} -> (AT V4) ¥{r['at_v4']:>+11,.0f}")
        print("🔥" * 40)
    else:
        run_vcp_benchmark(args.timeframe)
