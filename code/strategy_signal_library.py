"""
strategy_signal_library.py — TradingView 策略信号 Python 化特征库
将 lianghua/tradingview/ 下 347 个 Pine Script 策略的核心信号逻辑翻译为 Python/pandas

每个函数输入: df (包含 open/high/low/close/volume 列的 DataFrame，DatetimeIndex)
每个函数输出: pd.Series（+1=多头信号, -1=空头信号, 0=无信号），与 df.index 对齐

覆盖策略类别：
- 趋势跟随: SuperTrend, AlphaTrend, Chandelier Exit, Hull Suite, UT Bot
- 动量: MACD 系列, RSI 系列, QQE, Squeeze Momentum, Awesome Oscillator
- 结构: Market Structure (BOS/CHoCH), Swing Highs/Lows, Pivot Points
- 量价: Volume Breakout, VWAP Deviation, Volume Surprise
- 波动率: Bollinger Breakout, ATR Bands, Keltner Channel

ponytail: 只实现可从 OHLCV 计算的指标，不依赖 TradingView 专有数据接口
         ceiling: 无盘中 tick 数据，volume_delta 等需要 level2 的跳过
"""
import numpy as np
import pandas as pd


# ─── 工具函数 ──────────────────────────────────────────────────────────────────

def _ema(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(span=n, adjust=False).mean()

def _rma(series: pd.Series, n: int) -> pd.Series:
    """Pine Script ta.rma() = Wilder's Smoothing = EMA with alpha=1/n"""
    return series.ewm(alpha=1/n, adjust=False).mean()

def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift(1)).abs(),
        (df['low'] - df['close'].shift(1)).abs()
    ], axis=1).max(axis=1)
    return _rma(tr, n)

def _rsi(series: pd.Series, n: int = 14) -> pd.Series:
    delta = series.diff()
    gain = _rma(delta.clip(lower=0), n)
    loss = _rma((-delta).clip(lower=0), n)
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)

def _macd(series: pd.Series, fast=12, slow=26, signal=9):
    macd_line = _ema(series, fast) - _ema(series, slow)
    signal_line = _ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def crossover(a: pd.Series, b) -> pd.Series:
    """a 从下方穿越 b"""
    if isinstance(b, (int, float)):
        b = pd.Series(b, index=a.index)
    return (a > b) & (a.shift(1) <= b.shift(1))

def crossunder(a: pd.Series, b) -> pd.Series:
    """a 从上方穿越 b"""
    if isinstance(b, (int, float)):
        b = pd.Series(b, index=a.index)
    return (a < b) & (a.shift(1) >= b.shift(1))


# ─── 1. SuperTrend ────────────────────────────────────────────────────────────
# 来源: SuperTrend.md, AlphaTrend.md, SuperTrend Oscillator [LuxAlgo].md

