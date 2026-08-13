import numpy as np
import pandas as pd
import pytest

from ml_ensemble import (
    LABEL_HORIZON,
    RETRAIN_EVERY,
    TRAINING_WINDOW,
    build_label_frame,
    build_model_identity,
    causal_feature_frame,
    walk_forward_predict,
    walk_forward_splits,
)


def market_frame(rows=160):
    dates = pd.bdate_range("2025-01-01", periods=rows)
    close = 10 + np.arange(rows) * 0.03 + np.sin(np.arange(rows) / 5)
    volume = 1_000_000 + np.arange(rows) * 100
    return pd.DataFrame({
        "trade_date": dates.strftime("%Y-%m-%d"),
        "open": close - 0.02,
        "high": close + 0.10,
        "low": close - 0.10,
        "close": close,
        "volume": volume,
        "amount": close * volume,
        "pct_chg": pd.Series(close).pct_change().fillna(0).to_numpy() * 100,
    })


def factor_frame(df):
    index = pd.to_datetime(df["trade_date"])
    return pd.DataFrame({
        "rsi_14": 40 + np.arange(len(df)) * 0.1,
        "macd_hist": np.sin(np.arange(len(df)) / 8),
        "bias_20": np.zeros(len(df)),
    }, index=index)


def test_last_forward_window_labels_are_unknown():
    labels = build_label_frame(market_frame(20), forward_days=5)

    assert labels["label"].tail(5).isna().all()
    assert labels["label_end_time"].tail(5).isna().all()


def test_feature_prefix_does_not_change_when_future_rows_are_appended():
    short = market_frame(120)
    long = market_frame(160)

    short_features = causal_feature_frame(short, factor_frame(short))
    long_features = causal_feature_frame(long, factor_frame(long))

    pd.testing.assert_frame_equal(
        short_features,
        long_features.loc[short_features.index],
        check_dtype=False,
    )


def test_walk_forward_training_labels_mature_before_prediction():
    labels = build_label_frame(market_frame(160))

    splits = walk_forward_splits(
        labels,
        labels.index,
        min_train_size=40,
        retrain_every=5,
    )

    assert splits
    for split in splits:
        mature = labels.loc[split.train_index, "label_end_time"]
        assert (mature < split.prediction_start).all()
        assert split.prediction_start <= split.prediction_end


def test_walk_forward_predictions_report_training_cutoff():
    df = market_frame(160)

    result = walk_forward_predict(
        df,
        factor_frame(df),
        "000001",
        min_train_size=40,
        retrain_every=10,
    )

    covered = result.dropna(subset=["trained_until"])
    assert not covered.empty
    assert (
        pd.to_datetime(covered["trained_until"])
        < covered.index
    ).all()
    assert covered["probability"].between(0, 1).all()
    assert (
        result.loc[result["trained_until"].isna(), "model_version"]
        == "INSUFFICIENT_HISTORY"
    ).all()


def test_walk_forward_routes_each_prediction_row_by_its_own_regime(
        monkeypatch):
    import ml_ensemble

    routed = []
    probability_by_regime = {
        "LOW_VOL_BULL": 0.8,
        "HIGH_VOL_BEAR": 0.2,
        "RANGE": 0.5,
    }

    class IdentityModel:
        def get_params(self, deep=False):
            return {}

    class RecordingEnsemble:
        def __init__(self, base_factory=None):
            self.global_model = IdentityModel()

        def fit(self, features, target, regimes):
            return self

        def predict_proba(self, features, current_regime=None):
            routed.append((current_regime, len(features)))
            value = probability_by_regime[current_regime]
            return np.column_stack([
                np.full(len(features), 1.0 - value),
                np.full(len(features), value),
            ])

    monkeypatch.setattr(
        ml_ensemble, "RegimeConditionedMLEnsemble", RecordingEnsemble
    )
    monkeypatch.setattr(
        ml_ensemble, "build_model_identity", lambda *_args, **_kwargs: "v"
    )
    frame = market_frame(180)
    result = walk_forward_predict(
        frame,
        factor_frame(frame),
        "000001",
        min_train_size=40,
        max_train_size=40,
        retrain_every=21,
    )

    close = frame["close"]
    vol20 = close.pct_change().rolling(20).std()
    ma60 = close.rolling(60).mean()
    median = vol20.expanding(min_periods=20).median().fillna(0.02)
    expected_regime = np.where(
        (close >= ma60) & (vol20 < median),
        "LOW_VOL_BULL",
        np.where(close < ma60, "HIGH_VOL_BEAR", "RANGE"),
    )
    covered = result["model_version"].eq("v")
    expected = pd.Series(expected_regime, index=result.index).map(
        probability_by_regime
    )

    assert covered.any()
    assert len({state for state, _ in routed}) > 1
    pd.testing.assert_series_equal(
        result.loc[covered, "probability"],
        expected.loc[covered],
        check_names=False,
    )


def test_walk_forward_probabilities_are_prefix_invariant():
    short = market_frame(160)
    long = market_frame(180)
    kwargs = {
        "min_train_size": 40,
        "max_train_size": 40,
        "retrain_every": 21,
    }

    short_result = walk_forward_predict(
        short, factor_frame(short), "000001", **kwargs
    )
    long_result = walk_forward_predict(
        long, factor_frame(long), "000001", **kwargs
    )
    covered = short_result["probability"].notna()

    assert covered.any()
    pd.testing.assert_series_equal(
        short_result.loc[covered, "probability"],
        long_result.loc[short_result.index[covered], "probability"],
    )


