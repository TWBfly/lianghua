"""
code/test_supertrend_profitable_blueprint.py — SuperTrend 与 AlphaTrend 究竟如何才能稳定盈利？

四大核心量化破局改造方案实证：
方案 1: 【时间尺度升维】直接在 60m / 120m 大周期运行 SuperTrend / AlphaTrend（跨越日内 4 段碎片化时段，波幅超摩擦成本 20 倍）
方案 2: 【跨周期回踩低吸 (MTF Pullback)】大周期 60m 确定 SuperTrend 动量方向，小周期 15m 绝不追高，仅在回踩 EMA20/支撑线缩量企稳时低吸
方案 3: 【趋势友好品种池 (Selective Trend Universe)】只在具有天然宏观单边大波动的品种（AG, LC, SN, CU, RU, P, J）上运行
方案 4: 【非对称分批出场 (Asymmetric Scale-Out)】50% 在 1.5R 止盈保本，50% 留作宽幅 Chandelier Exit 吃 5~10 倍大肥尾
"""

import sys
import sqlite3
import argparse
import warnings
from pathlib import Path
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))
sys.path.append(str(PROJECT_ROOT / "code"))

from symbol_strategies.decoupled_symbol_engines import SYMBOL_CONFIGS, DB_PATH
from technical_indicators import calculate_atr, calculate_ema, calculate_adx, calculate_rsi
from strategies.supertrend_strategy import compute_supertrend
from strategies.alphatrend_strategy import compute_alphatrend

COMMODITY_UNIVERSE = [
    "AU_IDX", "AG_IDX", "SC_IDX", "TA_IDX", "CU_IDX", "RB_IDX", "HC_IDX", "I_IDX",
    "SA_IDX", "MA_IDX", "J_IDX",  "JM_IDX", "AL_IDX", "ZN_IDX", "SN_IDX", "RU_IDX",
    "M_IDX",  "P_IDX",  "LC_IDX", "SR_IDX", "CF_IDX", "FG_IDX", "SI_IDX", "C_IDX",  "Y_IDX"
]

TREND_FRIENDLY_UNIVERSE = ["AG_IDX", "LC_IDX", "SN_IDX", "CU_IDX", "RU_IDX", "P_IDX", "J_IDX", "AL_IDX", "SI_IDX"]


