import numpy as np
import pandas as pd
import pytest

from technical_indicators import (
    build_forward_return_target,
    calculate_technical_indicators,
    causal_expanding_zscore,
)


def indicator_bars(length=40):
    close = pd.Series(np.arange(10, length + 10, dtype=float))
    return pd.DataFrame({
        "trade_date": pd.bdate_range("2026-01-01", periods=length),
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": 1_000.0,
        "amount": close * 1_000,
    })


def test_wilder_rsi_atr_and_population_bollinger():
    result = calculate_technical_indicators(indicator_bars())

    assert result["rsi_14"].iloc[-1] == 100.0
    assert result["atr_14"].iloc[-1] == 2.0
    assert result["boll_upper"].iloc[19] == pytest.approx(
        19.5 + 2 * np.std(np.arange(10, 30), ddof=0)
    )


def test_indicator_warmup_remains_unknown():
    result = calculate_technical_indicators(indicator_bars())

    assert result["rsi_14"].iloc[:14].isna().all()
    assert result["atr_14"].iloc[:13].isna().all()
    assert result["macd_hist"].iloc[:33].isna().all()


def test_indicators_are_prefix_invariant():
    bars = indicator_bars(80)
    short = calculate_technical_indicators(bars.iloc[:50])
    long = calculate_technical_indicators(bars)

    pd.testing.assert_frame_equal(short, long.iloc[:50])


def test_expanding_normalization_is_prefix_invariant():
    frame = pd.DataFrame({"x": [1.0, 2.0, 3.0, 100.0]})
    short = causal_expanding_zscore(frame.iloc[:3])
    long = causal_expanding_zscore(frame)

    pd.testing.assert_frame_equal(short, long.iloc[:3])
    assert short.iloc[0, 0] == 0.0


def test_forward_target_keeps_unknown_tail():
    target = build_forward_return_target(
        pd.Series([10.0, 11.0, 12.0, 13.0]), periods=2
    )

    assert target.iloc[0] == pytest.approx(np.log(1.2))
    assert target.iloc[-2:].isna().all()
