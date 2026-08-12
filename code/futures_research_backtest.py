from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


FEATURE_COLUMNS = (
    "ret_1", "ret_3", "ret_6", "ret_12", "vol_12", "vol_48",
    "range_pct", "body_pct", "close_pos", "ema_gap_12_48", "volume_z48",
)
SERIES_TYPES = ("WEIGHTED_INDEX", "MONTHLY_AVERAGE_WEIGHTED_INDEX")
BAR_COLUMNS = (
    "symbol", "timeframe", "trade_time", "open", "high", "low", "close",
    "volume", "amount", "open_interest", "settlement", "series_type",
)


@dataclass(frozen=True)
class ResearchConfig:
    horizon: int = 6
    discontinuity: float = 0.03
    max_zero_volume_fraction: float = 0.50
    min_symbol_rows: int = 1000
    min_fold_rows: int = 200
    min_symbols: int = 20
    holdout_fraction: float = 0.20
    embargo_bars: int = 6
    thresholds: tuple = (0.52, 0.55, 0.58)
    costs_bps: tuple = (0, 2, 5, 10, 20)
    seed: int = 42


class ResearchRejected(ValueError):
    pass


@dataclass(frozen=True)
class TemporalFold:
    name: str
    train_times: pd.DatetimeIndex
    evaluation_times: pd.DatetimeIndex


def _parse_trade_time(values: pd.Series) -> pd.Series:
    def is_timezone_aware(value):
        try:
            return pd.Timestamp(value).tzinfo is not None
        except (TypeError, ValueError, OverflowError):
            return False

    if values.dropna().map(is_timezone_aware).any():
        raise ResearchRejected("timezone-aware futures timestamps are unsupported")
    try:
        parsed = pd.to_datetime(values, errors="raise")
    except (TypeError, ValueError) as exc:
        raise ResearchRejected("unparseable futures timestamp") from exc
    if parsed.isna().any():
        raise ResearchRejected("null futures timestamp")
    return parsed


def load_futures_bars(db_path, timeframe="5m") -> pd.DataFrame:
    """Load only provenance-approved futures index bars from SQLite."""
    try:
        with sqlite3.connect(Path(db_path)) as conn:
            bars = pd.read_sql_query(
                "SELECT symbol, timeframe FROM futures_min_bars WHERE timeframe=? "
                "GROUP BY symbol, timeframe",
                conn,
                params=(timeframe,),
            )
            metadata = pd.read_sql_query(
                "SELECT symbol, timeframe, series_type FROM futures_series_metadata "
                "WHERE timeframe=?",
                conn,
                params=(timeframe,),
            )
            frame = pd.read_sql_query(
                "SELECT b.symbol, b.timeframe, b.trade_time, b.open, b.high, b.low, "
                "b.close, b.volume, b.amount, b.open_interest, b.settlement, m.series_type "
                "FROM futures_min_bars AS b JOIN futures_series_metadata AS m "
                "ON m.symbol=b.symbol AND m.timeframe=b.timeframe "
                "WHERE b.timeframe=? ORDER BY b.symbol, b.trade_time",
                conn,
                params=(timeframe,),
            )
    except (sqlite3.Error, ValueError) as exc:
        raise ResearchRejected(f"unable to load futures bars: {exc}") from exc

    counts = metadata.groupby(["symbol", "timeframe"]).size()
    for pair in bars.itertuples(index=False):
        if counts.get((pair.symbol, pair.timeframe), 0) != 1:
            raise ResearchRejected(f"expected exactly one metadata row for {pair.symbol}")
    if frame.empty:
        raise ResearchRejected("no approved futures bars")
    if not frame["series_type"].isin(SERIES_TYPES).all():
        raise ResearchRejected("unsupported futures series type")
    frame["trade_time"] = _parse_trade_time(frame["trade_time"])
    return frame.loc[:, BAR_COLUMNS]


