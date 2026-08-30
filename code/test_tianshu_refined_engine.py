"""
code/test_tianshu_refined_engine.py — 天枢·微观量价真空跃迁策略 第一性原理数学模型精研与参数收敛测试
"""

from __future__ import annotations

import os
import sys
import math
import sqlite3
import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "code"))
sys.path.insert(0, str(PROJECT_ROOT / "strategies"))

from run_tianji_strict_1000_trades_per_symbol import ACTIVE_CONTRACT_SPECS

DB_PATH = str(PROJECT_ROOT / "data" / "ashare_quant.db")


def load_bars(symbol: str, timeframe: str = "15m") -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        q = """
            SELECT trade_time, open, high, low, close, volume, open_interest
            FROM futures_min_bars
            WHERE symbol = ? AND timeframe = ?
            ORDER BY trade_time ASC;
        """
        df = pd.read_sql_query(q, conn, params=(symbol, timeframe))
        if df.empty:
            return pd.DataFrame()
        df["datetime"] = pd.to_datetime(df["trade_time"])
        df = df.sort_values("datetime").reset_index(drop=True)
        for col in ["open", "high", "low", "close", "volume", "open_interest"]:
            df[col] = df[col].astype(float)
        return df


def calculate_ehlers_supersmoother_2pole(prices: np.ndarray, period: int = 12) -> np.ndarray:
    """Ehlers 2-Pole SuperSmoother 零滞后滤波器"""
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


def compute_tianshu_refined_signals(df: pd.DataFrame, vp_window: int = 40) -> Tuple[pd.Series, pd.DataFrame]:
    """
    天枢·量价真空跃迁精研信号引擎 (双机制：真空跃迁 + 极值吸附)
    """
    c = df["close"].astype(float).values
    o = df["open"].astype(float).values
    h = df["high"].astype(float).values
    l = df["low"].astype(float).values
    v = df["volume"].astype(float).values
    n = len(df)

    # 1. 因果 ATR (14 周期)
    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    tr_series = pd.Series(tr, index=df.index)
    atr = tr_series.rolling(14, min_periods=5).mean().bfill().values + 1e-8

    # 2. 闭式 Volume Profile 拓扑特征
    typical_p = (h + l + c) / 3.0
    v_series = pd.Series(v, index=df.index)
    pv_series = pd.Series(typical_p * v, index=df.index)

    roll_vol = v_series.rolling(vp_window, min_periods=5).sum().bfill().values + 1e-8
    roll_pv = pv_series.rolling(vp_window, min_periods=5).sum().bfill().values
    vwap = roll_pv / roll_vol

    p_diff_sq_v = pd.Series((typical_p - vwap) ** 2 * v, index=df.index).rolling(vp_window, min_periods=5).sum().bfill().values
    vw_std = np.sqrt(np.maximum(1e-8, p_diff_sq_v / roll_vol))

    vah = vwap + 1.0 * vw_std
    val = vwap - 1.0 * vw_std
    vol_density = np.exp(- ((c - vwap) ** 2) / (2.0 * (vw_std ** 2) + 1e-8))
    z_dist = (c - vwap) / vw_std

    # 3. 订单流微观失衡 (OFI Proxy)
    bar_range = np.maximum(1e-8, h - l)
    ofi_raw = v * ((c - l) - (h - c)) / bar_range
    ofi_series = pd.Series(ofi_raw, index=df.index)
    ofi_smooth = ofi_series.rolling(4, min_periods=1).mean()
    ofi_mean = ofi_series.rolling(vp_window, min_periods=10).mean().bfill()
    ofi_std = ofi_series.rolling(vp_window, min_periods=10).std(ddof=0).bfill() + 1e-8
    ofi_zscore = ((ofi_smooth - ofi_mean) / ofi_std).values

    # 4. Ehlers 2-Pole SuperSmoother 零滞后宏观趋势
    filt_fast = calculate_ehlers_supersmoother_2pole(c, period=6)
    filt_slow = calculate_ehlers_supersmoother_2pole(c, period=20)
    dsp_trend_up = filt_fast > filt_slow
    dsp_trend_dn = filt_fast < filt_slow

    # 5. 波动率能量挤压 (Squeeze Gate)
    c_series = pd.Series(c, index=df.index)
    c_std = c_series.rolling(20, min_periods=5).std(ddof=0).bfill().values + 1e-8
    squeeze_ratio = (4.0 * c_std) / (2.0 * atr)
    had_squeeze = pd.Series(squeeze_ratio, index=df.index).rolling(8, min_periods=1).min().values <= 1.20

    # 6. K 线微观形态
    body = np.abs(c - o)
    body_ratio = body / bar_range
    lower_shadow = np.where(c >= o, o - l, c - l)
    upper_shadow = np.where(c >= o, h - c, h - o)

    pinbar_long = (lower_shadow >= 1.5 * body) & (c > l + 0.5 * bar_range)
    pinbar_short = (upper_shadow >= 1.5 * body) & (c < h - 0.5 * bar_range)

    # 7. 考夫曼自适应效率 (KER)
    net_diff = np.abs(c - np.roll(c, 14))
    abs_diff = np.abs(c - prev_c)
    path = pd.Series(abs_diff, index=df.index).rolling(14, min_periods=5).sum().bfill().values + 1e-8
    ker = net_diff / path

    # 8. 持仓量与资金流入确认
    oi_filter_long = np.ones(n, dtype=bool)
    oi_filter_short = np.ones(n, dtype=bool)
    if "open_interest" in df.columns:
        oi = df["open_interest"].astype(float).values
        oi_diff = np.diff(oi, prepend=oi[0])
        vol_ma = pd.Series(v).rolling(20, min_periods=5).mean().bfill().values
        oi_filter_long = oi_diff >= -vol_ma * 0.35
        oi_filter_short = oi_diff >= -vol_ma * 0.35

    # ── 信号生成逻辑 ──
    # 模式 A: 顺势真空跃迁突破 (LVN Vacuum Jump)
    jump_long = (
        dsp_trend_up &
        had_squeeze &
        (c > vah) &
        (vol_density <= 0.45) &
        (ofi_zscore >= 0.7) &
        (c > o) &
        (body_ratio >= 0.40) &
        (ker >= 0.18) &
        oi_filter_long
    )

    jump_short = (
        dsp_trend_dn &
        had_squeeze &
        (c < val) &
        (vol_density <= 0.45) &
        (ofi_zscore <= -0.7) &
        (c < o) &
        (body_ratio >= 0.40) &
        (ker >= 0.18) &
        oi_filter_short
    )

    # 模式 B: 极值引力回踩 (HVN Boundary Absorption Reversal)
    absorb_long = (
        (z_dist <= -2.0) &
        pinbar_long &
        (vol_density <= 0.25) &
        (ofi_zscore >= -0.5) & # OFI 衰竭止跌
        oi_filter_long
    )

    absorb_short = (
        (z_dist >= 2.0) &
        pinbar_short &
        (vol_density <= 0.25) &
        (ofi_zscore <= 0.5) & # OFI 衰竭止涨
        oi_filter_short
    )

    signals = pd.Series(0, index=df.index, dtype=int)
    signal_type = pd.Series("NONE", index=df.index)

    signals[jump_long] = 1
    signal_type[jump_long] = "VACUUM_JUMP_LONG"

    signals[jump_short] = -1
    signal_type[jump_short] = "VACUUM_JUMP_SHORT"

    signals[absorb_long] = 1
    signal_type[absorb_long] = "ABSORPTION_REVERT_LONG"

    signals[absorb_short] = -1
    signal_type[absorb_short] = "ABSORPTION_REVERT_SHORT"

    factors_df = pd.DataFrame({
        "vwap": vwap,
        "vah": vah,
        "val": val,
        "vol_density": vol_density,
        "z_dist": z_dist,
        "ofi_zscore": ofi_zscore,
        "atr": atr,
        "signal_type": signal_type
    }, index=df.index)

    return signals, factors_df


