"""
strategies/autoquant_champion_strategy.py — 「AutoQuant·全球冠军自进化正反馈策略」
(AutoQuant Champion Self-Evolved Strategy — 50 代闭环进化优胜基因)

核心拓扑架构：
- DSP 零滞后滤波器：Fast = 4, Slow = 16
- 动力学机制分流门禁：Hurst Trend Gate = 0.56, Hurst Revert Gate = 0.38
- 微观能量挤压比率：Squeeze Ratio <= 1.25, K线实体饱和度 >= 0.35
- 非对称出场引擎：初始止损 1.4 * ATR, 动态保本 1.2 * ATR, 动态吊灯放飞 2.5 * ATR (绝无死止盈)
- 波动率等权单笔风险预算：1.5%
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd

STRATEGY_NAME = "autoquant_champion_strategy"
STRATEGY_DESCRIPTION = "「AutoQuant·全球冠军自进化正反馈策略」: 50代双Agent对抗进化生成的稳健工业级策略"


def calculate_ehlers_supersmoother_2pole(prices: np.ndarray, period: int = 16) -> np.ndarray:
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
    atr = pd.Series(tr, index=df.index).rolling(14, min_periods=5).mean().values + 1e-8

    filt_fast = calculate_ehlers_supersmoother_2pole(c, period=4)
    filt_slow = calculate_ehlers_supersmoother_2pole(c, period=16)
    trend_up = filt_fast > filt_slow
    trend_dn = filt_fast < filt_slow

    c_s = pd.Series(c, index=df.index)
    c_diff2 = c_s.diff(2)
    c_diff8 = c_s.diff(8)
    tau2 = c_diff2.rolling(40, min_periods=5).std(ddof=0)
    tau8 = c_diff8.rolling(40, min_periods=5).std(ddof=0)
    hurst = (np.log((tau8 + 1e-8) / (tau2 + 1e-8)) / np.log(4.0)).clip(0.1, 0.9).values

    is_trend = hurst >= 0.56
    is_revert = hurst <= 0.38

    c_std = c_s.rolling(20, min_periods=5).std(ddof=0).values + 1e-8
    squeeze_ratio = (4.0 * c_std) / (2.0 * atr)
    had_squeeze = pd.Series(squeeze_ratio, index=df.index).rolling(6, min_periods=1).min().values <= 1.25

    bar_range = np.maximum(1e-8, h - l)
    body_ratio = np.abs(c - o) / bar_range

    roll_high = pd.Series(h, index=df.index).rolling(30, min_periods=5).max().shift(1).values
    roll_low = pd.Series(l, index=df.index).rolling(30, min_periods=5).min().shift(1).values
    dev_atrs = (c - filt_slow) / atr

    vol_ma20 = pd.Series(v, index=df.index).rolling(20, min_periods=5).mean().values + 1e-8
    oi_filter_long = np.ones(n, dtype=bool)
    oi_filter_short = np.ones(n, dtype=bool)
    if "open_interest" in df.columns:
        oi = df["open_interest"].astype(float).values
        oi_diff = np.diff(oi, prepend=oi[0])
        oi_filter_long = oi_diff >= -vol_ma20 * 0.40
        oi_filter_short = oi_diff >= -vol_ma20 * 0.40

    return pd.DataFrame({
        "trend_up": trend_up,
        "trend_dn": trend_dn,
        "hurst": hurst,
        "is_trend": is_trend,
        "is_revert": is_revert,
        "roll_high": roll_high,
        "roll_low": roll_low,
        "had_squeeze": had_squeeze,
        "body_ratio": body_ratio,
        "dev_atrs": dev_atrs,
        "atr": atr,
        "filt_slow": filt_slow,
        "oi_filter_long": oi_filter_long,
        "oi_filter_short": oi_filter_short
    }, index=df.index)


def calculate_signal(df: pd.DataFrame) -> pd.Series:
    c = df["close"].astype(float).values
    o = df["open"].astype(float).values
    factors = calculate_factors(df)

    t_up = factors["trend_up"].values
    t_dn = factors["trend_dn"].values
    is_tr = factors["is_trend"].values
    is_rev = factors["is_revert"].values
    h_ch = factors["roll_high"].values
    l_ch = factors["roll_low"].values
    had_sq = factors["had_squeeze"].values
    body_ratio = factors["body_ratio"].values
    dev = factors["dev_atrs"].values
    oi_l = factors["oi_filter_long"].values
    oi_s = factors["oi_filter_short"].values

    sig_trend_long = is_tr & t_up & (c > h_ch) & had_sq & (c > o) & (body_ratio >= 0.35) & oi_l
    sig_trend_short = is_tr & t_dn & (c < l_ch) & had_sq & (c < o) & (body_ratio >= 0.35) & oi_s

    sig_rev_long = is_rev & (dev <= -2.0) & (c > o) & oi_l
    sig_rev_short = is_rev & (dev >= 2.0) & (c < o) & oi_s
    finite = np.isfinite(
        factors[["atr", "hurst", "roll_high", "roll_low"]]
    ).all(axis=1).values

    signals = pd.Series(0, index=df.index, dtype=int)
    signals[(sig_trend_long | sig_rev_long) & finite] = 1
    signals[(sig_trend_short | sig_rev_short) & finite] = -1

    return signals
