from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest


CODE_DIR = Path(__file__).resolve().parents[1] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from run_guiyuan_15m_lln_audit import (  # noqa: E402
    audit_bars,
    combine_simulations,
    lln_gate,
    simulate_guiyuan,
    summarize_simulation,
    summarize_portfolio,
    write_report,
)


SPEC = {"multiplier": 10.0, "tick": 1.0, "fee_rate": 0.001}


def deterministic_long_fixture() -> tuple[pd.DataFrame, pd.Series]:
    index = pd.date_range("2026-01-01 09:00", periods=20, freq="15min")
    close = [100.0] * 16 + [102.0, 104.0, 106.0, 110.0]
    df = pd.DataFrame(
        {
            "open": [100.0] * 20,
            "high": [101.0] * 16 + [103.0, 105.0, 107.0, 111.0],
            "low": [99.0] * 20,
            "close": close,
            "volume": [1_000.0] * 20,
            "open_interest": [10_000.0] * 20,
        },
        index=index,
    )
    signals = pd.Series(0, index=index, dtype=int)
    signals.iloc[14] = 1
    return df, signals


def test_signal_is_filled_at_next_open() -> None:
    df, signals = deterministic_long_fixture()

    trade = simulate_guiyuan(df, signals, SPEC, initial_capital=100_000.0)["trades"].iloc[0]

    assert trade["entry_time"] == df.index[15]
    assert trade["entry_price"] == pytest.approx(df["open"].iloc[15] + SPEC["tick"])


def test_position_size_and_round_trip_costs_are_in_ledger() -> None:
    df, signals = deterministic_long_fixture()

    result = simulate_guiyuan(df, signals, SPEC, initial_capital=100_000.0)
    trade = result["trades"].iloc[0]
    expected_gross = (
        (trade["exit_price"] - trade["entry_price"])
        * SPEC["multiplier"]
        * trade["lots"]
    )

    assert trade["gross_pnl"] == pytest.approx(expected_gross)
    assert trade["net_pnl"] == pytest.approx(
        expected_gross - trade["entry_fee"] - trade["exit_fee"]
    )
    assert result["ledger_reconciled"]
    assert result["final_equity"] == pytest.approx(
        100_000.0 + result["trades"]["net_pnl"].sum()
    )


def test_lln_gate_requires_strictly_more_than_1000_trades() -> None:
    assert not lln_gate(1_000)
    assert lln_gate(1_001)


def test_track_summaries_never_mix() -> None:
    rows = pd.DataFrame(
        {
            "track": ["real", "synthetic"],
            "net_pnl": [-10.0, 999.0],
            "trade_count": [2, 1_001],
        }
    )

    summary = summarize_portfolio(rows, "real")

    assert summary["net_pnl"] == -10.0
    assert summary["trade_count"] == 2


def test_simulation_summary_contains_statistical_and_cost_metrics() -> None:
    df, signals = deterministic_long_fixture()
    result = simulate_guiyuan(df, signals, SPEC, initial_capital=100_000.0)

    summary = summarize_simulation("TEST", "测试", "real", result, len(df))

    assert summary["trade_count"] == 1
    assert 0.0 <= summary["win_rate_ci95_low"] <= summary["win_rate_ci95_high"] <= 100.0
    assert summary["fees"] > 0.0
    assert summary["slippage"] > 0.0
    assert summary["ledger_reconciled"]


def test_data_quality_detects_duplicate_and_invalid_ohlc() -> None:
    df, _ = deterministic_long_fixture()
    duplicate = pd.concat([df, df.iloc[[-1]]])
    duplicate.iloc[0, duplicate.columns.get_loc("high")] = 98.0

    quality = audit_bars("TEST", "real", duplicate)

    assert quality["duplicate_timestamps"] == 1
    assert quality["ohlc_errors"] == 1


def test_independent_regime_batches_keep_every_trade_and_reconcile() -> None:
    df, signals = deterministic_long_fixture()
    first = simulate_guiyuan(df, signals, SPEC, initial_capital=100_000.0)
    second = simulate_guiyuan(df, signals, SPEC, initial_capital=100_000.0)

    combined = combine_simulations([first, second], initial_capital=100_000.0)

    assert len(combined["trades"]) == 2
    assert combined["net_pnl"] == pytest.approx(first["net_pnl"] + second["net_pnl"])
    assert combined["final_equity"] == pytest.approx(200_000.0 + combined["net_pnl"])
    assert combined["ledger_reconciled"]


def test_report_labels_synthetic_results(tmp_path: Path) -> None:
    result = {
        "metrics": pd.DataFrame(
            [
                {"symbol": "TEST", "name": "测试", "track": "real", "trade_count": 2,
                 "win_rate_pct": 50.0, "profit_factor": 0.8, "net_pnl": -10.0,
                 "max_drawdown_pct": 1.0, "sharpe": -0.2, "status": "REJECTED"},
                {"symbol": "TEST", "name": "测试", "track": "synthetic", "trade_count": 1_001,
                 "win_rate_pct": 55.0, "profit_factor": 1.2, "net_pnl": 999.0,
                 "max_drawdown_pct": 2.0, "sharpe": 0.5, "status": "REJECTED",
                 "holdout_net_pnl": 10.0, "stress_3x_net_pnl": 2.0,
                 "parameter_profitable": 12},
            ]
        ),
        "trades": pd.DataFrame(),
        "quality": pd.DataFrame(),
        "regime_metrics": pd.DataFrame(),
        "parameter_metrics": pd.DataFrame(),
        "summary": {
            "status": "REJECTED",
            "real": {"net_pnl": -10.0, "trade_count": 2},
            "synthetic": {
                "net_pnl": 999.0,
                "trade_count": 1_001,
                "min_symbol_trades": 1_001,
                "all_symbols_over_1000": True,
            },
        },
    }

    write_report(tmp_path, result)
    report = (tmp_path / "report.md").read_text(encoding="utf-8")

    assert "合成压力轨，不是历史绩效" in report
    assert "REJECTED" in report
    assert (tmp_path / "report.json").exists()
    assert (tmp_path / "symbol_metrics.csv").exists()
