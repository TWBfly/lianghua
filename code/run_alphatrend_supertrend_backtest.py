"""
code/run_alphatrend_supertrend_backtest.py — AlphaTrend 与 SuperTrend V2 深度优化回测引擎

V2 优化 (三层信号过滤 + Chandelier Exit):
  1. 宏观趋势对齐: 60min/120min EMA(20) 方向，只顺势交易
  2. 波动率挤压门控: ATR(7)/ATR(28) < 0.7 跳过 (低波震荡区)
  3. ADX 趋势强度门控: ADX(14) < 20 无趋势跳过
  4. Chandelier Exit 动态跟踪止损: max(highest) - 2.0*ATR
"""

import os
import sys
import sqlite3
import argparse
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))
sys.path.append(str(PROJECT_ROOT / "code"))

from symbol_strategies.decoupled_symbol_engines import SYMBOL_CONFIGS, DB_PATH
from technical_indicators import calculate_atr, calculate_ema, calculate_adx
from strategies.alphatrend_strategy import calculate_signal as calc_alphatrend_sig
from strategies.supertrend_strategy import calculate_signal as calc_supertrend_sig

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


def compute_macro_trend(df: pd.DataFrame, macro_freq: str = "60min") -> np.ndarray:
    """Resample to macro timeframe and compute EMA(20) trend direction. Returns aligned array: 1=bullish, -1=bearish, 0=neutral."""
    df_ts = df.set_index("datetime").copy()
    df_macro = df_ts.resample(macro_freq).agg({
        "open": "first", "high": "max", "low": "min", "close": "last"
    }).dropna()
    if len(df_macro) < 25:
        return np.zeros(len(df))
    c_macro = df_macro["close"]
    ema20 = calculate_ema(c_macro, 20)
    trend = np.where(c_macro > ema20, 1, np.where(c_macro < ema20, -1, 0))
    df_macro["macro_trend"] = pd.Series(trend, index=df_macro.index).shift(1)  # ponytail: shift(1) zero-lookahead
    aligned = pd.merge_asof(
        df[["datetime"]].copy(), df_macro[["macro_trend"]].reset_index().rename(columns={"index": "datetime"}),
        on="datetime", direction="backward"
    )
    return aligned["macro_trend"].fillna(0).values.astype(int)


def compute_filters(df: pd.DataFrame) -> tuple:
    """Compute squeeze ratio and ADX for signal gating. Returns (squeeze, adx) arrays."""
    atr_7 = calculate_atr(df, 7).fillna(0).values
    atr_28 = calculate_atr(df, 28).fillna(0).values
    squeeze = np.where(atr_28 > 0, atr_7 / atr_28, 1.0)
    adx = calculate_adx(df, 14).fillna(0).values
    return squeeze, adx


