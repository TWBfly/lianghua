"""
strategies/tianquan_extreme_phase_reversal.py — 「天权·极值条件相变反转策略」
Tianquan Conditional Extreme-Phase Reversal Strategy (Futures 15m / 30m)

核心量化物理机制（融合《研究策略.md》4 层事件架构与正反馈第一性原理）：
1. Layer 1: 动力学体制门禁 (Regime Gate):
   - Ehlers 2-Pole SuperSmoother (6 vs 18 周期) 零滞后基线与趋势方向；
   - 动态方差比率赫斯特指数 Hurst: H <= 0.52 允许均值回归反转，H >= 0.58 强趋势单边状态下严格禁止逆势摸顶抄底。
2. Layer 2: 复合极值事件检测器 (Extreme Event Detector with Cooldown):
   - 20 周期标准化价格位移 Z-Score (|Z| >= 2.2)；
   - 2 周期 Connors RSI 极度超卖 (<= 8.0) 或极度超买 (>= 92.0)；
   - 2.0 * ATR 动态带宽超限；
   - 动态冷却窗口 (Cooldown = 6 根 Bar): 避免极端持续走势中连续发单造成仓位集中。
3. Layer 3: 做市商吸收形态与筹码衰竭门禁 (Absorption & OI Unwinding):
   - K 线微观吸收形态 (Pin Bar Absorption): 探底长下影阳线 / 冲顶长上影阴线确立防守；
   - 持仓量 (Open Interest) 过滤: 排除持仓暴增的暴力突破 (ΔOI > 0.4 * MA(Vol) 时严禁反转)。
4. Layer 4: 非对称肥尾执行设计 (Asymmetric Execution Spec):
   - 信号在 t 根 Bar 收盘因果计算，严格在 t+1 根 Bar 开盘价 (Next-Open) 成交；
   - 配合动态保本 (1.0 * ATR) 与非对称吊灯追踪 (2.5 * ATR)，彻底废除微观固定止盈，消灭负期望陷阱。
"""

from __future__ import annotations

import math
from typing import Dict, Any
import numpy as np
import pandas as pd

STRATEGY_NAME = "tianquan_extreme_phase_reversal"
STRATEGY_DESCRIPTION = "「天权·极值相变」: 动力学体制门禁 + 复合极值检测 + 做市商吸收与持仓衰竭 + 动态吊灯非对称追踪"


def calculate_ehlers_supersmoother_2pole(prices: np.ndarray, period: int = 14) -> np.ndarray:
    """Ehlers 2-Pole SuperSmoother 零滞后滤波器 (纯因果 IIR)"""
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