def test_default_walk_forward_uses_latest_fixed_training_window():
    labels = build_label_frame(market_frame(800))

    splits = walk_forward_splits(labels, labels.index)

    assert splits
    assert len(splits[0].train_index) == TRAINING_WINDOW == 504
    mature = labels[
        labels["label"].notna()
        & (labels["label_end_time"] < splits[0].prediction_start)
    ]
    assert splits[0].train_index.equals(mature.index[-TRAINING_WINDOW:])
    assert LABEL_HORIZON == 5


def test_default_prediction_batches_advance_twenty_one_rows():
    labels = build_label_frame(market_frame(800))

    splits = walk_forward_splits(labels, labels.index)

    assert RETRAIN_EVERY == 21
    assert len(splits[0].prediction_index) == RETRAIN_EVERY
    assert splits[1].prediction_start == labels.index[
        labels.index.get_loc(splits[0].prediction_start) + RETRAIN_EVERY
    ]


def test_insufficient_history_never_uses_rule_fallback():
    df = market_frame(TRAINING_WINDOW)

    result = walk_forward_predict(df, factor_frame(df), "000001")

    assert result["probability"].isna().all()
    assert result["score"].isna().all()
    assert set(result["model_version"]) == {"INSUFFICIENT_HISTORY"}
    assert result["trained_until"].isna().all()


def test_walk_forward_rejects_invalid_policy_values():
    labels = build_label_frame(market_frame(20))

    with pytest.raises(ValueError, match="min_train_size"):
        walk_forward_splits(labels, labels.index, min_train_size=0)
    with pytest.raises(ValueError, match="retrain_every"):
        walk_forward_splits(labels, labels.index, retrain_every=0)
    with pytest.raises(ValueError, match="max_train_size"):
        walk_forward_splits(
            labels,
            labels.index,
            min_train_size=10,
            max_train_size=9,
        )


def test_model_identity_changes_with_data_parameters_and_policy():
    features = pd.DataFrame({"x": [1.0, 2.0]})
    target = pd.Series([0, 1])

    class Model:
        def __init__(self, depth=2):
            self.depth = depth

        def get_params(self, deep=False):
            return {"depth": self.depth}

    base = build_model_identity(
        "000001",
        pd.Timestamp("2025-01-01"),
        features,
        target,
        Model(),
        {"training_window": 504},
    )
    changed_data = build_model_identity(
        "000001",
        pd.Timestamp("2025-01-01"),
        features * 2,
        target,
        Model(),
        {"training_window": 504},
    )
    changed_model = build_model_identity(
        "000001",
        pd.Timestamp("2025-01-01"),
        features,
        target,
        Model(depth=3),
        {"training_window": 504},
    )
    changed_policy = build_model_identity(
        "000001",
        pd.Timestamp("2025-01-01"),
        features,
        target,
        Model(),
        {"training_window": 252},
    )

    assert len(base) == 16
    assert len({base, changed_data, changed_model, changed_policy}) == 4


def test_regime_conditioned_ml_ensemble_training_and_routing():
    from ml_ensemble import RegimeConditionedMLEnsemble

    np.random.seed(42)
    X = np.random.randn(150, 4)
    y = (X[:, 0] > 0).astype(int)

    # 50 bull, 50 bear, 50 range
    regimes = np.array(["LOW_VOL_BULL"] * 50 + ["HIGH_VOL_BEAR"] * 50 + ["RANGE"] * 50)

    ensemble = RegimeConditionedMLEnsemble()
    ensemble.fit(X, y, regimes)

    # Assert sub-models exist for regimes with sufficient samples
    assert set(ensemble.regime_models.keys()) == {"LOW_VOL_BULL", "HIGH_VOL_BEAR", "RANGE"}

    # Test prediction routing
    prob_bull = ensemble.predict_proba(X[:5], current_regime="LOW_VOL_BULL")
    prob_bear = ensemble.predict_proba(X[:5], current_regime="HIGH_VOL_BEAR")
    prob_fallback = ensemble.predict_proba(X[:5], current_regime="UNKNOWN_REGIME")

    assert prob_bull.shape == (5, 2)
    assert prob_bear.shape == (5, 2)
    assert prob_fallback.shape == (5, 2)
    np.testing.assert_allclose(
        prob_fallback,
        ensemble.global_model.predict_proba(X[:5]),
    )


def test_triple_barrier_labeling():
    from ml_ensemble import build_triple_barrier_labels

    df = market_frame(100)
    tb_labels = build_triple_barrier_labels(df, forward_days=5, pt_mult=1.5, sl_mult=1.0)

    assert "label" in tb_labels.columns
    assert "label_end_time" in tb_labels.columns
    assert set(tb_labels["label"].dropna().unique()).issubset({0.0, 1.0})
    assert tb_labels["label"].tail(5).isna().all()


def test_cross_sectional_quantile_ranking_engine():
    from ml_ensemble import cross_sectional_walk_forward_rank

    df1 = market_frame(160)
    df2 = market_frame(160)
    df2["close"] = df2["close"] * 1.5

    market_data = {"000001": df1, "000002": df2}
    ranked = cross_sectional_walk_forward_rank(
        market_data,
        top_quantile=0.50,
        min_train_size=40,
        retrain_every=10,
    )

    assert "000001" in ranked
    assert "000002" in ranked
    assert "cross_sectional_rank_pct" in ranked["000001"].columns
    assert "quantile_signal" in ranked["000001"].columns
