import inspect

import numpy as np
import pandas as pd
import pytest

from strategy_signal_library import (
    SIGNAL_FUNCTIONS,
    market_structure_signal,
    pivot_breakout_signal,
)


def synthetic_bars(periods=180):
    index = pd.bdate_range("2025-01-01", periods=periods)
    base = 20 + np.arange(periods) * 0.015 + np.sin(
        np.arange(periods) / 6
    ) * 1.2
    open_price = base + np.cos(np.arange(periods) / 5) * 0.15
    return pd.DataFrame({
        "open": open_price,
        "high": np.maximum(open_price, base) + 0.35,
        "low": np.minimum(open_price, base) - 0.35,
        "close": base,
        "volume": 1_000_000 + (
            np.sin(np.arange(periods) / 4) * 100_000
        ),
    }, index=index)


@pytest.mark.parametrize("name", SIGNAL_FUNCTIONS)
def test_registered_strategy_runs_with_discrete_aligned_output(name):
    frame = synthetic_bars()

    result = SIGNAL_FUNCTIONS[name](frame.copy())

    assert result.index.equals(frame.index)
    assert set(result.dropna().unique()).issubset({-1, 0, 1})


@pytest.mark.parametrize("name", SIGNAL_FUNCTIONS)
def test_registered_strategy_is_prefix_invariant(name):
    frame = synthetic_bars()
    full = SIGNAL_FUNCTIONS[name](frame.copy())

    for length in (80, 120, 160):
        prefix = SIGNAL_FUNCTIONS[name](frame.iloc[:length].copy())
        pd.testing.assert_series_equal(
            full.iloc[:length], prefix, check_names=False
        )


@pytest.mark.parametrize("function", [
    pivot_breakout_signal,
    market_structure_signal,
])
def test_pivot_strategies_do_not_use_centered_future_windows(function):
    assert "center=True" not in inspect.getsource(function)
