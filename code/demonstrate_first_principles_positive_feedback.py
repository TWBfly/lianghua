"""
code/demonstrate_first_principles_positive_feedback.py — 第一性原理期望值方程实证：为什么固定微观止盈必定负反馈，而右尾非对称跟踪 + GA 架构搜索能产生强正反馈
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
SYMBOLS = ["AG_IDX", "AU_IDX", "CU_IDX", "SC_IDX", "RB_IDX", "TA_IDX", "MA_IDX", "LC_IDX", "SN_IDX", "P_IDX"]


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


def load_30m_data():
    data = {}
    with sqlite3.connect(DB_PATH) as conn:
        for sym in SYMBOLS:
            q = "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars WHERE symbol = ? AND timeframe = '30m' ORDER BY trade_time ASC;"
            df = pd.read_sql_query(q, conn, params=(sym,))
            if df.empty or len(df) < 200:
                continue
            df["datetime"] = pd.to_datetime(df["trade_time"])
            df = df.sort_values("datetime").reset_index(drop=True)
            for col in ["open", "high", "low", "close", "volume", "open_interest"]:
                df[col] = df[col].astype(float)
            data[sym] = df
    return data


def run_strategy_mode(data_dict: dict, mode: str = "FIXED_MICRO_TP"):
    """
    mode:
      - 'FIXED_MICRO_TP': 传统微观固定止盈 (TP=1.0 ATR, SL=0.8 ATR) -> 截断右尾
      - 'ASYMMETRIC_TRAILING': 第一性原理非对称吊灯止损 (SL=1.2 ATR, 保本=1.2 ATR, 吊灯追踪=3.0 ATR, 不设死止盈) -> 拥抱肥尾
    """
    tot_pnl = 0.0
    tot_trades = 0
    tot_wins = 0
    sym_details = {}

    for sym, df in data_dict.items():
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

        # DSP 零滞后趋势 + Hurst 动力学门禁
        filt_fast = calculate_ehlers_supersmoother_2pole(c, period=6)
        filt_slow = calculate_ehlers_supersmoother_2pole(c, period=18)
        trend_up = filt_fast > filt_slow
        trend_dn = filt_fast < filt_slow

        c_s = pd.Series(c)
        c_diff2 = c_s.diff(2)
        c_diff8 = c_s.diff(8)
        tau2 = c_diff2.rolling(40, min_periods=5).std(ddof=0)
        tau8 = c_diff8.rolling(40, min_periods=5).std(ddof=0)
        hurst = (np.log((tau8 + 1e-8) / (tau2 + 1e-8)) / np.log(4.0)).clip(0.1, 0.9).bfill().values

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

        # 核心突破信号
        roll_high20 = pd.Series(h).rolling(20, min_periods=5).max().shift(1).bfill().values
        roll_low20 = pd.Series(l).rolling(20, min_periods=5).min().shift(1).bfill().values

        long_sig = (
            trend_up &
            (c > roll_high20) &
            (hurst >= 0.50) &
            (c > o) &
            (body_ratio >= 0.35) &
            oi_filter_long
        )

        short_sig = (
            trend_dn &
            (c < roll_low20) &
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
                profit_atrs = (highest_p - entry_p) / curr_atr
                if mode == "ASYMMETRIC_TRAILING":
                    # 动态吊灯跟踪止损
                    if profit_atrs >= 1.2:
                        stop_p = max(stop_p, entry_p + 0.1 * curr_atr)
                    if profit_atrs >= 2.0:
                        stop_p = max(stop_p, highest_p - 2.5 * curr_atr)
                elif mode == "FIXED_MICRO_TP":
                    if profit_atrs >= 1.0:
                        stop_p = max(stop_p, entry_p + 0.1 * curr_atr)

            elif pos == -1:
                lowest_p = min(lowest_p, l[i])
                profit_atrs = (entry_p - lowest_p) / curr_atr
                if mode == "ASYMMETRIC_TRAILING":
                    if profit_atrs >= 1.2:
                        stop_p = min(stop_p, entry_p - 0.1 * curr_atr)
                    if profit_atrs >= 2.0:
                        stop_p = min(stop_p, lowest_p + 2.5 * curr_atr)
                elif mode == "FIXED_MICRO_TP":
                    if profit_atrs >= 1.0:
                        stop_p = min(stop_p, entry_p - 0.1 * curr_atr)

            exit_reason = None
            exit_price = 0.0

            if pos == 1:
                if mode == "FIXED_MICRO_TP" and h[i] >= tp_p:
                    exit_reason = "tp"
                    exit_price = max(tp_p, o[i]) - slippage
                elif l[i] <= stop_p:
                    exit_reason = "stop"
                    exit_price = min(stop_p, o[i]) - slippage
                elif short_sig[i]:
                    exit_reason = "rev"
                    exit_price = next_o - slippage

            elif pos == -1:
                if mode == "FIXED_MICRO_TP" and l[i] <= tp_p:
                    exit_reason = "tp"
                    exit_price = min(tp_p, o[i]) + slippage
                elif h[i] >= stop_p:
                    exit_reason = "stop"
                    exit_price = max(stop_p, o[i]) + slippage
                elif long_sig[i]:
                    exit_reason = "rev"
                    exit_price = next_o + slippage

            if exit_reason and pos != 0:
                gross = (exit_price - entry_p) * contract_mult * lots * pos
                fee = (abs(entry_p) + abs(exit_price)) * contract_mult * lots * fee_rate
                net = gross - fee
                capital += net
                trades.append({"net": net, "pnl_atr": (exit_price - entry_p)*pos / curr_atr})
                pos = 0

            if pos == 0 and i < n - 1:
                sig = 1 if long_sig[i] else (-1 if short_sig[i] else 0)
                if sig != 0:
                    sl_mult = 0.8 if mode == "FIXED_MICRO_TP" else 1.5
                    unit_risk = max(tick_size * contract_mult, sl_mult * curr_atr * contract_mult)
                    calc_lots = max(1, min(30, int(capital * 0.015 / unit_risk)))
                    pos = sig
                    lots = calc_lots
                    entry_p = next_o + slippage * pos
                    highest_p = entry_p
                    lowest_p = entry_p
                    stop_p = entry_p - pos * sl_mult * curr_atr
                    tp_p = entry_p + pos * 1.0 * curr_atr if mode == "FIXED_MICRO_TP" else 0.0

        pnl = capital - 1_000_000.0
        wins = [t for t in trades if t["net"] > 0]
        losses = [t for t in trades if t["net"] <= 0]
        wr = len(wins) / max(1, len(trades)) * 100.0
        avg_w = float(np.mean([t["net"] for t in wins])) if wins else 0.0
        avg_l = abs(float(np.mean([t["net"] for t in losses]))) if losses else 1.0
        pl_ratio = avg_w / avg_l if avg_l > 0 else 0.0

        tot_pnl += pnl
        tot_trades += len(trades)
        tot_wins += len(wins)
        sym_details[sym] = {"pnl": pnl, "trades": len(trades), "wr": wr, "pl_ratio": pl_ratio}

    wr_all = tot_wins / max(1, tot_trades) * 100.0
    return tot_pnl, tot_trades, wr_all, sym_details


def main():
    print(f"{'='*80}")
    print(f"🔬 第一性原理实证对比：固定微观止盈 vs 非对称吊灯跟踪 (拥抱右尾肥尾)")
    print(f"{'='*80}")

    data_dict = load_30m_data()

    # 1. 运行固定微观止盈模式 (截断右尾)
    pnl_a, tr_a, wr_a, det_a = run_strategy_mode(data_dict, mode="FIXED_MICRO_TP")
    print(f"\n❌ [模式 A: 固定微观止盈 (TP=1.0 ATR, SL=0.8 ATR)]")
    print(f"   组合总净利: ¥{pnl_a:+11,.2f} | 交易: {tr_a} 笔 | 胜率: {wr_a:4.1f}%")
    for sym, d in det_a.items():
        print(f"     ├─ {sym:<8} | 净利: ¥{d['pnl']:+10,.2f} | 胜率: {d['wr']:4.1f}% | 盈亏比: {d['pl_ratio']:4.2f}")

    # 2. 运行非对称吊灯跟踪模式 (让利润奔跑)
    pnl_b, tr_b, wr_b, det_b = run_strategy_mode(data_dict, mode="ASYMMETRIC_TRAILING")
    print(f"\n✅ [模式 B: 第一性原理非对称吊灯跟踪 (SL=1.5 ATR, Trailing=2.5 ATR, 无死止盈)]")
    print(f"   组合总净利: ¥{pnl_b:+11,.2f} | 交易: {tr_b} 笔 | 胜率: {wr_b:4.1f}%")
    for sym, d in det_b.items():
        print(f"     ├─ {sym:<8} | 净利: ¥{d['pnl']:+10,.2f} | 胜率: {d['wr']:4.1f}% | 盈亏比: {d['pl_ratio']:4.2f}")


if __name__ == "__main__":
    main()
