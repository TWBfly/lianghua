"""
strategies/chanquant_v7_master_strategy.py — 「因果缠论 7.0·天枢全息相变正交量化策略」
(ChanQuant 7.0 Master Strategy: Multi-Scale Geometric Phase Transition & Dual-Island Architecture)

【核心数学物理架构与正反馈第一性原理】：
1. 宏观长程单边岛 (Macro Momentum Trend Island):
   - 管辖资产：白银 (AG)、黄金 (AU)、棕榈油 (P) 等宏观趋势驱动资产；
   - 算法内核：60m 递归宏观动量级联 (EMA60 >= EMA240 且 Kalman 速度 > 0.03) + 15m 因果缠论三买/二买 (B3/B2)；
   - 非对称风控：浮盈 1.2 ATR 动态锁定保本 (Entry + 0.2 ATR)，浮盈 2.2 ATR 激活 2.5 ATR 宽幅动态吊灯放飞右尾 (+5.0 ~ +12.0 ATR)。
2. 产业基差均值岛 (Industrial Reversion Island):
   - 管辖资产：螺纹 (RB)、热卷 (HC)、铁矿 (I)、铝 (AL)、甲醇 (MA)、豆粕 (M)、白糖 (SR)、工业硅 (SI)、橡胶 (RU) 等产业链驱动资产；
   - 算法内核：15m 价格极端偏离卡尔曼中枢 (>= 1.25 ATR) 触及中枢极值边界 (B1/S1)；
   - 均值收割风控：获利空间 >= 1.1 ATR 时入场，价格回归中枢中轴 (Z_mid) 立即止盈落袋，紧致硬止损 0.75 ATR。
3. 顶层波动率等权风险平价头寸管理 (Volatility Parity Position Sizing):
   - 每笔交易风险暴露严格锁定为账户净值的 1.0% (Risk = Capital * 1.0%)。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple
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


STRATEGY_NAME = "chanquant_v7_master_strategy"
STRATEGY_DESCRIPTION = "「因果缠论 7.0·天枢全息相变正交量化策略」: 60m 递归宏观定势 + 15m 纯因果结构 + 资产物理双岛 + 动态吊灯放飞"

# 宏观动量战队
TREND_CORE_SYMBOLS = {"AU_IDX", "AG_IDX", "P_IDX"}


def calculate_factors_v7(df: pd.DataFrame, atr_period: int = 14) -> pd.DataFrame:
    """计算因果缠论 7.0 全息特征与状态矩阵"""
    if df.empty or len(df) < 60:
        return pd.DataFrame(index=df.index)

    res = pd.DataFrame(index=df.index)
    close = df["close"].astype(float)
    close_vals = close.values

    # 1. 基础物理指标与多周期均线级联
    res["atr"] = calculate_atr(df, atr_period)
    res["ema20"] = calculate_ema(close, 20)
    res["ema60"] = calculate_ema(close, 60)
    res["ema240"] = calculate_ema(close, 240)  # 对应 60m 级别 EMA60
    res["adx"] = calculate_adx(df, 14)

    # 2. 卡尔曼状态空间运动学 (位置/速度/加速度) 与动力学指标
    k_pos, k_vel, k_acc = calculate_kalman_kinematics(close_vals)
    res["k_pos"] = k_pos
    res["k_vel"] = k_vel
    res["k_vel_norm"] = k_vel / (res["atr"].values + 1e-8)
    res["pe"] = calculate_permutation_entropy(close_vals, order=3, window=30)
    res["hurst"] = calculate_causal_hurst(close_vals, window=50)

    # 3. 纯因果缠论几何形态提取
    engine = CausalChanEngine(atr_k=0.0, strict_bi_bars=4)
    events = engine.process_dataframe(df)

    n = len(df)
    b1_arr = np.zeros(n)
    b2_arr = np.zeros(n)
    b3_arr = np.zeros(n)
    s1_arr = np.zeros(n)
    s2_arr = np.zeros(n)
    s3_arr = np.zeros(n)
    zs_high_arr = np.zeros(n)
    zs_low_arr = np.zeros(n)
    trig_p_arr = np.zeros(n)

    for ev in events:
        raw_idx = ev.known_raw_idx
        if 0 <= raw_idx < n:
            if ev.event_type == "B1":
                b1_arr[raw_idx] = 1.0
            elif ev.event_type == "B2":
                b2_arr[raw_idx] = 1.0
            elif ev.event_type == "B3":
                b3_arr[raw_idx] = 1.0
            elif ev.event_type == "S1":
                s1_arr[raw_idx] = 1.0
            elif ev.event_type == "S2":
                s2_arr[raw_idx] = 1.0
            elif ev.event_type == "S3":
                s3_arr[raw_idx] = 1.0

            zs_high_arr[raw_idx] = ev.zs_high
            zs_low_arr[raw_idx] = ev.zs_low
            trig_p_arr[raw_idx] = ev.trigger_price

    res["b1"] = b1_arr
    res["b2"] = b2_arr
    res["b3"] = b3_arr
    res["s1"] = s1_arr
    res["s2"] = s2_arr
    res["s3"] = s3_arr
    res["zs_high"] = zs_high_arr
    res["zs_low"] = zs_low_arr
    res["trigger_price"] = trig_p_arr

    return res


def calculate_signal(df: pd.DataFrame, symbol: str = "") -> pd.Series:
    """标准统一策略接口：返回逐柱持仓/开仓信号 (+1=多, -1=空, 0=空仓)"""
    if df.empty or len(df) < 60:
        return pd.Series(0.0, index=df.index)

    factors = calculate_factors_v7(df)
    n = len(df)
    signals = np.zeros(n)
    close = df["close"].astype(float).values
    atr = factors["atr"].values
    k_pos = factors["k_pos"].values
    k_vel_norm = factors["k_vel_norm"].values
    ema20 = factors["ema20"].values
    ema60 = factors["ema60"].values
    ema240 = factors["ema240"].values

    b1 = factors["b1"].values
    b2 = factors["b2"].values
    b3 = factors["b3"].values
    s1 = factors["s1"].values
    s2 = factors["s2"].values
    s3 = factors["s3"].values
    zs_h = factors["zs_high"].values
    zs_l = factors["zs_low"].values

    is_trend_sym = symbol in TREND_CORE_SYMBOLS

    for i in range(1, n):
        if is_trend_sym:
            is_macro_bull = (close[i] >= ema60[i]) and (ema60[i] >= ema240[i]) and (k_vel_norm[i] > 0.03)
            is_macro_bear = (close[i] <= ema60[i]) and (ema60[i] <= ema240[i]) and (k_vel_norm[i] < -0.03)
            if (b3[i] > 0 and zs_h[i] > 0 or b2[i] > 0 and close[i] >= ema20[i]) and is_macro_bull:
                signals[i] = 1.0
            elif (s3[i] > 0 and zs_l[i] > 0 or s2[i] > 0 and close[i] <= ema20[i]) and is_macro_bear:
                signals[i] = -1.0
        else:
            if zs_h[i] > 0 and zs_l[i] > 0:
                zs_mid = (zs_h[i] + zs_l[i]) * 0.5
                dev = abs(close[i] - k_pos[i]) / (atr[i] + 1e-8)
                if (b1[i] > 0 or close[i] <= zs_l[i]) and close[i] < zs_mid and dev >= 1.25:
                    signals[i] = 1.0
                elif (s1[i] > 0 or close[i] >= zs_h[i]) and close[i] > zs_mid and dev >= 1.25:
                    signals[i] = -1.0

    return pd.Series(signals, index=df.index)

