import hashlib
import inspect
import json
import shlex
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import futures_research_backtest as research
from futures_research_backtest import (
    Candidate,
    FEATURE_COLUMNS,
    ResearchConfig,
    ResearchRejected,
    assert_feature_columns,
    build_causal_dataset,
    candidate_names,
    choose_from_scores,
    fit_predict,
    inverse_symbol_class_weights,
    load_futures_bars,
    make_temporal_partitions,
    purged_training_rows,
    select_candidate,
    simulate_standardized_ledger,
    strategy_metrics,
    validate_and_segment,
)
from import_futures_5m import ensure_schema


def make_bars(rows, symbol="AG_IDX"):
    times = pd.date_range("2026-01-02 09:00:00", periods=rows, freq="5min")
    close = np.arange(100.0, 100.0 + rows)
    return pd.DataFrame({
        "symbol": symbol,
        "trade_time": times,
        "open": close - 0.25,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": 1.0,
        "open_interest": 1.0,
    })


def make_tianji_market(periods=80, symbols=None):
    symbols = symbols or (
        "AG_IDX", "AU_IDX", "CU_IDX", "AL_IDX",
        "RB_IDX", "I_IDX", "MA_IDX", "M_IDX",
    )
    times = pd.date_range("2026-01-02 09:00", periods=periods, freq="15min")
    rows = []
    for number, symbol in enumerate(symbols, start=1):
        close = 100.0 + number + np.arange(periods) * (0.02 * number)
        volume = 1_000.0 + number * 10 + np.arange(periods)
        for index, time in enumerate(times):
            rows.append({
                "symbol": symbol,
                "segment_id": f"{symbol}:1",
                "feature_segment_id": f"{symbol}:features",
                "trade_time": time,
                "open": close[index] - 0.1,
                "high": close[index] + 0.5,
                "low": close[index] - 0.5,
                "close": close[index],
                "volume": volume[index],
            })
    return pd.DataFrame(rows)


def test_tianji_contract_is_non_predictive_and_15m_only():
    domain = research._research_domain(ResearchConfig(
        strategy_mode="tianji", timeframe="15m"
    ))

    assert domain["strategy_mode"] == "tianji"
    assert domain["predictive"] is False
    assert domain["selectable_models"] == []
    assert domain["thresholds"] == []
    assert domain["candidate_threshold_pairs"] == 0
    with pytest.raises(ResearchRejected, match="15m"):
        research._validate_research_config(ResearchConfig(strategy_mode="tianji"))
    with pytest.raises(ResearchRejected, match="holdout_fraction"):
        research._validate_research_config(ResearchConfig(
            strategy_mode="tianji", timeframe="15m", holdout_fraction=0.25
        ))
    with pytest.raises(ResearchRejected, match="costs_bps"):
        research._validate_research_config(ResearchConfig(
            strategy_mode="tianji", timeframe="15m", costs_bps=(5,)
        ))


def test_tianji_score_prefix_is_unchanged_by_future_bars():
    market = make_tianji_market(90)
    cutoff = market["trade_time"].sort_values().unique()[70]
    prefix = market[market["trade_time"] <= cutoff]

    expected = research.build_tianji_scores(prefix)
    actual = research.build_tianji_scores(market)
    actual = actual[actual["decision_time"] <= cutoff].reset_index(drop=True)

    pd.testing.assert_frame_equal(expected.reset_index(drop=True), actual)
    assert {"label", "future_return", "probability"}.isdisjoint(actual.columns)


def _write_source(
        db_path, bars, series_type="WEIGHTED_INDEX", metadata=True,
        source_sha256="a" * 64):
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        conn.executemany(
            "INSERT INTO futures_min_bars (symbol, timeframe, trade_time, open, high, low, "
            "close, volume, open_interest) VALUES (?, '5m', ?, ?, ?, ?, ?, ?, ?)",
            [
                (row["symbol"], row["trade_time"].strftime("%Y-%m-%d %H:%M:%S"), row["open"],
                 row["high"], row["low"], row["close"], row["volume"], row["open_interest"])
                for _, row in bars.iterrows()
            ],
        )
        if metadata:
            if series_type == "OTHER":
                conn.execute("PRAGMA ignore_check_constraints = TRUE")
            for symbol in bars["symbol"].unique():
                conn.execute(
                    "INSERT INTO futures_series_metadata VALUES (?, '5m', 'source.txt', 'weighted', ?, "
                    "'gb18030', ?, 1, '2026-01-02 09:00:00', '2026-01-02 09:00:00', 'now')",
                    (symbol, series_type, source_sha256),
                )


@pytest.mark.parametrize("metadata,series_type", [(False, "WEIGHTED_INDEX"), (True, "OTHER")])
def test_load_rejects_missing_or_non_weighted_metadata(tmp_path, metadata, series_type):
    db_path = tmp_path / "futures.db"
    _write_source(db_path, make_bars(2), series_type, metadata)

    with pytest.raises(ResearchRejected):
        load_futures_bars(db_path)


def test_load_rejects_null_timestamp(tmp_path):
    db_path = tmp_path / "futures.db"
    _write_source(db_path, make_bars(2))
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE futures_min_bars SET trade_time=NULL")

    with pytest.raises(ResearchRejected):
        load_futures_bars(db_path)


def test_load_rejects_offset_aware_timestamp(tmp_path):
    db_path = tmp_path / "futures.db"
    _write_source(db_path, make_bars(2))
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE futures_min_bars SET trade_time=trade_time || '+00:00'")

    with pytest.raises(ResearchRejected, match="timezone-aware"):
        load_futures_bars(db_path)


def test_load_rejects_noncanonical_source_hash(tmp_path):
    db_path = tmp_path / "futures.db"
    _write_source(db_path, make_bars(2), source_sha256="hash")

    with pytest.raises(ResearchRejected, match="source SHA256"):
        load_futures_bars(db_path)


def test_validation_segments_every_unusable_boundary():
    bars = make_bars(40)
    bars.loc[10:, "trade_time"] += pd.Timedelta(minutes=5)
    bars.loc[20, "volume"] = 0.0
    bars.loc[30, "open"] = bars.loc[29, "close"] * 1.04
    bars.loc[30, "high"] = max(bars.loc[30, "high"], bars.loc[30, "open"])

    clean, quality = validate_and_segment(
        bars, ResearchConfig(min_symbol_rows=1, min_fold_rows=1)
    )

    changes = clean["segment_id"].ne(clean["segment_id"].shift()).to_numpy()
    assert changes[[0, 10, 20, 21, 30]].all()
    assert quality.loc["AG_IDX", "status"] == "INCLUDED"


def test_symbol_above_zero_volume_limit_is_excluded():
    bars = make_bars(20)
    bars.loc[:10, "volume"] = 0.0

    clean, quality = validate_and_segment(
        bars, ResearchConfig(min_symbol_rows=1, min_fold_rows=1)
    )

    assert clean.empty
    assert quality.loc["AG_IDX", "reason"] == "ZERO_VOLUME_FRACTION"


def test_close_jump_starts_a_new_segment():
    bars = make_bars(3)
    bars.loc[1, "close"] = bars.loc[0, "close"] * 1.04
    bars.loc[1, "high"] = max(bars.loc[1, "high"], bars.loc[1, "close"])

    clean, _ = validate_and_segment(bars, ResearchConfig(min_symbol_rows=1, min_fold_rows=1))

    assert clean["segment_id"].iloc[1] != clean["segment_id"].iloc[0]


def test_mixed_timezone_timestamps_are_rejected():
    bars = make_bars(3)
    bars["trade_time"] = bars["trade_time"].astype(object)
    bars.loc[1, "trade_time"] = pd.Timestamp("2026-01-02 09:05:00+00:00")

    with pytest.raises(ResearchRejected, match="timezone-aware"):
        validate_and_segment(bars, ResearchConfig(min_symbol_rows=1, min_fold_rows=1))


def test_pure_timezone_aware_timestamps_are_rejected():
    bars = make_bars(3)
    bars["trade_time"] = bars["trade_time"].dt.tz_localize("UTC")

    with pytest.raises(ResearchRejected, match="timezone-aware"):
        validate_and_segment(bars, ResearchConfig(min_symbol_rows=1, min_fold_rows=1))


def test_empty_structurally_correct_bars_fail_closed():
    bars = make_bars(0)

    with pytest.raises(ResearchRejected, match="no futures bars"):
        validate_and_segment(bars)


def test_non_null_optional_source_values_must_be_finite():
    bars = make_bars(3)
    bars["settlement"] = [100.0, "not-a-number", 102.0]

    with pytest.raises(ResearchRejected):
        validate_and_segment(bars, ResearchConfig(min_symbol_rows=1, min_fold_rows=1))


def make_segmented_bars(rows=120, symbol="AG_IDX", segment_id=None, start="2026-01-02 09:00"):
    bars = make_bars(rows, symbol)
    bars["trade_time"] = pd.date_range(start, periods=rows, freq="5min")
    bars["volume"] = np.arange(1.0, rows + 1.0)
    bars["segment_id"] = segment_id or f"{symbol}:1"
    return bars


def make_causal_evaluation_fixture(days=161):
    frames = []
    for symbol_number, symbol in enumerate(("AG_IDX", "CU_IDX")):
        for day_number, day in enumerate(pd.bdate_range("2025-01-02", periods=days)):
            direction = 1.0 if day_number % 2 == 0 else -1.0
            times = pd.date_range(day + pd.Timedelta(hours=9), periods=64, freq="5min")
            opens = (100.0 + symbol_number * 10.0) * np.exp(
                direction * 0.001 * np.arange(len(times))
            )
            closes = opens * (1.0 + direction * 0.0002)
            frames.append(pd.DataFrame({
                "symbol": symbol,
                "segment_id": f"{symbol}:{day.date()}",
                "trade_time": times,
                "open": opens,
                "high": np.maximum(opens, closes) * 1.001,
                "low": np.minimum(opens, closes) * 0.999,
                "close": closes,
                "volume": 100.0 + np.arange(len(times)) + np.arange(len(times)) % 3,
            }))
    segmented = pd.concat(frames, ignore_index=True)
    dataset = build_causal_dataset(segmented)
    return dataset, segmented


def test_causal_label_uses_next_open_to_six_bar_exit_open_and_stays_in_segment():
    bars = make_segmented_bars()
    dataset = build_causal_dataset(bars, ResearchConfig(horizon=6))
    decision = bars.iloc[60]
    row = dataset.loc[dataset["decision_time"].eq(decision.trade_time)].iloc[0]

    assert row.entry_time == bars.iloc[61].trade_time
    assert row.exit_time == bars.iloc[67].trade_time
    assert row.entry_open == pytest.approx(bars.iloc[61].open)
    assert row.exit_open == pytest.approx(bars.iloc[67].open)
    assert row.future_return == pytest.approx(bars.iloc[67].open / bars.iloc[61].open - 1)
    assert row.label == 1

    segmented = bars.copy()
    segmented.loc[64:, "segment_id"] = "AG_IDX:2"
    broken = build_causal_dataset(segmented, ResearchConfig(horizon=6))
    assert decision.trade_time not in set(broken["decision_time"])


@pytest.mark.parametrize("horizon", [-1, 0, 1.5, True], ids=["negative", "zero", "fractional", "bool"])
def test_causal_label_rejects_invalid_horizon_before_backward_exit(horizon):
    with pytest.raises(ResearchRejected, match="horizon"):
        build_causal_dataset(make_segmented_bars(), ResearchConfig(horizon=horizon))


def test_causal_dataset_prefix_is_unchanged_when_future_bars_are_appended():
    bars = make_segmented_bars()
    before = build_causal_dataset(bars, ResearchConfig(horizon=6)).reset_index(drop=True)
    extended = pd.concat([bars, make_segmented_bars(10, start="2026-01-02 19:00")], ignore_index=True)
    after = build_causal_dataset(extended, ResearchConfig(horizon=6))
    prefix = after[after["decision_time"].isin(before["decision_time"])].reset_index(drop=True)

    pd.testing.assert_frame_equal(before, prefix)


def test_feature_whitelist_rejects_future_and_unknown_columns():
    matrix = pd.DataFrame({name: [0.0] for name in FEATURE_COLUMNS})
    assert_feature_columns(matrix)
    with pytest.raises(ResearchRejected, match="feature whitelist"):
        assert_feature_columns(matrix.assign(future_return=1.0))
    with pytest.raises(ResearchRejected, match="feature whitelist"):
        assert_feature_columns(matrix.assign(symbol_code=1.0))


def make_partition_dataset():
    times = pd.date_range("2020-01-01", periods=1500, freq="D")
    rows = []
    for symbol in ("AG_IDX", "CU_IDX"):
        rows.append(pd.DataFrame({
            "symbol": symbol,
            "decision_time": times,
            "label_end_time": times + pd.Timedelta(days=1),
        }))
    return pd.concat(rows, ignore_index=True)


def test_temporal_partitions_lock_holdout_and_purge_labels_and_embargo():
    dataset = make_partition_dataset()
    config = ResearchConfig(min_symbols=2, min_fold_rows=50, embargo_bars=6)
    partitions = make_temporal_partitions(dataset, config)
    times = pd.DatetimeIndex(dataset["decision_time"].unique()).sort_values()
    holdout = partitions["holdout_fold"]

    assert holdout.evaluation_times[0] == times[int(np.floor(0.8 * len(times)))]
    outer = partitions["outer_folds"]
    assert len(outer) == 3
    assert pd.DatetimeIndex(np.concatenate([fold.evaluation_times for fold in outer])).is_monotonic_increasing
    assert len(set().union(*(set(fold.evaluation_times) for fold in outer))) == sum(len(fold.evaluation_times) for fold in outer)

    fold = outer[0]
    purged = purged_training_rows(dataset, fold.train_times, fold.evaluation_times[0], config.embargo_bars)
    assert (purged["label_end_time"] < fold.evaluation_times[0]).all()
    for symbol, group in dataset[dataset["decision_time"].isin(fold.train_times)].groupby("symbol"):
        eligible = group[group["label_end_time"] < fold.evaluation_times[0]].sort_values("decision_time")
        assert set(eligible.tail(config.embargo_bars).index).isdisjoint(purged.index)


def test_purge_excludes_label_ending_at_evaluation_start_without_embargo():
    evaluation_start = pd.Timestamp("2026-01-02 09:15")
    dataset = pd.DataFrame({
        "symbol": ["AG_IDX", "AG_IDX"],
        "decision_time": [evaluation_start - pd.Timedelta(minutes=10), evaluation_start - pd.Timedelta(minutes=5)],
        "label_end_time": [evaluation_start - pd.Timedelta(minutes=5), evaluation_start],
    })

    purged = purged_training_rows(dataset, dataset["decision_time"], evaluation_start, embargo_bars=0)

    assert purged.index.tolist() == [0]


def make_model_dataset(rows=460):
    decision_times = pd.date_range("2026-01-01", periods=rows, freq="20min")
    labels = np.arange(rows) % 2
    sign = labels * 2.0 - 1.0
    frames = []
    for symbol_number, symbol in enumerate(("AG_IDX", "CU_IDX")):
        frame = pd.DataFrame({
            "symbol": symbol,
            "segment_id": f"{symbol}:1",
            "decision_time": decision_times,
            "entry_time": decision_times + pd.Timedelta(minutes=5),
            "entry_open": 100.0,
            "exit_time": decision_times + pd.Timedelta(minutes=15),
            "exit_open": 100.0 + sign,
            "label_end_time": decision_times + pd.Timedelta(minutes=15),
            "future_return": sign / 100.0,
            "label": labels,
        })
        for feature_number, name in enumerate(FEATURE_COLUMNS, start=1):
            frame[name] = sign * feature_number + symbol_number * 0.01
        frames.append(frame)
    return pd.concat(frames, ignore_index=True).sort_values(
        ["decision_time", "symbol"], kind="stable"
    ).reset_index(drop=True)


def make_model_market(dataset):
    rows = []
    for row in dataset.itertuples(index=False):
        middle = (row.entry_open + row.exit_open) / 2.0
        for time, price in (
            (row.decision_time, row.entry_open),
            (row.entry_time, row.entry_open),
            (row.entry_time + pd.Timedelta(minutes=5), middle),
            (row.exit_time, row.exit_open),
        ):
            rows.append({
                "symbol": row.symbol,
                "segment_id": row.segment_id,
                "trade_time": time,
                "open": price,
                "close": price,
            })
    return pd.DataFrame(rows)