def _reject_if_invalid(bars: pd.DataFrame) -> pd.DataFrame:
    required = {"symbol", "trade_time", "open", "high", "low", "close", "volume"}
    missing = required.difference(bars.columns)
    if missing:
        raise ResearchRejected(f"missing required columns: {', '.join(sorted(missing))}")
    if bars.empty:
        raise ResearchRejected("no futures bars")
    frame = bars.copy()
    frame["trade_time"] = _parse_trade_time(frame["trade_time"])
    if frame["symbol"].isna().any():
        raise ResearchRejected("null symbol or timestamp")
    if (
        frame["trade_time"].dt.minute.mod(5).ne(0).any()
        or frame["trade_time"].dt.second.ne(0).any()
        or frame["trade_time"].dt.microsecond.ne(0).any()
    ):
        raise ResearchRejected("timestamps must align to five minutes")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if not np.isfinite(frame[column]).all():
            raise ResearchRejected(f"non-finite {column}")
    for column in ("amount", "open_interest", "settlement"):
        if column in frame:
            present = frame[column].notna()
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
            if frame.loc[present, column].isna().any() or not np.isfinite(
                frame.loc[present, column]
            ).all():
                raise ResearchRejected(f"non-finite {column}")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise ResearchRejected("prices must be positive")
    if (frame["volume"] < 0).any() or (
        "open_interest" in frame and (frame["open_interest"].dropna() < 0).any()
    ):
        raise ResearchRejected("negative volume or open interest")
    if (
        frame["high"].lt(frame[["open", "low", "close"]].max(axis=1)).any()
        or frame["low"].gt(frame[["open", "high", "close"]].min(axis=1)).any()
    ):
        raise ResearchRejected("invalid OHLC")
    for _, group in frame.groupby("symbol", sort=False):
        times = group["trade_time"]
        if times.duplicated().any():
            raise ResearchRejected("duplicate timestamp")
        if times.diff().lt(pd.Timedelta(0)).any():
            raise ResearchRejected("out-of-order timestamp")
    return frame.sort_values(["symbol", "trade_time"], kind="stable").reset_index(drop=True)


def validate_and_segment(bars: pd.DataFrame, config=ResearchConfig()) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = _reject_if_invalid(bars)
    clean_groups = []
    quality_rows = []
    for symbol, group in frame.groupby("symbol", sort=False):
        group = group.copy()
        zero = group["volume"].eq(0)
        gap = group["trade_time"].diff().ne(pd.Timedelta(minutes=5))
        zero_neighbor = zero | zero.shift(fill_value=False)
        open_gap = group["open"].div(group["close"].shift()).sub(1).abs().gt(
            config.discontinuity
        )
        close_jump = group["close"].pct_change().abs().gt(config.discontinuity)
        boundary = gap | zero_neighbor | open_gap | close_jump
        boundary.iloc[0] = True
        group["segment_id"] = group["symbol"] + ":" + boundary.cumsum().astype(str)
        zero_fraction = float(zero.mean())
        excluded = zero_fraction > config.max_zero_volume_fraction
        quality_rows.append({
            "symbol": symbol,
            "raw_rows": len(group),
            "start_time": group["trade_time"].min(),
            "end_time": group["trade_time"].max(),
            "zero_volume_fraction": zero_fraction,
            "segment_count": int(group["segment_id"].nunique()),
            "status": "EXCLUDED" if excluded else "INCLUDED",
            "reason": "ZERO_VOLUME_FRACTION" if excluded else "",
        })
        if not excluded:
            clean_groups.append(group)
    clean = pd.concat(clean_groups, ignore_index=True) if clean_groups else frame.iloc[0:0].assign(segment_id=pd.Series(dtype=str))
    quality = pd.DataFrame(quality_rows).set_index("symbol")
    return clean, quality


def assert_feature_columns(matrix):
    observed = tuple(matrix.columns)
    if observed != FEATURE_COLUMNS:
        raise ResearchRejected(
            f"feature whitelist mismatch: expected={FEATURE_COLUMNS}, observed={observed}"
        )


def _segment_features(group):
    close = group["close"].astype(float)
    volume = group["volume"].astype(float)
    feature = pd.DataFrame(index=group.index)
    for horizon in (1, 3, 6, 12):
        feature[f"ret_{horizon}"] = close.pct_change(horizon)
    feature["vol_12"] = close.pct_change().rolling(12).std()
    feature["vol_48"] = close.pct_change().rolling(48).std()
    feature["range_pct"] = (group["high"] - group["low"]) / close
    feature["body_pct"] = (group["close"] - group["open"]) / close
    span = (group["high"] - group["low"]).replace(0.0, np.nan)
    feature["close_pos"] = (group["close"] - group["low"]) / span
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema48 = close.ewm(span=48, adjust=False).mean()
    feature["ema_gap_12_48"] = (ema12 - ema48) / ema48
    prior_mean = volume.shift(1).rolling(48).mean()
    prior_std = volume.shift(1).rolling(48).std().replace(0.0, np.nan)
    feature["volume_z48"] = (volume - prior_mean) / prior_std
    return feature.loc[:, FEATURE_COLUMNS]


