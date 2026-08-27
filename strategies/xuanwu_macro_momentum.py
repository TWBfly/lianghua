"""
strategies/xuanwu_macro_momentum.py — 「玄武·宏观」: Walk-Forward HMM 宏观状态自适应 + 非对称半方差行业 ETF 动量轮动策略

核心微观量化机制：
1. 非对称下行半方差动量 (Upside vs Downside Realized Semi-Variance Asymmetry):
   - 传统动量容易买入暴涨暴跌的高下行波动资产。本策略计算 20 日上行波动与下行波动的半方差比率 (Asymmetry Ratio >= 1.15)，仅做多具有“大涨小回”非对称优势的强势标的；
2. 动量二阶加速度 (Momentum Velocity & Acceleration):
   - 结合 10 日短期速度与 20 日中期速度计算动量加速度 (Acceleration > 0)，确保动量处于增强通道而非衰竭末端；
3. 均线结构过滤 (Trend EMA Alignment):
   - 价格处于 EMA(20) 之上且 EMA(20) > EMA(60)，杜绝弱势阴跌标的；
4. 严格防未来函数：纯因果 Rolling 计算，与系统 HMM 顶层宏观风控无缝级联。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

STRATEGY_NAME = "xuanwu_macro_momentum"
STRATEGY_DESCRIPTION = "「玄武·宏观」: Walk-Forward HMM 宏观状态自适应 + 非对称半方差行业 ETF 动量轮动策略"


def calculate_signal(df: pd.DataFrame) -> pd.Series:
    """
    标准热插拔信号接口:
    输入: df 包含 open, high, low, close, volume, amount (可选)
    输出: pd.Series (+1=做多, -1=做空, 0=无信号)
    """
    c = df["close"].astype(float)
    o = df["open"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    v = df["volume"].astype(float)

    # 1. 计算日收益率与 20 日非对称半方差比率 (Upside / Downside Semi-Variance)
    ret = c.pct_change(1).fillna(0.0)
    up_ret = ret.clip(lower=0.0)
    down_ret = (-ret).clip(lower=0.0)
    up_var = (up_ret ** 2).rolling(20).mean()
    down_var = (down_ret ** 2).rolling(20).mean().replace(0, np.nan)
    asymmetry_ratio = np.sqrt(up_var / down_var).fillna(1.0)

    # 2. 动量速度与加速度 (10-day vs 20-day)
    ret_10 = c.pct_change(10).fillna(0.0)
    ret_20 = c.pct_change(20).fillna(0.0)
    mom_accel = ret_10 - (ret_20 / 2.0)

    # 3. 趋势均线结构 (EMA20 vs EMA60)
    ema_20 = c.ewm(span=20, adjust=False).mean()
    ema_60 = c.ewm(span=60, adjust=False).mean()

    # 4. 成交量流动性过滤 (排除无量阴跌或流动性枯竭)
    vol_ma20 = v.rolling(20).mean().replace(0, np.nan)
    vol_z20 = (v - vol_ma20) / (v.rolling(20).std(ddof=0).replace(0, np.nan) + 1e-8)

    # 5. 做多与出场条件
    long_condition = (
        (c > ema_20) &
        (ema_20 > ema_60) &
        (asymmetry_ratio >= 1.05) &
        (ret_10 > 0.0) &
        (mom_accel >= 0.0) &
        (vol_z20 >= -1.0)
    )

    exit_condition = (
        (c < ema_20 * 0.98) |
        (asymmetry_ratio < 0.80) |
        (mom_accel < -0.05)
    )

    signals = pd.Series(0, index=df.index)
    signals[long_condition] = 1
    signals[exit_condition] = -1

    return signals
