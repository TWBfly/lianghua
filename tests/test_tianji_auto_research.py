import dataclasses
import inspect
import random

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

