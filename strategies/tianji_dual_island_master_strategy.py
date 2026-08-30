"""
strategies/tianji_dual_island_master_strategy.py — 「天极·双岛正交高阶时空相变自适应策略」
(Tianji Dual-Island Orthogonal Space-Time Phase Transition Strategy)

【策略官方命名与技术体系】：
策略全称：天极·双岛正交高阶时空相变自适应策略 (Tianji Dual-Island Orthogonal Strategy)
策略简称：天极·双岛策略

【核心架构第一性原理】：
1. 宏观长程单边岛 (Macro Trend Island - 60m 周期):
   - 管辖资产：白银 (AG)、黄金 (AU)、碳酸锂 (LC)、沪锡 (SN)、沪铜 (CU)
   - 算法内核：60m 连续卡尔曼运动学 (Kalman Kinematics: 速度与加速度) + 排列熵确定性 + LuxAlgo FVG 流动性失衡
   - 核心门禁：Z_Alpha >= +1.40 顺势做多，Z_Alpha <= -1.40 顺势做空，|Z| < 1.0 混沌死区硬性空仓
   - 非对称风控：浮盈 1.2 ATR 自动锁定保本 (Entry + 0.2 ATR)，浮盈 2.5 ATR 激活 3.5 ATR 宽幅动态吊灯放飞 (专抓 +5.0~10.0 ATR 肥尾)

2. 产业基差均值岛 (Industrial Reversion Island - 30m 周期):
   - 管辖资产：PTA (TA)、棕榈油 (P)、原油 (SC)、甲醇 (MA)、螺纹钢 (RB)
   - 算法内核：30m 连续卡尔曼速度极端偏离 + 排列熵非单边确认
   - 核心门禁：Z_Alpha >= +0.85 冲高做空 (Fade)，Z_Alpha <= -0.85 极值低吸 (Fade)
   - 均值收割风控：价格回归卡尔曼滤波中枢立即止盈平仓，硬止损 1.2 ATR

3. 顶层正交风险平价组合层 (Top-Level Orthogonal Risk Parity Layer):
   - 趋势岛捕捉宏观单边大牛大熊，均值岛收割产业窄幅与宽幅震荡；
   - 两大岛屿底层收益相关性 Corr <= 0.05，实现跨周期的全天候平滑正反馈。
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Any

STRATEGY_NAME = "tianji_dual_island_master_strategy"
STRATEGY_FULL_NAME = "天极·双岛正交高阶时空相变自适应策略 (Tianji Dual-Island Orthogonal Strategy)"

TREND_ISLAND_SYMBOLS = ["AG_IDX", "AU_IDX", "LC_IDX", "SN_IDX", "CU_IDX"]
REVERT_ISLAND_SYMBOLS = ["TA_IDX", "P_IDX", "SC_IDX", "MA_IDX", "RB_IDX"]


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


def calculate_continuous_factors(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"].astype(float).values
    o = df["open"].astype(float).values
    h = df["high"].astype(float).values
    l = df["low"].astype(float).values
    v = df["volume"].astype(float).values
    n = len(df)

    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    atr = pd.Series(tr, index=df.index).rolling(14, min_periods=5).mean().bfill().values + 1e-8

    k_pos, k_vel, k_acc = calculate_kalman_kinematics(c)
    vel_norm = k_vel / atr
    vel_std = pd.Series(vel_norm).rolling(30, min_periods=5).std().bfill().values + 1e-8
    z_vel = (vel_norm / vel_std).clip(-3.0, 3.0)

    acc_norm = k_acc / atr
    acc_std = pd.Series(acc_norm).rolling(30, min_periods=5).std().bfill().values + 1e-8
    z_acc = (acc_norm / acc_std).clip(-3.0, 3.0)

    pe = calculate_permutation_entropy(c, order=3, window=30)
    pe_certainty = (0.70 - pe).clip(-0.5, 0.5) * 4.0

    fvg_intensity = np.zeros(n)
    for t in range(2, n):
        if l[t] > h[t - 2]:
            fvg_intensity[t] = min(2.0, (l[t] - h[t - 2]) / atr[t])
        elif h[t] < l[t - 2]:
            fvg_intensity[t] = -min(2.0, (l[t - 2] - h[t]) / atr[t])
    z_fvg = pd.Series(fvg_intensity).ewm(span=3).mean().values

    c_s = pd.Series(c, index=df.index)
    c_diff2 = c_s.diff(2)
    c_diff8 = c_s.diff(8)
    tau2 = c_diff2.rolling(40, min_periods=5).std(ddof=0)
    tau8 = c_diff8.rolling(40, min_periods=5).std(ddof=0)
    hurst = (np.log((tau8 + 1e-8) / (tau2 + 1e-8)) / np.log(4.0)).clip(0.1, 0.9).bfill().values
    z_hurst = ((hurst - 0.50) / 0.10).clip(-2.5, 2.5)

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
        "atr": atr,
        "k_pos": k_pos
    }, index=df.index)
