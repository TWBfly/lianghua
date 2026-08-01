import numpy as np
import pandas as pd
import pytest

from backtest_metrics import build_daily_ledger, calculate_performance
from portfolio_simulator import simulate_portfolio


def sample_simulation():
    dates = pd.bdate_range("2026-01-05", periods=4)
    market = pd.DataFrame({
        "open": [10.0, 10.5, 12.0, 11.5],
        "high": [10.2, 10.7, 12.2, 11.7],
        "low": [9.8, 10.3, 11.8, 11.3],
        "close": [10.0, 10.6, 12.0, 11.5],
        "volume": [1_000_000] * 4,
    }, index=dates)
    decisions = pd.DataFrame([{
        "decision_time": dates[0],
        "symbol": "000001",
        "action": "BUY",
        "target_fraction": 0.2,
        "reason": "test",
        "model_version": "v1",
    }])
    return simulate_portfolio(
        {"000001": market}, decisions, initial_cash=100_000
    )


def test_daily_ledger_reconciles_simulation():
    simulation = sample_simulation()

    ledger = build_daily_ledger(simulation)

    assert ledger[-1]["end_equity"] == simulation.final_equity
    assert sum(row["net_pnl"] for row in ledger) == pytest.approx(
        simulation.final_equity - simulation.initial_cash,
        abs=0.01,
    )
    assert sum(row["fill_count"] for row in ledger) == len(
        simulation.fills
    )


def test_performance_metrics_are_finite():
    simulation = sample_simulation()

    metrics = calculate_performance(
        build_daily_ledger(simulation), simulation.initial_cash
    )

    assert set(metrics) == {
        "annualized_volatility_pct",
        "sharpe_ratio",
        "sortino_ratio",
        "calmar_ratio",
        "max_drawdown_duration_days",
        "total_turnover_cny",
        "turnover_ratio",
    }
    assert all(np.isfinite(value) for value in metrics.values())
    assert metrics["total_turnover_cny"] > 0


def test_empty_performance_is_zeroed():
    metrics = calculate_performance([], 100_000)

    assert all(value == 0 for value in metrics.values())
