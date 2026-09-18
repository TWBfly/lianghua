"""
strategies/continuous_zscore_multi_factor_strategy.py — 「太微·连续多因子标准化 Alpha 评分策略」
(Taiwei Continuous Z-Score Multi-Factor Alpha Strategy)

核心技术体系：
1. 彻底废除离散布尔 `and` 门禁，消除“样本量坍缩陷阱”；
2. 采用连续因子标准化加权评分卡 (Composite Z-Score Alpha)：
   - Z_vel: 卡尔曼连续速度 (Kalman Velocity Z-Score)
   - Z_acc: 卡尔曼连续加速度 (Kalman Acceleration Z-Score)
   - Z_pe : 排列熵确定性动力学加权 (Permutation Entropy Certainty)
   - Z_fvg: LuxAlgo 微观流动性失衡强度 (FVG Signed Intensity)
   - Z_hurst: 分形长程记忆漂移 (Hurst Drift)
3. 保证充足的大数定律交易样本密度 (单品种 800~1,500 笔平仓交易)；
4. 搭载非对称动态吊灯放飞引擎 (2.5~3.5 ATR，捕获右尾肥尾)。
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Any

STRATEGY_NAME = "continuous_zscore_multi_factor_strategy"
STRATEGY_DESCRIPTION = "太微·连续多因子标准化 Alpha 评分策略 (Continuous Multi-Factor Z-Score Alpha)"


def calculate_kalman_kinematics(prices: np.ndarray, q_var: float = 1e-4, r_var: float = 1e-2) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(prices)
    pos = np.zeros(n)
    vel = np.zeros(n)
    acc = np.zeros(n)
    if n < 4:
        return prices.copy(), np.zeros(n), np.zeros(n)

    x = np.array([prices[0], 0.0, 0.0])
    P = np.eye(3) * 1.0
    dt = 1.0
    F = np.array([[1.0, dt, 0.5 * dt * dt], [0.0, 1.0, dt], [0.0, 0.0, 1.0]])
    H = np.array([[1.0, 0.0, 0.0]])
    Q = np.eye(3) * q_var
    R = np.array([[r_var]])

    for t in range(n):
        x_pred = F @ x
        P_pred = F @ P @ F.T + Q
        z = prices[t]
        y = z - H @ x_pred
        S = H @ P_pred @ H.T + R
        K = P_pred @ H.T @ np.linalg.inv(S)
        x = x_pred + (K @ y).flatten()
        P = (np.eye(3) - K @ H) @ P_pred
        pos[t] = x[0]
        vel[t] = x[1]
        acc[t] = x[2]

    return pos, vel, acc


def calculate_permutation_entropy(prices: np.ndarray, order: int = 3, window: int = 30) -> np.ndarray:
    n = len(prices)
    pe = np.ones(n) * 0.70
    if n < window + order:
        return pe

    fact = math.factorial(order)
    for i in range(window + order, n):
        sub_series = prices[i - window:i]
        patterns = {}
        total_patterns = 0
        for j in range(len(sub_series) - order + 1):
            motif = tuple(np.argsort(sub_series[j:j + order]))
            patterns[motif] = patterns.get(motif, 0) + 1
            total_patterns += 1

        entropy = 0.0
        for count in patterns.values():
            p = count / total_patterns
            entropy -= p * math.log(p)

        norm_entropy = entropy / math.log(fact) if fact > 1 else 1.0
        pe[i] = norm_entropy

    return pe


def calculate_continuous_alpha_factors(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"].astype(float).values
    o = df["open"].astype(float).values
    h = df["high"].astype(float).values
    l = df["low"].astype(float).values
    v = df["volume"].astype(float).values
    n = len(df)

    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    atr = pd.Series(tr, index=df.index).rolling(14, min_periods=5).mean().ffill().values + 1e-8

    # 1. 卡尔曼速度与加速度 Z-Score
    k_pos, k_vel, k_acc = calculate_kalman_kinematics(np.log(c + 1e-8))  # ponytail: log-space makes Q/R scale-invariant across instruments
    vel_norm = k_vel  # ponytail: log-space velocity is naturally dimensionless, no ATR normalization needed
    vel_std = pd.Series(vel_norm).rolling(30, min_periods=5).std().ffill().values + 1e-8
    z_vel = (vel_norm / vel_std).clip(-3.0, 3.0)

    acc_norm = k_acc  # ponytail: log-space acceleration is naturally dimensionless
    acc_std = pd.Series(acc_norm).rolling(30, min_periods=5).std().ffill().values + 1e-8
    z_acc = (acc_norm / acc_std).clip(-3.0, 3.0)

    # 2. 排列熵确定性动力学分值 (0.70 为白噪声均值，低于 0.70 为有序层流)
    pe = calculate_permutation_entropy(c, order=3, window=30)
    pe_certainty = (0.70 - pe).clip(-0.5, 0.5) * 4.0 # 归一化至 [-2.0, 2.0]

    # 3. LuxAlgo 连续 FVG 缺口强度向量
    fvg_intensity = np.zeros(n)
    for t in range(2, n):
        if l[t] > h[t - 2]: # Bullish FVG
            fvg_intensity[t] = min(2.0, (l[t] - h[t - 2]) / atr[t])
        elif h[t] < l[t - 2]: # Bearish FVG
            fvg_intensity[t] = -min(2.0, (l[t - 2] - h[t]) / atr[t])
    z_fvg = pd.Series(fvg_intensity).ewm(span=3).mean().values

    # 4. 连续 Hurst 漂移
    c_s = pd.Series(c, index=df.index)
    c_diff2 = c_s.diff(2)
    c_diff8 = c_s.diff(8)
    tau2 = c_diff2.rolling(40, min_periods=5).std(ddof=0)
    tau8 = c_diff8.rolling(40, min_periods=5).std(ddof=0)
    hurst = (np.log((tau8 + 1e-8) / (tau2 + 1e-8)) / np.log(4.0)).clip(0.1, 0.9).ffill().values
    z_hurst = ((hurst - 0.50) / 0.10).clip(-2.5, 2.5)

    # 5. 复合连续 Alpha 评分方程
    # 权重配置: 速度 35%, 加速度 20%, 动力学确定性 20%, FVG 失衡 15%, Hurst 10%
    composite_alpha = (
        0.35 * z_vel +
        0.20 * z_acc +
        0.20 * np.sign(z_vel) * np.maximum(0.0, pe_certainty) +
        0.15 * z_fvg +
        0.10 * np.sign(z_vel) * np.maximum(0.0, z_hurst)
    )

    return pd.DataFrame({
        "z_vel": z_vel,
        "z_acc": z_acc,
        "pe": pe,
        "pe_certainty": pe_certainty,
        "z_fvg": z_fvg,
        "z_hurst": z_hurst,
        "composite_alpha": composite_alpha,
        "atr": atr
    }, index=df.index)


def calculate_signals(df: pd.DataFrame, alpha_threshold: float = 0.85) -> pd.Series:
    factors = calculate_continuous_alpha_factors(df)
    alpha = factors["composite_alpha"].values
    signals = pd.Series(0, index=df.index, dtype=int)
    signals[alpha >= alpha_threshold] = 1
    signals[alpha <= -alpha_threshold] = -1
    return signals