def test_candidate_names_are_fixed():
    assert candidate_names() == (
        "logistic_c0.1", "logistic_c1.0", "lightgbm_constrained"
    )


def test_research_domain_records_fixed_trial_count():
    config = ResearchConfig(model_backend="qlib")

    domain = research._research_domain(config)

    assert domain == {
        "selectable_models": [
            "logistic_c0.1", "qlib_lightgbm_constrained",
        ],
        "thresholds": [0.52, 0.55, 0.58],
        "candidate_threshold_pairs": 6,
        "feature_names": list(FEATURE_COLUMNS),
        "horizon": 6,
        "embargo_bars": 6,
    }


def test_run_identity_changes_with_database_or_module_hash():
    domain = {
        "selectable_models": ["logistic_c0.1"],
        "thresholds": [0.55],
    }
    evaluation = {"id": "evaluation"}

    first = research._run_identity(
        domain, evaluation, "a" * 64, "b" * 64
    )
    second = research._run_identity(
        domain, evaluation, "c" * 64, "b" * 64
    )

    assert first["id"] != second["id"]
    assert len(first["id"]) == 64


@pytest.mark.parametrize("model_name", [
    "logistic_c0.1", "logistic_c1.0", "lightgbm_constrained",
])
def test_model_probabilities_are_finite_and_bounded(model_name):
    dataset = make_model_dataset()
    train = dataset[dataset["decision_time"] < dataset["decision_time"].unique()[360]]
    evaluation = dataset[dataset["decision_time"] >= dataset["decision_time"].unique()[360]]

    probability, _ = fit_predict(Candidate(model_name, 0.55), train, evaluation)

    assert len(probability) == len(evaluation)
    assert np.isfinite(probability).all()
    assert ((0.0 <= probability) & (probability <= 1.0)).all()


def test_evaluation_extremes_cannot_change_logistic_scaler():
    dataset = make_model_dataset()
    train = dataset[dataset["decision_time"] < dataset["decision_time"].unique()[360]]
    evaluation = dataset[dataset["decision_time"] >= dataset["decision_time"].unique()[360]]
    attacked = evaluation.copy()
    attacked.loc[:, FEATURE_COLUMNS] *= 1e12

    _, clean_model = fit_predict(Candidate("logistic_c0.1", 0.55), train, evaluation)
    _, attacked_model = fit_predict(Candidate("logistic_c0.1", 0.55), train, attacked)
    clean_scaler = clean_model.named_steps["standardscaler"]
    attacked_scaler = attacked_model.named_steps["standardscaler"]

    np.testing.assert_array_equal(clean_scaler.mean_, attacked_scaler.mean_)
    np.testing.assert_array_equal(clean_scaler.scale_, attacked_scaler.scale_)
    np.testing.assert_array_equal(
        clean_scaler.transform(train.loc[:, FEATURE_COLUMNS]),
        attacked_scaler.transform(train.loc[:, FEATURE_COLUMNS]),
    )


def test_inverse_weights_equalize_each_symbol_and_class_total():
    frame = pd.DataFrame({
        "symbol": ["AG_IDX"] * 100 + ["CU_IDX"] * 20,
        "label": [0] * 90 + [1] * 10 + [0] * 10 + [1] * 10,
    })

    weights = inverse_symbol_class_weights(frame)

    weighted = frame.assign(weight=weights)
    assert weights.mean() == pytest.approx(1.0)
    assert weighted.groupby("symbol")["weight"].sum().nunique() == 1
    assert weighted.groupby("label")["weight"].sum().nunique() == 1


def test_inverse_weights_reject_symbol_missing_a_class():
    frame = pd.DataFrame({
        "symbol": ["AG_IDX"] * 4 + ["CU_IDX"] * 2,
        "label": [0, 0, 1, 1, 0, 0],
    })

    with pytest.raises(ResearchRejected, match="each symbol.*both classes"):
        inverse_symbol_class_weights(frame)


@pytest.mark.parametrize("column", ["label", "ret_1"])
def test_model_boundaries_fail_closed_for_one_class_or_non_finite(column):
    dataset = make_model_dataset()
    train = dataset.iloc[:700].copy()
    evaluation = dataset.iloc[700:].copy()
    if column == "label":
        evaluation["label"] = 1
    else:
        evaluation.loc[evaluation.index[0], column] = np.inf

    with pytest.raises(ResearchRejected):
        fit_predict(Candidate("logistic_c0.1", 0.55), train, evaluation)


def test_selection_requires_both_inner_folds_positive():
    scores = pd.DataFrame([
        {"model_name": "lightgbm_constrained", "threshold": 0.52,
         "fold": "inner_1", "return_5bps": 0.20, "turnover": 0.4},
        {"model_name": "lightgbm_constrained", "threshold": 0.52,
         "fold": "inner_2", "return_5bps": -0.01, "turnover": 0.4},
        {"model_name": "logistic_c0.1", "threshold": 0.55,
         "fold": "inner_1", "return_5bps": 0.02, "turnover": 0.2},
        {"model_name": "logistic_c0.1", "threshold": 0.55,
         "fold": "inner_2", "return_5bps": 0.01, "turnover": 0.2},
    ])
    assert choose_from_scores(scores) == Candidate("logistic_c0.1", 0.55)


def test_selection_requires_two_distinct_score_folds():
    scores = pd.DataFrame([
        {"model_name": "logistic_c0.1", "threshold": 0.55,
         "fold": "inner_1", "return_5bps": 0.02, "turnover": 0.2},
        {"model_name": "logistic_c0.1", "threshold": 0.55,
         "fold": "inner_1", "return_5bps": 0.01, "turnover": 0.2},
    ])

    with pytest.raises(ResearchRejected):
        choose_from_scores(scores)


def test_select_candidate_rejects_duplicate_fold_name_or_window_before_fit(
    monkeypatch,
):
    dataset = make_model_dataset(30)
    times = pd.DatetimeIndex(dataset["decision_time"].unique())
    first = research.TemporalFold("inner_1", times[:10], times[10:14])
    cases = [
        [first, first],
        [first, research.TemporalFold("inner_1", times[:14], times[14:18])],
        [first, research.TemporalFold("inner_2", times[:14], times[10:14])],
    ]

    def unexpected_fit(*args, **kwargs):
        raise AssertionError("model fit happened before fold validation")

    monkeypatch.setattr(research, "fit_predict", unexpected_fit)
    for folds in cases:
        with pytest.raises(ResearchRejected, match="inner"):
            select_candidate(dataset, None, folds, ResearchConfig(embargo_bars=0))


@pytest.mark.parametrize(
    "case",
    ["reversed_same_set", "duplicate_timestamp", "partial_overlap"],
)
def test_select_candidate_rejects_invalid_evaluation_windows_before_fit(
    monkeypatch, case,
):
    dataset = make_model_dataset(30)
    market = make_model_market(dataset)
    times = pd.DatetimeIndex(dataset["decision_time"].unique())
    first_window = times[10:14]
    if case == "reversed_same_set":
        second_window = first_window[::-1]
    elif case == "duplicate_timestamp":
        first_window = pd.DatetimeIndex([
            times[10], times[11], times[11], times[12],
        ])
        second_window = times[14:18]
    else:
        first_window = times[10:15]
        second_window = times[14:18]
    folds = [
        research.TemporalFold("inner_1", times[:10], first_window),
        research.TemporalFold("inner_2", times[:14], second_window),
    ]
    fit_calls = 0

    def unexpected_fit(*args, **kwargs):
        nonlocal fit_calls
        fit_calls += 1
        raise AssertionError("model fit happened before window validation")

    monkeypatch.setattr(research, "fit_predict", unexpected_fit)
    with pytest.raises(ResearchRejected, match="inner evaluation windows"):
        select_candidate(dataset, market, folds, ResearchConfig(embargo_bars=0))
    assert fit_calls == 0


def test_select_candidate_accepts_adjacent_nonoverlapping_evaluation_windows():
    dataset = make_model_dataset(50)
    times = pd.DatetimeIndex(dataset["decision_time"].unique())
    folds = [
        research.TemporalFold("inner_1", times[:20], times[20:30]),
        research.TemporalFold("inner_2", times[:30], times[30:40]),
    ]

    chosen, scores = select_candidate(
        dataset,
        make_model_market(dataset),
        folds,
        ResearchConfig(embargo_bars=0, thresholds=(0.55,)),
    )

    assert chosen == Candidate("logistic_c0.1", 0.55)
    assert len(scores) == 8


def _two_fold_scores(candidates):
    return pd.DataFrame([
        {"model_name": model, "threshold": threshold, "fold": fold,
         "return_5bps": return_, "turnover": turnover}
        for model, threshold, return_, turnover in candidates
        for fold in ("inner_1", "inner_2")
    ])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda scores: scores.drop(columns="turnover"),
        lambda scores: scores.assign(model_name="dummy_prior"),
        lambda scores: scores.assign(model_name="unapproved_model"),
        lambda scores: scores.assign(threshold=0.51),
        lambda scores: scores.assign(return_5bps=np.inf),
        lambda scores: scores.assign(turnover=np.nan),
        lambda scores: scores.assign(turnover=-0.1),
    ],
    ids=[
        "missing_schema", "dummy_numeric_threshold", "unknown_model",
        "unknown_threshold", "infinite_return", "nan_turnover",
        "negative_turnover",
    ],
)
def test_score_chooser_rejects_invalid_public_contract(mutate):
    scores = _two_fold_scores([("logistic_c0.1", 0.55, 0.01, 0.1)])

    with pytest.raises(ResearchRejected):
        choose_from_scores(mutate(scores))


def test_score_chooser_is_independent_of_input_order_on_exact_ties():
    scores = _two_fold_scores([
        ("logistic_c0.1", 0.55, 0.01, 0.1),
        ("logistic_c1.0", 0.55, 0.01, 0.1),
    ])

    expected = choose_from_scores(scores)
    actual = choose_from_scores(scores.iloc[::-1].reset_index(drop=True))

    assert expected == Candidate("logistic_c0.1", 0.55)
    assert actual == expected


def test_selection_ties_use_return_turnover_logistic_then_higher_threshold():
    assert choose_from_scores(_two_fold_scores([
        ("logistic_c0.1", 0.52, 0.0100, 0.1),
        ("logistic_c1.0", 0.55, 0.0111, 0.9),
    ])) == Candidate("logistic_c1.0", 0.55)
    assert choose_from_scores(_two_fold_scores([
        ("logistic_c0.1", 0.52, 0.0100, 0.1),
        ("logistic_c1.0", 0.55, 0.0109, 0.2),
    ])) == Candidate("logistic_c0.1", 0.52)
    assert choose_from_scores(_two_fold_scores([
        ("lightgbm_constrained", 0.58, 0.0100, 0.1),
        ("logistic_c1.0", 0.52, 0.0100, 0.1),
    ])) == Candidate("logistic_c1.0", 0.52)
    assert choose_from_scores(_two_fold_scores([
        ("logistic_c0.1", 0.52, 0.0100, 0.1),
        ("logistic_c0.1", 0.58, 0.0100, 0.1),
    ])) == Candidate("logistic_c0.1", 0.58)


def test_near_best_qlib_domain_prefers_logistic_at_equal_turnover():
    scores = _two_fold_scores([
        ("logistic_c0.1", 0.55, 0.0100, 1.0),
        ("qlib_lightgbm_constrained", 0.55, 0.0105, 1.0),
    ])

    assert choose_from_scores(scores, "qlib") == Candidate(
        "logistic_c0.1", 0.55
    )


def test_selection_rejects_when_no_candidate_passes_both_folds():
    scores = _two_fold_scores([("logistic_c0.1", 0.55, 0.0, 0.0)])

    with pytest.raises(ResearchRejected, match="no candidate"):
        choose_from_scores(scores)


def test_select_candidate_scores_fixed_search_and_reports_dummy_prior():
    dataset = make_model_dataset()
    times = pd.DatetimeIndex(dataset["decision_time"].unique())
    folds = [
        research.TemporalFold("inner_1", times[:240], times[240:340]),
        research.TemporalFold("inner_2", times[:340], times[340:440]),
    ]

    market = make_model_market(dataset)
    chosen, scores = select_candidate(dataset, market, folds)
    outer_only = dataset.copy()
    outside = outer_only["decision_time"] >= times[440]
    outer_only.loc[outside, "symbol"] = "OUTER_ONLY"
    outer_only.loc[outside, "label"] = 7
    outer_only.loc[outside, "future_return"] = np.inf
    outer_only["label_end_time"] = outer_only["label_end_time"].astype(object)
    outer_only.loc[outside, "label_end_time"] = "OUTER_ONLY"
    outer_market = market.copy()
    outer_market.loc[outer_market["trade_time"] >= times[440], "open"] = np.inf
    protected_chosen, protected_scores = select_candidate(
        outer_only, outer_market, folds
    )

    assert chosen == Candidate("logistic_c0.1", 0.58)
    assert protected_chosen == chosen
    pd.testing.assert_frame_equal(protected_scores, scores)
    assert len(scores) == 20
    assert scores.loc[scores["model_name"].eq("dummy_prior"), "fold"].tolist() == [
        "inner_1", "inner_2"
    ]
    selectable = scores[scores["model_name"].isin(candidate_names())]
    assert set(selectable["threshold"]) == set(ResearchConfig().thresholds)
    assert len(selectable) == 18


class HoldoutGuardFrame(pd.DataFrame):
    _metadata = ["lock_start", "labels_unlocked"]

    @property
    def _constructor(self):
        return HoldoutGuardFrame

    def __getitem__(self, key):
        if (
            isinstance(key, str)
            and key in {"label", "future_return"}
            and not self.labels_unlocked
            and (
                pd.DataFrame.__getitem__(self, "label_end_time")
                >= self.lock_start
            ).any()
        ):
            raise AssertionError("parent-test label accessed during selection")
        return super().__getitem__(key)


