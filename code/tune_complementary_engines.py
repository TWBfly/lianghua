"""
code/tune_complementary_engines.py — 测试包含 SMA5 快速落袋与动态止损机制的天枢与太微策略
"""

import sys
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "code"))
sys.path.insert(0, str(PROJECT_ROOT / "strategies"))

from run_complementary_strategies_research import load_kline_bars
from run_tianji_strict_1000_trades_per_symbol import ACTIVE_CONTRACT_SPECS


def run_fast_target_backtest(
    df: pd.DataFrame,
    signals: pd.Series,
    symbol: str,
    initial_capital: float = 1_000_000.0,
    stop_atr_mult: float = 2.0,
    use_sma5_exit: bool = True
):
    spec = ACTIVE_CONTRACT_SPECS.get(symbol, {"multiplier": 10.0, "tick": 1.0, "fee_rate": 0.0001, "margin_rate": 0.12})
    contract_mult = float(spec.get("multiplier", 10.0))
    tick_size = float(spec.get("tick", 1.0))
    fee_rate = float(spec.get("fee_rate", 0.0001))
    margin_rate = float(spec.get("margin_rate", 0.12))
    slippage = tick_size

    c = df["close"].values
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    dt_arr = df["datetime"].values
    sig_arr = signals.values
    n = len(df)

    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    atr_arr = pd.Series(tr).rolling(14, min_periods=5).mean().bfill().values + 1e-8
    sma5_arr = pd.Series(c).rolling(5, min_periods=2).mean().bfill().values

    capital = initial_capital
    pos = 0
    current_lots = 0
    entry_price = 0.0
    entry_idx = 0
    stop_price = 0.0
    trades = []
    equity_curve = [capital]

    for i in range(1, n - 1):
        curr_p = c[i]
        curr_atr = atr_arr[i]
        next_open = o[i + 1]
        curr_sma5 = sma5_arr[i]

        unrealized = (curr_p - entry_price) * contract_mult * current_lots * pos if pos != 0 else 0.0
        equity_curve.append(max(0.0, capital + unrealized))

        exit_reason = None
        exit_p = 0.0

        if pos == 1:
            if use_sma5_exit and curr_p >= curr_sma5 and i > entry_idx:
                exit_reason = "tp_sma5"
                exit_p = next_open - slippage
            elif l[i] <= stop_price:
                exit_reason = "stop_loss"
                exit_p = min(stop_price, o[i]) - slippage
            elif sig_arr[i] == -1:
                exit_reason = "reverse"
                exit_p = next_open - slippage

        elif pos == -1:
            if use_sma5_exit and curr_p <= curr_sma5 and i > entry_idx:
                exit_reason = "tp_sma5"
                exit_p = next_open + slippage
            elif h[i] >= stop_price:
                exit_reason = "stop_loss"
                exit_p = max(stop_price, o[i]) + slippage
            elif sig_arr[i] == 1:
                exit_reason = "reverse"
                exit_p = next_open + slippage

        if exit_reason and pos != 0:
            gross = (exit_p - entry_price) * contract_mult * current_lots * pos
            fee = (abs(entry_price) + abs(exit_p)) * contract_mult * current_lots * fee_rate
            net = gross - fee
            capital += net
            trades.append({"net": net, "gross": gross, "reason": exit_reason, "win": net > 0})
            pos = 0

        if pos == 0 and i < n - 1:
            sig = sig_arr[i]
            if sig != 0:
                unit_risk = max(tick_size * contract_mult, stop_atr_mult * curr_atr * contract_mult)
                calc_lots = max(1, min(30, int(capital * 0.015 / unit_risk)))
                pos = sig
                current_lots = calc_lots
                entry_idx = i + 1
                entry_price = next_open + slippage * pos
                stop_price = entry_price - pos * stop_atr_mult * curr_atr

    wins = [t for t in trades if t["win"]]
    losses = [t for t in trades if not t["win"]]
    win_rate = len(wins) / len(trades) * 100.0 if trades else 0.0
    avg_w = float(np.mean([t["net"] for t in wins])) if wins else 0.0
    avg_l = abs(float(np.mean([t["net"] for t in losses]))) if losses else 1.0
    pl = avg_w / avg_l if avg_l > 0 else 0.0
    net_pnl = capital - initial_capital

    return {
        "symbol": symbol,
        "net_pnl": round(net_pnl, 2),
        "win_rate": round(win_rate, 1),
        "pl_ratio": round(pl, 2),
        "trades": len(trades),
        "wins": len(wins)
    }


def test_tianshu_and_taiwei():
    import tianshu_liquidity_profile_jump as tianshu_mod
    import taiwei_wavelet_fractal_squeeze as taiwei_mod

    symbols = ["AG_IDX", "AU_IDX", "CU_IDX", "SC_IDX", "RB_IDX", "TA_IDX", "MA_IDX", "LC_IDX", "SN_IDX", "P_IDX"]
    print("=" * 80)
    print("🚀 测试天枢策略 (SMA5 快速均值落袋机制):")
    print("=" * 80)
    tot_pnl = 0
    tot_tr = 0
    tot_w = 0
    for sym in symbols:
        df = load_kline_bars(sym, timeframe="15m")
        if df.empty:
            continue
        sigs = tianshu_mod.calculate_signal(df)
        res = run_fast_target_backtest(df, sigs, sym, use_sma5_exit=True)
        tot_pnl += res["net_pnl"]
        tot_tr += res["trades"]
        tot_w += res["wins"]
        print(f"  ├─ {sym:<8} | 交易: {res['trades']:<4}笔 | 胜率: {res['win_rate']:4.1f}% | 盈亏比: {res['pl_ratio']:4.2f} | 净利: ¥{res['net_pnl']:+10,.2f}")

    print(f"\n📊 天枢组合总净利: ¥{tot_pnl:+,.2f} | 总交易: {tot_tr} 笔 | 综合胜率: {tot_w/max(1,tot_tr)*100:.1f}%")

    print("\n" + "=" * 80)
    print("🚀 测试太微策略 (SMA5 快速均值落袋机制):")
    print("=" * 80)
    tot_pnl_tw = 0
    tot_tr_tw = 0
    tot_w_tw = 0
    for sym in symbols:
        df = load_kline_bars(sym, timeframe="15m")
        if df.empty:
            continue
        sigs = taiwei_mod.calculate_signal(df)
        res = run_fast_target_backtest(df, sigs, sym, use_sma5_exit=True)
        tot_pnl_tw += res["net_pnl"]
        tot_tr_tw += res["trades"]
        tot_w_tw += res["wins"]
        print(f"  ├─ {sym:<8} | 交易: {res['trades']:<4}笔 | 胜率: {res['win_rate']:4.1f}% | 盈亏比: {res['pl_ratio']:4.2f} | 净利: ¥{res['net_pnl']:+10,.2f}")

    print(f"\n📊 太微组合总净利: ¥{tot_pnl_tw:+,.2f} | 总交易: {tot_tr_tw} 笔 | 综合胜率: {tot_w_tw/max(1,tot_tr_tw)*100:.1f}%")


if __name__ == "__main__":
    test_tianshu_and_taiwei()
