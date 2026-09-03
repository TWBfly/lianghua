"""
strategies/chanquant_v8_production_strategy.py — 「因果缠论 9.0·终极双岛实盘量化生产策略」
(ChanQuant 9.0 Production Strategy: Orthogonal Dual-Island Structural Confluence Execution)

【第一性原理与核心数学物理架构】：
1. 资产物理特异性双岛完全隔离 (Asset Physics Specialization):
   - 【宏观长程动量岛 (Trend Island)】：
     管辖资产：沪金 (AU)、沪银 (AG)、沪铝 (AL)
     核心逻辑：顺应 15M EMA20 >= EMA60 宏观大势，专攻 3买/3卖 中枢突破回踩与 2买/2卖 动量共振，2.5 ATR 动态吊灯放飞右尾超级趋势 (+4.0~+10.0 ATR)；
   - 【产业中枢箱体岛 (Reversion Island)】：
     管辖资产：螺纹 (RB)、热卷 (HC)、铁矿 (I)、焦炭 (J)、焦煤 (JM)、沪锌 (ZN)、沪铜 (CU)、沪锡 (SN)、碳酸锂 (LC)、PTA (TA)、甲醇 (MA)、纯碱 (SA)、玻璃 (FG)、豆粕 (M)、豆油 (Y)、棕榈油 (P)、玉米 (C)、棉花 (CF)、白糖 (SR)、橡胶 (RU)、工业硅 (SI)、原油 (SC)
     核心逻辑：顺应趋势方向进行中枢极值触轨高抛低吸 (ZS_Low 低吸 / ZS_High 高抛) 与 1买/1卖 拐点回归，严格在 ZS_mid 止盈，0.75 ATR 硬止损。

2. 动态自适应混沌门禁 (Adaptive Entropy Noise Gate):
   - 门禁设为 PE <= 0.88，仅在无动量纯白噪声时避险；
   - 保证单品种 8k 根 K 线交易达到 20~80 笔，全市场组合交易 300~1,000 笔。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from contract_specs import get_spec
from technical_indicators import calculate_atr, calculate_ema, calculate_adx
from causal_chan_engine import CausalChanEngine
from chan_regime_classifier import calculate_causal_hurst
try:
    from strategies.tianji_dual_island_master_strategy import calculate_kalman_kinematics, calculate_permutation_entropy
except ImportError:
    from tianji_dual_island_master_strategy import calculate_kalman_kinematics, calculate_permutation_entropy


STRATEGY_NAME = "chanquant_v8_production_strategy"
STRATEGY_DESCRIPTION = "「因果缠论 9.0·终极双岛实盘量化生产策略」: 宏观动量顺势放飞 + 产业中枢极值回归"

TREND_ISLAND_SYMBOLS = {
    "AU_IDX", "AG_IDX", "AL_IDX"
}

REVERSION_ISLAND_SYMBOLS = {
    "RB_IDX", "HC_IDX", "I_IDX", "J_IDX", "JM_IDX", "ZN_IDX", "CU_IDX", "SN_IDX", "LC_IDX",
    "TA_IDX", "MA_IDX", "SA_IDX", "FG_IDX", "M_IDX", "Y_IDX", "P_IDX", "C_IDX", "CF_IDX", "SR_IDX", "RU_IDX", "SI_IDX", "SC_IDX"
}


@dataclass
class ChanSignal:
    symbol: str
    side: int  # +1 Long, -1 Short, 0 Flat
    mode: str  # 'TREND' or 'REVERSION'
    stop_price: float
    target_price: float
    causal_atr: float
    reason: str


def calculate_factors_v8(df: pd.DataFrame, atr_period: int = 14) -> pd.DataFrame:
    """
    计算因果缠论 9.0 全息特征与状态矩阵 (严格无未来信息)
    """
    if df.empty or len(df) < 80:
        return pd.DataFrame(index=df.index)

    res = pd.DataFrame(index=df.index)
    close = df["close"].astype(float)
    close_vals = close.values
    n = len(df)

    # 1. 经典指标与多尺度均线
    res["atr"] = calculate_atr(df, atr_period)
    res["ema20"] = calculate_ema(close, 20)
    res["ema60"] = calculate_ema(close, 60)
    res["ema240"] = calculate_ema(close, 240)
    res["adx"] = calculate_adx(df, 14)

    # 2. 卡尔曼状态空间运动学与混沌熵
    k_pos, k_vel, k_acc = calculate_kalman_kinematics(close_vals)
    res["k_pos"] = k_pos
    res["k_vel"] = k_vel
    res["k_vel_norm"] = k_vel / (res["atr"].values + 1e-8)
    res["pe"] = calculate_permutation_entropy(close_vals, order=3, window=30)
    res["hurst"] = calculate_causal_hurst(close_vals, window=50)

    # 3. 严格因果缠论结构与中枢几何
    engine = CausalChanEngine(atr_k=0.0, strict_bi_bars=4)
    events = engine.process_dataframe(df)

    b1_arr = np.zeros(n)
    b2_arr = np.zeros(n)
    b3_arr = np.zeros(n)
    s1_arr = np.zeros(n)
    s2_arr = np.zeros(n)
    s3_arr = np.zeros(n)
    zs_h_arr = np.zeros(n)
    zs_l_arr = np.zeros(n)
    zs_mid_arr = np.zeros(n)
    trig_p_arr = np.zeros(n)

    for ev in events:
        idx = ev.known_raw_idx
        if 0 <= idx < n:
            if ev.event_type == "B1":
                b1_arr[idx] = 1.0
            elif ev.event_type == "B2":
                b2_arr[idx] = 1.0
            elif ev.event_type == "B3":
                b3_arr[idx] = 1.0
            elif ev.event_type == "S1":
                s1_arr[idx] = 1.0
            elif ev.event_type == "S2":
                s2_arr[idx] = 1.0
            elif ev.event_type == "S3":
                s3_arr[idx] = 1.0

            zs_h_arr[idx] = ev.zs_high
            zs_l_arr[idx] = ev.zs_low
            if ev.zs_high > 0 and ev.zs_low > 0:
                zs_mid_arr[idx] = (ev.zs_high + ev.zs_low) * 0.5
            trig_p_arr[idx] = ev.trigger_price

    res["b1"] = b1_arr
    res["b2"] = b2_arr
    res["b3"] = b3_arr
    res["s1"] = s1_arr
    res["s2"] = s2_arr
    res["s3"] = s3_arr
    res["zs_high"] = zs_h_arr
    res["zs_low"] = zs_l_arr
    res["zs_mid"] = zs_mid_arr
    res["trigger_price"] = trig_p_arr

    return res


def evaluate_chan_signal(
    pdata_or_df: Any,
    b_idx: int,
    symbol: str,
    spec: Any = None,
    tick_size: float = 0.01,
) -> ChanSignal:
    """
    单一同源策略核心决策函数 (ChanQuant 9.0 双岛物理共振版)
    """
    if spec is None:
        spec = get_spec(symbol)
        tick_size = spec.tick_size

    if isinstance(pdata_or_df, dict) and "factors_arrays" in pdata_or_df:
        f_arrs = pdata_or_df["factors_arrays"]
        close_sig = pdata_or_df["close"][b_idx - 1]
        causal_atr = pdata_or_df["causal_atr"][b_idx]
        sig_idx = b_idx - 1
        n_factors = len(pdata_or_df["close"])
        if sig_idx < 0 or sig_idx >= n_factors:
            return ChanSignal(symbol=symbol, side=0, mode="", stop_price=0.0, target_price=0.0, causal_atr=causal_atr, reason="")

        h_val = float(f_arrs["hurst"][sig_idx])
        pe_val = float(f_arrs["pe"][sig_idx])
        adx_val = float(f_arrs["adx"][sig_idx])
        b1 = f_arrs["b1"][sig_idx]
        b2 = f_arrs["b2"][sig_idx]
        b3 = f_arrs["b3"][sig_idx]
        s1 = f_arrs["s1"][sig_idx]
        s2 = f_arrs["s2"][sig_idx]
        s3 = f_arrs["s3"][sig_idx]
        zs_h = f_arrs["zs_high"][sig_idx]
        zs_l = f_arrs["zs_low"][sig_idx]
        zs_mid = f_arrs["zs_mid"][sig_idx]
        trig_p = f_arrs["trigger_price"][sig_idx]
        ema20 = f_arrs["ema20"][sig_idx]
        ema60 = f_arrs["ema60"][sig_idx]
        k_vel = f_arrs["k_vel_norm"][sig_idx]

    elif isinstance(pdata_or_df, dict) and "factors" in pdata_or_df:
        factors = pdata_or_df["factors"]
        close_sig = pdata_or_df["close"][b_idx - 1]
        causal_atr = pdata_or_df["causal_atr"][b_idx]
        sig_idx = b_idx - 1
        if sig_idx < 0 or sig_idx >= len(factors):
            return ChanSignal(symbol=symbol, side=0, mode="", stop_price=0.0, target_price=0.0, causal_atr=causal_atr, reason="")

        h_val = float(factors["hurst"].iloc[sig_idx])
        pe_val = float(factors["pe"].iloc[sig_idx])
        adx_val = float(factors["adx"].iloc[sig_idx])
        b1 = factors["b1"].iloc[sig_idx]
        b2 = factors["b2"].iloc[sig_idx]
        b3 = factors["b3"].iloc[sig_idx]
        s1 = factors["s1"].iloc[sig_idx]
        s2 = factors["s2"].iloc[sig_idx]
        s3 = factors["s3"].iloc[sig_idx]
        zs_h = factors["zs_high"].iloc[sig_idx]
        zs_l = factors["zs_low"].iloc[sig_idx]
        zs_mid = factors["zs_mid"].iloc[sig_idx]
        trig_p = factors["trigger_price"].iloc[sig_idx]
        ema20 = factors["ema20"].iloc[sig_idx]
        ema60 = factors["ema60"].iloc[sig_idx]
        k_vel = factors["k_vel_norm"].iloc[sig_idx]

    else:
        df = pdata_or_df
        factors = calculate_factors_v8(df)
        close_sig = float(df["close"].iloc[b_idx - 1])
        causal_atr = max(tick_size, float(factors["atr"].iloc[b_idx - 1]))
        sig_idx = b_idx - 1
        if sig_idx < 0 or sig_idx >= len(factors):
            return ChanSignal(symbol=symbol, side=0, mode="", stop_price=0.0, target_price=0.0, causal_atr=causal_atr, reason="")

        h_val = float(factors["hurst"].iloc[sig_idx])
        pe_val = float(factors["pe"].iloc[sig_idx])
        adx_val = float(factors["adx"].iloc[sig_idx])
        b1 = factors["b1"].iloc[sig_idx]
        b2 = factors["b2"].iloc[sig_idx]
        b3 = factors["b3"].iloc[sig_idx]
        s1 = factors["s1"].iloc[sig_idx]
        s2 = factors["s2"].iloc[sig_idx]
        s3 = factors["s3"].iloc[sig_idx]
        zs_h = factors["zs_high"].iloc[sig_idx]
        zs_l = factors["zs_low"].iloc[sig_idx]
        zs_mid = factors["zs_mid"].iloc[sig_idx]
        trig_p = factors["trigger_price"].iloc[sig_idx]
        ema20 = factors["ema20"].iloc[sig_idx]
        ema60 = factors["ema60"].iloc[sig_idx]
        k_vel = factors["k_vel_norm"].iloc[sig_idx]

    def round_tick(val: float) -> float:
        return round(round(val / tick_size) * tick_size, 4)

    # 1. 动态自适应混沌噪声门禁
    if pe_val > 0.88 and abs(k_vel) < 0.02:
        return ChanSignal(symbol=symbol, side=0, mode="", stop_price=0.0, target_price=0.0, causal_atr=causal_atr, reason="")

    is_bull = (ema20 >= ema60)
    is_trend_island = (symbol in TREND_ISLAND_SYMBOLS)

    # =========================================================================
    # 岛屿 1: 宏观长程动量岛 (Trend Island - 沪金 AU、沪银 AG、沪铝 AL)
    # =========================================================================
    if is_trend_island:
        if is_bull:
            if b3 > 0.5 and k_vel > 0.01:
                sl = max(tick_size, trig_p - 0.6 * causal_atr if trig_p > 0 else close_sig - 0.8 * causal_atr)
                return ChanSignal(symbol=symbol, side=1, mode="TREND", stop_price=round_tick(sl), target_price=0.0, causal_atr=causal_atr, reason="B3_TREND")
            if b2 > 0.5 and close_sig >= ema20 and k_vel > 0.025:
                sl = max(tick_size, trig_p - 0.8 * causal_atr if trig_p > 0 else close_sig - 0.8 * causal_atr)
                return ChanSignal(symbol=symbol, side=1, mode="TREND", stop_price=round_tick(sl), target_price=0.0, causal_atr=causal_atr, reason="B2_TREND")
        else:
            if s3 > 0.5 and k_vel < -0.01:
                sl = trig_p + 0.6 * causal_atr if trig_p > 0 else close_sig + 0.8 * causal_atr
                return ChanSignal(symbol=symbol, side=-1, mode="TREND", stop_price=round_tick(sl), target_price=0.0, causal_atr=causal_atr, reason="S3_TREND")
            if s2 > 0.5 and close_sig <= ema20 and k_vel < -0.025:
                sl = trig_p + 0.8 * causal_atr if trig_p > 0 else close_sig + 0.8 * causal_atr
                return ChanSignal(symbol=symbol, side=-1, mode="TREND", stop_price=round_tick(sl), target_price=0.0, causal_atr=causal_atr, reason="S2_TREND")

    # =========================================================================
    # 岛屿 2: 产业中枢箱体岛 (Reversion Island - 螺纹、铁矿、焦煤、焦炭、农产品、能化等)
    # =========================================================================
    else:
        if is_bull:
            if b1 > 0.5 and k_vel > 0.015:
                sl = max(tick_size, trig_p - 0.75 * causal_atr if trig_p > 0 else close_sig - 0.75 * causal_atr)
                tp = zs_mid if (zs_mid > close_sig and (zs_mid - close_sig) >= 1.0 * causal_atr) else close_sig + 1.5 * causal_atr
                return ChanSignal(symbol=symbol, side=1, mode="REVERSION", stop_price=round_tick(sl), target_price=round_tick(tp), causal_atr=causal_atr, reason="B1_REV")
            if zs_h > 0 and zs_l > 0 and zs_mid > 0 and close_sig <= (zs_l + 0.2 * causal_atr) and (zs_mid - close_sig) >= 1.0 * causal_atr and k_vel > -0.015:
                sl = max(tick_size, zs_l - 0.75 * causal_atr)
                return ChanSignal(symbol=symbol, side=1, mode="REVERSION", stop_price=round_tick(sl), target_price=round_tick(zs_mid), causal_atr=causal_atr, reason="ZS_LOW_FADE")
        else:
            if s1 > 0.5 and k_vel < -0.015:
                sl = trig_p + 0.75 * causal_atr if trig_p > 0 else close_sig + 0.75 * causal_atr
                tp = zs_mid if (zs_mid > 0 and (close_sig - zs_mid) >= 1.0 * causal_atr) else close_sig - 1.5 * causal_atr
                return ChanSignal(symbol=symbol, side=-1, mode="REVERSION", stop_price=round_tick(sl), target_price=round_tick(tp), causal_atr=causal_atr, reason="S1_REV")
            if zs_h > 0 and zs_l > 0 and zs_mid > 0 and close_sig >= (zs_h - 0.2 * causal_atr) and (close_sig - zs_mid) >= 1.0 * causal_atr and k_vel < 0.015:
                sl = zs_h + 0.75 * causal_atr
                return ChanSignal(symbol=symbol, side=-1, mode="REVERSION", stop_price=round_tick(sl), target_price=round_tick(zs_mid), causal_atr=causal_atr, reason="ZS_HIGH_FADE")

    return ChanSignal(symbol=symbol, side=0, mode="", stop_price=0.0, target_price=0.0, causal_atr=causal_atr, reason="")


def calculate_signal(df: pd.DataFrame, symbol: str = "") -> pd.Series:
    """
    标准统一生产策略接口：返回逐柱信号 (+1=多, -1=空, 0=空仓)
    """
    if df.empty or len(df) < 80:
        return pd.Series(0.0, index=df.index)

    spec = get_spec(symbol)
    factors = calculate_factors_v8(df)
    n = len(df)
    signals = np.zeros(n)

    pdata = {
        "factors": factors,
        "close": df["close"].astype(float).values,
        "open": df["open"].astype(float).values,
        "causal_atr": np.insert(factors["atr"].values[:-1], 0, factors["atr"].values[0]),
    }

    for i in range(1, n):
        sig = evaluate_chan_signal(pdata, i, symbol, spec, spec.tick_size)
        signals[i] = float(sig.side)

    return pd.Series(signals, index=df.index)