def test_outer_and_holdout_base_evaluation_is_temporally_isolated(monkeypatch):
    dataset, market = make_causal_evaluation_fixture()
    config = ResearchConfig(min_symbols=2, min_fold_rows=5)
    partitions = make_temporal_partitions(dataset, config)
    holdout = partitions["holdout_fold"]
    guarded = HoldoutGuardFrame(dataset)
    guarded.lock_start = partitions["outer_folds"][0].evaluation_times[0]
    guarded.labels_unlocked = False
    selection_calls = []
    parent_fits = []
    bootstrap_calls = 0
    active_parent = None
    parents = [*partitions["outer_folds"], holdout]
    real_select = research.select_candidate
    real_evaluate = research.evaluate_fold
    real_fit = research.fit_predict
    real_bootstrap = research.moving_block_return_interval

    def tracked_select(rows, marks, folds, supplied_config):
        parent = parents[len(selection_calls)]
        rows.lock_start = parent.evaluation_times[0]
        rows.labels_unlocked = False
        assert not (
            pd.DataFrame.__getitem__(rows, "label_end_time")
            >= parent.evaluation_times[0]
        ).any()
        expected = purged_training_rows(
            dataset,
            parent.train_times,
            parent.evaluation_times[0],
            supplied_config.embargo_bars,
        )
        assert rows.index.tolist() == expected.index.tolist()
        safe_times = pd.DatetimeIndex(rows["decision_time"].unique())
        for inner_fold in folds:
            assert pd.DatetimeIndex(inner_fold.train_times).isin(safe_times).all()
            assert pd.DatetimeIndex(inner_fold.evaluation_times).isin(safe_times).all()
        chosen, scores = real_select(rows, marks, folds, supplied_config)
        selection_calls.append((tuple(fold.name for fold in folds), chosen, scores))
        return chosen, scores

    def unlock_only_for_parent_evaluation(rows, marks, fold, candidate, supplied_config):
        nonlocal active_parent
        rows.lock_start = fold.evaluation_times[0]
        rows.labels_unlocked = True
        active_parent = fold
        try:
            return real_evaluate(rows, marks, fold, candidate, supplied_config)
        finally:
            active_parent = None
            rows.labels_unlocked = False

    def tracked_fit(candidate, train, evaluation, supplied_config=ResearchConfig()):
        if active_parent is not None:
            parent_fits.append((active_parent.evaluation_times[0], train.copy()))
        return real_fit(candidate, train, evaluation, supplied_config)

    def tracked_bootstrap(
            returns, supplied_config=ResearchConfig(), block_days=5):
        nonlocal bootstrap_calls
        assert len(selection_calls) == 4
        assert active_parent is None
        bootstrap_calls += 1
        return real_bootstrap(returns, supplied_config, block_days=block_days)

    monkeypatch.setattr(research, "select_candidate", tracked_select)
    monkeypatch.setattr(research, "evaluate_fold", unlock_only_for_parent_evaluation)
    monkeypatch.setattr(research, "fit_predict", tracked_fit)
    monkeypatch.setattr(research, "moving_block_return_interval", tracked_bootstrap)

    result = research.build_base_evaluation(guarded, market, partitions, config)

    crossing_counts = [
        len(dataset[
            dataset["decision_time"].isin(parent.train_times)
            & (dataset["label_end_time"] >= parent.evaluation_times[0])
        ])
        for parent in (parents[0], parents[1], parents[-1])
    ]
    assert crossing_counts == [8, 4, 14]
    assert len(result["outer_results"]) == 3
    expected_selection_folds = [
        tuple(fold.name for fold in partitions["inner_by_outer"][outer.name])
        for outer in partitions["outer_folds"]
    ] + [tuple(fold.name for fold in partitions["development_inner_folds"])]
    assert [call[0] for call in selection_calls] == expected_selection_folds
    assert [fold_result["candidate"] for fold_result in result["outer_results"]] == [
        call[1] for call in selection_calls[:3]
    ]
    for _, chosen, scores in selection_calls[:3]:
        candidate_scores = scores[scores["model_name"].isin(candidate_names())]
        assert chosen == choose_from_scores(candidate_scores)
    assert result["final_candidate"] == selection_calls[-1][1]
    pd.testing.assert_frame_equal(result["final_inner_scores"], selection_calls[-1][2])
    assert bootstrap_calls == 3
    assert "bootstrap" in result["holdout"]
    identity = result["holdout"]["evaluation_identity"]
    assert identity["scope"] == "single_build_base_evaluation"
    assert identity["candidate"] == {
        "model_name": result["final_candidate"].model_name,
        "model_identity": result["holdout"]["model_identity"],
        "model_parameters": result["holdout"]["model_parameters"],
        "threshold": result["final_candidate"].threshold,
    }
    assert identity["evaluation_rows"] == result["holdout"]["sample_counts"][
        "evaluation_rows"
    ]
    assert identity["evaluation_times"] == [
        pd.Timestamp(time).isoformat() for time in holdout.evaluation_times
    ]
    assert identity["costs_bps"] == list(config.costs_bps)
    assert identity["seed"] == config.seed
    holdout_rows = dataset[
        dataset["decision_time"].isin(holdout.evaluation_times)
    ]
    holdout_marks = research._evaluation_market(holdout_rows, market)
    assert identity["market_mark_rows"] == len(holdout_marks)
    assert len(identity["market_mark_hash"]) == 64
    assert int(identity["market_mark_hash"], 16) >= 0

    assert len(parent_fits) == 4
    for parent, (evaluation_start, fitted_train) in zip(parents, parent_fits):
        assert evaluation_start == parent.evaluation_times[0]
        expected = purged_training_rows(
            dataset,
            parent.train_times,
            parent.evaluation_times[0],
            config.embargo_bars,
        )
        assert fitted_train.index.tolist() == expected.index.tolist()
        assert (fitted_train["label_end_time"] < parent.evaluation_times[0]).all()
    final_train = parent_fits[-1][1]
    eligible = dataset[
        dataset["decision_time"].isin(holdout.train_times)
        & (dataset["label_end_time"] < holdout.evaluation_times[0])
    ]
    for _, rows in eligible.groupby("symbol"):
        embargoed = rows.sort_values("decision_time").tail(config.embargo_bars)
        assert set(embargoed.index).isdisjoint(final_train.index)

    for fold_result in [*result["outer_results"], result["holdout"]]:
        assert len(fold_result["model_identity"]) == 16
        assert int(fold_result["model_identity"], 16) >= 0
        assert set(fold_result["cost_metrics"]) == set(config.costs_bps)
        assert set(fold_result["benchmarks"]) == {
            "dummy_prior", "equal_weight_long_only",
        }
        reference = fold_result["trades"][config.costs_bps[0]][
            ["symbol", "decision_time", "entry_time", "exit_time", "direction"]
        ].reset_index(drop=True)
        for cost in config.costs_bps[1:]:
            pd.testing.assert_frame_equal(
                reference,
                fold_result["trades"][cost][reference.columns].reset_index(drop=True),
            )
        for cost in config.costs_bps:
            counts = fold_result["trades"][cost].groupby("symbol").size()
            rows = fold_result["symbol_metrics"]
            rows = rows[rows["cost_bps"].eq(cost)].set_index("symbol")
            numeric = rows.select_dtypes(include=[np.number])
            assert np.isfinite(numeric.to_numpy(dtype=float)).all()
            assert set(rows["evaluation_start"]) == {
                fold_result["split_cutoffs"]["evaluation_start"]
            }
            assert set(rows["evaluation_end"]) == {
                fold_result["split_cutoffs"]["evaluation_end"]
            }
            assert rows["trades"].to_dict() == {
                symbol: int(counts.get(symbol, 0)) for symbol in rows.index
            }
            for benchmark in fold_result["benchmarks"].values():
                pd.testing.assert_series_equal(
                    benchmark["daily"][cost]["date"].reset_index(drop=True),
                    fold_result["daily"][cost]["date"].reset_index(drop=True),
                )


def test_outer_evaluation_ignores_future_only_symbol_statistics():
    dataset = make_model_dataset()
    market = make_model_market(dataset)
    times = pd.DatetimeIndex(dataset["decision_time"].unique())
    fold = research.TemporalFold("outer_future_guard", times[:240], times[240:340])
    config = ResearchConfig(costs_bps=(5,))
    expected = research.evaluate_fold(
        dataset, market, fold, Candidate("logistic_c0.1", 0.55), config
    )
    attacked = dataset.copy()
    attacked.loc[attacked["decision_time"] >= times[340], "symbol"] = "FUTURE_ONLY"
    attacked_market = market.copy()
    attacked_market.loc[
        attacked_market["trade_time"] >= times[340], "symbol"
    ] = "FUTURE_ONLY"

    actual = research.evaluate_fold(
        attacked, attacked_market, fold, Candidate("logistic_c0.1", 0.55), config
    )

    assert actual["sample_counts"] == expected["sample_counts"]
    assert actual["model_identity"] == expected["model_identity"]
    assert actual["predictive_metrics"] == pytest.approx(expected["predictive_metrics"])
    assert actual["cost_metrics"][5] == pytest.approx(expected["cost_metrics"][5])


def test_generic_fold_named_holdout_has_no_locked_evaluation_side_effects():
    dataset = make_model_dataset()
    market = make_model_market(dataset)
    times = pd.DatetimeIndex(dataset["decision_time"].unique())
    renamed_outer = research.TemporalFold("holdout", times[:240], times[240:340])
    config = ResearchConfig(costs_bps=(5,))

    first = research.evaluate_fold(
        dataset, market, renamed_outer, Candidate("logistic_c0.1", 0.55), config
    )
    second = research.evaluate_fold(
        dataset, market, renamed_outer, Candidate("logistic_c0.1", 0.55), config
    )

    assert "bootstrap" not in first
    assert "evaluation_identity" not in first
    assert "bootstrap" not in second
    assert "evaluation_identity" not in second
    assert first["model_identity"] == second["model_identity"]


def test_evaluation_identity_hashes_candidate_domain_costs_and_seed():
    dataset = make_model_dataset(80)
    evaluation = dataset.iloc[120:].copy()
    market = make_model_market(dataset)
    candidate = Candidate("logistic_c0.1", 0.55)
    fold_result = {"model_identity": "model-a", "model_parameters": {"C": 0.1}}
    config = ResearchConfig()

    baseline = research._evaluation_identity(
        candidate, fold_result, evaluation, market, config
    )
    identities = {baseline["id"]}
    identities.add(research._evaluation_identity(
        Candidate("logistic_c1.0", candidate.threshold),
        fold_result,
        evaluation,
        market,
        config,
    )["id"])
    identities.add(research._evaluation_identity(
        Candidate(candidate.model_name, 0.58), fold_result, evaluation, market, config
    )["id"])
    identities.add(research._evaluation_identity(
        candidate,
        {"model_identity": "model-a", "model_parameters": {"C": 1.0}},
        evaluation,
        market,
        config,
    )["id"])
    identities.add(research._evaluation_identity(
        candidate,
        {"model_identity": "model-b", "model_parameters": {"C": 0.1}},
        evaluation,
        market,
        config,
    )["id"])
    changed_domain = evaluation.iloc[:-1].copy()
    identities.add(research._evaluation_identity(
        candidate, fold_result, changed_domain, market, config
    )["id"])
    identities.add(research._evaluation_identity(
        candidate,
        fold_result,
        evaluation,
        market,
        ResearchConfig(costs_bps=(0, 5, 15)),
    )["id"])
    identities.add(research._evaluation_identity(
        candidate, fold_result, evaluation, market, ResearchConfig(seed=43)
    )["id"])

    assert baseline["scope"] == "single_build_base_evaluation"
    assert baseline["evaluation_rows"] == len(evaluation)
    assert len(baseline["evaluation_times"]) == evaluation["decision_time"].nunique()
    assert len(identities) == 8


def test_evaluation_identity_hashes_only_canonical_evaluation_market_marks():
    dataset = make_model_dataset(80)
    evaluation = dataset.iloc[120:].copy()
    market = make_model_market(dataset)
    candidate = Candidate("logistic_c0.1", 0.55)
    fold_result = {"model_identity": "model-a", "model_parameters": {"C": 0.1}}
    config = ResearchConfig()

    baseline = research._evaluation_identity(
        candidate, fold_result, evaluation, market, config
    )
    relevant = research._evaluation_market(evaluation, market)
    trade = evaluation.iloc[0]
    middle = relevant[
        relevant["symbol"].eq(trade.symbol)
        & relevant["segment_id"].eq(trade.segment_id)
        & relevant["trade_time"].eq(trade.entry_time + pd.Timedelta(minutes=5))
    ].index.item()
    assert trade.entry_time < relevant.loc[middle, "trade_time"] < trade.exit_time
    changed_mark = market.copy()
    changed_mark.loc[middle, "close"] *= 0.9
    changed = research._evaluation_identity(
        candidate, fold_result, evaluation, changed_mark, config
    )
    unrelated = pd.DataFrame([
        {
            "symbol": "UNRELATED",
            "segment_id": "UNRELATED:1",
            "trade_time": evaluation["decision_time"].min(),
            "open": 1.0,
            "close": 999.0,
        },
        {
            "symbol": evaluation["symbol"].iloc[0],
            "segment_id": evaluation["segment_id"].iloc[0],
            "trade_time": evaluation["decision_time"].min() - pd.Timedelta(days=1),
            "open": 1.0,
            "close": 999.0,
        },
    ])
    outside = research._evaluation_identity(
        candidate,
        fold_result,
        evaluation,
        pd.concat([market, unrelated], ignore_index=True),
        config,
    )
    shuffled = research._evaluation_identity(
        candidate,
        fold_result,
        evaluation,
        market.sample(frac=1, random_state=42).reset_index(drop=True),
        config,
    )
    microseconds = market.copy()
    microseconds["trade_time"] = microseconds["trade_time"].astype("datetime64[us]")
    equivalent_dtype = research._evaluation_identity(
        candidate, fold_result, evaluation, microseconds, config
    )

    assert changed["id"] != baseline["id"]
    assert changed["market_mark_hash"] != baseline["market_mark_hash"]
    assert outside == baseline
    assert shuffled == baseline
    assert equivalent_dtype == baseline
    assert baseline["market_mark_rows"] == len(relevant)


def test_model_identity_hashes_every_audit_input(monkeypatch):
    dataset = make_model_dataset(80)
    train = dataset.iloc[:120].copy()
    evaluation = dataset.iloc[120:].copy()
    candidate = Candidate("logistic_c0.1", 0.55)
    _, model = fit_predict(candidate, train, evaluation)
    baseline = research._model_identity(candidate, model, train)[0]
    identities = {baseline}
    identities.add(research._model_identity(
        Candidate("logistic_c1.0", 0.55), model, train
    )[0])
    model.set_params(logisticregression__C=2.0)
    identities.add(research._model_identity(candidate, model, train)[0])
    model.set_params(logisticregression__C=0.1)
    changed_row = train.copy()
    changed_row.loc[changed_row.index[0], "ret_1"] += 1.0
    identities.add(research._model_identity(candidate, model, changed_row)[0])
    changed_target = train.copy()
    changed_target.loc[changed_target.index[0], "label"] = 1 - changed_target.loc[
        changed_target.index[0], "label"
    ]
    identities.add(research._model_identity(candidate, model, changed_target)[0])
    original_features = research.FEATURE_COLUMNS
    monkeypatch.setattr(research, "FEATURE_COLUMNS", original_features[::-1])
    identities.add(research._model_identity(candidate, model, train)[0])

    assert len(baseline) == 16
    assert int(baseline, 16) >= 0
    assert len(identities) == 6