def build_causal_dataset(segmented, config=ResearchConfig()) -> pd.DataFrame:
    required = {"symbol", "segment_id", "trade_time", "open", "high", "low", "close", "volume"}
    missing = required.difference(segmented.columns)
    if missing:
        raise ResearchRejected(f"missing segmented columns: {', '.join(sorted(missing))}")
    rows = []
    for _, group in segmented.groupby(["symbol", "segment_id"], sort=False):
        group = group.sort_values("trade_time", kind="stable").copy()
        features = _segment_features(group)
        assert_feature_columns(features)
        entry_time = group["trade_time"].shift(-1)
        entry_open = group["open"].shift(-1)
        exit_time = group["trade_time"].shift(-(config.horizon + 1))
        exit_open = group["open"].shift(-(config.horizon + 1))
        same_segment = (
            group["segment_id"].eq(group["segment_id"].shift(-1))
            & group["segment_id"].eq(group["segment_id"].shift(-(config.horizon + 1)))
        )
        frame = pd.DataFrame({
            "symbol": group["symbol"],
            "segment_id": group["segment_id"],
            "decision_time": group["trade_time"],
            "entry_time": entry_time,
            "entry_open": entry_open,
            "exit_time": exit_time,
            "exit_open": exit_open,
            "label_end_time": exit_time,
        }, index=group.index).join(features)
        frame["future_return"] = frame["exit_open"] / frame["entry_open"] - 1.0
        finite = np.isfinite(frame.loc[:, FEATURE_COLUMNS]).all(axis=1)
        valid = same_segment & frame[["entry_time", "entry_open", "exit_time", "exit_open"]].notna().all(axis=1) & finite
        frame = frame.loc[valid].copy()
        frame["label"] = (frame["future_return"] > 0.0).astype(int)
        rows.append(frame)
    columns = (
        "symbol", "segment_id", "decision_time", *FEATURE_COLUMNS,
        "entry_time", "entry_open", "exit_time", "exit_open", "label_end_time",
        "future_return", "label",
    )
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.concat(rows).loc[:, columns].sort_values(["decision_time", "symbol"], kind="stable").reset_index(drop=True)


def _contiguous_windows(times, count):
    return [pd.DatetimeIndex(part) for part in np.array_split(times, count)]


def purged_training_rows(dataset, train_times, evaluation_start, embargo_bars):
    if embargo_bars < 0:
        raise ResearchRejected("embargo bars must be non-negative")
    train = dataset[
        dataset["decision_time"].isin(train_times)
        & (dataset["label_end_time"] < evaluation_start)
    ].copy()
    keep = pd.Series(True, index=train.index)
    for _, group in train.groupby("symbol", sort=False):
        keep.loc[group.sort_values("decision_time").tail(embargo_bars).index] = False
    return train.loc[keep]


def _inner_folds(times, prefix):
    initial = int(np.floor(0.5 * len(times)))
    windows = _contiguous_windows(times[initial:], 2)
    if initial == 0 or any(window.empty for window in windows):
        raise ResearchRejected("empty inner temporal window")
    return [
        TemporalFold(f"{prefix}_inner_{number}", times[:initial + sum(len(window) for window in windows[:number - 1])], window)
        for number, window in enumerate(windows, start=1)
    ]


def make_temporal_partitions(dataset, config=ResearchConfig()):
    if dataset.empty:
        raise ResearchRejected("no causal dataset rows")
    times = pd.DatetimeIndex(pd.to_datetime(dataset["decision_time"].unique())).sort_values()
    split = int(np.floor((1.0 - config.holdout_fraction) * len(times)))
    development, holdout_times = times[:split], times[split:]
    if development.empty or holdout_times.empty or holdout_times.normalize().nunique() < 30:
        raise ResearchRejected("holdout requires at least 30 distinct dates")
    initial = int(np.floor(0.4 * len(development)))
    windows = _contiguous_windows(development[initial:], 3)
    if initial == 0 or len(windows) < 3 or any(window.empty for window in windows):
        raise ResearchRejected("fewer than three non-empty outer folds")
    outer_folds = [
        TemporalFold(f"outer_{number}", development[:initial + sum(len(window) for window in windows[:number - 1])], window)
        for number, window in enumerate(windows, start=1)
    ]
    evaluation_windows = [fold.evaluation_times for fold in outer_folds] + [holdout_times]
    eligible = set(dataset["symbol"].dropna().unique())
    for window in evaluation_windows:
        counts = dataset.loc[dataset["decision_time"].isin(window), "symbol"].value_counts()
        eligible &= set(counts[counts >= config.min_fold_rows].index)
    if len(eligible) < config.min_symbols:
        raise ResearchRejected("too few fold-eligible symbols")
    return {
        "outer_folds": outer_folds,
        "inner_by_outer": {fold.name: _inner_folds(fold.train_times, fold.name) for fold in outer_folds},
        "development_inner_folds": _inner_folds(development, "development"),
        "holdout_fold": TemporalFold("holdout", development, holdout_times),
        "eligible_symbols": tuple(sorted(eligible)),
    }
