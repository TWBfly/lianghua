"""
code/run_chanquant_v7_full_audit.py — 缠论量化 7.0 全市场 25 大主力品种全周期大数定律与 1x正常 vs 3x极限压力测试终极审计
"""

from __future__ import annotations

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
from causal_chan_engine import CausalChanEngine
from chanquant_v7_master_strategy import calculate_factors_v7, TREND_CORE_SYMBOLS
from unified_backtest_pipeline import UnifiedDataProvider, UnifiedReportFormatter, round_to_tick, REPORTS_DIR



def backtest_chanquant_v7(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str = "15m",
    cost_multiplier: float = 1.0,
    capital: float = 500_000.0,
    target_risk_pct: float = 0.010,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    spec = get_spec(symbol)
    multiplier = spec.multiplier
    fee_rate = spec.fee_rate * cost_multiplier
    tick_size = spec.tick_size
    margin_rate = spec.margin_rate
    slippage_ticks = 2 * cost_multiplier
    n = len(df)

    if n < 80:
        return [], {}

    factors = calculate_factors_v7(df)
    if factors.empty or len(factors) < 80:
        return [], {}


    atr = factors["atr"].values
    ema20 = factors["ema20"].values
    ema60 = factors["ema60"].values
    ema240 = factors["ema240"].values
    k_pos = factors["k_pos"].values
    k_vel_norm = factors["k_vel_norm"].values
    pe = factors["pe"].values
    hurst = factors["hurst"].values
    engine = CausalChanEngine(atr_k=0.0, strict_bi_bars=4)

    events = engine.process_dataframe(df)
    events_by_idx: Dict[int, Any] = {}

    for ev in events:
        idx = ev.known_raw_idx
        if 0 <= idx < n:
            events_by_idx[idx] = ev

    opens = df["open"].astype(float).values
    highs = df["high"].astype(float).values
    lows = df["low"].astype(float).values
    closes = df["close"].astype(float).values
    times = df["trade_time"].astype(str).values

    is_trend_sym = symbol in TREND_CORE_SYMBOLS

    trades = []
    pos = 0
    trade_mode = 0
    entry_p = 0.0
    stop_p = 0.0
    target_p = 0.0
    best_p = 0.0
    entry_idx = 0
    lots = 1
    is_be_locked = False

    available_cash = capital
    bankruptcy_events = 0
    force_liquidations = 0

    for i in range(2, n):
        curr_o = round_to_tick(opens[i], tick_size)
        curr_h = round_to_tick(highs[i], tick_size)
        curr_l = round_to_tick(lows[i], tick_size)
        curr_c = round_to_tick(closes[i], tick_size)
        prev_c = round_to_tick(closes[i - 1], tick_size)
        curr_atr = max(tick_size, atr[i])

        is_limit_up = (curr_h - curr_l < 1e-4) and (curr_c >= prev_c * 1.059)
        is_limit_down = (curr_h - curr_l < 1e-4) and (curr_c <= prev_c * 0.941)

        # 1. 持仓出场与动态风险管理
        if pos == 1:
            unrealized = (curr_c - entry_p) * multiplier * lots
            equity = available_cash + unrealized
            margin_occ = curr_c * multiplier * lots * margin_rate
            risk_ratio = margin_occ / max(equity, 1e-6)
            is_force_liq = (risk_ratio >= 1.20 or equity <= margin_occ * 0.5)

            if trade_mode == 1:  # 宏观动量岛: 动态保本 + 2.5 ATR 宽幅动态吊灯放飞右尾
                if curr_h > best_p:
                    best_p = curr_h
                if not is_be_locked and (best_p - entry_p) >= 1.2 * curr_atr:
                    stop_p = max(stop_p, entry_p + 0.2 * curr_atr)
                    is_be_locked = True
                if (best_p - entry_p) >= 2.2 * curr_atr:
                    stop_p = max(stop_p, best_p - 2.5 * curr_atr)

                is_stopped = (curr_l <= stop_p)
                is_expired = ((i - entry_idx) >= 160)

                if (is_stopped or is_expired or is_force_liq) and not is_limit_down:
                    if is_force_liq:
                        force_liquidations += 1
                        raw_exit = curr_o
                    elif is_stopped:
                        raw_exit = curr_o if curr_o <= stop_p else stop_p
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
                        "mode": "TREND_MOMENTUM",
                        "entry_time": times[entry_idx],
                        "exit_time": times[i],
                        "entry_price": entry_p,
                        "exit_price": exit_p,
                        "lots": lots,
                        "holding_bars": i - entry_idx,
                        "net_pnl": net,
                    })
                    pos = 0

            elif trade_mode == 2:  # 产业均值岛: 归轴止盈 + 0.75 ATR 紧致硬止损
                is_tp = (curr_h >= target_p)
                is_stopped = (curr_l <= stop_p)
                is_expired = ((i - entry_idx) >= 25)

                if (is_tp or is_stopped or is_expired or is_force_liq) and not is_limit_down:
                    if is_force_liq:
                        force_liquidations += 1
                        raw_exit = curr_o
                    elif is_tp:
                        raw_exit = curr_o if curr_o >= target_p else target_p
                    elif is_stopped:
                        raw_exit = curr_o if curr_o <= stop_p else stop_p
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
                        "mode": "MEAN_REVERSION",
                        "entry_time": times[entry_idx],
                        "exit_time": times[i],
                        "entry_price": entry_p,
                        "exit_price": exit_p,
                        "lots": lots,
                        "holding_bars": i - entry_idx,
                        "net_pnl": net,
                    })
                    pos = 0

        elif pos == -1:
            unrealized = (entry_p - curr_c) * multiplier * lots
            equity = available_cash + unrealized
            margin_occ = curr_c * multiplier * lots * margin_rate
            risk_ratio = margin_occ / max(equity, 1e-6)
            is_force_liq = (risk_ratio >= 1.20 or equity <= margin_occ * 0.5)

            if trade_mode == 1:
                if curr_l < best_p:
                    best_p = curr_l
                if not is_be_locked and (entry_p - best_p) >= 1.2 * curr_atr:
                    stop_p = min(stop_p, entry_p - 0.2 * curr_atr)
                    is_be_locked = True
                if (entry_p - best_p) >= 2.2 * curr_atr:
                    stop_p = min(stop_p, best_p + 2.5 * curr_atr)

                is_stopped = (curr_h >= stop_p)
                is_expired = ((i - entry_idx) >= 160)

                if (is_stopped or is_expired or is_force_liq) and not is_limit_up:
                    if is_force_liq:
                        force_liquidations += 1
                        raw_exit = curr_o
                    elif is_stopped:
                        raw_exit = curr_o if curr_o >= stop_p else stop_p
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
                        "mode": "TREND_MOMENTUM",
                        "entry_time": times[entry_idx],
                        "exit_time": times[i],
                        "entry_price": entry_p,
                        "exit_price": exit_p,
                        "lots": lots,
                        "holding_bars": i - entry_idx,
                        "net_pnl": net,
                    })
                    pos = 0

            elif trade_mode == 2:
                is_tp = (curr_l <= target_p)
                is_stopped = (curr_h >= stop_p)
                is_expired = ((i - entry_idx) >= 25)

                if (is_tp or is_stopped or is_expired or is_force_liq) and not is_limit_up:
                    if is_force_liq:
                        force_liquidations += 1
                        raw_exit = curr_o
                    elif is_tp:
                        raw_exit = curr_o if curr_o <= target_p else target_p
                    elif is_stopped:
                        raw_exit = curr_o if curr_o >= stop_p else stop_p
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
                        "mode": "MEAN_REVERSION",
                        "entry_time": times[entry_idx],
                        "exit_time": times[i],
                        "entry_price": entry_p,
                        "exit_price": exit_p,
                        "lots": lots,
                        "holding_bars": i - entry_idx,
                        "net_pnl": net,
                    })
                    pos = 0

        # 2. 开仓信号检测 (严格 Next-Open 撮合)
        if pos == 0 and (i - 1) in events_by_idx:
            ev = events_by_idx[i - 1]
            p_e = pe[i - 1]
            h_u = hurst[i - 1]
            v_k = k_vel_norm[i - 1]

            if is_trend_sym:
                is_macro_bull = (closes[i - 1] >= ema60[i - 1]) and (ema60[i - 1] >= ema240[i - 1]) and (v_k > 0.03)
                is_macro_bear = (closes[i - 1] <= ema60[i - 1]) and (ema60[i - 1] <= ema240[i - 1]) and (v_k < -0.03)

                if ev.event_type == "B3" and is_macro_bull and ev.zs_high > 0:
                    pos = 1
                    trade_mode = 1
                    entry_p = curr_o
                    stop_p = round_to_tick(min(ev.trigger_price - 0.2 * curr_atr, ev.zs_high - 0.4 * curr_atr), tick_size)
                    best_p = entry_p
                    entry_idx = i
                    is_be_locked = False
                    risk_dist = max(abs(entry_p - stop_p), 0.6 * curr_atr)
                    risk_amt = risk_dist * multiplier
                    max_margin_lots = max(1, int((capital * 0.20) / (entry_p * multiplier * margin_rate + 1e-8)))
                    lots = max(1, min(int((capital * target_risk_pct) / (risk_amt + 1e-8)), max_margin_lots, 5))


                elif ev.event_type == "B2" and is_macro_bull and (closes[i - 1] >= ema20[i - 1]):
                    pos = 1
                    trade_mode = 1
                    entry_p = curr_o
                    stop_p = round_to_tick(ev.trigger_price - 0.3 * curr_atr, tick_size)
                    best_p = entry_p
                    entry_idx = i
                    is_be_locked = False
                    risk_dist = max(abs(entry_p - stop_p), 0.6 * curr_atr)
                    risk_amt = risk_dist * multiplier
                    max_margin_lots = max(1, int((capital * 0.20) / (entry_p * multiplier * margin_rate + 1e-8)))
                    lots = max(1, min(int((capital * target_risk_pct) / (risk_amt + 1e-8)), max_margin_lots, 5))


                elif ev.event_type == "S3" and is_macro_bear and ev.zs_low > 0:
                    pos = -1
                    trade_mode = 1
                    entry_p = curr_o
                    stop_p = round_to_tick(max(ev.trigger_price + 0.2 * curr_atr, ev.zs_low + 0.4 * curr_atr), tick_size)
                    best_p = entry_p
                    entry_idx = i
                    is_be_locked = False
                    risk_dist = max(abs(entry_p - stop_p), 0.6 * curr_atr)
                    risk_amt = risk_dist * multiplier
                    max_margin_lots = max(1, int((capital * 0.20) / (entry_p * multiplier * margin_rate + 1e-8)))
                    lots = max(1, min(int((capital * target_risk_pct) / (risk_amt + 1e-8)), max_margin_lots, 5))


                elif ev.event_type == "S2" and is_macro_bear and (closes[i - 1] <= ema20[i - 1]):
                    pos = -1
                    trade_mode = 1
                    entry_p = curr_o
                    stop_p = round_to_tick(ev.trigger_price + 0.3 * curr_atr, tick_size)
                    best_p = entry_p
                    entry_idx = i
                    is_be_locked = False
                    risk_dist = max(abs(entry_p - stop_p), 0.6 * curr_atr)
                    risk_amt = risk_dist * multiplier
                    max_margin_lots = max(1, int((capital * 0.20) / (entry_p * multiplier * margin_rate + 1e-8)))
                    lots = max(1, min(int((capital * target_risk_pct) / (risk_amt + 1e-8)), max_margin_lots, 5))


            else:
                # 产业均值回归岛: 严格在中枢极值边界偏离 >= 1.25 ATR 处低吸高抛
                if ev.zs_high > 0 and ev.zs_low > 0:
                    zs_mid = (ev.zs_high + ev.zs_low) * 0.5
                    dev = abs(closes[i - 1] - k_pos[i - 1]) / curr_atr

                    if (ev.event_type == "B1" or closes[i - 1] <= ev.zs_low) and closes[i - 1] < zs_mid and dev >= 1.25:
                        tgt_p = round_to_tick(zs_mid, tick_size)
                        if tgt_p > curr_o + 1.1 * curr_atr:
                            pos = 1
                            trade_mode = 2
                            entry_p = curr_o
                            target_p = tgt_p
                            stop_p = round_to_tick(entry_p - 0.75 * curr_atr, tick_size)
                            entry_idx = i
                            risk_dist = max(abs(entry_p - stop_p), 0.6 * curr_atr)
                            risk_amt = risk_dist * multiplier
                            max_margin_lots = max(1, int((capital * 0.20) / (entry_p * multiplier * margin_rate + 1e-8)))
                            lots = max(1, min(int((capital * target_risk_pct) / (risk_amt + 1e-8)), max_margin_lots, 5))


                    elif (ev.event_type == "S1" or closes[i - 1] >= ev.zs_high) and closes[i - 1] > zs_mid and dev >= 1.25:
                        tgt_p = round_to_tick(zs_mid, tick_size)
                        if tgt_p < curr_o - 1.1 * curr_atr:
                            pos = -1
                            trade_mode = 2
                            entry_p = curr_o
                            target_p = tgt_p
                            stop_p = round_to_tick(entry_p + 0.75 * curr_atr, tick_size)
                            entry_idx = i
                            risk_dist = max(abs(entry_p - stop_p), 0.6 * curr_atr)
                            risk_amt = risk_dist * multiplier
                            max_margin_lots = max(1, int((capital * 0.20) / (entry_p * multiplier * margin_rate + 1e-8)))
                            lots = max(1, min(int((capital * target_risk_pct) / (risk_amt + 1e-8)), max_margin_lots, 5))



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

    regime_pnl: Dict[str, float] = {}
    for t in trades:
        reg = t.get("mode", "UNKNOWN")
        regime_pnl[reg] = regime_pnl.get(reg, 0.0) + t["net_pnl"]

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



