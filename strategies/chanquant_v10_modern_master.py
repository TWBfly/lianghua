"""
strategies/chanquant_v10_modern_master.py — 「因果缠论 10.0·现代顶级非对称正反馈量化大师策略」
(ChanQuant 10.0 Modern Master Strategy: Causal Chan + DSP Zero-Lag + FVG Order Flow + Asymmetric Chandelier)

【核心数学物理架构与正反馈第一性原理】：
1. 信号发生引擎 (Signal Generation Engine):
   - 纯因果缠论状态机 (Causal Chan State Machine): B1/B2/B3 与 S1/S2/S3 严格右侧 known_time 触发；
   - 机构流动性失衡 (LuxAlgo Fair Value Gap, FVG): 检测 3-Bar 脉冲真空区与回踩承接；
   - 微观订单流失衡 (Order Flow Imbalance, OFI Z-Score): 确认主力大单主动推动力；
   - 埃勒斯 2 极超平滑零滞后滤波器 (Ehlers 2-Pole SuperSmoother): 40dB 阻带衰减，消除均线时滞。

2. 动力学机制分类与解耦 (Kinetic Regime Decoupling):
   - 动量顺势通道 (B2/B3): 当 Ehlers 速度 > 0 且 (OFI >= 0.50 或 FVG 回踩) 顺势做多；
   - 极值均值回归通道 (B1): 当价格偏离 Ehlers 均线 >= 0.85 ATR 且底背驰衰竭，反弹做多；
   - 符号排列熵混沌门禁 (PE <= 0.90): 仅在市场处于极度无序白噪声时避险。

3. 非对称非线性出场与风控 (Asymmetric Non-Linear Risk & Exit Engine):
   - 初始紧致止损: Entry - 0.85 * ATR (严格锁定左尾最大亏损);
   - 动态保本锁胜: 浮盈 >= 1.1 * ATR 时，强制提升止损至 Entry + 0.15 * ATR (消灭已盈利单翻亏);
   - 宽幅动态吊灯追踪: 浮盈 >= 2.0 * ATR 时，激活 Highest - 2.6 * ATR 动态追踪，放飞右尾超级单边 (+4.0 ~ +10.0 ATR)。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from contract_specs import get_spec
from technical_indicators import calculate_atr
from causal_chan_engine import CausalChanEngine
from chan_regime_classifier import calculate_causal_hurst, calculate_ehlers_supersmoother_2pole
from tianji_dual_island_master_strategy import calculate_kalman_kinematics, calculate_permutation_entropy

STRATEGY_NAME = "chanquant_v10_modern_master"
STRATEGY_DESCRIPTION = "「因果缠论 10.0·现代顶级非对称正反馈量化大师策略」: Causal Chan + Ehlers DSP + FVG 订单流 + 非对称动态吊灯"


def calculate_fvg_and_ofi(df: pd.DataFrame, window: int = 20) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    计算 Fair Value Gap (FVG 机构失衡强度) 与 订单流不平衡量 (OFI Z-Score)
    """
    close = df["close"].astype(float).values
    opens = df["open"].astype(float).values
    highs = df["high"].astype(float).values
    lows = df["low"].astype(float).values
    vol = df.get("volume", pd.Series(np.ones(len(df)))).astype(float).values
    oi = df.get("open_interest", pd.Series(np.zeros(len(df)))).astype(float).values
    n = len(df)

    # 1. FVG 机构失衡强度 (多头缺口: Low[t] > High[t-2], 空头缺口: High[t] < Low[t-2])
    fvg_bull = np.zeros(n)
    fvg_bear = np.zeros(n)
    for t in range(2, n):
        if lows[t] > highs[t - 2]:
            fvg_bull[t] = 1.0
        elif highs[t] < lows[t - 2]:
            fvg_bear[t] = 1.0

    # 2. 因果 OFI Z-Score
    c_dir = np.sign(close - opens)
    p_dir = np.zeros(n)
    p_dir[1:] = np.sign(close[1:] - close[:-1])
    delta_oi = np.zeros(n)
    delta_oi[1:] = oi[1:] - oi[:-1]

    ofi_raw = vol * c_dir + 0.3 * delta_oi * p_dir
    s_ofi = pd.Series(ofi_raw)
    mean_w = s_ofi.rolling(window, min_periods=5).mean().bfill()
    std_w = s_ofi.rolling(window, min_periods=5).std().bfill() + 1e-8
    ofi_zscore = ((s_ofi - mean_w) / std_w).clip(-3.0, 3.0).values

    return fvg_bull, fvg_bear, ofi_zscore


def calculate_factors_v10(df: pd.DataFrame) -> pd.DataFrame:
    """计算因果缠论 10.0 全息特征矩阵"""
    if df.empty or len(df) < 50:
        return pd.DataFrame(index=df.index)

    res = pd.DataFrame(index=df.index)
    close = df["close"].astype(float).values
    n = len(df)

    # 1. 因果 ATR 与 Ehlers 零滞后滤波器
    atr_series = calculate_atr(df, 14).bfill().fillna(1.0).values
    causal_atr = np.zeros(n)
    causal_atr[1:] = atr_series[:-1]
    causal_atr[0] = atr_series[0]
    res["atr"] = causal_atr

    ss_price = calculate_ehlers_supersmoother_2pole(close, period=12)
    ss_slope = np.zeros(n)
    ss_slope[1:] = (ss_price[1:] - ss_price[:-1]) / np.maximum(causal_atr[1:], 1e-6)
    res["ss_price"] = ss_price
    res["ss_slope"] = ss_slope

    # 2. 卡尔曼运动学与排列熵
    k_pos, k_vel, _ = calculate_kalman_kinematics(close)
    res["k_pos"] = k_pos
    res["k_vel_norm"] = k_vel / np.maximum(causal_atr, 1e-6)
    res["pe"] = calculate_permutation_entropy(close, order=3, window=30)
    res["hurst"] = calculate_causal_hurst(close, 50)

    # 3. FVG 与 OFI 订单流
    fvg_bull, fvg_bear, ofi_z = calculate_fvg_and_ofi(df, window=20)
    res["fvg_bull"] = fvg_bull
    res["fvg_bear"] = fvg_bear
    res["ofi_zscore"] = ofi_z

    # 4. 因果缠论买卖点事件
    engine = CausalChanEngine(atr_k=0.0, strict_bi_bars=4)
    events = engine.process_dataframe(df)

    b1_arr = np.zeros(n)
    b2_arr = np.zeros(n)
    b3_arr = np.zeros(n)
    s1_arr = np.zeros(n)
    s2_arr = np.zeros(n)
    s3_arr = np.zeros(n)
    zs_high_arr = np.zeros(n)
    zs_low_arr = np.zeros(n)

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

            zs_high_arr[idx] = ev.zs_high
            zs_low_arr[idx] = ev.zs_low

    res["b1"] = b1_arr
    res["b2"] = b2_arr
    res["b3"] = b3_arr
    res["s1"] = s1_arr
    res["s2"] = s2_arr
    res["s3"] = s3_arr
    res["zs_high"] = zs_high_arr
    res["zs_low"] = zs_low_arr

    return res
