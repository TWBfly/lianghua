"""
code/test_taiwei_chandelier_resonance.py — 测试太微多尺度小波共振与动态 Chandelier 跟踪止损
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


def compute_causal_modwt_3level(prices: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = len(prices)
    if n < 8:
        return np.zeros(n), np.zeros(n), np.zeros(n), prices.copy()

    a1 = np.zeros(n)
    d1 = np.zeros(n)
    a1[0] = prices[0]
    for t in range(1, n):
        a1[t] = 0.5 * (prices[t] + prices[t - 1])
        d1[t] = 0.5 * (prices[t] - prices[t - 1])

    a2 = np.zeros(n)
    d2 = np.zeros(n)
    a2[:2] = a1[:2]
    for t in range(2, n):
        a2[t] = 0.5 * (a1[t] + a1[t - 2])
        d2[t] = 0.5 * (a1[t] - a1[t - 2])

    a3 = np.zeros(n)
    d3 = np.zeros(n)
    a3[:4] = a2[:4]
    for t in range(4, n):
        a3[t] = 0.5 * (a2[t] + a2[t - 4])
        d3[t] = 0.5 * (a2[t] - a2[t - 4])

    return d1, d2, d3, a3


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


def run_taiwei_test(timeframe="30m", sl_mult=1.2, be_mult=1.2, trail_mult=1.8):
    symbols = ["AG_IDX", "AU_IDX", "CU_IDX", "SC_IDX", "RB_IDX", "TA_IDX", "MA_IDX", "LC_IDX", "SN_IDX", "P_IDX"]
    tot_pnl = 0.0
    tot_trades = 0
    tot_wins = 0

    for sym in symbols:
        with sqlite3.connect(DB_PATH) as conn:
            q = "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars WHERE symbol = ? AND timeframe = ? ORDER BY trade_time ASC;"
            df = pd.read_sql_query(q, conn, params=(sym, timeframe))
        if df.empty or len(df) < 200:
            continue
        df["datetime"] = pd.to_datetime(df["trade_time"])
        df = df.sort_values("datetime").reset_index(drop=True)

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

        d1, d2, d3, a3 = compute_causal_modwt_3level(c)

        window = 40
        d1_sq = pd.Series(d1 ** 2).rolling(window, min_periods=5).mean().bfill().values
        d2_sq = pd.Series(d2 ** 2).rolling(window, min_periods=5).mean().bfill().values
        d3_sq = pd.Series(d3 ** 2).rolling(window, min_periods=5).mean().bfill().values

        a3_s = pd.Series(a3)
        a3_mean = a3_s.rolling(window, min_periods=5).mean().bfill().values
        a3_sq = pd.Series((a3 - a3_mean) ** 2).rolling(window, min_periods=5).mean().bfill().values

        e_detail = d1_sq + d2_sq + d3_sq
        e_total = e_detail + a3_sq + 1e-8
        wavelet_squeeze = e_detail / e_total
        had_squeeze = pd.Series(wavelet_squeeze).rolling(6, min_periods=1).min().values <= 0.35

        a3_smooth = calculate_ehlers_supersmoother_2pole(a3, period=10)
        a3_slope = np.zeros(n)
        a3_slope[2:] = (a3_smooth[2:] - a3_smooth[:-2]) / (atr[2:] * np.sqrt(2.0))

        c_s = pd.Series(c)
        c_diff2 = c_s.diff(2)
        c_diff8 = c_s.diff(8)
        tau2 = c_diff2.rolling(window, min_periods=5).std(ddof=0)
        tau8 = c_diff8.rolling(window, min_periods=5).std(ddof=0)
        hurst = (np.log((tau8 + 1e-8) / (tau2 + 1e-8)) / np.log(4.0)).clip(0.1, 0.9).bfill().values

        filt_fast = calculate_ehlers_supersmoother_2pole(c, period=6)
        filt_slow = calculate_ehlers_supersmoother_2pole(c, period=18)
        dsp_trend_up = filt_fast > filt_slow
        dsp_trend_dn = filt_fast < filt_slow

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

        # 多尺度小波共振 (D2 + D3 + A3 速度同向)
        long_sig = (
            dsp_trend_up &
            (c > a3_smooth) &
            (a3_slope >= 0.10) &
            (d2 >= 0) &
            (d3 >= 0) &
            had_squeeze &
            (hurst >= 0.50) &
            (c > o) &
            (body_ratio >= 0.40) &
            oi_filter_long
        )

        short_sig = (
            dsp_trend_dn &
            (c < a3_smooth) &
            (a3_slope <= -0.10) &
            (d2 <= 0) &
            (d3 <= 0) &
            had_squeeze &
            (hurst >= 0.50) &
            (c < o) &
            (body_ratio >= 0.40) &
            oi_filter_short
        )

        capital = 1_000_000.0
        pos = 0
        lots = 0
        entry_p = 0.0
        stop_p = 0.0
        highest_p = 0.0
        lowest_p = 1e9
        trades = []

        for i in range(1, n - 1):
            curr_p = c[i]
            curr_atr = atr[i]
            next_o = o[i + 1]

            if pos == 1:
                highest_p = max(highest_p, h[i])
                profit_atrs = (highest_p - entry_p) / curr_atr
                if profit_atrs >= be_mult:
                    stop_p = max(stop_p, entry_p + 0.1 * curr_atr)
                if profit_atrs >= (be_mult + 0.8):
                    stop_p = max(stop_p, highest_p - trail_mult * curr_atr)
            elif pos == -1:
                lowest_p = min(lowest_p, l[i])
                profit_atrs = (entry_p - lowest_p) / curr_atr
                if profit_atrs >= be_mult:
                    stop_p = min(stop_p, entry_p - 0.1 * curr_atr)
                if profit_atrs >= (be_mult + 0.8):
                    stop_p = min(stop_p, lowest_p + trail_mult * curr_atr)

            exit_reason = None
            exit_price = 0.0

            if pos == 1:
                if l[i] <= stop_p:
                    exit_reason = "stop"
                    exit_price = min(stop_p, o[i]) - slippage
                elif short_sig[i]:
                    exit_reason = "rev"
                    exit_price = next_o - slippage
            elif pos == -1:
                if h[i] >= stop_p:
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
                trades.append({"net": net, "win": net > 0})
                pos = 0

            if pos == 0 and i < n - 1:
                sig = 1 if long_sig[i] else (-1 if short_sig[i] else 0)
                if sig != 0:
                    unit_risk = max(tick_size * contract_mult, sl_mult * curr_atr * contract_mult)
                    calc_lots = max(1, min(30, int(capital * 0.015 / unit_risk)))
                    pos = sig
                    lots = calc_lots
                    entry_p = next_o + slippage * pos
                    highest_p = entry_p
                    lowest_p = entry_p
                    stop_p = entry_p - pos * sl_mult * curr_atr

        wins = [t for t in trades if t["win"]]
        tot_pnl += (capital - 1_000_000.0)
        tot_trades += len(trades)
        tot_wins += len(wins)
        wr = len(wins) / max(1, len(trades)) * 100.0
        print(f"  ├─ {sym:<8} | 交易: {len(trades):<4}笔 | 胜率: {wr:4.1f}% | 净利: ¥{capital - 1_000_000.0:+10,.2f}")

    wr_all = tot_wins / max(1, tot_trades) * 100.0
    print(f"\n📊 周期 [{timeframe}] 组合总净利: ¥{tot_pnl:+,.2f} | 总交易: {tot_trades} 笔 | 综合胜率: {wr_all:.1f}%")


if __name__ == "__main__":
    for tf in ["15m", "30m"]:
        print(f"\n{'='*80}\n🚀 测试周期: {tf}\n{'='*80}")
        run_taiwei_test(timeframe=tf)