def simulate_trend_strategy_v2(
    df: pd.DataFrame, signals: pd.Series, cfg: dict,
    macro_trend: np.ndarray, squeeze: np.ndarray, adx: np.ndarray,
    initial_balance: float = 1000000.0,
    squeeze_thresh: float = 0.7, adx_thresh: float = 20.0,
    chandelier_atr_mult: float = 3.0,
    cooldown_bars: int = 3,
    fixed_stop_atr: float = 0.0  # ponytail: >0 = fixed stop (for AlphaTrend), 0 = Chandelier (for SuperTrend)
) -> dict:
    """V2 趋势回测: 三层过滤 + 可选 Chandelier/固定止损 + 冷却期"""
    multiplier = cfg.get("multiplier", 10.0)
    tick_size = cfg.get("tick_size", 1.0)
    commission_per_lot = cfg.get("commission", 3.0)
    max_lots = cfg.get("max_lots", 5)

    n = len(df)
    if n < 50:
        return {"net_profit": 0.0, "trades_count": 0, "win_rate": 0.0, "pl_ratio": 0.0,
                "max_dd": 0.0, "sharpe": 0.0, "trades": [], "filtered_count": 0}

    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    dts = df["trade_time"].values
    sig_vals = signals.values

    atr_series = calculate_atr(df, 14).bfill().values

    pos = 0
    lots = 0
    entry_p = 0.0
    entry_dt = ""
    trailing_stop = 0.0
    highest_since_entry = 0.0
    lowest_since_entry = float("inf")
    bars_since_exit = 999  # ponytail: cooldown counter, start high to allow first trade

    trades = []
    equity_curve = [initial_balance]
    current_equity = initial_balance
    filtered_count = 0

    for i in range(1, n):
        curr_sig = sig_vals[i - 1]  # ponytail: zero-lookahead
        curr_open = opens[i]
        curr_high = highs[i]
        curr_low = lows[i]
        curr_atr = max(2.0, atr_series[i - 1])

        if pos == 0:
            bars_since_exit += 1

        # 1. 止损检查 (fixed_stop_atr>0: 固定止损, else: Chandelier Exit 跟踪止损)
        if pos != 0:
            use_chandelier = fixed_stop_atr <= 0
            if use_chandelier:
                # Chandelier: update trailing extremes BEFORE checking stop
                if pos == 1:
                    highest_since_entry = max(highest_since_entry, curr_high)
                    new_stop = highest_since_entry - chandelier_atr_mult * curr_atr
                    trailing_stop = max(trailing_stop, new_stop)
                else:
                    lowest_since_entry = min(lowest_since_entry, curr_low)
                    new_stop = lowest_since_entry + chandelier_atr_mult * curr_atr
                    trailing_stop = min(trailing_stop, new_stop)

            stopped_out = False
            exit_p = curr_open
            if pos == 1 and curr_low <= trailing_stop:
                stopped_out = True
                exit_p = min(curr_open, trailing_stop)
            elif pos == -1 and curr_high >= trailing_stop:
                stopped_out = True
                exit_p = max(curr_open, trailing_stop)

            if stopped_out:
                pnl = (exit_p - entry_p) * multiplier * lots if pos == 1 else (entry_p - exit_p) * multiplier * lots
                pnl -= (commission_per_lot * lots * 2 + tick_size * multiplier * lots)
                current_equity += pnl
                stop_type = "Chandelier Exit 跟踪止损" if use_chandelier else "固定 ATR 硬止损"
                trades.append({
                    "entry_dt": entry_dt, "exit_dt": dts[i], "side": "LONG" if pos == 1 else "SHORT",
                    "entry_p": entry_p, "exit_p": exit_p, "lots": lots, "pnl": pnl, "reason": stop_type
                })
                pos = 0
                lots = 0
                bars_since_exit = 0

        # 2. 三层过滤 + 冷却期 + 信号翻转
        if curr_sig != 0 and ((curr_sig == 1 and pos != 1) or (curr_sig == -1 and pos != -1)):
            # Filter 0: 冷却期 — 止损出场后等待 N 根 Bar 避免whipsaw
            if pos == 0 and bars_since_exit < cooldown_bars:
                filtered_count += 1
            else:
                # Filter 1: 宏观趋势对齐 — 严格顺势 (neutral=0 不开仓)
                macro_ok = (curr_sig == 1 and macro_trend[i - 1] == 1) or (curr_sig == -1 and macro_trend[i - 1] == -1)
                # Filter 2: 波动率挤压门控
                squeeze_ok = squeeze[i - 1] >= squeeze_thresh
                # Filter 3: ADX 趋势强度门控
                adx_ok = adx[i - 1] >= adx_thresh

                if not (macro_ok and squeeze_ok and adx_ok):
                    filtered_count += 1
                    # Close existing position on reverse signal even if new direction filtered
                    if pos != 0 and ((curr_sig == 1 and pos == -1) or (curr_sig == -1 and pos == 1)):
                        exit_p = curr_open + (tick_size if pos == -1 else -tick_size)
                        pnl = ((entry_p - exit_p) if pos == -1 else (exit_p - entry_p)) * multiplier * lots
                        pnl -= (commission_per_lot * lots + tick_size * multiplier * lots)
                        current_equity += pnl
                        trades.append({
                            "entry_dt": entry_dt, "exit_dt": dts[i],
                            "side": "LONG" if pos == 1 else "SHORT",
                            "entry_p": entry_p, "exit_p": exit_p, "lots": lots, "pnl": pnl,
                            "reason": "反向信号平仓(新方向被过滤)"
                        })
                        pos = 0
                        lots = 0
                        bars_since_exit = 0
                else:
                    # All filters pass — execute
                    if pos != 0:
                        exit_p = curr_open + (tick_size if pos == -1 else -tick_size)
                        pnl = ((entry_p - exit_p) if pos == -1 else (exit_p - entry_p)) * multiplier * lots
                        pnl -= (commission_per_lot * lots + tick_size * multiplier * lots)
                        current_equity += pnl
                        trades.append({
                            "entry_dt": entry_dt, "exit_dt": dts[i],
                            "side": "LONG" if pos == 1 else "SHORT",
                            "entry_p": entry_p, "exit_p": exit_p, "lots": lots, "pnl": pnl,
                            "reason": "信号翻转平仓"
                        })

                    entry_p = curr_open + (tick_size if curr_sig == 1 else -tick_size)
                    stop_mult = fixed_stop_atr if fixed_stop_atr > 0 else chandelier_atr_mult
                    risk_per_share = stop_mult * curr_atr
                    calc_lots = max(1, min(max_lots, int((initial_balance * 0.01) / (risk_per_share * multiplier + 1e-6))))
                    pos = curr_sig
                    lots = calc_lots
                    entry_dt = dts[i]
                    highest_since_entry = curr_high if curr_sig == 1 else 0.0
                    lowest_since_entry = curr_low if curr_sig == -1 else float("inf")
                    trailing_stop = entry_p - stop_mult * curr_atr if curr_sig == 1 else entry_p + stop_mult * curr_atr

        # Equity curve
        unrealized = 0.0
        if pos == 1:
            unrealized = (closes[i] - entry_p) * multiplier * lots
        elif pos == -1:
            unrealized = (entry_p - closes[i]) * multiplier * lots
        equity_curve.append(current_equity + unrealized)

    # Stats
    total_trades = len(trades)
    if total_trades == 0:
        return {"net_profit": 0.0, "trades_count": 0, "win_rate": 0.0, "pl_ratio": 0.0,
                "max_dd": 0.0, "sharpe": 0.0, "trades": [], "filtered_count": filtered_count}

    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
    win_rate = len(wins) / total_trades * 100.0
    net_profit = sum(t["pnl"] for t in trades)
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = abs(np.mean(losses)) if losses else 1.0
    pl_ratio = (avg_win / avg_loss) if avg_loss > 0 else (99.0 if wins else 0.0)

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
        "trades": trades,
        "filtered_count": filtered_count
    }


