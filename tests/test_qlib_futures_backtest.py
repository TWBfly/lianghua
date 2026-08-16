from pathlib import Path

import numpy as np
import pandas as pd

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

    probability, model = qlib_model_adapter.fit_qlib_lightgbm(
        features.iloc[:400], labels.iloc[:400], weights.iloc[:400],
        features.iloc[400:], 42,
    )

    assert probability.shape == (100,)
    assert np.isfinite(probability).all()
    assert ((0.0 <= probability) & (probability <= 1.0)).all()
    assert model.get_params()["backend"] == "qlib.LGBModel"


def test_qlib_candidate_domain_contains_only_qlib_model():
    assert research.candidate_names("qlib") == ("qlib_lightgbm_constrained",)


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
