"""
code/run_taiwei_kalman_deep_audit.py — 「太微·卡尔曼动力学小波相变与订单流失衡策略」工业级大数定律深度因果审计
(Taiwei Kalman Kinematics & Microstructure FVG Deep LLN Audit)

核心验证：
- 摒弃唐奇安与传统 SuperTrend 滞后指标，全面实装卡尔曼 3 态运动学 + 排列熵确定性 + LuxAlgo FVG 失衡；
- 10 大主力品种 30m 周期全历史 70/30 OOS 盲测；
- 120,000+ Bar 物理隔离全周期合成大数定律检验；
- 16 组参数平原扰动与 3 倍摩擦极端压测。
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
from strategies.taiwei_kalman_wavelet_bocpd_strategy import (
    calculate_kalman_kinematics,
    calculate_permutation_entropy,
    calculate_fvg_liquidity_voids
)

DB_PATH = str(DATA_DIR / "ashare_quant.db")
TARGET_SYMBOLS = ["AG_IDX", "AU_IDX", "LC_IDX", "SN_IDX", "CU_IDX", "SC_IDX", "RB_IDX", "TA_IDX", "MA_IDX", "P_IDX"]


def simulate_taiwei_kalman(
    df: pd.DataFrame,
    sym: str,
    vel_th: float = 0.20,
    pe_th: float = 0.65,
    trail_atr_mult: float = 2.5,
    sl_atr_mult: float = 1.2,
    friction_mult: float = 1.0,
    capital_init: float = 1_000_000.0
) -> Dict[str, Any]:
    c = df["close"].astype(float).values
    o = df["open"].astype(float).values
    h = df["high"].astype(float).values
    l = df["low"].astype(float).values
    v = df["volume"].astype(float).values
    n = len(df)

    spec = ACTIVE_CONTRACT_SPECS.get(sym, {"multiplier": 10.0, "tick": 1.0, "fee_rate": 0.0001, "margin_rate": 0.12})
    contract_mult = float(spec.get("multiplier", 10.0))
    tick_size = float(spec.get("tick", 1.0))
    fee_rate = float(spec.get("fee_rate", 0.0001)) * friction_mult
    slippage = tick_size * friction_mult

    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    atr = pd.Series(tr).rolling(14, min_periods=5).mean().bfill().values + 1e-8

    # 1. 卡尔曼连续状态空间运动学
    k_pos, k_vel, k_acc = calculate_kalman_kinematics(c)
    k_vel_norm = k_vel / atr

    # 2. 排列熵确定性度量
    pe = calculate_permutation_entropy(c, order=3, window=30)
    is_laminar = pe <= pe_th

    # 3. LuxAlgo FVG 失衡
    bull_fvg, bear_fvg = calculate_fvg_liquidity_voids(h, l, c)
    had_bull_fvg = pd.Series(bull_fvg).rolling(6, min_periods=1).max().values == 1.0
    had_bear_fvg = pd.Series(bear_fvg).rolling(6, min_periods=1).max().values == 1.0

    # 4. 动力学 Hurst
    c_s = pd.Series(c)
    c_diff2 = c_s.diff(2)
    c_diff8 = c_s.diff(8)
    tau2 = c_diff2.rolling(40, min_periods=5).std(ddof=0)
    tau8 = c_diff8.rolling(40, min_periods=5).std(ddof=0)
    hurst = (np.log((tau8 + 1e-8) / (tau2 + 1e-8)) / np.log(4.0)).clip(0.1, 0.9).bfill().values

    vol_ma20 = pd.Series(v).rolling(20, min_periods=5).mean().bfill().values + 1e-8
    oi_filter = np.ones(n, dtype=bool)
    if "open_interest" in df.columns:
        oi = df["open_interest"].astype(float).values
        oi_diff = np.diff(oi, prepend=oi[0])
        oi_filter = oi_diff >= -vol_ma20 * 0.40

    sig_long = (k_vel_norm >= vel_th) & (k_acc > 0) & is_laminar & had_bull_fvg & (hurst >= 0.50) & (c > o) & oi_filter
    sig_short = (k_vel_norm <= -vel_th) & (k_acc < 0) & is_laminar & had_bear_fvg & (hurst >= 0.50) & (c < o) & oi_filter

    capital = capital_init
    pos = 0
    lots = 0
    entry_p = 0.0
    stop_p = 0.0
    highest_p = 0.0
    lowest_p = 1e9
    trades = []
    equity_curve = [capital]

    for i in range(1, n - 1):
        curr_atr = atr[i]
        next_o = o[i + 1]

        if pos == 1:
            highest_p = max(highest_p, h[i])
            profit_atrs = (highest_p - entry_p) / curr_atr
            if profit_atrs >= 1.0:
                stop_p = max(stop_p, entry_p + 0.1 * curr_atr) # 动态保本
            if profit_atrs >= 1.8:
                stop_p = max(stop_p, highest_p - trail_atr_mult * curr_atr) # 动态吊灯
            unrealized = (c[i] - entry_p) * contract_mult * lots
        elif pos == -1:
            lowest_p = min(lowest_p, l[i])
            profit_atrs = (entry_p - lowest_p) / curr_atr
            if profit_atrs >= 1.0:
                stop_p = min(stop_p, entry_p - 0.1 * curr_atr)
            if profit_atrs >= 1.8:
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
            elif sig_short[i]:
                exit_reason = 2
                exit_price = next_o - slippage
        elif pos == -1:
            if h[i] >= stop_p:
                exit_reason = 1
                exit_price = max(stop_p, o[i]) + slippage
            elif sig_long[i]:
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
            if sig_long[i]:
                unit_risk = max(tick_size * contract_mult, sl_atr_mult * curr_atr * contract_mult)
                calc_lots = max(1, min(30, int(capital * 0.015 / unit_risk)))
                pos = 1
                lots = calc_lots
                entry_p = next_o + slippage
                highest_p = entry_p
                lowest_p = entry_p
                stop_p = entry_p - sl_mult * curr_atr if 'sl_mult' in locals() else entry_p - sl_atr_mult * curr_atr
            elif sig_short[i]:
                unit_risk = max(tick_size * contract_mult, sl_atr_mult * curr_atr * contract_mult)
                calc_lots = max(1, min(30, int(capital * 0.015 / unit_risk)))
                pos = -1
                lots = calc_lots
                entry_p = next_o - slippage
                highest_p = entry_p
                lowest_p = entry_p
                stop_p = entry_p + sl_mult * curr_atr if 'sl_mult' in locals() else entry_p + sl_atr_mult * curr_atr

    wins = [t for t in trades if t > 0]
    wr = len(wins) / max(1, len(trades)) * 100.0
    net_pnl = capital - capital_init

    eq_arr = np.array(equity_curve)
    peak = np.maximum.accumulate(eq_arr)
    dd_arr = np.where(peak > 0, (peak - eq_arr) / peak, 0.0)
    max_dd = float(np.max(dd_arr) * 100.0) if len(dd_arr) > 0 else 0.0

    bar_rets = np.diff(eq_arr) / (eq_arr[:-1] + 1e-8) if len(eq_arr) > 1 else np.array([0.0])
    annual_factor = np.sqrt(4662)
    sharpe = (np.mean(bar_rets) / (np.std(bar_rets) + 1e-8)) * annual_factor if len(bar_rets) > 1 and np.std(bar_rets) > 0 else 0.0

    return {
        "pnl": net_pnl,
        "trades_count": len(trades),
        "wr": wr,
        "max_dd": max_dd,
        "sharpe": sharpe,
        "trades_list": trades,
        "equity_curve": equity_curve
    }


def main():
    print(f"\n{'='*95}")
    print(f"🚀 【「太微·卡尔曼动力学小波相变与订单流失衡策略」 工业级大数定律深度因果审计】")
    print(f"{'='*95}")

    # Track A
    print(f"\n📈 【模块 1: Track A 真实历史基准轨 (30m 真实 K 线 70/30 OOS 盲测)】")
    print(f"{'='*95}")
    print(f"{'品种':<8} | {'IS 交易':<8} | {'IS 胜率':<8} | {'IS 净利':<14} | {'OOS 交易':<8} | {'OOS 胜率':<8} | {'OOS 净利':<14} | {'OOS 夏普':<8} | {'平原通过率'}")
    print(f"{'-'*95}")

    tot_is_pnl = 0.0
    tot_oos_pnl = 0.0
    tot_is_tr = 0
    tot_oos_tr = 0
    track_a_dict = {}

    with sqlite3.connect(DB_PATH) as conn:
        for sym in TARGET_SYMBOLS:
            q = "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars WHERE symbol = ? AND timeframe = '30m' ORDER BY trade_time ASC;"
            df = pd.read_sql_query(q, conn, params=(sym,))
            if df.empty or len(df) < 200:
                continue
            n = len(df)
            split_idx = int(n * 0.70)
            df_is = df.iloc[:split_idx].reset_index(drop=True)
            df_oos = df.iloc[split_idx + 20:].reset_index(drop=True)

            res_is = simulate_taiwei_kalman(df_is, sym)
            res_oos = simulate_taiwei_kalman(df_oos, sym)

            tot_is_pnl += res_is["pnl"]
            tot_oos_pnl += res_oos["pnl"]
            tot_is_tr += res_is["trades_count"]
            tot_oos_tr += res_oos["trades_count"]

            # 平原测试
            plat_pass = 0
            for d_vel in [-0.05, 0.0, 0.05, 0.10]:
                for d_trail in [-0.5, 0.0, 0.5, 1.0]:
                    r_p = simulate_taiwei_kalman(df_oos, sym, vel_th=max(0.10, 0.20 + d_vel), trail_atr_mult=max(1.8, 2.5 + d_trail))
                    if r_p["pnl"] >= res_oos["pnl"] * 0.70 or r_p["pnl"] > 0:
                        plat_pass += 1
            plat_ratio = plat_pass / 16.0 * 100.0

            track_a_dict[sym] = {"is": res_is, "oos": res_oos, "plat": plat_ratio}
            print(f"{sym:<8} | {res_is['trades_count']:<8} | {res_is['wr']:5.1f}%  | ¥{res_is['pnl']:+12,.2f} | {res_oos['trades_count']:<8} | {res_oos['wr']:5.1f}%  | ¥{res_oos['pnl']:+12,.2f} | {res_oos['sharpe']:5.2f}    | {plat_ratio:5.1f}%")

    print(f"{'-'*95}")
    print(f"{'组合汇总':<8} | {tot_is_tr:<8} | {'-':<8} | ¥{tot_is_pnl:+12,.2f} | {tot_oos_tr:<8} | {'-':<8} | ¥{tot_oos_pnl:+12,.2f} | {'-':<8} | {'-'}")

    # Track B
    print(f"\n🔬 【模块 2: Track B 物理隔离全周期合成大数定律轨 (LLN 120,000+ Bar/品种)】")
    print(f"{'='*95}")

    generator = SyntheticMarketRegimeGenerator(seed=2026)
    all_trades_pool = []
    tot_syn_pnl = 0.0
    tot_syn_tr = 0
    tot_3x_pnl = 0.0

    for sym in TARGET_SYMBOLS:
        spec = ACTIVE_CONTRACT_SPECS.get(sym, {"multiplier": 10.0, "tick": 1.0, "fee_rate": 0.0001})
        base_price = 7000.0 if "AG" in sym else (600.0 if "AU" in sym else (70000.0 if "CU" in sym else 3500.0))

        df_syn = generator.generate_regime_bars(
            symbol=sym,
            start_price=base_price,
            bars_per_regime=30000,
            tick_size=float(spec.get("tick", 1.0)),
            timeframe="30m"
        )

        res_norm = simulate_taiwei_kalman(df_syn, sym, friction_mult=1.0)
        res_3x = simulate_taiwei_kalman(df_syn, sym, friction_mult=3.0)

        tot_syn_pnl += res_norm["pnl"]
        tot_syn_tr += res_norm["trades_count"]
        tot_3x_pnl += res_3x["pnl"]
        all_trades_pool.extend(res_norm["trades_list"])

        print(f"  ├─ {sym:<8} | 合成 Bar: {len(df_syn):6d} | 交易: {res_norm['trades_count']:5d} 笔 | 胜率: {res_norm['wr']:4.1f}% | 净利: ¥{res_norm['pnl']:+12,.2f} | 3倍摩擦净利: ¥{res_3x['pnl']:+12,.2f}")

    print(f"\n📊 Track B 大数定律全景汇总: 10 品种总交易 {tot_syn_tr:,} 笔 | 总净利润: ¥{tot_syn_pnl:+12,.2f} | 3倍摩擦总净利: ¥{tot_3x_pnl:+12,.2f}")


if __name__ == "__main__":
    main()
