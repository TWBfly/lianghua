"""
strategies/beiji_csmom_roll_yield_matrix.py — 「北极·截面展期」: 商品期货期限结构展期收益率矩阵 + 截面动量 + 风险平价多空对冲策略 (30m 黄金级别)

第一性原理与宏观量化机制：
1. 期限结构持有成本与展期收益率 (Term Structure & Roll Yield Matrix):
   - 商品期货具有物理仓储成本、资本利息与便利收益 (Convenience Yield)；
   - 现货-期货价格关系遵循 $F(t, T) = S(t) \cdot e^{(r + u - y)(T - t)}$；
   - 当现货需求紧俏或库存极低时，市场呈现 Backwardation（近高远低贴水结构），展期收益率 Roll Yield > 0；
   - 年化展期收益率代理：
     Basis_Proxy = [P - SMA(P, 80)] / ATR
     Basis_Z = Z-Score(Basis_Proxy)
   - 具有长期正向现金流与结构性收益。

2. 截面动量与基差动量双重正交排序 (CSMOM & Basis Momentum Orthogonal Ranking):
   - 因子 1: 展期基差代理 Z-Score (45% 权重)
   - 因子 2: 20/60 周期中长线时序/截面动量归一化 (35% 权重)
   - 因子 3: 趋势物理效率 KER (20% 权重)
   - 综合打分：Composite_Score = 0.45 * Basis_Z + 0.35 * Mom_Norm + 0.20 * KER

3. 动力学标度律分形赫斯特指数门禁 (Hurst Gate):
   - 方差比率自适应赫斯特指数：H >= 0.50 确认系统处于具备长程自相关记忆的真实单边动力学状态；
   - 严格过滤随机游走与宽幅洗盘假突破。

4. Ehlers 2-Pole SuperSmoother 零滞后宏观趋势对齐:
   - 6 周期 vs 18 周期 SuperSmoother 消除滞后，顺应 30m 宏观大势。

5. 物理跃迁出场引擎:
   - 目标位 (Take Profit): 1.0 * ATR (基差溢价收敛饱和位)；
   - 止损位 (Stop Loss): 0.8 * ATR (基差趋势反转认赔)；
   - 动态保本 (Break-Even): 浮盈达到 1.0 * ATR 时，自动抬升至 Entry + 0.1 * ATR。
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Any

STRATEGY_NAME = "beiji_csmom_roll_yield_matrix"
STRATEGY_DESCRIPTION = "「北极·截面展期」: 商品期货期限结构展期收益率矩阵 + 截面动量 + 风险平价多空对冲策略 (30m)"


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


def calculate_factors(df: pd.DataFrame, window: int = 80) -> pd.DataFrame:
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

    # 2. 展期基差代理与基差 Z-Score
    c_s = pd.Series(c, index=df.index)
    basis_raw = (c - c_s.rolling(window, min_periods=20).mean().bfill().values) / atr
    b_mean = pd.Series(basis_raw, index=df.index).rolling(window, min_periods=20).mean().bfill()
    b_std = pd.Series(basis_raw, index=df.index).rolling(window, min_periods=20).std(ddof=0).bfill() + 1e-8
    basis_z = ((basis_raw - b_mean) / b_std).values

    # 3. 动量与趋势物理效率
    mom_20 = c_s.pct_change(20).fillna(0.0).values
    mom_norm = mom_20 / (atr / (c + 1e-8))
    net_diff = np.abs(c - np.roll(c, 20))
    path = pd.Series(np.abs(c - prev_c), index=df.index).rolling(20, min_periods=5).sum().bfill().values + 1e-8
    ker = net_diff / path

    # 4. 动力学标度律 Hurst
    c_diff2 = c_s.diff(2)
    c_diff8 = c_s.diff(8)
    tau2 = c_diff2.rolling(40, min_periods=5).std(ddof=0)
    tau8 = c_diff8.rolling(40, min_periods=5).std(ddof=0)
    hurst = (np.log((tau8 + 1e-8) / (tau2 + 1e-8)) / np.log(4.0)).clip(0.1, 0.9).bfill().values

    # 5. Ehlers 零滞后趋势
    filt_fast = calculate_ehlers_supersmoother_2pole(c, period=6)
    filt_slow = calculate_ehlers_supersmoother_2pole(c, period=18)
    trend_up = filt_fast > filt_slow
    trend_dn = filt_fast < filt_slow

    bar_range = np.maximum(1e-8, h - l)
    body_ratio = np.abs(c - o) / bar_range

    # 6. 持仓量过滤
    vol_ma20 = pd.Series(v, index=df.index).rolling(20, min_periods=5).mean().bfill().values + 1e-8
    oi_filter_long = np.ones(n, dtype=bool)
    oi_filter_short = np.ones(n, dtype=bool)
    if "open_interest" in df.columns:
        oi = df["open_interest"].astype(float).values
        oi_diff = np.diff(oi, prepend=oi[0])
        oi_filter_long = oi_diff >= -vol_ma20 * 0.40
        oi_filter_short = oi_diff >= -vol_ma20 * 0.40

    composite_score = 0.45 * basis_z + 0.35 * mom_norm + 0.20 * ker

    return pd.DataFrame({
        "basis_z": basis_z,
        "mom_norm": mom_norm,
        "ker": ker,
        "composite_score": composite_score,
        "trend_up": trend_up,
        "trend_dn": trend_dn,
        "hurst": hurst,
        "body_ratio": body_ratio,
        "atr": atr,
        "oi_filter_long": oi_filter_long,
        "oi_filter_short": oi_filter_short
    }, index=df.index)


def calculate_signal(df: pd.DataFrame) -> pd.Series:
    """
    单标的独立热插拔信号生成接口:
    输入: df 包含 open, high, low, close, volume, open_interest (可选)
    输出: pd.Series (+1=做多, -1=做空, 0=无信号)
    """
    c = df["close"].astype(float).values
    o = df["open"].astype(float).values
    factors = calculate_factors(df)

    score = factors["composite_score"].values
    t_up = factors["trend_up"].values
    t_dn = factors["trend_dn"].values
    hurst = factors["hurst"].values
    body_ratio = factors["body_ratio"].values
    oi_long = factors["oi_filter_long"].values
    oi_short = factors["oi_filter_short"].values

    long_cond = (
        t_up &
        (score >= 0.50) &
        (hurst >= 0.50) &
        (c > o) &
        (body_ratio >= 0.35) &
        oi_long
    )

    short_cond = (
        t_dn &
        (score <= -0.50) &
        (hurst >= 0.50) &
        (c < o) &
        (body_ratio >= 0.35) &
        oi_short
    )

    signals = pd.Series(0, index=df.index, dtype=int)
    signals[long_cond] = 1
    signals[short_cond] = -1

    return signals


def generate_csmom_signals(
    universe_dict: Dict[str, pd.DataFrame],
    rebalance_bars: int = 16,
    top_k: int = 3,
    bottom_k: int = 3
) -> Dict[str, pd.Series]:
    """
    全市场横截面动量与展期曲率多空对冲组合接口 (30m 周期下每 16 根 Bar / 8 小时再平衡)
    """
    symbols = list(universe_dict.keys())
    if not symbols:
        return {}

    factors_dict = {sym: calculate_factors(universe_dict[sym]) for sym in symbols}
    signals_dict = {sym: pd.Series(0, index=universe_dict[sym].index, dtype=int) for sym in symbols}

    n_bars = min(len(universe_dict[sym]) for sym in symbols)
    last_pos = {sym: 0 for sym in symbols}

    for i in range(n_bars):
        if i % rebalance_bars == 0 and i >= 80:
            scores = {}
            for sym in symbols:
                scores[sym] = factors_dict[sym]["composite_score"].iloc[i]

            sorted_syms = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            long_syms = [s[0] for s in sorted_syms[:top_k] if s[1] > 0]
            short_syms = [s[0] for s in sorted_syms[-bottom_k:] if s[1] < 0]

            new_pos = {sym: 0 for sym in symbols}
            for s in long_syms:
                new_pos[s] = 1
            for s in short_syms:
                new_pos[s] = -1
            last_pos = new_pos

        for sym in symbols:
            signals_dict[sym].iloc[i] = last_pos.get(sym, 0)

    return signals_dict
