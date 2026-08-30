"""
code/test_decoupled_regime_portfolio.py — 第一性原理资产与机制解耦组合实证：
趋势池 (AG, AU, LC, SN, CU, P) 运行 60m Ehlers SuperTrend + 弹性做市池 (RB, TA, MA) 运行太冲弹塑性均值回归
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

TREND_SYMBOLS = ["AG_IDX", "AU_IDX", "LC_IDX", "SN_IDX", "CU_IDX", "P_IDX"]
REVERT_SYMBOLS = ["RB_IDX", "TA_IDX", "MA_IDX", "SC_IDX"]


def calculate_ehlers_supersmoother_2pole(prices: np.ndarray, period: int = 14) -> np.ndarray:
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


def run_trend_symbol_60m(df60: pd.DataFrame, sym: str):
    c = df60["close"].values
    o = df60["open"].values
    h = df60["high"].values
    l = df60["low"].values
    n = len(df60)

    spec = ACTIVE_CONTRACT_SPECS.get(sym, {"multiplier": 10.0, "tick": 1.0, "fee_rate": 0.0001, "margin_rate": 0.12})
    contract_mult = float(spec.get("multiplier", 10.0))
    tick_size = float(spec.get("tick", 1.0))
    fee_rate = float(spec.get("fee_rate", 0.0001))
    slippage = tick_size

    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    atr = pd.Series(tr).rolling(14, min_periods=5).mean().bfill().values + 1e-8

    filt = calculate_ehlers_supersmoother_2pole(c, period=14)
    upper_band = filt + 2.5 * atr
    lower_band = filt - 2.5 * atr

    trend = np.zeros(n, dtype=int)
    for i in range(1, n):
        if c[i] > upper_band[i - 1]:
            trend[i] = 1
        elif c[i] < lower_band[i - 1]:
            trend[i] = -1
        else:
            trend[i] = trend[i - 1]

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
            if (highest_p - entry_p) >= 1.5 * curr_atr:
                stop_p = max(stop_p, entry_p + 0.2 * curr_atr)
            if (highest_p - entry_p) >= 2.5 * curr_atr:
                stop_p = max(stop_p, highest_p - 2.5 * curr_atr)
        elif pos == -1:
            lowest_p = min(lowest_p, l[i])
            if (entry_p - lowest_p) >= 1.5 * curr_atr:
                stop_p = min(stop_p, entry_p - 0.2 * curr_atr)
            if (entry_p - lowest_p) >= 2.5 * curr_atr:
                stop_p = min(stop_p, lowest_p + 2.5 * curr_atr)

        exit_reason = None
        exit_price = 0.0

        if pos == 1:
            if l[i] <= stop_p:
                exit_reason = "stop"
                exit_price = min(stop_p, o[i]) - slippage
            elif trend[i] == -1:
                exit_reason = "rev"
                exit_price = next_o - slippage
        elif pos == -1:
            if h[i] >= stop_p:
                exit_reason = "stop"
                exit_price = max(stop_p, o[i]) + slippage
            elif trend[i] == 1:
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
            if trend[i] == 1 and trend[i - 1] <= 0:
                unit_risk = max(tick_size * contract_mult, 1.2 * curr_atr * contract_mult)
                calc_lots = max(1, min(30, int(capital * 0.02 / unit_risk)))
                pos = 1
                lots = calc_lots
                entry_p = next_o + slippage
                highest_p = entry_p
                lowest_p = entry_p
                stop_p = entry_p - 1.2 * curr_atr
            elif trend[i] == -1 and trend[i - 1] >= 0:
                unit_risk = max(tick_size * contract_mult, 1.2 * curr_atr * contract_mult)
                calc_lots = max(1, min(30, int(capital * 0.02 / unit_risk)))
                pos = -1
                lots = calc_lots
                entry_p = next_o - slippage
                highest_p = entry_p
                lowest_p = entry_p
                stop_p = entry_p + 1.2 * curr_atr

    wins = [t for t in trades if t > 0]
    wr = len(wins) / max(1, len(trades)) * 100.0
    pnl = capital - 1_000_000.0
    return pnl, len(trades), wr


def run_revert_symbol_30m(df30: pd.DataFrame, sym: str):
    c = df30["close"].values
    o = df30["open"].values
    h = df30["high"].values
    l = df30["low"].values
    n = len(df30)

    spec = ACTIVE_CONTRACT_SPECS.get(sym, {"multiplier": 10.0, "tick": 1.0, "fee_rate": 0.0001, "margin_rate": 0.12})
    contract_mult = float(spec.get("multiplier", 10.0))
    tick_size = float(spec.get("tick", 1.0))
    fee_rate = float(spec.get("fee_rate", 0.0001))
    slippage = tick_size

    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    atr = pd.Series(tr).rolling(14, min_periods=5).mean().bfill().values + 1e-8

    filt = calculate_ehlers_supersmoother_2pole(c, period=20)
    dev_atrs = (c - filt) / atr

    long_sig = (dev_atrs <= -2.2) & (c > o)
    short_sig = (dev_atrs >= 2.2) & (c < o)

    capital = 1_000_000.0
    pos = 0
    lots = 0
    entry_p = 0.0
    stop_p = 0.0
    trades = []

    for i in range(1, n - 1):
        curr_atr = atr[i]
        next_o = o[i + 1]

        exit_reason = None
        exit_price = 0.0

        if pos == 1:
            if c[i] >= filt[i]: # 回归均线平仓
                exit_reason = "target"
                exit_price = next_o - slippage
            elif l[i] <= stop_p:
                exit_reason = "stop"
                exit_price = min(stop_p, o[i]) - slippage
        elif pos == -1:
            if c[i] <= filt[i]:
                exit_reason = "target"
                exit_price = next_o + slippage
            elif h[i] >= stop_p:
                exit_reason = "stop"
                exit_price = max(stop_p, o[i]) + slippage

        if exit_reason and pos != 0:
            gross = (exit_price - entry_p) * contract_mult * lots * pos
            fee = (abs(entry_p) + abs(exit_price)) * contract_mult * lots * fee_rate
            net = gross - fee
            capital += net
            trades.append(net)
            pos = 0

        if pos == 0 and i < n - 1:
            if long_sig[i]:
                unit_risk = max(tick_size * contract_mult, 1.0 * curr_atr * contract_mult)
                calc_lots = max(1, min(30, int(capital * 0.015 / unit_risk)))
                pos = 1
                lots = calc_lots
                entry_p = next_o + slippage
                stop_p = entry_p - 1.0 * curr_atr
            elif short_sig[i]:
                unit_risk = max(tick_size * contract_mult, 1.0 * curr_atr * contract_mult)
                calc_lots = max(1, min(30, int(capital * 0.015 / unit_risk)))
                pos = -1
                lots = calc_lots
                entry_p = next_o - slippage
                stop_p = entry_p + 1.0 * curr_atr

    wins = [t for t in trades if t > 0]
    wr = len(wins) / max(1, len(trades)) * 100.0
    pnl = capital - 1_000_000.0
    return pnl, len(trades), wr


def main():
    print("=" * 85)
    print("🚀 【第一性原理资产与机制解耦组合实证】")
    print("=" * 85)

    tot_pnl = 0.0
    tot_tr = 0

    with sqlite3.connect(DB_PATH) as conn:
        print("\n📈 [1. 趋势友好优选池 (60m Ehlers SuperTrend + 非对称动态吊灯放飞)]")
        for sym in TREND_SYMBOLS:
            df15 = pd.read_sql_query("SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars WHERE symbol=? AND timeframe='15m' ORDER BY trade_time ASC", conn, params=(sym,))
            if df15.empty: continue
            df15["datetime"] = pd.to_datetime(df15["trade_time"])
            df15 = df15.sort_values("datetime").reset_index(drop=True)
            for c in ["open", "high", "low", "close", "volume", "open_interest"]:
                df15[c] = df15[c].astype(float)
            df60 = df15.set_index("datetime").resample("60min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "open_interest": "last"}).dropna().reset_index()

            pnl, tr, wr = run_trend_symbol_60m(df60, sym)
            tot_pnl += pnl
            tot_tr += tr
            print(f"  ├─ {sym:<8} | 交易: {tr:<3} 笔 | 胜率: {wr:4.1f}% | 净利润: ¥{pnl:+10,.2f}")

        print("\n🔄 [2. 弹性做市均值回归池 (30m 弹塑性均值偏离修复)]")
        for sym in REVERT_SYMBOLS:
            df30 = pd.read_sql_query("SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars WHERE symbol=? AND timeframe='30m' ORDER BY trade_time ASC", conn, params=(sym,))
            if df30.empty: continue
            df30["datetime"] = pd.to_datetime(df30["trade_time"])
            df30 = df30.sort_values("datetime").reset_index(drop=True)
            for c in ["open", "high", "low", "close", "volume", "open_interest"]:
                df30[c] = df30[c].astype(float)

            pnl, tr, wr = run_revert_symbol_30m(df30, sym)
            tot_pnl += pnl
            tot_tr += tr
            print(f"  ├─ {sym:<8} | 交易: {tr:<3} 笔 | 胜率: {wr:4.1f}% | 净利润: ¥{pnl:+10,.2f}")

    print("=" * 85)
    print(f"🏆 【解耦对冲组合全盘总净利润】: ¥{tot_pnl:+11,.2f} | 交易: {tot_tr} 笔 | 结论: {'🔥 强劲全局正反馈 PASS' if tot_pnl > 0 else 'FAIL'}")
    print("=" * 85)


if __name__ == "__main__":
    main()