def test_base_evaluation_rejects_holdout_time_in_inner_domain_before_selection(
    monkeypatch,
):
    dataset = make_partition_dataset()
    config = ResearchConfig(min_symbols=2, min_fold_rows=50)
    partitions = make_temporal_partitions(dataset, config)
    holdout_time = partitions["holdout_fold"].evaluation_times[0]
    development_inner = list(partitions["development_inner_folds"])
    poisoned = development_inner[1]
    development_inner[1] = research.TemporalFold(
        poisoned.name,
        poisoned.train_times,
        poisoned.evaluation_times.append(pd.DatetimeIndex([holdout_time])),
    )
    partitions["development_inner_folds"] = development_inner
    calls = 0

    def unexpected_selection(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("selection started before partition validation")

    monkeypatch.setattr(research, "select_candidate", unexpected_selection)

    with pytest.raises(ResearchRejected, match="partition"):
        research.build_base_evaluation(dataset, None, partitions, config)
    assert calls == 0


def test_base_evaluation_rejects_renamed_holdout_before_selection(monkeypatch):
    dataset = make_partition_dataset()
    config = ResearchConfig(min_symbols=2, min_fold_rows=50)
    partitions = make_temporal_partitions(dataset, config)
    holdout = partitions["holdout_fold"]
    partitions["holdout_fold"] = research.TemporalFold(
        "renamed", holdout.train_times, holdout.evaluation_times
    )
    calls = 0

    def unexpected_selection(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("selection started before partition validation")

    monkeypatch.setattr(research, "select_candidate", unexpected_selection)

    with pytest.raises(ResearchRejected, match="partition"):
        research.build_base_evaluation(dataset, None, partitions, config)
    assert calls == 0


def test_base_evaluation_rejects_outer_named_holdout_before_selection(monkeypatch):
    dataset = make_partition_dataset()
    config = ResearchConfig(min_symbols=2, min_fold_rows=50)
    partitions = make_temporal_partitions(dataset, config)
    outer = list(partitions["outer_folds"])
    renamed = research.TemporalFold(
        "holdout", outer[0].train_times, outer[0].evaluation_times
    )
    inner_by_outer = dict(partitions["inner_by_outer"])
    inner_by_outer[renamed.name] = inner_by_outer.pop(outer[0].name)
    outer[0] = renamed
    partitions["outer_folds"] = outer
    partitions["inner_by_outer"] = inner_by_outer
    calls = 0

    def unexpected_selection(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("selection started before partition validation")

    monkeypatch.setattr(research, "select_candidate", unexpected_selection)

    with pytest.raises(ResearchRejected, match="partition"):
        research.build_base_evaluation(dataset, None, partitions, config)
    assert calls == 0


def test_holdout_predictive_metrics_fail_closed_and_include_rank_correlation():
    metrics = research.predictive_metrics([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9], 0.55)

    assert metrics == pytest.approx({
        "roc_auc": 1.0,
        "balanced_accuracy": 1.0,
        "brier_score": 0.025,
        "rank_correlation": 0.8944271909999159,
    })
    with pytest.raises(ResearchRejected):
        research.predictive_metrics([1, 1], [0.8, 0.9], 0.55)
    with pytest.raises(ResearchRejected):
        research.predictive_metrics([0, 1], [0.2, np.inf], 0.55)
    with pytest.raises(ResearchRejected):
        research.predictive_metrics([0, "bad"], [0.2, 0.8], 0.55)


def test_bootstrap_uses_1000_deterministic_five_day_moving_blocks():
    returns = np.array([0.01, -0.02, 0.03, 0.00, 0.02, -0.01, 0.04, -0.03])
    rng = np.random.default_rng(42)
    samples = []
    for _ in range(1000):
        sample = []
        while len(sample) < len(returns):
            start = rng.integers(0, len(returns) - 5 + 1)
            sample.extend(returns[start:start + 5])
        samples.append(np.prod(1.0 + np.asarray(sample[:len(returns)])) - 1.0)
    expected = np.percentile(samples, [5, 50, 95])

    first = research.moving_block_return_interval(returns, ResearchConfig(seed=42))
    second = research.moving_block_return_interval(returns, ResearchConfig(seed=42))

    assert first == second
    assert first["samples"] == 1000
    assert first["block_days"] == 5
    assert [first["p05"], first["p50"], first["p95"]] == pytest.approx(expected)
    assert first["p05"] <= first["p50"] <= first["p95"]
    constant = research.moving_block_return_interval(
        np.full(8, 0.01), ResearchConfig(seed=42)
    )
    compounded = (1.01 ** 8) - 1.0
    assert [constant["p05"], constant["p50"], constant["p95"]] == pytest.approx(
        [compounded] * 3
    )
    with pytest.raises(ResearchRejected):
        research.moving_block_return_interval(returns[:4], ResearchConfig(seed=42))
    with pytest.raises(ResearchRejected):
        research.moving_block_return_interval(["bad"] * 5, ResearchConfig(seed=42))
    with pytest.raises(ResearchRejected):
        research.moving_block_return_interval(returns, ResearchConfig(seed=-1))


def test_moving_block_intervals_cover_5_10_and_20_days():
    returns = np.full(60, 0.001)

    result = research.moving_block_return_intervals(
        returns, ResearchConfig(seed=42)
    )

    assert set(result["blocks"]) == {"5", "10", "20"}
    assert result["worst_p05"] == min(
        row["p05"] for row in result["blocks"].values()
    )


def test_default_cost_grid_includes_15_bps():
    assert ResearchConfig().costs_bps == (0, 2, 5, 10, 15, 20)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda bars: bars.loc.__setitem__((1, "trade_time"), bars.loc[0, "trade_time"]),
        lambda bars: bars.loc.__setitem__(([0, 1], "trade_time"), bars.loc[[1, 0], "trade_time"].to_numpy()),
        lambda bars: bars.loc.__setitem__((1, "trade_time"), bars.loc[1, "trade_time"] + pd.Timedelta(minutes=1)),
        lambda bars: bars.loc.__setitem__((1, "close"), np.inf),
        lambda bars: bars.loc.__setitem__((1, "high"), bars.loc[1, "low"] - 1),
        lambda bars: bars.loc.__setitem__((1, "volume"), -1.0),
        lambda bars: bars.loc.__setitem__((1, "open_interest"), -1.0),
    ],
    ids=[
        "duplicate_time", "out_of_order", "not_five_minute", "non_finite_price",
        "invalid_ohlc", "negative_volume", "negative_open_interest",
    ],
)
def test_structural_data_violations_fail_closed(mutate):
    bars = make_bars(3)
    mutate(bars)

    with pytest.raises(ResearchRejected):
        validate_and_segment(bars, ResearchConfig(min_symbol_rows=1, min_fold_rows=1))


def _prepare_15m(bars):
    return research._prepare_segmented_bars(
        bars,
        ResearchConfig(
            timeframe="15m", min_symbol_rows=1,
            min_symbols=1, min_fold_rows=1,
        ),
    )


def test_15m_resampling_does_not_hide_internal_zero_volume():
    bars = make_bars(6)
    bars["trade_time"] = pd.date_range(
        "2026-01-02 09:05", periods=6, freq="5min"
    )
    bars.loc[1, "volume"] = 0.0

    segmented, quality = _prepare_15m(bars)

    assert segmented["trade_time"].tolist() == [pd.Timestamp("2026-01-02 09:30")]
    assert quality.loc["AG_IDX", "zero_volume_boundaries"] >= 1
    assert quality.loc["AG_IDX", "aggregated_15m_rows"] == 1


def test_15m_resampling_does_not_hide_internal_price_jump():
    bars = make_bars(6)
    bars["trade_time"] = pd.date_range(
        "2026-01-02 09:05", periods=6, freq="5min"
    )
    bars.loc[1, ["open", "high", "low", "close"]] *= 1.04

    segmented, quality = _prepare_15m(bars)

    assert segmented["trade_time"].tolist() == [pd.Timestamp("2026-01-02 09:30")]
    assert quality.loc["AG_IDX", "price_jump_boundaries"] >= 1


def test_15m_resampling_uses_natural_boundaries_and_drops_partials():
    bars = make_bars(6)
    bars["trade_time"] = pd.date_range(
        "2026-01-02 09:10", periods=6, freq="5min"
    )

    segmented, quality = _prepare_15m(bars)

    assert segmented["trade_time"].tolist() == [pd.Timestamp("2026-01-02 09:30")]
    assert quality.loc["AG_IDX", "partial_15m_windows"] == 2


def test_prepare_segmented_bars_resamples_5m_without_crossing_gaps():
    bars = make_bars(12)
    bars.loc[6:, "trade_time"] += pd.Timedelta(minutes=5)
    manifest = [{
        "symbol": "AG_IDX", "source_path": "source.txt",
        "source_sha256": "a" * 64,
    }]
    bars.attrs["source_manifest"] = manifest

    segmented, quality = research._prepare_segmented_bars(
        bars,
        ResearchConfig(
            timeframe="15m", min_symbol_rows=1, min_symbols=1,
            min_fold_rows=1,
        ),
    )

    assert segmented["trade_time"].tolist() == [
        pd.Timestamp("2026-01-02 09:15"),
        pd.Timestamp("2026-01-02 09:45"),
        pd.Timestamp("2026-01-02 10:00"),
    ]
    assert segmented.groupby("segment_id").size().tolist() == [1, 2]
    assert quality.loc["AG_IDX", "partial_15m_windows"] == 2
    assert segmented.attrs["source_manifest"] == manifest


def test_causal_features_cross_session_gaps_but_trade_paths_do_not():
    first = make_bars(30)
    second = make_bars(30)
    second["trade_time"] = pd.date_range(
        "2026-01-03 09:00", periods=30, freq="15min"
    )
    bars = pd.concat([first, second], ignore_index=True)
    bars["trade_time"] = pd.concat([
        pd.Series(pd.date_range("2026-01-02 09:00", periods=30, freq="15min")),
        pd.Series(pd.date_range("2026-01-03 09:00", periods=30, freq="15min")),
    ], ignore_index=True)
    bars["segment_id"] = ["AG_IDX:1"] * 30 + ["AG_IDX:2"] * 30
    bars["feature_segment_id"] = "AG_IDX:1"
    bars["volume"] = np.arange(1.0, 61.0)

    dataset = build_causal_dataset(
        bars, ResearchConfig(timeframe="15m", horizon=2)
    )

    assert not dataset.empty
    assert set(dataset["segment_id"]) == {"AG_IDX:2"}
    assert dataset["entry_time"].dt.date.eq(dataset["exit_time"].dt.date).all()


def make_scored(symbol, decision_time, probability, entry_open, exit_open):
    decision_time = pd.Timestamp(decision_time)
    return {
        "symbol": symbol,
        "segment_id": f"{symbol}:1",
        "decision_time": decision_time,
        "entry_time": decision_time + pd.Timedelta(minutes=5),
        "entry_open": entry_open,
        "exit_time": decision_time + pd.Timedelta(minutes=15),
        "exit_open": exit_open,
        "probability": probability,
    }


def make_mark_market(scored=None):
    scored = scored if scored is not None else pd.DataFrame([
        make_scored("AG_IDX", "2026-01-01 09:05", 0.80, 100.0, 110.0),
        make_scored("CU_IDX", "2026-01-01 09:05", 0.20, 100.0, 90.0),
    ])
    rows = []
    for row in scored.itertuples(index=False):
        exit_open = row.exit_open if pd.notna(row.exit_open) else row.terminal_open
        middle = (float(row.entry_open) + float(exit_open)) / 2.0
        for time, open_, close in (
            (row.decision_time, row.entry_open, row.entry_open),
            (row.entry_time, row.entry_open, row.entry_open),
            (row.entry_time + pd.Timedelta(minutes=5), middle, middle),
            (row.exit_time, exit_open, exit_open),
        ):
            rows.append({
                "symbol": row.symbol,
                "segment_id": row.segment_id,
                "trade_time": time,
                "open": open_,
                "close": close,
            })
    return pd.DataFrame(rows).drop_duplicates(["symbol", "segment_id", "trade_time"])


def test_standardized_ledger_accepts_regular_15m_paths():
    decision = pd.Timestamp("2026-01-01 09:00")
    scored = pd.DataFrame([{
        "symbol": "AG_IDX", "segment_id": "AG_IDX:1",
        "decision_time": decision,
        "entry_time": decision + pd.Timedelta(minutes=15),
        "entry_open": 100.0,
        "exit_time": decision + pd.Timedelta(minutes=45),
        "exit_open": 103.0,
        "probability": 0.80,
    }])
    market = pd.DataFrame({
        "symbol": "AG_IDX", "segment_id": "AG_IDX:1",
        "trade_time": pd.date_range(decision, periods=4, freq="15min"),
        "open": [100.0, 100.0, 101.0, 103.0],
        "close": [100.0, 100.0, 101.0, 103.0],
    })

    trades, daily = simulate_standardized_ledger(scored, market, 0.55, 5, 1)

    assert len(trades) == 1
    assert not daily.empty


def test_ledger_reconciles_long_short_and_double_sided_costs():
    scored = pd.DataFrame([
        make_scored("AG_IDX", "2026-01-01 09:05", 0.80, 100.0, 110.0),
        make_scored("CU_IDX", "2026-01-01 09:05", 0.20, 100.0, 90.0),
    ])

    trades, daily = simulate_standardized_ledger(
        scored, make_mark_market(scored), threshold=0.55, cost_bps=5, symbol_count=2
    )

    c = 5 / 10_000
    expected_long = (110 / 100 - 1) - c * (1 + 110 / 100)
    expected_short = -(90 / 100 - 1) - c * (1 + 90 / 100)
    assert trades["net_sleeve_return"].tolist() == pytest.approx(
        [expected_long, expected_short]
    )
    assert daily["portfolio_return"].sum() == pytest.approx(
        (expected_long + expected_short) / 2
    )
    assert (trades["sleeve_end_equity"] - trades["sleeve_start_equity"]).tolist() == pytest.approx(
        trades["sleeve_pnl"]
    )
    assert daily["equity"].iloc[-1] - 1.0 == pytest.approx(daily["pnl"].sum(), abs=1e-12)


def test_overlap_and_alternating_signals_leave_one_position():
    first = make_scored("AG_IDX", "2026-01-01 09:05", 0.80, 100.0, 110.0)
    repeated = make_scored("AG_IDX", "2026-01-01 09:10", 0.20, 105.0, 90.0)
    repeated["exit_time"] = pd.Timestamp("2026-01-01 09:30")
    market = pd.concat([
        make_mark_market(pd.DataFrame([first])),
        pd.DataFrame([
            {"symbol": "AG_IDX", "segment_id": "AG_IDX:1", "trade_time": time, "open": open_, "close": open_}
            for time, open_ in (
                ("2026-01-01 09:25", 95.0),
                ("2026-01-01 09:30", 90.0),
            )
        ]),
    ], ignore_index=True)

    trades, _ = simulate_standardized_ledger(
        pd.DataFrame([repeated, first]), market, threshold=0.55, cost_bps=5, symbol_count=1
    )

    assert trades[["symbol", "direction"]].to_dict("records") == [
        {"symbol": "AG_IDX", "direction": 1}
    ]


def test_ledger_order_is_deterministic_and_sleeves_cap_exposure():
    scored = pd.DataFrame([
        make_scored("AG_IDX", "2026-01-01 09:05", 0.80, 100.0, 110.0),
        make_scored("CU_IDX", "2026-01-01 09:05", 0.20, 100.0, 90.0),
    ])
    market = make_mark_market(scored)

    expected = simulate_standardized_ledger(scored, market, 0.55, 5, 2)
    actual = simulate_standardized_ledger(
        scored.sample(frac=1, random_state=7),
        market.sample(frac=1, random_state=8),
        0.55,
        5,
        2,
    )

    pd.testing.assert_frame_equal(expected[0], actual[0])
    pd.testing.assert_frame_equal(expected[1], actual[1])
    assert actual[1]["gross_exposure"].max() <= 1.0


def test_daily_marks_retain_adverse_excursion_before_profitable_exit():
    scored = pd.DataFrame([make_scored("AG_IDX", "2026-01-01 23:50", 0.80, 100.0, 110.0)])
    scored.loc[0, "exit_time"] = pd.Timestamp("2026-01-03 00:00")
    times = pd.date_range("2026-01-01 23:50", "2026-01-03 00:00", freq="5min")
    market = pd.DataFrame({
        "symbol": "AG_IDX",
        "segment_id": "AG_IDX:1",
        "trade_time": times,
        "open": np.where(times == times[-1], 110.0, np.where(times.date == pd.Timestamp("2026-01-02").date(), 80.0, 100.0)),
        "close": np.where(times == times[-1], 110.0, np.where(times.date == pd.Timestamp("2026-01-02").date(), 80.0, 100.0)),
    })

    trades, daily = simulate_standardized_ledger(scored, market, 0.55, 0, 1)
    metrics = strategy_metrics(trades, daily)

    assert daily.loc[daily["date"].eq(pd.Timestamp("2026-01-02")), "equity"].item() == pytest.approx(0.8)
    assert metrics["total_return"] == pytest.approx(0.1)
    assert metrics["max_drawdown"] == pytest.approx(0.2)


def test_cost_sensitivity_is_monotone():
    scored = pd.DataFrame([make_scored("AG_IDX", "2026-01-01 09:05", 0.80, 100.0, 110.0)])
    market = make_mark_market(scored)

    returns = [
        simulate_standardized_ledger(scored, market, 0.55, cost, 1)[0]["net_sleeve_return"].item()
        for cost in (0, 2, 5, 10, 20)
    ]

    assert returns == sorted(returns, reverse=True)


def test_terminal_close_uses_supplied_open_and_pays_exit_cost():
    row = make_scored("AG_IDX", "2026-01-01 09:05", 0.80, 100.0, np.nan)
    row["terminal_open"] = 105.0
    scored = pd.DataFrame([row])

    trades, _ = simulate_standardized_ledger(scored, make_mark_market(scored), 0.55, 5, 1)

    assert trades.loc[0, "exit_open"] == 105.0
    assert trades.loc[0, "exit_cost"] == pytest.approx(0.0005 * 1.05)
    assert trades.loc[0, "exit_reason"] == "TERMINAL_CLOSE"


def test_strategy_metrics_use_compounded_daily_mark_path_and_are_finite():
    trades = pd.DataFrame({"sleeve_pnl": [0.1, -0.05], "turnover": [0.5, 0.5]})
    daily = pd.DataFrame({
        "equity": [1.1, 1.045],
        "portfolio_return": [0.1, -0.05],
        "gross_exposure": [0.5, 1.0],
        "turnover": [0.5, 0.5],
    })

    metrics = strategy_metrics(trades, daily)

    deviation = np.std([0.1, -0.05], ddof=1)
    assert metrics == pytest.approx({
        "days": 2,
        "trades": 2,
        "total_return": 0.045,
        "annualized_return": 1.045 ** 126 - 1,
        "annualized_volatility": deviation * np.sqrt(252),
        "sharpe": np.mean([0.1, -0.05]) / deviation * np.sqrt(252),
        "max_drawdown": 0.05,
        "win_rate": 0.5,
        "profit_factor": 2.0,
        "exposure": 0.75,
        "turnover": 1.0,
    })
    assert all(np.isfinite(value) for value in metrics.values())


@pytest.mark.parametrize(
    "threshold,cost_bps,symbol_count",
    [
        (0.5, 5, 1), (1.0, 5, 1), ("bad", 5, 1),
        (0.55, -1, 1), (0.55, "bad", 1), (0.55, 5, 0),
    ],
)
def test_ledger_parameters_fail_closed(threshold, cost_bps, symbol_count):
    scored = pd.DataFrame([make_scored("AG_IDX", "2026-01-01 09:05", 0.80, 100.0, 110.0)])

    with pytest.raises(ResearchRejected):
        simulate_standardized_ledger(scored, make_mark_market(scored), threshold, cost_bps, symbol_count)


def test_strategy_metrics_reject_non_finite_inputs():
    with pytest.raises(ResearchRejected):
        strategy_metrics(pd.DataFrame({"sleeve_pnl": []}), pd.DataFrame({
            "equity": [1.0],
            "portfolio_return": [np.nan],
            "gross_exposure": [0.0],
            "turnover": [0.0],
        }))


def test_strategy_metrics_rejects_daily_reconciliation_mismatch():
    daily = pd.DataFrame({
        "equity": [1.2, 1.0],
        "portfolio_return": [0.1, -1 / 11],
        "gross_exposure": [0.0, 0.0],
        "turnover": [0.0, 0.0],
    })

    with pytest.raises(ResearchRejected, match="ledger mismatch"):
        strategy_metrics(pd.DataFrame({"sleeve_pnl": []}), daily)


def test_market_outside_scored_paths_does_not_change_ledger_or_metrics():
    scored = pd.DataFrame([
        make_scored("AG_IDX", "2026-01-02 09:05", 0.80, 100.0, 110.0),
    ])
    market = make_mark_market(scored)
    unrelated = pd.DataFrame([
        {"symbol": "AG_IDX", "segment_id": "AG_IDX:1", "trade_time": "2026-01-01 09:00", "open": 50.0, "close": 50.0},
        {"symbol": "AG_IDX", "segment_id": "AG_IDX:1", "trade_time": "2026-01-03 09:00", "open": 500.0, "close": 500.0},
        {"symbol": "CU_IDX", "segment_id": "CU_IDX:9", "trade_time": "2025-12-01 09:00", "open": 1.0, "close": 1.0},
        {"symbol": "CU_IDX", "segment_id": "CU_IDX:9", "trade_time": "2027-12-01 09:00", "open": 9.0, "close": 9.0},
    ])

    expected = simulate_standardized_ledger(scored, market, 0.55, 5, 2)
    actual = simulate_standardized_ledger(
        scored,
        pd.concat([unrelated, market], ignore_index=True),
        0.55,
        5,
        2,
    )

    pd.testing.assert_frame_equal(expected[0], actual[0])
    pd.testing.assert_frame_equal(expected[1], actual[1])
    assert strategy_metrics(*expected) == strategy_metrics(*actual)


def test_empty_scored_rows_return_empty_ledger_without_replaying_market():
    scored = pd.DataFrame([
        make_scored("AG_IDX", "2026-01-02 09:05", 0.80, 100.0, 110.0),
    ])

    trades, daily = simulate_standardized_ledger(
        scored.iloc[0:0], make_mark_market(scored), 0.55, 5, 1
    )

    assert trades.empty
    assert daily.empty
    assert strategy_metrics(trades, daily)["days"] == 0


def test_entry_must_be_first_same_segment_bar_after_decision():
    row = make_scored("AG_IDX", "2026-01-01 09:05", 0.80, 100.0, 110.0)
    row["entry_time"] = pd.Timestamp("2026-01-01 09:15")
    market = pd.DataFrame([
        {"symbol": "AG_IDX", "segment_id": "AG_IDX:1", "trade_time": time, "open": open_, "close": open_}
        for time, open_ in (
            ("2026-01-01 09:05", 99.0),
            ("2026-01-01 09:10", 101.0),
            ("2026-01-01 09:15", 100.0),
            ("2026-01-01 09:20", 110.0),
        )
    ])

    with pytest.raises(ResearchRejected, match="first bar"):
        simulate_standardized_ledger(pd.DataFrame([row]), market, 0.55, 5, 1)


def test_duplicate_decision_ties_fail_closed_independent_of_shuffle():
    long = make_scored("AG_IDX", "2026-01-01 09:05", 0.80, 100.0, 110.0)
    short = {**long, "probability": 0.20}
    scored = pd.DataFrame([long, short])
    market = make_mark_market(scored)

    for rows in (scored, scored.iloc[::-1].reset_index(drop=True)):
        with pytest.raises(ResearchRejected, match="duplicate decision"):
            simulate_standardized_ledger(rows, market, 0.55, 5, 1)


@pytest.mark.parametrize(
    "trades",
    [pd.DataFrame({"sleeve_pnl": [1.0]}), pd.DataFrame({"sleeve_pnl": [np.inf]})],
)
def test_strategy_metrics_rejects_nonempty_trades_with_empty_daily(trades):
    with pytest.raises(ResearchRejected):
        strategy_metrics(trades, pd.DataFrame())


def test_ledger_market_lookup_count_is_not_per_trade(monkeypatch):
    scored_rows = []
    market_rows = []
    start = pd.Timestamp("2026-01-01 09:00")
    for number in range(40):
        decision = start + pd.Timedelta(minutes=20 * number)
        row = make_scored("AG_IDX", decision, 0.80, 100.0, 101.0)
        scored_rows.append(row)
        market_rows.extend(make_mark_market(pd.DataFrame([row])).to_dict("records"))
    market = pd.DataFrame(market_rows).drop_duplicates(
        ["symbol", "segment_id", "trade_time"]
    )
    calls = 0
    original = research._segment_arrays

    def counted_segment_arrays(group):
        nonlocal calls
        calls += 1
        return original(group)

    monkeypatch.setattr(research, "_segment_arrays", counted_segment_arrays)
    trades, _ = simulate_standardized_ledger(
        pd.DataFrame(scored_rows), market, 0.55, 5, 1
    )

    assert len(trades) == len(scored_rows)
    assert calls == 1


def test_long_short_multibar_marks_reconcile_by_hand_with_unused_cash():
    scored = pd.DataFrame([
        make_scored("AG_IDX", "2026-01-01 23:50", 0.80, 100.0, 110.0),
        make_scored("CU_IDX", "2026-01-01 23:50", 0.20, 200.0, 180.0),
    ])
    scored["exit_time"] = pd.Timestamp("2026-01-03 00:00")
    times = pd.date_range("2026-01-01 23:50", "2026-01-03 00:00", freq="5min")
    frames = []
    for symbol, entry, adverse, exit_ in (
        ("AG_IDX", 100.0, 90.0, 110.0),
        ("CU_IDX", 200.0, 220.0, 180.0),
    ):
        values = np.where(
            times < pd.Timestamp("2026-01-02"),
            entry,
            np.where(times < times[-1], adverse, exit_),
        )
        frames.append(pd.DataFrame({
            "symbol": symbol,
            "segment_id": f"{symbol}:1",
            "trade_time": times,
            "open": values,
            "close": values,
        }))

    trades, daily = simulate_standardized_ledger(
        scored, pd.concat(frames, ignore_index=True), 0.55, 0, 4
    )

    assert trades["sleeve_start_equity"].tolist() == pytest.approx([0.25, 0.25])
    assert trades["sleeve_end_equity"].tolist() == pytest.approx([0.275, 0.275])
    assert daily["equity"].tolist() == pytest.approx([1.0, 0.95, 1.05])
    assert daily["unused_cash"].tolist() == pytest.approx([0.5, 0.5, 0.5])
    assert daily["sleeve_equity"].tolist() == pytest.approx([0.5, 0.45, 0.55])
    assert daily["gross_exposure"].tolist() == pytest.approx([0.25, 0.5, 0.0])


def test_neutral_decision_extends_evaluation_days_without_changing_equity():
    accepted = make_scored("AG_IDX", "2026-01-01 09:05", 0.80, 100.0, 110.0)
    neutral = make_scored("AG_IDX", "2026-01-02 09:05", 0.50, 110.0, 120.0)
    scored = pd.DataFrame([accepted, neutral])
    market = pd.concat([
        make_mark_market(pd.DataFrame([accepted])),
        make_mark_market(pd.DataFrame([neutral])),
    ], ignore_index=True)

    trades, daily = simulate_standardized_ledger(scored, market, 0.55, 0, 1)

    assert len(trades) == 1
    assert daily["date"].tolist() == [
        pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-02")
    ]
    assert daily["equity"].tolist() == pytest.approx([1.1, 1.1])
    assert daily["pnl"].tolist() == pytest.approx([0.1, 0.0])
    assert daily["portfolio_return"].tolist() == pytest.approx([0.1, 0.0])
    assert daily["gross_exposure"].tolist() == pytest.approx([0.5, 0.0])
    assert strategy_metrics(trades, daily)["days"] == 2


def test_all_neutral_scored_rows_return_flat_complete_evaluation_days():
    rows = [
        make_scored("AG_IDX", "2026-01-01 09:05", 0.50, 100.0, 110.0),
        make_scored("AG_IDX", "2026-01-02 09:05", 0.50, 110.0, 120.0),
    ]
    scored = pd.DataFrame(rows)
    market = pd.concat(
        [make_mark_market(pd.DataFrame([row])) for row in rows], ignore_index=True
    )

    trades, daily = simulate_standardized_ledger(scored, market, 0.55, 5, 1)
    metrics = strategy_metrics(trades, daily)

    assert trades.empty
    assert daily["date"].tolist() == [
        pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-02")
    ]
    np.testing.assert_allclose(
        daily[["equity", "pnl", "portfolio_return", "gross_exposure"]],
        [[1.0, 0.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0]],
    )
    assert metrics["days"] == 2
    assert metrics["trades"] == 0
    assert all(metrics[name] == 0.0 for name in (
        "total_return", "annualized_return", "annualized_volatility", "sharpe",
        "max_drawdown", "win_rate", "profit_factor", "exposure", "turnover",
    ))


@pytest.mark.parametrize("bad_market", [None, pd.DataFrame({"open": []})])
def test_empty_scored_still_rejects_bad_market_contract(bad_market):
    scored = pd.DataFrame([
        make_scored("AG_IDX", "2026-01-01 09:05", 0.50, 100.0, 110.0)
    ]).iloc[0:0]

    with pytest.raises(ResearchRejected):
        simulate_standardized_ledger(scored, bad_market, 0.55, 5, 1)


def test_empty_scored_accepts_typed_empty_market():
    scored = pd.DataFrame([
        make_scored("AG_IDX", "2026-01-01 09:05", 0.50, 100.0, 110.0)
    ]).iloc[0:0]
    market = make_mark_market(pd.DataFrame([
        make_scored("AG_IDX", "2026-01-01 09:05", 0.50, 100.0, 110.0)
    ])).iloc[0:0]

    trades, daily = simulate_standardized_ledger(scored, market, 0.55, 5, 1)

    assert trades.empty
    assert daily.empty


def test_decision_to_entry_gap_is_rejected_even_when_entry_is_next_row():
    row = make_scored("AG_IDX", "2026-01-01 09:00", 0.80, 100.0, 110.0)
    row["entry_time"] = pd.Timestamp("2026-01-01 10:00")
    row["exit_time"] = pd.Timestamp("2026-01-01 10:10")
    market = pd.DataFrame([
        {"symbol": "AG_IDX", "segment_id": "AG_IDX:1", "trade_time": time, "open": open_, "close": open_}
        for time, open_ in (
            ("2026-01-01 09:00", 99.0),
            ("2026-01-01 10:00", 100.0),
            ("2026-01-01 10:05", 105.0),
            ("2026-01-01 10:10", 110.0),
        )
    ])

    with pytest.raises(ResearchRejected, match="continuous|missing"):
        simulate_standardized_ledger(pd.DataFrame([row]), market, 0.55, 5, 1)


def make_attack_context(rows=80, holdout_start=50, holdout_end=70):
    dataset = make_model_dataset(rows)
    times = pd.DatetimeIndex(dataset["decision_time"].unique())
    holdout_fold = research.TemporalFold(
        "holdout", times[:holdout_start], times[holdout_start:holdout_end]
    )
    candidate = Candidate("logistic_c0.1", 0.55)
    config = ResearchConfig(embargo_bars=0)
    market = make_model_market(dataset)
    train = purged_training_rows(
        dataset, holdout_fold.train_times, holdout_fold.evaluation_times[0], 0
    )
    evaluation = dataset[
        dataset["decision_time"].isin(holdout_fold.evaluation_times)
    ]
    execution_identity = research._attack_execution_identity(
        train, evaluation, research._evaluation_market(evaluation, market)
    )
    context = {
        "dataset": dataset,
        "segmented": market,
        "partitions": {"holdout_fold": holdout_fold},
        "base": {
            "final_candidate": candidate,
            "holdout": {
                "predictive_metrics": {"roc_auc": 0.60},
                "cost_metrics": {5: {"total_return": 0.10}},
                "evaluation_identity": {"id": "locked-holdout"},
                "attack_execution_identity": execution_identity,
            },
        },
        "config": config,
    }
    return context


def test_prefix_attack_rebuilds_and_preserves_frozen_prefix():
    _, bars = make_causal_evaluation_fixture(days=6)
    bars = bars.drop(columns="segment_id")
    segmented, _ = validate_and_segment(bars)
    dataset = build_causal_dataset(segmented)
    times = pd.DatetimeIndex(dataset["decision_time"].unique()).sort_values()
    split = len(times) // 2
    fold = research.TemporalFold("holdout", times[:split], times[split:])
    context = {
        "bars": bars,
        "partitions": {
            "outer_folds": (),
            "holdout_fold": fold,
            "eligible_symbols": (dataset["symbol"].iloc[0],),
        },
        "base": {
            "outer_results": [],
            "final_candidate": Candidate("logistic_c0.1", 0.55),
            "holdout": {
                "candidate": Candidate("logistic_c0.1", 0.55),
                "evaluation_identity": {"id": "locked-holdout"},
            },
        },
        "config": ResearchConfig(embargo_bars=0),
    }
    eligible_dataset = dataset[
        dataset["symbol"].eq(context["partitions"]["eligible_symbols"][0])
    ].copy()
    train = purged_training_rows(
        eligible_dataset, fold.train_times, fold.evaluation_times[0], 0
    )
    evaluation = eligible_dataset[
        eligible_dataset["decision_time"].isin(fold.evaluation_times)
    ]
    context["base"]["holdout"]["attack_execution_identity"] = (
        research._attack_execution_identity(
            train,
            evaluation,
            research._evaluation_market(evaluation, segmented),
        )
    )

    result = research.run_prefix_attack(context)

    assert result["id"] == "prefix_invariance"
    assert result["passed"] is True
    assert result["checks"] == {
        "features": True,
        "matured_labels": True,
        "split_membership": True,
        "probabilities": True,
    }
    assert result["max_probability_difference"] <= 1e-12
    assert result["candidate"] == context["base"]["final_candidate"]
    assert result["threshold"] == context["base"]["final_candidate"].threshold
    assert result["kind"] == "prefix"
    assert result["columns"] == FEATURE_COLUMNS
    assert result["baseline_evaluation_identity"] == {"id": "locked-holdout"}
    assert result["attack_execution_identity"] == context["base"]["holdout"][
        "attack_execution_identity"
    ]
    assert len(result["consistency_sha256"]) == 64
    assert "evidence_sha256" not in result

    foreign_train = purged_training_rows(
        dataset, fold.train_times, fold.evaluation_times[0], 0
    )
    foreign_evaluation = dataset[
        dataset["decision_time"].isin(fold.evaluation_times)
    ]
    context["base"]["holdout"]["attack_execution_identity"] = (
        research._attack_execution_identity(
            foreign_train,
            foreign_evaluation,
            research._evaluation_market(foreign_evaluation, segmented),
        )
    )
    with pytest.raises(ResearchRejected, match="locked baseline identity"):
        research.run_prefix_attack(context)


def test_whitelist_attack_rejects_future_and_unknown_columns():
    matrix = pd.DataFrame({name: [0.0] for name in FEATURE_COLUMNS})

    with pytest.raises(ResearchRejected, match="feature whitelist"):
        assert_feature_columns(matrix.assign(future_return=1.0))
    with pytest.raises(ResearchRejected, match="feature whitelist"):
        assert_feature_columns(matrix.assign(unknown=1.0))


def test_label_shuffle_attack_uses_twenty_within_symbol_seeded_permutations(
    monkeypatch,
):
    context = make_attack_context()
    source = context["dataset"].copy(deep=True)
    captured = []

    def capture_fit(candidate, x_train, y_train, weights, x_evaluation, config):
        captured.append(np.asarray(y_train).copy())
        return np.linspace(0.1, 0.9, len(x_evaluation)), object()

    monkeypatch.setattr(research, "_fit_matrix", capture_fit)

    result = research.run_label_shuffle_attack(context)

    pd.testing.assert_frame_equal(context["dataset"], source)
    assert len(captured) == len(result["metrics"]) == 20
    train = purged_training_rows(
        source,
        context["partitions"]["holdout_fold"].train_times,
        context["partitions"]["holdout_fold"].evaluation_times[0],
        0,
    )
    for number, observed in enumerate(captured):
        expected = train["label"].copy()
        rng = np.random.default_rng(42 + number)
        for _, rows in train.groupby("symbol", sort=False):
            expected.loc[rows.index] = rng.permutation(rows["label"].to_numpy())
        np.testing.assert_array_equal(observed, expected)
        for symbol, rows in train.groupby("symbol"):
            assert sorted(observed[train["symbol"].eq(symbol)]) == sorted(rows["label"])
    assert [row["seed"] for row in result["metrics"]] == list(range(42, 62))
    assert np.isfinite(result["max_auc"])
    assert np.isfinite(result["median_return_5bps"])
    assert result["kind"] == "label_shuffle"
    assert result["columns"] == FEATURE_COLUMNS
    assert result["baseline_evaluation_identity"] == {"id": "locked-holdout"}
    assert result["attack_execution_identity"] == context["base"]["holdout"][
        "attack_execution_identity"
    ]


@pytest.mark.parametrize(
    "kind,expected_columns",
    [
        ("noise", tuple(f"noise_{number}" for number in range(1, 6))),
        (
            "calendar",
            (
                "time_of_day_sin", "time_of_day_cos",
                "day_of_week_sin", "day_of_week_cos",
            ),
        ),
    ],
)
def test_feature_attack_is_local_deterministic_and_keeps_baseline_candidate(
    monkeypatch, kind, expected_columns,
):
    context = make_attack_context()
    source = context["dataset"].copy(deep=True)
    original_features = FEATURE_COLUMNS
    captured = []

    def capture_fit(candidate, x_train, y_train, weights, x_evaluation, config):
        captured.append((candidate, x_train.copy(), x_evaluation.copy()))
        return np.linspace(0.1, 0.9, len(x_evaluation)), object()

    monkeypatch.setattr(research, "_fit_matrix", capture_fit)

    first = research.run_feature_attack(context, kind)
    second = research.run_feature_attack(context, kind)

    assert first == second
    assert first["candidate"] == context["base"]["final_candidate"]
    assert first["threshold"] == context["base"]["final_candidate"].threshold
    assert first["columns"] == expected_columns
    assert FEATURE_COLUMNS == original_features
    pd.testing.assert_frame_equal(context["dataset"], source)
    assert len(captured) == 2
    for candidate, train, evaluation in captured:
        assert candidate == context["base"]["final_candidate"]
        assert tuple(train.columns) == FEATURE_COLUMNS + expected_columns
        assert tuple(evaluation.columns) == FEATURE_COLUMNS + expected_columns
        assert np.isfinite(train.to_numpy(dtype=float)).all()
        assert np.isfinite(evaluation.to_numpy(dtype=float)).all()
    pd.testing.assert_frame_equal(captured[0][1], captured[1][1])
    pd.testing.assert_frame_equal(captured[0][2], captured[1][2])
    assert first["kind"] == kind
    assert first["baseline_evaluation_identity"] == {"id": "locked-holdout"}
    assert first["attack_execution_identity"] == context["base"]["holdout"][
        "attack_execution_identity"
    ]


def test_attack_identity_evidence_does_not_alias_the_locked_baseline(monkeypatch):
    context = make_attack_context()

    def capture_fit(candidate, x_train, y_train, weights, x_evaluation, config):
        return np.linspace(0.1, 0.9, len(x_evaluation)), object()

    monkeypatch.setattr(research, "_fit_matrix", capture_fit)
    result = research.run_feature_attack(context, "noise")
    result["baseline_evaluation_identity"]["id"] = "tampered"

    assert context["base"]["holdout"]["evaluation_identity"] == {
        "id": "locked-holdout"
    }


def test_feature_attack_from_another_real_holdout_cannot_be_mixed(monkeypatch):
    original = passing_gate_context()
    other = make_attack_context(80, holdout_start=55, holdout_end=75)

    def capture_fit(candidate, x_train, y_train, weights, x_evaluation, config):
        return np.linspace(0.1, 0.9, len(x_evaluation)), object()

    monkeypatch.setattr(research, "_fit_matrix", capture_fit)
    foreign = research.run_feature_attack(other, "noise")
    original["attacks"] = [
        foreign if row["id"] == "noise_features" else row
        for row in original["attacks"]
    ]

    gates = research.evaluate_acceptance_gates(original)

    assert foreign["attack_execution_identity"] != original["holdout"][
        "attack_execution_identity"
    ]
    assert all(gate["passed"] is False for gate in gates)
    assert research.research_status(gates) == "RESEARCH_REJECTED"


def test_pure_evaluator_consistency_checksum_is_not_source_authentication(monkeypatch):
    original = passing_gate_context()
    other = make_attack_context(80, holdout_start=55, holdout_end=75)

    def capture_fit(candidate, x_train, y_train, weights, x_evaluation, config):
        return np.linspace(0.1, 0.9, len(x_evaluation)), object()

    monkeypatch.setattr(research, "_fit_matrix", capture_fit)
    foreign = research.run_feature_attack(other, "noise")
    foreign["baseline_evaluation_identity"] = original["holdout"][
        "evaluation_identity"
    ]
    foreign["attack_execution_identity"] = original["holdout"][
        "attack_execution_identity"
    ]
    foreign["consistency_sha256"] = research._attack_consistency_sha256(foreign)
    original["attacks"] = [
        foreign if row["id"] == "noise_features" else row
        for row in original["attacks"]
    ]

    gates = research.evaluate_acceptance_gates(original)

    assert all(gate["passed"] is True for gate in gates)
    assert research.research_status(gates) == "RESEARCH_ACCEPTED"


def _patch_official_attack_producers(monkeypatch, context, noise=None):
    attacks = {row["id"]: row for row in context["attacks"]}
    monkeypatch.setattr(
        research, "run_prefix_attack", lambda built: dict(attacks["prefix_invariance"])
    )
    monkeypatch.setattr(
        research, "run_label_shuffle_attack", lambda built: dict(attacks["label_shuffle"])
    )
    monkeypatch.setattr(
        research,
        "run_feature_attack",
        lambda built, kind: dict(
            noise if kind == "noise" and noise is not None
            else attacks[f"{kind}_features"]
        ),
    )


def _official_adversarial_arguments(context):
    base = {
        key: context[key]
        for key in ("outer_results", "holdout", "final_candidate")
    }
    partitions = {
        **context["partitions"],
        "eligible_symbols": context["eligible_symbols"],
    }
    return (
        base,
        pd.DataFrame({"raw": [1]}),
        context["dataset"],
        context["segmented"],
        partitions,
        context["checks"],
        context["config"],
    )


def _run_official_adversarial_checks(context):
    return research.run_adversarial_checks(
        *_official_adversarial_arguments(context)
    )


def test_official_adversarial_entry_has_no_attack_or_context_injection(monkeypatch):
    context = passing_gate_context()
    _patch_official_attack_producers(monkeypatch, context)

    signature = inspect.signature(research.run_adversarial_checks)
    assert "context" not in signature.parameters
    assert "attacks" not in signature.parameters
    with pytest.raises(TypeError):
        research.run_adversarial_checks(
            *_official_adversarial_arguments(context), attacks=[]
        )

    result = _run_official_adversarial_checks(context)

    assert [row["id"] for row in result["attacks"]] == [
        "prefix_invariance", "feature_whitelist", "label_shuffle",
        "noise_features", "calendar_features",
    ]
    produced = {row["id"]: row for row in result["attacks"]}
    expected = {row["id"]: row for row in context["attacks"]}
    for attack_id in (
        "prefix_invariance", "label_shuffle", "noise_features",
        "calendar_features",
    ):
        assert produced[attack_id] == expected[attack_id]
    names = ("base", "bars", "dataset", "segmented", "partitions", "checks", "config")
    expected_context = dict(zip(names, _official_adversarial_arguments(context)))
    expected_context["attacks"] = result["attacks"]
    assert result["gates"] == research.evaluate_acceptance_gates(expected_context)
    assert result["status"] == research.research_status(result["gates"])
    assert result["status"] == "RESEARCH_ACCEPTED"


def test_official_adversarial_entry_rejects_a_foreign_producer_result(monkeypatch):
    context = passing_gate_context()
    other = make_attack_context(80, holdout_start=55, holdout_end=75)

    def capture_fit(candidate, x_train, y_train, weights, x_evaluation, config):
        return np.linspace(0.1, 0.9, len(x_evaluation)), object()

    monkeypatch.setattr(research, "_fit_matrix", capture_fit)
    foreign = research.run_feature_attack(other, "noise")
    _patch_official_attack_producers(monkeypatch, context, noise=foreign)

    result = _run_official_adversarial_checks(context)

    assert result["status"] == "RESEARCH_REJECTED"
    assert all(gate["passed"] is False for gate in result["gates"])


def passing_gate_context():
    dataset = make_model_dataset(80)
    market = make_model_market(dataset)
    times = pd.DatetimeIndex(dataset["decision_time"].unique())
    temporal = {
        "outer_1": research.TemporalFold("outer_1", times[:20], times[20:30]),
        "outer_2": research.TemporalFold("outer_2", times[:30], times[30:40]),
        "outer_3": research.TemporalFold("outer_3", times[:40], times[40:50]),
        "holdout": research.TemporalFold("holdout", times[:50], times[50:70]),
    }
    config = ResearchConfig(embargo_bars=6)
    trade = pd.DataFrame([{
        "symbol": "S00",
        "decision_time": pd.Timestamp("2026-01-01 09:00"),
        "entry_time": pd.Timestamp("2026-01-01 09:05"),
        "exit_time": pd.Timestamp("2026-01-01 09:15"),
        "direction": 1,
        "entry_open": 100.0,
        "exit_open": 101.0,
    }])

    def fold(name):
        temporal_fold = temporal[name]
        train = purged_training_rows(
            dataset,
            temporal_fold.train_times,
            temporal_fold.evaluation_times[0],
            config.embargo_bars,
        )
        evaluation = dataset[
            dataset["decision_time"].isin(temporal_fold.evaluation_times)
        ]
        return {
            "fold": name,
            "predictive_metrics": {"roc_auc": 0.60, "brier_score": 0.20},
            "cost_metrics": {
                0: {"total_return": 0.12, "max_drawdown": 0.08},
                2: {"total_return": 0.11, "max_drawdown": 0.08},
                5: {"total_return": 0.10, "max_drawdown": 0.09},
                10: {"total_return": 0.08, "max_drawdown": 0.10},
                20: {"total_return": 0.04, "max_drawdown": 0.12},
            },
            "trades": {
                cost: trade.copy() for cost in (0, 2, 5, 10, 20)
            },
            "benchmarks": {
                "dummy_prior": {
                    "predictive_metrics": {"brier_score": 0.25},
                    "cost_metrics": {5: {"total_return": 0.01}},
                },
                "equal_weight_long_only": {
                    "cost_metrics": {5: {"total_return": 0.02}},
                },
            },
            "split_cutoffs": {
                "training_start": train["decision_time"].min(),
                "training_cutoff": train["decision_time"].max(),
                "label_cutoff": train["label_end_time"].max(),
                "evaluation_start": evaluation["decision_time"].min(),
                "evaluation_end": evaluation["decision_time"].max(),
            },
        }

    symbols = pd.DataFrame([
        {"symbol": f"S{number:02d}", "cost_bps": 5, "total_return": 0.01}
        for number in range(10)
    ])
    holdout = fold("holdout")
    holdout["bootstrap"] = {
        "blocks": {
            str(days): {
                "samples": 1000, "block_days": days,
                "p05": 0.01, "p50": 0.10, "p95": 0.20,
            }
            for days in (5, 10, 20)
        },
        "worst_p05": 0.01,
    }
    holdout["symbol_metrics"] = symbols
    candidate = Candidate("logistic_c0.1", 0.55)
    holdout_evaluation = dataset[
        dataset["decision_time"].isin(temporal["holdout"].evaluation_times)
    ]
    holdout["evaluation_identity"] = research._evaluation_identity(
        candidate,
        {"model_identity": "fixture", "model_parameters": {}},
        holdout_evaluation,
        market,
        config,
    )
    holdout_train = purged_training_rows(
        dataset,
        temporal["holdout"].train_times,
        temporal["holdout"].evaluation_times[0],
        config.embargo_bars,
    )
    holdout["attack_execution_identity"] = research._attack_execution_identity(
        holdout_train,
        holdout_evaluation,
        research._evaluation_market(holdout_evaluation, market),
    )
    def frozen():
        return {
            "candidate": candidate,
            "threshold": candidate.threshold,
            "baseline_evaluation_identity": dict(holdout["evaluation_identity"]),
        }
    context = {
        "checks": {"structural": True, "causal": True, "ledger": True},
        "outer_results": [fold(f"outer_{number}") for number in range(1, 4)],
        "holdout": holdout,
        "dataset": dataset,
        "segmented": market,
        "partitions": {
            "outer_folds": [temporal[f"outer_{number}"] for number in range(1, 4)],
            "holdout_fold": temporal["holdout"],
            "eligible_symbols": ("AG_IDX", "CU_IDX"),
        },
        "config": config,
        "eligible_symbols": tuple(symbols["symbol"]),
        "attacks": [
            {
                "id": "prefix_invariance", "kind": "prefix",
                "columns": FEATURE_COLUMNS, "passed": True,
                "checks": {
                    "features": True,
                    "matured_labels": True,
                    "split_membership": True,
                    "probabilities": True,
                },
                "compared_rows": 100,
                "max_probability_difference": 0.0,
                **frozen(),
            },
            {
                "id": "feature_whitelist", "kind": "whitelist",
                "columns": FEATURE_COLUMNS, "rejected_columns": (
                    "future_return", "unknown",
                ),
                "passed": True, **frozen(),
            },
            {
                "id": "label_shuffle", "kind": "label_shuffle",
                "columns": FEATURE_COLUMNS, "passed": True, **frozen(),
                "metrics": [
                    {"seed": seed, "roc_auc": 0.49, "return_5bps": -0.01}
                    for seed in range(42, 62)
                ],
                "max_auc": 0.49,
                "median_return_5bps": -0.01,
            },
            {
                "id": "noise_features", "kind": "noise",
                "columns": tuple(f"noise_{number}" for number in range(1, 6)),
                "passed": True, **frozen(),
                "roc_auc": 0.605, "return_5bps": 0.12,
            },
            {
                "id": "calendar_features", "kind": "calendar",
                "columns": (
                    "time_of_day_sin", "time_of_day_cos",
                    "day_of_week_sin", "day_of_week_cos",
                ),
                "passed": True, **frozen(),
                "roc_auc": 0.605, "return_5bps": 0.12,
            },
        ],
        "final_candidate": candidate,
    }
    for attack in context["attacks"]:
        attack["attack_execution_identity"] = dict(
            holdout["attack_execution_identity"]
        )
        attack["consistency_sha256"] = research._attack_consistency_sha256(attack)
    return context


def _attack(context, attack_id):
    return next(row for row in context["attacks"] if row["id"] == attack_id)


def test_brier_gate_requires_model_to_beat_dummy_in_every_fold():
    context = passing_gate_context()
    context["outer_results"][1]["predictive_metrics"][
        "brier_score"
    ] = context["outer_results"][1]["benchmarks"]["dummy_prior"][
        "predictive_metrics"
    ]["brier_score"]

    gate = next(
        row for row in research.evaluate_acceptance_gates(context)
        if row["id"] == "brier_better_than_dummy_each_fold"
    )

    assert gate["passed"] is False
    assert gate["affected_fold"] == "outer_2"


def test_baseline_gate_requires_5bp_return_to_beat_both_benchmarks():
    context = passing_gate_context()
    holdout = context["holdout"]
    holdout["benchmarks"]["equal_weight_long_only"]["cost_metrics"][5][
        "total_return"
    ] = holdout["cost_metrics"][5]["total_return"]

    gate = next(
        row for row in research.evaluate_acceptance_gates(context)
        if row["id"] == "baseline_superiority_each_fold"
    )

    assert gate["passed"] is False
    assert gate["affected_fold"] == "holdout"


def test_bootstrap_gate_uses_worst_of_all_required_blocks():
    context = passing_gate_context()
    context["holdout"]["bootstrap"]["blocks"]["20"]["p05"] = 0.0
    context["holdout"]["bootstrap"]["worst_p05"] = 0.0

    gate = next(
        row for row in research.evaluate_acceptance_gates(context)
        if row["id"] == "positive_bootstrap_lower_bound"
    )

    assert gate["passed"] is False


def _refresh_attack_execution_evidence(context):
    train, evaluation, market, _, _ = research._attack_domain(context)
    identity = research._attack_execution_identity(train, evaluation, market)
    context["holdout"]["attack_execution_identity"] = identity
    for attack in context["attacks"]:
        attack["attack_execution_identity"] = dict(identity)
        attack["consistency_sha256"] = research._attack_consistency_sha256(attack)


def _attack_ready_partition_dataset():
    dataset = make_partition_dataset().assign(
        segment_id=lambda rows: rows["symbol"] + ":1",
        exit_time=lambda rows: rows["label_end_time"],
    )
    market = dataset.loc[:, ["symbol", "segment_id", "decision_time"]].rename(
        columns={"decision_time": "trade_time"}
    )
    market = market.assign(open=100.0, close=100.0)
    return dataset, market


@pytest.mark.parametrize(
    "gate_id,mutate",
    [
        ("integrity_checks", lambda c: c["checks"].__setitem__("ledger", False)),
        ("auc_above_chance_each_fold", lambda c: c["holdout"]["predictive_metrics"].__setitem__("roc_auc", 0.50)),
        ("brier_better_than_dummy_each_fold", lambda c: c["outer_results"][1]["predictive_metrics"].__setitem__("brier_score", 0.25)),
        ("positive_5bps_each_fold", lambda c: c["outer_results"][1]["cost_metrics"][5].__setitem__("total_return", -0.001)),
        ("baseline_superiority_each_fold", lambda c: c["holdout"]["benchmarks"]["dummy_prior"]["cost_metrics"][5].__setitem__("total_return", 0.10)),
        ("positive_bootstrap_lower_bound", lambda c: (c["holdout"]["bootstrap"]["blocks"]["20"].__setitem__("p05", 0.0), c["holdout"]["bootstrap"].__setitem__("worst_p05", 0.0))),
        ("label_shuffle", lambda c: _attack(c, "label_shuffle").__setitem__("median_return_5bps", 0.001)),
        ("feature_attacks", lambda c: _attack(c, "noise_features").__setitem__("roc_auc", 0.62)),
        ("positive_symbol_fraction", lambda c: c["holdout"].__setitem__("symbol_metrics", c["holdout"]["symbol_metrics"].assign(total_return=[-0.01] * 6 + [0.01] * 4))),
        ("positive_symbol_concentration", lambda c: c["holdout"].__setitem__("symbol_metrics", c["holdout"]["symbol_metrics"].assign(total_return=[1.0] + [0.01] * 9))),
        ("ten_bps_resilience", lambda c: c["outer_results"][0]["cost_metrics"][10].__setitem__("max_drawdown", 0.20)),
        ("cost_monotonicity", lambda c: c["holdout"]["cost_metrics"][20].__setitem__("total_return", 0.09)),
    ],
)
def test_each_acceptance_gate_is_non_negotiable(gate_id, mutate):
    context = passing_gate_context()
    mutate(context)

    gates = research.evaluate_acceptance_gates(context)
    failed = next(gate for gate in gates if gate["id"] == gate_id)

    assert len(gates) == 12
    assert failed["passed"] is False
    assert failed["reason"]
    assert research.research_status(gates) == "RESEARCH_REJECTED"


def test_all_acceptance_gates_pass_only_with_complete_finite_evidence():
    gates = research.evaluate_acceptance_gates(passing_gate_context())

    assert len(gates) == 12
    assert all(gate["passed"] is True and gate["reason"] for gate in gates)
    assert research.research_status(gates) == "RESEARCH_ACCEPTED"


@pytest.mark.parametrize("case", ["short_shuffle", "non_finite", "profitable_shuffle"])
def test_statistical_gates_fail_closed_on_incomplete_or_hostile_results(case):
    context = passing_gate_context()
    shuffled = _attack(context, "label_shuffle")
    if case == "short_shuffle":
        shuffled["metrics"] = shuffled["metrics"][:-1]
    elif case == "non_finite":
        shuffled["max_auc"] = np.nan
    else:
        shuffled["median_return_5bps"] = 0.001

    gate = next(
        row for row in research.evaluate_acceptance_gates(context)
        if row["id"] == "label_shuffle"
    )

    assert gate["passed"] is False
    assert research.research_status([gate]) == "RESEARCH_REJECTED"


def test_deliberately_leaking_feature_attack_fails_gate():
    context = passing_gate_context()
    _attack(context, "calendar_features")["return_5bps"] = 0.151

    gate = next(
        row for row in research.evaluate_acceptance_gates(context)
        if row["id"] == "feature_attacks"
    )

    assert gate["passed"] is False


def test_integrity_gate_executes_purge_and_embargo_evidence():
    context = passing_gate_context()
    dataset, market = _attack_ready_partition_dataset()
    config = ResearchConfig(min_symbols=2, min_fold_rows=50, embargo_bars=6)
    partitions = make_temporal_partitions(dataset, config)
    context.update({
        "dataset": dataset, "segmented": market,
        "partitions": partitions, "config": config,
    })
    folds = [*partitions["outer_folds"], partitions["holdout_fold"]]
    results = [*context["outer_results"], context["holdout"]]
    for fold, result in zip(folds, results):
        train = purged_training_rows(
            dataset, fold.train_times, fold.evaluation_times[0], config.embargo_bars
        )
        evaluation = dataset[dataset["decision_time"].isin(fold.evaluation_times)]
        result["split_cutoffs"] = {
            "training_start": train["decision_time"].min(),
            "training_cutoff": train["decision_time"].max(),
            "label_cutoff": train["label_end_time"].max(),
            "evaluation_start": evaluation["decision_time"].min(),
            "evaluation_end": evaluation["decision_time"].max(),
        }
    _refresh_attack_execution_evidence(context)
    results[1]["split_cutoffs"]["label_cutoff"] = folds[1].evaluation_times[0]

    gate = next(
        row for row in research.evaluate_acceptance_gates(context)
        if row["id"] == "integrity_checks"
    )

    assert gate["passed"] is False
    assert gate["observed"]["purge_outer_2"] is False
    assert gate["affected_fold"] == "purge_outer_2"


def test_duplicate_fold_identity_cannot_hide_a_failed_outer_fold():
    context = passing_gate_context()
    context["outer_results"][1]["fold"] = "outer_1"
    context["outer_results"][1]["predictive_metrics"]["roc_auc"] = 0.10

    gates = research.evaluate_acceptance_gates(context)

    assert all(gate["passed"] is False for gate in gates)
    assert all("fold" in gate["reason"] for gate in gates)
    assert research.research_status(gates) == "RESEARCH_REJECTED"


def test_raw_partition_names_are_validated_before_fold_observations():
    context = passing_gate_context()
    folds = context["partitions"]["outer_folds"]
    context["partitions"]["outer_folds"] = [
        research.TemporalFold("outer_3", fold.train_times, fold.evaluation_times)
        for fold in folds
    ]

    gates = research.evaluate_acceptance_gates(context)

    assert all(gate["passed"] is False for gate in gates)
    assert all("partition" in gate["reason"] for gate in gates)
    assert research.research_status(gates) == "RESEARCH_REJECTED"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: _attack(c, "noise_features").pop("candidate"),
        lambda c: c["attacks"].append({**c["attacks"][0], "id": "unknown"}),
        lambda c: c["attacks"].append(dict(c["attacks"][0])),
        lambda c: _attack(c, "noise_features").__setitem__(
            "candidate", Candidate("logistic_c1.0", 0.55)
        ),
        lambda c: _attack(c, "noise_features").__setitem__("threshold", 0.58),
        lambda c: _attack(c, "noise_features").__setitem__(
            "columns", ("future_return",) + _attack(c, "noise_features")["columns"][1:]
        ),
        lambda c: _attack(c, "noise_features").__setitem__(
            "baseline_evaluation_identity", {"id": "other-holdout"}
        ),
        lambda c: _attack(c, "noise_features")[
            "baseline_evaluation_identity"
        ].__setitem__("id", "other-holdout"),
        lambda c: _attack(c, "noise_features").__setitem__("kind", "calendar"),
    ],
    ids=[
        "missing_metadata", "unknown_attack", "duplicate_attack", "changed_model",
        "changed_threshold", "future_return_column", "changed_holdout",
        "changed_nested_holdout", "changed_kind",
    ],
)
def test_attack_evidence_is_exactly_bound_to_the_frozen_baseline(mutate):
    context = passing_gate_context()
    mutate(context)

    gates = research.evaluate_acceptance_gates(context)

    assert all(gate["passed"] is False for gate in gates)
    assert research.research_status(gates) == "RESEARCH_REJECTED"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda row: row.pop("checks"),
        lambda row: row["checks"].__setitem__("probabilities", False),
        lambda row: row.__setitem__("compared_rows", 0),
        lambda row: row.__setitem__("max_probability_difference", np.nan),
        lambda row: row.__setitem__("max_probability_difference", 2e-12),
    ],
    ids=["missing_checks", "failed_check", "no_rows", "non_finite", "too_different"],
)
def test_prefix_attack_summary_is_executable_evidence(mutate):
    context = passing_gate_context()
    mutate(_attack(context, "prefix_invariance"))

    gates = research.evaluate_acceptance_gates(context)

    assert all(gate["passed"] is False for gate in gates)
    assert research.research_status(gates) == "RESEARCH_REJECTED"


