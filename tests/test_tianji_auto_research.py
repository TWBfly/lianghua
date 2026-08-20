import dataclasses
import inspect
import random

import numpy as np
import pandas as pd
import pytest

import futures_research_backtest as research
import tianji_auto_research as auto


def test_auto_research_grammar_has_exact_stable_counts():
    signals = auto.signal_specs()
    risks = auto.risk_specs()
    assert len(signals) == 16
    assert len(risks) == 32
    assert len({spec.id for spec in signals}) == 16
    assert len({spec.id for spec in risks}) == 32
    assert all(dataclasses.is_dataclass(spec) for spec in (*signals, *risks))


def test_search_hash_and_candidate_ids_ignore_input_order():
    signals = list(auto.signal_specs())
    risks = list(auto.risk_specs())
    expected_hash = auto.search_space_hash(signals, risks)
    expected_ids = sorted(
        spec.id for spec in auto.candidate_specs(signals, risks)
    )
    random.Random(7).shuffle(signals)
    random.Random(8).shuffle(risks)
    assert auto.search_space_hash(signals, risks) == expected_hash
    assert sorted(
        spec.id for spec in auto.candidate_specs(signals, risks)
    ) == expected_ids


def test_runtime_search_specs_have_no_predictive_fields():
    fields = {
        field.name
        for cls in (auto.SignalSpec, auto.RiskSpec, auto.CandidateSpec)
        for field in dataclasses.fields(cls)
    }
    assert fields.isdisjoint({"label", "prediction", "probability", "model"})
    assert all(
        token not in inspect.getsource(auto.signal_specs)
        for token in ("label", "predict", "probability")
    )


def auto_score_fixture():
    symbols = (
        "AG_IDX", "AU_IDX", "AL_IDX", "CU_IDX", "RB_IDX", "I_IDX",
        "SC_IDX", "FU_IDX", "MA_IDX", "TA_IDX", "M_IDX", "C_IDX",
        "CF_IDX", "SR_IDX", "IF_IDX", "IC_IDX", "RU_IDX", "SA_IDX",
        "SN_IDX", "ZN_IDX",
    )
    frame = pd.DataFrame({
        "decision_time": pd.Timestamp("2026-01-02 09:00"),
        "symbol": symbols,
        "signal_ready": True,
        "score": np.linspace(0.01, 0.99, len(symbols)),
        "atr": 2.0,
        "atr_pct": 0.02,
        "sector": [research.TIANJI_SECTORS[symbol] for symbol in symbols],
    })
    for column in (
        "signed_kaufman_efficiency_20", "donchian_position_20",
        "momentum_acceleration_5_20", "intraday_intensity_10",
        "signed_kaufman_efficiency_40", "donchian_position_40",
        "momentum_acceleration_10_40", "intraday_intensity_20",
    ):
        frame[column] = np.linspace(-1.0, 1.0, len(frame))
    return frame


def test_auto_target_builder_serializes_risk_spec_and_forbids_holdout():
    scores = auto_score_fixture()
    candidate = auto.CandidateSpec(
        auto.signal_specs()[0], auto.risk_specs()[0]
    )

    targets, _ = auto.build_auto_targets(
        scores,
        candidate,
        pd.DatetimeIndex(scores["decision_time"].unique()),
    )

    assert {
        "initial_stop_atr", "trail_activation_r", "trail_distance_atr",
        "side_exposure",
    }.issubset(targets.columns)
    scores.loc[0, "decision_time"] = auto.FORBIDDEN_HOLDOUT_START
    with pytest.raises(research.ResearchRejected, match="holdout"):
        auto.build_auto_targets(
            scores,
            candidate,
            pd.DatetimeIndex(scores["decision_time"].unique()),
        )
