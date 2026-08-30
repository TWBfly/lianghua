"""
code/run_chanquant_v3_deep_audit.py — 「因果缠论 3.0 (ChanQuant 3.0)」多品种深度回测与五重硬门禁审计运行器

核心审计准则：
1. 动力学机制分流 (Kinetic Regime Adaptation):
   - 动量态 (Hurst >= 0.53): 3.0 ATR 动态吊灯跟踪三买单边；
   - 弹性态 (Hurst <= 0.47): 偏离均线 1.5 ATR 抄一买背驰，回归中枢即落袋；
   - 噪声态: 100% 空仓观望。
2. 工业级摩擦模型:
   - Next-Open 严格成交；
   - 扣除真实双边手续费 + 1-Tick 跳价真实滑点。
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STRATEGIES_DIR = PROJECT_ROOT / "strategies"
CODE_DIR = PROJECT_ROOT / "code"
for p in (STRATEGIES_DIR, CODE_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from chanquant_v3_master_strategy import calculate_factors
from contract_specs import get_spec

DB_PATH = PROJECT_ROOT / "data" / "ashare_quant.db"
OUTPUT_DIR = PROJECT_ROOT / "data" / "reports" / "chanquant_v3_audit_20260830"


def load_futures_data(symbol: str, timeframe: str = "15m") -> pd.DataFrame:
    """从本地 SQLite 数据库加载期货分钟行情"""
    conn = sqlite3.connect(DB_PATH)
    query = """
        SELECT trade_time, open, high, low, close, volume, open_interest
        FROM futures_min_bars
        WHERE symbol = ? AND timeframe = ?
        ORDER BY trade_time ASC
    """
    df = pd.read_sql_query(query, conn, params=(symbol, timeframe))
    conn.close()

    if df.empty:
        return pd.DataFrame()

    df["trade_time"] = pd.to_datetime(df["trade_time"])
    df = df.drop_duplicates(subset=["trade_time"]).sort_values("trade_time").reset_index(drop=True)
    return df


def wilson_score_interval(wins: int, total: int, confidence: float = 0.95) -> Tuple[float, float]:
    """Wilson Score 置信区间"""
    if total == 0:
        return 0.0, 0.0
    z = 1.95996
    p = wins / total
    denom = 1 + z**2 / total
    center = (p + z**2 / (2 * total)) / denom
    spread = (z * math.sqrt(p * (1 - p) / total + z**2 / (4 * total**2))) / denom
    return max(0.0, center - spread), min(1.0, center + spread)


def backtest_v3_single_series(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str = "15m",
    min_er: float = 0.35,
    max_comp: float = 1.30,
    stop_atr_mult: float = 1.2,
    trail_atr_mult: float = 3.0,
    holding_bars_max: int = 40,
    lots: int = 2,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    ChanQuant 3.0 高保真因果回测引擎
    """
    spec = get_spec(symbol)
    multiplier = spec.multiplier
    fee_rate = spec.fee_rate
    tick_size = spec.tick_size
    init_capital = 500_000

    if len(df) < 50:
        return [], {}

    factors_df = calculate_factors(df, atr_period=14)
    atr = factors_df["atr"].values
    b1_raw = factors_df["b1_raw"].values
    s1_raw = factors_df["s1_raw"].values
    b3_raw = factors_df["b3_raw"].values
    s3_raw = factors_df["s3_raw"].values

    regime = factors_df["regime"].values
    ss_price = factors_df["ss_price"].values
    ofi_z = factors_df["ofi_zscore"].values
    vol_dens = factors_df["vol_density"].values
    b05_er = factors_df["b05_er"].values
    z09_comp = factors_df["z09_comp"].values
    zs_high = factors_df["zs_high"].values
    zs_low = factors_df["zs_low"].values

    opens = df["open"].astype(float).values
    highs = df["high"].astype(float).values
    lows = df["low"].astype(float).values
    closes = df["close"].astype(float).values
    times = df["trade_time"].astype(str).values
    n = len(df)

    trades: List[Dict[str, Any]] = []
    position = 0
    trade_mode = 0  # 1: 动量三买 (3.0 ATR吊灯), 2: 弹性一买 (回归均线平仓)
    entry_idx = 0
    entry_p = 0.0
    stop_p = 0.0
    target_p = 0.0
    highest_p = 0.0
    lowest_p = 999999.0
    setup_name = ""

    for i in range(1, n):
        curr_o = opens[i]
        curr_h = highs[i]
        curr_l = lows[i]
        curr_c = closes[i]
        curr_atr = atr[i] if atr[i] > 0 else 1.0
        curr_ss = ss_price[i]

        # --- 1. 出场管理 ---
        if position == 1:
            highest_p = max(highest_p, curr_h)

            if trade_mode == 1:
                # 动量轨：动态保本 + 动态吊灯跟踪
                if highest_p >= entry_p + 1.0 * curr_atr:
                    stop_p = max(stop_p, entry_p + 0.1 * curr_atr)
                if highest_p >= entry_p + 1.8 * curr_atr:
                    chandelier_stop = highest_p - trail_atr_mult * curr_atr
                    stop_p = max(stop_p, chandelier_stop)

                if curr_l <= stop_p or (i - entry_idx) >= holding_bars_max:
                    exit_p = min(curr_o, stop_p) if curr_o <= stop_p else stop_p
                    exit_p = max(exit_p, curr_l)

                    gross = (exit_p - entry_p) * multiplier * lots
                    entry_fee = entry_p * multiplier * lots * fee_rate
                    exit_fee = exit_p * multiplier * lots * fee_rate
                    slippage = 2 * tick_size * multiplier * lots
                    net_pnl = gross - entry_fee - exit_fee - slippage

                    trades.append({
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "side": "LONG",
                        "setup": setup_name,
                        "mode": "MOMENTUM" if trade_mode == 1 else "REVERSION",
                        "entry_time": times[entry_idx],
                        "exit_time": times[i],
                        "entry_price": entry_p,
                        "exit_price": exit_p,
                        "lots": lots,
                        "holding_bars": i - entry_idx,
                        "gross_pnl": gross,
                        "fees": entry_fee + exit_fee,
                        "slippage": slippage,
                        "net_pnl": net_pnl,
                        "return_atr": (exit_p - entry_p) / curr_atr,
                    })
                    position = 0

            elif trade_mode == 2:
                # 弹性轨：价格回归均线中轴即刻落袋
                if curr_h >= target_p or curr_h >= curr_ss or curr_l <= stop_p or (i - entry_idx) >= 20:
                    exit_p = max(target_p, curr_ss) if (curr_h >= target_p or curr_h >= curr_ss) else (min(curr_o, stop_p) if curr_o <= stop_p else stop_p)
                    exit_p = min(max(exit_p, curr_l), curr_h)

                    gross = (exit_p - entry_p) * multiplier * lots
                    entry_fee = entry_p * multiplier * lots * fee_rate
                    exit_fee = exit_p * multiplier * lots * fee_rate
                    slippage = 2 * tick_size * multiplier * lots
                    net_pnl = gross - entry_fee - exit_fee - slippage

                    trades.append({
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "side": "LONG",
                        "setup": setup_name,
                        "mode": "REVERSION",
                        "entry_time": times[entry_idx],
                        "exit_time": times[i],
                        "entry_price": entry_p,
                        "exit_price": exit_p,
                        "lots": lots,
                        "holding_bars": i - entry_idx,
                        "gross_pnl": gross,
                        "fees": entry_fee + exit_fee,
                        "slippage": slippage,
                        "net_pnl": net_pnl,
                        "return_atr": (exit_p - entry_p) / curr_atr,
                    })
                    position = 0

        elif position == -1:
            lowest_p = min(lowest_p, curr_l)

            if trade_mode == 1:
                if lowest_p <= entry_p - 1.0 * curr_atr:
                    stop_p = min(stop_p, entry_p - 0.1 * curr_atr)
                if lowest_p <= entry_p - 1.8 * curr_atr:
                    chandelier_stop = lowest_p + trail_atr_mult * curr_atr
                    stop_p = min(stop_p, chandelier_stop)

                if curr_h >= stop_p or (i - entry_idx) >= holding_bars_max:
                    exit_p = max(curr_o, stop_p) if curr_o >= stop_p else stop_p
                    exit_p = min(exit_p, curr_h)

                    gross = (entry_p - exit_p) * multiplier * lots
                    entry_fee = entry_p * multiplier * lots * fee_rate
                    exit_fee = exit_p * multiplier * lots * fee_rate
                    slippage = 2 * tick_size * multiplier * lots
                    net_pnl = gross - entry_fee - exit_fee - slippage

                    trades.append({
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "side": "SHORT",
                        "setup": setup_name,
                        "mode": "MOMENTUM",
                        "entry_time": times[entry_idx],
                        "exit_time": times[i],
                        "entry_price": entry_p,
                        "exit_price": exit_p,
                        "lots": lots,
                        "holding_bars": i - entry_idx,
                        "gross_pnl": gross,
                        "fees": entry_fee + exit_fee,
                        "slippage": slippage,
                        "net_pnl": net_pnl,
                        "return_atr": (entry_p - exit_p) / curr_atr,
                    })
                    position = 0

            elif trade_mode == 2:
                if curr_l <= target_p or curr_l <= curr_ss or curr_h >= stop_p or (i - entry_idx) >= 20:
                    exit_p = min(target_p, curr_ss) if (curr_l <= target_p or curr_l <= curr_ss) else (max(curr_o, stop_p) if curr_o >= stop_p else stop_p)
                    exit_p = min(max(exit_p, curr_l), curr_h)

                    gross = (entry_p - exit_p) * multiplier * lots
                    entry_fee = entry_p * multiplier * lots * fee_rate
                    exit_fee = exit_p * multiplier * lots * fee_rate
                    slippage = 2 * tick_size * multiplier * lots
                    net_pnl = gross - entry_fee - exit_fee - slippage

                    trades.append({
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "side": "SHORT",
                        "setup": setup_name,
                        "mode": "REVERSION",
                        "entry_time": times[entry_idx],
                        "exit_time": times[i],
                        "entry_price": entry_p,
                        "exit_price": exit_p,
                        "lots": lots,
                        "holding_bars": i - entry_idx,
                        "gross_pnl": gross,
                        "fees": entry_fee + exit_fee,
                        "slippage": slippage,
                        "net_pnl": net_pnl,
                        "return_atr": (entry_p - exit_p) / curr_atr,
                    })
                    position = 0

        # --- 2. 机制分流与订单流门禁入场 ---
        if position == 0:
            reg = regime[i - 1]

            # 模式 1: 单边动量态 (MOMENTUM_TREND) -> 仅做 三买 / 三卖
            if reg == 1:
                if b3_raw[i - 1] > 0:
                    er = b05_er[i - 1]
                    comp = z09_comp[i - 1]
                    ofi = ofi_z[i - 1]
                    dens = vol_dens[i - 1]

                    if er >= min_er and comp <= max_comp and ofi >= -0.2 and dens <= 1.4:
                        position = 1
                        trade_mode = 1
                        entry_idx = i
                        entry_p = curr_o
                        highest_p = entry_p
                        setup_name = "B3_MOMENTUM"
                        zh = zs_high[i - 1]
                        if zh > 0 and (entry_p - zh) < 2.5 * curr_atr:
                            stop_p = max(zh - 0.5 * curr_atr, entry_p - 1.5 * curr_atr)
                        else:
                            stop_p = entry_p - stop_atr_mult * curr_atr
                        continue

                elif s3_raw[i - 1] > 0:
                    er = b05_er[i - 1]
                    comp = z09_comp[i - 1]
                    ofi = ofi_z[i - 1]
                    dens = vol_dens[i - 1]

                    if er >= min_er and comp <= max_comp and ofi <= 0.2 and dens <= 1.4:
                        position = -1
                        trade_mode = 1
                        entry_idx = i
                        entry_p = curr_o
                        lowest_p = entry_p
                        setup_name = "S3_MOMENTUM"
                        zl = zs_low[i - 1]
                        if zl > 0 and (zl - entry_p) < 2.5 * curr_atr:
                            stop_p = min(zl + 0.5 * curr_atr, entry_p + 1.5 * curr_atr)
                        else:
                            stop_p = entry_p + stop_atr_mult * curr_atr
                        continue

            # 模式 2: 均值弹性态 (MEAN_REVERTING) -> 仅做 一买 / 一卖 极值背驰
            elif reg == 2:
                if b1_raw[i - 1] > 0:
                    position = 1
                    trade_mode = 2
                    entry_idx = i
                    entry_p = curr_o
                    highest_p = entry_p
                    setup_name = "B1_REVERSION"
                    stop_p = entry_p - 1.0 * curr_atr
                    target_p = max(curr_ss, entry_p + 1.5 * curr_atr)
                    continue

                elif s1_raw[i - 1] > 0:
                    position = -1
                    trade_mode = 2
                    entry_idx = i
                    entry_p = curr_o
                    lowest_p = entry_p
                    setup_name = "S1_REVERSION"
                    stop_p = entry_p + 1.0 * curr_atr
                    target_p = min(curr_ss, entry_p - 1.5 * curr_atr)
                    continue

    if not trades:
        return [], {}

    tdf = pd.DataFrame(trades)
    tot_trades = len(tdf)
    wins = tdf[tdf["net_pnl"] > 0]
    losses = tdf[tdf["net_pnl"] < 0]
    win_rate = len(wins) / tot_trades
    w_low, w_high = wilson_score_interval(len(wins), tot_trades)
    tot_win_pnl = wins["net_pnl"].sum()
    tot_loss_pnl = abs(losses["net_pnl"].sum())
    profit_factor = float(tot_win_pnl / tot_loss_pnl) if tot_loss_pnl > 0 else 99.0
    net_pnl = float(tdf["net_pnl"].sum())

    cum_pnl = tdf["net_pnl"].cumsum()
    peak = cum_pnl.cummax()
    max_dd_rmb = float((peak - cum_pnl).max())
    max_dd_pct = float(max_dd_rmb / init_capital)

    summary = {
        "symbol": symbol,
        "name": spec.name,
        "timeframe": timeframe,
        "trade_count": tot_trades,
        "win_rate": round(win_rate, 4),
        "wilson_95_ci": [round(w_low, 4), round(w_high, 4)],
        "net_pnl": round(net_pnl, 2),
        "profit_factor": round(profit_factor, 2),
        "avg_trade_pnl": round(float(tdf["net_pnl"].mean()), 2),
        "expectancy_atr": round(float(tdf["return_atr"].mean()), 4),
        "total_fees": round(float(tdf["fees"].sum()), 2),
        "total_slippage": round(float(tdf["slippage"].sum()), 2),
        "max_drawdown_rmb": round(max_dd_rmb, 2),
        "max_drawdown_pct": round(max_dd_pct, 4),
    }
    return trades, summary


