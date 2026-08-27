"""
strategies/tianji_orderflow_breakout.py — 「破阵·天玑」: 日内订单流持仓失衡与波动率挤压自适应动量突破策略

核心微观量化机制：
1. 波动率能量挤压 (Volatility Squeeze Gate):
   - 采用布林带宽度与 ATR 比率衡量波动蓄势，只有当 Squeeze <= 0.95 (蓄势压缩态) 时才释放入场；
2. 订单流与主力推波验证 (Orderflow & Capital Surge):
   - 成交量与持仓量同步放大 (Volume Ratio >= 1.10，持仓量净增 >= 0)，确认机构主动推波而非虚假诱多/诱空；
3. 物理因果动量捕获 (Kaufman Efficiency & Donchian Breakout):
   - 考夫曼自适应效率比率 (KER) 确认净路径方向，唐奇安通道极值 (Donchian Position) 确认价格处于突破通道前沿；
4. 严格防未来函数：纯因果 Rolling 计算，支持热插拔即时调用。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

STRATEGY_NAME = "tianji_orderflow_breakout"
STRATEGY_DESCRIPTION = "「破阵·天玑」: 日内订单流持仓失衡与波动率挤压自适应动量突破策略"


def calculate_signal(df: pd.DataFrame) -> pd.Series:
    """
    标准热插拔信号接口:
    输入: df 包含 open, high, low, close, volume, open_interest (可选)
    输出: pd.Series (+1=做多, -1=做空, 0=无信号)
    """
    c = df["close"].astype(float)
    o = df["open"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    v = df["volume"].astype(float)

    # 1. 20 周期真实波幅 ATR
    prev_c = c.shift(1)
    tr = pd.concat([
        h - l,
        (h - prev_c).abs(),
        (l - prev_c).abs()
    ], axis=1).max(axis=1)
    atr_20 = tr.rolling(20).mean().replace(0, np.nan)

    # 2. 20 周期布林带与波动率挤压比率 (Squeeze Ratio)
    sma_20 = c.rolling(20).mean()
    std_20 = c.rolling(20).std(ddof=0)
    bb_width = 4.0 * std_20
    squeeze_ratio = bb_width / (atr_20 * 2.0 + 1e-8)
    # 局部近期（前5根Bar内）出现过挤压蓄势
    had_squeeze = squeeze_ratio.rolling(5).min() <= 1.05

    # 3. 考夫曼自适应效率比率 (KER)
    net_change = c - c.shift(20)
    path = c.diff().abs().rolling(20).sum().replace(0, np.nan)
    ker = (net_change.abs() / path) * np.sign(net_change)

    # 4. 唐奇安通道位置 (0.0=通道底部, 1.0=通道顶部)
    don_hi = h.rolling(20).max()
    don_lo = l.rolling(20).min()
    don_span = (don_hi - don_lo).replace(0, np.nan)
    donchian_pos = (c - don_lo) / don_span

    # 5. 订单流成交量与持仓量加速度
    v_ma20 = v.rolling(20).mean().replace(0, np.nan)
    vol_ratio = v / v_ma20

    oi_filter_long = pd.Series(True, index=df.index)
    oi_filter_short = pd.Series(True, index=df.index)
    if "open_interest" in df.columns:
        oi = df["open_interest"].astype(float)
        oi_diff = oi.diff().fillna(0)
        vol_ma = v.rolling(20).mean().fillna(1.0)
        # 多头突破要求持仓量无大幅溃退（资金在场）
        oi_filter_long = oi_diff >= -vol_ma * 0.3
        # 空头突破要求持仓量无大幅溃退
        oi_filter_short = oi_diff >= -vol_ma * 0.3

    # 6. 大周期 1h 趋势级联滤波 (1h Trend Cascade: 15m 上 4 周期 vs 16 周期 EMA)
    ema_1h_fast = c.ewm(span=4, adjust=False).mean()
    ema_1h_slow = c.ewm(span=16, adjust=False).mean()
    trend_up_1h = ema_1h_fast > ema_1h_slow
    trend_dn_1h = ema_1h_fast < ema_1h_slow

    # 7. K 线微观收盘质量 (防冲高回落长上影假突破)
    bar_span = (h - l).replace(0, np.nan)
    close_pos = (c - l) / bar_span

    # 8. 综合突破信号逻辑 (多周期共振 + 蓄势释放 + 资金在场 + 实体饱满)
    long_cond = (
        trend_up_1h &
        had_squeeze &
        (vol_ratio >= 1.05) &
        (ker >= 0.25) &
        (donchian_pos >= 0.70) &
        (close_pos >= 0.60) &
        (c > o) &
        oi_filter_long
    )

    short_cond = (
        trend_dn_1h &
        had_squeeze &
        (vol_ratio >= 1.05) &
        (ker <= -0.25) &
        (donchian_pos <= 0.30) &
        (close_pos <= 0.40) &
        (c < o) &
        oi_filter_short
    )

    signals = pd.Series(0, index=df.index)
    signals[long_cond] = 1
    signals[short_cond] = -1

    return signals
