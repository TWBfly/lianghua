"""
code/regime_trend_evolution_engine.py — 三阶因果自适应量化系统核心状态与前驱预测引擎

基于《研究策略.md》与量化第一性原理构建：
第一步：对当前趋势的判断 (State Detection)
  - Ehlers 2-Pole SuperSmoother 零相位滞后趋势滤波
  - Normalized Slope (线性回归斜率 / ATR, 20/50 周期)
  - Kaufman Directional Efficiency Ratio (DER = ER * sign(ΔP))
  - Range Position Centered ((Close - LL) / (HH - LL) 映射至 [-1, 1])
  - Swing Structure (Higher High & Higher Low vs Lower High & Lower Low)
  - Crossing Frequency (价格穿透均线频度，识别洗盘震荡)
  - 迟滞机制 (Hysteresis) 输出稳定状态：UPTREND, DOWNTREND, RANGE, TRANSITION

第二步：对未来趋势的判断 (State Forecasting & Continuation)
  - 趋势前驱因子族 (Volatility Compression, Momentum Acceleration, RVOL, CLV)
  - 趋势延续与衰竭诊断 (Trend Deceleration, Pullback Quality, Breakout Follow-Through, Extension)
  - 输出条件概率：P(Continue), P(Transition), P(Reversal)
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
from typing import Dict, Tuple, Any


def calculate_ehlers_supersmoother_2pole(prices: np.ndarray, period: int = 12) -> np.ndarray:
    """Ehlers 2-Pole SuperSmoother Filter (2极点超平滑零滞后滤波器)."""
    n = len(prices)
    if n < 4:
        return prices.copy()
    a1 = math.exp(-math.sqrt(2.0) * math.pi / period)
    b1 = 2.0 * a1 * math.cos(math.sqrt(2.0) * math.pi / period)
    c2 = b1
    c3 = -a1 * a1
    c1 = 1.0 - c2 - c3
    filt = np.zeros(n, dtype=float)
    filt[0] = prices[0]
    filt[1] = prices[1]
    for t in range(2, n):
        filt[t] = c1 * (prices[t] + prices[t - 1]) * 0.5 + c2 * filt[t - 1] + c3 * filt[t - 2]
    return filt


def calculate_kalman_velocity_state(
    prices: np.ndarray, q_factor: float = 0.01, r_factor: float = 0.5
) -> Tuple[np.ndarray, np.ndarray]:
    """
    一阶标量卡尔曼运动学状态估计器 (Kinematic State-Space Velocity Estimator).
    无动态矩阵分配开销，时间复杂度 O(N)，纯因果计算。
    返回: (平滑价格估计, 瞬时速度估计)
    """
    n = len(prices)
    if n < 2:
        return prices.copy(), np.zeros(n, dtype=float)

    est_price = np.zeros(n, dtype=float)
    est_vel = np.zeros(n, dtype=float)

    p = prices[0]
    v = 0.0
    p00 = 1.0
    p01 = 0.0
    p11 = 1.0

    q00 = q_factor / 4.0
    q01 = q_factor / 2.0
    q11 = q_factor
    r = r_factor

    for t in range(n):
        p_pred = p + v
        v_pred = v
        pp00 = p00 + 2.0 * p01 + p11 + q00
        pp01 = p01 + p11 + q01
        pp11 = p11 + q11

        z = prices[t]
        s = pp00 + r
        k0 = pp00 / s
        k1 = pp01 / s

        err = z - p_pred
        p = p_pred + k0 * err
        v = v_pred + k1 * err

        p00 = (1.0 - k0) * pp00
        p01 = (1.0 - k0) * pp01
        p11 = pp11 - k1 * pp01

        est_price[t] = p
        est_vel[t] = v

    return est_price, est_vel


def calculate_causal_hurst(prices: np.ndarray, window: int = 60) -> np.ndarray:
    """
    向量化纯因果方差比率 Hurst 指数估计器 (Variance-Ratio Causal Hurst).
    H > 0.50: 长程正自相关 (持久趋势动量)
    H < 0.50: 均值反转 (均值回归特征)
    H ≈ 0.50: 几何布朗运动 (白噪声随机游走)
    """
    n = len(prices)
    if n < window + 4:
        return np.full(n, 0.50, dtype=float)

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


def calculate_fast_permutation_entropy(prices: np.ndarray, window: int = 30) -> np.ndarray:
    """
    向量化 3 阶符号排列熵 (Permutation Entropy).
    PE <= 0.55: 强单边低熵趋势；PE >= 0.85: 极端混乱高熵震荡区。
    采用前缀和滑动窗口加速，时间复杂度 O(N)。
    """
    n = len(prices)
    if n < window:
        return np.full(n, 1.0, dtype=float)

    p0 = prices[:-2]
    p1 = prices[1:-1]
    p2 = prices[2:]

    c01 = (p0 > p1).astype(int)
    c12 = (p1 > p2).astype(int)
    c02 = (p0 > p2).astype(int)
    code = (c01 << 2) | (c12 << 1) | c02

    mapping = np.zeros(8, dtype=int)
    mapping[0] = 0
    mapping[2] = 1
    mapping[4] = 2
    mapping[3] = 3
    mapping[5] = 4
    mapping[7] = 5
    pattern_ids = mapping[code]

    m = window - 2
    one_hot = np.zeros((len(pattern_ids), 6), dtype=float)
    one_hot[np.arange(len(pattern_ids)), pattern_ids] = 1.0

    cs = np.vstack([np.zeros((1, 6)), np.cumsum(one_hot, axis=0)])
    counts = cs[m:] - cs[:-m]

    probs = counts / float(m)
    log_p = np.zeros_like(probs)
    mask = probs > 1e-10
    log_p[mask] = np.log(probs[mask])
    entropy = -np.sum(probs * log_p, axis=1)

    max_entropy = math.log(6.0)
    norm_entropy = entropy / max_entropy

    res = np.full(n, 1.0, dtype=float)
    valid_len = len(norm_entropy) - 1
    if valid_len > 0:
        p_s = pd.Series(prices)
        span = (p_s.rolling(window).max() - p_s.rolling(window).min()).values
        target_slice = slice(window, window + valid_len)
        # ponytail: 平盘零波动无任何序数信息，按最大不确定性(PE=1.0)处理，防止伪造满分趋势
        res[target_slice] = np.where(span[target_slice] <= 1e-6, 1.0, norm_entropy[:-1])
    return res


def compute_normalized_slope(prices: np.ndarray, atr: np.ndarray, window: int = 20) -> np.ndarray:
    """
    计算线性回归斜率并经 ATR 标准化 (Normalized Linear Regression Slope).
    输出单位: 每一根 Bar 平均移动多少个 ATR.
    """
    n = len(prices)
    slopes = np.zeros(n, dtype=float)
    if n < window:
        return slopes

    x = np.arange(window, dtype=float)
    x_mean = (window - 1) / 2.0
    x_dev = x - x_mean
    denom = np.sum(x_dev ** 2)

    for t in range(window - 1, n):
        y = prices[t - window + 1 : t + 1]
        y_mean = np.mean(y)
        cov = np.sum(x_dev * (y - y_mean))
        raw_slope = cov / denom
        curr_atr = atr[t] if atr[t] > 1e-8 else 1.0
        slopes[t] = raw_slope / curr_atr
    return slopes


def compute_kaufman_efficiency_ratio(prices: np.ndarray, window: int = 20) -> Tuple[np.ndarray, np.ndarray]:
    """
    计算考夫曼效率比率 (ER) 与 带方向效率比率 (DER = ER * sign(ΔP)).
    ER: 0 ~ 1 (1 为极干净单边趋势，接近 0 为高频白噪声/随机游走)
    DER: -1 ~ +1 (+1 极强上涨，-1 极强下跌，0 横盘)
    """
    n = len(prices)
    er = np.zeros(n, dtype=float)
    der = np.zeros(n, dtype=float)
    if n < window:
        return er, der

    abs_diffs = np.abs(np.diff(prices, prepend=prices[0]))
    for t in range(window, n):
        net_change = prices[t] - prices[t - window]
        path_length = np.sum(abs_diffs[t - window + 1 : t + 1])
        if path_length > 1e-8:
            ratio = min(1.0, abs(net_change) / path_length)
            er[t] = ratio
            der[t] = ratio * (1.0 if net_change > 0 else (-1.0 if net_change < 0 else 0.0))
        else:
            er[t] = 0.0
            der[t] = 0.0
    return er, der


def compute_range_position(closes: np.ndarray, highs: np.ndarray, lows: np.ndarray, window: int = 20) -> Tuple[np.ndarray, np.ndarray]:
    """
    计算价格在 N 周期区间中的相对位置.
    RangePosition in [0, 1]
    RangePositionCentered in [-1, 1] (靠近上沿为 +1, 靠近下沿为 -1)
    """
    n = len(closes)
    pos = np.full(n, 0.5, dtype=float)
    pos_centered = np.zeros(n, dtype=float)
    if n < window:
        return pos, pos_centered

    for t in range(window - 1, n):
        hh = np.max(highs[t - window + 1 : t + 1])
        ll = np.min(lows[t - window + 1 : t + 1])
        span = hh - ll
        if span > 1e-8:
            val = np.clip((closes[t] - ll) / span, 0.0, 1.0)
            pos[t] = val
            pos_centered[t] = 2.0 * val - 1.0
        else:
            pos[t] = 0.5
            pos_centered[t] = 0.0
    return pos, pos_centered


def compute_crossing_frequency(prices: np.ndarray, baseline: np.ndarray, window: int = 20) -> np.ndarray:
    """
    计算价格在过去 N 根 Bar 穿越基准均线的频率 (CrossFreq).
    趋势市: CrossFreq 极低 (<= 0.10)
    震荡市: CrossFreq 极高 (>= 0.25 ~ 0.40)
    """
    n = len(prices)
    cross_freq = np.zeros(n, dtype=float)
    if n < window + 1:
        return cross_freq

    diffs = prices - baseline
    signs = np.sign(diffs)
    # 处理 0
    for i in range(1, n):
        if signs[i] == 0:
            signs[i] = signs[i - 1] if signs[i - 1] != 0 else 1.0

    crosses = (signs[1:] * signs[:-1] < 0).astype(float)
    crosses = np.pad(crosses, (1, 0), constant_values=0.0)

    for t in range(window, n):
        cross_freq[t] = np.mean(crosses[t - window + 1 : t + 1])
    return cross_freq


def compute_swing_structure(highs: np.ndarray, lows: np.ndarray, sub_window: int = 10) -> np.ndarray:
    """
    计算局部高低点结构 (HH+HL vs LH+LL).
    比较最近两个 sub_window 的波段高点与低点.
    +1.0: Higher High & Higher Low (健康上涨结构)
    -1.0: Lower High & Lower Low (健康下跌结构)
     0.0: 结构冲突 / 震荡无序
    """
    n = len(highs)
    swing_score = np.zeros(n, dtype=float)
    w2 = sub_window * 2
    if n < w2:
        return swing_score

    for t in range(w2 - 1, n):
        h1 = np.max(highs[t - w2 + 1 : t - sub_window + 1])
        l1 = np.min(lows[t - w2 + 1 : t - sub_window + 1])
        h2 = np.max(highs[t - sub_window + 1 : t + 1])
        l2 = np.min(lows[t - sub_window + 1 : t + 1])

        hh = h2 > h1
        hl = l2 > l1
        lh = h2 < h1
        ll = l2 < l1

        if hh and hl:
            swing_score[t] = 1.0
        elif lh and ll:
            swing_score[t] = -1.0
        elif hh and ll:
            swing_score[t] = 0.0  # 扩张喇叭形
        elif lh and hl:
            swing_score[t] = 0.0  # 收敛三角形
        else:
            swing_score[t] = 0.5 if (hh or hl) else (-0.5 if (lh or ll) else 0.0)
    return swing_score


class CurrentTrendDetector:
    """
    第一步：当前趋势判断引擎 (State Detection Engine)
    输入：纯因果历史 OHLCV
    输出：
      - TS (Trend Strength Score, 0 ~ 100)
      - DS (Direction Score, -1.0 ~ +1.0)
      - State (UPTREND=1, DOWNTREND=-1, RANGE=0, TRANSITION=2)
    """

    def __init__(self, fast_period: int = 8, slow_period: int = 24, er_window: int = 20):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.er_window = er_window

    def analyze(self, df: pd.DataFrame) -> pd.DataFrame:
        df_res = df.copy()
        c = df_res["close"].astype(float).values
        h = df_res["high"].astype(float).values
        l = df_res["low"].astype(float).values
        o = df_res["open"].astype(float).values
        n = len(c)

        # 1. 因果 ATR (14 周期)
        prev_c = np.roll(c, 1)
        prev_c[0] = c[0]
        tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
        # 严格单向因果填充，前序使用前向填充配合常数保底，杜绝未来函数
        atr = pd.Series(tr, index=df_res.index).rolling(14, min_periods=5).mean().ffill().fillna(1.0).values
        atr = np.maximum(atr, 1e-4)
        df_res["atr"] = atr

        # 2. Ehlers 2-Pole SuperSmoother 趋势滤波
        filt_fast = calculate_ehlers_supersmoother_2pole(c, period=self.fast_period)
        filt_slow = calculate_ehlers_supersmoother_2pole(c, period=self.slow_period)
        df_res["ss_fast"] = filt_fast
        df_res["ss_slow"] = filt_slow

        # 3. Normalized Slope (20 周期与 50 周期)
        slope_20 = compute_normalized_slope(c, atr, window=20)
        slope_50 = compute_normalized_slope(c, atr, window=50)
        df_res["norm_slope_20"] = slope_20
        df_res["norm_slope_50"] = slope_50

        # 4. Kaufman Efficiency Ratio & Directional ER
        er_20, der_20 = compute_kaufman_efficiency_ratio(c, window=self.er_window)
        er_50, der_50 = compute_kaufman_efficiency_ratio(c, window=50)
        df_res["er_20"] = er_20
        df_res["der_20"] = der_20
        df_res["er_50"] = er_50
        df_res["der_50"] = der_50

        # 5. Range Position Centered
        pos_20, pos_cen_20 = compute_range_position(c, h, l, window=20)
        pos_50, pos_cen_50 = compute_range_position(c, h, l, window=50)
        df_res["pos_cen_20"] = pos_cen_20
        df_res["pos_cen_50"] = pos_cen_50

        # 6. Crossing Frequency
        cross_freq_20 = compute_crossing_frequency(c, filt_slow, window=20)
        df_res["cross_freq_20"] = cross_freq_20

        # 7. Swing Structure
        swing_score = compute_swing_structure(h, l, sub_window=10)
        df_res["swing_score"] = swing_score

        # 8. 卡尔曼状态空间运动学估计 (Kinematic Kalman Velocity & Accel)
        kalman_price, kalman_vel = calculate_kalman_velocity_state(c, q_factor=0.01, r_factor=0.5)
        kalman_norm_vel = np.clip((kalman_vel / atr) / 0.18, -1.0, 1.0)
        kalman_accel = np.diff(kalman_vel / atr, prepend=(kalman_vel[0] / atr[0]))
        df_res["kalman_price"] = kalman_price
        df_res["kalman_vel"] = kalman_vel
        df_res["kalman_norm_vel"] = kalman_norm_vel
        df_res["kalman_accel"] = kalman_accel

        # 9. 统计物理特征: 因果方差比率 Hurst 指数与符号排列熵 (Permutation Entropy)
        causal_hurst = calculate_causal_hurst(c, window=60)
        perm_entropy = calculate_fast_permutation_entropy(c, window=30)
        df_res["causal_hurst"] = causal_hurst
        df_res["perm_entropy"] = perm_entropy

        hurst_trend_score = np.clip((causal_hurst - 0.48) / 0.14, 0.0, 1.0)
        pe_order_score = np.clip((0.92 - perm_entropy) / 0.25, 0.0, 1.0)
        physics_trend = 0.5 * hurst_trend_score + 0.5 * pe_order_score
        df_res["physics_trend"] = physics_trend

        # 10. 综合计算 Trend Strength Score (TS: 0~100)
        # TS 回答：当前有没有趋势？
        # 融合: 统计物理有序度(35%) + 卡尔曼运动学速度强度(35%) + 考夫曼路径效率比(15%) + 均线穿透惩罚(15%)
        chop_penalty = np.clip(1.0 - 2.5 * cross_freq_20, 0.0, 1.0)
        ts_raw = 0.35 * physics_trend + 0.35 * np.abs(kalman_norm_vel) + 0.15 * er_20 + 0.15 * chop_penalty
        ts = np.clip(ts_raw * 100.0, 0.0, 100.0)
        df_res["trend_strength"] = ts

        # 11. 综合计算 Direction Score (DS: -1.0 ~ +1.0)
        # DS 回答：当前倾向往哪里走？
        # 核心驱动升级为零滞后卡尔曼速度 (40%)，配合 DER(25%)、快线斜率(20%)与通道位置(15%)
        fast_slope = np.zeros(n, dtype=float)
        if n >= 3:
            fast_slope[2:] = (filt_fast[2:] - filt_fast[:-2]) / (2.0 * atr[2:])
        norm_fast_slope = np.clip(fast_slope / 0.15, -1.0, 1.0)
        ds = 0.40 * kalman_norm_vel + 0.25 * der_20 + 0.20 * norm_fast_slope + 0.15 * pos_cen_20
        ds = np.clip(ds, -1.0, 1.0)
        df_res["direction_score"] = ds

        # 12. 带迟滞机制 (Hysteresis) 与物理分形门禁的离散状态机判别
        # 状态定义:
        # 1: UPTREND (强上涨)
        # -1: DOWNTREND (强下跌)
        # 0: RANGE (横盘震荡)
        # 2: TRANSITION (过渡/中性不确定态)
        regimes = np.zeros(n, dtype=int)
        current_state = 0  # 初始 RANGE
        bars_in_state = 0

        for i in range(self.slow_period, n):
            t_val = ts[i]
            d_val = ds[i]
            cf_val = cross_freq_20[i]
            h_val = causal_hurst[i]
            c_val = c[i]
            atr_val = atr[i]
            fast_val = filt_fast[i]
            k_vel = kalman_norm_vel[i]

            pe_val = perm_entropy[i]
            # 第一性原理分形布朗运动与高熵混沌门禁:
            # 当 Hurst <= 0.50 且 PE >= 0.88 时，动力学属于反持续均值回归与高熵混沌双重噪声态;
            # 或当 20 周期均线穿越率 >= 25% 且效率比 ER < 0.20 时，属于典型织布横盘缠绕
            is_anti_persistent = (h_val <= 0.50 and pe_val >= 0.88) or (cf_val >= 0.25 and er_20[i] < 0.20) or (physics_trend[i] < 0.08 and abs(der_20[i]) < 0.15)
            can_enter_up = not is_anti_persistent and d_val >= 0.30 and c_val > fast_val and t_val >= 28.0
            can_enter_down = not is_anti_persistent and d_val <= -0.30 and c_val < fast_val and t_val >= 28.0

            catastrophic_down = c_val < fast_val - 1.8 * atr_val and d_val <= -0.45
            catastrophic_up = c_val > fast_val + 1.8 * atr_val and d_val >= 0.45

            if current_state == 1:  # 原处于 UPTREND
                if catastrophic_down:
                    current_state = -1
                    bars_in_state = 0
                elif c_val < fast_val and (d_val <= 0.08 or cf_val >= 0.25):
                    # 多头动能衰竭且跌破均线中枢，平滑回落至横盘震荡(0)，拒绝在横盘窄幅箱体内来回跳变多空
                    current_state = 0
                    bars_in_state = 0
                else:
                    bars_in_state += 1
            elif current_state == -1:  # 原处于 DOWNTREND
                if catastrophic_up:
                    current_state = 1
                    bars_in_state = 0
                elif c_val > fast_val and (d_val >= -0.08 or cf_val >= 0.25):
                    # 空头动能衰竭且上破均线中枢，平滑回落至横盘震荡(0)
                    current_state = 0
                    bars_in_state = 0
                else:
                    bars_in_state += 1
            else:  # 原处于 RANGE 或 TRANSITION
                if can_enter_up:
                    current_state = 1  # 确认为 UPTREND
                    bars_in_state = 0
                elif can_enter_down:
                    current_state = -1  # 确认为 DOWNTREND
                    bars_in_state = 0
                else:
                    current_state = 0  # 明确为 RANGE
                    bars_in_state += 1

            regimes[i] = current_state

        df_res["market_state"] = regimes
        return df_res


class FutureTrendForecaster:
    """
    第二步：未来趋势判断与前驱延续引擎 (State Forecasting & Continuation Engine)
    量化趋势前驱特征与衰竭风险，预测趋势延续概率 P(Continue | State)
    """

    def __init__(self, lookback: int = 20):
        self.lookback = lookback

    def analyze(self, df: pd.DataFrame) -> pd.DataFrame:
        df_res = df.copy()
        c = df_res["close"].astype(float).values
        h = df_res["high"].astype(float).values
        l = df_res["low"].astype(float).values
        o = df_res["open"].astype(float).values
        v = df_res["volume"].astype(float).values
        atr = df_res["atr"].values
        ts = df_res["trend_strength"].values
        ds = df_res["direction_score"].values
        state = df_res["market_state"].values
        er_20 = df_res["er_20"].values
        slope_20 = df_res["norm_slope_20"].values
        causal_hurst = df_res["causal_hurst"].values
        n = len(c)

        # 1. 波动率压缩比 (Volatility Compression Ratio: ATR(10) / ATR(60))
        atr_10 = pd.Series(atr).rolling(10, min_periods=3).mean().values
        atr_60 = pd.Series(atr).rolling(60, min_periods=10).mean().ffill().fillna(1.0).values
        compression_ratio = np.clip(atr_10 / np.maximum(atr_60, 1e-4), 0.2, 3.0)
        df_res["compression_ratio"] = compression_ratio

        # 2. 动量加速度 (Momentum Acceleration)
        # 优先使用平滑运动学卡尔曼加速度 (Kalman Acceleration) 替换离散价格粗糙差分
        if "kalman_accel" in df_res.columns:
            mom_acc = df_res["kalman_accel"].values
        else:
            ret_10 = pd.Series(c).pct_change(10).fillna(0.0).values
            ret_20 = pd.Series(c).pct_change(20).fillna(0.0).values
            mom_acc = ret_10 - 0.5 * ret_20
        df_res["mom_acc"] = mom_acc

        # 3. 斜率变化率 (Slope Acceleration)
        slope_acc = np.diff(slope_20, prepend=slope_20[0])
        df_res["slope_acc"] = slope_acc

        # 4. 相对成交量 (RVOL) 与 量价确认 (Volume Confirmation)
        vol_ma20 = pd.Series(v).rolling(20, min_periods=5).mean().ffill().fillna(1.0).values
        rvol = np.clip(v / np.maximum(vol_ma20, 1e-4), 0.1, 10.0)
        df_res["rvol"] = rvol

        # 量价顺逆确认: 顺趋势方向移动时放量为 +1, 逆势回调放量为 -1
        bar_direction = np.sign(c - o)
        trend_dir_sign = np.sign(ds)
        vol_harmony = np.where(rvol > 1.2, bar_direction * trend_dir_sign, 0.0)
        df_res["vol_harmony"] = vol_harmony

        # 5. K线能量收盘位置 (Candle Location Value, CLV)
        hl_span = h - l
        clv = np.where(hl_span > 1e-6, ((c - l) - (h - c)) / np.maximum(hl_span, 1e-6), 0.0)
        df_res["clv"] = clv

        # 6. 回撤质量与深度 (Pullback Quality / Depth)
        # 健康上涨趋势回撤浅 (<= 0.8 ATR)，脆弱趋势回撤深 (>= 1.5 ATR)
        pullback_depth = np.zeros(n, dtype=float)
        for i in range(10, n):
            curr_atr = max(atr[i], 1e-4)
            if state[i] == 1:
                hh_recent = np.max(h[i - 9 : i + 1])
                pullback_depth[i] = (hh_recent - c[i]) / curr_atr
            elif state[i] == -1:
                ll_recent = np.min(l[i - 9 : i + 1])
                pullback_depth[i] = (c[i] - ll_recent) / curr_atr
            else:
                pullback_depth[i] = 0.5
        df_res["pullback_depth"] = pullback_depth

        # 7. 趋势过度延伸风险 (Extension from Equilibrium: (Close - SS_Slow) / ATR)
        ss_slow = df_res["ss_slow"].values
        extension = (c - ss_slow) / np.maximum(atr, 1e-4)
        df_res["extension"] = extension

        # 8. 趋势隐性减速诊断 (Trend Deceleration)
        # 价格接近新高但 ER 衰退，说明趋势内部动能减速
        deceleration = np.zeros(n, dtype=float)
        for i in range(15, n):
            if state[i] == 1:
                is_near_high = c[i] >= np.max(h[i - 14 : i]) * 0.995
                er_dropping = er_20[i] < er_20[i - 5] - 0.10
                if is_near_high and er_dropping:
                    deceleration[i] = 1.0
            elif state[i] == -1:
                is_near_low = c[i] <= np.min(l[i - 14 : i]) * 1.005
                er_dropping = er_20[i] < er_20[i - 5] - 0.10
                if is_near_low and er_dropping:
                    deceleration[i] = 1.0
        df_res["deceleration"] = deceleration

        # 9. 趋势持续期年龄 (Trend Age in Bars)
        trend_age = np.zeros(n, dtype=int)
        curr_age = 0
        for i in range(1, n):
            if state[i] != 0 and state[i] == state[i - 1]:
                curr_age += 1
            else:
                curr_age = 1 if state[i] != 0 else 0
            trend_age[i] = curr_age
        df_res["trend_age"] = trend_age

        # 10. 计算未来趋势延续概率 P(Continue) 与 转移概率 P(Transition)
        # 使用基于先验物理特性的因果 Logistic 激活函数
        p_continue = np.full(n, 0.5, dtype=float)
        p_transition = np.full(n, 0.3, dtype=float)
        p_reversal = np.full(n, 0.2, dtype=float)

        for i in range(20, n):
            s = state[i]
            if s == 0:
                # 震荡态 (RANGE)：延续震荡概率取决于效率比是否持续低、压缩是否未突破
                comp = compression_ratio[i]
                p_cont = 0.70 if er_20[i] < 0.25 and comp > 0.85 else 0.40
                p_continue[i] = p_cont
                p_transition[i] = 1.0 - p_cont
                p_reversal[i] = 0.0
            elif s == 2:
                # 过渡态 (TRANSITION): 处于方向未明的不确定性中，延续概率低，转移概率高
                p_continue[i] = 0.35
                p_transition[i] = 0.55
                p_reversal[i] = 0.10
            else:
                # 趋势态 (s == 1 或 -1): 评估趋势是否具有强延续性
                # 基础 Logit 分值
                base_logit = 0.5  # 对应约 62% 先验

                # 趋势强度加分
                q_score = (ts[i] - 50.0) / 25.0  # [-0.4, +2.0]
                # 动量加速度贡献 (结合斜率变化与 MOMACC)
                acc_score = np.clip(slope_acc[i] * 5.0 + mom_acc[i] * 25.0, -1.0, 1.0) * (1.0 if s == 1 else -1.0)
                # 成交量确认贡献
                vol_score = np.clip(vol_harmony[i] * 0.5, -0.5, 0.5)
                # 回撤质量惩罚: 回撤越深，延续概率大幅下降
                pb = pullback_depth[i]
                pb_penalty = 0.0
                if pb > 1.2:
                    pb_penalty = (pb - 1.2) * 1.5  # 回撤 > 1.2 ATR 惩罚

                # 减速惩罚
                decel_penalty = 1.2 if deceleration[i] > 0.5 else 0.0

                # 延伸惩罚: 离均线超过 3.5 ATR 衰退
                ext = abs(extension[i])
                ext_penalty = max(0.0, (ext - 2.8) * 0.8)

                # 趋势年龄衰退: 趋势 80 根以上进入过度成熟期
                age = trend_age[i]
                age_factor = 0.3 if age < 15 else (0.0 if age < 60 else -0.5)

                total_logit = base_logit + 0.6 * q_score + 0.4 * acc_score + 0.3 * vol_score + age_factor - pb_penalty - decel_penalty - ext_penalty
                # ponytail: Hurst 持续性加分——H>0.5 趋势记忆增强延续概率，H<0.5 反之
                hurst_bonus = np.clip((causal_hurst[i] - 0.50) * 2.0, -0.5, 0.5)
                total_logit += 0.3 * hurst_bonus
                prob_c = 1.0 / (1.0 + math.exp(-np.clip(total_logit, -4.0, 4.0)))
                prob_c = np.clip(prob_c, 0.10, 0.92)

                # 剩余概率分配给 Transition 与 Reversal
                rem = 1.0 - prob_c
                if decel_penalty > 0 or pb_penalty > 0:
                    prob_rev = rem * 0.45
                    prob_trans = rem * 0.55
                else:
                    prob_rev = rem * 0.25
                    prob_trans = rem * 0.75

                p_continue[i] = prob_c
                p_transition[i] = prob_trans
                p_reversal[i] = prob_rev

        df_res["p_continue"] = p_continue
        df_res["p_transition"] = p_transition
        df_res["p_reversal"] = p_reversal
        return df_res
