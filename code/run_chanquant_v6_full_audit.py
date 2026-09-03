"""
code/run_chanquant_v6_full_audit.py — 缠论量化 6.0 全市场 25 大主力品种全周期大数定律与 3 倍压力测试终极审计
"""

import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = PROJECT_ROOT / "code"
STRATEGIES_DIR = PROJECT_ROOT / "strategies"
for p in (CODE_DIR, STRATEGIES_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from contract_specs import get_spec
from technical_indicators import calculate_atr
from chanquant_v6_alpha_master import calculate_factors_v6
from unified_backtest_pipeline import UnifiedDataProvider, UnifiedReportFormatter, round_to_tick, REPORTS_DIR


def backtest_chanquant_v6(df: pd.DataFrame, symbol: str, timeframe: str = "15m", cost_multiplier: float = 1.0) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    spec = get_spec(symbol)
    multiplier = spec.multiplier
    fee_rate = spec.fee_rate * cost_multiplier
    tick_size = spec.tick_size
    margin_rate = spec.margin_rate
    slippage_ticks = 2 * cost_multiplier

    factors = calculate_factors_v6(df)
    atr = factors["atr"].values
    is_bull = factors["is_bull"].values
    is_bear = factors["is_bear"].values
    b2 = factors["b2"].values
    b3 = factors["b3"].values
    s2 = factors["s2"].values
    s3 = factors["s3"].values
    zs_high = factors["zs_high"].values
    zs_low = factors["zs_low"].values
    ema20 = factors["ema20"].values
    ss_slope = factors["ss_slope"].values

    opens = df["open"].astype(float).values
    highs = df["high"].astype(float).values
    lows = df["low"].astype(float).values
    closes = df["close"].astype(float).values
    times = df["trade_time"].astype(str).values
    regimes = df.get("regime", pd.Series(["UNKNOWN"] * len(df))).values
    n = len(df)

    trades = []
    position = 0
    entry_p = 0.0
    stop_p = 0.0
    target_p = 0.0
    entry_idx = 0
    lots = 1
    entry_regime = "UNKNOWN"

    pending_side = 0
    pending_limit_p = 0.0
    pending_stop_p = 0.0
    pending_target_p = 0.0
    pending_timeout = 0
    pending_regime = "UNKNOWN"

    available_cash = 500_000.0
    bankruptcy_events = 0
    force_liquidations = 0

    for i in range(1, n):
        curr_o = round_to_tick(opens[i], tick_size)
        curr_h = round_to_tick(highs[i], tick_size)
        curr_l = round_to_tick(lows[i], tick_size)
        curr_c = round_to_tick(closes[i], tick_size)
        prev_c = round_to_tick(closes[i - 1], tick_size)
        curr_atr = max(tick_size, atr[i])

        is_limit_up = (curr_h - curr_l < 1e-4) and (curr_c >= prev_c * 1.059)
        is_limit_down = (curr_h - curr_l < 1e-4) and (curr_c <= prev_c * 0.941)

        # 1. 检查持仓出场
        if position == 1:
            unrealized = (curr_c - entry_p) * multiplier * lots
            equity = available_cash + unrealized
            margin_occ = curr_c * multiplier * lots * margin_rate
            risk_ratio = margin_occ / max(equity, 1e-6)

            is_force_liq = (risk_ratio >= 1.20 or equity <= margin_occ * 0.5)
            is_stopped = (curr_l <= stop_p)
            is_tp = (curr_h >= target_p)
            is_expired = ((i - entry_idx) >= 100)

            if (is_stopped or is_tp or is_expired or is_force_liq) and not is_limit_down:
                if is_force_liq:
                    force_liquidations += 1
                    raw_exit = curr_o
                elif is_stopped:
                    raw_exit = curr_o if curr_o <= stop_p else stop_p
                elif is_tp:
                    raw_exit = curr_o if curr_o >= target_p else target_p
                else:
                    raw_exit = curr_o

                exit_p = round_to_tick(max(curr_l, min(curr_h, raw_exit)), tick_size)
                gross = (exit_p - entry_p) * multiplier * lots
                fee = (entry_p + exit_p) * multiplier * lots * fee_rate
                slip = slippage_ticks * tick_size * multiplier * lots
                net = gross - fee - slip

                available_cash += net
                if available_cash < 0:
                    bankruptcy_events += 1

                trades.append({
                    "symbol": symbol,
                    "side": "LONG",
                    "entry_time": times[entry_idx],
                    "exit_time": times[i],
                    "entry_price": entry_p,
                    "exit_price": exit_p,
                    "lots": lots,
                    "holding_bars": i - entry_idx,
                    "regime": entry_regime,
                    "net_pnl": net,
                })
                position = 0

        elif position == -1:
            unrealized = (entry_p - curr_c) * multiplier * lots
            equity = available_cash + unrealized
            margin_occ = curr_c * multiplier * lots * margin_rate
            risk_ratio = margin_occ / max(equity, 1e-6)

            is_force_liq = (risk_ratio >= 1.20 or equity <= margin_occ * 0.5)
            is_stopped = (curr_h >= stop_p)
            is_tp = (curr_l <= target_p)
            is_expired = ((i - entry_idx) >= 100)

            if (is_stopped or is_tp or is_expired or is_force_liq) and not is_limit_up:
                if is_force_liq:
                    force_liquidations += 1
                    raw_exit = curr_o
                elif is_stopped:
                    raw_exit = curr_o if curr_o >= stop_p else stop_p
                elif is_tp:
                    raw_exit = curr_o if curr_o <= target_p else target_p
                else:
                    raw_exit = curr_o

                exit_p = round_to_tick(max(curr_l, min(curr_h, raw_exit)), tick_size)
                gross = (entry_p - exit_p) * multiplier * lots
                fee = (entry_p + exit_p) * multiplier * lots * fee_rate
                slip = slippage_ticks * tick_size * multiplier * lots
                net = gross - fee - slip

                available_cash += net
                if available_cash < 0:
                    bankruptcy_events += 1

                trades.append({
                    "symbol": symbol,
                    "side": "SHORT",
                    "entry_time": times[entry_idx],
                    "exit_time": times[i],
                    "entry_price": entry_p,
                    "exit_price": exit_p,
                    "lots": lots,
                    "holding_bars": i - entry_idx,
                    "regime": entry_regime,
                    "net_pnl": net,
                })
                position = 0

        # 2. 检查挂单回踩成交
        if position == 0 and pending_side != 0:
            if pending_side == 1 and curr_l <= pending_limit_p and not is_limit_up:
                position = 1
                entry_idx = i
                entry_p = min(curr_o, pending_limit_p)
                stop_p = pending_stop_p
                target_p = pending_target_p
                entry_regime = pending_regime
                risk_amt = abs(entry_p - stop_p) * multiplier
                lots = max(1, min(int((500_000 * 0.010) / (risk_amt + 1e-8)), 50))
                pending_side = 0
            elif pending_side == -1 and curr_h >= pending_limit_p and not is_limit_down:
                position = -1
                entry_idx = i
                entry_p = max(curr_o, pending_limit_p)
                stop_p = pending_stop_p
                target_p = pending_target_p
                entry_regime = pending_regime
                risk_amt = abs(entry_p - stop_p) * multiplier
                lots = max(1, min(int((500_000 * 0.010) / (risk_amt + 1e-8)), 50))
                pending_side = 0
            else:
                pending_timeout += 1
                if pending_timeout > 12:
                    pending_side = 0

        # 3. 信号检测与回踩挂单
        if position == 0 and pending_side == 0:
            if is_bull[i] and ss_slope[i] > 0.04:
                if b3[i] > 0 and zs_high[i] > 0:
                    pending_side = 1
                    pending_limit_p = round_to_tick(zs_high[i] + 0.2 * curr_atr, tick_size)
                    pending_stop_p = round_to_tick(zs_high[i] - 0.6 * curr_atr, tick_size)
                    pending_target_p = round_to_tick(pending_limit_p + 3.2 * curr_atr, tick_size)
                    pending_timeout = 0
                    pending_regime = regimes[i]
                elif b2[i] > 0:
                    pending_side = 1
                    pending_limit_p = round_to_tick(ema20[i], tick_size)
                    pending_stop_p = round_to_tick(ema20[i] - 0.8 * curr_atr, tick_size)
                    pending_target_p = round_to_tick(ema20[i] + 3.2 * curr_atr, tick_size)
                    pending_timeout = 0
                    pending_regime = regimes[i]

            elif is_bear[i] and ss_slope[i] < -0.04:
                if s3[i] > 0 and zs_low[i] > 0:
                    pending_side = -1
                    pending_limit_p = round_to_tick(zs_low[i] - 0.2 * curr_atr, tick_size)
                    pending_stop_p = round_to_tick(zs_low[i] + 0.6 * curr_atr, tick_size)
                    pending_target_p = round_to_tick(pending_limit_p - 3.2 * curr_atr, tick_size)
                    pending_timeout = 0
                    pending_regime = regimes[i]
                elif s2[i] > 0:
                    pending_side = -1
                    pending_limit_p = round_to_tick(ema20[i], tick_size)
                    pending_stop_p = round_to_tick(ema20[i] + 0.8 * curr_atr, tick_size)
                    pending_target_p = round_to_tick(ema20[i] - 3.2 * curr_atr, tick_size)
                    pending_timeout = 0
                    pending_regime = regimes[i]

    if not trades:
        return [], {}

    tdf = pd.DataFrame(trades)
    tot_trades = len(tdf)
    pnls = tdf["net_pnl"].values
    wins = pnls[pnls > 0]
    losses = np.abs(pnls[pnls < 0])
    win_rate = len(wins) / tot_trades
    tot_win = wins.sum() if len(wins) > 0 else 0.0
    tot_loss = losses.sum() if len(losses) > 0 else 0.0
    pf = float(tot_win / (tot_loss + 1e-8))
    net_pnl = float(pnls.sum())

    cum_pnl = np.cumsum(pnls)
    max_dd = float((np.maximum.accumulate(cum_pnl) - cum_pnl).max())

    regime_pnl = {}
    for t in trades:
        regime_pnl[t["regime"]] = regime_pnl.get(t["regime"], 0.0) + t["net_pnl"]

    summary = {
        "symbol": symbol,
        "name": spec.name,
        "timeframe": timeframe,
        "cost_multiplier": cost_multiplier,
        "trade_count": tot_trades,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(pf, 2),
        "net_pnl": round(net_pnl, 2),
        "total_win_rmb": round(float(tot_win), 2),
        "total_loss_rmb": round(float(tot_loss), 2),
        "max_drawdown": round(max_dd, 2),
        "bankruptcy_events": bankruptcy_events,
        "force_liquidations": force_liquidations,
        "regime_attribution": {k: round(v, 2) for k, v in regime_pnl.items()},
    }
    return trades, summary


def run_chanquant_v6_audit():
    provider = UnifiedDataProvider()
    symbols = [
        "RB_IDX", "HC_IDX", "I_IDX", "J_IDX", "JM_IDX",
        "CU_IDX", "AL_IDX", "ZN_IDX", "SN_IDX", "AG_IDX", "AU_IDX",
        "TA_IDX", "MA_IDX", "SA_IDX", "FG_IDX", "SC_IDX",
        "M_IDX", "Y_IDX", "P_IDX", "C_IDX", "CF_IDX", "SR_IDX", "RU_IDX", "LC_IDX", "SI_IDX"
    ]

    all_results = []
    print("🚀 Running ChanQuant 6.0 Full-Market Audit across 25 Commodities...")

    for sym in symbols:
        df_bars, meta = provider.load_or_generate_bars(sym, "15m", target_min_trades=1000)
        if df_bars.empty:
            continue

        _, sum_1x = backtest_chanquant_v6(df_bars, sym, timeframe="15m", cost_multiplier=1.0)
        _, sum_3x = backtest_chanquant_v6(df_bars, sym, timeframe="15m", cost_multiplier=3.0)

        if sum_1x.get("trade_count", 0) > 0:
            all_results.append({
                "symbol": sym,
                "name": sum_1x["name"],
                "timeframe": "15m",
                "meta": meta,
                "normal_1x": sum_1x,
                "stress_3x": sum_3x,
            })

    UnifiedReportFormatter.print_master_audit_table("ChanQuant_6.0_Alpha_Master", all_results)

    timestamp_str = time.strftime("%Y%m%d_%H%M%S")
    report_file = REPORTS_DIR / f"ChanQuant_6.0_Full_Market_Audit_{timestamp_str}.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump({
            "strategy_name": "ChanQuant_6.0_Alpha_Master",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_trades": sum(r["normal_1x"]["trade_count"] for r in all_results),
            "total_1x_pnl_rmb": round(sum(r["normal_1x"]["net_pnl"] for r in all_results), 2),
            "total_3x_pnl_rmb": round(sum(r["stress_3x"]["net_pnl"] for r in all_results), 2),
            "details": all_results,
        }, f, ensure_ascii=False, indent=2)

    print(f"📁 审计报告已归档至: {report_file}")


if __name__ == "__main__":
    run_chanquant_v6_audit()