@pytest.mark.parametrize("case", ["missing", "extra", "mismatch"])
def test_split_cutoff_evidence_must_be_complete_and_exact(case):
    context = passing_gate_context()
    dataset, market = _attack_ready_partition_dataset()
    config = ResearchConfig(min_symbols=2, min_fold_rows=50, embargo_bars=6)
    partitions = make_temporal_partitions(dataset, config)
    context.update({
        "dataset": dataset, "segmented": market,
        "partitions": partitions, "config": config,
    })
    folds = [*partitions["outer_folds"], partitions["holdout_fold"]]
    results = [*context["outer_results"], context["holdout"]]
    for fold, result in zip(folds, results):
        train = purged_training_rows(
            dataset, fold.train_times, fold.evaluation_times[0], config.embargo_bars
        )
        evaluation = dataset[dataset["decision_time"].isin(fold.evaluation_times)]
        result["split_cutoffs"] = {
            "training_start": train["decision_time"].min(),
            "training_cutoff": train["decision_time"].max(),
            "label_cutoff": train["label_end_time"].max(),
            "evaluation_start": evaluation["decision_time"].min(),
            "evaluation_end": evaluation["decision_time"].max(),
        }
    _refresh_attack_execution_evidence(context)
    if case == "missing":
        results[0]["split_cutoffs"].pop("training_start")
    elif case == "extra":
        results[0]["split_cutoffs"]["future_cutoff"] = folds[0].evaluation_times[-1]
    else:
        results[0]["split_cutoffs"]["training_cutoff"] += pd.Timedelta(days=1)

    gate = next(
        row for row in research.evaluate_acceptance_gates(context)
        if row["id"] == "integrity_checks"
    )

    assert gate["passed"] is False
    assert research.research_status(research.evaluate_acceptance_gates(context)) == "RESEARCH_REJECTED"


