from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest


CODE_DIR = Path(__file__).resolve().parents[1] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from run_guiyuan_15m_lln_audit import (  # noqa: E402
    lln_gate,
    simulate_guiyuan,
    summarize_portfolio,
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