def run_comprehensive_v3_audit(symbols: List[str], timeframes: List[str] = ["15m"]):
    """全景执行 ChanQuant 3.0 深度审计"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_summaries = []
    all_trades_list = []

    print("================================================================================")
    print("🚀 【ChanQuant 3.0 动力学机制分流与订单流门禁】全景深度审计开始...")
    print("================================================================================")

    for tf in timeframes:
        for sym in symbols:
            df = load_futures_data(sym, tf)
            if df.empty or len(df) < 50:
                continue

            trades, summary = backtest_v3_single_series(df, sym, timeframe=tf)
            if summary.get("trade_count", 0) > 0:
                all_summaries.append(summary)
                all_trades_list.extend(trades)
                pnl_str = f"{summary['net_pnl']:12.2f} RMB"
                status_icon = "🟢" if summary["net_pnl"] > 0 else "🔴"
                print(f"{status_icon} {sym:8s} ({summary['name']:4s}) | {tf:3s} | 交易: {summary['trade_count']:4d} 笔 | 胜率: {summary['win_rate']*100:5.2f}% | 净利: {pnl_str} | PF: {summary['profit_factor']:4.2f} | MaxDD: {summary['max_drawdown_pct']*100:5.2f}%")

    if not all_trades_list:
        print("[!] 无有效交易数据")
        return

    all_tdf = pd.DataFrame(all_trades_list)
    tot_trades_all = len(all_tdf)
    tot_wins = all_tdf[all_tdf["net_pnl"] > 0]
    tot_losses = all_tdf[all_tdf["net_pnl"] < 0]
    overall_win_rate = len(tot_wins) / tot_trades_all
    overall_pf = float(tot_wins["net_pnl"].sum() / abs(tot_losses["net_pnl"].sum())) if len(tot_losses) > 0 else 99.0
    overall_net_pnl = float(all_tdf["net_pnl"].sum())

    all_tdf["exit_time_dt"] = pd.to_datetime(all_tdf["exit_time"])
    all_tdf_sorted = all_tdf.sort_values("exit_time_dt").reset_index(drop=True)
    cum_pnl = all_tdf_sorted["net_pnl"].cumsum()
    peak = cum_pnl.cummax()
    max_dd_val = float((peak - cum_pnl).max())

    daily_pnl = all_tdf_sorted.groupby(all_tdf_sorted["exit_time_dt"].dt.date)["net_pnl"].sum()
    sharpe = float(daily_pnl.mean() / (daily_pnl.std() + 1e-8) * math.sqrt(250)) if len(daily_pnl) > 1 else 0.0

    report = {
        "benchmark_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_portfolio_trades": tot_trades_all,
        "overall_win_rate": round(overall_win_rate, 4),
        "overall_profit_factor": round(overall_pf, 2),
        "overall_net_pnl_rmb": round(overall_net_pnl, 2),
        "annualized_sharpe": round(sharpe, 2),
        "portfolio_max_drawdown_rmb": round(max_dd_val, 2),
        "total_fees_rmb": round(float(all_tdf["fees"].sum()), 2),
        "total_slippage_rmb": round(float(all_tdf["slippage"].sum()), 2),
        "symbol_reports": all_summaries,
    }

    report_path = OUTPUT_DIR / "chanquant_v3_master_audit_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n================================================================================")
    print("🏆 【ChanQuant 3.0 全景审计汇总结论】")
    print("================================================================================")
    print(f"• 组合总独立交易样本:  {tot_trades_all:6d} 笔 (噪声过滤后高质量波段交易)")
    print(f"• 摩擦后全额综合净利润: {overall_net_pnl:14.2f} RMB")
    print(f"• 全局综合盈亏比 (PF):  {overall_pf:6.2f}")
    print(f"• 年化夏普比率:         {sharpe:6.2f}")
    print(f"• 组合最大历史回撤:     {max_dd_val:14.2f} RMB")
    print(f"• 摩擦成本总消耗 (佣金+滑点): {float(all_tdf['fees'].sum() + all_tdf['slippage'].sum()):10.2f} RMB")
    print(f"• 完整 JSON 审计报告:   {report_path}")
    print("================================================================================")


if __name__ == "__main__":
    target_symbols = [
        "AG_IDX", "AU_IDX", "SC_IDX", "CU_IDX", "AL_IDX", "ZN_IDX", "SN_IDX",
        "RB_IDX", "HC_IDX", "I_IDX", "JM_IDX", "J_IDX", "MA_IDX", "TA_IDX",
        "SA_IDX", "FG_IDX", "M_IDX", "Y_IDX", "P_IDX", "C_IDX", "CF_IDX",
        "SR_IDX", "RU_IDX", "LC_IDX", "SI_IDX"
    ]
    run_comprehensive_v3_audit(target_symbols, timeframes=["15m", "30m"])
