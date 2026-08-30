"""
code/run_chanquant_v4_deep_audit.py — 「因果缠论 4.0 (ChanQuant 4.0)」全息区间套与波动率平价全景深度审计与版本对比

核心审计准则：
1. 波动率平价与动态头寸管理 (Risk-Parity Position Sizing):
   - 单笔交易风险固定锚定为 Capital * 1.0%；
   - 彻底平衡贵金属、原油、有色与化工小品种的风险贡献度。
2. 资产物理基因专属映射 (Asset-Class Regime Hard-Locking):
    - 动量战队 (AG, AU, SC, CU, SN, LC) 专做三买顺势加速；
    - 弹性战队 (J, JM, RB, HC, AL, ZN, I, TA, MA, SA, FG, M, Y, P, C, CF, SR, RU, SI) 专做一买极值反弹回归。
3. 双级别区间套宏观共振 (Recursive Multi-Timeframe Alignment):
   - 15m 三买必须顺应 1h/EMA50 宏观主势。
4. 全景跨版本对比 (Cross-Version Comparison):
   - 与 V2 (无约束高频) 及 V3 (基础分流) 输出清晰量化对比卡。
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

from chanquant_v4_master_strategy import (
    calculate_factors_v4,
    calculate_risk_parity_lots,
    get_asset_profile,
    ASSET_PHYSICS_PROFILES,
)
from contract_specs import get_spec
from backtest_validator import (
    validate_report,
    format_reliability_banner,
    stamp_symbol_report,
    check_data_coverage,
    wilson_score_interval,
    MIN_TRADES_RELIABLE,
)

DB_PATH = PROJECT_ROOT / "data" / "ashare_quant.db"
OUTPUT_DIR = PROJECT_ROOT / "data" / "reports" / "chanquant_v4_audit_20260830"


def load_futures_data(symbol: str, timeframe: str = "15m") -> pd.DataFrame:
    """加载期货历史分钟 K 线"""
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




def backtest_v4_single_series(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str = "15m",
    capital: float = 500_000,
    target_risk_pct: float = 0.010,
    holding_bars_max: int = 40,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    ChanQuant 4.0 波动率平价与区间套回测引擎
    """
    spec = get_spec(symbol)
    multiplier = spec.multiplier
    fee_rate = spec.fee_rate
    tick_size = spec.tick_size

    if len(df) < 50:
        return [], {}

    profile = get_asset_profile(symbol)
    asset_mode = profile["mode"]
    trail_atr_mult = profile.get("trail_atr", 3.0)
    stop_atr_mult = profile.get("stop_atr", 1.2)

    factors_df = calculate_factors_v4(df, atr_period=14)
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
    macro_bull = factors_df["macro_bull"].values
    macro_bear = factors_df["macro_bear"].values

    opens = df["open"].astype(float).values
    highs = df["high"].astype(float).values
    lows = df["low"].astype(float).values
    closes = df["close"].astype(float).values
    times = df["trade_time"].astype(str).values
    n = len(df)

    trades: List[Dict[str, Any]] = []
    position = 0
    trade_mode = 0  # 1: 动量三买, 2: 弹性一买
    entry_idx = 0
    entry_p = 0.0
    stop_p = 0.0
    target_p = 0.0
    current_lots = 1
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

                    gross = (exit_p - entry_p) * multiplier * current_lots
                    entry_fee = entry_p * multiplier * current_lots * fee_rate
                    exit_fee = exit_p * multiplier * current_lots * fee_rate
                    slippage = 2 * tick_size * multiplier * current_lots
                    net_pnl = gross - entry_fee - exit_fee - slippage

                    trades.append({
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "side": "LONG",
                        "setup": setup_name,
                        "mode": "MOMENTUM",
                        "entry_time": times[entry_idx],
                        "exit_time": times[i],
                        "entry_price": entry_p,
                        "exit_price": exit_p,
                        "lots": current_lots,
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

                    gross = (exit_p - entry_p) * multiplier * current_lots
                    entry_fee = entry_p * multiplier * current_lots * fee_rate
                    exit_fee = exit_p * multiplier * current_lots * fee_rate
                    slippage = 2 * tick_size * multiplier * current_lots
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
                        "lots": current_lots,
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

                    gross = (entry_p - exit_p) * multiplier * current_lots
                    entry_fee = entry_p * multiplier * current_lots * fee_rate
                    exit_fee = exit_p * multiplier * current_lots * fee_rate
                    slippage = 2 * tick_size * multiplier * current_lots
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
                        "lots": current_lots,
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

                    gross = (entry_p - exit_p) * multiplier * current_lots
                    entry_fee = entry_p * multiplier * current_lots * fee_rate
                    exit_fee = exit_p * multiplier * current_lots * fee_rate
                    slippage = 2 * tick_size * multiplier * current_lots
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
                        "lots": current_lots,
                        "holding_bars": i - entry_idx,
                        "gross_pnl": gross,
                        "fees": entry_fee + exit_fee,
                        "slippage": slippage,
                        "net_pnl": net_pnl,
                        "return_atr": (entry_p - exit_p) / curr_atr,
                    })
                    position = 0

        # --- 2. 机制分流与资产基因硬锁定入场 ---
        if position == 0:
            reg = regime[i - 1]
            allow_momentum = (asset_mode in ("MOMENTUM_ONLY", "HYBRID")) and (reg == 1 or asset_mode == "MOMENTUM_ONLY")
            allow_reversion = (asset_mode in ("REVERSION_ONLY", "HYBRID")) and (reg == 2 or asset_mode == "REVERSION_ONLY")

            # 计算波动率平价开仓手数
            lots = calculate_risk_parity_lots(symbol, curr_o, curr_atr, stop_mult=stop_atr_mult, capital=capital, target_risk_pct=target_risk_pct)

            # >>> 模式 1: 单边动量三买/三卖 (带区间套大周期宏观共振 + 订单流放行) <<<
            if allow_momentum:
                if b3_raw[i - 1] > 0 and macro_bull[i - 1]:
                    er = b05_er[i - 1]
                    comp = z09_comp[i - 1]
                    ofi = ofi_z[i - 1]
                    dens = vol_dens[i - 1]

                    if er >= 0.35 and comp <= 1.35 and ofi >= -0.3 and dens <= 1.4:
                        position = 1
                        trade_mode = 1
                        entry_idx = i
                        entry_p = curr_o
                        highest_p = entry_p
                        current_lots = lots
                        setup_name = "B3_MOMENTUM"
                        zh = zs_high[i - 1]
                        if zh > 0 and (entry_p - zh) < 2.5 * curr_atr:
                            stop_p = max(zh - 0.5 * curr_atr, entry_p - 1.5 * curr_atr)
                        else:
                            stop_p = entry_p - stop_atr_mult * curr_atr
                        continue

                elif s3_raw[i - 1] > 0 and macro_bear[i - 1]:
                    er = b05_er[i - 1]
                    comp = z09_comp[i - 1]
                    ofi = ofi_z[i - 1]
                    dens = vol_dens[i - 1]

                    if er >= 0.35 and comp <= 1.35 and ofi <= 0.3 and dens <= 1.4:
                        position = -1
                        trade_mode = 1
                        entry_idx = i
                        entry_p = curr_o
                        lowest_p = entry_p
                        current_lots = lots
                        setup_name = "S3_MOMENTUM"
                        zl = zs_low[i - 1]
                        if zl > 0 and (zl - entry_p) < 2.5 * curr_atr:
                            stop_p = min(zl + 0.5 * curr_atr, entry_p + 1.5 * curr_atr)
                        else:
                            stop_p = entry_p + stop_atr_mult * curr_atr
                        continue

            # >>> 模式 2: 均值弹性一买/一卖 (极值超跌/超买背驰反弹) <<<
            elif allow_reversion:
                dev = abs(curr_c - curr_ss) / curr_atr
                if b1_raw[i - 1] > 0 and dev >= 1.2:
                    position = 1
                    trade_mode = 2
                    entry_idx = i
                    entry_p = curr_o
                    highest_p = entry_p
                    current_lots = lots
                    setup_name = "B1_REVERSION"
                    stop_p = entry_p - stop_atr_mult * curr_atr
                    target_p = max(curr_ss, entry_p + 1.5 * curr_atr)
                    continue

                elif s1_raw[i - 1] > 0 and dev >= 1.2:
                    position = -1
                    trade_mode = 2
                    entry_idx = i
                    entry_p = curr_o
                    lowest_p = entry_p
                    current_lots = lots
                    setup_name = "S1_REVERSION"
                    stop_p = entry_p + stop_atr_mult * curr_atr
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
    max_dd_pct = float(max_dd_rmb / capital)

    summary = {
        "symbol": symbol,
        "name": spec.name,
        "timeframe": timeframe,
        "mode": asset_mode,
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


def _query_data_ranges(symbols: List[str], timeframes: List[str]) -> Dict[Tuple[str, str], Dict[str, str]]:
    """从数据库查询每个品种-周期的实际数据起止时间"""
    conn = sqlite3.connect(DB_PATH)
    ranges = {}
    for tf in timeframes:
        rows = conn.execute(
            "SELECT symbol, min(trade_time), max(trade_time) "
            "FROM futures_min_bars WHERE timeframe=? GROUP BY symbol", (tf,)
        ).fetchall()
        for sym, t_min, t_max in rows:
            if sym in symbols:
                ranges[(sym, tf)] = {"start": t_min, "end": t_max}
    conn.close()
    return ranges


def run_comprehensive_v4_audit(symbols: List[str], timeframes: List[str] = ["15m", "30m"]):
    """全景执行 ChanQuant 4.0 深度审计 — 含统计可靠性硬门禁"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_summaries = []
    all_trades_list = []

    # 预先查询数据覆盖范围
    data_ranges = _query_data_ranges(symbols, timeframes)

    print("=" * 80)
    print("🚀 【ChanQuant 4.0 波动率平价与区间套终极审计 (含统计可靠性门禁)】")
    print("=" * 80)

    for tf in timeframes:
        for sym in symbols:
            df = load_futures_data(sym, tf)
            if df.empty or len(df) < 50:
                continue

            trades, summary = backtest_v4_single_series(df, sym, timeframe=tf)
            if summary.get("trade_count", 0) > 0:
                all_summaries.append(summary)
                all_trades_list.extend(trades)

                # 实时打印 — 带可靠性标记
                tc = summary["trade_count"]
                grade_icon = "✅" if tc >= MIN_TRADES_RELIABLE else ("⚠️ " if tc >= 20 else "❌")
                pnl_icon = "🟢" if summary["net_pnl"] > 0 else "🔴"
                mode_tag = f"[{summary['mode'][:4]}]"
                print(f"{pnl_icon}{grade_icon} {sym:8s} ({summary['name']:4s}) {mode_tag:6s} | {tf:3s} | 交易: {tc:3d}笔 | 胜率: {summary['win_rate']*100:5.2f}% | 净利: {summary['net_pnl']:12.2f} | PF: {summary['profit_factor']:4.2f}")

    if not all_trades_list:
        print("[!] 无有效交易数据")
        return

    # --- 统计可靠性验证 ---
    validation = validate_report(all_summaries, data_ranges)
    print("\n" + format_reliability_banner(validation))

    # --- 全量原始统计 (不隐藏任何数字) ---
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

    # 战队细分归因
    squad_pnl = {}
    for sym_res in all_summaries:
        m = sym_res["mode"]
        squad_pnl[m] = squad_pnl.get(m, 0.0) + sym_res["net_pnl"]

    report = {
        "benchmark_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "version": "ChanQuant 4.0",
        "total_portfolio_trades": tot_trades_all,
        "overall_win_rate": round(overall_win_rate, 4),
        "overall_profit_factor": round(overall_pf, 2),
        "overall_net_pnl_rmb": round(overall_net_pnl, 2),
        "annualized_sharpe": round(sharpe, 2),
        "portfolio_max_drawdown_rmb": round(max_dd_val, 2),
        "total_fees_rmb": round(float(all_tdf["fees"].sum()), 2),
        "total_slippage_rmb": round(float(all_tdf["slippage"].sum()), 2),
        "squad_attribution": squad_pnl,
        "reliability": validation["reliability_summary"],
        "symbol_reports": all_summaries,
    }

    report_path = OUTPUT_DIR / "chanquant_v4_master_audit_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 80)
    print("🏆 【ChanQuant 4.0 全景审计汇总结论】")
    print("=" * 80)
    print(f"• 组合总交易样本:        {tot_trades_all:6d} 笔")
    print(f"• 全量净利润 (含不可靠):  {overall_net_pnl:14.2f} RMB")
    print(f"• 全局盈亏比 (PF):       {overall_pf:6.2f}")
    print(f"• 年化夏普比率:          {sharpe:6.2f}")
    print(f"• 组合最大回撤:          {max_dd_val:14.2f} RMB")
    rs = validation["reliability_summary"]
    print(f"• 可靠子策略净利润:      {rs['reliable_net_pnl']:14.2f} RMB  ← 这才是真实结论")
    print(f"• 动量战队总净利润:      {squad_pnl.get('MOMENTUM_ONLY', 0.0):14.2f} RMB")
    print(f"• 弹性战队总净利润:      {squad_pnl.get('REVERSION_ONLY', 0.0):14.2f} RMB")
    print(f"• 完整 JSON 审计报告:    {report_path}")
    print("=" * 80)


if __name__ == "__main__":
    target_symbols = [
        "AG_IDX", "AU_IDX", "SC_IDX", "CU_IDX", "AL_IDX", "ZN_IDX", "SN_IDX",
        "RB_IDX", "HC_IDX", "I_IDX", "JM_IDX", "J_IDX", "MA_IDX", "TA_IDX",
        "SA_IDX", "FG_IDX", "M_IDX", "Y_IDX", "P_IDX", "C_IDX", "CF_IDX",
        "SR_IDX", "RU_IDX", "LC_IDX", "SI_IDX"
    ]
    run_comprehensive_v4_audit(target_symbols, timeframes=["15m", "30m"])