# ponytail: keep V1 simulate for baseline comparison, minimal copy
def simulate_trend_strategy_v1(df, signals, cfg, initial_balance=1000000.0):
    """V1 baseline: fixed 2.5 ATR hard stop, no filtering."""
    multiplier = cfg.get("multiplier", 10.0)
    tick_size = cfg.get("tick_size", 1.0)
    commission_per_lot = cfg.get("commission", 3.0)
    max_lots = cfg.get("max_lots", 5)
    n = len(df)
    if n < 50:
        return {"net_profit": 0.0, "trades_count": 0, "win_rate": 0.0, "pl_ratio": 0.0, "max_dd": 0.0}

    opens, highs, lows, closes = df["open"].values, df["high"].values, df["low"].values, df["close"].values
    dts, sig_vals = df["trade_time"].values, signals.values
    atr_series = calculate_atr(df, 14).bfill().values

    pos = lots = 0
    entry_p = stop_loss = 0.0
    entry_dt = ""
    trades = []
    equity_curve = [initial_balance]
    current_equity = initial_balance

    for i in range(1, n):
        curr_sig = sig_vals[i - 1]
        curr_open, curr_high, curr_low = opens[i], highs[i], lows[i]
        curr_atr = max(2.0, atr_series[i - 1])

        if pos != 0:
            stopped = False
            exit_p = curr_open
            if pos == 1 and curr_low <= stop_loss:
                stopped, exit_p = True, min(curr_open, stop_loss)
            elif pos == -1 and curr_high >= stop_loss:
                stopped, exit_p = True, max(curr_open, stop_loss)
            if stopped:
                pnl = ((exit_p - entry_p) if pos == 1 else (entry_p - exit_p)) * multiplier * lots
                pnl -= (commission_per_lot * lots * 2 + tick_size * multiplier * lots)
                current_equity += pnl
                trades.append({"pnl": pnl})
                pos = lots = 0

        if curr_sig == 1 and pos != 1:
            if pos == -1:
                pnl = (entry_p - curr_open - tick_size) * multiplier * lots - (commission_per_lot * lots + tick_size * multiplier * lots)
                current_equity += pnl
                trades.append({"pnl": pnl})
            entry_p = curr_open + tick_size
            lots = max(1, min(max_lots, int((initial_balance * 0.01) / (2.0 * curr_atr * multiplier + 1e-6))))
            pos, stop_loss = 1, entry_p - 2.5 * curr_atr
        elif curr_sig == -1 and pos != -1:
            if pos == 1:
                pnl = (curr_open - tick_size - entry_p) * multiplier * lots - (commission_per_lot * lots + tick_size * multiplier * lots)
                current_equity += pnl
                trades.append({"pnl": pnl})
            entry_p = curr_open - tick_size
            lots = max(1, min(max_lots, int((initial_balance * 0.01) / (2.0 * curr_atr * multiplier + 1e-6))))
            pos, stop_loss = -1, entry_p + 2.5 * curr_atr

        unrealized = ((closes[i] - entry_p) if pos == 1 else (entry_p - closes[i]) if pos == -1 else 0.0) * multiplier * lots
        equity_curve.append(current_equity + unrealized)

    total = len(trades)
    if total == 0:
        return {"net_profit": 0.0, "trades_count": 0, "win_rate": 0.0, "pl_ratio": 0.0, "max_dd": 0.0}
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
    net = sum(t["pnl"] for t in trades)
    wr = len(wins) / total * 100.0
    avg_w = np.mean(wins) if wins else 0.0
    avg_l = abs(np.mean(losses)) if losses else 1.0
    plr = (avg_w / avg_l) if avg_l > 0 else 0.0
    eq = np.array(equity_curve)
    pk = np.maximum.accumulate(eq)
    mdd = np.max((pk - eq) / pk * 100.0)
    return {"net_profit": round(net, 2), "trades_count": total, "win_rate": round(wr, 1), "pl_ratio": round(plr, 2), "max_dd": round(mdd, 2)}


