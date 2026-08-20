import inspect
import json

import numpy as np
import pandas as pd
import pytest

import futures_research_backtest as research
import tianji_development_research as development


def test_development_folds_are_chronological_and_before_viewed_holdout():
    times = pd.date_range("2025-10-16", "2026-06-26 10:30", freq="15min")

    folds = development.development_folds(
        times, pd.Timestamp("2026-06-26 10:45")
    )

    assert len(folds) == 3
    assert all(
        fold.max() < pd.Timestamp("2026-06-26 10:45") for fold in folds
    )
    assert all(
        left.max() < right.min() for left, right in zip(folds, folds[1:])
    )


def test_development_candidate_domain_is_exact_and_non_predictive():
    assert development.CANDIDATES == (
        "continuation", "reversal", "timeseries_donchian"
    )
    source = inspect.getsource(development.candidate_targets)
    assert all(
        word not in source for word in ("label", "probability", "predict")
    )


def _candidate_score_fixture():
    symbols = (
        "AG_IDX", "AU_IDX", "AL_IDX", "CU_IDX", "RB_IDX", "I_IDX",
        "SC_IDX", "FU_IDX", "MA_IDX", "TA_IDX", "M_IDX", "C_IDX",
        "CF_IDX", "SR_IDX", "IF_IDX", "IC_IDX", "RU_IDX", "SA_IDX",
        "SN_IDX", "ZN_IDX",
    )
    time = pd.Timestamp("2026-01-02 09:00")
    scores = pd.DataFrame({
        "decision_time": time,
        "symbol": symbols,
        "signal_ready": True,
        "score": np.linspace(0.01, 0.99, len(symbols)),
        "signed_kaufman_efficiency_20": 0.0,
        "donchian_position_20": 0.0,
        "momentum_acceleration_5_20": 0.0,
        "intraday_intensity_10": 0.0,
        "prior_breakout_up_20": False,
        "prior_breakout_down_20": False,
        "atr": 2.0,
        "atr_pct": 0.02,
        "sector": [research.TIANJI_SECTORS[symbol] for symbol in symbols],
    })
    shorts = scores.nsmallest(2, "score").index
    longs = scores.nlargest(2, "score").index
    scores.loc[longs, [
        "signed_kaufman_efficiency_20", "donchian_position_20",
        "momentum_acceleration_5_20", "intraday_intensity_10",
    ]] = [0.5, 0.9, 0.1, 0.5]
    scores.loc[shorts, [
        "signed_kaufman_efficiency_20", "donchian_position_20",
        "momentum_acceleration_5_20", "intraday_intensity_10",
    ]] = [-0.5, -0.9, -0.1, -0.5]
    return scores, pd.DatetimeIndex([time])


def test_candidate_targets_are_sparse_paired_and_use_three_r_trailing():
    scores, fold = _candidate_score_fixture()

    targets, _ = development.candidate_targets(
        scores, pd.DataFrame(), "continuation", fold
    )

    assert targets["direction"].eq(1).sum() == 2
    assert targets["direction"].eq(-1).sum() == 2
    assert targets["trail_activation_r"].eq(3.0).all()


def test_development_gates_require_payoff_three_drawdown_and_positive_return():
    passing = {
        "payoff_ratio": 3.0,
        "max_drawdown": 0.15,
        "total_return": 0.01,
        "trades": 200,
    }
    assert development.development_gates(passing)["passed"]
    for name, value in (
        ("payoff_ratio", 2.99),
        ("max_drawdown", 0.151),
        ("total_return", 0.0),
        ("trades", 199),
    ):
        metrics = {**passing, name: value}
        assert not development.development_gates(metrics)["passed"]


def test_development_selection_uses_worst_fold_then_drawdown_then_turnover():
    rows = pd.DataFrame([
        {
            "candidate": "continuation", "eligible": True,
            "worst_payoff": 3.2, "worst_drawdown": 0.12,
            "turnover": 10.0,
        },
        {
            "candidate": "reversal", "eligible": True,
            "worst_payoff": 3.2, "worst_drawdown": 0.10,
            "turnover": 12.0,
        },
        {
            "candidate": "timeseries_donchian", "eligible": True,
            "worst_payoff": 3.1, "worst_drawdown": 0.08,
            "turnover": 5.0,
        },
    ])

    assert development.select_development_candidate(rows) == "reversal"


def test_development_status_never_claims_research_acceptance():
    assert (
        development.development_status("continuation")
        == "DEVELOPMENT_CANDIDATE"
    )
    assert development.development_status(None) == "DEVELOPMENT_REJECTED"


def test_development_report_is_atomic_and_refuses_overwrite(tmp_path):
    import run_tianji_development_research as runner

    result = {
        "status": "DEVELOPMENT_REJECTED",
        "selected_candidate": None,
        "candidate_metrics": pd.DataFrame([{
            "candidate": "continuation",
            "eligible": False,
            "gates": {"passed": False},
        }]),
        "fold_metrics": pd.DataFrame(),
        "stress_metrics": pd.DataFrame(),
        "quality": pd.DataFrame(),
        "forbidden_holdout_start": pd.Timestamp("2026-06-26 10:45"),
        "limitations": ("development only",),
    }

    output = runner.write_development_report(result, tmp_path / "report")

    payload = json.loads((output / "development_report.json").read_text())
    assert payload["status"] == "DEVELOPMENT_REJECTED"
    assert (output / "candidate_metrics.csv").is_file()
    assert (output / "development_report.md").is_file()
    with pytest.raises(FileExistsError):
        runner.write_development_report(result, output)