@pytest.mark.parametrize("case", ["missing", "empty", "different"])
def test_cost_gate_requires_nonempty_identical_trade_identity_each_fold(case):
    context = passing_gate_context()
    trades = context["outer_results"][0]["trades"]
    if case == "missing":
        trades.pop(20)
    elif case == "empty":
        trades[20] = trades[20].iloc[0:0]
    else:
        trades[20] = trades[20].assign(direction=-1)

    gate = next(
        row for row in research.evaluate_acceptance_gates(context)
        if row["id"] == "cost_monotonicity"
    )

    assert gate["passed"] is False
    assert research.research_status(research.evaluate_acceptance_gates(context)) == "RESEARCH_REJECTED"


@pytest.mark.parametrize("metric,limit", [("roc_auc", 0.01), ("return_5bps", 0.05)])
def test_feature_attack_gain_boundary_has_only_roundoff_tolerance(metric, limit):
    context = passing_gate_context()
    baseline = (
        context["holdout"]["predictive_metrics"]["roc_auc"]
        if metric == "roc_auc"
        else context["holdout"]["cost_metrics"][5]["total_return"]
    )
    attack = _attack(context, "noise_features")
    attack[metric] = baseline + limit + 0.5e-12
    attack["consistency_sha256"] = research._attack_consistency_sha256(attack)

    boundary = next(
        row for row in research.evaluate_acceptance_gates(context)
        if row["id"] == "feature_attacks"
    )
    assert boundary["passed"] is True

    attack[metric] = baseline + limit + 2e-12
    attack["consistency_sha256"] = research._attack_consistency_sha256(attack)
    exceeded = next(
        row for row in research.evaluate_acceptance_gates(context)
        if row["id"] == "feature_attacks"
    )
    assert exceeded["passed"] is False