def run_benchmark_comparison(timeframe: str):
    macro_freq = "120min" if timeframe == "30m" else "60min"

    print("\n" + "=" * 140)
    print(f"📊 【AlphaTrend vs SuperTrend】V1 Baseline vs V2 深度优化 实证对决 —— 周期: {timeframe} | 宏观对齐: {macro_freq}")
    print("=" * 140)
    print(f"{'品种':<10} | {'------- AlphaTrend V1 -------':<30} | {'------- AlphaTrend V2 -------':<30} | {'------- SuperTrend V1 -------':<30} | {'------- SuperTrend V2 -------':<30}")
    print(f"{'':10} | {'净利':>12} {'胜率':>6} {'盈亏比':>6} {'笔数':>5} | {'净利':>12} {'胜率':>6} {'盈亏比':>6} {'笔数':>5} | {'净利':>12} {'胜率':>6} {'盈亏比':>6} {'笔数':>5} | {'净利':>12} {'胜率':>6} {'盈亏比':>6} {'笔数':>5}")
    print("-" * 140)

    totals = {"at_v1": 0.0, "at_v2": 0.0, "st_v1": 0.0, "st_v2": 0.0}
    trade_counts = {"at_v1": 0, "at_v2": 0, "st_v1": 0, "st_v2": 0}
    filtered_counts = {"at": 0, "st": 0}

    for sym in COMMODITY_UNIVERSE:
        df = load_symbol_data(sym, timeframe)
        if len(df) < 100:
            continue

        cfg = SYMBOL_CONFIGS.get(sym, {"name": sym, "multiplier": 10.0})
        name = cfg.get("name", sym)

        # Compute shared filters once
        macro_trend = compute_macro_trend(df, macro_freq)
        squeeze, adx = compute_filters(df)

        # AlphaTrend — ponytail: fixed stop preserves its delay-crossover exit architecture
        at_sig = calc_alphatrend_sig(df, period=14, multiplier=1.618)
        at_v1 = simulate_trend_strategy_v1(df, at_sig, cfg)
        at_v2 = simulate_trend_strategy_v2(df, at_sig, cfg, macro_trend, squeeze, adx, fixed_stop_atr=2.5)

        # SuperTrend — Chandelier Exit works well with state-machine flips
        st_sig = calc_supertrend_sig(df, period=10, multiplier=3.0)
        st_v1 = simulate_trend_strategy_v1(df, st_sig, cfg)
        st_v2 = simulate_trend_strategy_v2(df, st_sig, cfg, macro_trend, squeeze, adx)

        totals["at_v1"] += at_v1["net_profit"]
        totals["at_v2"] += at_v2["net_profit"]
        totals["st_v1"] += st_v1["net_profit"]
        totals["st_v2"] += st_v2["net_profit"]
        trade_counts["at_v1"] += at_v1["trades_count"]
        trade_counts["at_v2"] += at_v2["trades_count"]
        trade_counts["st_v1"] += st_v1["trades_count"]
        trade_counts["st_v2"] += st_v2["trades_count"]
        filtered_counts["at"] += at_v2.get("filtered_count", 0)
        filtered_counts["st"] += st_v2.get("filtered_count", 0)

        sym_str = f"{name}({sym[:2]})"
        def fmt(r):
            return f"¥{r['net_profit']:>+10,.0f} {r['win_rate']:>5.1f}% {r['pl_ratio']:>5.2f} {r['trades_count']:>5d}"
        print(f"{sym_str:<10} | {fmt(at_v1)} | {fmt(at_v2)} | {fmt(st_v1)} | {fmt(st_v2)}")

    print("=" * 140)
    print(f"🏆 【{timeframe} 汇总】:")
    print(f"  AlphaTrend V1: 总净利 ¥{totals['at_v1']:>+12,.2f} | {trade_counts['at_v1']} 笔")
    print(f"  AlphaTrend V2: 总净利 ¥{totals['at_v2']:>+12,.2f} | {trade_counts['at_v2']} 笔 | 过滤 {filtered_counts['at']} 笔")
    v2_improve_at = totals['at_v2'] - totals['at_v1']
    print(f"  → V2 改善: ¥{v2_improve_at:>+12,.2f}")
    print()
    print(f"  SuperTrend V1: 总净利 ¥{totals['st_v1']:>+12,.2f} | {trade_counts['st_v1']} 笔")
    print(f"  SuperTrend V2: 总净利 ¥{totals['st_v2']:>+12,.2f} | {trade_counts['st_v2']} 笔 | 过滤 {filtered_counts['st']} 笔")
    v2_improve_st = totals['st_v2'] - totals['st_v1']
    print(f"  → V2 改善: ¥{v2_improve_st:>+12,.2f}")
    print("=" * 140)

    return {
        "timeframe": timeframe,
        "at_v1_pnl": totals["at_v1"], "at_v2_pnl": totals["at_v2"],
        "st_v1_pnl": totals["st_v1"], "st_v2_pnl": totals["st_v2"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeframe", type=str, default="all", choices=["10m", "15m", "30m", "all"])
    args = parser.parse_args()

    if args.timeframe == "all":
        results = {}
        for tf in ["10m", "15m", "30m"]:
            results[tf] = run_benchmark_comparison(tf)
        # Final cross-timeframe summary
        print("\n" + "🔥" * 35)
        print("📊 全周期 V1→V2 改善总览:")
        for tf, r in results.items():
            print(f"  {tf}: AT V1 ¥{r['at_v1_pnl']:>+12,.0f} → V2 ¥{r['at_v2_pnl']:>+12,.0f} (Δ ¥{r['at_v2_pnl']-r['at_v1_pnl']:>+12,.0f})"
                  f"  |  ST V1 ¥{r['st_v1_pnl']:>+12,.0f} → V2 ¥{r['st_v2_pnl']:>+12,.0f} (Δ ¥{r['st_v2_pnl']-r['st_v1_pnl']:>+12,.0f})")
        print("🔥" * 35)
    else:
        run_benchmark_comparison(args.timeframe)
