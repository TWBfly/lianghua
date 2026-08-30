"""
code/test_tianshu_hvn_lvn_physics.py — 基于 HVN1 -> LVN -> HVN2 物理拓扑跃迁机制与三阶目标位回测
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


def load_bars(symbol: str, timeframe: str = "15m") -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        q = "SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars WHERE symbol = ? AND timeframe = ? ORDER BY trade_time ASC;"
        df = pd.read_sql_query(q, conn, params=(symbol, timeframe))
        if df.empty:
            return pd.DataFrame()
        df["datetime"] = pd.to_datetime(df["trade_time"])
        df = df.sort_values("datetime").reset_index(drop=True)
        for col in ["open", "high", "low", "close", "volume", "open_interest"]:
            df[col] = df[col].astype(float)
        return df


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


def run_hvn_lvn_jump_sim(
    df: pd.DataFrame,
    symbol: str,
    tp_atr_mult: float = 2.0,
    sl_atr_mult: float = 1.2,
    be_trigger_mult: float = 1.0,
    vp_window: int = 40,
    ofi_th: float = 0.8
):
    c = df["close"].values
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    v = df["volume"].values
    dt_arr = df["datetime"].values
    n = len(df)

    spec = ACTIVE_CONTRACT_SPECS.get(symbol, {"multiplier": 10.0, "tick": 1.0, "fee_rate": 0.0001, "margin_rate": 0.12})
    contract_mult = float(spec.get("multiplier", 10.0))
    tick_size = float(spec.get("tick", 1.0))
    fee_rate = float(spec.get("fee_rate", 0.0001))
    slippage = tick_size

    # 1. 因果 ATR
    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    atr = pd.Series(tr).rolling(14, min_periods=5).mean().bfill().values + 1e-8

    # 2. Volume Profile Topology
    typical_p = (h + l + c) / 3.0
    v_s = pd.Series(v)
    pv_s = pd.Series(typical_p * v)
    roll_vol = v_s.rolling(vp_window, min_periods=5).sum().bfill().values + 1e-8
    roll_pv = pv_s.rolling(vp_window, min_periods=5).sum().bfill().values
    vwap = roll_pv / roll_vol
    p_diff_sq_v = pd.Series((typical_p - vwap) ** 2 * v).rolling(vp_window, min_periods=5).sum().bfill().values
    vw_std = np.sqrt(np.maximum(1e-8, p_diff_sq_v / roll_vol))

    vah = vwap + 1.0 * vw_std
    val = vwap - 1.0 * vw_std
    vol_density = np.exp(- ((c - vwap) ** 2) / (2.0 * (vw_std ** 2) + 1e-8))

    # 3. OFI Proxy
    bar_range = np.maximum(1e-8, h - l)
    ofi_raw = v * ((c - l) - (h - c)) / bar_range
    ofi_s = pd.Series(ofi_raw)
    ofi_smooth = ofi_s.rolling(3, min_periods=1).mean()
    ofi_mean = ofi_s.rolling(vp_window, min_periods=10).mean().bfill()
    ofi_std = ofi_s.rolling(vp_window, min_periods=10).std(ddof=0).bfill() + 1e-8
    ofi_z = ((ofi_smooth - ofi_mean) / ofi_std).values

    # 4. DSP SuperSmoother Trend
    filt_fast = calculate_ehlers_supersmoother_2pole(c, period=6)
    filt_slow = calculate_ehlers_supersmoother_2pole(c, period=18)
    trend_up = filt_fast > filt_slow
    trend_dn = filt_fast < filt_slow

    # 5. Kaufman Efficiency & Squeeze
    net_diff = np.abs(c - np.roll(c, 14))
    path = pd.Series(np.abs(c - prev_c)).rolling(14, min_periods=5).sum().bfill().values + 1e-8
    ker = net_diff / path

    c_std = pd.Series(c).rolling(20, min_periods=5).std(ddof=0).bfill().values + 1e-8
    squeeze_ratio = (4.0 * c_std) / (2.0 * atr)
    had_squeeze = pd.Series(squeeze_ratio).rolling(6, min_periods=1).min().values <= 1.25

    body_ratio = np.abs(c - o) / bar_range

    # 信号生成 (纯因果)
    long_sig = (
        trend_up &
        had_squeeze &
        (c > vah) &
        (vol_density <= 0.45) &
        (ofi_z >= ofi_th) &
        (c > o) &
        (body_ratio >= 0.45) &
        (ker >= 0.20)
    )

    short_sig = (
        trend_dn &
        had_squeeze &
        (c < val) &
        (vol_density <= 0.45) &
        (ofi_z <= -ofi_th) &
        (c < o) &
        (body_ratio >= 0.45) &
        (ker >= 0.20)
    )

    capital = 1_000_000.0
    pos = 0
    lots = 0
    entry_p = 0.0
    entry_idx = 0
    stop_p = 0.0
    tp_p = 0.0
    highest_p = 0.0
    lowest_p = 1e9

    trades = []
    equity_curve = [capital]

    for i in range(1, n - 1):
        curr_p = c[i]
        curr_atr = atr[i]
        next_o = o[i + 1]

        # M2M & Break-even lock
        if pos == 1:
            highest_p = max(highest_p, h[i])
            if (highest_p - entry_p) >= be_trigger_mult * curr_atr:
                stop_p = max(stop_p, entry_p + 0.1 * curr_atr)
            unrealized = (curr_p - entry_p) * contract_mult * lots
        elif pos == -1:
            lowest_p = min(lowest_p, l[i])
            if (entry_p - lowest_p) >= be_trigger_mult * curr_atr:
                stop_p = min(stop_p, entry_p - 0.1 * curr_atr)
            unrealized = (entry_p - curr_p) * contract_mult * lots
        else:
            unrealized = 0.0

        equity_curve.append(max(0.0, capital + unrealized))

        # 出场逻辑 (严格下一柱 Open / 当柱止盈止损)
        exit_reason = None
        exit_price = 0.0

        if pos == 1:
            if h[i] >= tp_p:
                exit_reason = "tp_hvn2"
                exit_price = max(tp_p, o[i]) - slippage
            elif l[i] <= stop_p:
                exit_reason = "stop_loss"
                exit_price = min(stop_p, o[i]) - slippage
            elif short_sig[i]:
                exit_reason = "rev_signal"
                exit_price = next_o - slippage

        elif pos == -1:
            if l[i] <= tp_p:
                exit_reason = "tp_hvn2"
                exit_price = min(tp_p, o[i]) + slippage
            elif h[i] >= stop_p:
                exit_reason = "stop_loss"
                exit_price = max(stop_p, o[i]) + slippage
            elif long_sig[i]:
                exit_reason = "rev_signal"
                exit_price = next_o + slippage

        if exit_reason and pos != 0:
            gross = (exit_price - entry_p) * contract_mult * lots * pos
            fee = (abs(entry_p) + abs(exit_price)) * contract_mult * lots * fee_rate
            net = gross - fee
            capital += net
            trades.append({"net": net, "gross": gross, "win": net > 0, "reason": exit_reason})
            pos = 0

        # 进场逻辑 (严格下一柱 Open)
        if pos == 0 and i < n - 1:
            sig = 1 if long_sig[i] else (-1 if short_sig[i] else 0)
            if sig != 0:
                unit_risk = max(tick_size * contract_mult, sl_atr_mult * curr_atr * contract_mult)
                calc_lots = max(1, min(30, int(capital * 0.015 / unit_risk)))
                pos = sig
                lots = calc_lots
                entry_idx = i + 1
                entry_p = next_o + slippage * pos
                highest_p = entry_p
                lowest_p = entry_p

                if pos == 1:
                    stop_p = entry_p - sl_atr_mult * curr_atr
                    tp_p = entry_p + tp_atr_mult * curr_atr
                else:
                    stop_p = entry_p + sl_atr_mult * curr_atr
                    tp_p = entry_p - tp_atr_mult * curr_atr

    wins = [t for t in trades if t["win"]]
    losses = [t for t in trades if not t["win"]]
    win_rate = len(wins) / len(trades) * 100.0 if trades else 0.0
    avg_w = float(np.mean([t["net"] for t in wins])) if wins else 0.0
    avg_l = abs(float(np.mean([t["net"] for t in losses]))) if losses else 1.0
    pl = avg_w / avg_l if avg_l > 0 else 0.0
    net_pnl = capital - 1_000_000.0

    eq_arr = np.array(equity_curve)
    peak = np.maximum.accumulate(eq_arr)
    dd_arr = np.where(peak > 0, (peak - eq_arr) / peak, 0.0)
    max_dd = float(np.max(dd_arr) * 100.0) if len(dd_arr) > 0 else 0.0

    return {
        "symbol": symbol,
        "net_pnl": round(net_pnl, 2),
        "win_rate": round(win_rate, 1),
        "pl_ratio": round(pl, 2),
        "max_dd": round(max_dd, 2),
        "trades": len(trades),
        "wins": len(wins)
    }


def grid_search():
    symbols = ["AG_IDX", "AU_IDX", "CU_IDX", "SC_IDX", "RB_IDX", "TA_IDX", "MA_IDX", "LC_IDX", "SN_IDX", "P_IDX"]
    print("=" * 80)
    print("🎯 网格测试 HVN2 目标位与参数组合 (15m):")
    print("=" * 80)

    for tp in [1.5, 2.0, 2.5, 3.0]:
        for sl in [1.0, 1.2, 1.5]:
            for be in [0.8, 1.0, 1.2]:
                tot_pnl = 0.0
                tot_trades = 0
                tot_wins = 0
                for sym in symbols:
                    df = load_bars(sym, timeframe="15m")
                    if df.empty:
                        continue
                    res = run_hvn_lvn_jump_sim(df, sym, tp_atr_mult=tp, sl_atr_mult=sl, be_trigger_mult=be)
                    tot_pnl += res["net_pnl"]
                    tot_trades += res["trades"]
                    tot_wins += res["wins"]
                wr = tot_wins / max(1, tot_trades) * 100.0
                print(f"TP: {tp:3.1f} | SL: {sl:3.1f} | BE: {be:3.1f} => 总净利: ¥{tot_pnl:+11,.2f} | 交易: {tot_trades:<4} | 胜率: {wr:4.1f}%")


if __name__ == "__main__":
    grid_search()