EXPECTED_REPORT_FILES = {
    "report.html", "report.md", "report.json", "data_quality.csv",
    "fold_metrics.csv", "symbol_metrics.csv", "trades.csv",
}
EXPECTED_GATE_IDS = (
    "integrity_checks", "auc_above_chance_each_fold",
    "brier_better_than_dummy_each_fold", "positive_5bps_each_fold",
    "baseline_superiority_each_fold", "positive_bootstrap_lower_bound",
    "label_shuffle", "feature_attacks", "positive_symbol_fraction",
    "positive_symbol_concentration", "ten_bps_resilience",
    "cost_monotonicity",
)
EXPECTED_ATTACK_IDS = tuple(research.ATTACK_EVIDENCE)


def official_attack_fixture():
    return [{"id": attack_id, "passed": True} for attack_id in EXPECTED_ATTACK_IDS]


def official_gate_fixture(failed_id="positive_5bps_each_fold"):
    return [{
        "id": gate_id,
        "passed": gate_id != failed_id,
        "observed": 0.0 if gate_id == failed_id else 1.0,
        "required": "fixture requirement",
        "affected_fold": "outer_1" if gate_id == failed_id else None,
        "reason": "fixture gate rejection" if gate_id == failed_id else "passed",
    } for gate_id in EXPECTED_GATE_IDS]


def rejected_result_fixture():
    result = research.rejected_result(
        "rejected-fixture", ResearchConfig(min_symbols=1), "fixture rejection"
    )
    result.update({
        "cutoffs": {
            "outer_1": {
                "evaluation_start": "2026-01-02T09:00:00",
                "evaluation_end": "2026-01-02T09:10:00",
            },
        },
        "data_quality": [{
            "symbol": "AG_IDX", "status": "INCLUDED", "reason": "",
        }],
        "fold_metrics": [{
            "evaluation_kind": "base", "fold": "outer_1", "cost_bps": 5,
            "total_return": -0.01, "trade_count": 1,
            "trade_sleeve_pnl": -0.01,
        }],
        "symbol_metrics": [{
            "fold": "outer_1", "symbol": "AG_IDX", "cost_bps": 5,
            "total_return": -0.01,
        }],
        "trades": [{
            "fold": "outer_1", "symbol": "AG_IDX", "cost_bps": 5,
            "decision_time": "2026-01-02T09:00:00",
            "entry_time": "2026-01-02T09:05:00",
            "exit_time": "2026-01-02T09:10:00", "sleeve_pnl": -0.01,
        }],
        "metrics": [{"optional_non_finite": np.nan}],
        "gates": official_gate_fixture(),
    })
    return result


