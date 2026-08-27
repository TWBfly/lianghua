"""
strategies/guiyuan_zscore_reversion.py — 「归元·极值」: 极值 Z-Score 偏离 + Pin Bar 做市商吸收 + 筹码衰竭均值反转策略

核心微观量化机制：
1. 极值偏离度 (Z-Score & Extreme Oscillator):
   - 20 周期标准差偏离度 |Z| >= 2.0 结合 2 周期 Connors RSI 极度超卖 (<=12) / 超买 (>=88)；
2. 做市商微观流动性吸收 (Pin Bar Absorption Geometry):
   - 要求出现探底长下影线阳线或冲顶长上影线阴线，证明流动性被吸收与反向防守动作确立；
3. 筹码衰竭与防逆势接飞刀 (Open Interest Unwinding Filter):
   - 极值偏离时，持仓量无爆发性单向暴增（剔除对手盘凶猛逼仓行情的逆势接飞刀风险）；
4. 严格防未来函数：所有指标均为当前 Bar 完结时纯因果计算。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

STRATEGY_NAME = "guiyuan_zscore_reversion"
STRATEGY_DESCRIPTION = "「归元·极值」: 极值 Z-Score 偏离 + Pin Bar 做市商吸收 + 筹码衰竭均值反转策略"


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

    # 1. 20 周期 SMA 与 Z-Score
    sma_20 = c.rolling(20).mean()
    std_20 = c.rolling(20).std(ddof=0) + 1e-8
    zscore = (c - sma_20) / std_20

    # 2. 2 周期 Connors RSI (极高灵敏度超买超卖)
    delta = c.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.rolling(2).mean()
    avg_loss = loss.rolling(2).mean() + 1e-8
    rs = avg_gain / avg_loss
    rsi_2 = 100.0 - (100.0 / (1.0 + rs))

    # 3. 5 周期快速均线 (均值回归第一目标)
    sma_5 = c.rolling(5).mean()

    # 4. K 线微观吸收形态 (Pin Bar Absorption)
    body = (c - o).abs() + 1e-8
    lower_shadow = np.where(c >= o, o - l, c - l)
    upper_shadow = np.where(c >= o, h - c, h - o)

    # 阳线探底拒斥形态
    bullish_reversal = (c > o) & (c > c.shift(1)) & (lower_shadow >= body * 0.5)
    # 阴线冲顶滞涨形态
    bearish_reversal = (c < o) & (c < c.shift(1)) & (upper_shadow >= body * 0.5)

    # 5. 期货持仓量筹码背离过滤
    oi_filter_long = pd.Series(True, index=df.index)
    oi_filter_short = pd.Series(True, index=df.index)
    if "open_interest" in df.columns:
        oi_diff = df["open_interest"].diff().fillna(0)
        vol_ma = v.rolling(20).mean().fillna(1.0)
        # 极度超卖时，排除持仓暴增的强力主动开空砸盘
        oi_filter_long = oi_diff <= vol_ma * 0.4
        # 极度超买时，排除持仓暴增的强力主动开多逼仓
        oi_filter_short = oi_diff <= vol_ma * 0.4

    # 6. 均值回归反转信号触发
    long_candidate = (
        (zscore <= -2.0) &
        (rsi_2 <= 12.0) &
        bullish_reversal &
        (c < sma_5) &
        oi_filter_long
    )

    short_candidate = (
        (zscore >= 2.0) &
        (rsi_2 >= 88.0) &
        bearish_reversal &
        (c > sma_5) &
        oi_filter_short
    )

    signals = pd.Series(0, index=df.index)
    signals[long_candidate] = 1
    signals[short_candidate] = -1

    return signals
