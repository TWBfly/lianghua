"""
Unit tests for Alpha Factor Mining, Pluggable Registry, and Multi-Dimensional Factor Evaluator.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from alpha_factor_miner import FactorRegistry, compute_factors_for_panel
from alpha_factor_evaluator import (
    calculate_factor_ic_series,
    evaluate_single_factor,
    evaluate_factor_pool,
    FactorEvaluationResult,
)


def _generate_synthetic_stock_panel(n_days=100, n_symbols=25, seed=42) -> pd.DataFrame:
    """Generate deterministic synthetic panel of stock daily prices with a known alpha signal."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_days, freq="B")
    symbols = [f"{i:06d}" for i in range(1, n_symbols + 1)]

    records = []
    # Assign each symbol a fixed intrinsic drift (alpha ground truth)
    drifts = {s: (i - n_symbols / 2) * 0.001 for i, s in enumerate(symbols)}

    for s in symbols:
        price = 10.0 + rng.uniform(0, 5)
        drift = drifts[s]
        for d in dates:
            daily_shock = rng.normal(0, 0.02)
            ret = drift + daily_shock
            price = max(1.0, price * (1.0 + ret))
            high = price * (1.0 + abs(rng.normal(0, 0.01)))
            low = price * (1.0 - abs(rng.normal(0, 0.01)))
            volume = rng.integers(10000, 100000)
            amount = volume * price
            records.append({
                "symbol": s,
                "trade_date": d.strftime("%Y-%m-%d"),
                "open": low + (high - low) * 0.5,
                "high": high,
                "low": low,
                "close": price,
                "volume": volume,
                "amount": amount,
                "turnover_rate": rng.uniform(0.5, 5.0),
            })

    df = pd.DataFrame(records).sort_values(["trade_date", "symbol"]).reset_index(drop=True)
    return df


def test_factor_registry_and_custom_factor():
    """Verify FactorRegistry decorator, metadata retrieval, and custom factor registration."""
    # Register a new custom factor
    @FactorRegistry.register("test_custom_spread", category="test", description="Test spread factor")
    def factor_test_spread(df: pd.DataFrame) -> pd.Series:
        return (df["high"] - df["close"]) / df["close"]

    assert "test_custom_spread" in FactorRegistry.list_factors()
    meta = FactorRegistry.get_metadata()
    assert meta["test_custom_spread"]["category"] == "test"

    func = FactorRegistry.get_factor("test_custom_spread")
    assert func is not None

    sample_df = pd.DataFrame({"high": [12.0], "close": [10.0]})
    res = func(sample_df)
    assert pytest.approx(float(res.iloc[0]), 0.001) == 0.2


def test_compute_factors_for_panel():
    """Verify panel causal factor computation."""
    panel = _generate_synthetic_stock_panel(n_days=40, n_symbols=5)
    factors = ["ret_1", "ret_5", "vol_20", "boll_pos", "volume_z20"]
    computed = compute_factors_for_panel(panel, factor_names=factors)

    for f in factors:
        assert f in computed.columns
        assert computed[f].notna().sum() > 0


def test_single_factor_evaluation_metrics():
    """Verify IC, Rank IC, ICIR, Quantile Layering, and Decay calculations."""
    panel = _generate_synthetic_stock_panel(n_days=80, n_symbols=30)
    computed = compute_factors_for_panel(panel, factor_names=["ret_5", "vol_20", "boll_pos"])
    
    # Add forward 5-day label
    prices = computed.pivot(index="trade_date", columns="symbol", values="close")
    fwd_ret = (prices.shift(-5) / prices - 1.0).unstack().rename("label").reset_index()
    computed = computed.merge(fwd_ret, on=["symbol", "trade_date"], how="left")

    result = evaluate_single_factor(
        df=computed,
        factor_col="ret_5",
        label_col="label",
        quantiles=5,
        decay_horizons=(1, 3, 5),
    )

    assert isinstance(result, FactorEvaluationResult)
    assert result.factor_name == "ret_5"
    assert -1.0 <= result.mean_rank_ic <= 1.0
    assert result.evaluated_days > 20
    assert 0.0 <= result.ic_positive_ratio <= 1.0
    assert len(result.quantile_returns) == 5
    assert set(result.quantile_returns.keys()) == {"Q1", "Q2", "Q3", "Q4", "Q5"}
    assert set(result.ic_decay.keys()) == {1, 3, 5}


def test_evaluate_factor_pool_leaderboard():
    """Verify multi-factor evaluation leaderboard and correlation matrix."""
    panel = _generate_synthetic_stock_panel(n_days=60, n_symbols=20)
    factors = ["ret_1", "ret_5", "vol_20", "rsi_14", "volume_z20"]
    computed = compute_factors_for_panel(panel, factor_names=factors)

    # Add label
    prices = computed.pivot(index="trade_date", columns="symbol", values="close")
    fwd_ret = (prices.shift(-5) / prices - 1.0).unstack().rename("label").reset_index()
    computed = computed.merge(fwd_ret, on=["symbol", "trade_date"], how="left")

    leaderboard, corr_matrix = evaluate_factor_pool(
        df=computed,
        factor_cols=factors,
        label_col="label",
        quantiles=3,
    )

    assert not leaderboard.empty
    assert len(leaderboard) == len(factors)
    assert "factor" in leaderboard.columns
    assert "rank_icir" in leaderboard.columns
    assert "monotonicity" in leaderboard.columns

    assert corr_matrix.shape == (len(factors), len(factors))
    assert np.allclose(np.diag(corr_matrix), 1.0)
