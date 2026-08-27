import numpy as np
import pandas as pd
try:
    import pytest
except ImportError:
    pytest = None
from pathlib import Path

import sync_calendar_spread_pairs as sync_module
from taiyin_calendar_spread_15m import CommodityCarryCostProfile
import taiyin_calendar_spread_100pct_real as real_module
from taiyin_calendar_spread_100pct_real import Taiyin100PctRealSpreadEngine


def make_leg(closes, opens=None, volumes=None):
    closes = np.asarray(closes, dtype=float)
    opens = closes if opens is None else np.asarray(opens, dtype=float)
    volumes = np.full(len(closes), 100.0) if volumes is None else volumes
    return pd.DataFrame({
        "trade_time": pd.date_range(
            "2026-01-01 09:00", periods=len(closes), freq="15min"
        ).astype(str),
        "open": opens,
        "high": np.maximum(opens, closes),
        "low": np.minimum(opens, closes),
        "close": closes,
        "volume": volumes,
    })


def fixture_inputs(
    spreads,
    *,
    near_opens=None,
    near_volumes=None,
):
    far = np.full(len(spreads), 50.0)
    near = far + np.asarray(spreads, dtype=float)
    profile = CommodityCarryCostProfile(
        "TEST",
        "test",
        multiplier=1.0,
        tick_size=1.0,
        annual_interest_rate=0.0,
        storage_fee_per_day=0.0,
        delivery_fee_fixed=0.0,
        vat_capital_drag=0.0,
        default_lots=1,
    )
    pair = {
        "symbol": "TEST",
        "near": "TEST.n",
        "far": "TEST.f",
        "name": "test",
        "days_between_contracts": 30,
    }
    return make_leg(near, near_opens, near_volumes), make_leg(far), profile, pair


def run_fixture(
    spreads,
    *,
    near_opens=None,
    near_volumes=None,
    initial_capital=1_000.0,
    fee_rate=0.0,
    slippage_ticks=0.0,
):
    near, far, profile, pair = fixture_inputs(
        spreads, near_opens=near_opens, near_volumes=near_volumes
    )
    return Taiyin100PctRealSpreadEngine(
        z_entry=0.5, z_exit=0.2, z_stop=3.5, lookback_window=2
    ).run_pair_real_backtest(
        near, far, profile, pair,
        initial_capital=initial_capital,
        fee_rate=fee_rate,
        slippage_ticks=slippage_ticks,
    )


def test_signal_fills_on_next_open():
    spreads = [50] * 10 + [30, 50, 50, 50]
    near_opens = [100] * 10 + [80, 77, 103, 100]

    result = run_fixture(spreads, near_opens=near_opens)

    trade = result["trades"].iloc[0]
    assert trade["entry_time"] == "2026-01-01 11:45:00"
    assert trade["entry_spread"] == 27.0
    assert trade["exit_time"] == "2026-01-01 12:00:00"
    assert trade["exit_spread"] == 53.0


def test_next_open_fill_does_not_peek_at_fill_bar_volume():
    spreads = [50] * 10 + [30, 50, 50, 50]
    volumes = [100] * 11 + [0, 100, 100]

    result = run_fixture(spreads, near_volumes=volumes)

    assert result["trades"].iloc[0]["entry_time"] == "2026-01-01 11:45:00"


def test_illiquid_exit_waits_for_a_completed_liquid_bar():
    spreads = [50] * 10 + [30, 20, 50, 50, 50, 50]
    volumes = [100] * 12 + [0, 100, 100, 100]
    near_opens = [100] * 10 + [80, 80, 70, 100, 100, 100]

    result = run_fixture(
        spreads, near_opens=near_opens, near_volumes=volumes
    )

    trade = result["trades"].iloc[0]
    assert trade["exit_time"] == "2026-01-01 12:30:00"


def test_metrics_use_net_pnl_and_mark_to_market_equity():
    spreads = [50] * 10 + [30, 30, 30, 30]

    result = run_fixture(
        spreads, fee_rate=0.001, slippage_ticks=1.0
    )

    trade = result["trades"].iloc[0]
    assert trade["net_pnl"] < trade["gross_pnl"]
    assert result["win_rate_pct"] == 0.0
    assert result["max_drawdown_pct"] > 0.0
    assert result["ledger_reconciled"] is True


def test_unrealized_loss_is_included_in_drawdown():
    spreads = [50] * 10 + [30, 20, 50, 50]
    near_opens = [100] * 10 + [80, 80, 70, 100]

    result = run_fixture(spreads, near_opens=near_opens)

    assert result["max_drawdown_pct"] >= 1.0


def test_end_of_data_reports_unclosed_when_last_bar_is_illiquid():
    spreads = [50] * 10 + [30, 30]
    volumes = [100] * 11 + [0]

    result = run_fixture(spreads, near_volumes=volumes)

    assert result["unclosed_position"] is True
    assert result["ledger_reconciled"] is False


def test_validation_requires_enough_holdout_trades():
    assert real_module.classify_validation(8, 1, 16, 1, True, False) == "INSUFFICIENT_EVIDENCE"


def test_validation_rejects_observed_failure():
    assert real_module.classify_validation(40, -1, 16, 1, True, False) == "REJECTED"
    assert real_module.classify_validation(40, 1, 16, 1, False, False) == "REJECTED"
    assert real_module.classify_validation(40, 1, 16, 1, True, True) == "REJECTED"


def test_validation_passes_only_all_observed_gates():
    assert real_module.classify_validation(40, 1, 12, 1, True, False) == "BACKTEST_VALIDATED"


def test_validate_pair_reports_observed_fields():
    spreads = ([50] * 10 + [30, 20, 50, 50]) * 20
    near, far, profile, pair = fixture_inputs(spreads)

    result = real_module.validate_pair(near, far, profile, pair)

    assert set(result) >= {
        "full",
        "holdout",
        "profitable_parameter_sets",
        "triple_cost_net_profit",
        "status",
    }
    assert result["status"] in {
        "BACKTEST_VALIDATED",
        "INSUFFICIENT_EVIDENCE",
        "REJECTED",
    }


def test_every_pair_has_real_contract_interval():
    intervals = {pair["days_between_contracts"] for pair in sync_module.CALENDAR_SPREAD_PAIRS}
    assert intervals <= {30, 92, 122, 183}


def test_missing_tq_credentials_fail_closed(monkeypatch, tmp_path):
    monkeypatch.delenv("TQ_ACCOUNT", raising=False)
    monkeypatch.delenv("TQ_PASSWORD", raising=False)
    monkeypatch.setattr(sync_module, "ENV_PATH", str(tmp_path / "missing.env"))

    with pytest.raises(RuntimeError, match="TQ_ACCOUNT"):
        sync_module.load_tq_credentials()


def test_tq_credentials_prefer_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("TQ_ACCOUNT", "environment-user")
    monkeypatch.setenv("TQ_PASSWORD", "environment-password")
    monkeypatch.setattr(sync_module, "ENV_PATH", str(tmp_path / "missing.env"))

    assert sync_module.load_tq_credentials() == (
        "environment-user",
        "environment-password",
    )


def test_synthetic_runner_is_explicitly_labeled():
    source = Path("code/taiyin_calendar_spread_15m.py").read_text(encoding="utf-8")
    assert "SYNTHETIC RESEARCH ONLY" in source