def run_chanquant_v7_audit():
    provider = UnifiedDataProvider()
    symbols = [
        "RB_IDX", "HC_IDX", "I_IDX", "J_IDX", "JM_IDX",
        "CU_IDX", "AL_IDX", "ZN_IDX", "SN_IDX", "AG_IDX", "AU_IDX",
        "TA_IDX", "MA_IDX", "SA_IDX", "FG_IDX", "SC_IDX",
        "M_IDX", "Y_IDX", "P_IDX", "C_IDX", "CF_IDX", "SR_IDX", "RU_IDX", "LC_IDX", "SI_IDX"
    ]

    all_results = []
    print("🚀 Running ChanQuant 7.0 Full-Market Audit across 25 Commodities...")

    for sym in symbols:
        df_bars, meta = provider.load_or_generate_bars(sym, "15m", target_min_trades=1000)
        if df_bars.empty:
            continue

        _, sum_1x = backtest_chanquant_v7(df_bars, sym, timeframe="15m", cost_multiplier=1.0)
        _, sum_3x = backtest_chanquant_v7(df_bars, sym, timeframe="15m", cost_multiplier=3.0)

        if sum_1x.get("trade_count", 0) > 0:
            all_results.append({
                "symbol": sym,
                "name": sum_1x["name"],
                "timeframe": "15m",
                "meta": meta,
                "normal_1x": sum_1x,
                "stress_3x": sum_3x,
            })

    UnifiedReportFormatter.print_master_audit_table("ChanQuant_7.0_Master", all_results)

    timestamp_str = time.strftime("%Y%m%d_%H%M%S")
    report_file = REPORTS_DIR / f"ChanQuant_7.0_Full_Market_Audit_{timestamp_str}.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump({
            "strategy_name": "ChanQuant_7.0_Master",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_trades": sum(r["normal_1x"]["trade_count"] for r in all_results),
            "total_1x_pnl_rmb": round(sum(r["normal_1x"]["net_pnl"] for r in all_results), 2),
            "total_3x_pnl_rmb": round(sum(r["stress_3x"]["net_pnl"] for r in all_results), 2),
            "details": all_results,
        }, f, ensure_ascii=False, indent=2)

    print(f"📁 审计报告已归档至: {report_file}")


if __name__ == "__main__":
    run_chanquant_v7_audit()
