from pathlib import Path
import warnings

import numpy as np
import pandas as pd
import pytest

import futures_research_backtest as research


def test_qlib_backend_returns_finite_probabilities_and_audit_identity():
    import qlib_model_adapter

    rows = 500
    rng = np.random.default_rng(42)
    features = pd.DataFrame(
        rng.normal(size=(rows, len(research.FEATURE_COLUMNS))),
        columns=research.FEATURE_COLUMNS,
    )
    labels = pd.Series(np.arange(rows) % 2, name="label")
    weights = pd.Series(np.ones(rows), index=features.index)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        probability, model = qlib_model_adapter.fit_qlib_lightgbm(
            features.iloc[:400], labels.iloc[:400], weights.iloc[:400],
            features.iloc[400:], 42,
        )

    assert probability.shape == (100,)
    assert np.isfinite(probability).all()
    assert ((0.0 <= probability) & (probability <= 1.0)).all()
    assert model.get_params()["backend"] == "qlib.LGBModel"
    assert not any("Only training set found" in str(row.message) for row in caught)


def test_qlib_domain_competes_with_one_simple_model():
    assert research.candidate_names("qlib") == (
        "logistic_c0.1", "qlib_lightgbm_constrained",
    )


def test_qlib_dataset_does_not_duplicate_train_as_validation():
    import qlib_model_adapter as adapter

    train = pd.concat({
        "feature": pd.DataFrame({"x": [0.0, 1.0]}),
        "label": pd.DataFrame({"label": [0, 1]}),
    }, axis=1)
    test = pd.concat({"feature": pd.DataFrame({"x": [0.5]})}, axis=1)
    dataset = adapter._FrameDataset(train, test)

    assert set(dataset.segments) == {"train", "test"}
    with pytest.raises(KeyError):
        dataset.prepare("valid", ["feature", "label"])


def test_official_config_requires_embargo_at_least_horizon():
    with pytest.raises(research.ResearchRejected, match="embargo"):
        research._validate_research_config(
            research.ResearchConfig(horizon=6, embargo_bars=5)
        )


def test_qlib_backend_routes_logistic_candidate_to_logistic(monkeypatch):
    import qlib_model_adapter

    def forbidden(*_args, **_kwargs):
        raise AssertionError("logistic candidate was routed through Qlib")

    monkeypatch.setattr(qlib_model_adapter, "fit_qlib_lightgbm", forbidden)
    rng = np.random.default_rng(7)
    train = pd.DataFrame(
        rng.normal(size=(400, len(research.FEATURE_COLUMNS))),
        columns=research.FEATURE_COLUMNS,
    )
    evaluation = train.iloc[:20].copy()
    labels = pd.Series(np.arange(len(train)) % 2)

    probability, model = research._fit_matrix(
        research.Candidate("logistic_c0.1", 0.55),
        train, labels, np.ones(len(train)), evaluation,
        research.ResearchConfig(model_backend="qlib"),
    )

    assert probability.shape == (len(evaluation),)
    assert "logisticregression" in model.named_steps


def test_report_bundle_contains_self_contained_qlib_html_for_rejection(tmp_path):
    result = research.rejected_result(
        "run",
        research.ResearchConfig(timeframe="15m", model_backend="qlib"),
        "fixture rejection",
    )

    paths = research.write_report(result, tmp_path / "report")

    html = Path(paths["report.html"]).read_text(encoding="utf-8")
    assert "RESEARCH_REJECTED" in html
    assert research.DISCLAIMER in html
    assert "fixture rejection" in html
    assert "Qlib" in html
    assert "15m" in html
    assert "https://" not in html and "http://" not in html
