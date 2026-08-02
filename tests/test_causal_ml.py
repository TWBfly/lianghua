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
