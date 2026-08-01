"""Causal technical indicators used by factors and backtests."""

import numpy as np
import pandas as pd


def _wilder_average(values: pd.Series, periods: int) -> pd.Series:
    values = values.astype(float)
    result = pd.Series(np.nan, index=values.index, dtype=float)
    valid_positions = np.flatnonzero(values.notna().to_numpy())
    if len(valid_positions) < periods:
        return result

    seed_positions = valid_positions[:periods]
    seed_position = int(seed_positions[-1])
    result.iloc[seed_position] = float(values.iloc[seed_positions].mean())
    for position in range(seed_position + 1, len(values)):
        value = values.iloc[position]
        if pd.isna(value):
            continue
        previous = result.iloc[position - 1]
        result.iloc[position] = previous + (value - previous) / periods
    return result


def calculate_technical_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    volume = frame["volume"].astype(float)
    result = pd.DataFrame(index=frame.index)

    result["return_1d"] = close.pct_change(1)
    result["return_5d"] = close.pct_change(5)
    result["return_20d"] = close.pct_change(20)
    result["log_return"] = np.log(close / close.shift(1))
    for periods in (5, 10, 20, 60):
        average = close.rolling(periods).mean()
        result[f"ma_{periods}"] = average
        result[f"bias_{periods}"] = (close - average) / average

    ema12 = close.ewm(
        span=12, adjust=False, min_periods=12
    ).mean()
    ema26 = close.ewm(
        span=26, adjust=False, min_periods=26
    ).mean()
    result["macd_dif"] = ema12 - ema26
    result["macd_dea"] = result["macd_dif"].ewm(
        span=9, adjust=False, min_periods=9
    ).mean()
    result["macd_hist"] = (
        result["macd_dif"] - result["macd_dea"]
    ) * 2

    delta = close.diff()
    average_gain = _wilder_average(delta.clip(lower=0), 14)
    average_loss = _wilder_average(-delta.clip(upper=0), 14)
    rs = average_gain / average_loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    rsi = rsi.where(average_loss.ne(0), 100.0)
    rsi = rsi.where(
        average_gain.ne(0) | average_loss.ne(0), 50.0
    )
    result["rsi_14"] = rsi

    true_range = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    result["atr_14"] = _wilder_average(true_range, 14)
    result["norm_atr"] = result["atr_14"] / close

    std20 = close.rolling(20).std(ddof=0)
    result["boll_upper"] = result["ma_20"] + 2 * std20
    result["boll_lower"] = result["ma_20"] - 2 * std20
    width = (
        result["boll_upper"] - result["boll_lower"]
    ).replace(0, np.nan)
    result["boll_pct_b"] = (
        close - result["boll_lower"]
    ) / width
    result["vol_ma_5"] = volume.rolling(5).mean()
    result["vol_ma_20"] = volume.rolling(20).mean()
    result["vol_ratio"] = volume / result["vol_ma_20"].replace(0, np.nan)
    return result


def build_forward_return_target(close: pd.Series,
                                periods: int = 5) -> pd.Series:
    close = close.astype(float)
    return np.log(close.shift(-periods) / close)


def causal_expanding_zscore(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.astype(float)
    mean = frame.expanding(min_periods=2).mean().shift(1)
    std = frame.expanding(min_periods=2).std(ddof=0).shift(1)
    return ((frame - mean) / std.replace(0, np.nan)).replace(
        [np.inf, -np.inf], np.nan
    ).fillna(0.0)
