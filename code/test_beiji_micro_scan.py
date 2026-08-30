"""
code/test_beiji_micro_scan.py — 北极·截面展期动量策略 多周期与微观参数极速扫描
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


def precompute_beiji_dataset(timeframes: list, symbols: list) -> dict:
    dataset = {}
    with sqlite3.connect(DB_PATH) as conn:
        for tf in timeframes:
            for sym in symbols:
                q = "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars WHERE symbol = ? AND timeframe = ? ORDER BY trade_time ASC;"
                df = pd.read_sql_query(q, conn, params=(sym, tf))
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

                prev_c = np.roll(c, 1)
                prev_c[0] = c[0]
                tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
                atr = pd.Series(tr).rolling(14, min_periods=5).mean().bfill().values + 1e-8

                # 1. 展期基差代理与基差动量
                c_s = pd.Series(c)
                basis_proxy = (c - c_s.rolling(80, min_periods=20).mean().bfill().values) / atr
                basis_mom = pd.Series(basis_proxy).diff(14).fillna(0.0).values

                # 2. 中长线时序动量
                mom_20 = c_s.pct_change(20).fillna(0.0).values
                mom_60 = c_s.pct_change(60).fillna(0.0).values

                # 3. 趋势物理效率 KER
                net_diff = np.abs(c - np.roll(c, 20))
                path = pd.Series(np.abs(c - prev_c)).rolling(20, min_periods=5).sum().bfill().values + 1e-8
                ker = net_diff / path

                # 4. Ehlers 零滞后趋势
                filt_fast = calculate_ehlers_supersmoother_2pole(c, period=6)
                filt_slow = calculate_ehlers_supersmoother_2pole(c, period=18)
                trend_up = filt_fast > filt_slow
                trend_dn = filt_fast < filt_slow

                # 5. K 线实体
                bar_range = np.maximum(1e-8, h - l)
                body_ratio = np.abs(c - o) / bar_range

                # 6. 持仓量过滤
                vol_ma20 = pd.Series(v).rolling(20, min_periods=5).mean().bfill().values + 1e-8
                oi_filter_long = np.ones(n, dtype=bool)
                oi_filter_short = np.ones(n, dtype=bool)
                if "open_interest" in df.columns:
                    oi = df["open_interest"].astype(float).values
                    oi_diff = np.diff(oi, prepend=oi[0])
                    oi_filter_long = oi_diff >= -vol_ma20 * 0.35
                    oi_filter_short = oi_diff >= -vol_ma20 * 0.35

                # 综合展期动量评分
                score = 0.40 * basis_proxy + 0.35 * (mom_20 / (atr / c + 1e-8)) + 0.25 * ker

                long_sig = (
                    trend_up &
                    (score >= 0.30) &
                    (basis_mom >= 0) &
                    (c > o) &
                    (body_ratio >= 0.35) &
                    oi_filter_long
                )

                short_sig = (
                    trend_dn &
                    (score <= -0.30) &
                    (basis_mom <= 0) &
                    (c < o) &
                    (body_ratio >= 0.35) &
                    oi_filter_short
                )

                dataset[(sym, tf)] = {
                    "c": c, "o": o, "h": h, "l": l, "atr": atr,
                    "long_sig": long_sig, "short_sig": short_sig,
                    "mult": contract_mult, "tick": tick_size, "fee_rate": fee_rate,
                    "n": n
                }
    return dataset


def run_fast_simulation(data: dict, tp: float, sl: float, be: float) -> tuple[float, int, int]:
    c = data["c"]
    o = data["o"]
    h = data["h"]
    l = data["l"]
    atr = data["atr"]
    long_sig = data["long_sig"]
    short_sig = data["short_sig"]
    mult = data["mult"]
    tick = data["tick"]
    fee_rate = data["fee_rate"]
    n = data["n"]
    slippage = tick

    capital = 1_000_000.0
    pos = 0
    lots = 0
    entry_p = 0.0
    stop_p = 0.0
    tp_p = 0.0
    highest_p = 0.0
    lowest_p = 1e9
    trades_pnl = []

    for i in range(1, n - 1):
        curr_atr = atr[i]
        next_o = o[i + 1]

        if pos == 1:
            highest_p = max(highest_p, h[i])
            if (highest_p - entry_p) >= be * curr_atr:
                stop_p = max(stop_p, entry_p + 0.1 * curr_atr)
        elif pos == -1:
            lowest_p = min(lowest_p, l[i])
            if (entry_p - lowest_p) >= be * curr_atr:
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
            elif short_sig[i]:
                exit_reason = "rev"
                exit_price = next_o - slippage
        elif pos == -1:
            if l[i] <= tp_p:
                exit_reason = "tp"
                exit_price = min(tp_p, o[i]) + slippage
            elif h[i] >= stop_p:
                exit_reason = "sl"
                exit_price = max(stop_p, o[i]) + slippage
            elif long_sig[i]:
                exit_reason = "rev"
                exit_price = next_o + slippage

        if exit_reason and pos != 0:
            gross = (exit_price - entry_p) * mult * lots * pos
            fee = (abs(entry_p) + abs(exit_price)) * mult * lots * fee_rate
            net = gross - fee
            capital += net
            trades_pnl.append(net)
            pos = 0

        if pos == 0 and i < n - 1:
            sig = 1 if long_sig[i] else (-1 if short_sig[i] else 0)
            if sig != 0:
                unit_risk = max(tick * mult, sl * curr_atr * mult)
                calc_lots = max(1, min(30, int(capital * 0.015 / unit_risk)))
                pos = sig
                lots = calc_lots
                entry_p = next_o + slippage * pos
                highest_p = entry_p
                lowest_p = entry_p
                stop_p = entry_p - pos * sl * curr_atr
                tp_p = entry_p + pos * tp * curr_atr

    wins = sum(1 for p in trades_pnl if p > 0)
    return capital - 1_000_000.0, len(trades_pnl), wins


def main():
    timeframes = ["5m", "15m", "30m"]
    symbols = ["AG_IDX", "AU_IDX", "CU_IDX", "SC_IDX", "RB_IDX", "TA_IDX", "MA_IDX", "LC_IDX", "SN_IDX", "P_IDX"]

    print("⏳ 预计算北极展期特征流...")
    dataset = precompute_beiji_dataset(timeframes, symbols)
    print(f"✅ 特征预计算完成: {len(dataset)} 个数据集")

    results = []

    for tf in timeframes:
        for tp in [0.8, 1.0, 1.2, 1.5, 2.0]:
            for sl in [0.6, 0.8, 1.0, 1.2]:
                for be in [0.6, 0.8, 1.0]:
                    tot_pnl = 0.0
                    tot_trades = 0
                    tot_wins = 0

                    for sym in symbols:
                        if (sym, tf) not in dataset:
                            continue
                        pnl, tr_cnt, w_cnt = run_fast_simulation(dataset[(sym, tf)], tp, sl, be)
                        tot_pnl += pnl
                        tot_trades += tr_cnt
                        tot_wins += w_cnt

                    wr = tot_wins / max(1, tot_trades) * 100.0 if tot_trades > 0 else 0.0
                    results.append({
                        "tf": tf, "tp": tp, "sl": sl, "be": be,
                        "pnl": tot_pnl, "trades": tot_trades, "wr": wr
                    })

    df_res = pd.DataFrame(results).sort_values("pnl", ascending=False)
    print("\n🏆 北极策略全周期与参数扫描 Top 20 结果:")
    print(df_res.head(20).to_string(index=False))

    print("\n📊 各周期最佳表现对比:")
    for tf in timeframes:
        sub = df_res[df_res["tf"] == tf].iloc[0]
        print(f"  ├─ 周期 [{tf:<4}]: 最佳净利 ¥{sub['pnl']:+10,.2f} | 胜率: {sub['wr']:4.1f}% | 交易: {sub['trades']} 笔 | 参数 (TP={sub['tp']}, SL={sub['sl']}, BE={sub['be']})")


if __name__ == "__main__":
    main()
