"""
strategies/tianji_v2_optimized_master_strategy.py — 「天极·双岛正交高阶自适应策略 V2.0 终极实证版」
(Tianji Dual-Island Master Strategy V2.0 — Verified Holy Grail Production Edition)
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Any

STRATEGY_FULL_NAME = "天极·双岛正交高阶自适应策略 V2.0 (Tianji Dual-Island Strategy V2.0)"

TIER1_TREND_SYMBOLS = ["AU_IDX", "AG_IDX", "LC_IDX", "SN_IDX"]
TIER1_REVERT_SYMBOLS = ["P_IDX", "TA_IDX", "SC_IDX", "MA_IDX"]
TIER1_ALL_SYMBOLS = TIER1_TREND_SYMBOLS + TIER1_REVERT_SYMBOLS


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


def calculate_reversion_factors(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"].astype(float).values
    o = df["open"].astype(float).values
    h = df["high"].astype(float).values
    l = df["low"].astype(float).values
    n = len(df)

    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    prev2_c = np.roll(c, 2)
    prev2_c[0:2] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    atr = pd.Series(tr, index=df.index).rolling(14, min_periods=5).mean().fillna(0).values + 1e-8

    k_pos, k_vel, k_acc = calculate_kalman_kinematics(c)
    vel_norm = k_vel / atr
    vel_std = pd.Series(vel_norm).rolling(30, min_periods=5).std().fillna(0).values + 1e-8
    z_vel = (vel_norm / vel_std).clip(-3.0, 3.0)

    # --- 加速度（曲率）计算 ---
    acc = c - 2 * prev_c + prev2_c
    acc_norm = acc / atr
    acc_std = pd.Series(acc_norm).rolling(30, min_periods=5).std().fillna(0).values + 1e-8
    z_acc = (acc_norm / acc_std).clip(-3.0, 3.0)

    pe = calculate_permutation_entropy(c, order=3, window=30)
    pe_certainty = (0.70 - pe).clip(-0.5, 0.5) * 4.0

    composite_alpha = (
        0.45 * z_vel +
        0.30 * z_acc +
        0.25 * np.sign(z_vel) * np.maximum(0.0, pe_certainty)
    )

    return pd.DataFrame({
        "composite_alpha": composite_alpha,
        "atr": atr,
        "k_pos": k_pos,
        "pe": pe
    }, index=df.index)
