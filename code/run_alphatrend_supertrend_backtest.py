"""
code/run_alphatrend_supertrend_backtest.py — AlphaTrend 与 SuperTrend 25 大主力期货全量多周期实证对决回测引擎

涵盖周期: 10m, 15m, 30m
数据源: SQLite futures_min_bars (严格校准北京时间, 8000 根纯净 Bar)
执行逻辑:
- 严格零前瞻事件驱动 (Bar Close 产生信号, Next Bar Open 撮合)
- 真实滑点 1 Tick + 交易所手续费
- 逐日 MTM 盯市与资金曲线、最大回撤、盈亏比计算
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
from technical_indicators import calculate_atr
from strategies.alphatrend_strategy import compute_alphatrend, calculate_signal as calc_alphatrend_sig
from strategies.supertrend_strategy import compute_supertrend, calculate_signal as calc_supertrend_sig

# 25 大主力品种全量列表
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
        df["open"] = df["open"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)
        df["open_interest"] = df["open_interest"].astype(float)
    return df


def simulate_trend_strategy(df: pd.DataFrame, signals: pd.Series, cfg: dict, initial_balance: float = 1000000.0) -> dict:
    """标准趋势跟踪回测撮合 (支持持仓翻转与 ATR 动态止损)"""
    multiplier = cfg.get("multiplier", 10.0)
    tick_size = cfg.get("tick_size", 1.0)
    commission_per_lot = cfg.get("commission", 3.0)
    max_lots = cfg.get("max_lots", 5)

    n = len(df)
    if n < 50:
        return {"net_profit": 0.0, "trades_count": 0, "win_rate": 0.0, "pl_ratio": 0.0, "max_dd": 0.0, "sharpe": 0.0, "trades": []}

    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    dts = df["trade_time"].values
    sig_vals = signals.values

    # 计算 ATR 作为仓位与止损参考
    atr_series = calculate_atr(df, 14).bfill().values

    pos = 0  # 1: 多头, -1: 空头, 0: 空仓
    lots = 0
    entry_p = 0.0
    entry_idx = 0
    entry_dt = ""
    stop_loss = 0.0

    trades = []
    equity_curve = [initial_balance]
    current_equity = initial_balance

    for i in range(1, n):
        curr_sig = sig_vals[i - 1]  # 零前瞻: 使用上根 Bar 收盘信号在当前 Bar 开盘执行
        curr_open = opens[i]
        curr_high = highs[i]
        curr_low = lows[i]
        curr_atr = max(2.0, atr_series[i - 1])

        # 1. 检查是否触发硬止损 (2.0 ATR)
        if pos != 0:
            stopped_out = False
            exit_p = curr_open
            if pos == 1 and curr_low <= stop_loss:
                stopped_out = True
                exit_p = min(curr_open, stop_loss)
            elif pos == -1 and curr_high >= stop_loss:
                stopped_out = True
                exit_p = max(curr_open, stop_loss)

            if stopped_out:
                pnl = (exit_p - entry_p) * multiplier * lots if pos == 1 else (entry_p - exit_p) * multiplier * lots
                pnl -= (commission_per_lot * lots * 2 + tick_size * multiplier * lots)
                current_equity += pnl
                trades.append({
                    "entry_dt": entry_dt, "exit_dt": dts[i], "side": "LONG" if pos == 1 else "SHORT",
                    "entry_p": entry_p, "exit_p": exit_p, "lots": lots, "pnl": pnl, "reason": "触发 ATR 趋势硬止损"
                })
                pos = 0
                lots = 0

        # 2. 信号翻转撮合
        if curr_sig == 1 and pos != 1:
            # 平空 (如果有)
            if pos == -1:
                exit_p = curr_open + tick_size
                pnl = (entry_p - exit_p) * multiplier * lots - (commission_per_lot * lots + tick_size * multiplier * lots)
                current_equity += pnl
                trades.append({
                    "entry_dt": entry_dt, "exit_dt": dts[i], "side": "SHORT",
                    "entry_p": entry_p, "exit_p": exit_p, "lots": lots, "pnl": pnl, "reason": "信号翻多平空"
                })
            # 开多
            entry_p = curr_open + tick_size
            risk_per_share = 2.0 * curr_atr
            calc_lots = max(1, min(max_lots, int((initial_balance * 0.01) / (risk_per_share * multiplier + 1e-6))))
            pos = 1
            lots = calc_lots
            entry_dt = dts[i]
            entry_idx = i
            stop_loss = entry_p - 2.5 * curr_atr

        elif curr_sig == -1 and pos != -1:
            # 平多 (如果有)
            if pos == 1:
                exit_p = curr_open - tick_size
                pnl = (exit_p - entry_p) * multiplier * lots - (commission_per_lot * lots + tick_size * multiplier * lots)
                current_equity += pnl
                trades.append({
                    "entry_dt": entry_dt, "exit_dt": dts[i], "side": "LONG",
                    "entry_p": entry_p, "exit_p": exit_p, "lots": lots, "pnl": pnl, "reason": "信号翻空平多"
                })
            # 开空
            entry_p = curr_open - tick_size
            risk_per_share = 2.0 * curr_atr
            calc_lots = max(1, min(max_lots, int((initial_balance * 0.01) / (risk_per_share * multiplier + 1e-6))))
            pos = -1
            lots = calc_lots
            entry_dt = dts[i]
            entry_idx = i
            stop_loss = entry_p + 2.5 * curr_atr

        # 记录资金曲线
        unrealized = 0.0
        if pos == 1:
            unrealized = (closes[i] - entry_p) * multiplier * lots
        elif pos == -1:
            unrealized = (entry_p - closes[i]) * multiplier * lots
        equity_curve.append(current_equity + unrealized)

    # 统计指标
    total_trades = len(trades)
    if total_trades == 0:
        return {"net_profit": 0.0, "trades_count": 0, "win_rate": 0.0, "pl_ratio": 0.0, "max_dd": 0.0, "sharpe": 0.0, "trades": []}

    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
    win_rate = len(wins) / total_trades * 100.0
    net_profit = sum(t["pnl"] for t in trades)
    pl_ratio = (sum(wins) / abs(sum(losses))) if (len(losses) > 0 and sum(losses) != 0) else (99.0 if len(wins) > 0 else 0.0)

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
        "trades": trades
    }


def run_benchmark_comparison(timeframe: str):
    print("\n" + "=" * 115)
    print(f"📊 【AlphaTrend vs SuperTrend】25 大主力期货全量实证对决 —— 周期: {timeframe}")
    print("=" * 115)
    header = f"{'品种':<10} | {'AlphaTrend 净利':<15} {'胜率':<8} {'盈亏比':<8} {'交易数':<8} | {'SuperTrend 净利':<15} {'胜率':<8} {'盈亏比':<8} {'交易数':<8}"
    print(header)
    print("-" * 115)

    at_total_pnl = 0.0
    at_total_trades = 0
    at_total_wins = 0

    st_total_pnl = 0.0
    st_total_trades = 0
    st_total_wins = 0

    at_symbol_results = []
    st_symbol_results = []

    for sym in COMMODITY_UNIVERSE:
        df = load_symbol_data(sym, timeframe)
        if len(df) < 100:
            continue

        cfg = SYMBOL_CONFIGS.get(sym, {"name": sym, "multiplier": 10.0})
        name = cfg.get("name", sym)

        # 1. 运行 AlphaTrend
        at_sig = calc_alphatrend_sig(df, period=14, multiplier=1.618)
        at_res = simulate_trend_strategy(df, at_sig, cfg)

        # 2. 运行 SuperTrend
        st_sig = calc_supertrend_sig(df, period=10, multiplier=3.0)
        st_res = simulate_trend_strategy(df, st_sig, cfg)

        at_total_pnl += at_res["net_profit"]
        at_total_trades += at_res["trades_count"]
        at_total_wins += int(at_res["trades_count"] * at_res["win_rate"] / 100.0)
        at_symbol_results.append((sym, name, at_res))

        st_total_pnl += st_res["net_profit"]
        st_total_trades += st_res["trades_count"]
        st_total_wins += int(st_res["trades_count"] * st_res["win_rate"] / 100.0)
        st_symbol_results.append((sym, name, st_res))

        sym_str = f"{name} ({sym[:2]})"
        at_pnl_str = f"¥{at_res['net_profit']:+,.2f}"
        st_pnl_str = f"¥{st_res['net_profit']:+,.2f}"

        print(f"{sym_str:<10} | {at_pnl_str:<15} {at_res['win_rate']:>6.1f}%  {at_res['pl_ratio']:>6.2f}  {at_res['trades_count']:>6d}   | {st_pnl_str:<15} {st_res['win_rate']:>6.1f}%  {st_res['pl_ratio']:>6.2f}  {st_res['trades_count']:>6d}")

    at_avg_win = (at_total_wins / at_total_trades * 100.0) if at_total_trades > 0 else 0.0
    st_avg_win = (st_total_wins / st_total_trades * 100.0) if st_total_trades > 0 else 0.0

    print("=" * 115)
    print(f"🏆 【{timeframe} 大盘汇总】:")
    print(f"  • AlphaTrend (RSI+ATR通道) : 总净利 ¥{at_total_pnl:+,.2f} | 平均胜率 {at_avg_win:.1f}% | 总交易 {at_total_trades} 笔")
    print(f"  • SuperTrend (经典ATR通道)  : 总净利 ¥{st_total_pnl:+,.2f} | 平均胜率 {st_avg_win:.1f}% | 总交易 {st_total_trades} 笔")
    print("=" * 115)

    return {
        "timeframe": timeframe,
        "at": {"total_pnl": at_total_pnl, "win_rate": at_avg_win, "trades": at_total_trades, "symbols": at_symbol_results},
        "st": {"total_pnl": st_total_pnl, "win_rate": st_avg_win, "trades": st_total_trades, "symbols": st_symbol_results}
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeframe", type=str, default="all", choices=["10m", "15m", "30m", "all"])
    args = parser.parse_args()

    if args.timeframe == "all":
        results = {}
        for tf in ["10m", "15m", "30m"]:
            results[tf] = run_benchmark_comparison(tf)
    else:
        run_benchmark_comparison(args.timeframe)
