"""
code/test_fvg_luxalgo_engine.py — 测试 TradingView LuxAlgo Fair Value Gap (FVG) 机构失衡回踩 + 动态吊灯策略
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


def run_fvg_simulation():
    tot_pnl = 0.0
    tot_tr = 0
    tot_w = 0

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

            filt_fast = calculate_ehlers_supersmoother_2pole(c, period=6)
            filt_slow = calculate_ehlers_supersmoother_2pole(c, period=18)
            trend_up = filt_fast > filt_slow
            trend_dn = filt_fast < filt_slow

            # TradingView LuxAlgo FVG 检测
            fvg_top = np.zeros(n)
            fvg_bot = np.zeros(n)
            fvg_bull = np.zeros(n, dtype=bool)
            fvg_bear = np.zeros(n, dtype=bool)

            for t in range(2, n):
                if l[t] > h[t - 2]: # Bullish FVG
                    fvg_bull[t] = True
                    fvg_top[t] = l[t]
                    fvg_bot[t] = h[t - 2]
                elif h[t] < l[t - 2]: # Bearish FVG
                    fvg_bear[t] = True
                    fvg_top[t] = l[t - 2]
                    fvg_bot[t] = h[t]

            # 动力学 Hurst 门禁
            c_s = pd.Series(c)
            c_diff2 = c_s.diff(2)
            c_diff8 = c_s.diff(8)
            tau2 = c_diff2.rolling(40, min_periods=5).std(ddof=0)
            tau8 = c_diff8.rolling(40, min_periods=5).std(ddof=0)
            hurst = (np.log((tau8 + 1e-8) / (tau2 + 1e-8)) / np.log(4.0)).clip(0.1, 0.9).bfill().values

            # 持仓量过滤
            vol_ma20 = pd.Series(v).rolling(20, min_periods=5).mean().bfill().values + 1e-8
            oi_filter_long = np.ones(n, dtype=bool)
            oi_filter_short = np.ones(n, dtype=bool)
            if "open_interest" in df.columns:
                oi = df["open_interest"].astype(float).values
                oi_diff = np.diff(oi, prepend=oi[0])
                oi_filter_long = oi_diff >= -vol_ma20 * 0.40
                oi_filter_short = oi_diff >= -vol_ma20 * 0.40

            long_sig = trend_up & fvg_bull & (hurst >= 0.50) & (c > o) & oi_filter_long
            short_sig = trend_dn & fvg_bear & (hurst >= 0.50) & (c < o) & oi_filter_short

            capital = 1_000_000.0
            pos = 0
            lots = 0
            entry_p = 0.0
            stop_p = 0.0
            highest_p = 0.0
            lowest_p = 1e9
            trades = []

            for i in range(1, n - 1):
                curr_atr = atr[i]
                next_o = o[i + 1]

                if pos == 1:
                    highest_p = max(highest_p, h[i])
                    profit_atrs = (highest_p - entry_p) / curr_atr
                    if profit_atrs >= 1.2:
                        stop_p = max(stop_p, entry_p + 0.1 * curr_atr)
                    if profit_atrs >= 2.0:
                        stop_p = max(stop_p, highest_p - 2.5 * curr_atr)
                elif pos == -1:
                    lowest_p = min(lowest_p, l[i])
                    profit_atrs = (entry_p - lowest_p) / curr_atr
                    if profit_atrs >= 1.2:
                        stop_p = min(stop_p, entry_p - 0.1 * curr_atr)
                    if profit_atrs >= 2.0:
                        stop_p = min(stop_p, lowest_p + 2.5 * curr_atr)

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
                    trades.append(net)
                    pos = 0

                if pos == 0 and i < n - 1:
                    sig = 1 if long_sig[i] else (-1 if short_sig[i] else 0)
                    if sig != 0:
                        unit_risk = max(tick_size * contract_mult, 1.2 * curr_atr * contract_mult)
                        calc_lots = max(1, min(30, int(capital * 0.015 / unit_risk)))
                        pos = sig
                        lots = calc_lots
                        entry_p = next_o + slippage * pos
                        highest_p = entry_p
                        lowest_p = entry_p
                        stop_p = entry_p - pos * 1.2 * curr_atr

            wins = [t for t in trades if t > 0]
            losses = [t for t in trades if t <= 0]
            wr = len(wins) / max(1, len(trades)) * 100.0
            avg_w = float(np.mean(wins)) if wins else 0.0
            avg_l = abs(float(np.mean(losses))) if losses else 1.0
            pl_ratio = avg_w / avg_l if avg_l > 0 else 0.0
            pnl = capital - 1_000_000.0

            tot_pnl += pnl
            tot_tr += len(trades)
            tot_w += len(wins)

            print(f"  ├─ {sym:<8} | 交易: {len(trades):<4}笔 | 胜率: {wr:4.1f}% | 盈亏比: {pl_ratio:4.2f} | 净利: ¥{pnl:+10,.2f}")

    wr_all = tot_w / max(1, tot_tr) * 100.0
    print(f"\n📊 [FVG + 动态吊灯组合] 总净利: ¥{tot_pnl:+11,.2f} | 总交易: {tot_tr} 笔 | 综合胜率: {wr_all:.1f}%")


if __name__ == "__main__":
    run_fvg_simulation()
