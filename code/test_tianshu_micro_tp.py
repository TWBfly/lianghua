"""
code/test_tianshu_micro_tp.py — 预计算特征向量极速多周期扫描
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


def precompute_dataset(timeframes: list, symbols: list) -> dict:
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

                typical_p = (h + l + c) / 3.0
                v_s = pd.Series(v)
                pv_s = pd.Series(typical_p * v)
                roll_vol = v_s.rolling(40, min_periods=5).sum().bfill().values + 1e-8
                roll_pv = pv_s.rolling(40, min_periods=5).sum().bfill().values
                vwap = roll_pv / roll_vol
                p_diff_sq_v = pd.Series((typical_p - vwap) ** 2 * v).rolling(40, min_periods=5).sum().bfill().values
                vw_std = np.sqrt(np.maximum(1e-8, p_diff_sq_v / roll_vol))

                vah = vwap + 0.8 * vw_std
                val = vwap - 0.8 * vw_std
                vol_density = np.exp(- ((c - vwap) ** 2) / (2.0 * (vw_std ** 2) + 1e-8))

                bar_range = np.maximum(1e-8, h - l)
                ofi_raw = v * ((c - l) - (h - c)) / bar_range
                ofi_s = pd.Series(ofi_raw)
                ofi_smooth = ofi_s.rolling(3, min_periods=1).mean()
                ofi_mean = ofi_s.rolling(40, min_periods=10).mean().bfill()
                ofi_std = ofi_s.rolling(40, min_periods=10).std(ddof=0).bfill() + 1e-8
                ofi_z = ((ofi_smooth - ofi_mean) / ofi_std).values

                filt_fast = calculate_ehlers_supersmoother_2pole(c, period=6)
                filt_slow = calculate_ehlers_supersmoother_2pole(c, period=18)
                trend_up = filt_fast > filt_slow
                trend_dn = filt_fast < filt_slow

                net_diff = np.abs(c - np.roll(c, 14))
                path = pd.Series(np.abs(c - prev_c)).rolling(14, min_periods=5).sum().bfill().values + 1e-8
                ker = net_diff / path

                c_std = pd.Series(c).rolling(20, min_periods=5).std(ddof=0).bfill().values + 1e-8
                squeeze_ratio = (4.0 * c_std) / (2.0 * atr)
                had_squeeze = pd.Series(squeeze_ratio).rolling(6, min_periods=1).min().values <= 1.25

                body_ratio = np.abs(c - o) / bar_range

                long_sig = trend_up & had_squeeze & (c > vah) & (vol_density <= 0.50) & (ofi_z >= 0.6) & (c > o) & (body_ratio >= 0.40) & (ker >= 0.18)
                short_sig = trend_dn & had_squeeze & (c < val) & (vol_density <= 0.50) & (ofi_z <= -0.6) & (c < o) & (body_ratio >= 0.40) & (ker >= 0.18)

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

    print("⏳ 预计算特征向量流...")
    dataset = precompute_dataset(timeframes, symbols)
    print(f"✅ 特征预计算完成: {len(dataset)} 个品种周期流")

    results = []

    for tf in timeframes:
        for tp in [0.8, 1.0, 1.2, 1.5, 2.0, 2.5]:
            for sl in [0.8, 1.0, 1.2, 1.5]:
                for be in [0.4, 0.6, 0.8, 1.0]:
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
    print("\n🏆 全周期与参数扫描 Top 20 结果:")
    print(df_res.head(20).to_string(index=False))

    print("\n📊 各周期最佳表现对比:")
    for tf in timeframes:
        sub = df_res[df_res["tf"] == tf].iloc[0]
        print(f"  ├─ 周期 [{tf:<4}]: 最佳净利 ¥{sub['pnl']:+10,.2f} | 胜率: {sub['wr']:4.1f}% | 交易: {sub['trades']} 笔 | 参数 (TP={sub['tp']}, SL={sub['sl']}, BE={sub['be']})")


if __name__ == "__main__":
    main()
