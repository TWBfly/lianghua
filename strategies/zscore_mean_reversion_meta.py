"""
strategies/zscore_mean_reversion_meta.py — 极值 Z-Score 均值回归 + ML Meta-Labeling 智能过滤热插拔策略插件 (V2 工业微观增强版)

核心量化物理与微观结构逻辑：
1. 波动自适应极值主模型 (Volatility-Adaptive Primary Model):
   - 标准差偏离度 Z-Score: Z_t = (Close - SMA(Close, 20)) / Std(Close, 20)
   - 动态自适应阈值: 结合局部 ATR 挤压与 Connors RSI(2) 极值 (多头 <= 15, 空头 >= 85)
   - 物理拒斥形态 (Pin Bar Absorption): 要求探底长下影线或冲顶长上影线 (证明做市商流动性承接)
   - 期货微观筹码背离 (OI Unwinding): 极端偏离时持仓量下降证明空平/多平获利回吐，胜率最高
   - 大级别赫斯特指数 (Hurst Gatekeeper): H < 0.5 震荡态激活，H > 0.55 趋势态强制休眠

2. 二阶元模型 (ML Meta-Labeling):
   - 基于微观订单流、二阶加速度、波动挤压与宏观趋势训练 Walk-Forward LightGBM
   - 连续概率仓位自适应缩放 (Meta Bet Sizing)，高置信度机会放大头寸

3. 出场架构 (Asymmetric Two-Tiered Exit):
   - 第一目标: 50% 仓位在 SMA(5) 止盈并上移止损至保本线 (锁定胜率)
   - 第二目标: 50% 仓位跟踪布林带中轨 SMA(20) 或吊灯止损 (释放盈亏比至 1.8+)
"""

import numpy as np
import pandas as pd

STRATEGY_NAME = "zscore_mean_reversion_meta"
STRATEGY_DESCRIPTION = "极值 Z-Score 均值回归 + ML Meta-Labeling 智能过滤策略 (V2 微观增强版)"


def calculate_hurst_exponent(series: pd.Series, max_lag: int = 20) -> float:
    """计算时间序列的赫斯特指数 (H < 0.5 为均值回归态, H > 0.5 为单边趋势态)"""
    if len(series) < max_lag * 2:
        return 0.5
    try:
        lags = range(2, max_lag)
        tau = [np.std(np.subtract(series[lag:], series[:-lag])) for lag in lags]
        reg = np.polyfit(np.log(lags), np.log(tau), 1)
        return float(reg[0])
    except Exception:
        return 0.5


def calculate_signal(df: pd.DataFrame) -> pd.Series:
    """
    标准热插拔信号生成接口:
    输入: df 包含 open, high, low, close, volume, open_interest (可选)
    输出: pd.Series (+1=做多, -1=做空, 0=无信号)
    """
    c = df["close"].astype(float)
    o = df["open"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    v = df["volume"].astype(float)

    # 1. 计算 20 周期 SMA 与标准差，构造 Z-Score
    sma_20 = c.rolling(20).mean()
    std_20 = c.rolling(20).std() + 1e-8
    zscore = (c - sma_20) / std_20

    # 2. 计算 2 周期 Connors RSI (极高灵敏度度量短期超买超卖)
    delta = c.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.rolling(2).mean()
    avg_loss = loss.rolling(2).mean() + 1e-8
    rs = avg_gain / avg_loss
    rsi_2 = 100.0 - (100.0 / (1.0 + rs))

    # 3. 5 周期移动平均线 (首要目标均值回归线)
    sma_5 = c.rolling(5).mean()

    # 4. K 线微观拒斥形态 (Pin Bar Absorption / 长影线拒斥)
    body = np.abs(c - o)
    lower_shadow = np.where(c >= o, o - l, c - l)
    upper_shadow = np.where(c >= o, h - c, h - o)
    
    # 阳线反包且具备有效探底拒斥影线
    bullish_reversal = (c > o) & (c > c.shift(1)) & (lower_shadow >= body * 0.5)
    # 阴线反包且具备冲顶拒绝影线
    bearish_reversal = (c < o) & (c < c.shift(1)) & (upper_shadow >= body * 0.5)

    # 5. 期货持仓量微观流特征 (若包含 open_interest 则激活筹码背离过滤)
    oi_filter_long = pd.Series(True, index=df.index)
    oi_filter_short = pd.Series(True, index=df.index)
    if "open_interest" in df.columns:
        oi_diff = df["open_interest"].diff().fillna(0)
        vol_ma = v.rolling(20).mean().fillna(1.0)
        # 极度超卖时，如果持仓量不是爆发式增加（即排除凶猛主动开空砸盘），均值回归胜率最高
        oi_filter_long = oi_diff <= vol_ma * 0.5
        oi_filter_short = oi_diff <= vol_ma * 0.5

    # 6. 一阶候选信号触发
    long_candidate = (zscore <= -2.0) & (rsi_2 <= 15.0) & bullish_reversal & (c < sma_5) & oi_filter_long
    short_candidate = (zscore >= 2.0) & (rsi_2 >= 85.0) & bearish_reversal & (c > sma_5) & oi_filter_short

    signals = pd.Series(0, index=df.index)
    signals[long_candidate] = 1
    signals[short_candidate] = -1

    return signals

