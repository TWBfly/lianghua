"""
strategies/alphatrend_strategy.py — AlphaTrend (RSI + ATR 动态自适应通道) 独立热插拔策略

数学原理 (Kivanç Özbilgiç):
1. 计算 ATR (周期 14) 与 RSI (周期 14)。
2. 基准通道:
   - 若 RSI >= 50 (多头动能): UpT = Low - ATR * Multiplier (下轨支撑)
   - 若 RSI < 50 (空头动能): DownT = High + ATR * Multiplier (上轨阻力)
3. 递归跟踪轨 (AlphaTrend):
   - 若 RSI >= 50: AlphaTrend = max(UpT, AlphaTrend[t-1])
   - 若 RSI < 50: AlphaTrend = min(DownT, AlphaTrend[t-1])
4. 延迟线与金叉死叉:
   - AlphaTrend_2 = AlphaTrend[t-2]
   - 做多: AlphaTrend 向上金叉 AlphaTrend_2
   - 做空: AlphaTrend 向下死叉 AlphaTrend_2
"""

import numpy as np
import pandas as pd


def compute_alphatrend(df: pd.DataFrame, period: int = 14, multiplier: float = 1.618) -> tuple:
    """计算 AlphaTrend 核心指标序列"""
    high = df["high"].astype(float).values
    low = df["low"].astype(float).values
    close = df["close"].astype(float).values
    n = len(close)

    if n < period + 5:
        return np.zeros(n), np.zeros(n)

    # 1. 计算 True Range & ATR (Wilder RMA)
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))

    # RMA of TR
    atr = np.zeros(n)
    atr[period - 1] = np.mean(tr[:period])
    alpha = 1.0 / period
    for i in range(period, n):
        atr[i] = alpha * tr[i] + (1.0 - alpha) * atr[i - 1]

    # 2. 计算 RSI
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    
    avg_gain = np.zeros(n)
    avg_loss = np.zeros(n)
    avg_gain[period - 1] = np.mean(gain[:period])
    avg_loss[period - 1] = np.mean(loss[:period])
    
    for i in range(period, n):
        avg_gain[i] = alpha * gain[i] + (1.0 - alpha) * avg_gain[i - 1]
        avg_loss[i] = alpha * loss[i] + (1.0 - alpha) * avg_loss[i - 1]
        
    rsi = np.zeros(n)
    for i in range(period, n):
        if avg_loss[i] == 0:
            rsi[i] = 100.0 if avg_gain[i] > 0 else 50.0
        else:
            rs = avg_gain[i] / avg_loss[i]
            rsi[i] = 100.0 - (100.0 / (1.0 + rs))

    # 3. 计算 UpT, DownT & 递归 AlphaTrend
    up_t = low - atr * multiplier
    down_t = high + atr * multiplier
    
    alpha_trend = np.zeros(n)
    for i in range(1, n):
        prev_at = alpha_trend[i - 1]
        if rsi[i] >= 50:
            alpha_trend[i] = max(up_t[i], prev_at) if prev_at != 0 else up_t[i]
        else:
            alpha_trend[i] = min(down_t[i], prev_at) if prev_at != 0 else down_t[i]

    # 4. 延迟 2 周期线
    alpha_trend_2 = np.zeros(n)
    alpha_trend_2[2:] = alpha_trend[:-2]

    return alpha_trend, alpha_trend_2


def calculate_signal(df: pd.DataFrame, period: int = 14, multiplier: float = 1.618) -> pd.Series:
    """标准热插拔信号函数: 返回 1 (做多), -1 (做空), 0 (无操作)"""
    alpha_trend, alpha_trend_2 = compute_alphatrend(df, period=period, multiplier=multiplier)
    n = len(df)
    signals = np.zeros(n, dtype=int)

    for i in range(3, n):
        # 金叉
        if alpha_trend[i] > alpha_trend_2[i] and alpha_trend[i - 1] <= alpha_trend_2[i - 1]:
            signals[i] = 1
        # 死叉
        elif alpha_trend[i] < alpha_trend_2[i] and alpha_trend[i - 1] >= alpha_trend_2[i - 1]:
            signals[i] = -1

    return pd.Series(signals, index=df.index)
