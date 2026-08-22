"""
strategies/supertrend_strategy.py — SuperTrend (ATR 经典趋势追踪通道) 独立热插拔策略

数学原理:
1. 计算中位价 HL2 = (High + Low) / 2 与 ATR (周期 10)。
2. 基础上下轨:
   - Basic Upper = HL2 + Multiplier * ATR
   - Basic Lower = HL2 - Multiplier * ATR
3. 动态最终上下轨 (防回退锁定):
   - Final Upper = Basic Upper if (Basic Upper < Prev Final Upper or Prev Close > Prev Final Upper) else Prev Final Upper
   - Final Lower = Basic Lower if (Basic Lower > Prev Final Lower or Prev Close < Prev Final Lower) else Prev Final Lower
4. 状态机翻转:
   - Close 上穿 Final Upper -> 翻多 (Signal = 1)
   - Close 下穿 Final Lower -> 翻空 (Signal = -1)
"""

import numpy as np
import pandas as pd


def compute_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> tuple:
    """计算 SuperTrend 轨线与多空方向"""
    high = df["high"].astype(float).values
    low = df["low"].astype(float).values
    close = df["close"].astype(float).values
    n = len(close)

    if n < period + 5:
        return np.zeros(n), np.zeros(n)

    # 1. 计算 ATR
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))

    atr = np.zeros(n)
    atr[period - 1] = np.mean(tr[:period])
    alpha = 1.0 / period
    for i in range(period, n):
        atr[i] = alpha * tr[i] + (1.0 - alpha) * atr[i - 1]

    # 2. 基础上下轨
    hl2 = (high + low) / 2.0
    basic_upper = hl2 + multiplier * atr
    basic_lower = hl2 - multiplier * atr

    final_upper = np.zeros(n)
    final_lower = np.zeros(n)
    super_trend = np.zeros(n)
    direction = np.zeros(n, dtype=int)  # 1: Long/Bullish, -1: Short/Bearish

    # 初始化
    final_upper[period - 1] = basic_upper[period - 1]
    final_lower[period - 1] = basic_lower[period - 1]
    direction[period - 1] = 1 if close[period - 1] > final_upper[period - 1] else -1
    super_trend[period - 1] = final_lower[period - 1] if direction[period - 1] == 1 else final_upper[period - 1]

    for i in range(period, n):
        # 最终上轨
        if basic_upper[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]:
            final_upper[i] = basic_upper[i]
        else:
            final_upper[i] = final_upper[i - 1]

        # 最终下轨
        if basic_lower[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]:
            final_lower[i] = basic_lower[i]
        else:
            final_lower[i] = final_lower[i - 1]

        # 判定方向与 SuperTrend 线
        prev_st = super_trend[i - 1]
        prev_dir = direction[i - 1]

        if prev_dir == 1:
            if close[i] < final_lower[i]:
                direction[i] = -1
                super_trend[i] = final_upper[i]
            else:
                direction[i] = 1
                super_trend[i] = final_lower[i]
        else:
            if close[i] > final_upper[i]:
                direction[i] = 1
                super_trend[i] = final_lower[i]
            else:
                direction[i] = -1
                super_trend[i] = final_upper[i]

    return super_trend, direction


def calculate_signal(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.Series:
    """标准热插拔信号函数: 返回 1 (翻多), -1 (翻空), 0 (无操作)"""
    super_trend, direction = compute_supertrend(df, period=period, multiplier=multiplier)
    n = len(df)
    signals = np.zeros(n, dtype=int)

    for i in range(1, n):
        if direction[i] == 1 and direction[i - 1] == -1:
            signals[i] = 1
        elif direction[i] == -1 and direction[i - 1] == 1:
            signals[i] = -1

    return pd.Series(signals, index=df.index)
