"""
code/test_beiji_refined_engine.py — 北极·展期基差动量策略 精细化特征与出场测试
"""

import sys
import math
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "code"))
sys.path.insert(0, str(PROJECT_ROOT / "strategies"))

from run_tianji_strict_1000_trades_per_symbol import ACTIVE_CONTRACT_SPECS

DB_PATH = str(PROJECT_ROOT / "data" / "ashare_quant.db")


def calculate_ehlers_supersmoother_2pole(prices: np.ndarray, period: int = 12) -> np.ndarray:
    n = len(prices)
    if n < 4:
        return prices.copy()
    a1 = math.exp(-math.sqrt(2.0) * math.pi / period)
    b1 = 2.0 * a1 * math.cos(math.sqrt(2.0) * math.pi / period)
    c2 = b1
    c3 = -a1 * a1
    c1 = 1.0 - c2 - c3
    filt = np.zeros(n)
    filt[0] = prices[0]
    filt[1] = prices[1]
    for t in range(2, n):
        filt[t] = c1 * (prices[t] + prices[t - 1]) * 0.5 + c2 * filt[t - 1] + c3 * filt[t - 2]
    return filt


def run_beiji_single_symbol(df: pd.DataFrame, sym: str, tp_mult=1.0, sl_mult=0.8, be_mult=1.0):
    c = df["close"].values
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    v = df["volume"].values
    n = len(df)

    spec = ACTIVE_CONTRACT_SPECS.get(sym, {"multiplier": 10.0, "tick": 1.0, "fee_rate": 0.0001, "margin_rate": 0.12})
    contract_mult = float(spec.get("multiplier", 10.0))
    tick_size = float(spec.get("tick", 1.0))
    fee_rate = float(spec.get("fee_rate", 0.0001))
    slippage = tick_size

    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    atr = pd.Series(tr).rolling(14, min_periods=5).mean().bfill().values + 1e-8

    # 1. 基差代理与基差 Z-Score
    c_s = pd.Series(c)
    basis_raw = (c - c_s.rolling(80, min_periods=20).mean().bfill().values) / atr
    b_mean = pd.Series(basis_raw).rolling(80, min_periods=20).mean().bfill()
    b_std = pd.Series(basis_raw).rolling(80, min_periods=20).std(ddof=0).bfill() + 1e-8
    basis_z = ((basis_raw - b_mean) / b_std).values

    # 2. 动量与趋势物理效率
    mom_20 = c_s.pct_change(20).fillna(0.0).values
    net_diff = np.abs(c - np.roll(c, 20))
    path = pd.Series(np.abs(c - prev_c)).rolling(20, min_periods=5).sum().bfill().values + 1e-8
    ker = net_diff / path

    # 3. 标度律 Hurst
    c_diff2 = c_s.diff(2)
    c_diff8 = c_s.diff(8)
    tau2 = c_diff2.rolling(40, min_periods=5).std(ddof=0)
    tau8 = c_diff8.rolling(40, min_periods=5).std(ddof=0)
    hurst = (np.log((tau8 + 1e-8) / (tau2 + 1e-8)) / np.log(4.0)).clip(0.1, 0.9).bfill().values

    # 4. Ehlers 零滞后趋势
    filt_fast = calculate_ehlers_supersmoother_2pole(c, period=6)
    filt_slow = calculate_ehlers_supersmoother_2pole(c, period=18)
    trend_up = filt_fast > filt_slow
    trend_dn = filt_fast < filt_slow

    bar_range = np.maximum(1e-8, h - l)
    body_ratio = np.abs(c - o) / bar_range

    vol_ma20 = pd.Series(v).rolling(20, min_periods=5).mean().bfill().values + 1e-8
    oi_filter_long = np.ones(n, dtype=bool)
    oi_filter_short = np.ones(n, dtype=bool)
    if "open_interest" in df.columns:
        oi = df["open_interest"].astype(float).values
        oi_diff = np.diff(oi, prepend=oi[0])
        oi_filter_long = oi_diff >= -vol_ma20 * 0.35
        oi_filter_short = oi_diff >= -vol_ma20 * 0.35

    composite_score = 0.45 * basis_z + 0.35 * (mom_20 / (atr / c + 1e-8)) + 0.20 * ker

    long_cond = (
        trend_up &
        (composite_score >= 0.50) &
        (hurst >= 0.50) &
        (c > o) &
        (body_ratio >= 0.35) &
        oi_filter_long
    )

    short_cond = (
        trend_dn &
        (composite_score <= -0.50) &
        (hurst >= 0.50) &
        (c < o) &
        (body_ratio >= 0.35) &
        oi_filter_short
    )

    capital = 1_000_000.0
    pos = 0
    lots = 0
    entry_p = 0.0
    stop_p = 0.0
    tp_p = 0.0
    highest_p = 0.0
    lowest_p = 1e9
    trades = []

    for i in range(1, n - 1):
        curr_atr = atr[i]
        next_o = o[i + 1]

        if pos == 1:
            highest_p = max(highest_p, h[i])
            if (highest_p - entry_p) >= be_mult * curr_atr:
                stop_p = max(stop_p, entry_p + 0.1 * curr_atr)
        elif pos == -1:
            lowest_p = min(lowest_p, l[i])
            if (entry_p - lowest_p) >= be_mult * curr_atr:
                stop_p = min(stop_p, entry_p - 0.1 * curr_atr)

        exit_reason = None
        exit_price = 0.0

        if pos == 1:
            if h[i] >= tp_p:
                exit_reason = "tp"
                exit_price = max(tp_p, o[i]) - slippage
            elif l[i] <= stop_p:
                exit_reason = "sl"
                exit_price = min(stop_p, o[i]) - slippage
            elif short_cond[i]:
                exit_reason = "rev"
                exit_price = next_o - slippage
        elif pos == -1:
            if l[i] <= tp_p:
                exit_reason = "tp"
                exit_price = min(tp_p, o[i]) + slippage
            elif h[i] >= stop_p:
                exit_reason = "sl"
                exit_price = max(stop_p, o[i]) + slippage
            elif long_cond[i]:
                exit_reason = "rev"
                exit_price = next_o + slippage

        if exit_reason and pos != 0:
            gross = (exit_price - entry_p) * contract_mult * lots * pos
            fee = (abs(entry_p) + abs(exit_price)) * contract_mult * lots * fee_rate
            net = gross - fee
            capital += net
            trades.append({"net": net, "win": net > 0})
            pos = 0

        if pos == 0 and i < n - 1:
            sig = 1 if long_cond[i] else (-1 if short_cond[i] else 0)
            if sig != 0:
                unit_risk = max(tick_size * contract_mult, sl_mult * curr_atr * contract_mult)
                calc_lots = max(1, min(30, int(capital * 0.015 / unit_risk)))
                pos = sig
                lots = calc_lots
                entry_p = next_o + slippage * pos
                highest_p = entry_p
                lowest_p = entry_p
                stop_p = entry_p - pos * sl_mult * curr_atr
                tp_p = entry_p + pos * tp_mult * curr_atr

    wins = [t for t in trades if t["win"]]
    return capital - 1_000_000.0, len(trades), len(wins)