def test_report_contains_domain_identity_and_aggregation_evidence(tmp_path):
    result = rejected_result_fixture()
    result["research_domain"] = research._research_domain(
        ResearchConfig(model_backend="qlib")
    )
    result["run_identity"] = {
        "id": "a" * 64,
        "evaluation_identity": "evaluation",
    }
    result["data_quality"] = [{
        "symbol": "AG_IDX", "status": "INCLUDED", "reason": "",
        "aggregated_15m_rows": 10, "partial_15m_windows": 2,
        "zero_volume_boundaries": 1, "price_jump_boundaries": 1,
        "time_gap_boundaries": 1,
    }]

    paths = research.write_report(result, tmp_path / "evidence")

    payload = json.loads(Path(paths["report.json"]).read_text())
    markdown = Path(paths["report.md"]).read_text()
    html = Path(paths["report.html"]).read_text()
    assert payload["research_domain"]["candidate_threshold_pairs"] == 6
    assert payload["run_identity"]["id"] == "a" * 64
    assert payload["data_quality"][0]["partial_15m_windows"] == 2
    assert "Research domain" in markdown
    assert "Run identity" in html


def test_report_artifacts_reconcile_and_preserve_rejection(tmp_path):
    result = rejected_result_fixture()

    paths = research.write_report(result, tmp_path)

    assert set(paths) == EXPECTED_REPORT_FILES
    payload = json.loads(
        (tmp_path / "report.json").read_text(encoding="utf-8"),
        parse_constant=lambda value: pytest.fail(f"non-standard JSON: {value}"),
    )
    assert payload["status"] == "RESEARCH_REJECTED"
    assert payload["run_id"] == result["run_id"]
    assert payload["metrics"][0]["optional_non_finite"] is None
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert markdown.startswith("# RESEARCH_REJECTED\n")
    assert "加权指数研究回测，不代表可成交合约或实盘收益" in markdown
    assert "positive_5bps_each_fold" in markdown
    assert "fixture gate rejection" in markdown
    for name in EXPECTED_REPORT_FILES - {"report.html", "report.md", "report.json"}:
        rows = pd.read_csv(tmp_path / name)
        assert set(rows["run_id"].astype(str)) <= {result["run_id"]}
        assert len(rows) == payload["row_counts"][name]
    trades = pd.read_csv(tmp_path / "trades.csv")
    assert len(trades) == len(result["trades"])
    assert trades.loc[0, "symbol"] == payload["trades"][0]["symbol"]
    assert pd.Timestamp(trades.loc[0, "decision_time"]).isoformat() == payload[
        "trades"
    ][0]["decision_time"]


def test_report_writer_is_atomic_and_refuses_existing_evidence(tmp_path):
    output = tmp_path / "evidence"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("original", encoding="utf-8")

    with pytest.raises(FileExistsError):
        research.write_report(rejected_result_fixture(), output)

    assert marker.read_text(encoding="utf-8") == "original"
    assert {path.name for path in output.iterdir()} == {"keep.txt"}


def test_report_writer_rejects_unreconciled_trade_summary_atomically(tmp_path):
    result = rejected_result_fixture()
    result["fold_metrics"][0]["trade_sleeve_pnl"] = 1.0
    output = tmp_path / "bad-report"

    with pytest.raises(ResearchRejected, match="trade summary mismatch"):
        research.write_report(result, output)

    assert not output.exists()
    assert not list(tmp_path.glob(".bad-report.*"))


@pytest.mark.parametrize(
    "case",
    [
        "accepted_with_failed_gate", "rejected_with_all_gates_passed",
        "missing_gate", "duplicate_gate", "extra_gate", "non_finite_gate",
    ],
)
def test_report_writer_rejects_contradictory_official_gate_bundle(
        tmp_path, case):
    result = rejected_result_fixture()
    if case == "accepted_with_failed_gate":
        result["status"] = "RESEARCH_ACCEPTED"
    elif case == "rejected_with_all_gates_passed":
        result["gates"] = official_gate_fixture(failed_id=None)
    elif case == "missing_gate":
        result["gates"].pop()
    elif case == "duplicate_gate":
        result["gates"][-1] = dict(result["gates"][0])
    elif case == "extra_gate":
        result["gates"].append({
            **result["gates"][0], "id": "not_a_gate",
        })
    else:
        result["gates"][0]["observed"] = np.inf
    output = tmp_path / "contradictory"

    with pytest.raises(RuntimeError, match="gate bundle"):
        research.write_report(result, output)

    assert not output.exists()
    assert not list(tmp_path.glob(".contradictory.*"))


def test_report_writer_rejects_precondition_gate_mixed_with_official_gates(tmp_path):
    result = research.rejected_result("precondition", ResearchConfig(), "reason")
    result["gates"].extend(official_gate_fixture())
    output = tmp_path / "mixed"

    with pytest.raises(RuntimeError, match="gate bundle"):
        research.write_report(result, output)

    assert not output.exists()


def test_report_writer_rejects_existing_ancestor_symlink(tmp_path):
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    symlink_parent = tmp_path / "linked"
    symlink_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        research.write_report(rejected_result_fixture(), symlink_parent / "report")

    assert not (real_parent / "report").exists()
    assert not list(real_parent.glob(".report.*"))


def test_report_csv_strings_are_spreadsheet_safe_without_changing_json(tmp_path):
    result = rejected_result_fixture()
    result["data_quality"] = [{
        "symbol": "=2+2", "status": "\n@status", "reason": "\t@formula",
    }]

    research.write_report(result, tmp_path)

    csv_row = pd.read_csv(
        tmp_path / "data_quality.csv", dtype=str, keep_default_na=False
    ).iloc[0]
    payload = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert csv_row["symbol"] == "'=2+2"
    assert csv_row["status"] == "'\n@status"
    assert csv_row["reason"] == "'\t@formula"
    assert payload["data_quality"][0]["symbol"] == "=2+2"
    assert payload["data_quality"][0]["status"] == "\n@status"
    assert payload["data_quality"][0]["reason"] == "\t@formula"


def test_run_research_consumes_only_official_adversarial_result(
        tmp_path, monkeypatch):
    db_path = tmp_path / "futures.db"
    _write_source(db_path, make_bars(56))
    dataset = pd.DataFrame([{
        "symbol": "AG_IDX", "decision_time": pd.Timestamp("2026-01-02 09:00"),
    }])
    partitions = {"eligible_symbols": ("AG_IDX",)}
    base = {
        "outer_results": [],
        "holdout": {
            "fold": "holdout",
            "evaluation_identity": {"id": "fixture"},
        },
        "final_candidate": Candidate("logistic_c0.1", 0.55),
        "final_inner_scores": pd.DataFrame(),
    }
    official = {
        "attacks": official_attack_fixture(),
        "gates": official_gate_fixture(),
        "status": "RESEARCH_REJECTED",
    }
    monkeypatch.setattr(research, "build_causal_dataset", lambda *_: dataset)
    monkeypatch.setattr(research, "make_temporal_partitions", lambda *_: partitions)
    monkeypatch.setattr(research, "build_base_evaluation", lambda *_: base)
    monkeypatch.setattr(
        research, "run_adversarial_checks", lambda *args, **kwargs: official
    )
    monkeypatch.setattr(
        research, "evaluate_acceptance_gates",
        lambda *_: pytest.fail("run_research bypassed the official result"),
    )
    monkeypatch.setattr(
        research, "research_status",
        lambda *_: pytest.fail("run_research recomputed official status"),
    )

    result = research.run_research(
        db_path, tmp_path / "report",
        ResearchConfig(min_symbol_rows=1, min_symbols=1, min_fold_rows=1),
    )

    assert result["status"] == "RESEARCH_REJECTED"
    assert result["gates"] == official["gates"]
    assert result["attacks"] == official["attacks"]
    provenance = result["provenance"]
    assert provenance["source_sha256"] == {"AG_IDX": "a" * 64}
    assert provenance["source_manifest"] == [{
        "symbol": "AG_IDX", "source_path": "source.txt",
        "source_sha256": "a" * 64,
    }]
    assert len(provenance["source_manifest_sha256"]) == 64
    assert provenance["database_path"] == str(db_path.resolve())
    assert provenance["cwd"] == str(Path.cwd().resolve())
    assert len(provenance["module_sha256"]) == 64
    assert provenance["module_sha256"] == hashlib.sha256(
        Path(research.__file__).read_bytes()
    ).hexdigest()
    assert len(provenance["git_head"]) == 40
    assert isinstance(provenance["git_dirty"], bool)
    assert isinstance(provenance["git_status"], list)
    command = shlex.split(provenance["command"])
    replayed_config = json.loads(command[command.index("--config-json") + 1])
    assert replayed_config == result["config"]
    assert replayed_config["min_symbols"] == 1
    assert replayed_config["min_symbol_rows"] == 1
    assert command[command.index("--db-path") + 1] == str(db_path.resolve())
    assert result["config"]["min_symbols"] == 1
    assert set(result["artifacts"]) == EXPECTED_REPORT_FILES
    report = json.loads((tmp_path / "report" / "report.json").read_text())
    failed = next(gate for gate in report["gates"] if not gate["passed"])
    assert failed["reason"] == "fixture gate rejection"


@pytest.mark.parametrize(
    "official",
    [
        {},
        {"attacks": official_attack_fixture(), "gates": official_gate_fixture(), "status": "INVALID"},
        {"attacks": official_attack_fixture(), "gates": {}, "status": "RESEARCH_REJECTED"},
    ],
    ids=["missing_keys", "invalid_status", "wrong_gate_type"],
)
def test_run_research_exposes_malformed_official_bundle_as_internal_error(
        tmp_path, monkeypatch, official):
    db_path = tmp_path / "futures.db"
    _write_source(db_path, make_bars(56))
    dataset = pd.DataFrame([{
        "symbol": "AG_IDX", "decision_time": pd.Timestamp("2026-01-02 09:00"),
    }])
    monkeypatch.setattr(research, "build_causal_dataset", lambda *_: dataset)
    monkeypatch.setattr(
        research, "make_temporal_partitions",
        lambda *_: {"eligible_symbols": ("AG_IDX",)},
    )
    monkeypatch.setattr(research, "build_base_evaluation", lambda *_: {
        "outer_results": [],
        "holdout": {
            "fold": "holdout",
            "evaluation_identity": {"id": "fixture"},
        },
        "final_candidate": Candidate("logistic_c0.1", 0.55),
        "final_inner_scores": pd.DataFrame(),
    })
    monkeypatch.setattr(
        research, "run_adversarial_checks", lambda *args, **kwargs: official
    )
    output = tmp_path / "must-not-exist"

    with pytest.raises((RuntimeError, TypeError), match="official adversarial"):
        research.run_research(
            db_path, output,
            ResearchConfig(min_symbol_rows=1, min_symbols=1, min_fold_rows=1),
        )

    assert not output.exists()
    assert not list(tmp_path.glob(".must-not-exist.*"))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda attacks: attacks.clear(),
        lambda attacks: attacks.pop(),
        lambda attacks: attacks.__setitem__(-1, dict(attacks[0])),
        lambda attacks: attacks.append({"id": "extra", "passed": True}),
    ],
    ids=["empty", "missing", "duplicate", "extra"],
)
def test_official_bundle_requires_exact_unique_attack_ids(mutate):
    bundle = {
        "attacks": official_attack_fixture(),
        "gates": official_gate_fixture(),
        "status": "RESEARCH_REJECTED",
    }
    mutate(bundle["attacks"])

    with pytest.raises(RuntimeError, match="official adversarial attacks"):
        research._validate_official_bundle(bundle)


@pytest.mark.parametrize(
    "evidence",
    [None, np.inf, np.array([1.0]), np.array([np.inf]), np.float64(1.0),
     {"nested": [1.0, {"bad": np.nan}]}, pd.Series([1.0])],
    ids=["null", "inf", "numpy_array", "numpy_array_inf", "numpy_scalar",
         "nested_nan", "pandas_series"],
)
def test_formal_gate_evidence_is_strict_native_finite_json(evidence):
    bundle = {
        "attacks": official_attack_fixture(),
        "gates": official_gate_fixture(),
        "status": "RESEARCH_REJECTED",
    }
    bundle["gates"][0]["observed"] = evidence

    with pytest.raises(RuntimeError, match="gate bundle"):
        research._validate_official_bundle(bundle)


@pytest.mark.parametrize("existing", [False, True], ids=["missing", "empty"])
def test_run_research_invalid_database_is_evidence_complete_rejection(
        tmp_path, existing):
    db_path = tmp_path / "invalid.db"
    if existing:
        db_path.touch()

    result = research.run_research(db_path, tmp_path / "rejected-report")

    assert result["status"] == "RESEARCH_REJECTED"
    assert result["gates"][0]["id"] == "RUN_PRECONDITION"
    assert "unable to load futures bars" in result["gates"][0]["reason"]
    assert set(result["artifacts"]) == EXPECTED_REPORT_FILES
    if not existing:
        assert not db_path.exists()


def test_invalid_config_still_writes_rejected_research_domain(tmp_path):
    result = research.run_research(
        tmp_path / "missing.db",
        tmp_path / "invalid-config-report",
        ResearchConfig(
            model_backend="invalid",
            horizon="bad",
            embargo_bars="bad",
            thresholds=("bad",),
        ),
    )

    assert result["status"] == "RESEARCH_REJECTED"
    assert result["research_domain"]["selectable_models"] == []
    assert result["research_domain"]["thresholds"] == []
    assert result["research_domain"]["candidate_threshold_pairs"] == 0
    assert Path(result["artifacts"]["report.json"]).is_file()


def test_run_research_rejects_impossible_segments_before_causal_build(
        tmp_path, monkeypatch):
    bars = make_bars(5_500)
    bars["trade_time"] = pd.DatetimeIndex(np.concatenate([
        pd.date_range(day + pd.Timedelta(hours=9), periods=55, freq="5min")
        for day in pd.date_range("2025-01-02", periods=100, freq="D")
    ]))
    db_path = tmp_path / "short-segments.db"
    _write_source(db_path, bars)
    monkeypatch.setattr(
        research, "build_causal_dataset",
        lambda *_: pytest.fail("impossible segments reached causal build"),
    )

    result = research.run_research(
        db_path, tmp_path / "rejected-report",
        ResearchConfig(min_symbol_rows=1, min_symbols=1, min_fold_rows=1),
    )

    assert result["status"] == "RESEARCH_REJECTED"
    reason = result["gates"][0]["reason"]
    assert "required_bars=56" in reason
    assert "eligible_symbols=0/1" in reason
    assert 'observed={"AG_IDX": 0}' in reason
    assert len(result["data_quality"]) == 1
    quality = result["data_quality"][0]
    assert quality["symbol"] == "AG_IDX"
    assert quality["status"] == "INCLUDED"
    assert quality["segment_count"] == 100
    assert quality["zero_volume_fraction"] == 0.0
    assert quality["reason"] == ""
    report = json.loads(
        (tmp_path / "rejected-report" / "report.json").read_text()
    )
    assert report["data_quality"] == [{"run_id": result["run_id"], **quality}]
    csv_quality = pd.read_csv(tmp_path / "rejected-report" / "data_quality.csv")
    assert csv_quality.loc[0, "symbol"] == "AG_IDX"
    assert "AG_IDX: INCLUDED" in (
        tmp_path / "rejected-report" / "report.md"
    ).read_text()


def test_report_cli_returns_two_for_a_complete_rejection(tmp_path, monkeypatch, capsys):
    result = rejected_result_fixture()
    result["artifacts"] = {name: str(tmp_path / name) for name in EXPECTED_REPORT_FILES}
    captured = {}

    def fake_run(db_path, output_dir, config):
        captured.update({
            "db_path": db_path, "output_dir": output_dir, "config": config,
        })
        return result

    monkeypatch.setattr(research, "run_research", fake_run)

    exit_code = research.main([
        "--db-path", str(tmp_path / "source.db"),
        "--output-dir", str(tmp_path / "report"),
        "--config-json", '{"min_symbols": 3, "min_symbol_rows": 17}',
    ])

    assert exit_code == 2
    assert json.loads(capsys.readouterr().out)["status"] == "RESEARCH_REJECTED"
    assert captured["config"].min_symbols == 3
    assert captured["config"].min_symbol_rows == 17


def test_report_cli_returns_one_for_internal_contract_error(
        tmp_path, monkeypatch, capsys):
    def broken_run(*_args, **_kwargs):
        raise RuntimeError("official adversarial result has invalid fields")

    monkeypatch.setattr(research, "run_research", broken_run)

    exit_code = research.main([
        "--db-path", str(tmp_path / "source.db"),
        "--output-dir", str(tmp_path / "report"),
    ])

    assert exit_code == 1
    assert "official adversarial" in capsys.readouterr().err
    assert not (tmp_path / "report").exists()