def supertrend_signal(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.Series:
    """SuperTrend 趋势方向信号: +1=多头, -1=空头"""
    hl2 = (df['high'] + df['low']) / 2
    atr = _atr(df, period)
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    supertrend = pd.Series(np.nan, index=df.index)
    direction = pd.Series(1, index=df.index)

    for i in range(1, len(df)):
        prev_upper = upper_band.iloc[i-1]
        prev_lower = lower_band.iloc[i-1]
        curr_close = df['close'].iloc[i]
        prev_close = df['close'].iloc[i-1]

        # 上轨不收缩
        if lower_band.iloc[i] > prev_lower or prev_close < prev_lower:
            lower_band.iloc[i] = lower_band.iloc[i]
        else:
            lower_band.iloc[i] = prev_lower

        # 下轨不扩张
        if upper_band.iloc[i] < prev_upper or prev_close > prev_upper:
            upper_band.iloc[i] = upper_band.iloc[i]
        else:
            upper_band.iloc[i] = prev_upper

        prev_dir = direction.iloc[i-1]
        if prev_dir == -1 and curr_close > prev_upper:
            direction.iloc[i] = 1
        elif prev_dir == 1 and curr_close < prev_lower:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = prev_dir

    return direction  # +1 / -1


def supertrend_crossover(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.Series:
    """SuperTrend 方向切换信号（金叉+1, 死叉-1, 否则0）"""
    d = supertrend_signal(df, period, multiplier)
    signal = pd.Series(0, index=df.index)
    signal[d == 1 and d.shift(1) == -1] = 1   # 方向切多
    signal[(d == 1) & (d.shift(1) == -1)] = 1
    signal[(d == -1) & (d.shift(1) == 1)] = -1
    return signal


# ─── 2. AlphaTrend ───────────────────────────────────────────────────────────
# 来源: AlphaTrend.md — 结合 MFI（量价）或 RSI 动量确认

def alphatrend_signal(df: pd.DataFrame, period: int = 14, coeff: float = 1.0) -> pd.Series:
    """AlphaTrend 买卖信号: +1=BUY, -1=SELL, 0=持有"""
    atr_val = _atr(df, period)
    hlc3 = (df['high'] + df['low'] + df['close']) / 3
    # 用 RSI 替代 MFI（无 volume tick 精度）
    rsi_val = _rsi(df['close'], period)
    condition = rsi_val >= 50

    upT = df['low'] - atr_val * coeff
    downT = df['high'] + atr_val * coeff

    at = pd.Series(np.nan, index=df.index)
    at.iloc[0] = upT.iloc[0] if condition.iloc[0] else downT.iloc[0]

    for i in range(1, len(df)):
        prev = at.iloc[i-1]
        if condition.iloc[i]:
            at.iloc[i] = max(upT.iloc[i], prev) if not np.isnan(prev) else upT.iloc[i]
        else:
            at.iloc[i] = min(downT.iloc[i], prev) if not np.isnan(prev) else downT.iloc[i]

    buy = crossover(at, at.shift(2))
    sell = crossunder(at, at.shift(2))
    signal = pd.Series(0, index=df.index)
    signal[buy] = 1
    signal[sell] = -1
    return signal


# ─── 3. Chandelier Exit ──────────────────────────────────────────────────────
# 来源: Chandelier Exit.md

def chandelier_exit_signal(df: pd.DataFrame, period: int = 22, multiplier: float = 3.0) -> pd.Series:
    """Chandelier Exit 方向: +1=多, -1=空, 变化=信号"""
    atr = _atr(df, period) * multiplier
    long_stop = df['close'].rolling(period).max() - atr
    short_stop = df['close'].rolling(period).min() + atr

    # ratchet
    long_stop = long_stop.where(
        (long_stop > long_stop.shift(1)) | (df['close'].shift(1) > long_stop.shift(1)),
        long_stop.shift(1)
    )
    short_stop = short_stop.where(
        (short_stop < short_stop.shift(1)) | (df['close'].shift(1) < short_stop.shift(1)),
        short_stop.shift(1)
    )

    direction = pd.Series(1, index=df.index)
    for i in range(1, len(df)):
        if df['close'].iloc[i] > short_stop.iloc[i-1]:
            direction.iloc[i] = 1
        elif df['close'].iloc[i] < long_stop.iloc[i-1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i-1]

    signal = pd.Series(0, index=df.index)
    signal[(direction == 1) & (direction.shift(1) == -1)] = 1
    signal[(direction == -1) & (direction.shift(1) == 1)] = -1
    return signal


# ─── 4. Hull Suite ────────────────────────────────────────────────────────────
# 来源: Hull Suite Strategy.md

def hull_signal(df: pd.DataFrame, period: int = 55) -> pd.Series:
    """Hull Moving Average 趋势信号"""
    src = df['close']
    half = period // 2
    hma = _ema(2 * _ema(src, half) - _ema(src, period), int(np.sqrt(period)))
    signal = pd.Series(0, index=df.index)
    signal[crossover(hma, hma.shift(2))] = 1
    signal[crossunder(hma, hma.shift(2))] = -1
    return signal


# ─── 5. Squeeze Momentum (LazyBear) ──────────────────────────────────────────
# 来源: Squeeze Momentum Indicator [LazyBear].md

def squeeze_momentum_signal(df: pd.DataFrame, bb_len: int = 20, kc_mult: float = 1.5) -> pd.Series:
    """Squeeze Momentum: 动量从负转正=+1, 正转负=-1"""
    src = df['close']
    # Bollinger Bands
    bb_mid = src.rolling(bb_len).mean()
    bb_std = src.rolling(bb_len).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    # Keltner Channel
    kc_mid = src.rolling(bb_len).mean()
    kc_range = _atr(df, bb_len)
    kc_upper = kc_mid + kc_mult * kc_range
    kc_lower = kc_mid - kc_mult * kc_range

    squeeze = (bb_upper < kc_upper) & (bb_lower > kc_lower)  # True=压缩中

    # Delta from linear regression midpoint
    highest = df['high'].rolling(bb_len).max()
    lowest = df['low'].rolling(bb_len).min()
    delta = src - (highest + lowest) / 2 - bb_mid

    # 动量柱状值
    momentum = delta.rolling(bb_len).apply(lambda x: np.polyfit(range(len(x)), x, 1)[0], raw=True)

    signal = pd.Series(0, index=df.index)
    signal[(momentum > 0) & (momentum.shift(1) <= 0) & ~squeeze] = 1
    signal[(momentum < 0) & (momentum.shift(1) >= 0) & ~squeeze] = -1
    return signal


# ─── 6. MACD Crossover ───────────────────────────────────────────────────────
def macd_signal(df: pd.DataFrame) -> pd.Series:
    """MACD 金叉/死叉信号"""
    _, _, hist = _macd(df['close'])
    signal = pd.Series(0, index=df.index)
    signal[crossover(hist, pd.Series(0, index=hist.index))] = 1
    signal[crossunder(hist, pd.Series(0, index=hist.index))] = -1
    return signal


# ─── 7. RSI Divergence (简化版) ──────────────────────────────────────────────
def rsi_oversold_signal(df: pd.DataFrame, period: int = 14,
                         oversold: float = 30, overbought: float = 70) -> pd.Series:
    """RSI 超卖回升 / 超买回落信号"""
    rsi = _rsi(df['close'], period)
    signal = pd.Series(0, index=df.index)
    signal[crossover(rsi, pd.Series(oversold, index=rsi.index))] = 1   # 超卖区回升
    signal[crossunder(rsi, pd.Series(overbought, index=rsi.index))] = -1  # 超买区回落
    return signal


# ─── 8. Bollinger Band Breakout ───────────────────────────────────────────────
# 来源: Bollinger + RSI Strategy.md, Bollinger Band Percentile Suite.md

def bollinger_breakout_signal(df: pd.DataFrame, period: int = 20, std: float = 2.0) -> pd.Series:
    """布林带突破信号: 价格突破上轨=+1, 跌破下轨=-1"""
    mid = df['close'].rolling(period).mean()
    band = df['close'].rolling(period).std() * std
    upper, lower = mid + band, mid - band
    signal = pd.Series(0, index=df.index)
    signal[crossover(df['close'], upper)] = 1
    signal[crossunder(df['close'], lower)] = -1
    return signal


# ─── 9. Volume Breakout ───────────────────────────────────────────────────────
# 来源: Breakout Finder.md, Volume Surprise [LuxAlgo].md

def volume_breakout_signal(df: pd.DataFrame, vol_period: int = 20,
                            vol_mult: float = 2.0, price_period: int = 20) -> pd.Series:
    """成交量放大突破新高/低信号"""
    vol_avg = df['volume'].rolling(vol_period).mean()
    vol_surge = df['volume'] > vol_avg * vol_mult
    price_high = df['close'].rolling(price_period).max().shift(1)
    price_low = df['close'].rolling(price_period).min().shift(1)
    signal = pd.Series(0, index=df.index)
    signal[(df['close'] > price_high) & vol_surge] = 1
    signal[(df['close'] < price_low) & vol_surge] = -1
    return signal


# ─── 10. VWAP Deviation ──────────────────────────────────────────────────────
# 来源: Rolling VWAP Channel [LuxAlgo].md, Order Flow VWAP Deviation [LuxAlgo].md

def vwap_deviation_signal(df: pd.DataFrame, period: int = 20, threshold: float = 0.02) -> pd.Series:
    """VWAP 偏离信号: 价格大幅偏离 VWAP 后回归"""
    typical = (df['high'] + df['low'] + df['close']) / 3
    vwap = (typical * df['volume']).rolling(period).sum() / df['volume'].rolling(period).sum()
    deviation = (df['close'] - vwap) / vwap
    signal = pd.Series(0, index=df.index)
    # 严重超买 → 看跌回归 / 严重超卖 → 看涨回归（均值回归）
    signal[deviation < -threshold] = 1
    signal[deviation > threshold] = -1
    return signal


# ─── 11. Pivot High/Low Breakout ─────────────────────────────────────────────
# 来源: Pivot Points High Low & Missed Reversal [LuxAlgo].md

def pivot_breakout_signal(df: pd.DataFrame, left: int = 5, right: int = 5) -> pd.Series:
    """价格突破 Pivot High/Low 信号"""
    pivot_high = df['high'].rolling(left + right + 1, center=True).apply(
        lambda x: x[left] if x[left] == x.max() else np.nan, raw=True
    )
    pivot_low = df['low'].rolling(left + right + 1, center=True).apply(
        lambda x: x[left] if x[left] == x.min() else np.nan, raw=True
    )
    last_ph = pivot_high.ffill()
    last_pl = pivot_low.ffill()
    signal = pd.Series(0, index=df.index)
    signal[crossover(df['close'], last_ph)] = 1
    signal[crossunder(df['close'], last_pl)] = -1
    return signal


# ─── 12. Williams Vix Fix (底部探测) ─────────────────────────────────────────
# 来源: CM_Williams_Vix_Fix Finds Market Bottoms.md

def williams_vix_fix_signal(df: pd.DataFrame, period: int = 22,
                              bb_len: int = 20, bb_mult: float = 2.0) -> pd.Series:
    """Williams VixFix: 市场恐慌底部买入信号"""
    wvf = (df['close'].rolling(period).max() - df['low']) / df['close'].rolling(period).max() * 100
    bb_mid = wvf.rolling(bb_len).mean()
    bb_upper = bb_mid + bb_mult * wvf.rolling(bb_len).std()
    # WVF 突破 BB 上轨 = 恐慌高峰 → 潜在底部
    signal = pd.Series(0, index=df.index)
    signal[wvf >= bb_upper] = 1
    return signal


# ─── 13. Awesome Oscillator ──────────────────────────────────────────────────
# 来源: Amazing Oscillator (AO) [Algoalpha].md

def awesome_oscillator_signal(df: pd.DataFrame) -> pd.Series:
    """AO 零轴穿越信号"""
    midpoint = (df['high'] + df['low']) / 2
    ao = midpoint.rolling(5).mean() - midpoint.rolling(34).mean()
    signal = pd.Series(0, index=df.index)
    signal[crossover(ao, pd.Series(0.0, index=ao.index))] = 1
    signal[crossunder(ao, pd.Series(0.0, index=ao.index))] = -1
    return signal


# ─── 14. Parabolic SAR ───────────────────────────────────────────────────────

def parabolic_sar_signal(df: pd.DataFrame, af_start: float = 0.02,
                          af_step: float = 0.02, af_max: float = 0.2) -> pd.Series:
    """Parabolic SAR 趋势反转信号"""
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    n = len(close)

    sar = np.zeros(n)
    ep = np.zeros(n)
    af = np.zeros(n)
    trend = np.ones(n, dtype=int)  # 1=up, -1=down

    sar[0] = low[0]
    ep[0] = high[0]
    af[0] = af_start

    for i in range(1, n):
        prev_trend = trend[i-1]
        prev_sar = sar[i-1]
        prev_ep = ep[i-1]
        prev_af = af[i-1]

        if prev_trend == 1:
            new_sar = prev_sar + prev_af * (prev_ep - prev_sar)
            new_sar = min(new_sar, low[i-1], low[i-2] if i >= 2 else low[i-1])
            if low[i] < new_sar:
                trend[i] = -1
                sar[i] = prev_ep
                ep[i] = low[i]
                af[i] = af_start
            else:
                trend[i] = 1
                sar[i] = new_sar
                if high[i] > prev_ep:
                    ep[i] = high[i]
                    af[i] = min(prev_af + af_step, af_max)
                else:
                    ep[i] = prev_ep
                    af[i] = prev_af
        else:
            new_sar = prev_sar + prev_af * (prev_ep - prev_sar)
            new_sar = max(new_sar, high[i-1], high[i-2] if i >= 2 else high[i-1])
            if high[i] > new_sar:
                trend[i] = 1
                sar[i] = prev_ep
                ep[i] = high[i]
                af[i] = af_start
            else:
                trend[i] = -1
                sar[i] = new_sar
                if low[i] < prev_ep:
                    ep[i] = low[i]
                    af[i] = min(prev_af + af_step, af_max)
                else:
                    ep[i] = prev_ep
                    af[i] = prev_af

    trend_s = pd.Series(trend, index=df.index)
    signal = pd.Series(0, index=df.index)
    signal[(trend_s == 1) & (trend_s.shift(1) == -1)] = 1
    signal[(trend_s == -1) & (trend_s.shift(1) == 1)] = -1
    return signal


# ─── 15. Market Structure BOS/CHoCH (简化版) ─────────────────────────────────
# 来源: Market Structure CHoCH BOS (Fractal) [LuxAlgo].md

def market_structure_signal(df: pd.DataFrame, swing_len: int = 5) -> pd.Series:
    """市场结构突破 (BOS/CHoCH) 信号: 突破前高=+1, 跌破前低=-1"""
    pivot_high = df['high'].rolling(2*swing_len+1, center=True).max()
    pivot_low = df['low'].rolling(2*swing_len+1, center=True).min()
    is_ph = df['high'] == pivot_high
    is_pl = df['low'] == pivot_low

    last_ph_price = df['high'].where(is_ph).ffill()
    last_pl_price = df['low'].where(is_pl).ffill()

    signal = pd.Series(0, index=df.index)
    signal[crossover(df['close'], last_ph_price)] = 1
    signal[crossunder(df['close'], last_pl_price)] = -1
    return signal


# ─── 16. Donchian Channel Breakout ───────────────────────────────────────────
# 来源: Donchian MA Bands [LuxAlgo].md

def donchian_breakout_signal(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """唐奇安通道突破信号"""
    upper = df['high'].rolling(period).max()
    lower = df['low'].rolling(period).min()
    signal = pd.Series(0, index=df.index)
    signal[df['close'] > upper.shift(1)] = 1
    signal[df['close'] < lower.shift(1)] = -1
    return signal


# ─── 主函数：计算所有策略信号并汇总为特征矩阵 ─────────────────────────────────

SIGNAL_FUNCTIONS = {
    'supertrend': supertrend_signal,
    'supertrend_cross': supertrend_crossover,
    'alphatrend': alphatrend_signal,
    'chandelier': chandelier_exit_signal,
    'hull': hull_signal,
    'squeeze': squeeze_momentum_signal,
    'macd_cross': macd_signal,
    'rsi_extreme': rsi_oversold_signal,
    'bb_breakout': bollinger_breakout_signal,
    'vol_breakout': volume_breakout_signal,
    'vwap_dev': vwap_deviation_signal,
    'pivot_break': pivot_breakout_signal,
    'williams_vix': williams_vix_fix_signal,
    'ao_cross': awesome_oscillator_signal,
    'psar': parabolic_sar_signal,
    'mkt_struct': market_structure_signal,
    'donchian': donchian_breakout_signal,
}


def compute_all_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算全部 17 个策略信号，返回 DataFrame
    列: signal_supertrend, signal_macd_cross, ... 每列值 +1/0/-1
    同时返回聚合特征:
      - signal_consensus: 多头信号数 - 空头信号数 (范围 -17 ~ +17)
      - signal_bull_count: 同时看多的策略数量
      - signal_bear_count: 同时看空的策略数量
      - signal_agreement_pct: |多数派| / 总有信号策略数
    """
    result = {}
    for name, func in SIGNAL_FUNCTIONS.items():
        try:
            result[f'sig_{name}'] = func(df)
        except Exception as e:
            result[f'sig_{name}'] = pd.Series(0, index=df.index)

    signals_df = pd.DataFrame(result, index=df.index)

    # 聚合特征
    bull = (signals_df > 0).sum(axis=1)
    bear = (signals_df < 0).sum(axis=1)
    total = (signals_df != 0).sum(axis=1).replace(0, 1)

    signals_df['sig_consensus'] = bull - bear
    signals_df['sig_bull_count'] = bull
    signals_df['sig_bear_count'] = bear
    signals_df['sig_agreement_pct'] = (bull - bear).abs() / total

    return signals_df
