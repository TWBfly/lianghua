import dataclasses
import hashlib
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


def test_stage1_keeps_at_most_four_with_stable_order():
    rows = pd.DataFrame([
        {
            "signal_id": f"s{number:02d}",
            "worst_payoff": number / 10,
            "worst_return": number / 100,
            "turnover": 20 - number,
        }
        for number in range(16)
    ])

    survivors = auto.select_stage1_survivors(rows)

    assert len(survivors) == 4
    assert survivors["signal_id"].tolist() == ["s15", "s14", "s13", "s12"]


def test_stage1_screen_evaluates_every_signal_on_three_folds():
    calls = []

    def evaluate(candidate, fold):
        calls.append((candidate.signal.id, fold))
        rank = auto.signal_specs().index(candidate.signal) + 1
        return {
            "payoff_ratio": rank / 10,
            "total_return": rank / 100,
            "turnover": 10.0,
        }

    survivors = auto.stage1_screen(
        auto.signal_specs(), (1, 2, 3), evaluate
    )

    assert len(calls) == 16 * 3
    assert len(survivors) == 4


def test_successive_halving_caps_128_to_32_to_8_deterministically():
    signals = auto.signal_specs()[:4]
    candidates = auto.candidate_specs(signals, auto.risk_specs())
    calls = []

    def evaluate(candidate, fold):
        calls.append((candidate.id, fold))
        rank = int(hashlib.sha256(candidate.id.encode()).hexdigest()[:8], 16)
        return {
            "candidate_id": candidate.id,
            "fold": fold,
            "payoff_ratio": 1.1 + rank % 100 / 100,
            "max_drawdown": 0.05,
            "total_return": 0.01,
            "trades": 80,
            "turnover": 10.0,
        }

    result = auto.successive_halving(candidates, evaluate)

    assert len(result["stage1"]) == 128
    assert len(result["stage2"]) == 32
    assert len(result["stage3"]) == 8
    assert len(calls) == 128 + 32 + 8


def test_auto_gates_require_all_hard_thresholds_and_positive_folds():
    metrics = {
        "payoff_ratio": 3.0,
        "max_drawdown": 0.15,
        "total_return": 0.01,
        "trades": 200,
        "fold_returns": [0.01, 0.02, 0.01],
    }
    assert auto.auto_development_gates(metrics)["passed"]
    metrics["fold_returns"][1] = 0.0
    assert not auto.auto_development_gates(metrics)["passed"]


def test_attach_auto_gates_handles_empty_stage3():
    frame = pd.DataFrame(columns=[
        "candidate_id", "payoff_ratio", "max_drawdown", "total_return",
        "trades", "turnover", "fold_returns",
    ])

    result = auto.attach_auto_gates(frame)

    assert result.empty
    assert "gates" in result.columns


def test_auto_status_never_claims_research_acceptance():
    assert auto.auto_status("candidate") == "AUTO_DEVELOPMENT_CANDIDATE"
    assert auto.auto_status(None) == "AUTO_DEVELOPMENT_REJECTED"


def test_robustness_attack_cannot_replace_original_candidate():
    original = auto.candidate_specs(
        auto.signal_specs()[:1], auto.risk_specs()[:1]
    )[0]
    attacks = auto.robustness_attacks(
        original,
        evaluate=lambda spec, attack: {
            "candidate_id": spec.id,
            "attack": attack,
            "total_return": 0.01,
            "max_drawdown": 0.10,
            "payoff_ratio": 3.1,
            "trades": 210,
        },
    )
    assert set(attacks["candidate_id"]) == {original.id}
    assert set(attacks["attack"]) == {
        "costs", "sector_exclusion", "top_symbol_exclusion",
        "entry_quantile_neighbor", "risk_neighbor", "prefix_invariance",
    }


def auto_report_fixture():
    return {
        "status": "AUTO_DEVELOPMENT_REJECTED",
        "selected_candidate": None,
        "selected_rule": None,
        "search_space": {"signals": [], "risks": [], "sha256": "a" * 64},
        "stage1_metrics": pd.DataFrame(),
        "stage2_metrics": pd.DataFrame(),
        "attack_metrics": pd.DataFrame(),
        "survivors": pd.DataFrame(),
        "stage_counts": {"stage1": 0, "stage2": 0, "stage3": 0},
        "gates": {},
        "limitations": ["development only"],
    }


def test_auto_report_bundle_is_atomic_and_refuses_overwrite(tmp_path):
    import run_tianji_auto_research as runner

    result = auto_report_fixture()
    output = runner.write_auto_report(result, tmp_path / "auto")
    expected = {
        "auto_research_report.json", "search_space.json", "stage1_metrics.csv",
        "stage2_metrics.csv", "attack_metrics.csv", "survivors.csv",
        "auto_research_report.md",
    }
    assert expected.issubset({path.name for path in output.iterdir()})
    with pytest.raises(FileExistsError):
        runner.write_auto_report(result, output)
