"""
strategies/taiwei_wavelet_fractal_squeeze.py — 「太微·小波分形相变」: 极大重叠离散小波变换 (MODWT) + 动力学分形赫斯特 + 能量挤压相变动量策略 (30m 黄金级别)

第一性原理与现代量化物理机制：
1. 极大重叠离散小波多分辨率分解 (MODWT 3-Level Multiresolution Analysis):
   - 采用纯因果 MODWT (Maximal Overlap Discrete Wavelet Transform) 进行 3 级正交时频分解：
     * 细节分量 D1 (2-4 Bar 高频微观噪声)
     * 细节分量 D2 (4-8 Bar 短期周期波)
     * 细节分量 D3 (8-16 Bar 中期动力波)
     * 近似分量 A3 (16+ Bar 宏观趋势基线)
   - MODWT 具备严格平移不变性与 Parseval 能量守恒性。

2. 小波能量凝聚与相变耗散度量 (Wavelet Energy Squeeze & Phase Transition):
   - 计算高频细节分量能量占比与全局能量比率：
     E_detail = RMS(D1)^2 + RMS(D2)^2 + RMS(D3)^2
     E_total = E_detail + RMS(A3 - mean(A3))^2
     Wavelet_Squeeze = E_detail / (E_total + 1e-8)
   - 当 Wavelet_Squeeze <= 0.35 时，系统处于极度凝聚的“卷簧”蓄能态；
   - 当系统从小波能量收敛区发生突变扩张（相变跃迁）时，释放强烈动能。

3. 动力学标度律分形赫斯特指数 (Vectorized Hurst Exponent):
   - 方差比率标度律自适应赫斯特指数：H >= 0.50 确认系统处于具备长程自相关记忆的真实单边动力学状态；
   - 排除随机游走与宽幅洗盘假突破。

4. Ehlers 2-Pole SuperSmoother 零滞后宏观趋势对齐:
   - 6 周期 vs 18 周期 SuperSmoother 消除低通时滞，顺应 30m 宏观大势。

5. 物理跃迁出场引擎:
   - 目标位 (Take Profit): 1.0 * ATR (小波高频能量耗散至平衡态位)；
   - 止损位 (Stop Loss): 0.8 * ATR (相变失败即刻止损)；
   - 动态保本 (Break-Even): 浮盈达到 1.0 * ATR 时，抬升止损至 Entry + 0.1 * ATR。
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd

STRATEGY_NAME = "taiwei_wavelet_fractal_squeeze"
STRATEGY_DESCRIPTION = "「太微·小波分形相变」: 极大重叠离散小波变换 (MODWT) + 动力学分形赫斯特 + 能量挤压相变动量策略 (30m)"


def compute_causal_modwt_3level(prices: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = len(prices)
    if n < 8:
        return np.zeros(n), np.zeros(n), np.zeros(n), prices.copy()

    a1 = np.zeros(n)
    d1 = np.zeros(n)
    a1[0] = prices[0]
    for t in range(1, n):
        a1[t] = 0.5 * (prices[t] + prices[t - 1])
        d1[t] = 0.5 * (prices[t] - prices[t - 1])

    a2 = np.zeros(n)
    d2 = np.zeros(n)
    a2[:2] = a1[:2]
    for t in range(2, n):
        a2[t] = 0.5 * (a1[t] + a1[t - 2])
        d2[t] = 0.5 * (a1[t] - a1[t - 2])

    a3 = np.zeros(n)
    d3 = np.zeros(n)
    a3[:4] = a2[:4]
    for t in range(4, n):
        a3[t] = 0.5 * (a2[t] + a2[t - 4])
        d3[t] = 0.5 * (a2[t] - a2[t - 4])

    return d1, d2, d3, a3


def calculate_ehlers_supersmoother_2pole(prices: np.ndarray, period: int = 12) -> np.ndarray:
    n = len(prices)
    if n < 4:
        return prices.copy()
    a1 = math.exp(-math.sqrt(2.0) * math.pi / period)
    b1 = 2.0 * a1 * math.cos(math.sqrt(2.0) * math.pi / period)
    c2 = b1
    c3 = -a1 * a1
    c1 = 1.0 - c2 - c3
    filt = np.zeros(n)
    filt[0] = prices[0]
    filt[1] = prices[1]
    for t in range(2, n):
        filt[t] = c1 * (prices[t] + prices[t - 1]) * 0.5 + c2 * filt[t - 1] + c3 * filt[t - 2]
    return filt


def calculate_factors(df: pd.DataFrame, window: int = 40) -> pd.DataFrame:
    c = df["close"].astype(float).values
    o = df["open"].astype(float).values
    h = df["high"].astype(float).values
    l = df["low"].astype(float).values
    v = df["volume"].astype(float).values
    n = len(df)

    # 1. 因果 ATR (14 周期)
    prev_c = np.roll(c, 1)
    prev_c[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    atr = pd.Series(tr, index=df.index).rolling(14, min_periods=5).mean().bfill().values + 1e-8

    # 2. MODWT 3 级分解
    d1, d2, d3, a3 = compute_causal_modwt_3level(c)

    # 3. 小波局部能量谱与挤压度量
    d1_sq = pd.Series(d1 ** 2, index=df.index).rolling(window, min_periods=5).mean().bfill().values
    d2_sq = pd.Series(d2 ** 2, index=df.index).rolling(window, min_periods=5).mean().bfill().values
    d3_sq = pd.Series(d3 ** 2, index=df.index).rolling(window, min_periods=5).mean().bfill().values

    a3_s = pd.Series(a3, index=df.index)
    a3_mean = a3_s.rolling(window, min_periods=5).mean().bfill().values
    a3_sq = pd.Series((a3 - a3_mean) ** 2, index=df.index).rolling(window, min_periods=5).mean().bfill().values

    e_detail = d1_sq + d2_sq + d3_sq
    e_total = e_detail + a3_sq + 1e-8
    wavelet_squeeze = e_detail / e_total
    had_squeeze = pd.Series(wavelet_squeeze, index=df.index).rolling(6, min_periods=1).min().values <= 0.35

    # 4. 近似分量 A3 斜率速度
    a3_slope = np.zeros(n)
    a3_slope[3:] = (a3[3:] - a3[:-3]) / (atr[3:] * np.sqrt(3.0))

    # 5. Ehlers 零滞后趋势
    filt_fast = calculate_ehlers_supersmoother_2pole(c, period=6)
    filt_slow = calculate_ehlers_supersmoother_2pole(c, period=18)
    trend_up = filt_fast > filt_slow
    trend_dn = filt_fast < filt_slow

    # 6. 标度律分形赫斯特指数
    c_s = pd.Series(c, index=df.index)
    c_diff2 = c_s.diff(2)
    c_diff8 = c_s.diff(8)
    tau2 = c_diff2.rolling(window, min_periods=5).std(ddof=0)
    tau8 = c_diff8.rolling(window, min_periods=5).std(ddof=0)
    hurst = (np.log((tau8 + 1e-8) / (tau2 + 1e-8)) / np.log(4.0)).clip(0.1, 0.9).bfill().values

    # 7. K 线微观实体
    bar_range = np.maximum(1e-8, h - l)
    body = np.abs(c - o)
    body_ratio = body / bar_range

    # 8. 持仓量过滤
    vol_ma20 = pd.Series(v, index=df.index).rolling(20, min_periods=5).mean().bfill().values + 1e-8
    oi_filter_long = np.ones(n, dtype=bool)
    oi_filter_short = np.ones(n, dtype=bool)
    if "open_interest" in df.columns:
        oi = df["open_interest"].astype(float).values
        oi_diff = np.diff(oi, prepend=oi[0])
        oi_filter_long = oi_diff >= -vol_ma20 * 0.40
        oi_filter_short = oi_diff >= -vol_ma20 * 0.40

    return pd.DataFrame({
        "d1": d1,
        "d2": d2,
        "d3": d3,
        "a3": a3,
        "a3_slope": a3_slope,
        "wavelet_squeeze": wavelet_squeeze,
        "had_squeeze": had_squeeze,
        "trend_up": trend_up,
        "trend_dn": trend_dn,
        "hurst": hurst,
        "body_ratio": body_ratio,
        "atr": atr,
        "oi_filter_long": oi_filter_long,
        "oi_filter_short": oi_filter_short
    }, index=df.index)


def calculate_signal(df: pd.DataFrame) -> pd.Series:
    c = df["close"].astype(float).values
    o = df["open"].astype(float).values
    factors = calculate_factors(df)

    a3 = factors["a3"].values
    a3_slope = factors["a3_slope"].values
    had_squeeze = factors["had_squeeze"].values
    t_up = factors["trend_up"].values
    t_dn = factors["trend_dn"].values
    hurst = factors["hurst"].values
    body_ratio = factors["body_ratio"].values
    oi_long = factors["oi_filter_long"].values
    oi_short = factors["oi_filter_short"].values

    long_cond = (
        t_up &
        (c > a3) &
        (a3_slope >= 0.10) &
        had_squeeze &
        (hurst >= 0.50) &
        (c > o) &
        (body_ratio >= 0.40) &
        oi_long
    )

    short_cond = (
        t_dn &
        (c < a3) &
        (a3_slope <= -0.10) &
        had_squeeze &
        (hurst >= 0.50) &
        (c < o) &
        (body_ratio >= 0.40) &
        oi_short
    )

    signals = pd.Series(0, index=df.index, dtype=int)
    signals[long_cond] = 1
    signals[short_cond] = -1

    return signals
