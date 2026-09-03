"""
code/run_tianji_v2_optimized_deep_audit.py — 「天极·双岛策略 V2.0 终极实证版」全息因果深度回测与 V1/V2 综合对比打分报告
(Tianji V2.0 Holy Grail Deep Audit & Comparative 100-Point Scorecard)
"""

from __future__ import annotations

import os
import sys
import math
import copy
import json
import sqlite3
import datetime
import warnings
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple, Any

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CODE_DIR = PROJECT_ROOT / "code"
STRATEGIES_DIR = PROJECT_ROOT / "strategies"
DATA_DIR = PROJECT_ROOT / "data"

for p in (PROJECT_ROOT, CODE_DIR, STRATEGIES_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from run_tianji_strict_1000_trades_per_symbol import ACTIVE_CONTRACT_SPECS
from synthetic_market_regime_generator import SyntheticMarketRegimeGenerator
from strategies.tianji_v2_optimized_master_strategy import (
    STRATEGY_FULL_NAME,
    TIER1_TREND_SYMBOLS,
    TIER1_REVERT_SYMBOLS,
    TIER1_ALL_SYMBOLS,
    calculate_reversion_factors
)

DB_PATH = str(DATA_DIR / "ashare_quant.db")


def build_tianji_scorecard(total_pnl: float, is_pnl: float, oos_pnl: float):
    """Build a scorecard only from evidence this script actually measures."""
    profitable = math.isfinite(total_pnl) and total_pnl > 0.0
    generalized = (
        math.isfinite(is_pnl)
        and math.isfinite(oos_pnl)
        and is_pnl > 0.0
        and oos_pnl > 0.0
    )
    return [
        (
            "维度 1: 绝对与超额收益力 (Alpha PnL)",
            20,
            20.0 if profitable else 0.0,
            f"实测全历史净利 ¥{total_pnl:+,.2f}",
        ),
        (
            "维度 2: 极端尾部与回撤控制力 (Risk Control)",
            15,
            0.0,
            "未提供可独立复核的组合级尾部风险证据",
        ),
        (
            "维度 3: 样本外泛化与防过拟合 (OOS Generalization)",
            15,
            15.0 if generalized else 0.0,
            f"实测 IS ¥{is_pnl:+,.2f} / OOS ¥{oos_pnl:+,.2f}",
        ),
        ("维度 4: 参数稳定性", 15, 0.0, "未提供独立保留集参数稳定性证据"),
        ("维度 5: 统计置信度", 10, 0.0, "未提供可验证统计门禁"),
        ("维度 6: 摩擦鲁棒性", 10, 0.0, "未提供组合级压力成本门禁"),
        ("维度 7: 正交多样性", 10, 0.0, "未提供组合收益相关性证据"),
        ("维度 8: 因果与账本", 5, 0.0, "未提供独立账本对账门禁"),
    ]


def build_tianji_audit_gates(
    total_pnl: float,
    is_pnl: float,
    oos_pnl: float,
    total_score: float,
):
    checks = (
        ("positive_full_sample", total_pnl > 0.0, total_pnl, "> 0"),
        ("positive_is", is_pnl > 0.0, is_pnl, "> 0"),
        ("positive_oos", oos_pnl > 0.0, oos_pnl, "> 0"),
        ("approval_score", total_score >= 85.0, total_score, ">= 85"),
    )
    gates = [
        {
            "id": gate_id,
            "passed": bool(math.isfinite(observed) and passed),
            "observed": observed,
            "required": required,
        }
        for gate_id, passed, observed, required in checks
    ]
    return gates, (
        "BACKTEST_VALIDATED"
        if all(gate["passed"] for gate in gates)
        else "REJECTED"
    )


def resample_to_4h(df_30m: pd.DataFrame) -> pd.DataFrame:
    df = df_30m.copy()
    df["datetime"] = pd.to_datetime(df["trade_time"])
    df = df.set_index("datetime")
    df_4h = df.resample("4h").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "open_interest": "last"
    }).dropna().reset_index()
    df_4h["trade_time"] = df_4h["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return df_4h.drop(columns=["datetime"])


# ==============================================================================
# 4H 宏观单边岛仿真器 (AU, AG, LC, SN)
# ==============================================================================

def simulate_4h_macro_trend(
    df_4h: pd.DataFrame,
    sym: str,
    period: int = 20,
    trail_atr_mult: float = 3.0,
    sl_atr_mult: float = 2.0,
    friction_mult: float = 1.0,
    capital_init: float = 1_000_000.0
) -> Dict[str, Any]:
    c = df_4h["close"].astype(float).values
    o = df_4h["open"].astype(float).values
    h = df_4h["high"].astype(float).values
    l = df_4h["low"].astype(float).values
    n = len(df_4h)

    spec = ACTIVE_CONTRACT_SPECS.get(sym, {"multiplier": 10.0, "tick": 1.0, "fee_rate": 0.0001})
    contract_mult = float(spec.get("multiplier", 10.0))
    tick_size = float(spec.get("tick", 1.0))
    fee_rate = float(spec.get("fee_rate", 0.0001)) * friction_mult
    slippage = tick_size * friction_mult

    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    atr = pd.Series(tr).rolling(14, min_periods=5).mean().ffill().fillna(1.0).values + 1e-8
    hh = pd.Series(h).rolling(period, min_periods=5).max().shift(1).ffill().fillna(h[0]).values
    ll = pd.Series(l).rolling(period, min_periods=5).min().shift(1).ffill().fillna(l[0]).values

    capital = capital_init
    pos = 0
    lots = 0
    entry_p = 0.0
    stop_p = 0.0
    highest_p = 0.0
    lowest_p = 1e9
    trades = []
    equity_curve = [capital]

    for i in range(period, n - 1):
        next_o = o[i + 1]
        curr_atr = atr[i]

        if pos == 1:
            highest_p = max(highest_p, h[i])
            stop_p = max(stop_p, highest_p - trail_atr_mult * curr_atr)
            unrealized = (c[i] - entry_p) * contract_mult * lots
        elif pos == -1:
            lowest_p = min(lowest_p, l[i])
            stop_p = min(stop_p, lowest_p + trail_atr_mult * curr_atr)
            unrealized = (entry_p - c[i]) * contract_mult * lots
        else:
            unrealized = 0.0

        equity_curve.append(max(0.0, capital + unrealized))

        exit_reason = 0
        exit_price = 0.0

        if pos == 1:
            if l[i] <= stop_p:
                exit_reason = 1
                exit_price = min(stop_p, o[i]) - slippage
            elif c[i] < ll[i]:
                exit_reason = 2
                exit_price = next_o - slippage
        elif pos == -1:
            if h[i] >= stop_p:
                exit_reason = 1
                exit_price = max(stop_p, o[i]) + slippage
            elif c[i] > hh[i]:
                exit_reason = 2
                exit_price = next_o + slippage

        if exit_reason != 0 and pos != 0:
            gross = (exit_price - entry_p) * contract_mult * lots * pos
            fee = (abs(entry_p) + abs(exit_price)) * contract_mult * lots * fee_rate
            net = gross - fee
            capital += net
            trades.append(net)
            pos = 0

        if pos == 0 and i < n - 1:
            unit_risk = max(tick_size * contract_mult * 2.0, sl_atr_mult * curr_atr * contract_mult)
            calc_lots = max(1, min(30, int(capital * 0.02 / unit_risk)))

            if c[i] > hh[i]:
                pos = 1
                lots = calc_lots
                entry_p = next_o + slippage
                highest_p = entry_p
                lowest_p = entry_p
                stop_p = entry_p - sl_atr_mult * curr_atr
            elif c[i] < ll[i]:
                pos = -1
                lots = calc_lots
                entry_p = next_o - slippage
                highest_p = entry_p
                lowest_p = entry_p
                stop_p = entry_p + sl_atr_mult * curr_atr

    wins = [t for t in trades if t > 0]
    wr = len(wins) / max(1, len(trades)) * 100.0
    net_pnl = capital - capital_init

    eq_arr = np.array(equity_curve)
    peak = np.maximum.accumulate(eq_arr)
    dd_arr = np.where(peak > 0, (peak - eq_arr) / peak, 0.0)
    max_dd = float(np.max(dd_arr) * 100.0) if len(dd_arr) > 0 else 0.0
    if "trade_time" in df_4h.columns and len(equity_curve) > 1:
        date_series = pd.to_datetime(df_4h["trade_time"]).dt.date.iloc[:len(equity_curve)]
        eq_df = pd.DataFrame({"date": date_series, "equity": equity_curve})
        daily_eq = eq_df.groupby("date")["equity"].last().values
        daily_rets = np.diff(daily_eq) / (daily_eq[:-1] + 1e-8) if len(daily_eq) > 1 else np.array([0.0])
        daily_std = np.std(daily_rets)
        sharpe = float((np.mean(daily_rets) / (daily_std + 1e-8)) * np.sqrt(252)) if len(daily_rets) > 1 and daily_std > 0 else 0.0
    else:
        bar_rets = np.diff(eq_arr) / (eq_arr[:-1] + 1e-8) if len(eq_arr) > 1 else np.array([0.0])
        bar_std = np.std(bar_rets)
        sharpe = float((np.mean(bar_rets) / (bar_std + 1e-8)) * np.sqrt(252)) if len(bar_rets) > 1 and bar_std > 0 else 0.0

    gross_profit = sum(t for t in trades if t > 0)
    gross_loss = abs(sum(t for t in trades if t < 0))
    profit_factor = round(gross_profit / max(1.0, gross_loss), 2) if gross_loss > 0 else 99.0

    return {
        "pnl": net_pnl,
        "trades_count": len(trades),
        "wr": wr,
        "max_dd": max_dd,
        "sharpe": sharpe,
        "profit_factor": profit_factor,
        "trades_list": trades,
        "equity_curve": equity_curve
    }


# ==============================================================================
# 30m 产业均值岛仿真器 (P, TA, SC, MA)
# ==============================================================================

def simulate_30m_reversion_v2(
    df_30m: pd.DataFrame,
    sym: str,
    alpha_th: float = 0.85,
    sl_atr_mult: float = 1.2,
    friction_mult: float = 1.0,
    capital_init: float = 1_000_000.0
) -> Dict[str, Any]:
    c = df_30m["close"].astype(float).values
    o = df_30m["open"].astype(float).values
    h = df_30m["high"].astype(float).values
    l = df_30m["low"].astype(float).values
    n = len(df_30m)

    spec = ACTIVE_CONTRACT_SPECS.get(sym, {"multiplier": 10.0, "tick": 1.0, "fee_rate": 0.0001})
    contract_mult = float(spec.get("multiplier", 10.0))
    tick_size = float(spec.get("tick", 1.0))
    fee_rate = float(spec.get("fee_rate", 0.0001)) * friction_mult
    slippage = tick_size * friction_mult

    factors_df = calculate_reversion_factors(df_30m)
    alpha = factors_df["composite_alpha"].values
    atr = factors_df["atr"].values

    sig_long = alpha <= -alpha_th
    sig_short = alpha >= alpha_th

    capital = capital_init
    pos = 0
    lots = 0
    entry_p = 0.0
    stop_p = 0.0
    trades = []
    equity_curve = [capital]

    for i in range(1, n - 1):
        curr_atr = atr[i]
        next_o = o[i + 1]

        unrealized = (c[i] - entry_p) * contract_mult * lots * pos if pos != 0 else 0.0
        equity_curve.append(max(0.0, capital + unrealized))

        exit_reason = 0
        exit_price = 0.0

        if pos == 1:
            if l[i] <= stop_p:
                exit_reason = 2
                exit_price = min(stop_p, o[i]) - slippage
            elif alpha[i] >= 0.0:
                exit_reason = 1
                exit_price = next_o - slippage
        elif pos == -1:
            if h[i] >= stop_p:
                exit_reason = 2
                exit_price = max(stop_p, o[i]) + slippage
            elif alpha[i] <= 0.0:
                exit_reason = 1
                exit_price = next_o + slippage

        if exit_reason != 0 and pos != 0:
            gross = (exit_price - entry_p) * contract_mult * lots * pos
            fee = (abs(entry_p) + abs(exit_price)) * contract_mult * lots * fee_rate
            net = gross - fee
            capital += net
            trades.append(net)
            pos = 0

        if pos == 0 and i < n - 1:
            unit_risk = max(tick_size * contract_mult, sl_atr_mult * curr_atr * contract_mult)
            calc_lots = max(1, min(30, int(capital * 0.015 / unit_risk)))

            if sig_long[i]:
                pos = 1
                lots = calc_lots
                entry_p = next_o + slippage
                stop_p = entry_p - sl_atr_mult * curr_atr
            elif sig_short[i]:
                pos = -1
                lots = calc_lots
                entry_p = next_o - slippage
                stop_p = entry_p + sl_atr_mult * curr_atr

    wins = [t for t in trades if t > 0]
    wr = len(wins) / max(1, len(trades)) * 100.0
    net_pnl = capital - capital_init

    eq_arr = np.array(equity_curve)
    peak = np.maximum.accumulate(eq_arr)
    dd_arr = np.where(peak > 0, (peak - eq_arr) / peak, 0.0)
    max_dd = float(np.max(dd_arr) * 100.0) if len(dd_arr) > 0 else 0.0

    if "trade_time" in df_30m.columns and len(equity_curve) > 1:
        date_series = pd.to_datetime(df_30m["trade_time"]).dt.date.iloc[:len(equity_curve)]
        eq_df = pd.DataFrame({"date": date_series, "equity": equity_curve})
        daily_eq = eq_df.groupby("date")["equity"].last().values
        daily_rets = np.diff(daily_eq) / (daily_eq[:-1] + 1e-8) if len(daily_eq) > 1 else np.array([0.0])
        daily_std = np.std(daily_rets)
        sharpe = float((np.mean(daily_rets) / (daily_std + 1e-8)) * np.sqrt(252)) if len(daily_rets) > 1 and daily_std > 0 else 0.0
    else:
        bar_rets = np.diff(eq_arr) / (eq_arr[:-1] + 1e-8) if len(eq_arr) > 1 else np.array([0.0])
        bar_std = np.std(bar_rets)
        sharpe = float((np.mean(bar_rets) / (bar_std + 1e-8)) * np.sqrt(252)) if len(bar_rets) > 1 and bar_std > 0 else 0.0

    gross_profit = sum(t for t in trades if t > 0)
    gross_loss = abs(sum(t for t in trades if t < 0))
    profit_factor = round(gross_profit / max(1.0, gross_loss), 2) if gross_loss > 0 else 99.0

    return {
        "pnl": net_pnl,
        "trades_count": len(trades),
        "wr": wr,
        "max_dd": max_dd,
        "sharpe": sharpe,
        "profit_factor": profit_factor,
        "trades_list": trades,
        "equity_curve": equity_curve
    }


def run_comparative_deep_audit():
    print(f"\n{'='*100}")
    print(f"👑 【{STRATEGY_FULL_NAME} 360 度全息深度因果审计与 V1/V2 综合对比打分报告】")
    print(f"{'='*100}")

    # 1. Track A 真实全历史基准轨审计
    print(f"\n📈 【模块 1: Track A 真实全历史基准轨全息审计 (70% IS 训练 vs 30% OOS 盲测)】")
    print(f"{'='*100}")
    print(f"{'品种代码':<8} | {'归属模式与级别':<16} | {'全历史总净利 (¥)':<16} | {'IS 净利 (70%)':<14} | {'OOS 盲测 (30%)':<14} | {'胜率':<8} | {'盈亏比':<8} | {'最大回撤':<8} | {'平原通过率'}")
    print(f"{'-'*100}")

    v2_results = {}
    tot_all_pnl = 0.0
    tot_is_pnl = 0.0
    tot_oos_pnl = 0.0
    tot_trades = 0

    with sqlite3.connect(DB_PATH) as conn:
        for sym in TIER1_ALL_SYMBOLS:
            is_trend = sym in TIER1_TREND_SYMBOLS
            label = "4H 宏观趋势岛" if is_trend else "30m 产业均值岛"

            q = "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars WHERE symbol = ? AND timeframe = '30m' ORDER BY trade_time ASC;"
            df_raw = pd.read_sql_query(q, conn, params=(sym,))
            if df_raw.empty or len(df_raw) < 200:
                continue

            df = resample_to_4h(df_raw) if is_trend else df_raw.copy()
            n = len(df)
            split_idx = int(n * 0.70)
            df_is = df.iloc[:split_idx].reset_index(drop=True)
            df_oos = df.iloc[split_idx + 20:].reset_index(drop=True)

            if is_trend:
                res_all = simulate_4h_macro_trend(df, sym)
                res_is = simulate_4h_macro_trend(df_is, sym)
                res_oos = simulate_4h_macro_trend(df_oos, sym)
            else:
                res_all = simulate_30m_reversion_v2(df, sym)
                res_is = simulate_30m_reversion_v2(df_is, sym)
                res_oos = simulate_30m_reversion_v2(df_oos, sym)

            tot_all_pnl += res_all["pnl"]
            tot_is_pnl += res_is["pnl"]
            tot_oos_pnl += res_oos["pnl"]
            tot_trades += res_all["trades_count"]

            # 16 组平原扰动测试
            plat_pass = 0
            for d_p in [-4, 0, 4, 8]:
                for d_trail in [-0.5, 0.0, 0.5, 1.0]:
                    if is_trend:
                        r_p = simulate_4h_macro_trend(df_oos, sym, period=max(12, 20 + d_p), trail_atr_mult=max(2.0, 3.0 + d_trail))
                    else:
                        r_p = simulate_30m_reversion_v2(df_oos, sym, alpha_th=max(0.60, 0.85 + d_trail * 0.2))
                    if r_p["pnl"] >= res_oos["pnl"] * 0.70 or r_p["pnl"] > 0:
                        plat_pass += 1
            plat_ratio = plat_pass / 16.0 * 100.0

            v2_results[sym] = {"all": res_all, "is": res_is, "oos": res_oos, "plat": plat_ratio}
            print(f"{sym:<8} | {label:<16} | ¥{res_all['pnl']:+14,.2f} | ¥{res_is['pnl']:+12,.2f} | ¥{res_oos['pnl']:+12,.2f} | {res_all['wr']:5.1f}%  | {res_all['profit_factor']:5.2f}   | {res_all['max_dd']:5.2f}%  | {plat_ratio:5.1f}%")

    print(f"{'-'*100}")
    print(f"{'全盘总成':<8} | {'优选双岛V2总成':<16} | ¥{tot_all_pnl:+14,.2f} | ¥{tot_is_pnl:+12,.2f} | ¥{tot_oos_pnl:+12,.2f} | -      | -      | -      | -")

    # 2. V1 vs V2 深度对比看板
    print(f"\n📊 【模块 2: 天极 V1.0 原始版 vs 天极 V2.0 终极实证版 核心指标对比看板】")
    print(f"{'='*100}")
    print(f"{'核心评估维度':<24} | {'天极 V1.0 (优化前)':<24} | {'天极 V2.0 (终极实证版)':<24} | {'改善幅度 / 质变突破'}")
    print(f"{'-'*100}")
    print(f"{'全历史总净利润 (¥)':<24} | {'-¥ 2,161,697.57 (全盘亏损)':<24} | {f'¥ {tot_all_pnl:+,.2f}':<24} | {'按实测值判定'}")
    print(f"{'训练集 IS 70% 净利 (¥)':<24} | {'-¥ 2,161,697.57':<24} | {f'¥ {tot_is_pnl:+,.2f}':<24} | {'按实测值判定'}")
    print(f"{'样本外 OOS 30% 盲测 (¥)':<24} | {'+¥   358,295.37':<24} | {f'¥ {tot_oos_pnl:+,.2f}':<24} | {'按实测值判定'}")
    # 3. 100 分量化体检打分卡
    print(f"\n🏆 【模块 3: 工业级期货量化策略 100 分健康体检打分卡 (8 大核心维度)】")
    print(f"{'='*100}")

    score_card = build_tianji_scorecard(
        tot_all_pnl, tot_is_pnl, tot_oos_pnl
    )

    total_score = sum(item[2] for item in score_card)

    for name, max_s, act_s, desc in score_card:
        print(f"  ├─ {name:<42} | 满分: {max_s:4.1f} | 实得: {act_s:4.1f} 分 | 判定依据: {desc}")
    print(f"{'-'*100}")
    gates, verdict = build_tianji_audit_gates(
        tot_all_pnl, tot_is_pnl, tot_oos_pnl, total_score
    )
    print(f"  🎯 【综合体检总得分】: 【 {total_score:.1f} / 100.0 分 】  (结论: {verdict})")

    report_file = DATA_DIR / "tianji_v2_vs_v1_comparative_audit_report.json"
    full_report = {
        "strategy": STRATEGY_FULL_NAME,
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_pnl": tot_all_pnl,
        "is_pnl": tot_is_pnl,
        "oos_pnl": tot_oos_pnl,
        "total_score": total_score,
        "verdict": verdict,
        "gates": gates,
        "score_card": score_card,
        "v2_results": v2_results
    }
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(full_report, f, ensure_ascii=False, indent=2)
    print(f"\n💾 V1/V2 全息对比与打分报告已成功写入: {report_file}\n")


if __name__ == "__main__":
    run_comparative_deep_audit()
