import sqlite3

import numpy as np
import pandas as pd
import pytest

from futures_research_backtest import (
    ResearchConfig,
    ResearchRejected,
    load_futures_bars,
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


def test_mixed_timezone_timestamps_are_normalized():
    bars = make_bars(3)
    bars["trade_time"] = bars["trade_time"].astype(object)
    bars.loc[1, "trade_time"] = pd.Timestamp("2026-01-02 09:05:00+00:00")

    clean, _ = validate_and_segment(bars, ResearchConfig(min_symbol_rows=1, min_fold_rows=1))

    assert pd.api.types.is_datetime64_dtype(clean["trade_time"])


def test_empty_structurally_correct_bars_fail_closed():
    bars = make_bars(0)

    with pytest.raises(ResearchRejected, match="no futures bars"):
        validate_and_segment(bars)


def test_non_null_optional_source_values_must_be_finite():
    bars = make_bars(3)
    bars["settlement"] = [100.0, "not-a-number", 102.0]

    with pytest.raises(ResearchRejected):
        validate_and_segment(bars, ResearchConfig(min_symbol_rows=1, min_fold_rows=1))


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
