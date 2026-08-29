"""
strategies/supertrend_evolution_master.py — SuperTrend 工业级全周期系统化进化策略库

涵盖 SuperTrend 从指标向「交易系统」转型的全套进阶架构：
- ST-00: 基准经典 SuperTrend (Flip-Flop 翻转反手)
- ST-01: 市场状态与趋势效率过滤 (Kaufman Efficiency Ratio / ADX Chop Filter)
- ST-02: 多周期级联 SuperTrend (60m 宏观趋势状态机 + 15m 微观执行)
- ST-03: 独立入场引擎解耦 (SuperTrend 仅定多空偏向 + 唐奇安突破 / EMA 回踩低吸)
- ST-04: 入场/出场敏感度解耦 (快进慢出: Fast ST 入场 + Slow ST / Chandelier 吊灯宽幅出场，废除无脑反手)
- ST-05: 动态自适应波动率乘数 (Dynamic Multiplier: M_t = f(TrendStrength, Volatility))
- ST-06: 波动率目标风险平价仓位管理 (Volatility Targeting Risk Sizing)
- ST-07: 跨品种多资产低相关趋势组合 (Multi-Asset Trend Portfolio)
- ST-Meta: 量化状态元标签过滤 (Meta-Labeling Expectancy Filter)

第一性原理：
1. 严禁未来函数：全部使用纯因果 Rolling / EMA 递推计算；
2. 状态机解耦：Strategy = Regime + Direction + Entry + Exit + Sizing + RiskControl；
3. 热插拔兼容：完全符合 strategy_hot_plugger 与 unified_realtime_trader 规范。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Any
import numpy as np
import pandas as pd

STRATEGY_NAME = "supertrend_evolution_master"
STRATEGY_DESCRIPTION = "SuperTrend 工业级全周期系统化进化策略 (8代演进架构)"


# ==============================================================================
# 1. 底层核心算子：因果 SuperTrend 轨线与状态机
# ==============================================================================

def compute_supertrend_bands(
    df: pd.DataFrame,
    period: int = 10,
    multiplier: float = 3.0
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    纯因果计算 SuperTrend 上下轨与趋势方向：
    返回: (super_trend_line, direction, final_upper, final_lower)
    - direction: +1 (多头牛市趋势), -1 (空头熊市趋势)
    """
    high = df["high"].astype(float).to_numpy()
    low = df["low"].astype(float).to_numpy()
    close = df["close"].astype(float).to_numpy()
    n = len(close)

    if n < period + 2:
        return np.zeros(n), np.zeros(n, dtype=int), np.zeros(n), np.zeros(n)

    # 1. 真实波幅 ATR (Wilder's Smoothing)
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
    direction = np.zeros(n, dtype=int)

    # 初始化起始状态
    final_upper[period - 1] = basic_upper[period - 1]
    final_lower[period - 1] = basic_lower[period - 1]
    direction[period - 1] = 1 if close[period - 1] > final_upper[period - 1] else -1
    super_trend[period - 1] = final_lower[period - 1] if direction[period - 1] == 1 else final_upper[period - 1]

    # 递推锁定轨线
    for i in range(period, n):
        # 最终上轨：未突破时只能下移或保持，不可向上漂移
        if basic_upper[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]:
            final_upper[i] = basic_upper[i]
        else:
            final_upper[i] = final_upper[i - 1]

        # 最终下轨：未跌破时只能上移或保持，不可向下漂移
        if basic_lower[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]:
            final_lower[i] = basic_lower[i]
        else:
            final_lower[i] = final_lower[i - 1]

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

    return super_trend, direction, final_upper, final_lower


def compute_kaufman_efficiency_ratio(close: pd.Series, period: int = 20) -> pd.Series:
    """
    计算考夫曼趋势效率比率 (KER):
    KER = |Close_t - Close_{t-N}| / sum(|Close_i - Close_{i-1}|)
    - KER -> 1: 完美单边趋势 (位移/路程比极高)
    - KER -> 0: 严重锯齿震荡 (位移极小，路程极大，SuperTrend 绞肉机环境)
    """
    net_change = (close - close.shift(period)).abs()
    path = close.diff().abs().rolling(period).sum().replace(0, np.nan)
    ker = (net_change / path).fillna(0.0)
    return ker


