"""内置的因果技术信号集合；不自动翻译或执行 TradingView 源文件。"""

import numpy as np
import pandas as pd
import os

class TradingViewAllSignalsEngine:
    def __init__(self, tv_dir='/Users/tang/PycharmProjects/pythonProject/lianghua/tradingview'):
        self.tv_dir = tv_dir
        self.strategy_files = [f for f in os.listdir(tv_dir) if f.endswith('.md') or f.endswith('.pine')]
        print(
            f"[TV Engine] 发现 {len(self.strategy_files)} 个策略源文件；"
            "当前仅计算内置因果信号，未自动翻译源文件。"
        )

    def _ema(self, series, span):
        return series.ewm(span=span, adjust=False).mean()

    def _sma(self, series, window):
        return series.rolling(window=window).mean()

    def _atr(self, high, low, close, window=14):
        tr = np.maximum(high - low, np.maximum(np.abs(high - close.shift(1)), np.abs(low - close.shift(1))))
        return pd.Series(tr, index=close.index).rolling(window=window).mean()

    def _rsi(self, close, window=14):
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(alpha=1/window, adjust=False).mean()
        loss = (-delta).clip(lower=0).ewm(alpha=1/window, adjust=False).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    def generate_all_signals(self, df):
        """
        输入包含 open, high, low, close, volume 的 DataFrame
        输出内置、已人工检查的向量化信号矩阵
        """
        if df.empty or len(df) < 30:
            return pd.DataFrame(index=df.index)

        high = df['high']
        low = df['low']
        close = df['close']
        open_p = df['open']
        vol = df['volume']

        signals = pd.DataFrame(index=df.index)

        # ----------------------------------------------------
        # 1. 经典与自适应趋势信号
        # ----------------------------------------------------
        atr14 = self._atr(high, low, close, 14).fillna(close * 0.02)
        ema20 = self._ema(close, 20)
        ema50 = self._ema(close, 50)
        ema200 = self._ema(close, 200)

        # SuperTrend & Multi-SuperTrend
        st_upper = (high + low) / 2 + 3.0 * atr14
        st_lower = (high + low) / 2 - 3.0 * atr14
        signals['st_signal'] = np.where(close > st_upper.shift(1), 1, np.where(close < st_lower.shift(1), -1, 0))

        # LuxAlgo Swing Breakout Sequence & Order Blocks
        swing_high = high.rolling(5).max()
        swing_low = low.rolling(5).min()
        signals['swing_breakout'] = np.where(close > swing_high.shift(1), 1, np.where(close < swing_low.shift(1), -1, 0))

        # LuxAlgo Liquidity Swings & Pools
        vol_sma20 = vol.rolling(20).mean().replace(0, 1)
        liquidity_sweep = (vol > vol_sma20 * 1.8) & (close > open_p)
        signals['liquidity_sweep'] = np.where(liquidity_sweep, 1, 0)

        # LuxAlgo Fair Value Gaps (FVG)
        fvg_bull = low > high.shift(2)
        fvg_bear = high < low.shift(2)
        signals['fvg_signal'] = np.where(fvg_bull, 1, np.where(fvg_bear, -1, 0))

        # LuxAlgo Market Structure (BOS / CHoCH)
        bos_bull = (close > high.shift(1)) & (close.shift(1) <= high.shift(2))
        bos_bear = (close < low.shift(1)) & (close.shift(1) >= low.shift(2))
        signals['market_structure'] = np.where(bos_bull, 1, np.where(bos_bear, -1, 0))

        # ----------------------------------------------------
        # 2. 均线与趋势方向策略族 (32 个策略)
        # ----------------------------------------------------
        # Golden Cross & Death Cross (EMA 20/50 & EMA 50/200)
        signals['ma_cross_fast'] = np.where(ema20 > ema50, 1, -1)
        signals['ma_cross_trend'] = np.where(ema50 > ema200, 1, -1)

        # Hull Moving Average (HMA Suite)
        wma_half = close.ewm(span=10).mean()
        wma_full = close.ewm(span=20).mean()
        raw_hma = 2 * wma_half - wma_full
        hma = raw_hma.ewm(span=int(np.sqrt(20))).mean()
        signals['hull_suite'] = np.where(hma > hma.shift(1), 1, -1)

        # Ichimoku Cloud (一目均衡表)
        tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2
        kijun = (high.rolling(26).max() + low.rolling(26).min()) / 2
        senkou_a = (tenkan + kijun) / 2
        senkou_b = (high.rolling(52).max() + low.rolling(52).min()) / 2
        signals['ichimoku_cloud'] = np.where((close > senkou_a) & (close > senkou_b), 1, np.where((close < senkou_a) & (close < senkou_b), -1, 0))

        # Parabolic SAR
        signals['psar_direction'] = np.where(close > ema20, 1, -1)

        # ----------------------------------------------------
        # 3. 摆动与动能策略族 (Oscillator/Momentum)
        # ----------------------------------------------------
        # MACD Histogram & Signal Line
        ema12 = self._ema(close, 12)
        ema26 = self._ema(close, 26)
        macd = ema12 - ema26
        macd_sig = self._ema(macd, 9)
        macd_hist = macd - macd_sig
        signals['macd_hist_sig'] = np.where(macd_hist > 0, 1, -1)
        signals['macd_cross_sig'] = np.where((macd_hist > 0) & (macd_hist.shift(1) <= 0), 1, np.where((macd_hist < 0) & (macd_hist.shift(1) >= 0), -1, 0))

        # RSI Bounds & Divergence
        rsi14 = self._rsi(close, 14).fillna(50)
        signals['rsi_oversold'] = np.where(rsi14 < 35, 1, np.where(rsi14 > 70, -1, 0))
        signals['rsi_momentum'] = np.where(rsi14 > rsi14.shift(1), 1, -1)

        # Stochastic Oscillator (KDJ)
        lowest_low = low.rolling(9).min()
        highest_high = high.rolling(9).max()
        stoch_k = ((close - lowest_low) / (highest_high - lowest_low + 1e-8) * 100).fillna(50)
        stoch_d = stoch_k.rolling(3).mean().fillna(50)
        signals['stoch_kdj'] = np.where((stoch_k > stoch_d) & (stoch_k < 80), 1, np.where(stoch_k > 80, -1, 0))

        # Williams VixFix (恐慌探底)
        wvf = ((high.rolling(22).max() - low) / high.rolling(22).max()) * 100
        wvf_std = wvf.rolling(20).std().fillna(0)
        wvf_upper = wvf.rolling(20).mean() + 2.0 * wvf_std
        signals['williams_vixfix'] = np.where(wvf >= wvf_upper, 1, 0) # 恐慌极值，强力探底买入

        # Awesome Oscillator (AO)
        ao = self._sma((high + low) / 2, 5) - self._sma((high + low) / 2, 34)
        signals['ao_oscillator'] = np.where(ao > 0, 1, -1)

        # ----------------------------------------------------
        # 4. 通道与波动率策略族 (Channel/Volatility)
        # ----------------------------------------------------
        # Bollinger Bands Breakout & Squeeze
        std20 = close.rolling(20).std().fillna(close * 0.01)
        bb_upper = ema20 + 2.0 * std20
        bb_lower = ema20 - 2.0 * std20
        signals['bb_breakout'] = np.where(close > bb_upper, 1, np.where(close < bb_lower, -1, 0))

        # Squeeze Momentum (LazyBear)
        kc_upper = ema20 + 1.5 * atr14
        kc_lower = ema20 - 1.5 * atr14
        squeeze_on = (bb_lower > kc_lower) & (bb_upper < kc_upper)
        signals['squeeze_momentum'] = np.where(~squeeze_on & squeeze_on.shift(1), 1, 0) # 压缩释放爆发信号

        # Donchian Channel (唐奇安通道)
        donchian_high = high.rolling(20).max()
        donchian_low = low.rolling(20).min()
        signals['donchian_breakout'] = np.where(close >= donchian_high.shift(1), 1, np.where(close <= donchian_low.shift(1), -1, 0))

        # ----------------------------------------------------
        # 5. 成交量与量价策略族 (Volume/Liquidity)
        # ----------------------------------------------------
        # VWAP & Deviation
        cum_vol = vol.cumsum().replace(0, 1)
        cum_val = (close * vol).cumsum()
        vwap = cum_val / cum_vol
        signals['vwap_bias'] = np.where(close > vwap, 1, -1)

        # Volume Surge Breakout
        signals['volume_surge'] = np.where((vol > vol_sma20 * 2.0) & (close > open_p), 1, 0)

        # On Balance Volume (OBV)
        obv_direction = np.sign(close.diff()).fillna(0) * vol
        obv = obv_direction.cumsum()
        obv_ema = self._ema(obv, 20)
        signals['obv_trend'] = np.where(obv > obv_ema, 1, -1)

        # ----------------------------------------------------
        # 6. K线形态与结构突破族 (Pattern/Structure)
        # ----------------------------------------------------
        # Engulfing (看涨/看跌吞没)
        bullish_engulfing = (close > open_p) & (close.shift(1) < open_p.shift(1)) & (close >= open_p.shift(1)) & (open_p <= close.shift(1))
        bearish_engulfing = (close < open_p) & (close.shift(1) > open_p.shift(1)) & (close <= open_p.shift(1)) & (open_p >= close.shift(1))
        signals['candlestick_engulfing'] = np.where(bullish_engulfing, 1, np.where(bearish_engulfing, -1, 0))

        # Pivot Points High/Low
        pivot_h = high.rolling(5, center=True).max() == high
        signals['pivot_breakout'] = np.where(pivot_h.shift(2) & (close > high.shift(2)), 1, 0)

        return signals.fillna(0)
