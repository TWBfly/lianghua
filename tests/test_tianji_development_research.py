import inspect

import numpy as np
import pandas as pd

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