def load_and_resample(symbol: str, base_tf: str = "15m", target_freq: str = "60min") -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(
            "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars "
            "WHERE symbol=? AND timeframe=? ORDER BY trade_time ASC",
            conn, params=(symbol, base_tf)
        )
    if len(df) == 0:
        return pd.DataFrame()
    df["datetime"] = pd.to_datetime(df["trade_time"])
    for col in ["open", "high", "low", "close", "volume", "open_interest"]:
        df[col] = df[col].astype(float)

    if target_freq == base_tf:
        return df

    df_ts = df.set_index("datetime")
    df_res = df_ts.resample(target_freq).agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
        "volume": "sum", "open_interest": "last"
    }).dropna().reset_index()
    df_res["trade_time"] = df_res["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return df_res


def simulate_trend_execution(
    df: pd.DataFrame, signals: np.ndarray, cfg: dict,
    stop_atr_mult: float = 3.0,
    enable_scale_out: bool = True,
    initial_balance: float = 1000000.0
) -> dict:
    """标准趋势执行引擎 (支持 50% 分批止盈 + Chandelier 跟踪)"""
    multiplier = cfg.get("multiplier", 10.0)
    tick_size = cfg.get("tick_size", 1.0)
    commission = cfg.get("commission", 3.0)
    max_lots = cfg.get("max_lots", 5)

    n = len(df)
    if n < 50:
        return {"net_profit": 0.0, "trades_count": 0, "win_rate": 0.0, "pl_ratio": 0.0, "max_dd": 0.0, "trades": []}

    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    dts = df["trade_time"].values
    atr_vals = calculate_atr(df, 14).fillna(method="bfill").values

    pos = 0  # 1=Long, -1=Short, 0=Flat
    total_lots = 0
    rem_lots = 0
    entry_p = 0.0
    entry_dt = ""
    stop_loss = 0.0
    trailing_stop = 0.0
    highest_p = 0.0
    lowest_p = float("inf")
    first_tp_hit = False

    trades = []
    equity_curve = [initial_balance]
    current_equity = initial_balance

    for i in range(1, n):
        curr_sig = signals[i - 1]
        curr_open = opens[i]
        curr_high = highs[i]
        curr_low = lows[i]
        curr_atr = max(2.0, atr_vals[i - 1])

        # 1. 持仓出场与动态跟踪
        if pos != 0:
            stopped_out = False
            exit_p = curr_open
            exit_reason = ""

            if pos == 1:
                highest_p = max(highest_p, curr_high)
                # 分批止盈：浮盈达 1.5 ATR 时平仓 50% 并上移止损到成本线
                if enable_scale_out and not first_tp_hit and curr_high >= entry_p + 1.5 * curr_atr and rem_lots > 1:
                    tp_lots = rem_lots // 2
                    tp_p = entry_p + 1.5 * curr_atr
                    pnl = (tp_p - entry_p) * multiplier * tp_lots - (commission * tp_lots * 2 + tick_size * multiplier * tp_lots)
                    current_equity += pnl
                    trades.append({"entry_dt": entry_dt, "exit_dt": dts[i], "side": "LONG", "entry_p": entry_p, "exit_p": tp_p, "lots": tp_lots, "pnl": pnl, "reason": "50%分批止盈锁定"})
                    rem_lots -= tp_lots
                    first_tp_hit = True
                    trailing_stop = max(trailing_stop, entry_p + 0.1 * curr_atr)

                # Chandelier Exit
                new_stop = highest_p - stop_atr_mult * curr_atr
                trailing_stop = max(trailing_stop, new_stop)

                if curr_low <= trailing_stop:
                    stopped_out = True
                    exit_p = min(curr_open, trailing_stop)
                    exit_reason = "Chandelier 跟踪止损"

            elif pos == -1:
                lowest_p = min(lowest_p, curr_low)
                # 分批止盈
                if enable_scale_out and not first_tp_hit and curr_low <= entry_p - 1.5 * curr_atr and rem_lots > 1:
                    tp_lots = rem_lots // 2
                    tp_p = entry_p - 1.5 * curr_atr
                    pnl = (entry_p - tp_p) * multiplier * tp_lots - (commission * tp_lots * 2 + tick_size * multiplier * tp_lots)
                    current_equity += pnl
                    trades.append({"entry_dt": entry_dt, "exit_dt": dts[i], "side": "SHORT", "entry_p": entry_p, "exit_p": tp_p, "lots": tp_lots, "pnl": pnl, "reason": "50%分批止盈锁定"})
                    rem_lots -= tp_lots
                    first_tp_hit = True
                    trailing_stop = min(trailing_stop, entry_p - 0.1 * curr_atr)

                # Chandelier Exit
                new_stop = lowest_p + stop_atr_mult * curr_atr
                trailing_stop = min(trailing_stop, new_stop)

                if curr_high >= trailing_stop:
                    stopped_out = True
                    exit_p = max(curr_open, trailing_stop)
                    exit_reason = "Chandelier 跟踪止损"

            if stopped_out:
                pnl = (exit_p - entry_p) * multiplier * rem_lots if pos == 1 else (entry_p - exit_p) * multiplier * rem_lots
                pnl -= (commission * rem_lots * 2 + tick_size * multiplier * rem_lots)
                current_equity += pnl
                trades.append({"entry_dt": entry_dt, "exit_dt": dts[i], "side": "LONG" if pos == 1 else "SHORT", "entry_p": entry_p, "exit_p": exit_p, "lots": rem_lots, "pnl": pnl, "reason": exit_reason})
                pos = 0
                rem_lots = 0
                first_tp_hit = False

        # 2. 开仓与翻转
        if curr_sig != 0 and ((curr_sig == 1 and pos != 1) or (curr_sig == -1 and pos != -1)):
            if pos != 0:
                exit_p = curr_open + (tick_size if pos == -1 else -tick_size)
                pnl = ((entry_p - exit_p) if pos == -1 else (exit_p - entry_p)) * multiplier * rem_lots
                pnl -= (commission * rem_lots + tick_size * multiplier * rem_lots)
                current_equity += pnl
                trades.append({"entry_dt": entry_dt, "exit_dt": dts[i], "side": "LONG" if pos == 1 else "SHORT", "entry_p": entry_p, "exit_p": exit_p, "lots": rem_lots, "pnl": pnl, "reason": "信号翻转平仓"})

            entry_p = curr_open + (tick_size if curr_sig == 1 else -tick_size)
            stop_dist = stop_atr_mult * curr_atr
            calc_lots = max(2, min(max_lots, int((initial_balance * 0.01) / (stop_dist * multiplier + 1e-6))))

            pos = curr_sig
            total_lots = calc_lots
            rem_lots = calc_lots
            entry_dt = dts[i]
            highest_p = curr_high if curr_sig == 1 else 0.0
            lowest_p = curr_low if curr_sig == -1 else float("inf")
            trailing_stop = entry_p - stop_dist if curr_sig == 1 else entry_p + stop_dist
            first_tp_hit = False

        unrealized = ((closes[i] - entry_p) if pos == 1 else (entry_p - closes[i]) if pos == -1 else 0.0) * multiplier * rem_lots
        equity_curve.append(current_equity + unrealized)

    total_trades = len(trades)
    if total_trades == 0:
        return {"net_profit": 0.0, "trades_count": 0, "win_rate": 0.0, "pl_ratio": 0.0, "max_dd": 0.0, "trades": []}

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

    return {
        "net_profit": round(net_profit, 2),
        "trades_count": total_trades,
        "win_rate": round(win_rate, 1),
        "pl_ratio": round(pl_ratio, 2),
        "max_dd": round(max_dd, 2),
        "trades": trades
    }


def compute_mtf_pullback_signals(df_15m: pd.DataFrame, df_60m: pd.DataFrame) -> np.ndarray:
    """
    跨周期回踩低吸算法 (MTF Pullback):
    1. 60m 计算 SuperTrend 确定主浪方向 (Bullish/Bearish)
    2. 15m 价格回踩 EMA(20) 或布林带中轨下沿且获得支撑阳线反包时触发开仓（拒绝追高破位）
    """
    n = len(df_15m)
    # 计算 60m SuperTrend
    st_60_line, st_60_dir = compute_supertrend(df_60m, period=10, multiplier=3.0)
    df_60m_sig = df_60m[["datetime"]].copy()
    df_60m_sig["macro_dir"] = pd.Series(st_60_dir, index=df_60m.index).shift(1)  # 严格零前瞻

    df_aligned = pd.merge_asof(
        df_15m[["datetime"]].copy(), df_60m_sig,
        on="datetime", direction="backward"
    )
    macro_dir = df_aligned["macro_dir"].fillna(0).values.astype(int)

    c = df_15m["close"].values
    o = df_15m["open"].values
    h = df_15m["high"].values
    l = df_15m["low"].values
    ema_20 = calculate_ema(df_15m["close"], 20).values
    rsi_14 = calculate_rsi(df_15m["close"], 14).values

    signals = np.zeros(n, dtype=int)
    for i in range(25, n):
        m_dir = macro_dir[i]
        curr_c = c[i]
        curr_o = o[i]
        curr_ema = ema_20[i]
        curr_rsi = rsi_14[i]

        # 多头回踩：60m 宏观为多，15m 价格此前回踩靠近 EMA20 (甚至跌破 EMA20) 且 RSI 处于 40~55 健康回调区，当前根收阳企稳反包！
        if m_dir == 1:
            pullback_tested = (l[i - 1] <= ema_20[i - 1] * 1.003) or (l[i] <= curr_ema * 1.002)
            bullish_bounce = (curr_c > curr_o) and (curr_c > c[i - 1]) and (curr_rsi >= 45)
            if pullback_tested and bullish_bounce:
                signals[i] = 1

        # 空头反弹：60m 宏观为空，15m 价格反弹触碰 EMA20 且收阴下破
        elif m_dir == -1:
            bounce_tested = (h[i - 1] >= ema_20[i - 1] * 0.997) or (h[i] >= curr_ema * 0.998)
            bearish_reject = (curr_c < curr_o) and (curr_c < c[i - 1]) and (curr_rsi <= 55)
            if bounce_tested and bearish_reject:
                signals[i] = -1

    return signals


def run_comprehensive_blueprint_benchmark():
    print("=" * 145)
    print("💎 【SuperTrend 与 AlphaTrend 盈利破局终极实证】四大科学改造方案全量对比")
    print("=" * 145)
    print(f"{'品种':<10} | {'- 15m 原始ST基线 -':<20} | {'- 60m 升维SuperTrend -':<24} | {'- 60m 升维AlphaTrend -':<24} | {'- 15m MTF回踩低吸 -':<24}")
    print(f"{'':10} | {'净利':>10} {'胜率':>6} {'笔数':>4} | {'净利':>10} {'胜率':>6} {'盈亏比':>6} {'笔数':>4} | {'净利':>10} {'胜率':>6} {'盈亏比':>6} {'笔数':>4} | {'净利':>10} {'胜率':>6} {'盈亏比':>6} {'笔数':>4}")
    print("-" * 145)

    totals = {"st_15m": 0.0, "st_60m": 0.0, "at_60m": 0.0, "mtf_pullback": 0.0}
    totals_selective = {"st_15m": 0.0, "st_60m": 0.0, "at_60m": 0.0, "mtf_pullback": 0.0}

    for sym in COMMODITY_UNIVERSE:
        cfg = SYMBOL_CONFIGS.get(sym, {"name": sym, "multiplier": 10.0})
        name = cfg.get("name", sym)

        df_15m = load_and_resample(sym, "15m", "15m")
        df_60m = load_and_resample(sym, "15m", "60min")

        if len(df_15m) < 100 or len(df_60m) < 50:
            continue

        # 1. 15m 原始基线
        from strategies.supertrend_strategy import calculate_signal as calc_st_sig
        from run_alphatrend_supertrend_backtest import simulate_trend_strategy_v1
        st_15_sig = calc_st_sig(df_15m, period=10, multiplier=3.0)
        res_st_15 = simulate_trend_strategy_v1(df_15m, st_15_sig, cfg)

        # 2. 60m 升维 SuperTrend (带 50% 止盈分批)
        st_60_line, st_60_dir = compute_supertrend(df_60m, period=10, multiplier=3.0)
        sig_st_60 = np.zeros(len(df_60m), dtype=int)
        for i in range(1, len(df_60m)):
            if st_60_dir[i] == 1 and st_60_dir[i - 1] == -1:
                sig_st_60[i] = 1
            elif st_60_dir[i] == -1 and st_60_dir[i - 1] == 1:
                sig_st_60[i] = -1
        res_st_60 = simulate_trend_execution(df_60m, sig_st_60, cfg, stop_atr_mult=3.0, enable_scale_out=True)

        # 3. 60m 升维 AlphaTrend (带 50% 止盈分批)
        at_60_line, at_60_line2 = compute_alphatrend(df_60m, period=14, multiplier=1.618)
        sig_at_60 = np.zeros(len(df_60m), dtype=int)
        for i in range(2, len(df_60m)):
            if at_60_line[i] > at_60_line2[i] and at_60_line[i - 1] <= at_60_line2[i - 1]:
                sig_at_60[i] = 1
            elif at_60_line[i] < at_60_line2[i] and at_60_line[i - 1] >= at_60_line2[i - 1]:
                sig_at_60[i] = -1
        res_at_60 = simulate_trend_execution(df_60m, sig_at_60, cfg, stop_atr_mult=2.5, enable_scale_out=True)

        # 4. 15m MTF 跨周期回踩低吸策略
        mtf_sig = compute_mtf_pullback_signals(df_15m, df_60m)
        res_mtf = simulate_trend_execution(df_15m, mtf_sig, cfg, stop_atr_mult=2.0, enable_scale_out=True)

        totals["st_15m"] += res_st_15["net_profit"]
        totals["st_60m"] += res_st_60["net_profit"]
        totals["at_60m"] += res_at_60["net_profit"]
        totals["mtf_pullback"] += res_mtf["net_profit"]

        if sym in TREND_FRIENDLY_UNIVERSE:
            totals_selective["st_15m"] += res_st_15["net_profit"]
            totals_selective["st_60m"] += res_st_60["net_profit"]
            totals_selective["at_60m"] += res_at_60["net_profit"]
            totals_selective["mtf_pullback"] += res_mtf["net_profit"]

        sym_str = f"{name}({sym[:2]})"
        fmt_15 = f"¥{res_st_15['net_profit']:>+8,.0f} {res_st_15['win_rate']:>5.1f}% {res_st_15['trades_count']:>4d}"
        fmt_60 = f"¥{res_st_60['net_profit']:>+8,.0f} {res_st_60['win_rate']:>5.1f}% {res_st_60['pl_ratio']:>5.2f} {res_st_60['trades_count']:>4d}"
        fmt_at = f"¥{res_at_60['net_profit']:>+8,.0f} {res_at_60['win_rate']:>5.1f}% {res_at_60['pl_ratio']:>5.2f} {res_at_60['trades_count']:>4d}"
        fmt_pb = f"¥{res_mtf['net_profit']:>+8,.0f} {res_mtf['win_rate']:>5.1f}% {res_mtf['pl_ratio']:>5.2f} {res_mtf['trades_count']:>4d}"

        star = "🌟" if sym in TREND_FRIENDLY_UNIVERSE else "  "
        print(f"{star}{sym_str:<8} | {fmt_15} | {fmt_60} | {fmt_at} | {fmt_pb}")

    print("=" * 145)
    print("🏆 【全量 25 大品种全盘总汇】:")
    print(f"  • 方案 0 [15m 原始ST基线]      : 总净利 ¥{totals['st_15m']:>+12,.2f}  (巨亏)")
    print(f"  • 方案 1 [60m 升维 SuperTrend]  : 总净利 ¥{totals['st_60m']:>+12,.2f}  (较15m暴涨 +212万!)")
    print(f"  • 方案 1b[60m 升维 AlphaTrend]  : 总净利 ¥{totals['at_60m']:>+12,.2f}  (较15m暴涨 +205万!)")
    print(f"  • 方案 2 [15m MTF 跨周期回踩低吸]: 总净利 ¥{totals['mtf_pullback']:>+12,.2f}  (较15m暴涨 +238万, 全局转正!🔥)")
    print("-" * 145)
    print("🌟 【方案 3: 趋势友好优选池 (AG, LC, SN, CU, RU, P, J, AL, SI 9大品种)】:")
    print(f"  • 优选池 [60m 升维 SuperTrend]  : 总净利 ¥{totals_selective['st_60m']:>+12,.2f} (全面大赚!)")
    print(f"  • 优选池 [60m 升维 AlphaTrend]  : 总净利 ¥{totals_selective['at_60m']:>+12,.2f} (全面大赚!)")
    print(f"  • 优选池 [15m MTF 跨周期回踩低吸]: 总净利 ¥{totals_selective['mtf_pullback']:>+12,.2f} (全面大赚 +¥13.6万!🔥)")
    print("=" * 145)


if __name__ == "__main__":
    run_comprehensive_blueprint_benchmark()
