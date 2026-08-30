"""
strategies/tianshu_liquidity_profile_jump.py — 「天枢·量价真空」: 动态成交量分布拓扑 (VPVR) + 订单流失衡 (OFI) + Ehlers零滞后滤波 + 流动性真空极速跃迁策略 (30m 黄金级别)

第一性原理与微观物理拓扑机制：
1. 闭式成交量价格分布剖面拓扑 (Volume Profile VPVR & Liquidity Topology):
   - 市场的本质是撮合与流动性寻找。价格在高换手区 (High Volume Node, HVN) 呈现高摩擦引力吸附（振荡整理）；
   - 在低成交真空区 (Low Volume Node, LVN / Liquidity Void) 呈现阻力极小通道；
   - 纯因果计算 Volume-Weighted 价格分布与流动性密度 Vol_Density；
   - 当 Vol_Density <= 0.55 且价格突破 VAH/VAL 时，判定进入低阻力真空通道。

2. 订单流微观失衡与主力资金推动 (Order Flow Imbalance & Capital Surge):
   - 结合微观订单流失衡 (OFI Z-Score >= 0.50) 确认主动进攻资金流入；
   - 结合持仓量净增 (OI Filter) 确认机构在场未大幅离场。

3. Ehlers 2-Pole SuperSmoother 零滞后宏观趋势对齐:
   - 6 周期 vs 18 周期 SuperSmoother 零滞后滤波器，消灭传统均线 80% 的相位延迟；
   - 严格顺应 30m 宏观动力学大势。

4. 物理跃迁出场引擎 (HVN1 -> LVN -> HVN2):
   - 目标位 (Take Profit): 1.0 * ATR (对应下一个 HVN 阻力区饱和位)；
   - 止损位 (Stop Loss): 0.8 * ATR (跌破 HVN1 边缘即刻认赔)；
   - 动态保本 (Break-Even): 浮盈达到 1.0 * ATR 时，自动抬升至 Entry + 0.1 * ATR 锁胜。
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd

STRATEGY_NAME = "tianshu_liquidity_profile_jump"
STRATEGY_DESCRIPTION = "「天枢·量价真空」: 动态成交量分布拓扑 (VPVR) + 订单流失衡 (OFI) + Ehlers零滞后滤波 + 流动性真空极速跃迁策略 (30m)"


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


def calculate_factors(df: pd.DataFrame, vp_window: int = 40, ofi_th: float = 0.50) -> pd.DataFrame:
    """
    纯因果全向量化计算「天枢·量价真空跃迁」特征流
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
    atr = pd.Series(tr, index=df.index).rolling(14, min_periods=5).mean().bfill().values + 1e-8

    # 2. 闭式 Volume Profile 拓扑特征
    typical_p = (h + l + c) / 3.0
    v_s = pd.Series(v, index=df.index)
    pv_s = pd.Series(typical_p * v, index=df.index)

    roll_vol = v_s.rolling(vp_window, min_periods=5).sum().bfill().values + 1e-8
    roll_pv = pv_s.rolling(vp_window, min_periods=5).sum().bfill().values
    vwap = roll_pv / roll_vol

    p_diff_sq_v = pd.Series((typical_p - vwap) ** 2 * v, index=df.index).rolling(vp_window, min_periods=5).sum().bfill().values
    vw_std = np.sqrt(np.maximum(1e-8, p_diff_sq_v / roll_vol))

    vah = vwap + 0.8 * vw_std
    val = vwap - 0.8 * vw_std
    vol_density = np.exp(- ((c - vwap) ** 2) / (2.0 * (vw_std ** 2) + 1e-8))

    # 3. 订单流微观失衡 (OFI Z-Score)
    bar_range = np.maximum(1e-8, h - l)
    ofi_raw = v * ((c - l) - (h - c)) / bar_range
    ofi_s = pd.Series(ofi_raw, index=df.index)
    ofi_smooth = ofi_s.rolling(3, min_periods=1).mean()
    ofi_mean = ofi_s.rolling(vp_window, min_periods=10).mean().bfill()
    ofi_std = ofi_s.rolling(vp_window, min_periods=10).std(ddof=0).bfill() + 1e-8
    ofi_z = ((ofi_smooth - ofi_mean) / ofi_std).values

    # 4. Ehlers 2-Pole SuperSmoother 零滞后宏观趋势
    filt_fast = calculate_ehlers_supersmoother_2pole(c, period=6)
    filt_slow = calculate_ehlers_supersmoother_2pole(c, period=18)
    trend_up = filt_fast > filt_slow
    trend_dn = filt_fast < filt_slow

    # 5. 持仓量过滤
    oi_filter_long = np.ones(n, dtype=bool)
    oi_filter_short = np.ones(n, dtype=bool)
    if "open_interest" in df.columns:
        oi = df["open_interest"].astype(float).values
        oi_diff = np.diff(oi, prepend=oi[0])
        vol_ma20 = pd.Series(v, index=df.index).rolling(20, min_periods=5).mean().bfill().values + 1e-8
        oi_filter_long = oi_diff >= -vol_ma20 * 0.40
        oi_filter_short = oi_diff >= -vol_ma20 * 0.40

    return pd.DataFrame({
        "vwap": vwap,
        "vah": vah,
        "val": val,
        "vol_density": vol_density,
        "ofi_z": ofi_z,
        "trend_up": trend_up,
        "trend_dn": trend_dn,
        "atr": atr,
        "oi_filter_long": oi_filter_long,
        "oi_filter_short": oi_filter_short
    }, index=df.index)


def calculate_signal(df: pd.DataFrame) -> pd.Series:
    """
    标准热插拔信号生成接口:
    输入: df 包含 open, high, low, close, volume, open_interest (可选)
    输出: pd.Series (+1=做多, -1=做空, 0=无信号)
    """
    c = df["close"].astype(float).values
    o = df["open"].astype(float).values
    factors = calculate_factors(df)

    vah = factors["vah"].values
    val = factors["val"].values
    vol_density = factors["vol_density"].values
    ofi_z = factors["ofi_z"].values
    t_up = factors["trend_up"].values
    t_dn = factors["trend_dn"].values
    oi_long = factors["oi_filter_long"].values
    oi_short = factors["oi_filter_short"].values

    long_cond = (
        t_up &
        (c > vah) &
        (vol_density <= 0.55) &
        (ofi_z >= 0.50) &
        (c > o) &
        oi_long
    )

    short_cond = (
        t_dn &
        (c < val) &
        (vol_density <= 0.55) &
        (ofi_z <= -0.50) &
        (c < o) &
        oi_short
    )

    signals = pd.Series(0, index=df.index, dtype=int)
    signals[long_cond] = 1
    signals[short_cond] = -1

    return signals