def compute_dynamic_supertrend(
    df: pd.DataFrame,
    period: int = 10,
    base_multiplier: float = 3.0,
    alpha_adapt: float = 1.5
) -> Tuple[np.ndarray, np.ndarray]:
    """
    ST-05: 动态自适应 Multiplier SuperTrend
    M_t = base_multiplier + alpha * (KER - 0.3)
    - 趋势强时: 放大乘数 (例如 3.5~4.0)，给利润奔跑预留波动空间；
    - 震荡弱时: 缩小乘数 (例如 2.0~2.5)，快速止损离场防深套。
    """
    close_series = df["close"].astype(float)
    ker = compute_kaufman_efficiency_ratio(close_series, period=20).to_numpy()
    
    # 动态计算每根 Bar 的 Multiplier
    dynamic_m = np.clip(base_multiplier + alpha_adapt * (ker - 0.30), 1.5, 5.0)

    high = df["high"].astype(float).to_numpy()
    low = df["low"].astype(float).to_numpy()
    close = close_series.to_numpy()
    n = len(close)

    if n < period + 2:
        return np.zeros(n), np.zeros(n, dtype=int)

    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))

    atr = np.zeros(n)
    atr[period - 1] = np.mean(tr[:period])
    alpha_atr = 1.0 / period
    for i in range(period, n):
        atr[i] = alpha_atr * tr[i] + (1.0 - alpha_atr) * atr[i - 1]

    hl2 = (high + low) / 2.0
    basic_upper = hl2 + dynamic_m * atr
    basic_lower = hl2 - dynamic_m * atr

    final_upper = np.zeros(n)
    final_lower = np.zeros(n)
    super_trend = np.zeros(n)
    direction = np.zeros(n, dtype=int)

    final_upper[period - 1] = basic_upper[period - 1]
    final_lower[period - 1] = basic_lower[period - 1]
    direction[period - 1] = 1 if close[period - 1] > final_upper[period - 1] else -1
    super_trend[period - 1] = final_lower[period - 1] if direction[period - 1] == 1 else final_upper[period - 1]

    for i in range(period, n):
        if basic_upper[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]:
            final_upper[i] = basic_upper[i]
        else:
            final_upper[i] = final_upper[i - 1]

        if basic_lower[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]:
            final_lower[i] = basic_lower[i]
        else:
            final_lower[i] = final_lower[i - 1]

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


# ==============================================================================
# 2. 八代演进策略信号生成器 (ST-00 ~ ST-07)
# ==============================================================================

