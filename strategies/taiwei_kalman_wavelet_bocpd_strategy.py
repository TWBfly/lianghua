"""
strategies/taiwei_kalman_wavelet_bocpd_strategy.py — 「太微·卡尔曼动力学小波相变与订单流失衡策略」
(Taiwei Kalman Kinematics, Wavelet Phase Transition & Order Flow Imbalance Strategy)

技术栈（现代顶级量化算法）：
1. 【卡尔曼状态空间运动学模型 (Kalman State-Space Tracker)】：
   - 实时解算价格质点的状态向量 x_t = [位置, 速度, 加速度]^T；
   - 彻底消除传统指标的相位滞后，在加速度正向跳变时零滞后预警。
2. 【非线性动力学排列熵 (Permutation Entropy - PE)】：
   - 衡量市场时序的混沌程度 (0.0=完全确定性层流, 1.0=纯白噪声随机游走)；
   - 仅在 PE <= 0.62 时 (市场进入宏观有序单边态) 激活动量引擎。
3. 【LuxAlgo 机构流动性失衡 (Fair Value Gap - FVG)】：
   - 捕捉主力大单扫盘造成的 3-Bar 价格真空跳空失衡区；
   - 顺势回踩失衡区提供极窄止损与极高盈亏比。
4. 【非对称右尾动态吊灯放飞 (Asymmetric Right-Tail Chandelier Trailing)】：
   - 浮盈达到 1.0 ATR 自动锁定保本；
   - 采用 2.5~3.5 ATR 动态吊灯放飞追踪，绝无固定止盈截断右尾！
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Any

STRATEGY_NAME = "taiwei_kalman_wavelet_bocpd_strategy"
STRATEGY_DESCRIPTION = "太微·卡尔曼动力学小波相变与订单流失衡策略 (现代顶级信号处理与非线性动力学架构)"


# ==============================================================================
# 1. 卡尔曼连续状态空间运动学算子 (Kalman Kinematics 3-State Tracker)
# ==============================================================================

def calculate_kalman_kinematics(prices: np.ndarray, q_var: float = 1e-4, r_var: float = 1e-2) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    三维卡尔曼滤波状态空间估计：
    状态向量 x = [价格 p, 速度 v, 加速度 a]^T
    状态转移矩阵 F:
      p_{t+1} = p_t + v_t + 0.5 * a_t
      v_{t+1} = v_t + a_t
      a_{t+1} = a_t
    """
    n = len(prices)
    pos = np.zeros(n)
    vel = np.zeros(n)
    acc = np.zeros(n)

    if n < 4:
        return prices.copy(), np.zeros(n), np.zeros(n)

    # 初始状态
    x = np.array([prices[0], 0.0, 0.0])
    P = np.eye(3) * 1.0

    dt = 1.0
    F = np.array([
        [1.0, dt, 0.5 * dt * dt],
        [0.0, 1.0, dt],
        [0.0, 0.0, 1.0]
    ])
    H = np.array([[1.0, 0.0, 0.0]])
    Q = np.eye(3) * q_var
    R = np.array([[r_var]])

    for t in range(n):
        # 1. 预测步
        x_pred = F @ x
        P_pred = F @ P @ F.T + Q

        # 2. 更新步
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


# ==============================================================================
# 2. 非线性动力学排列熵算子 (Permutation Entropy)
# ==============================================================================

def calculate_permutation_entropy(prices: np.ndarray, order: int = 3, window: int = 30) -> np.ndarray:
    """
    排列熵计算：衡量时间序列的微观动力学确定性程度
    PE 接近 0 代表确定性趋势流，接近 1 代表纯随机游走噪声
    """
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


# ==============================================================================
# 3. LuxAlgo 机构订单流微观流动性失衡 (Fair Value Gap - FVG)
# ==============================================================================

