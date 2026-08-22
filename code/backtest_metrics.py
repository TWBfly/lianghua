"""Daily mark-to-market ledger and aggregate backtest statistics."""

import numpy as np
import pandas as pd


def build_daily_ledger(simulation):
    ledger = [{
        "date": pd.Timestamp(point["date"]).strftime("%Y-%m-%d"),
        "start_equity": float(point["start_equity"]),
        "end_equity": float(point["equity"]),
        "cash": float(point["cash"]),
        "market_value": float(point["gross_exposure"]),
        "holding_pnl": float(point["holding_pnl"]),
        "trading_pnl": float(point["trading_pnl"]),
        "commission": float(point["commission"]),
        "transfer_fee": float(point["transfer_fee"]),
        "stamp_duty": float(point["stamp_duty"]),
        "slippage": float(point["slippage"]),
        "turnover": float(point["turnover"]),
        "fill_count": int(point["fill_count"]),
        "net_pnl": float(point["net_pnl"]),
        "daily_return": float(point["daily_return"]),
        "drawdown": float(point["drawdown"]),
    } for point in simulation.equity_curve]

    if not ledger:
        return []
    equity_change = simulation.final_equity - simulation.initial_cash
    if abs(sum(row["net_pnl"] for row in ledger) - equity_change) > 0.01:
        raise ValueError("daily ledger does not reconcile")
    for field in ("commission", "transfer_fee", "stamp_duty", "slippage"):
        daily_total = sum(row[field] for row in ledger)
        fill_total = sum(float(fill[field]) for fill in simulation.fills)
        if abs(daily_total - fill_total) > 0.01:
            raise ValueError("daily ledger costs do not reconcile")
    return ledger


def calculate_performance(daily_results, initial_capital, annual_days=252):
    zero = {
        "annualized_volatility_pct": 0.0,
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0,
        "calmar_ratio": 0.0,
        "max_drawdown_duration_days": 0,
        "total_turnover_cny": 0.0,
        "turnover_ratio": 0.0,
    }
    if not daily_results:
        return zero

    frame = pd.DataFrame(daily_results)
    returns = frame["daily_return"].astype(float)
    deviation = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    volatility = deviation * np.sqrt(annual_days)
    sharpe = (
        float(returns.mean()) / deviation * np.sqrt(annual_days)
        if deviation else 0.0
    )
    downside = float(np.sqrt(np.mean(
        np.minimum(returns.to_numpy(), 0.0) ** 2
    )))
    sortino = (
        float(returns.mean()) * annual_days
        / (downside * np.sqrt(annual_days))
        if downside else 0.0
    )

    dates = pd.to_datetime(frame["date"])
    elapsed_days = max(1, (dates.iloc[-1] - dates.iloc[0]).days)
    final_equity = float(frame["end_equity"].iloc[-1])
    annual_return = (
        (final_equity / float(initial_capital))
        ** (365.0 / elapsed_days) - 1.0
        if final_equity > 0 else -1.0
    )
    max_drawdown = float(frame["drawdown"].max())
    calmar = annual_return / max_drawdown if max_drawdown else 0.0

    peak_date = dates.iloc[0]
    peak_equity = float(frame["end_equity"].iloc[0])
    max_duration = 0
    for date, equity in zip(dates, frame["end_equity"].astype(float)):
        if equity >= peak_equity:
            peak_equity = equity
            peak_date = date
        else:
            max_duration = max(max_duration, (date - peak_date).days)

    turnover = float(frame["turnover"].sum())
    average_equity = float(frame["end_equity"].mean())
    result = {
        "annualized_return_pct": annual_return * 100.0,
        "annualized_volatility_pct": volatility * 100.0,
        "max_drawdown_pct": max_drawdown * 100.0,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "calmar_ratio": calmar,
        "max_drawdown_duration_days": max_duration,
        "total_turnover_cny": turnover,
        "turnover_ratio": (
            turnover / average_equity if average_equity else 0.0
        ),
    }
    return {
        key: (
            int(value)
            if key == "max_drawdown_duration_days"
            else float(np.nan_to_num(
                value, nan=0.0, posinf=0.0, neginf=0.0
            ))
        )
        for key, value in result.items()
    }


def run_monte_carlo_analysis(daily_results, n_simulations: int = 1000,
                              block_size: int = 5, annual_days: int = 252) -> dict:
    """Stationary block bootstrapping Monte Carlo stress testing for strategy returns."""
    if not daily_results or len(daily_results) < 5:
        return {
            "p_value_sharpe": 1.0,
            "is_statistically_significant": False,
            "sharpe_ci_95": [0.0, 0.0],
            "win_rate_ci_95": [0.0, 0.0],
            "max_drawdown_ci_95": [0.0, 0.0],
        }

    frame = pd.DataFrame(daily_results)
    returns = frame["daily_return"].astype(float).to_numpy()
    n_days = len(returns)
    if n_days < 5:
        return {
            "p_value_sharpe": 1.0,
            "is_statistically_significant": False,
            "sharpe_ci_95": [0.0, 0.0],
            "win_rate_ci_95": [0.0, 0.0],
            "max_drawdown_ci_95": [0.0, 0.0],
        }

    actual_std = np.std(returns, ddof=1) if n_days > 1 else 0.0
    actual_sharpe = (np.mean(returns) / actual_std * np.sqrt(annual_days)) if actual_std > 0 else 0.0

    sim_sharpes = []
    sim_win_rates = []
    sim_max_drawdowns = []

    np.random.seed(42)
    max_block_start = max(1, n_days - block_size + 1)

    for _ in range(n_simulations):
        sampled_returns = []
        while len(sampled_returns) < n_days:
            start_idx = np.random.randint(0, max_block_start)
            sampled_returns.extend(returns[start_idx:start_idx + block_size])
        sampled = np.array(sampled_returns[:n_days])

        std = np.std(sampled, ddof=1) if n_days > 1 else 0.0
        sharpe = (np.mean(sampled) / std * np.sqrt(annual_days)) if std > 0 else 0.0
        win_rate = float(np.mean(sampled > 0))

        cum_equity = np.cumprod(1.0 + sampled)
        peak = np.maximum.accumulate(cum_equity)
        drawdown = (peak - cum_equity) / peak
        max_dd = float(np.max(drawdown)) if len(drawdown) > 0 else 0.0

        sim_sharpes.append(sharpe)
        sim_win_rates.append(win_rate)
        sim_max_drawdowns.append(max_dd)

    p_value = float(np.mean(np.array(sim_sharpes) <= 0)) if actual_sharpe > 0 else 1.0

    return {
        "p_value_sharpe": p_value,
        "is_statistically_significant": bool(p_value < 0.05),
        "sharpe_ci_95": [
            float(np.percentile(sim_sharpes, 2.5)),
            float(np.percentile(sim_sharpes, 97.5)),
        ],
        "win_rate_ci_95": [
            float(np.percentile(sim_win_rates, 2.5)),
            float(np.percentile(sim_win_rates, 97.5)),
        ],
        "max_drawdown_ci_95": [
            float(np.percentile(sim_max_drawdowns, 2.5)),
            float(np.percentile(sim_max_drawdowns, 97.5)),
        ],
    }