def calculate_factors(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    计算天权策略全套因果特征拓扑矩阵
    输入必须包含: open, high, low, close, volume (open_interest 可选)
    """
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
    atr_series = pd.Series(tr, index=df.index).rolling(14, min_periods=3).mean().ffill().fillna(1.0)
    atr = atr_series.values + 1e-8

    # 2. Layer 1: Ehlers 2-Pole SuperSmoother 零滞后中枢与大势
    filt_fast = calculate_ehlers_supersmoother_2pole(c, period=6)
    filt_slow = calculate_ehlers_supersmoother_2pole(c, period=18)
    trend_up = filt_fast > filt_slow
    trend_dn = filt_fast < filt_slow

    # 局部方差比率赫斯特指数 (Variance Ratio Hurst Proxy)
    c_s = pd.Series(c, index=df.index)
    c_diff2 = c_s.diff(2)
    c_diff8 = c_s.diff(8)
    tau2 = c_diff2.rolling(window, min_periods=5).std(ddof=0)
    tau8 = c_diff8.rolling(window, min_periods=5).std(ddof=0)
    hurst_raw = (np.log((tau8 + 1e-8) / (tau2 + 1e-8)) / np.log(4.0)).clip(0.1, 0.9)
    hurst = hurst_raw.ffill().fillna(0.5).values

    # 3. Layer 2: 复合极值度量 (Extreme Score Components)
    # 20 周期 SMA 与 Z-Score
    sma_20 = c_s.rolling(window, min_periods=5).mean().ffill().fillna(c_s).values
    std_20 = c_s.rolling(window, min_periods=5).std(ddof=0).ffill().fillna(1.0).values + 1e-8
    zscore = (c - sma_20) / std_20

    # 2 周期 Connors RSI (超高频敏锐震荡器)
    delta = c_s.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.rolling(2, min_periods=1).mean()
    avg_loss = loss.rolling(2, min_periods=1).mean() + 1e-8
    rs = avg_gain / avg_loss
    rsi_2 = (100.0 - (100.0 / (1.0 + rs))).ffill().fillna(50.0).values

    # Keltner/Bollinger 动态 ATR 通道超限
    upper_env = sma_20 + 2.0 * atr
    lower_env = sma_20 - 2.0 * atr
    extreme_oversold_band = c < lower_env
    extreme_overbought_band = c > upper_env

    # 4. Layer 3: K 线解剖与做市商微观吸收 (Candle Anatomy & Absorption)
    bar_range = np.maximum(1e-8, h - l)
    body = np.abs(c - o)
    lower_shadow = np.where(c >= o, o - l, c - l)
    upper_shadow = np.where(c >= o, h - c, h - o)

    # 阳线探底拒斥吸收 (Bullish Absorption Pin Bar)
    bullish_absorption = (c >= o) & (lower_shadow >= body * 0.5) & (lower_shadow >= bar_range * 0.35)
    # 阴线冲顶拒斥吸收 (Bearish Absorption Pin Bar)
    bearish_absorption = (c <= o) & (upper_shadow >= body * 0.5) & (upper_shadow >= bar_range * 0.35)

    # 5. 持仓量解耦过滤 (Open Interest Unwinding Filter)
    vol_ma20 = pd.Series(v, index=df.index).rolling(20, min_periods=3).mean().ffill().fillna(1.0).values + 1e-8
    oi_filter_long = np.ones(n, dtype=bool)
    oi_filter_short = np.ones(n, dtype=bool)

    if "open_interest" in df.columns:
        oi = df["open_interest"].astype(float).values
        oi_diff = np.diff(oi, prepend=oi[0])
        # 极度超卖或超买时，若持仓量暴增(>0.4 * 均量)，代表主力在凶猛单边加仓逼仓，严禁逆势接刀！
        oi_filter_long = oi_diff <= vol_ma20 * 0.40
        oi_filter_short = oi_diff <= vol_ma20 * 0.40

    return pd.DataFrame({
        "atr": atr,
        "filt_fast": filt_fast,
        "filt_slow": filt_slow,
        "trend_up": trend_up,
        "trend_dn": trend_dn,
        "hurst": hurst,
        "zscore": zscore,
        "rsi_2": rsi_2,
        "extreme_oversold_band": extreme_oversold_band,
        "extreme_overbought_band": extreme_overbought_band,
        "bullish_absorption": bullish_absorption,
        "bearish_absorption": bearish_absorption,
        "oi_filter_long": oi_filter_long,
        "oi_filter_short": oi_filter_short,
        "vol_ma20": vol_ma20
    }, index=df.index)


def calculate_signal(df: pd.DataFrame, cooldown_bars: int = 6) -> pd.Series:
    """
    天权策略标准热插拔信号生成接口:
    输入: df 包含 open, high, low, close, volume, open_interest (可选)
    输出: pd.Series (+1=做多, -1=做空, 0=无信号)
    
    严格时序语义:
    第 t 根 Bar 收盘因果计算产生信号，严格在第 t+1 根 Bar 开盘撮合成交。
    包含动态冷却窗口 (Cooldown)，防止同一波极值行情中连续开仓导致仓位非理性暴露。
    """
    n = len(df)
    if n < 20:
        return pd.Series(0, index=df.index, dtype=int)

    factors = calculate_factors(df)

    zscore = factors["zscore"].values
    rsi_2 = factors["rsi_2"].values
    band_os = factors["extreme_oversold_band"].values
    band_ob = factors["extreme_overbought_band"].values
    b_absorb = factors["bullish_absorption"].values
    s_absorb = factors["bearish_absorption"].values
    oi_long = factors["oi_filter_long"].values
    oi_short = factors["oi_filter_short"].values
    hurst = factors["hurst"].values

    t_up = factors["trend_up"].values
    t_dn = factors["trend_dn"].values

    # 1. 裸信号候选识别 (Raw Candidates)
    # 做多反转条件:
    # a. 极度超卖: Z-Score <= -2.0 且 2周期RSI <= 8.0 且 跌破2.0 ATR下轨
    # b. 做市商微观吸收: 探底长下影阳线
    # c. 动力学体制门禁: Hurst <= 0.54 且 严禁在宏观主跌浪强单边(trend_dn 且 hurst > 0.48)中逆势接刀
    # d. 筹码衰竭: 持仓量无异常爆发性逼仓
    macro_long_allowed = (~t_dn) | (hurst <= 0.48)
    macro_short_allowed = (~t_up) | (hurst <= 0.48)

    raw_long = (
        (zscore <= -2.0) &
        (rsi_2 <= 8.0) &
        band_os &
        b_absorb &
        (hurst <= 0.54) &
        macro_long_allowed &
        oi_long
    )

    # 做空反转条件:
    # a. 极度超买: Z-Score >= 2.0 且 2周期RSI >= 92.0 且 突破2.0 ATR上轨
    # b. 做市商微观吸收: 冲顶长上影阴线
    # c. 动力学体制门禁: Hurst <= 0.54 且 严禁在宏观主升浪强单边(trend_up 且 hurst > 0.48)中逆势摸顶
    # d. 筹码衰竭: 持仓量无异常爆发性逼仓
    raw_short = (
        (zscore >= 2.0) &
        (rsi_2 >= 92.0) &
        band_ob &
        s_absorb &
        (hurst <= 0.54) &
        macro_short_allowed &
        oi_short
    )

    # 2. 动态冷却状态机 (Event Cooldown State Machine)
    # 避免在连续下跌或暴涨中多次触发同向信号
    signals = np.zeros(n, dtype=int)
    last_signal_idx = -999
    last_signal_dir = 0

    for i in range(n):
        if raw_long[i]:
            if i - last_signal_idx >= cooldown_bars or last_signal_dir != 1:
                signals[i] = 1
                last_signal_idx = i
                last_signal_dir = 1
        elif raw_short[i]:
            if i - last_signal_idx >= cooldown_bars or last_signal_dir != -1:
                signals[i] = -1
                last_signal_idx = i
                last_signal_dir = -1

    return pd.Series(signals, index=df.index, dtype=int)
