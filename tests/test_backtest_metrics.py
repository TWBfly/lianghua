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
        "annualized_return_pct",
        "annualized_volatility_pct",
        "max_drawdown_pct",
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


def test_calculate_performance_mathematical_precision():
    # 5-day scenario with known daily returns
    daily_results = [
        {"date": "2026-01-01", "end_equity": 101000.0, "daily_return": 0.01, "drawdown": 0.0, "turnover": 10000.0},
        {"date": "2026-01-02", "end_equity": 100495.0, "daily_return": -0.005, "drawdown": 0.005, "turnover": 0.0},
        {"date": "2026-01-03", "end_equity": 102504.9, "daily_return": 0.02, "drawdown": 0.0, "turnover": 10000.0},
        {"date": "2026-01-04", "end_equity": 101479.851, "daily_return": -0.01, "drawdown": 0.01, "turnover": 0.0},
        {"date": "2026-01-05", "end_equity": 103002.048765, "daily_return": 0.015, "drawdown": 0.0, "turnover": 5000.0},
    ]
    initial_capital = 100000.0

    metrics = calculate_performance(daily_results, initial_capital, annual_days=252)

    # Hand-derived math checks:
    returns = np.array([0.01, -0.005, 0.02, -0.01, 0.015])
    mean_ret = returns.mean()  # 0.006
    std_ret = returns.std(ddof=1)  # sqrt(0.000670 / 4) = 0.012942179105544777
    expected_vol_pct = float(std_ret * np.sqrt(252) * 100)
    expected_sharpe = float((mean_ret / std_ret) * np.sqrt(252))

    downside = np.sqrt(np.mean(np.minimum(returns, 0.0) ** 2))  # 0.005
    expected_sortino = float((mean_ret * 252) / (downside * np.sqrt(252)))

    elapsed_days = 4  # (2026-01-05 - 2026-01-01).days
    annual_return = (103002.048765 / 100000.0) ** (365.0 / elapsed_days) - 1.0
    expected_calmar = annual_return / 0.01

    assert metrics["annualized_volatility_pct"] == pytest.approx(expected_vol_pct, rel=1e-5)
    assert metrics["sharpe_ratio"] == pytest.approx(expected_sharpe, rel=1e-5)
    assert metrics["sortino_ratio"] == pytest.approx(expected_sortino, rel=1e-5)
    assert metrics["calmar_ratio"] == pytest.approx(expected_calmar, rel=1e-5)
    assert metrics["total_turnover_cny"] == 25000.0
    assert metrics["max_drawdown_duration_days"] == 1


def test_max_drawdown_duration_calculation():
    # Test multi-day drawdown recovery duration
    daily_results = [
        {"date": "2026-01-01", "end_equity": 100000.0, "daily_return": 0.0, "drawdown": 0.0, "turnover": 0.0},
        {"date": "2026-01-02", "end_equity": 90000.0, "daily_return": -0.1, "drawdown": 0.1, "turnover": 0.0},
        {"date": "2026-01-05", "end_equity": 95000.0, "daily_return": 0.055, "drawdown": 0.05, "turnover": 0.0},
        {"date": "2026-01-10", "end_equity": 105000.0, "daily_return": 0.105, "drawdown": 0.0, "turnover": 0.0},
    ]
    metrics = calculate_performance(daily_results, 100000.0)
    # Peak on Jan 1st (100k), drops on Jan 2nd and Jan 5th, recovered on Jan 10th (105k)
    # Max duration in drawdown from Jan 1st peak = (2026-01-05 - 2026-01-01).days = 4 days
    assert metrics["max_drawdown_duration_days"] == 4


def test_monte_carlo_analysis():
    from backtest_metrics import run_monte_carlo_analysis

    daily_results = [
        {"date": f"2026-01-{i+1:02d}", "end_equity": 100000.0 * (1.002 ** i), "daily_return": 0.002 + (0.001 if i % 2 == 0 else -0.0005), "drawdown": 0.0, "turnover": 1000.0}
        for i in range(30)
    ]

    mc_res = run_monte_carlo_analysis(daily_results, n_simulations=200, block_size=3)

    assert "p_value_sharpe" in mc_res
    assert "is_statistically_significant" in mc_res
    assert len(mc_res["sharpe_ci_95"]) == 2
    assert mc_res["sharpe_ci_95"][0] <= mc_res["sharpe_ci_95"][1]
    assert 0.0 <= mc_res["p_value_sharpe"] <= 1.0


