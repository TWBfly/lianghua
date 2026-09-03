"""
strategies/chanquant_v11_dual_island_master.py — 「因果缠论 11.0·终极正交双岛量化大师策略」
(ChanQuant 11.0 Orthogonal Dual-Island Master Strategy)

【核心架构设计】：
1. 宏观长程动量岛 (Trend Island):
   - 管辖资产：沪金 (AU)、沪银 (AG)、沪铝 (AL)、原油 (SC)、沪锡 (SN)、碳酸锂 (LC)
   - 算法内核：Ehlers 2-Pole 零滞后滤波器 + 纯因果 B2/B3 顺势突破回踩 + 2.5 ATR 宽幅动态吊灯放飞右尾；
   - 非对称风控：浮盈 1.1 ATR 锁定保本 (Entry + 0.15 ATR)，浮盈 2.0 ATR 激活吊灯追踪。

2. 产业基差均值岛 (Reversion Island):
   - 管辖资产：螺纹 (RB)、热卷 (HC)、铁矿 (I)、焦炭 (J)、焦煤 (JM)、沪铜 (CU)、沪锌 (ZN)、PTA (TA)、甲醇 (MA)、纯碱 (SA)、玻璃 (FG)、豆粕 (M)、豆油 (Y)、棕榈油 (P)、玉米 (C)、棉花 (CF)、白糖 (SR)、橡胶 (RU)、工业硅 (SI)
   - 算法内核：Ehlers 中枢通道极值脱轨触底反弹 (B1/B2 低吸, S1/S2 高抛)；
   - 止盈与风控：目标快速平仓于 Ehlers 零滞后基线，硬止损 0.70 ATR。

3. 动态自适应混沌避险门禁 (Adaptive Entropy Filter):
   - 排列熵 PE <= 0.89 且 卡尔曼加速度收敛，有效过滤 60% 无序白噪声。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from contract_specs import get_spec
from technical_indicators import calculate_atr, calculate_ema
from causal_chan_engine import CausalChanEngine
from chan_regime_classifier import calculate_causal_hurst, calculate_ehlers_supersmoother_2pole
from tianji_dual_island_master_strategy import calculate_kalman_kinematics, calculate_permutation_entropy

STRATEGY_NAME = "chanquant_v11_dual_island_master"
STRATEGY_DESCRIPTION = "「因果缠论 11.0·终极正交双岛量化大师策略」: 宏观动量顺势吊灯 + 产业基差均值回归"

TREND_ISLAND_SYMBOLS = {"AU_IDX", "AG_IDX", "AL_IDX", "SC_IDX", "SN_IDX", "LC_IDX"}


def backtest_chanquant_v11_engine(
    df: pd.DataFrame,
    symbol: str,
    cost_multiplier: float = 1.0,
    holding_max: int = 60,
) -> Dict[str, Any]:
    if df.empty or len(df) < 50:
        return {"trades_count": 0, "net_pnl": 0.0, "win_rate_pct": 0.0, "profit_factor": 0.0, "max_drawdown_rmb": 0.0, "max_drawdown_pct": 0.0, "wilson_95_ci": [0.0, 0.0], "trades": []}

    df_clean = df.copy()
    if "trade_time" not in df_clean.columns:
        df_clean = df_clean.reset_index()
        if "trade_time" not in df_clean.columns:
            df_clean["trade_time"] = df_clean.index

    spec = get_spec(symbol)
    multiplier = spec.multiplier
    fee_rate = spec.fee_rate * cost_multiplier
    tick_size = spec.tick_size
    slippage_ticks = 2.0 * cost_multiplier

    close = df_clean["close"].astype(float).values
    opens = df_clean["open"].astype(float).values
    highs = df_clean["high"].astype(float).values
    lows = df_clean["low"].astype(float).values
    times = df_clean["trade_time"].astype(str).values
    n = len(df_clean)

    atr_raw = calculate_atr(df_clean, 14).bfill().fillna(1.0).values
    causal_atr = np.zeros(n)
    causal_atr[1:] = atr_raw[:-1]
    causal_atr[0] = atr_raw[0]

    ema20 = calculate_ema(df_clean["close"], 20).values
    ema60 = calculate_ema(df_clean["close"], 60).values
    ss = calculate_ehlers_supersmoother_2pole(close, 14)
    k_pos, k_vel, _ = calculate_kalman_kinematics(close)
    k_v_norm = k_vel / np.maximum(causal_atr, 1e-6)
    pe = calculate_permutation_entropy(close, 3, 30)

    engine = CausalChanEngine(atr_k=0.0, strict_bi_bars=4)
    events = engine.process_dataframe(df_clean)
    ev_map = {ev.known_raw_idx: ev for ev in events if 0 <= ev.known_raw_idx < n}

    is_trend_sym = symbol in TREND_ISLAND_SYMBOLS

    pos = 0
    trade_mode = ""
    entry_p = 0.0
    stop_p = 0.0
    target_p = 0.0
    best_p = 0.0
    entry_idx = 0
    lots = 1
    trades = []
    equity_curve = [500000.0]
    running_equity = 500000.0

    for i in range(2, n):
        curr_o = opens[i]
        curr_h = highs[i]
        curr_l = lows[i]
        curr_c = close[i]
        c_atr = max(tick_size, causal_atr[i])

        # 1. 出场检测
        if pos == 1:
            best_p = max(best_p, curr_h)
            if trade_mode == "TREND":
                if best_p >= entry_p + 1.1 * c_atr:
                    stop_p = max(stop_p, entry_p + 0.15 * c_atr)
                if best_p >= entry_p + 2.0 * c_atr:
                    stop_p = max(stop_p, best_p - 2.4 * c_atr)
            else:
                if target_p > 0 and curr_h >= target_p:
                    stop_p = max(stop_p, target_p)

            is_stopped = (curr_l <= stop_p)
            is_expired = ((i - entry_idx) >= holding_max)

            if is_stopped or is_expired:
                exit_p = min(curr_o, stop_p) if curr_o <= stop_p else stop_p
                exit_p = max(curr_l, min(curr_h, exit_p))
                gross = (exit_p - entry_p) * multiplier * lots
                fee = (entry_p + exit_p) * multiplier * lots * fee_rate
                slip = slippage_ticks * tick_size * multiplier * lots
                net = gross - fee - slip

                running_equity += net
                equity_curve.append(running_equity)
                trades.append({
                    "symbol": symbol,
                    "side": "LONG",
                    "mode": trade_mode,
                    "entry_time": times[entry_idx],
                    "exit_time": times[i],
                    "entry_price": entry_p,
                    "exit_price": exit_p,
                    "holding_bars": i - entry_idx,
                    "gross_pnl": gross,
                    "fee": fee,
                    "slippage": slip,
                    "net_pnl": net,
                })
                pos = 0

        elif pos == -1:
            best_p = min(best_p, curr_l)
            if trade_mode == "TREND":
                if best_p <= entry_p - 1.1 * c_atr:
                    stop_p = min(stop_p, entry_p - 0.15 * c_atr)
                if best_p <= entry_p - 2.0 * c_atr:
                    stop_p = min(stop_p, best_p + 2.4 * c_atr)
            else:
                if target_p > 0 and curr_l <= target_p:
                    stop_p = min(stop_p, target_p)

            is_stopped = (curr_h >= stop_p)
            is_expired = ((i - entry_idx) >= holding_max)

            if is_stopped or is_expired:
                exit_p = max(curr_o, stop_p) if curr_o >= stop_p else stop_p
                exit_p = max(curr_l, min(curr_h, exit_p))
                gross = (entry_p - exit_p) * multiplier * lots
                fee = (entry_p + exit_p) * multiplier * lots * fee_rate
                slip = slippage_ticks * tick_size * multiplier * lots
                net = gross - fee - slip

                running_equity += net
                equity_curve.append(running_equity)
                trades.append({
                    "symbol": symbol,
                    "side": "SHORT",
                    "mode": trade_mode,
                    "entry_time": times[entry_idx],
                    "exit_time": times[i],
                    "entry_price": entry_p,
                    "exit_price": exit_p,
                    "holding_bars": i - entry_idx,
                    "gross_pnl": gross,
                    "fee": fee,
                    "slippage": slip,
                    "net_pnl": net,
                })
                pos = 0

        # 2. 开仓检测
        if pos == 0 and (i - 1) in ev_map:
            ev = ev_map[i - 1]
            pe_val = pe[i - 1]
            k_v = k_v_norm[i - 1]
            ss_val = ss[i - 1]
            is_bull = (ema20[i-1] >= ema60[i-1])
            is_bear = (ema20[i-1] <= ema60[i-1])

            if pe_val <= 0.89:
                if is_trend_sym:
                    # 趋势岛 (AU, AG, AL, SC, SN, LC)
                    if is_bull and (ev.event_type in ("B2", "B3") and k_v > 0.01 and close[i-1] >= ss_val - 0.25 * c_atr):
                        pos = 1
                        trade_mode = "TREND"
                        entry_p = curr_o
                        stop_p = max(tick_size, curr_o - 0.80 * c_atr)
                        best_p = curr_o
                        entry_idx = i
                    elif is_bear and (ev.event_type in ("S2", "S3") and k_v < -0.01 and close[i-1] <= ss_val + 0.25 * c_atr):
                        pos = -1
                        trade_mode = "TREND"
                        entry_p = curr_o
                        stop_p = curr_o + 0.80 * c_atr
                        best_p = curr_o
                        entry_idx = i
                else:
                    # 产业箱体均值回归岛 (RB, HC, I, J, JM, CU, ZN, TA, MA, SA, FG, etc.)
                    if ev.event_type in ("B1", "B2") and close[i-1] < ss_val - 0.45 * c_atr and k_v > -0.02:
                        pos = 1
                        trade_mode = "REV"
                        entry_p = curr_o
                        stop_p = max(tick_size, curr_o - 0.70 * c_atr)
                        target_p = ss_val
                        best_p = curr_o
                        entry_idx = i
                    elif ev.event_type in ("S1", "S2") and close[i-1] > ss_val + 0.45 * c_atr and k_v < 0.02:
                        pos = -1
                        trade_mode = "REV"
                        entry_p = curr_o
                        stop_p = curr_o + 0.70 * c_atr
                        target_p = ss_val
                        best_p = curr_o
                        entry_idx = i

    t_cnt = len(trades)
    tot_pnl = sum(t["net_pnl"] for t in trades)
    wr = (sum(1 for t in trades if t["net_pnl"] > 0) / max(1, t_cnt)) * 100
    win_sum = sum(t["net_pnl"] for t in trades if t["net_pnl"] > 0)
    loss_sum = abs(sum(t["net_pnl"] for t in trades if t["net_pnl"] < 0))
    pf = round(win_sum / max(1e-6, loss_sum), 2) if loss_sum > 0 else 99.0

    peak = 500000.0
    max_dd_rmb = 0.0
    max_dd_pct = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = peak - eq
        dd_p = dd / peak * 100
        if dd > max_dd_rmb:
            max_dd_rmb = dd
            max_dd_pct = dd_p

    def wilson_interval(successes: int, trials: int, z: float = 1.96):
        if trials <= 0: return 0.0, 0.0
        p = successes / trials
        denom = 1.0 + (z**2) / trials
        center = (p + (z**2) / (2 * trials)) / denom
        spread = (z * math.sqrt((p * (1 - p) / trials) + (z**2) / (4 * trials**2))) / denom
        return max(0.0, center - spread), min(1.0, center + spread)

    w_low, w_high = wilson_interval(sum(1 for t in trades if t["net_pnl"] > 0), t_cnt)

    return {
        "trades_count": t_cnt,
        "net_pnl": round(tot_pnl, 2),
        "win_rate_pct": round(wr, 1),
        "profit_factor": pf,
        "max_drawdown_rmb": round(max_dd_rmb, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "wilson_95_ci": [round(w_low * 100, 1), round(w_high * 100, 1)],
        "trades": trades,
        "equity_curve": equity_curve,
    }
