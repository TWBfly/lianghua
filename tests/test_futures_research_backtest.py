import sqlite3

import numpy as np
import pandas as pd
import pytest

from futures_research_backtest import (
    FEATURE_COLUMNS,
    ResearchConfig,
    ResearchRejected,
    assert_feature_columns,
    build_causal_dataset,
    load_futures_bars,
    make_temporal_partitions,
    purged_training_rows,
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
