"""
Pluggable Alpha Factor Mining and Definition Engine.
Provides a decoupled, extensible registry for formulaic and algorithmic alpha factors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd


FactorFunc = Callable[[pd.DataFrame], pd.Series]


class FactorRegistry:
    """Central registry for alpha factor formulas and functions."""

    _registry: Dict[str, FactorFunc] = {}
    _descriptions: Dict[str, str] = {}
    _categories: Dict[str, str] = {}

    @classmethod
    def register(cls, name: str, category: str = "custom", description: str = ""):
        """Decorator to register a custom factor calculation function."""
        def decorator(func: FactorFunc) -> FactorFunc:
            cls._registry[name] = func
            cls._categories[name] = category
            cls._descriptions[name] = description or func.__doc__ or name
            return func
        return decorator

    @classmethod
    def get_factor(cls, name: str) -> Optional[FactorFunc]:
        return cls._registry.get(name)

    @classmethod
    def list_factors(cls, category: Optional[str] = None) -> List[str]:
        if category:
            return [k for k, v in cls._categories.items() if v == category]
        return list(cls._registry.keys())

    @classmethod
    def get_metadata(cls) -> Dict[str, Dict[str, str]]:
        return {
            name: {
                "category": cls._categories.get(name, "custom"),
                "description": cls._descriptions.get(name, ""),
            }
            for name in cls._registry
        }


# ==============================================================================
# 1. Momentum & Trend Factors
# ==============================================================================

@FactorRegistry.register("ret_1", "momentum", "1-day return")
def factor_ret_1(df: pd.DataFrame) -> pd.Series:
    return df["close"].pct_change(1)


@FactorRegistry.register("ret_3", "momentum", "3-day return")
def factor_ret_3(df: pd.DataFrame) -> pd.Series:
    return df["close"].pct_change(3)


@FactorRegistry.register("ret_5", "momentum", "5-day return")
def factor_ret_5(df: pd.DataFrame) -> pd.Series:
    return df["close"].pct_change(5)


@FactorRegistry.register("ret_10", "momentum", "10-day return")
def factor_ret_10(df: pd.DataFrame) -> pd.Series:
    return df["close"].pct_change(10)


@FactorRegistry.register("ret_20", "momentum", "20-day return")
def factor_ret_20(df: pd.DataFrame) -> pd.Series:
    return df["close"].pct_change(20)


@FactorRegistry.register("ema_gap_5_20", "trend", "Spread between EMA5 and EMA20 normalized by EMA20")
def factor_ema_gap_5_20(df: pd.DataFrame) -> pd.Series:
    ema5 = df["close"].ewm(span=5, adjust=False).mean()
    ema20 = df["close"].ewm(span=20, adjust=False).mean()
    return (ema5 - ema20) / ema20.replace(0, np.nan)


@FactorRegistry.register("ema_gap_10_60", "trend", "Spread between EMA10 and EMA60 normalized by EMA60")
def factor_ema_gap_10_60(df: pd.DataFrame) -> pd.Series:
    ema10 = df["close"].ewm(span=10, adjust=False).mean()
    ema60 = df["close"].ewm(span=60, adjust=False).mean()
    return (ema10 - ema60) / ema60.replace(0, np.nan)


@FactorRegistry.register("price_slope_10", "trend", "10-day linear regression slope of close price")
def factor_price_slope_10(df: pd.DataFrame) -> pd.Series:
    close = df["close"].astype(float)
    x = np.arange(10)
    x_mean = 4.5
    x_var = np.sum((x - x_mean) ** 2)

    def _calc_slope(window: np.ndarray) -> float:
        if len(window) < 10 or np.isnan(window).any():
            return np.nan
        y_mean = np.mean(window)
        cov = np.sum((x - x_mean) * (window - y_mean))
        return (cov / x_var) / (y_mean + 1e-6)

    return close.rolling(10).apply(_calc_slope, raw=True)


# ==============================================================================
# 2. Volatility & Extremes Factors
# ==============================================================================

@FactorRegistry.register("vol_5", "volatility", "5-day rolling std of log returns")
def factor_vol_5(df: pd.DataFrame) -> pd.Series:
    log_ret = np.log(df["close"] / df["close"].shift(1).replace(0, np.nan))
    return log_ret.rolling(5).std(ddof=0)


@FactorRegistry.register("vol_20", "volatility", "20-day rolling std of log returns")
def factor_vol_20(df: pd.DataFrame) -> pd.Series:
    log_ret = np.log(df["close"] / df["close"].shift(1).replace(0, np.nan))
    return log_ret.rolling(20).std(ddof=0)


@FactorRegistry.register("vol_60", "volatility", "60-day rolling std of log returns")
def factor_vol_60(df: pd.DataFrame) -> pd.Series:
    log_ret = np.log(df["close"] / df["close"].shift(1).replace(0, np.nan))
    return log_ret.rolling(60).std(ddof=0)


@FactorRegistry.register("range_pct", "volatility", "Intraday high-low range normalized by previous close")
def factor_range_pct(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1).replace(0, np.nan)
    return (df["high"] - df["low"]) / prev_close


@FactorRegistry.register("boll_pos", "volatility", "Bollinger Band Position ((Close - MA20) / (2 * Std20))")
def factor_boll_pos(df: pd.DataFrame) -> pd.Series:
    ma20 = df["close"].rolling(20).mean()
    std20 = df["close"].rolling(20).std(ddof=0).replace(0, np.nan)
    return (df["close"] - ma20) / (2.0 * std20)


@FactorRegistry.register("atr_ratio_14", "volatility", "14-day Average True Range normalized by close")
def factor_atr_ratio_14(df: pd.DataFrame) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    prev_close = df["close"].shift(1).astype(float)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    return atr / df["close"].replace(0, np.nan)


# ==============================================================================
# 3. Volume-Price & Liquidity Factors
# ==============================================================================

@FactorRegistry.register("volume_z20", "volume", "20-day Volume Z-Score")
def factor_volume_z20(df: pd.DataFrame) -> pd.Series:
    vol = df["volume"].astype(float)
    return (vol - vol.rolling(20).mean()) / vol.rolling(20).std(ddof=0).replace(0, np.nan)


@FactorRegistry.register("volume_z60", "volume", "60-day Volume Z-Score")
def factor_volume_z60(df: pd.DataFrame) -> pd.Series:
    vol = df["volume"].astype(float)
    return (vol - vol.rolling(60).mean()) / vol.rolling(60).std(ddof=0).replace(0, np.nan)


@FactorRegistry.register("turnover_ma5", "liquidity", "5-day rolling average turnover rate")
def factor_turnover_ma5(df: pd.DataFrame) -> pd.Series:
    to = df.get("turnover_rate", pd.Series(0.0, index=df.index)).astype(float)
    return to.rolling(5).mean()


@FactorRegistry.register("turnover_ma20", "liquidity", "20-day rolling average turnover rate")
def factor_turnover_ma20(df: pd.DataFrame) -> pd.Series:
    to = df.get("turnover_rate", pd.Series(0.0, index=df.index)).astype(float)
    return to.rolling(20).mean()


@FactorRegistry.register("volume_price_corr_10", "volume", "10-day correlation between price and volume")
def factor_volume_price_corr_10(df: pd.DataFrame) -> pd.Series:
    return df["close"].rolling(10).corr(df["volume"])


@FactorRegistry.register("amihud_illiquidity_20", "liquidity", "20-day Amihud Illiquidity Ratio (Abs Return / Amount)")
def factor_amihud_illiquidity_20(df: pd.DataFrame) -> pd.Series:
    ret_abs = df["close"].pct_change(1).abs()
    amount = df["amount"].replace(0, np.nan)
    return (ret_abs / amount * 1e8).rolling(20).mean()


# ==============================================================================
# 4. Reversal & Technical Oscillators
# ==============================================================================

@FactorRegistry.register("rsi_14", "oscillator", "14-day Relative Strength Index")
def factor_rsi_14(df: pd.DataFrame) -> pd.Series:
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean().replace(0, np.nan)
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


@FactorRegistry.register("body_pct", "geometry", "Bar body (Close - Open) normalized by previous close")
def factor_body_pct(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1).replace(0, np.nan)
    return (df["close"] - df["open"]) / prev_close


@FactorRegistry.register("close_pos_in_bar", "geometry", "Position of close within intraday high-low range (0 to 1)")
def factor_close_pos_in_bar(df: pd.DataFrame) -> pd.Series:
    hl = (df["high"] - df["low"]).replace(0, np.nan)
    return (df["close"] - df["low"]) / hl


# ==============================================================================
# 5. Advanced OHLCV Microstructure, Efficiency & Asymmetry Factors (Pure Price-Volume)
# ==============================================================================

@FactorRegistry.register("kaufman_efficiency_10", "efficiency", "10-day Kaufman Trend Efficiency Ratio (Net Direction / Total Path)")
def factor_kaufman_efficiency_10(df: pd.DataFrame) -> pd.Series:
    close = df["close"].astype(float)
    net_change = (close - close.shift(10)).abs()
    path = close.diff().abs().rolling(10).sum().replace(0, np.nan)
    return net_change / path


@FactorRegistry.register("kaufman_efficiency_20", "efficiency", "20-day Kaufman Trend Efficiency Ratio (Net Direction / Total Path)")
def factor_kaufman_efficiency_20(df: pd.DataFrame) -> pd.Series:
    close = df["close"].astype(float)
    net_change = (close - close.shift(20)).abs()
    path = close.diff().abs().rolling(20).sum().replace(0, np.nan)
    return net_change / path


@FactorRegistry.register("parkinson_vol_10", "volatility", "10-day Parkinson Extreme Volatility Estimator")
def factor_parkinson_vol_10(df: pd.DataFrame) -> pd.Series:
    hl_ratio = (df["high"] / df["low"].replace(0, np.nan)).apply(np.log)
    parkinson_sq = (hl_ratio ** 2) / (4.0 * np.log(2.0))
    return np.sqrt(parkinson_sq.rolling(10).mean())


@FactorRegistry.register("garman_klass_vol_10", "volatility", "10-day Garman-Klass Microstructure Volatility Estimator")
def factor_garman_klass_vol_10(df: pd.DataFrame) -> pd.Series:
    hl = (df["high"] / df["low"].replace(0, np.nan)).apply(np.log)
    co = (df["close"] / df["open"].replace(0, np.nan)).apply(np.log)
    gk = 0.5 * (hl ** 2) - (2.0 * np.log(2.0) - 1.0) * (co ** 2)
    return np.sqrt(gk.clip(lower=0).rolling(10).mean())


@FactorRegistry.register("vol_squeeze_ratio_20", "regime", "20-day Bollinger Bandwidth to ATR Squeeze Ratio")
def factor_vol_squeeze_ratio_20(df: pd.DataFrame) -> pd.Series:
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    prev_close = close.shift(1)
    
    std20 = close.rolling(20).std(ddof=0)
    bb_width = 4.0 * std20 / close.replace(0, np.nan)
    
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr20 = (tr.rolling(20).mean() / close).replace(0, np.nan)
    return bb_width / atr20


@FactorRegistry.register("intraday_intensity_10", "volume", "10-day Volume-Weighted Intraday Pressure")
def factor_intraday_intensity_10(df: pd.DataFrame) -> pd.Series:
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)
    
    hl = (high - low).replace(0, np.nan)
    clv = (2.0 * close - high - low) / hl
    vol_norm = volume / volume.rolling(20).mean().replace(0, np.nan)
    return (clv * vol_norm).rolling(10).mean()


@FactorRegistry.register("upside_downside_vol_ratio_20", "asymmetry", "20-day Upside vs Downside Realized Semi-Variance Ratio")
def factor_upside_downside_vol_ratio_20(df: pd.DataFrame) -> pd.Series:
    ret = df["close"].pct_change(1)
    up_ret = ret.clip(lower=0)
    down_ret = (-ret).clip(lower=0)
    up_var = (up_ret ** 2).rolling(20).mean()
    down_var = (down_ret ** 2).rolling(20).mean().replace(0, np.nan)
    return np.sqrt(up_var / down_var)


@FactorRegistry.register("breakout_channel_pos_20", "trend", "20-day Donchian Channel Position (0=Low, 1=High)")
def factor_breakout_channel_pos_20(df: pd.DataFrame) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    
    max20 = high.rolling(20).max()
    min20 = low.rolling(20).min()
    span = (max20 - min20).replace(0, np.nan)
    return (close - min20) / span


@FactorRegistry.register("momentum_acceleration_5_20", "momentum", "Momentum Acceleration (Short-term velocity vs medium velocity)")
def factor_momentum_acceleration_5_20(df: pd.DataFrame) -> pd.Series:
    ret5 = df["close"].pct_change(5)
    ret20 = df["close"].pct_change(20)
    return ret5 - (ret20 / 4.0)


# ==============================================================================
# Pipeline Calculation Helper
# ==============================================================================

def compute_factors_for_panel(
    df: pd.DataFrame,
    factor_names: Optional[Sequence[str]] = None,
    symbol_col: str = "symbol",
    date_col: str = "trade_date",
) -> pd.DataFrame:
    """
    Compute all or specified registered factors on a multi-symbol dataframe.
    Ensures strict per-symbol causal calculation without lookahead bias.
    """
    available_factors = FactorRegistry.list_factors()
    if factor_names is None:
        target_factors = available_factors
    else:
        target_factors = [f for f in factor_names if f in FactorRegistry._registry]

    if not target_factors:
        raise ValueError("No valid factor names specified")

    df_sorted = df.sort_values([symbol_col, date_col]).copy()
    computed_chunks = []

    for sym, group in df_sorted.groupby(symbol_col, sort=False):
        group_df = group.copy()
        for name in target_factors:
            func = FactorRegistry.get_factor(name)
            if func is not None:
                group_df[name] = func(group_df)
        computed_chunks.append(group_df)

    result = pd.concat(computed_chunks, ignore_index=True)
    return result.sort_values([date_col, symbol_col]).reset_index(drop=True)