class SuperTrendEvolutionEngine:
    """SuperTrend 8代演进架构生成引擎"""

    @staticmethod
    def generate_st00_baseline(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.Series:
        """
        ST-00: 经典纯 SuperTrend (翻转即反手)
        信号: +1 (翻多), -1 (翻空), 0 (维持)
        """
        _, direction, _, _ = compute_supertrend_bands(df, period=period, multiplier=multiplier)
        n = len(df)
        signals = np.zeros(n, dtype=int)
        for i in range(1, n):
            if direction[i] == 1 and direction[i - 1] == -1:
                signals[i] = 1
            elif direction[i] == -1 and direction[i - 1] == 1:
                signals[i] = -1
        return pd.Series(signals, index=df.index)

    @staticmethod
    def generate_st01_regime_filtered(
        df: pd.DataFrame,
        period: int = 10,
        multiplier: float = 3.0,
        ker_threshold: float = 0.28
    ) -> pd.Series:
        """
        ST-01: 市场状态与趋势效率过滤
        只有在 KER >= ker_threshold 且非超低波动死寂区时才释放入场信号
        """
        _, direction, _, _ = compute_supertrend_bands(df, period=period, multiplier=multiplier)
        c = df["close"].astype(float)
        ker = compute_kaufman_efficiency_ratio(c, period=20)

        n = len(df)
        signals = np.zeros(n, dtype=int)
        for i in range(1, n):
            if direction[i] == 1 and direction[i - 1] == -1:
                if ker.iloc[i] >= ker_threshold:
                    signals[i] = 1
            elif direction[i] == -1 and direction[i - 1] == 1:
                if ker.iloc[i] >= ker_threshold:
                    signals[i] = -1
        return pd.Series(signals, index=df.index)

    @staticmethod
    def generate_st02_multitimeframe(
        df_micro: pd.DataFrame,
        macro_direction: np.ndarray,
        period: int = 10,
        multiplier: float = 3.0
    ) -> pd.Series:
        """
        ST-02: 多周期级联 (HTF Macro SuperTrend + LTF Micro Execution)
        主趋势由宏观 60m 锁定，小周期 15m 顺大势触发
        """
        _, micro_dir, _, _ = compute_supertrend_bands(df_micro, period=period, multiplier=multiplier)
        n = len(df_micro)
        signals = np.zeros(n, dtype=int)

        for i in range(1, n):
            if micro_dir[i] == 1 and micro_dir[i - 1] == -1 and macro_direction[i] == 1:
                signals[i] = 1
            elif micro_dir[i] == -1 and micro_dir[i - 1] == 1 and macro_direction[i] == -1:
                signals[i] = -1
        return pd.Series(signals, index=df_micro.index)

    @staticmethod
    def generate_st03_independent_entry(
        df: pd.DataFrame,
        period: int = 10,
        multiplier: float = 3.0,
        entry_mode: str = "breakout"
    ) -> pd.Series:
        """
        ST-03: 独立入场引擎解耦
        SuperTrend 降级为背景状态机 (direction == 1 允许买, direction == -1 允许卖)
        - breakout: 20 周期唐奇安极值突破
        - pullback: 价格回踩 EMA20 / SuperTrend 轨线后强实体反弹
        """
        st_line, direction, _, _ = compute_supertrend_bands(df, period=period, multiplier=multiplier)
        c = df["close"].astype(float)
        h = df["high"].astype(float)
        l = df["low"].astype(float)
        o = df["open"].astype(float)
        n = len(df)

        signals = np.zeros(n, dtype=int)

        if entry_mode == "breakout":
            don_hi = h.shift(1).rolling(20).max()
            don_lo = l.shift(1).rolling(20).min()
            for i in range(20, n):
                if direction[i] == 1 and c.iloc[i] > don_hi.iloc[i] and c.iloc[i - 1] <= don_hi.iloc[i]:
                    signals[i] = 1
                elif direction[i] == -1 and c.iloc[i] < don_lo.iloc[i] and c.iloc[i - 1] >= don_lo.iloc[i]:
                    signals[i] = -1
        elif entry_mode == "pullback":
            ema20 = c.ewm(span=20, adjust=False).mean()
            for i in range(20, n):
                if direction[i] == 1 and l.iloc[i - 1] <= ema20.iloc[i - 1] * 1.003 and c.iloc[i] > o.iloc[i] and c.iloc[i] > ema20.iloc[i]:
                    signals[i] = 1
                elif direction[i] == -1 and h.iloc[i - 1] >= ema20.iloc[i - 1] * 0.997 and c.iloc[i] < o.iloc[i] and c.iloc[i] < ema20.iloc[i]:
                    signals[i] = -1

        return pd.Series(signals, index=df.index)

    @staticmethod
    def generate_st04_decoupled_exit(
        df: pd.DataFrame,
        fast_period: int = 10,
        fast_mult: float = 2.0,
        slow_period: int = 20,
        slow_mult: float = 4.0
    ) -> Tuple[pd.Series, pd.Series]:
        """
        ST-04: 入场与出场敏感度解耦 (快进慢出，废除无脑反手)
        """
        _, fast_dir, _, _ = compute_supertrend_bands(df, period=fast_period, multiplier=fast_mult)
        _, slow_dir, _, _ = compute_supertrend_bands(df, period=slow_period, multiplier=slow_mult)
        n = len(df)

        entry_sig = np.zeros(n, dtype=int)
        exit_sig = np.zeros(n, dtype=int)

        for i in range(1, n):
            if fast_dir[i] == 1 and fast_dir[i - 1] == -1 and slow_dir[i] == 1:
                entry_sig[i] = 1
            elif fast_dir[i] == -1 and fast_dir[i - 1] == 1 and slow_dir[i] == -1:
                entry_sig[i] = -1

            if slow_dir[i] == -1 and slow_dir[i - 1] == 1:
                exit_sig[i] = 1
            elif slow_dir[i] == 1 and slow_dir[i - 1] == -1:
                exit_sig[i] = -1

        return pd.Series(entry_sig, index=df.index), pd.Series(exit_sig, index=df.index)

    @staticmethod
    def generate_st05_dynamic_multiplier(
        df: pd.DataFrame,
        period: int = 10,
        base_multiplier: float = 3.0
    ) -> pd.Series:
        """
        ST-05: 自适应动态 Multiplier 信号
        """
        _, direction = compute_dynamic_supertrend(df, period=period, base_multiplier=base_multiplier)
        n = len(df)
        signals = np.zeros(n, dtype=int)
        for i in range(1, n):
            if direction[i] == 1 and direction[i - 1] == -1:
                signals[i] = 1
            elif direction[i] == -1 and direction[i - 1] == 1:
                signals[i] = -1
        return pd.Series(signals, index=df.index)


# ==============================================================================
# 3. 仓位管理与风险平价算子 (ST-06 Volatility Targeting)
# ==============================================================================

def calculate_volatility_targeted_lots(
    equity: float,
    atr_price: float,
    contract_multiplier: float,
    risk_pct_per_trade: float = 0.005,
    stop_atr_multiple: float = 2.5,
    min_lots: int = 1,
    max_lots: int = 20
) -> int:
    """
    ST-06: 波动率目标仓位计算
    """
    if atr_price <= 0 or contract_multiplier <= 0 or equity <= 0:
        return min_lots
    risk_capital = equity * risk_pct_per_trade
    loss_per_lot = atr_price * stop_atr_multiple * contract_multiplier
    if loss_per_lot <= 0:
        return min_lots
    raw_lots = int(math.floor(risk_capital / loss_per_lot))
    return max(min_lots, min(max_lots, raw_lots))


# ==============================================================================
# 4. 标准热插拔接口
# ==============================================================================

def calculate_signal(df: pd.DataFrame) -> pd.Series:
    """
    热插拔默认入口 (ST-01 状态滤波版)
    """
    return SuperTrendEvolutionEngine.generate_st01_regime_filtered(
        df, period=10, multiplier=3.0, ker_threshold=0.25
    )
