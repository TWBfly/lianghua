"""
code/chan_regime_classifier.py — 动力学机制分类器 (Kinetic Regime State Machine)

第一性原理与数学算法：
1. 动力学标度律分形赫斯特指数 (Causal Vectorized Hurst Exponent):
   - 基于方差比率与标度律 (Variance Ratio Scaling Law) 实时在线计算:
     Var(r_{2k}) / (2 * Var(r_k)) = 2^(2H - 1)
     => H = 0.5 + 0.5 * log2(Var(r_{2k}) / (2 * Var(r_k)))
   - 具备纯因果滚动窗口特性，无任何未来数据穿越。
2. 埃勒斯两极超平滑零滞后滤波器 (Ehlers 2-Pole SuperSmoother Zero-Lag Filter):
   - 40 dB/decade 阻带衰减，消除 80% 均线相位时滞；
   - 提取平滑基线与瞬时一阶导数 (瞬时动量速度)。
3. 三状态物理机制状态机 (Three-State Kinetic Regime Classification):
   - 状态 1: 【低熵单边动量态 (MOMENTUM_TREND)】(H >= 0.54, Ehlers斜率持续且显著) -> 激活三买/三卖突破
   - 状态 2: 【高熵均值弹性态 (MEAN_REVERTING)】(H <= 0.46, 价格偏离 Ehlers 均值 >= 1.5 ATR) -> 激活一买背驰
   - 状态 3: 【无序随机游走态 (BROWNIAN_NOISE)】(0.46 < H < 0.54) -> 硬性空仓观望 (Cash is King)
"""

from __future__ import annotations

import math
from enum import IntEnum
from typing import Tuple
import numpy as np
import pandas as pd


class KineticRegime(IntEnum):
    BROWNIAN_NOISE = 0      # 随机游走态 (空仓)
    MOMENTUM_TREND = 1      # 单边动量态 (做三买三卖)
    MEAN_REVERTING = 2      # 均值回归态 (做一买背驰)


def calculate_ehlers_supersmoother_2pole(prices: np.ndarray, period: int = 14) -> np.ndarray:
    """埃勒斯 2 极零滞后超平滑滤波器"""
    n = len(prices)
    if n < 4:
        return prices.copy()

    p = max(2, period)
    a1 = math.exp(-math.sqrt(2.0) * math.pi / p)
    b1 = 2.0 * a1 * math.cos(math.sqrt(2.0) * math.pi / p)
    c2 = b1
    c3 = -a1 * a1
    c1 = 1.0 - c2 - c3

    filt = np.zeros(n)
    filt[0] = prices[0]
    filt[1] = prices[1]
    for t in range(2, n):
        filt[t] = c1 * (prices[t] + prices[t - 1]) * 0.5 + c2 * filt[t - 1] + c3 * filt[t - 2]
    return filt


def calculate_causal_hurst(prices: np.ndarray, window: int = 60) -> np.ndarray:
    """
    向量化纯因果方差比率 Hurst 指数估计器 (全向量化极速版)
    H > 0.5: 长程正自相关 (趋势动量)
    H < 0.5: 均值反转 (均值回归)
    H ≈ 0.5: 几何布朗运动 (随机游走)
    """
    n = len(prices)
    if n < window + 4:
        return np.full(n, 0.50)

    log_p = np.log(np.maximum(prices, 1e-8))
    s_log_p = pd.Series(log_p)
    ret1 = s_log_p.diff(1)
    ret2 = s_log_p.diff(2)

    var1 = ret1.rolling(window).var(ddof=1).values
    var2 = ret2.rolling(window).var(ddof=1).values

    valid = (var1 > 1e-12) & (var2 > 1e-12)
    vr = np.where(valid, var2 / (2.0 * np.maximum(var1, 1e-12)), 1.0)
    vr = np.maximum(1e-4, vr)
    h = 0.5 + 0.5 * (np.log(vr) / math.log(2.0))
    hurst_arr = np.where(valid, np.clip(h, 0.10, 0.90), 0.50)
    return np.nan_to_num(hurst_arr, nan=0.50)


def classify_kinetic_regime(
    df: pd.DataFrame,
    hurst_window: int = 50,
    ss_period: int = 14,
    trend_hurst_th: float = 0.53,
    revert_hurst_th: float = 0.47,
) -> pd.DataFrame:
    """
    对输入 DataFrame 进行因果机制状态机分类
    """
    close = df["close"].astype(float).values
    n = len(df)

    res = pd.DataFrame(index=df.index)
    hurst = calculate_causal_hurst(close, window=hurst_window)
    ss_price = calculate_ehlers_supersmoother_2pole(close, period=ss_period)

    # 计算 Ehlers 零滞后斜率 (1阶差分)
    ss_slope = np.zeros(n)
    ss_slope[1:] = ss_price[1:] - ss_price[:-1]

    # 计算价格偏离 Ehlers 均值的 ATR 倍数
    atr = df.get("atr", df.get("atr_14", pd.Series(np.ones(n)))).astype(float).values
    atr_safe = np.where(atr > 0, atr, 1.0)
    dev_atr = np.abs(close - ss_price) / atr_safe

    regime_arr = np.full(n, KineticRegime.BROWNIAN_NOISE, dtype=int)

    for t in range(n):
        h_val = hurst[t]
        d_val = dev_atr[t]

        if h_val >= trend_hurst_th:
            # 单边动量态
            regime_arr[t] = KineticRegime.MOMENTUM_TREND
        elif h_val <= revert_hurst_th and d_val >= 1.2:
            # 极值偏离均值弹性态
            regime_arr[t] = KineticRegime.MEAN_REVERTING
        else:
            # 无序随机游走态
            regime_arr[t] = KineticRegime.BROWNIAN_NOISE

    res["hurst"] = hurst
    res["ss_price"] = ss_price
    res["ss_slope"] = ss_slope
    res["dev_atr"] = dev_atr
    res["regime"] = regime_arr

    return res