def main():
    symbols = ["AG_IDX", "AU_IDX", "CU_IDX", "SC_IDX", "RB_IDX", "TA_IDX", "MA_IDX", "LC_IDX", "SN_IDX", "P_IDX"]
    for tf in ["5m", "15m", "30m"]:
        print(f"\n{'='*80}\n🚀 测试周期: {tf}\n{'='*80}")
        tot_pnl = 0.0
        tot_tr = 0
        tot_w = 0
        for sym in symbols:
            with sqlite3.connect(DB_PATH) as conn:
                q = "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars WHERE symbol = ? AND timeframe = ? ORDER BY trade_time ASC;"
                df = pd.read_sql_query(q, conn, params=(sym, tf))
            if df.empty or len(df) < 200:
                continue
            df["datetime"] = pd.to_datetime(df["trade_time"])
            df = df.sort_values("datetime").reset_index(drop=True)
            for col in ["open", "high", "low", "close", "volume", "open_interest"]:
                df[col] = df[col].astype(float)

            pnl, tr, w = run_beiji_single_symbol(df, sym, tp_mult=1.0, sl_mult=0.8, be_mult=1.0)
            tot_pnl += pnl
            tot_tr += tr
            tot_w += w
            wr = w / max(1, tr) * 100.0
            print(f"  ├─ {sym:<8} | 交易: {tr:<4}笔 | 胜率: {wr:4.1f}% | 净利: ¥{pnl:+10,.2f}")

        wr_all = tot_w / max(1, tot_tr) * 100.0
        print(f"\n📊 周期 [{tf}] 组合总净利: ¥{tot_pnl:+,.2f} | 总交易: {tot_tr} 笔 | 综合胜率: {wr_all:.1f}%")


if __name__ == "__main__":
    main()
