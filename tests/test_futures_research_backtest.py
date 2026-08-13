import sqlite3

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


def _write_source(db_path, bars, series_type="WEIGHTED_INDEX", metadata=True):
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
                    "'gb18030', 'hash', 1, '2026-01-02 09:00:00', '2026-01-02 09:00:00', 'now')",
                    (symbol, series_type),
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

    def tracked_bootstrap(returns, supplied_config=ResearchConfig()):
        nonlocal bootstrap_calls
        assert len(selection_calls) == 4
        assert active_parent is None
        bootstrap_calls += 1
        return real_bootstrap(returns, supplied_config)

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
    assert bootstrap_calls == 1
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
    candidate = Candidate("logistic_c0.1", 0.55)
    fold_result = {"model_identity": "model-a", "model_parameters": {"C": 0.1}}
    config = ResearchConfig()

    baseline = research._evaluation_identity(
        candidate, fold_result, evaluation, config
    )
    identities = {baseline["id"]}
    identities.add(research._evaluation_identity(
        Candidate("logistic_c1.0", candidate.threshold),
        fold_result,
        evaluation,
        config,
    )["id"])
    identities.add(research._evaluation_identity(
        Candidate(candidate.model_name, 0.58), fold_result, evaluation, config
    )["id"])
    identities.add(research._evaluation_identity(
        candidate,
        {"model_identity": "model-a", "model_parameters": {"C": 1.0}},
        evaluation,
        config,
    )["id"])
    identities.add(research._evaluation_identity(
        candidate,
        {"model_identity": "model-b", "model_parameters": {"C": 0.1}},
        evaluation,
        config,
    )["id"])
    changed_domain = evaluation.iloc[:-1].copy()
    identities.add(research._evaluation_identity(
        candidate, fold_result, changed_domain, config
    )["id"])
    identities.add(research._evaluation_identity(
        candidate, fold_result, evaluation, ResearchConfig(costs_bps=(0, 5, 15))
    )["id"])
    identities.add(research._evaluation_identity(
        candidate, fold_result, evaluation, ResearchConfig(seed=43)
    )["id"])

    assert baseline["scope"] == "single_build_base_evaluation"
    assert baseline["evaluation_rows"] == len(evaluation)
    assert len(baseline["evaluation_times"]) == evaluation["decision_time"].nunique()
    assert len(identities) == 8


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