def run_refined_backtest(
    df: pd.DataFrame,
    signals: pd.Series,
    factors_df: pd.DataFrame,
    symbol: str,
    initial_capital: float = 1_000_000.0,
    risk_pct: float = 0.015,
    stop_atr_mult: float = 1.5,
    be_atr_mult: float = 1.2,
    trail_atr_mult: float = 1.8,
    friction_multiplier: float = 1.0
) -> Dict[str, Any]:
    n = len(df)
    if n < 50 or signals.empty:
        return {"error": "数据不足"}

    spec = ACTIVE_CONTRACT_SPECS.get(symbol, {"multiplier": 10.0, "tick": 1.0, "fee_rate": 0.0001, "margin_rate": 0.12})
    contract_mult = float(spec.get("multiplier", 10.0))
    tick_size = float(spec.get("tick", 1.0))
    fee_rate = float(spec.get("fee_rate", 0.0001)) * friction_multiplier
    margin_rate = float(spec.get("margin_rate", 0.12))
    base_slippage = tick_size * friction_multiplier

    c = df["close"].values
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    dt_arr = df["datetime"].values
    sig_arr = signals.values
    sig_types = factors_df["signal_type"].values
    vwap_arr = factors_df["vwap"].values
    atr_arr = factors_df["atr"].values
    ofi_z_arr = factors_df["ofi_zscore"].values

    sma5_arr = pd.Series(c).rolling(5, min_periods=2).mean().bfill().values

    capital = initial_capital
    position = 0
    current_lots = 0
    entry_price = 0.0
    entry_idx = 0
    entry_type = ""
    stop_price = 0.0
    highest_price = 0.0
    lowest_price = 1e9

    trades = []
    equity_curve = [capital]
    cash_flow_ledger = 0.0

    for i in range(1, n - 1):
        curr_p = c[i]
        curr_atr = atr_arr[i]
        next_open = o[i + 1]
        curr_h = h[i]
        curr_l = l[i]

        # 逐柱 M2M 与动态跟踪
        if position == 1:
            highest_price = max(highest_price, curr_h)
            profit_atrs = (highest_price - entry_price) / curr_atr
            
            # 保本与追踪逻辑
            if "VACUUM_JUMP" in entry_type:
                if profit_atrs >= be_atr_mult:
                    stop_price = max(stop_price, entry_price + 0.1 * curr_atr)
                if profit_atrs >= (be_atr_mult + 1.0):
                    stop_price = max(stop_price, highest_price - trail_atr_mult * curr_atr)
            else: # ABSORPTION 回归逻辑：靠近 VWAP 或 SMA5 快速落袋
                if curr_p >= vwap_arr[i] or curr_p >= sma5_arr[i]:
                    stop_price = max(stop_price, curr_p)

            unrealized = (curr_p - entry_price) * contract_mult * current_lots
        elif position == -1:
            lowest_price = min(lowest_price, curr_l)
            profit_atrs = (entry_price - lowest_price) / curr_atr

            if "VACUUM_JUMP" in entry_type:
                if profit_atrs >= be_atr_mult:
                    stop_price = min(stop_price, entry_price - 0.1 * curr_atr)
                if profit_atrs >= (be_atr_mult + 1.0):
                    stop_price = min(stop_price, lowest_price + trail_atr_mult * curr_atr)
            else:
                if curr_p <= vwap_arr[i] or curr_p <= sma5_arr[i]:
                    stop_price = min(stop_price, curr_p)

            unrealized = (entry_price - curr_p) * contract_mult * current_lots
        else:
            unrealized = 0.0

        m2m_equity = max(0.0, capital + unrealized)
        equity_curve.append(m2m_equity)

        # ── 出场判断 ──
        exit_reason = None
        exit_price = 0.0

        if position == 1:
            if "ABSORPTION" in entry_type and (curr_p >= vwap_arr[i] or curr_p >= sma5_arr[i]) and i > entry_idx:
                exit_reason = "tp_vwap_sma5"
                exit_price = next_open - base_slippage
            elif curr_l <= stop_price:
                exit_reason = "stop_loss"
                exit_price = min(stop_price, o[i]) - base_slippage
            elif sig_arr[i] == -1:
                exit_reason = "reverse_signal"
                exit_price = next_open - base_slippage
            elif "VACUUM_JUMP" in entry_type and ofi_z_arr[i] <= -1.2: # OFI 剧烈逆转
                exit_reason = "ofi_invalidation"
                exit_price = next_open - base_slippage

        elif position == -1:
            if "ABSORPTION" in entry_type and (curr_p <= vwap_arr[i] or curr_p <= sma5_arr[i]) and i > entry_idx:
                exit_reason = "tp_vwap_sma5"
                exit_price = next_open + base_slippage
            elif curr_h >= stop_price:
                exit_reason = "stop_loss"
                exit_price = max(stop_price, o[i]) + base_slippage
            elif sig_arr[i] == 1:
                exit_reason = "reverse_signal"
                exit_price = next_open + base_slippage
            elif "VACUUM_JUMP" in entry_type and ofi_z_arr[i] >= 1.2:
                exit_reason = "ofi_invalidation"
                exit_price = next_open + base_slippage

        if exit_reason and position != 0:
            gross_pnl = (exit_price - entry_price) * contract_mult * current_lots * position
            trade_fee = (abs(entry_price) + abs(exit_price)) * contract_mult * current_lots * fee_rate
            net_pnl = gross_pnl - trade_fee
            capital += net_pnl
            cash_flow_ledger += net_pnl

            trades.append({
                "entry_time": str(dt_arr[entry_idx]),
                "exit_time": str(dt_arr[i]),
                "entry_type": entry_type,
                "direction": "LONG" if position > 0 else "SHORT",
                "lots": current_lots,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "gross_pnl": gross_pnl,
                "fee": trade_fee,
                "net_pnl": net_pnl,
                "holding_bars": i - entry_idx,
                "exit_reason": exit_reason
            })
            position = 0
            current_lots = 0

        # ── 进场判断 ──
        if position == 0 and i < n - 1:
            signal = sig_arr[i]
            if signal != 0:
                unit_risk = max(tick_size * contract_mult, stop_atr_mult * curr_atr * contract_mult)
                calc_lots = max(1, min(40, int(capital * risk_pct / unit_risk)))

                req_margin = next_open * contract_mult * calc_lots * margin_rate
                if req_margin > capital * 0.70:
                    calc_lots = max(1, int((capital * 0.70) / (next_open * contract_mult * margin_rate + 1e-8)))

                position = signal
                current_lots = calc_lots
                entry_idx = i + 1
                entry_type = sig_types[i]
                entry_price = next_open + base_slippage * position
                highest_price = entry_price
                lowest_price = entry_price

                if position == 1:
                    stop_price = entry_price - stop_atr_mult * curr_atr
                else:
                    stop_price = entry_price + stop_atr_mult * curr_atr

    final_equity = capital
    total_net_pnl = final_equity - initial_capital
    ret_pct = total_net_pnl / initial_capital * 100.0

    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] <= 0]
    win_rate = len(wins) / len(trades) * 100.0 if trades else 0.0
    avg_win = float(np.mean([t["net_pnl"] for t in wins])) if wins else 0.0
    avg_loss = abs(float(np.mean([t["net_pnl"] for t in losses]))) if losses else 1.0
    pl_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0

    eq_arr = np.array(equity_curve)
    peak = np.maximum.accumulate(eq_arr)
    dd_arr = np.where(peak > 0, (peak - eq_arr) / peak, 0.0)
    max_dd = float(np.max(dd_arr) * 100.0) if len(dd_arr) > 0 else 0.0

    bar_rets = np.diff(eq_arr) / (eq_arr[:-1] + 1e-8) if len(eq_arr) > 1 else np.array([0.0])
    annual_factor = np.sqrt(9324) if "15m" in str(df.get("timeframe", "15m")) else np.sqrt(4662)
    sharpe = (np.mean(bar_rets) / (np.std(bar_rets) + 1e-8)) * annual_factor if len(bar_rets) > 1 and np.std(bar_rets) > 0 else 0.0

    ledger_diff = abs(total_net_pnl - cash_flow_ledger)
    ledger_closed = ledger_diff <= 0.01

    return {
        "symbol": symbol,
        "total_bars": n,
        "initial_capital": initial_capital,
        "final_equity": round(final_equity, 2),
        "total_net_pnl": round(total_net_pnl, 2),
        "return_pct": round(ret_pct, 2),
        "win_rate_pct": round(win_rate, 1),
        "profit_loss_ratio": round(pl_ratio, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe_ratio": round(float(sharpe), 2),
        "total_trades": len(trades),
        "win_trades": len(wins),
        "loss_trades": len(losses),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "ledger_closed": ledger_closed,
        "trades": trades,
        "equity_curve": equity_curve
    }


def compare_timeframes():
    timeframes = ["5m", "15m", "30m"]
    symbols = ["AG_IDX", "AU_IDX", "CU_IDX", "SC_IDX", "RB_IDX", "TA_IDX", "MA_IDX", "LC_IDX", "SN_IDX", "P_IDX"]

    print("=" * 80)
    print("🔬 [天枢·精研引擎] 多周期 (5m / 15m / 30m) 真实历史横向深度对比测试")
    print("=" * 80)

    for tf in timeframes:
        print(f"\n▶ 正在测试 K 线周期: [{tf}] ...")
        tot_pnl = 0.0
        tot_trades = 0
        all_wins = 0
        max_dds = []
        sharpes = []

        for sym in symbols:
            df = load_bars(sym, timeframe=tf)
            if df.empty or len(df) < 200:
                continue
            sigs, factors = compute_tianshu_refined_signals(df)
            res = run_refined_backtest(df, sigs, factors, sym)
            if "error" not in res:
                tot_pnl += res["total_net_pnl"]
                tot_trades += res["total_trades"]
                all_wins += res["win_trades"]
                max_dds.append(res["max_drawdown_pct"])
                sharpes.append(res["sharpe_ratio"])
                print(f"  ├─ {sym:<8} | 交易: {res['total_trades']:<4}笔 | 胜率: {res['win_rate_pct']:4.1f}% | 盈亏比: {res['profit_loss_ratio']:4.2f} | 净利: ¥{res['total_net_pnl']:+10,.2f} | MaxDD: {res['max_drawdown_pct']:4.2f}% | Sharpe: {res['sharpe_ratio']:4.2f}")

        win_rate = all_wins / max(1, tot_trades) * 100.0
        avg_dd = float(np.mean(max_dds)) if max_dds else 0.0
        avg_sharpe = float(np.mean(sharpes)) if sharpes else 0.0

        print(f"  └─ 周期 [{tf}] 组合汇总: 总净利: ¥{tot_pnl:+,.2f} | 总交易: {tot_trades} 笔 | 综合胜率: {win_rate:.1f}% | 平均最大回撤: {avg_dd:.2f}% | 平均夏普: {avg_sharpe:.2f}")


if __name__ == "__main__":
    compare_timeframes()