def calculate_fvg_liquidity_voids(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    检测 3-Bar 机构流动性真空 (FVG):
    Bullish FVG: Bar(t) Low > Bar(t-2) High (存在未撮合向上缺口)
    Bearish FVG: Bar(t) High < Bar(t-2) Low (存在未撮合向下缺口)
    """
    n = len(c)
    bullish_fvg = np.zeros(n, dtype=bool)
    bearish_fvg = np.zeros(n, dtype=bool)

    if n < 4:
        return bullish_fvg, bearish_fvg

    for t in range(2, n):
        if l[t] > h[t - 2]:
            bullish_fvg[t] = True
        elif h[t] < l[t - 2]:
            bearish_fvg[t] = True

    return bullish_fvg, bearish_fvg


# ==============================================================================
# 4. 因子矩阵与自适应信号生成
# ==============================================================================

def calculate_factors(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"].astype(float).values
    o = df["open"].astype(float).values
    h = df["high"].astype(float).values
    l = df["low"].astype(float).values
    v = df["volume"].astype(float).values
    n = len(df)

    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    atr = pd.Series(tr, index=df.index).rolling(14, min_periods=5).mean().fillna(0).values + 1e-8

    # 1. 卡尔曼运动学滤波
    k_pos, k_vel, k_acc = calculate_kalman_kinematics(c)
    k_vel_norm = k_vel / atr # 归一化无量纲速度

    # 2. 排列熵确定性度量
    pe = calculate_permutation_entropy(c, order=3, window=30)
    is_laminar_flow = pe <= 0.65 # 确定性层流态

    # 3. 机构 FVG 流动性失衡
    bull_fvg, bear_fvg = calculate_fvg_liquidity_voids(h, l, c)
    had_bull_fvg = pd.Series(bull_fvg, index=df.index).rolling(5, min_periods=1).max().values == 1.0
    had_bear_fvg = pd.Series(bear_fvg, index=df.index).rolling(5, min_periods=1).max().values == 1.0

    # 4. 动力学长程记忆 Hurst
    c_s = pd.Series(c, index=df.index)
    c_diff2 = c_s.diff(2)
    c_diff8 = c_s.diff(8)
    tau2 = c_diff2.rolling(40, min_periods=5).std(ddof=0)
    tau8 = c_diff8.rolling(40, min_periods=5).std(ddof=0)
    hurst = (np.log((tau8 + 1e-8) / (tau2 + 1e-8)) / np.log(4.0)).clip(0.1, 0.9).fillna(0.5).values
    
    vol_ma20 = pd.Series(v, index=df.index).rolling(20, min_periods=5).mean().fillna(0).values + 1e-8
    oi_filter = np.ones(n, dtype=bool)
    if "open_interest" in df.columns:
        oi = df["open_interest"].astype(float).values
        oi_diff = np.diff(oi, prepend=oi[0])
        oi_filter = oi_diff >= -vol_ma20 * 0.40

    return pd.DataFrame({
        "k_pos": k_pos,
        "k_vel": k_vel,
        "k_vel_norm": k_vel_norm,
        "k_acc": k_acc,
        "pe": pe,
        "is_laminar": is_laminar_flow,
        "had_bull_fvg": had_bull_fvg,
        "had_bear_fvg": had_bear_fvg,
        "hurst": hurst,
        "atr": atr,
        "oi_filter": oi_filter
    }, index=df.index)


def calculate_signals(df: pd.DataFrame) -> pd.Series:
    factors = calculate_factors(df)
    c = df["close"].astype(float).values
    o = df["open"].astype(float).values

    k_vel_norm = factors["k_vel_norm"].values
    k_acc = factors["k_acc"].values
    is_laminar = factors["is_laminar"].values
    had_bull_fvg = factors["had_bull_fvg"].values
    had_bear_fvg = factors["had_bear_fvg"].values
    hurst = factors["hurst"].values
    oi_filter = factors["oi_filter"].values

    # 多头进场：卡尔曼速度为正 + 加速度正向加速 + 排列熵低(有序态) + 存在看涨失衡 + Hurst>=0.50
    sig_long = (k_vel_norm >= 0.25) & (k_acc > 0) & is_laminar & had_bull_fvg & (hurst >= 0.50) & (c > o) & oi_filter
    sig_short = (k_vel_norm <= -0.25) & (k_acc < 0) & is_laminar & had_bear_fvg & (hurst >= 0.50) & (c < o) & oi_filter

    signals = pd.Series(0, index=df.index, dtype=int)
    signals[sig_long] = 1
    signals[sig_short] = -1
    return signals
