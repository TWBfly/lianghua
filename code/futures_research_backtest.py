from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass, is_dataclass
from numbers import Real
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


FEATURE_COLUMNS = (
    "ret_1", "ret_3", "ret_6", "ret_12", "vol_12", "vol_48",
    "range_pct", "body_pct", "close_pos", "ema_gap_12_48", "volume_z48",
)
ATTACK_EVIDENCE = {
    "prefix_invariance": ("prefix", FEATURE_COLUMNS),
    "feature_whitelist": ("whitelist", FEATURE_COLUMNS),
    "label_shuffle": ("label_shuffle", FEATURE_COLUMNS),
    "noise_features": ("noise", tuple(f"noise_{number}" for number in range(1, 6))),
    "calendar_features": (
        "calendar",
        (
            "time_of_day_sin", "time_of_day_cos",
            "day_of_week_sin", "day_of_week_cos",
        ),
    ),
}
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
    costs_bps: tuple = (0, 2, 5, 10, 15, 20)
    seed: int = 42


class ResearchRejected(ValueError):
    pass


@dataclass(frozen=True)
class Candidate:
    model_name: str
    threshold: float


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
    db_path = Path(db_path)
    if not db_path.is_file():
        raise ResearchRejected(f"unable to load futures bars: missing database {db_path}")
    try:
        with sqlite3.connect(db_path) as conn:
            bars = pd.read_sql_query(
                "SELECT symbol, timeframe FROM futures_min_bars WHERE timeframe=? "
                "GROUP BY symbol, timeframe",
                conn,
                params=(timeframe,),
            )
            metadata = pd.read_sql_query(
                "SELECT symbol, timeframe, series_type, source_file, source_sha256 "
                "FROM futures_series_metadata "
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
    except (sqlite3.Error, pd.errors.DatabaseError, ValueError) as exc:
        raise ResearchRejected(f"unable to load futures bars: {exc}") from exc

    counts = metadata.groupby(["symbol", "timeframe"]).size()
    for pair in bars.itertuples(index=False):
        if counts.get((pair.symbol, pair.timeframe), 0) != 1:
            raise ResearchRejected(f"expected exactly one metadata row for {pair.symbol}")
    if frame.empty:
        raise ResearchRejected("no approved futures bars")
    if not frame["series_type"].isin(SERIES_TYPES).all():
        raise ResearchRejected("unsupported futures series type")
    if not metadata["source_sha256"].map(_is_sha256).all():
        raise ResearchRejected("source SHA256 must be canonical lowercase hex")
    frame["trade_time"] = _parse_trade_time(frame["trade_time"])
    result = frame.loc[:, BAR_COLUMNS]
    result.attrs["source_sha256"] = dict(sorted(zip(
        metadata["symbol"].astype(str), metadata["source_sha256"].astype(str)
    )))
    result.attrs["source_manifest"] = _source_manifest(
        metadata.loc[:, ["symbol", "source_file", "source_sha256"]]
        .rename(columns={"source_file": "source_path"})
        .to_dict("records")
    )[0]
    return result


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


def candidate_names():
    return ("logistic_c0.1", "logistic_c1.0", "lightgbm_constrained")


def inverse_symbol_class_weights(frame):
    complete = frame.groupby("symbol", dropna=False)["label"].agg(
        lambda labels: set(labels) == {0, 1}
    )
    if frame.empty or not complete.all():
        raise ResearchRejected("each symbol must contain both classes")
    cell_count = frame.groupby(
        ["symbol", "label"], dropna=False
    )["label"].transform("size")
    weights = 1.0 / cell_count.astype(float)
    return weights / weights.mean()


def _fit_matrix(candidate, x_train, y_train, sample_weight, x_evaluation, config):
    if candidate.model_name not in candidate_names():
        raise ResearchRejected(f"unknown model candidate: {candidate.model_name}")
    arrays = (x_train, y_train, sample_weight, x_evaluation)
    if any(not np.isfinite(np.asarray(array, dtype=float)).all() for array in arrays):
        raise ResearchRejected("model inputs must be finite")
    if candidate.model_name.startswith("logistic_c"):
        c_value = float(candidate.model_name.removeprefix("logistic_c"))
        model = make_pipeline(
            StandardScaler(),
            LogisticRegression(
                C=c_value, penalty="l2", solver="liblinear",
                max_iter=1000, random_state=config.seed,
            ),
        )
        model.fit(
            x_train, y_train,
            logisticregression__sample_weight=sample_weight,
        )
    else:
        model = LGBMClassifier(
            n_estimators=100, learning_rate=0.03, max_depth=3,
            num_leaves=7, min_child_samples=200, subsample=0.8,
            colsample_bytree=0.8, subsample_freq=1, reg_alpha=1.0,
            reg_lambda=5.0, objective="binary", verbosity=-1,
            n_jobs=1, random_state=config.seed,
        )
        model.fit(x_train, y_train, sample_weight=sample_weight)
    probability = model.predict_proba(x_evaluation)[:, 1]
    if not np.isfinite(probability).all() or ((probability < 0.0) | (probability > 1.0)).any():
        raise ResearchRejected("model probabilities must be finite and in [0, 1]")
    return probability, model


def fit_predict(candidate, train, evaluation, config=ResearchConfig()):
    if not isinstance(train, pd.DataFrame) or not isinstance(evaluation, pd.DataFrame):
        raise ResearchRejected("train and evaluation must be data frames")
    required = {"symbol", "label", *FEATURE_COLUMNS}
    if required.difference(train.columns) or required.difference(evaluation.columns):
        raise ResearchRejected("model frame is missing required columns")
    if train.empty or evaluation.empty:
        raise ResearchRejected("model frames must not be empty")
    x_train = train.loc[:, FEATURE_COLUMNS]
    x_evaluation = evaluation.loc[:, FEATURE_COLUMNS]
    assert_feature_columns(x_train)
    assert_feature_columns(x_evaluation)
    y_train = pd.to_numeric(train["label"], errors="coerce")
    y_evaluation = pd.to_numeric(evaluation["label"], errors="coerce")
    if set(y_train.unique()) != {0, 1} or set(y_evaluation.unique()) != {0, 1}:
        raise ResearchRejected("train and evaluation must each contain both classes")
    sample_weight = inverse_symbol_class_weights(train)
    return _fit_matrix(
        candidate, x_train, y_train, sample_weight, x_evaluation, config
    )


def _probability_metrics(labels, probability, threshold):
    return predictive_metrics(labels, probability, threshold)


def choose_from_scores(scores):
    required = {"model_name", "threshold", "fold", "return_5bps", "turnover"}
    if (
        not isinstance(scores, pd.DataFrame)
        or scores.empty
        or not scores.columns.is_unique
        or required.difference(scores.columns)
    ):
        raise ResearchRejected("invalid candidate score frame")
    if (
        not scores["model_name"].map(lambda value: isinstance(value, str)).all()
        or not scores["model_name"].isin(candidate_names()).all()
        or not scores["fold"].map(
            lambda value: isinstance(value, str) and bool(value)
        ).all()
        or scores["fold"].nunique() != 2
        or not scores["threshold"].map(
            lambda value: _finite_number(value)
            and float(value) in (0.52, 0.55, 0.58)
        ).all()
        or not scores["return_5bps"].map(_finite_number).all()
        or not scores["turnover"].map(_finite_number).all()
        or (scores["turnover"] < 0.0).any()
    ):
        raise ResearchRejected("invalid candidate score frame")
    grouped = []
    for (model_name, threshold), rows in scores.groupby(
        ["model_name", "threshold"], sort=False
    ):
        if (
            len(rows) != 2
            or rows["fold"].nunique(dropna=False) != 2
        ):
            raise ResearchRejected("invalid candidate score frame")
        if not (rows["return_5bps"] > 0).all():
            continue
        grouped.append({
            "candidate": Candidate(str(model_name), float(threshold)),
            "median_return": float(rows["return_5bps"].median()),
            "turnover": float(rows["turnover"].mean()),
        })
    if not grouped:
        raise ResearchRejected("no candidate passed both inner folds")
    best_return = max(row["median_return"] for row in grouped)
    near = [
        row for row in grouped
        if best_return - row["median_return"] <= 0.001
    ]
    near.sort(key=lambda row: (
        row["turnover"],
        row["candidate"].model_name == "lightgbm_constrained",
        -row["candidate"].threshold,
        candidate_names().index(row["candidate"].model_name),
    ))
    return near[0]["candidate"]


def select_candidate(dataset, market, folds, config=ResearchConfig()):
    folds = tuple(folds)
    try:
        distinct_names = len({fold.name for fold in folds}) == 2
        evaluation_windows = tuple(
            pd.DatetimeIndex(fold.evaluation_times) for fold in folds
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ResearchRejected("invalid inner evaluation windows") from exc
    if len(folds) != 2 or not distinct_names:
        raise ResearchRejected("selection requires two distinct inner folds")
    if (
        any(
            window.empty
            or window.has_duplicates
            or not window.is_monotonic_increasing
            for window in evaluation_windows
        )
        or not evaluation_windows[0].intersection(evaluation_windows[1]).empty
    ):
        raise ResearchRejected("invalid inner evaluation windows")
    folds = tuple(
        TemporalFold(fold.name, fold.train_times, window)
        for fold, window in zip(folds, evaluation_windows)
    )
    thresholds = tuple(config.thresholds)
    allowed_thresholds = (0.52, 0.55, 0.58)
    if (
        not thresholds
        or any(not _finite_number(value) for value in thresholds)
        or any(float(value) not in allowed_thresholds for value in thresholds)
        or len(set(thresholds)) != len(thresholds)
    ):
        raise ResearchRejected("candidate thresholds must be a unique fixed subset")
    score_rows = []
    selectable_rows = []
    selection_times = pd.DatetimeIndex([])
    for fold in folds:
        selection_times = selection_times.union(fold.train_times).union(
            fold.evaluation_times
        )
    symbol_count = int(dataset.loc[
        dataset["decision_time"].isin(selection_times), "symbol"
    ].nunique())
    if symbol_count < 1:
        raise ResearchRejected("model dataset has no symbols")
    for fold in folds:
        if fold.evaluation_times.empty:
            raise ResearchRejected("empty inner evaluation window")
        train = purged_training_rows(
            dataset, fold.train_times, fold.evaluation_times[0], config.embargo_bars
        )
        evaluation = dataset[
            dataset["decision_time"].isin(fold.evaluation_times)
        ].copy()
        evaluation_pairs = pd.MultiIndex.from_frame(
            evaluation.loc[:, ["symbol", "segment_id"]].drop_duplicates()
        )
        market_pairs = pd.MultiIndex.from_frame(
            market.loc[:, ["symbol", "segment_id"]]
        )
        fold_market = market.loc[
            market_pairs.isin(evaluation_pairs)
            & market["trade_time"].between(
                evaluation["decision_time"].min(), evaluation["exit_time"].max()
            )
        ]
        for model_name in candidate_names():
            probability, _ = fit_predict(
                Candidate(model_name, float(thresholds[0])), train, evaluation, config
            )
            for threshold in thresholds:
                threshold = float(threshold)
                scored = evaluation.copy()
                scored["probability"] = probability
                trades, daily = simulate_standardized_ledger(
                    scored, fold_market, threshold, 5, symbol_count
                )
                strategy = strategy_metrics(trades, daily)
                row = {
                    "model_name": model_name,
                    "threshold": threshold,
                    "fold": fold.name,
                    "train_rows": len(train),
                    "evaluation_rows": len(evaluation),
                    **_probability_metrics(evaluation["label"], probability, threshold),
                    "return_5bps": strategy["total_return"],
                    "turnover": strategy["turnover"],
                }
                score_rows.append(row)
                selectable_rows.append(row)

        x_train = train.loc[:, FEATURE_COLUMNS]
        x_evaluation = evaluation.loc[:, FEATURE_COLUMNS]
        dummy = DummyClassifier(strategy="prior", random_state=config.seed)
        dummy.fit(
            x_train, train["label"],
            sample_weight=inverse_symbol_class_weights(train),
        )
        dummy_probability = dummy.predict_proba(x_evaluation)[:, 1]
        if not np.isfinite(dummy_probability).all():
            raise ResearchRejected("dummy probabilities must be finite")
        score_rows.append({
            "model_name": "dummy_prior",
            "threshold": np.nan,
            "fold": fold.name,
            "train_rows": len(train),
            "evaluation_rows": len(evaluation),
            **_probability_metrics(evaluation["label"], dummy_probability, 0.5),
            "return_5bps": np.nan,
            "turnover": np.nan,
        })
    return choose_from_scores(pd.DataFrame(selectable_rows)), pd.DataFrame(score_rows)


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
    horizon = config.horizon
    if (
        isinstance(horizon, (bool, np.bool_))
        or not isinstance(horizon, (int, np.integer))
        or horizon < 1
    ):
        raise ResearchRejected("horizon must be an integer greater than or equal to one")
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
    train = dataset[dataset["decision_time"].isin(train_times)].copy()
    train = train[train["label_end_time"] < evaluation_start].copy()
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


def _direction(probability, threshold):
    if probability >= threshold:
        return 1
    if probability <= 1.0 - threshold:
        return -1
    return 0


def _net_sleeve_return(direction, entry_open, exit_open, cost_bps):
    ratio = float(exit_open) / float(entry_open)
    cost = float(cost_bps) / 10_000.0
    gross = int(direction) * (ratio - 1.0)
    return gross, cost, cost * ratio, gross - cost * (1.0 + ratio)


def _finite_number(value):
    return isinstance(value, Real) and not isinstance(value, (bool, np.bool_)) and np.isfinite(value)


def _segment_arrays(group):
    group = group.sort_values("trade_time", kind="stable")
    times = group["trade_time"].to_numpy(dtype="datetime64[ns]").view(np.int64)
    positions = {int(timestamp): position for position, timestamp in enumerate(times)}
    gap_prefix = np.r_[
        0,
        np.cumsum(np.diff(times) != pd.Timedelta(minutes=5).value),
    ]
    return (
        times,
        group["open"].to_numpy(dtype=float),
        group["close"].to_numpy(dtype=float),
        positions,
        gap_prefix,
    )


def simulate_standardized_ledger(scored, market, threshold, cost_bps, symbol_count):
    """Build the fixed-sleeve, next-open, bar-marked research ledger."""
    trade_columns = (
        "symbol", "segment_id", "decision_time", "entry_time", "exit_time", "direction",
        "entry_open", "exit_open", "gross_return", "entry_cost", "exit_cost",
        "net_sleeve_return", "portfolio_return", "threshold", "cost_bps", "exit_reason",
        "sleeve_start_equity", "sleeve_end_equity", "sleeve_pnl", "turnover",
    )
    daily_columns = (
        "date", "equity", "pnl", "portfolio_return", "gross_exposure", "turnover",
        "unused_cash", "sleeve_equity",
    )
    if not _finite_number(threshold) or not 0.5 < float(threshold) < 1.0:
        raise ResearchRejected("threshold must be between 0.5 and 1.0")
    if not _finite_number(cost_bps) or float(cost_bps) < 0.0:
        raise ResearchRejected("cost_bps must be finite and non-negative")
    if (
        isinstance(symbol_count, (bool, np.bool_))
        or not isinstance(symbol_count, (int, np.integer))
        or symbol_count < 1
    ):
        raise ResearchRejected("symbol_count must be a positive integer")

    if not isinstance(scored, pd.DataFrame) or not isinstance(market, pd.DataFrame):
        raise ResearchRejected("scored and market must be data frames")
    scored_required = {
        "symbol", "segment_id", "decision_time", "entry_time", "entry_open",
        "exit_time", "exit_open", "probability",
    }
    market_required = {"symbol", "segment_id", "trade_time", "open", "close"}
    missing = scored_required.difference(scored.columns)
    if missing:
        raise ResearchRejected(f"missing scored columns: {', '.join(sorted(missing))}")
    missing = market_required.difference(market.columns)
    if missing:
        raise ResearchRejected(f"missing market columns: {', '.join(sorted(missing))}")
    if scored.empty:
        if (
            not pd.api.types.is_datetime64_any_dtype(market["trade_time"])
            or not pd.api.types.is_numeric_dtype(market["open"])
            or not pd.api.types.is_numeric_dtype(market["close"])
        ):
            raise ResearchRejected("empty market columns must have explicit types")
        return pd.DataFrame(columns=trade_columns), pd.DataFrame(columns=daily_columns)
    if market.empty:
        raise ResearchRejected("no segmented market bars")

    decisions = scored.copy()
    marks = market.copy()
    for column in ("decision_time", "entry_time", "exit_time"):
        decisions[column] = _parse_trade_time(decisions[column])
    marks["trade_time"] = _parse_trade_time(marks["trade_time"])
    if decisions.duplicated(["symbol", "decision_time"]).any():
        raise ResearchRejected("duplicate decision")
    if decisions[["symbol", "segment_id"]].isna().any().any():
        raise ResearchRejected("null scored symbol or segment")
    if marks[["symbol", "segment_id"]].isna().any().any():
        raise ResearchRejected("null market symbol or segment")

    for column in ("probability", "entry_open", "exit_open"):
        decisions[column] = pd.to_numeric(decisions[column], errors="coerce")
    if "terminal_open" in decisions:
        decisions["terminal_open"] = pd.to_numeric(decisions["terminal_open"], errors="coerce")
    if (
        not np.isfinite(decisions["probability"]).all()
        or decisions["probability"].le(0.0).any()
        or decisions["probability"].gt(1.0).any()
    ):
        raise ResearchRejected("probabilities must be finite and in (0, 1]")
    if not np.isfinite(decisions["entry_open"]).all() or decisions["entry_open"].le(0.0).any():
        raise ResearchRejected("entry prices must be finite and positive")
    terminal = decisions.get("terminal_open", pd.Series(np.nan, index=decisions.index))
    usable_exit = decisions["exit_open"].where(decisions["exit_open"].notna(), terminal)
    if not np.isfinite(usable_exit).all() or usable_exit.le(0.0).any():
        raise ResearchRejected("exit prices must be finite and positive")
    if (
        decisions["entry_time"].le(decisions["decision_time"]).any()
        or decisions["exit_time"].le(decisions["entry_time"]).any()
    ):
        raise ResearchRejected("decision, entry, and exit times are inconsistent")

    symbols = tuple(sorted(decisions["symbol"].unique()))
    if len(symbols) > symbol_count:
        raise ResearchRejected("symbol_count is smaller than the scored universe")
    for column in ("open", "close"):
        marks[column] = pd.to_numeric(marks[column], errors="coerce")
        if not np.isfinite(marks[column]).all() or marks[column].le(0.0).any():
            raise ResearchRejected(f"market {column} must be finite and positive")
    if marks.duplicated(["symbol", "segment_id", "trade_time"]).any():
        raise ResearchRejected("duplicate segmented market timestamp")
    market_groups = {
        key: _segment_arrays(group)
        for key, group in marks.groupby(["symbol", "segment_id"], sort=False)
    }

    decisions = decisions.sort_values(
        ["entry_time", "symbol", "decision_time"], kind="stable"
    ).reset_index(drop=True)
    sleeve_cash = {symbol: 1.0 / symbol_count for symbol in symbols}
    available_after = {}
    trades = []
    accepted_paths = []
    evaluation_times = set()
    for row in decisions.itertuples(index=False):
        group = market_groups.get((row.symbol, row.segment_id))
        if group is None:
            raise ResearchRejected("scored segment is missing from market")
        times, opens, closes, positions, gap_prefix = group
        try:
            decision_position = positions[row.decision_time.value]
            entry_position = positions[row.entry_time.value]
            exit_position = positions[row.exit_time.value]
        except KeyError as exc:
            raise ResearchRejected("trade path is missing segmented market marks") from exc
        if entry_position != decision_position + 1:
            raise ResearchRejected("entry_time must be the first bar after decision")
        if exit_position <= entry_position:
            raise ResearchRejected("exit must follow entry")
        if gap_prefix[exit_position] != gap_prefix[decision_position]:
            raise ResearchRejected("trade path must be continuous five-minute bars")
        evaluation_times.update(times[decision_position:exit_position + 1])

        terminal_close = pd.isna(row.exit_open)
        exit_open = float(row.terminal_open) if terminal_close else float(row.exit_open)
        if terminal_close and exit_position != len(times) - 1:
            raise ResearchRejected("terminal close is not the final segment open")
        if (
            not np.isclose(float(row.entry_open), opens[entry_position], rtol=0.0, atol=1e-12)
            or not np.isclose(exit_open, opens[exit_position], rtol=0.0, atol=1e-12)
        ):
            raise ResearchRejected("scored prices do not match market opens")

        direction = _direction(float(row.probability), float(threshold))
        if not direction or row.entry_time < available_after.get(row.symbol, pd.Timestamp.min):
            continue

        gross, entry_cost, exit_cost, net_return = _net_sleeve_return(
            direction, row.entry_open, exit_open, cost_bps
        )
        start_equity = sleeve_cash[row.symbol]
        end_equity = start_equity * (1.0 + net_return)
        if not np.isfinite(end_equity):
            raise ResearchRejected("non-finite sleeve equity")
        ratio = exit_open / float(row.entry_open)
        trade = {
            "symbol": row.symbol,
            "segment_id": row.segment_id,
            "decision_time": row.decision_time,
            "entry_time": row.entry_time,
            "exit_time": row.exit_time,
            "direction": direction,
            "entry_open": float(row.entry_open),
            "exit_open": exit_open,
            "gross_return": gross,
            "entry_cost": entry_cost,
            "exit_cost": exit_cost,
            "net_sleeve_return": net_return,
            "portfolio_return": net_return / symbol_count,
            "threshold": float(threshold),
            "cost_bps": float(cost_bps),
            "exit_reason": "TERMINAL_CLOSE" if terminal_close else "HORIZON_EXIT",
            "sleeve_start_equity": start_equity,
            "sleeve_end_equity": end_equity,
            "sleeve_pnl": end_equity - start_equity,
            "turnover": start_equity * (1.0 + ratio),
        }
        trades.append(trade)
        accepted_paths.append((trade, times, closes, entry_position, exit_position))
        sleeve_cash[row.symbol] = end_equity
        available_after[row.symbol] = row.exit_time

    trade_frame = pd.DataFrame(trades, columns=trade_columns)

    unused_cash = 1.0 - len(symbols) / symbol_count
    events = {}
    for trade, times, closes, entry_position, exit_position in accepted_paths:
        for position in range(entry_position, exit_position + 1):
            timestamp = int(times[position])
            is_entry = position == entry_position
            is_exit = position == exit_position
            sleeve_value = (
                trade["sleeve_end_equity"]
                if is_exit
                else trade["sleeve_start_equity"] * (
                    1.0 - trade["entry_cost"]
                    + trade["direction"] * (closes[position] / trade["entry_open"] - 1.0)
                )
            )
            events.setdefault(timestamp, []).append({
                "symbol": trade["symbol"],
                "sleeve_value": sleeve_value,
                "exposure_delta": (1.0 / symbol_count if is_entry else 0.0)
                - (1.0 / symbol_count if is_exit else 0.0),
                "turnover": (
                    trade["sleeve_start_equity"] if is_entry else 0.0
                ) + (
                    trade["sleeve_start_equity"] * trade["exit_open"] / trade["entry_open"]
                    if is_exit else 0.0
                ),
            })

    sleeve_values = {symbol: 1.0 / symbol_count for symbol in symbols}
    gross_exposure = 0.0
    timestamp_rows = []
    for timestamp in sorted(evaluation_times):
        timestamp_events = events.get(int(timestamp), ())
        for event in timestamp_events:
            sleeve_values[event["symbol"]] = float(event["sleeve_value"])
            gross_exposure += float(event["exposure_delta"])
        sleeve_equity = sum(sleeve_values.values())
        equity = unused_cash + sleeve_equity
        if not np.isfinite(equity) or equity <= 0.0:
            raise ResearchRejected("non-positive portfolio equity")
        if gross_exposure < -1e-12 or gross_exposure > 1.0 + 1e-12:
            raise ResearchRejected("invalid gross exposure")
        timestamp_rows.append({
            "trade_time": pd.Timestamp(timestamp),
            "equity": equity,
            "gross_exposure": gross_exposure,
            "turnover": sum(event["turnover"] for event in timestamp_events),
            "unused_cash": unused_cash,
            "sleeve_equity": sleeve_equity,
        })

    timestamp_frame = pd.DataFrame(timestamp_rows)
    timestamp_frame["date"] = timestamp_frame["trade_time"].dt.normalize()
    daily_rows = []
    previous_equity = 1.0
    for date, group in timestamp_frame.groupby("date", sort=True):
        equity = float(group["equity"].iloc[-1])
        daily_rows.append({
            "date": date,
            "equity": equity,
            "pnl": equity - previous_equity,
            "portfolio_return": equity / previous_equity - 1.0,
            "gross_exposure": float(group["gross_exposure"].mean()),
            "turnover": float(group["turnover"].sum()),
            "unused_cash": unused_cash,
            "sleeve_equity": float(group["sleeve_equity"].iloc[-1]),
        })
        previous_equity = equity
    daily = pd.DataFrame(daily_rows, columns=daily_columns)

    tolerance = 1e-12
    for trade in trade_frame.itertuples(index=False):
        recomputed = _net_sleeve_return(
            trade.direction, trade.entry_open, trade.exit_open, trade.cost_bps
        )
        observed = (trade.gross_return, trade.entry_cost, trade.exit_cost, trade.net_sleeve_return)
        if max(abs(left - right) for left, right in zip(recomputed, observed)) > tolerance:
            raise ResearchRejected("ledger mismatch")
        if abs(trade.sleeve_end_equity - trade.sleeve_start_equity * (1.0 + trade.net_sleeve_return)) > tolerance:
            raise ResearchRejected("ledger mismatch")
    if (timestamp_frame["equity"] - timestamp_frame["sleeve_equity"] - unused_cash).abs().max() > tolerance:
        raise ResearchRejected("ledger mismatch")
    if not daily.empty:
        compounded = float((1.0 + daily["portfolio_return"]).prod())
        if (
            abs(compounded - float(daily["equity"].iloc[-1])) > tolerance
            or abs(float(daily["pnl"].sum()) - (float(daily["equity"].iloc[-1]) - 1.0)) > tolerance
            or abs(float(trade_frame["sleeve_pnl"].sum()) - (float(daily["equity"].iloc[-1]) - 1.0)) > tolerance
        ):
            raise ResearchRejected("ledger mismatch")
    return trade_frame, daily


def strategy_metrics(trades, daily):
    """Return finite strategy statistics from the marked daily ledger."""
    zero = {
        "days": 0,
        "trades": int(len(trades)),
        "total_return": 0.0,
        "annualized_return": 0.0,
        "annualized_volatility": 0.0,
        "sharpe": 0.0,
        "max_drawdown": 0.0,
        "win_rate": 0.0,
        "profit_factor": 0.0,
        "exposure": 0.0,
        "turnover": 0.0,
    }
    if "sleeve_pnl" not in trades:
        raise ResearchRejected("missing trade pnl column")
    required = {"equity", "portfolio_return", "gross_exposure", "turnover"}
    missing = required.difference(daily.columns)
    if missing:
        raise ResearchRejected(f"missing daily ledger columns: {', '.join(sorted(missing))}")
    pnl = pd.to_numeric(trades["sleeve_pnl"], errors="coerce")
    numeric_trades = trades.select_dtypes(include=[np.number])
    if not np.isfinite(pnl).all() or not np.isfinite(numeric_trades).all().all():
        raise ResearchRejected("non-finite strategy metric input")
    if daily.empty:
        if not trades.empty:
            raise ResearchRejected("nonempty trades require a daily ledger")
        return zero
    frame = daily.copy()
    for column in required:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if not np.isfinite(frame[column]).all():
            raise ResearchRejected("non-finite strategy metric input")
    if frame["equity"].le(0.0).any() or frame["portfolio_return"].le(-1.0).any():
        raise ResearchRejected("non-positive strategy equity")

    returns = frame["portfolio_return"].astype(float)
    equity = frame["equity"].to_numpy(dtype=float)
    expected_returns = equity / np.r_[1.0, equity[:-1]] - 1.0
    if np.max(np.abs(returns.to_numpy() - expected_returns)) > 1e-12:
        raise ResearchRejected("ledger mismatch")
    compounded = float((1.0 + returns).prod())
    if abs(compounded - float(frame["equity"].iloc[-1])) > 1e-12:
        raise ResearchRejected("ledger mismatch")
    deviation = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    total_return = compounded - 1.0
    wins = float(pnl[pnl > 0.0].sum())
    losses = float(-pnl[pnl < 0.0].sum())
    peak = np.maximum.accumulate(np.r_[1.0, frame["equity"].to_numpy(dtype=float)])
    drawdown = 1.0 - np.r_[1.0, frame["equity"].to_numpy(dtype=float)] / peak
    result = {
        "days": int(len(frame)),
        "trades": int(len(trades)),
        "total_return": total_return,
        "annualized_return": compounded ** (252.0 / len(frame)) - 1.0,
        "annualized_volatility": deviation * np.sqrt(252.0),
        "sharpe": float(returns.mean()) / deviation * np.sqrt(252.0) if deviation else 0.0,
        "max_drawdown": float(drawdown.max()),
        "win_rate": float(pnl.gt(0.0).mean()) if len(pnl) else 0.0,
        "profit_factor": wins / losses if losses else 0.0,
        "exposure": float(frame["gross_exposure"].mean()),
        "turnover": float(frame["turnover"].sum()),
    }
    if not all(np.isfinite(value) for value in result.values()):
        raise ResearchRejected("non-finite strategy metrics")
    return result


def predictive_metrics(labels, probability, threshold):
    try:
        labels = np.asarray(labels, dtype=float)
        probability = np.asarray(probability, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ResearchRejected("invalid predictive metric input") from exc
    if (
        labels.ndim != 1
        or probability.ndim != 1
        or len(labels) != len(probability)
        or not len(labels)
        or not np.isfinite(labels).all()
        or not np.isfinite(probability).all()
        or set(labels) != {0, 1}
        or (probability < 0.0).any()
        or (probability > 1.0).any()
        or not _finite_number(threshold)
        or not 0.0 <= float(threshold) <= 1.0
    ):
        raise ResearchRejected("invalid predictive metric input")
    label_rank = pd.Series(labels).rank().to_numpy(dtype=float)
    probability_rank = pd.Series(probability).rank().to_numpy(dtype=float)
    rank_correlation = (
        0.0
        if np.ptp(label_rank) == 0.0 or np.ptp(probability_rank) == 0.0
        else float(np.corrcoef(label_rank, probability_rank)[0, 1])
    )
    return {
        "roc_auc": float(roc_auc_score(labels, probability)),
        "balanced_accuracy": float(
            balanced_accuracy_score(labels, probability >= float(threshold))
        ),
        "brier_score": float(brier_score_loss(labels, probability)),
        "rank_correlation": rank_correlation,
    }


def moving_block_return_interval(daily_returns, config=ResearchConfig()):
    try:
        returns = np.asarray(daily_returns, dtype=float)
        rng = np.random.default_rng(config.seed)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ResearchRejected("invalid moving-block interval input") from exc
    if returns.ndim != 1 or len(returns) < 5 or not np.isfinite(returns).all():
        raise ResearchRejected("moving-block interval requires five finite daily returns")
    totals = []
    for _ in range(1000):
        sample = []
        while len(sample) < len(returns):
            start = int(rng.integers(0, len(returns) - 4))
            sample.extend(returns[start:start + 5])
        total = float(np.prod(1.0 + np.asarray(sample[:len(returns)])) - 1.0)
        if not np.isfinite(total):
            raise ResearchRejected("non-finite moving-block return")
        totals.append(total)
    p05, p50, p95 = np.percentile(totals, [5, 50, 95])
    return {
        "samples": 1000,
        "block_days": 5,
        "p05": float(p05),
        "p50": float(p50),
        "p95": float(p95),
    }


def _stable_parameter(value):
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (tuple, list)):
        return [_stable_parameter(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _stable_parameter(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    return repr(value)


def _model_identity(candidate, model, train):
    parameters = {
        key: _stable_parameter(value)
        for key, value in sorted(model.get_params(deep=True).items())
    }
    cutoff = pd.Timestamp(train["decision_time"].max()).isoformat()
    header = json.dumps({
        "model_name": candidate.model_name,
        "parameters": parameters,
        "feature_names": FEATURE_COLUMNS,
        "training_cutoff": cutoff,
    }, sort_keys=True, separators=(",", ":")).encode()
    row_hash = pd.util.hash_pandas_object(train, index=True).to_numpy(dtype=np.uint64)
    target_hash = pd.util.hash_pandas_object(
        train["label"], index=True
    ).to_numpy(dtype=np.uint64)
    digest = hashlib.sha256(header)
    digest.update(row_hash.tobytes())
    digest.update(target_hash.tobytes())
    return digest.hexdigest()[:16], parameters


def _canonical_evaluation_marks(evaluation, market):
    columns = ["symbol", "segment_id", "trade_time", "open", "close"]
    frame = _evaluation_market(evaluation, market).loc[:, columns].copy()
    if frame.empty or frame[["symbol", "segment_id"]].isna().any().any():
        raise ResearchRejected("invalid evaluation market identity input")
    frame["symbol"] = frame["symbol"].astype("string")
    frame["segment_id"] = frame["segment_id"].astype("string")
    frame["trade_time"] = _parse_trade_time(frame["trade_time"]).astype(
        "datetime64[ns]"
    )
    for column in ("open", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")
        if not np.isfinite(frame[column]).all() or frame[column].le(0.0).any():
            raise ResearchRejected("invalid evaluation market identity input")
    frame = frame.sort_values(columns, kind="stable").reset_index(drop=True)
    hashes = pd.util.hash_pandas_object(
        frame, index=False, categorize=True
    ).to_numpy(dtype="<u8")
    return frame, hashlib.sha256(hashes.tobytes()).hexdigest()


def _evaluation_identity(candidate, fold_result, evaluation, market, config):
    if (
        not isinstance(candidate, Candidate)
        or not isinstance(fold_result, dict)
        or "model_identity" not in fold_result
        or "model_parameters" not in fold_result
        or not isinstance(evaluation, pd.DataFrame)
        or evaluation.empty
        or "decision_time" not in evaluation
    ):
        raise ResearchRejected("invalid evaluation identity input")
    try:
        times = pd.DatetimeIndex(evaluation["decision_time"].unique()).sort_values()
        costs = [
            int(cost) if float(cost).is_integer() else float(cost)
            for cost in config.costs_bps
        ]
        seed = int(config.seed)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ResearchRejected("invalid evaluation identity input") from exc
    if times.empty or not costs:
        raise ResearchRejected("invalid evaluation identity input")
    row_hash = hashlib.sha256(
        pd.util.hash_pandas_object(evaluation, index=True)
        .to_numpy(dtype=np.uint64)
        .tobytes()
    ).hexdigest()
    marks, mark_hash = _canonical_evaluation_marks(evaluation, market)
    payload = {
        "scope": "single_build_base_evaluation",
        "candidate": {
            "model_name": candidate.model_name,
            "model_identity": str(fold_result["model_identity"]),
            "model_parameters": _stable_parameter(fold_result["model_parameters"]),
            "threshold": float(candidate.threshold),
        },
        "evaluation_times": [pd.Timestamp(time).isoformat() for time in times],
        "evaluation_rows": int(len(evaluation)),
        "evaluation_row_hash": row_hash,
        "market_mark_rows": int(len(marks)),
        "market_mark_hash": mark_hash,
        "costs_bps": costs,
        "seed": seed,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {"id": hashlib.sha256(encoded).hexdigest()[:16], **payload}


def _evaluation_market(evaluation, market):
    required = {"symbol", "segment_id", "trade_time", "open", "close"}
    if not isinstance(market, pd.DataFrame) or required.difference(market.columns):
        raise ResearchRejected("invalid segmented evaluation market")
    pairs = pd.MultiIndex.from_frame(
        evaluation.loc[:, ["symbol", "segment_id"]].drop_duplicates()
    )
    market_pairs = pd.MultiIndex.from_frame(market.loc[:, ["symbol", "segment_id"]])
    return market.loc[
        market_pairs.isin(pairs)
        & market["trade_time"].between(
            evaluation["decision_time"].min(), evaluation["exit_time"].max()
        )
    ].copy()


def _ledger_by_cost(scored, market, threshold, costs, symbol_count):
    trades_by_cost = {}
    daily_by_cost = {}
    metrics_by_cost = {}
    signature = None
    identity_columns = [
        "symbol", "decision_time", "entry_time", "exit_time", "direction",
        "entry_open", "exit_open",
    ]
    for cost in costs:
        key = int(cost) if float(cost).is_integer() else float(cost)
        trades, daily = simulate_standardized_ledger(
            scored, market, threshold, cost, symbol_count
        )
        current = trades.loc[:, identity_columns].reset_index(drop=True)
        if signature is None:
            signature = current
        elif not current.equals(signature):
            raise ResearchRejected("cost runs changed the frozen trade set")
        trades_by_cost[key] = trades
        daily_by_cost[key] = daily
        metrics_by_cost[key] = strategy_metrics(trades, daily)
    return trades_by_cost, daily_by_cost, metrics_by_cost


def evaluate_fold(dataset, market, fold, candidate, config=ResearchConfig()):
    if not isinstance(dataset, pd.DataFrame) or not isinstance(candidate, Candidate):
        raise ResearchRejected("invalid fold evaluation input")
    try:
        evaluation_times = pd.DatetimeIndex(fold.evaluation_times)
        evaluation_start = evaluation_times[0]
    except (AttributeError, IndexError, TypeError, ValueError) as exc:
        raise ResearchRejected("invalid fold evaluation window") from exc
    if (
        evaluation_times.empty
        or evaluation_times.has_duplicates
        or not evaluation_times.is_monotonic_increasing
    ):
        raise ResearchRejected("invalid fold evaluation window")

    train = purged_training_rows(
        dataset, fold.train_times, evaluation_start, config.embargo_bars
    )
    evaluation = dataset[
        dataset["decision_time"].isin(evaluation_times)
    ].copy()
    if evaluation.empty:
        raise ResearchRejected("empty fold evaluation rows")
    probability, model = fit_predict(candidate, train, evaluation, config)
    scored = evaluation.copy()
    scored["probability"] = probability
    metrics = predictive_metrics(evaluation["label"], probability, candidate.threshold)
    fold_market = _evaluation_market(evaluation, market)
    symbol_count = int(evaluation["symbol"].nunique())
    if symbol_count < 1:
        raise ResearchRejected("model dataset has no symbols")
    costs = tuple(config.costs_bps)
    if (
        not costs
        or any(not _finite_number(cost) or float(cost) < 0.0 for cost in costs)
        or len(set(float(cost) for cost in costs)) != len(costs)
    ):
        raise ResearchRejected("evaluation costs must be non-empty and unique")
    model_identity, model_parameters = _model_identity(candidate, model, train)
    trades_by_cost, daily_by_cost, cost_metrics = _ledger_by_cost(
        scored, fold_market, candidate.threshold, costs, symbol_count
    )
    for cost, trades in trades_by_cost.items():
        trades["fold"] = fold.name
        trades["model_identity"] = model_identity
        daily_by_cost[cost]["fold"] = fold.name
        daily_by_cost[cost]["model_identity"] = model_identity

    symbol_rows = []
    for symbol in sorted(evaluation["symbol"].unique()):
        symbol_scored = scored[scored["symbol"].eq(symbol)].copy()
        symbol_predictive = predictive_metrics(
            symbol_scored["label"], symbol_scored["probability"], candidate.threshold
        )
        _, _, symbol_cost_metrics = _ledger_by_cost(
            symbol_scored, fold_market, candidate.threshold, costs, symbol_count
        )
        for cost, strategy in symbol_cost_metrics.items():
            symbol_rows.append({
                "fold": fold.name,
                "symbol": symbol,
                "cost_bps": cost,
                "rows": len(symbol_scored),
                "evaluation_start": pd.Timestamp(
                    symbol_scored["decision_time"].min()
                ),
                "evaluation_end": pd.Timestamp(
                    symbol_scored["decision_time"].max()
                ),
                "evaluation_dates": int(
                    symbol_scored["decision_time"].dt.normalize().nunique()
                ),
                **symbol_predictive,
                **strategy,
            })

    dummy = DummyClassifier(strategy="prior", random_state=config.seed)
    dummy.fit(
        train.loc[:, FEATURE_COLUMNS], train["label"],
        sample_weight=inverse_symbol_class_weights(train),
    )
    dummy_probability = dummy.predict_proba(evaluation.loc[:, FEATURE_COLUMNS])[:, 1]
    benchmark_probabilities = {
        "dummy_prior": dummy_probability,
        "equal_weight_long_only": np.ones(len(evaluation)),
    }
    benchmarks = {}
    reference_dates = {
        cost: daily["date"].reset_index(drop=True)
        for cost, daily in daily_by_cost.items()
    }
    for name, benchmark_probability in benchmark_probabilities.items():
        benchmark_scored = evaluation.copy()
        benchmark_scored["probability"] = benchmark_probability
        benchmark_trades, benchmark_daily, benchmark_cost_metrics = _ledger_by_cost(
            benchmark_scored, fold_market, candidate.threshold, costs, symbol_count
        )
        for cost, daily in benchmark_daily.items():
            if not daily["date"].reset_index(drop=True).equals(reference_dates[cost]):
                raise ResearchRejected("benchmark evaluation timestamps changed")
        benchmarks[name] = {
            "predictive_metrics": predictive_metrics(
                evaluation["label"], benchmark_probability, candidate.threshold
            ),
            "cost_metrics": benchmark_cost_metrics,
            "trades": benchmark_trades,
            "daily": benchmark_daily,
        }

    result = {
        "fold": fold.name,
        "candidate": candidate,
        "model_name": candidate.model_name,
        "model_parameters": model_parameters,
        "model_identity": model_identity,
        "threshold": candidate.threshold,
        "split_cutoffs": {
            "training_start": pd.Timestamp(train["decision_time"].min()),
            "training_cutoff": pd.Timestamp(train["decision_time"].max()),
            "label_cutoff": pd.Timestamp(train["label_end_time"].max()),
            "evaluation_start": pd.Timestamp(evaluation["decision_time"].min()),
            "evaluation_end": pd.Timestamp(evaluation["decision_time"].max()),
        },
        "sample_counts": {
            "train_rows": int(len(train)),
            "evaluation_rows": int(len(evaluation)),
            "symbols": symbol_count,
            "train_dates": int(train["decision_time"].dt.normalize().nunique()),
            "evaluation_dates": int(evaluation["decision_time"].dt.normalize().nunique()),
            "positive_labels": int(evaluation["label"].sum()),
            "negative_labels": int(len(evaluation) - evaluation["label"].sum()),
        },
        "predictive_metrics": metrics,
        "cost_metrics": cost_metrics,
        "benchmarks": benchmarks,
        "symbol_metrics": pd.DataFrame(symbol_rows),
        "trades": trades_by_cost,
        "daily": daily_by_cost,
    }
    return result


def _partition_times(fold):
    try:
        train = pd.DatetimeIndex(fold.train_times)
        evaluation = pd.DatetimeIndex(fold.evaluation_times)
        ordered = train[-1] < evaluation[0]
    except (AttributeError, IndexError, TypeError, ValueError) as exc:
        raise ResearchRejected("invalid evaluation partition") from exc
    if (
        train.empty
        or evaluation.empty
        or train.hasnans
        or evaluation.hasnans
        or train.has_duplicates
        or evaluation.has_duplicates
        or not train.is_monotonic_increasing
        or not evaluation.is_monotonic_increasing
        or not ordered
    ):
        raise ResearchRejected("invalid evaluation partition")
    return train, evaluation


def _validate_evaluation_partitions(partitions):
    try:
        outer_folds = tuple(partitions["outer_folds"])
        inner_by_outer = partitions["inner_by_outer"]
        development_inner = tuple(partitions["development_inner_folds"])
        holdout_fold = partitions["holdout_fold"]
        outer_names = tuple(fold.name for fold in outer_folds)
    except (AttributeError, KeyError, TypeError) as exc:
        raise ResearchRejected("invalid evaluation partition") from exc
    if (
        len(outer_folds) != 3
        or len(set(outer_names)) != 3
        or "holdout" in outer_names
        or holdout_fold.name != "holdout"
    ):
        raise ResearchRejected("invalid evaluation partition")
    development, holdout = _partition_times(holdout_fold)
    previous_outer_end = None
    for fold in outer_folds:
        train, evaluation = _partition_times(fold)
        if (
            not train.isin(development).all()
            or not evaluation.isin(development).all()
            or (previous_outer_end is not None and evaluation[0] <= previous_outer_end)
        ):
            raise ResearchRejected("invalid evaluation partition")
        previous_outer_end = evaluation[-1]
        try:
            inner_folds = tuple(inner_by_outer[fold.name])
        except (KeyError, TypeError) as exc:
            raise ResearchRejected("invalid evaluation partition") from exc
        _validate_inner_domains(inner_folds, train)
    _validate_inner_domains(development_inner, development)
    if not holdout.intersection(development).empty:
        raise ResearchRejected("invalid evaluation partition")


def _validate_inner_domains(folds, allowed_times):
    try:
        names = tuple(fold.name for fold in folds)
    except (AttributeError, TypeError) as exc:
        raise ResearchRejected("invalid evaluation partition") from exc
    if len(folds) != 2 or len(set(names)) != 2:
        raise ResearchRejected("invalid evaluation partition")
    evaluation_windows = []
    for fold in folds:
        train, evaluation = _partition_times(fold)
        if not train.isin(allowed_times).all() or not evaluation.isin(allowed_times).all():
            raise ResearchRejected("invalid evaluation partition")
        evaluation_windows.append(evaluation)
    if not evaluation_windows[0].intersection(evaluation_windows[1]).empty:
        raise ResearchRejected("invalid evaluation partition")


def _parent_selection_view(dataset, parent, inner_folds, config):
    safe = purged_training_rows(
        dataset,
        parent.train_times,
        parent.evaluation_times[0],
        config.embargo_bars,
    )
    safe_times = pd.DatetimeIndex(safe["decision_time"].unique()).sort_values()
    restricted = []
    for fold in inner_folds:
        train_times = pd.DatetimeIndex(fold.train_times)
        evaluation_times = pd.DatetimeIndex(fold.evaluation_times)
        restricted.append(TemporalFold(
            fold.name,
            train_times[train_times.isin(safe_times)],
            evaluation_times[evaluation_times.isin(safe_times)],
        ))
    _validate_inner_domains(tuple(restricted), safe_times)
    return safe, tuple(restricted)


def build_base_evaluation(dataset, market, partitions, config=ResearchConfig()):
    _validate_evaluation_partitions(partitions)
    outer_results = []
    for fold in partitions["outer_folds"]:
        selection_dataset, inner = _parent_selection_view(
            dataset, fold, partitions["inner_by_outer"][fold.name], config
        )
        chosen, inner_scores = select_candidate(
            selection_dataset, market, inner, config
        )
        outer_result = evaluate_fold(dataset, market, fold, chosen, config)
        outer_result["inner_scores"] = inner_scores
        outer_results.append(outer_result)
    holdout_fold = partitions["holdout_fold"]
    selection_dataset, development_inner = _parent_selection_view(
        dataset, holdout_fold, partitions["development_inner_folds"], config
    )
    final_candidate, final_inner_scores = select_candidate(
        selection_dataset, market, development_inner, config
    )
    holdout_result = evaluate_fold(
        dataset, market, holdout_fold, final_candidate, config
    )
    if 5 not in holdout_result["daily"]:
        raise ResearchRejected("locked holdout requires the 5 bp ledger")
    holdout_result["bootstrap"] = moving_block_return_interval(
        holdout_result["daily"][5]["portfolio_return"], config
    )
    holdout_evaluation = dataset[
        dataset["decision_time"].isin(holdout_fold.evaluation_times)
    ].copy()
    holdout_result["evaluation_identity"] = _evaluation_identity(
        final_candidate, holdout_result, holdout_evaluation, market, config
    )
    holdout_train = purged_training_rows(
        dataset,
        holdout_fold.train_times,
        holdout_fold.evaluation_times[0],
        config.embargo_bars,
    )
    holdout_result["attack_execution_identity"] = _attack_execution_identity(
        holdout_train,
        holdout_evaluation,
        _evaluation_market(holdout_evaluation, market),
    )
    return {
        "outer_results": outer_results,
        "final_candidate": final_candidate,
        "final_inner_scores": final_inner_scores,
        "holdout": holdout_result,
    }


def _attack_domain(context):
    try:
        dataset = context["dataset"]
        market = context["segmented"]
        fold = context["partitions"]["holdout_fold"]
        base = context.get("base", context)
        candidate = base["final_candidate"]
        config = context.get("config", ResearchConfig())
        evaluation_times = pd.DatetimeIndex(fold.evaluation_times)
        train = purged_training_rows(
            dataset, fold.train_times, evaluation_times[0], config.embargo_bars
        )
        evaluation = dataset[dataset["decision_time"].isin(evaluation_times)].copy()
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise ResearchRejected("invalid adversarial context") from exc
    if (
        not isinstance(dataset, pd.DataFrame)
        or not isinstance(candidate, Candidate)
        or train.empty
        or evaluation.empty
    ):
        raise ResearchRejected("invalid adversarial context")
    return train, evaluation, _evaluation_market(evaluation, market), candidate, config


def _append_future_bars(bars, config):
    future = []
    for _, rows in bars.groupby("symbol", sort=False):
        last = rows.iloc[-1]
        for number in range(1, int(config.horizon) + 2):
            row = last.copy()
            row["trade_time"] = pd.Timestamp(last["trade_time"]) + pd.Timedelta(
                minutes=5 * number
            )
            future.append(row)
    if not future:
        raise ResearchRejected("prefix attack requires source bars")
    return pd.DataFrame(future, columns=bars.columns)


def _same_numeric(left, right):
    return (
        left.shape == right.shape
        and np.allclose(
            left.to_numpy(dtype=float), right.to_numpy(dtype=float),
            rtol=0.0, atol=1e-12,
        )
    )


def _canonical_attack_frame(frame):
    if not isinstance(frame, pd.DataFrame) or frame.empty or not frame.columns.is_unique:
        raise ResearchRejected("attack execution domain must be a non-empty data frame")
    # Drop DataFrame subclasses used to guard target access: hashing the frozen
    # rows is an audit operation and must not re-enter selection-time accessors.
    canonical = pd.DataFrame(frame).copy(deep=True)
    for column in canonical.columns:
        if pd.api.types.is_datetime64_any_dtype(canonical[column]):
            canonical[column] = pd.to_datetime(canonical[column]).astype("datetime64[ns]")
    for column in ("symbol", "segment_id"):
        if column in canonical:
            canonical[column] = canonical[column].astype("string")
    columns = sorted(canonical.columns)
    sort_columns = [
        column for column in ("decision_time", "symbol", "segment_id", "trade_time")
        if column in canonical
    ]
    canonical = canonical.loc[:, columns].sort_values(
        sort_columns or columns, kind="stable"
    ).reset_index(drop=True)
    header = json.dumps({
        "columns": columns,
        "dtypes": [str(canonical[column].dtype) for column in columns],
    }, sort_keys=True, separators=(",", ":")).encode()
    hashes = pd.util.hash_pandas_object(
        canonical, index=False, categorize=True
    ).to_numpy(dtype="<u8")
    digest = hashlib.sha256(header)
    digest.update(hashes.tobytes())
    return {"rows": int(len(canonical)), "sha256": digest.hexdigest()}


def _attack_execution_identity(train, evaluation, market):
    required_train = {"decision_time", "label_end_time"}
    required_evaluation = {"decision_time", "label_end_time"}
    if (
        not isinstance(train, pd.DataFrame)
        or not isinstance(evaluation, pd.DataFrame)
        or required_train.difference(train.columns)
        or required_evaluation.difference(evaluation.columns)
        or train.empty
        or evaluation.empty
    ):
        raise ResearchRejected("invalid attack execution domain")
    marks, market_hash = _canonical_evaluation_marks(evaluation, market)
    times = pd.DatetimeIndex(evaluation["decision_time"].unique()).sort_values()
    time_hashes = pd.util.hash_pandas_object(
        pd.Series(times, dtype="datetime64[ns]"), index=False
    ).to_numpy(dtype="<u8")
    payload = {
        "training": {
            **_canonical_attack_frame(train),
            "start": pd.Timestamp(train["decision_time"].min()).isoformat(),
            "cutoff": pd.Timestamp(train["decision_time"].max()).isoformat(),
            "label_cutoff": pd.Timestamp(train["label_end_time"].max()).isoformat(),
        },
        "evaluation": {
            **_canonical_attack_frame(evaluation),
            "time_count": int(len(times)),
            "time_sha256": hashlib.sha256(time_hashes.tobytes()).hexdigest(),
            "start": pd.Timestamp(times[0]).isoformat(),
            "end": pd.Timestamp(times[-1]).isoformat(),
        },
        "market": {"rows": int(len(marks)), "sha256": market_hash},
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {"id": hashlib.sha256(encoded).hexdigest(), **payload}


def _attack_consistency_sha256(attack):
    if not isinstance(attack, dict):
        raise ResearchRejected("invalid attack consistency data")
    payload = {
        key: value for key, value in attack.items()
        if key != "consistency_sha256"
    }
    candidate = payload.get("candidate")
    if isinstance(candidate, Candidate):
        payload["candidate"] = {
            "model_name": candidate.model_name,
            "threshold": candidate.threshold,
        }
    encoded = json.dumps(
        _stable_parameter(payload), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _seal_attack_consistency(attack):
    attack["consistency_sha256"] = _attack_consistency_sha256(attack)
    return attack


def _frozen_attack_evidence(context, attack_id, execution_identity):
    try:
        base = context.get("base", context)
        candidate = base["final_candidate"]
        identity = base["holdout"]["evaluation_identity"]
        expected_execution = base["holdout"]["attack_execution_identity"]
        kind, columns = ATTACK_EVIDENCE[attack_id]
    except (AttributeError, KeyError, TypeError) as exc:
        raise ResearchRejected("attack requires locked baseline identity") from exc
    if (
        not isinstance(candidate, Candidate)
        or not isinstance(identity, dict)
        or not identity
        or execution_identity != expected_execution
    ):
        raise ResearchRejected("attack requires locked baseline identity")
    return {
        "candidate": candidate,
        "threshold": candidate.threshold,
        "kind": kind,
        "columns": columns,
        "baseline_evaluation_identity": copy.deepcopy(identity),
        "attack_execution_identity": copy.deepcopy(execution_identity),
    }


def run_prefix_attack(context):
    try:
        bars = context["bars"]
        partitions = context["partitions"]
        base = context.get("base", context)
        config = context.get("config", ResearchConfig())
        appended = context.get("future_bars")
    except (AttributeError, KeyError, TypeError) as exc:
        raise ResearchRejected("invalid prefix attack context") from exc
    if not isinstance(bars, pd.DataFrame) or bars.empty:
        raise ResearchRejected("prefix attack requires source bars")
    if appended is None:
        appended = _append_future_bars(bars, config)
    if not isinstance(appended, pd.DataFrame) or appended.empty:
        raise ResearchRejected("prefix attack requires future bars")

    original_segmented, _ = validate_and_segment(bars, config)
    extended_segmented, _ = validate_and_segment(
        pd.concat([bars, appended], ignore_index=True), config
    )
    full_original = build_causal_dataset(original_segmented, config)
    full_extended = build_causal_dataset(extended_segmented, config)
    original = full_original
    extended = full_extended
    eligible = partitions.get("eligible_symbols")
    if eligible is not None:
        original = original[original["symbol"].isin(eligible)].copy()
        extended = extended[extended["symbol"].isin(eligible)].copy()
    if original.empty:
        raise ResearchRejected("prefix attack has no matured labels")
    cutoff = pd.Timestamp(original["decision_time"].max())
    keys = ["symbol", "segment_id", "decision_time"]
    original = original[original["decision_time"] <= cutoff].sort_values(
        keys, kind="stable"
    ).reset_index(drop=True)
    extended = extended[extended["decision_time"] <= cutoff].sort_values(
        keys, kind="stable"
    ).reset_index(drop=True)
    same_keys = original.loc[:, keys].equals(extended.loc[:, keys])
    features_equal = same_keys and _same_numeric(
        original.loc[:, FEATURE_COLUMNS], extended.loc[:, FEATURE_COLUMNS]
    )
    time_columns = ["entry_time", "exit_time", "label_end_time"]
    numeric_label_columns = ["entry_open", "exit_open", "future_return", "label"]
    labels_equal = (
        same_keys
        and original.loc[:, time_columns].equals(extended.loc[:, time_columns])
        and _same_numeric(
            original.loc[:, numeric_label_columns],
            extended.loc[:, numeric_label_columns],
        )
    )

    folds = [*partitions.get("outer_folds", ()), partitions["holdout_fold"]]
    outer_results = tuple(base.get("outer_results", ()))
    candidates = [row.get("candidate") for row in outer_results]
    candidates.append(base.get("final_candidate"))
    if len(candidates) != len(folds) or any(
        not isinstance(candidate, Candidate) for candidate in candidates
    ):
        raise ResearchRejected("prefix attack requires frozen candidates")

    membership_equal = True
    probabilities_equal = True
    maximum_difference = 0.0
    for fold, candidate in zip(folds, candidates):
        try:
            evaluation_start = pd.DatetimeIndex(fold.evaluation_times)[0]
        except (AttributeError, IndexError, TypeError, ValueError) as exc:
            raise ResearchRejected("invalid prefix attack partition") from exc
        before_train = purged_training_rows(
            original, fold.train_times, evaluation_start, config.embargo_bars
        )
        after_train = purged_training_rows(
            extended, fold.train_times, evaluation_start, config.embargo_bars
        )
        before_evaluation = original[
            original["decision_time"].isin(fold.evaluation_times)
        ].copy()
        after_evaluation = extended[
            extended["decision_time"].isin(fold.evaluation_times)
        ].copy()
        membership_equal &= (
            before_train.loc[:, keys].reset_index(drop=True).equals(
                after_train.loc[:, keys].reset_index(drop=True)
            )
            and before_evaluation.loc[:, keys].reset_index(drop=True).equals(
                after_evaluation.loc[:, keys].reset_index(drop=True)
            )
        )
        before_probability, _ = fit_predict(
            candidate, before_train, before_evaluation, config
        )
        after_probability, _ = fit_predict(
            candidate, after_train, after_evaluation, config
        )
        if before_probability.shape != after_probability.shape:
            probabilities_equal = False
            maximum_difference = float("inf")
        else:
            difference = float(np.max(np.abs(before_probability - after_probability)))
            maximum_difference = max(maximum_difference, difference)
            probabilities_equal &= bool(np.allclose(
                before_probability, after_probability, rtol=0.0, atol=1e-12
            ))

    checks = {
        "features": bool(features_equal),
        "matured_labels": bool(labels_equal),
        "split_membership": bool(membership_equal),
        "probabilities": bool(probabilities_equal),
    }
    passed = all(checks.values())
    holdout_fold = partitions["holdout_fold"]
    holdout_evaluation = full_original[
        full_original["decision_time"].isin(holdout_fold.evaluation_times)
    ].copy()
    holdout_train = purged_training_rows(
        full_original,
        holdout_fold.train_times,
        holdout_fold.evaluation_times[0],
        config.embargo_bars,
    )
    execution_identity = _attack_execution_identity(
        holdout_train,
        holdout_evaluation,
        _evaluation_market(holdout_evaluation, original_segmented),
    )
    return _seal_attack_consistency({
        "id": "prefix_invariance",
        **_frozen_attack_evidence(
            context, "prefix_invariance", execution_identity
        ),
        "passed": passed,
        "reason": "all frozen prefixes match" if passed else "future bars changed frozen evidence",
        "checks": checks,
        "cutoff": cutoff,
        "compared_rows": int(len(original)),
        "max_probability_difference": maximum_difference,
    })


def _attack_strategy_metrics(evaluation, probability, market, candidate):
    scored = evaluation.copy()
    scored["probability"] = probability
    trades, daily = simulate_standardized_ledger(
        scored, market, candidate.threshold, 5, int(evaluation["symbol"].nunique())
    )
    return predictive_metrics(
        evaluation["label"], probability, candidate.threshold
    ), strategy_metrics(trades, daily)


def run_label_shuffle_attack(context):
    train, evaluation, market, candidate, config = _attack_domain(context)
    execution_identity = _attack_execution_identity(train, evaluation, market)
    metrics = []
    for number in range(20):
        shuffled = train.copy()
        rng = np.random.default_rng(42 + number)
        for _, rows in train.groupby("symbol", sort=False):
            shuffled.loc[rows.index, "label"] = rng.permutation(
                rows["label"].to_numpy()
            )
        probability, _ = fit_predict(candidate, shuffled, evaluation, config)
        predictive, strategy = _attack_strategy_metrics(
            evaluation, probability, market, candidate
        )
        metrics.append({
            "permutation": number,
            "seed": 42 + number,
            "roc_auc": predictive["roc_auc"],
            "return_5bps": strategy["total_return"],
        })
    aucs = np.asarray([row["roc_auc"] for row in metrics], dtype=float)
    returns = np.asarray([row["return_5bps"] for row in metrics], dtype=float)
    if not np.isfinite(aucs).all() or not np.isfinite(returns).all():
        raise ResearchRejected("non-finite label shuffle result")
    return _seal_attack_consistency({
        "id": "label_shuffle",
        **_frozen_attack_evidence(
            context, "label_shuffle", execution_identity
        ),
        "passed": True,
        "reason": "20 deterministic within-symbol permutations completed",
        "metrics": metrics,
        "max_auc": float(aucs.max()),
        "median_return_5bps": float(np.median(returns)),
    })


def _hash_noise(symbol, decision_time, column, seed=42):
    token = f"{seed}|{symbol}|{pd.Timestamp(decision_time).isoformat()}|{column}"
    integer = int(hashlib.sha256(token.encode()).hexdigest()[:16], 16)
    return integer / float(0xFFFFFFFFFFFFFFFF) * 2.0 - 1.0


def _feature_attack_columns(frame, kind):
    if kind == "noise":
        columns = tuple(f"noise_{number}" for number in range(1, 6))
        values = {
            name: [
                _hash_noise(symbol, decision_time, number, 42)
                for symbol, decision_time in zip(
                    frame["symbol"], frame["decision_time"]
                )
            ]
            for number, name in enumerate(columns, start=1)
        }
    elif kind == "calendar":
        columns = (
            "time_of_day_sin", "time_of_day_cos",
            "day_of_week_sin", "day_of_week_cos",
        )
        times = pd.to_datetime(frame["decision_time"])
        time_angle = 2.0 * np.pi * (
            times.dt.hour * 3600 + times.dt.minute * 60 + times.dt.second
        ) / 86_400.0
        day_angle = 2.0 * np.pi * times.dt.dayofweek / 7.0
        values = {
            columns[0]: np.sin(time_angle),
            columns[1]: np.cos(time_angle),
            columns[2]: np.sin(day_angle),
            columns[3]: np.cos(day_angle),
        }
    else:
        raise ResearchRejected("feature attack kind must be noise or calendar")
    return pd.DataFrame(values, index=frame.index), columns


def run_feature_attack(context, kind):
    train, evaluation, market, candidate, config = _attack_domain(context)
    execution_identity = _attack_execution_identity(train, evaluation, market)
    train_attack, columns = _feature_attack_columns(train, kind)
    evaluation_attack, _ = _feature_attack_columns(evaluation, kind)
    x_train = pd.concat([train.loc[:, FEATURE_COLUMNS], train_attack], axis=1)
    x_evaluation = pd.concat([
        evaluation.loc[:, FEATURE_COLUMNS], evaluation_attack
    ], axis=1)
    probability, _ = _fit_matrix(
        candidate,
        x_train,
        train["label"],
        inverse_symbol_class_weights(train),
        x_evaluation,
        config,
    )
    predictive, strategy = _attack_strategy_metrics(
        evaluation, probability, market, candidate
    )
    return _seal_attack_consistency({
        "id": f"{kind}_features",
        **_frozen_attack_evidence(
            context, f"{kind}_features", execution_identity
        ),
        "passed": True,
        "reason": f"{kind} attack completed on the locked holdout",
        "roc_auc": predictive["roc_auc"],
        "return_5bps": strategy["total_return"],
    })


def run_adversarial_checks(
    base, bars, dataset, segmented, partitions, checks,
    config=ResearchConfig(),
):
    """Run the official in-process attacks and immediately derive gate status."""
    context = {
        "base": base,
        "bars": bars,
        "dataset": dataset,
        "segmented": segmented,
        "partitions": partitions,
        "checks": checks,
        "config": config,
    }
    matrix = pd.DataFrame({name: [0.0] for name in FEATURE_COLUMNS})
    rejected = []
    for extra in ("future_return", "unknown"):
        try:
            assert_feature_columns(matrix.assign(**{extra: 0.0}))
        except ResearchRejected:
            rejected.append(extra)
    whitelist_passed = rejected == ["future_return", "unknown"]
    train, evaluation, market, _, _ = _attack_domain(context)
    execution_identity = _attack_execution_identity(train, evaluation, market)
    attacks = [
        run_prefix_attack(context),
        _seal_attack_consistency({
            "id": "feature_whitelist",
            **_frozen_attack_evidence(
                context, "feature_whitelist", execution_identity
            ),
            "passed": whitelist_passed,
            "reason": (
                "future and unknown columns rejected"
                if whitelist_passed else "feature whitelist accepted an attack column"
            ),
            "rejected_columns": rejected,
        }),
        run_label_shuffle_attack(context),
        run_feature_attack(context, "noise"),
        run_feature_attack(context, "calendar"),
    ]
    gate_context = {**context, "attacks": attacks}
    gates = evaluate_acceptance_gates(gate_context)
    return {
        "attacks": attacks,
        "gates": gates,
        "status": research_status(gates),
    }


def _gate_record(gate_id, passed, observed, required, affected_fold, reason):
    return {
        "id": gate_id,
        "passed": passed is True,
        "observed": observed,
        "required": required,
        "affected_fold": affected_fold,
        "reason": reason,
    }


def _failed_gate(gate_id, required, reason, observed=None, affected_fold=None):
    return _gate_record(
        gate_id, False, observed, required, affected_fold, reason
    )


def _gate_inputs(context):
    try:
        raw_outer = tuple(context["partitions"]["outer_folds"])
        raw_holdout = context["partitions"]["holdout_fold"]
        raw_names = [fold.name for fold in raw_outer]
    except (AttributeError, KeyError, TypeError) as exc:
        raise ValueError("invalid raw evaluation partition identity") from exc
    if (
        len(raw_outer) != 3
        or len(set(raw_names)) != 3
        or set(raw_names) != {"outer_1", "outer_2", "outer_3"}
        or raw_holdout.name != "holdout"
    ):
        raise ValueError("raw partition identities must be unique outer_1/outer_2/outer_3/holdout")
    base = context.get("base", context)
    outer = list(base["outer_results"])
    holdout = base["holdout"]
    _fold_results(outer, holdout)
    attacks = context["attacks"]
    if not isinstance(attacks, (list, tuple)):
        raise ValueError("attacks must be a sequence")
    attack_ids = [row.get("id") if isinstance(row, dict) else None for row in attacks]
    if len(attack_ids) != len(ATTACK_EVIDENCE) or set(attack_ids) != set(ATTACK_EVIDENCE):
        raise ValueError("attack IDs must be complete, exact, and unique")
    attack_map = {
        row["id"]: row for row in attacks
    }
    candidate = base["final_candidate"]
    identity = holdout["evaluation_identity"]
    train, evaluation, market, domain_candidate, _ = _attack_domain(context)
    expected_execution = _attack_execution_identity(train, evaluation, market)
    baseline_execution = holdout.get("attack_execution_identity")
    if (
        not isinstance(candidate, Candidate)
        or candidate != domain_candidate
        or not isinstance(identity, dict)
        or not identity
        or baseline_execution != expected_execution
    ):
        raise ValueError("invalid frozen baseline identity")
    for attack_id, attack in attack_map.items():
        kind, columns = ATTACK_EVIDENCE[attack_id]
        required = {
            "candidate", "threshold", "kind", "columns",
            "baseline_evaluation_identity", "attack_execution_identity",
            "consistency_sha256",
        }
        if (
            required.difference(attack)
            or attack["candidate"] != candidate
            or attack["threshold"] != candidate.threshold
            or attack["kind"] != kind
            or tuple(attack["columns"]) != columns
            or "future_return" in attack["columns"]
            or attack["baseline_evaluation_identity"] != identity
            or attack["attack_execution_identity"] != expected_execution
            or attack["consistency_sha256"] != _attack_consistency_sha256(attack)
        ):
            raise ValueError(f"attack data is inconsistent: {attack_id}")
    whitelist = attack_map["feature_whitelist"]
    if tuple(whitelist.get("rejected_columns", ())) != ("future_return", "unknown"):
        raise ValueError("feature whitelist evidence is incomplete")
    prefix = attack_map["prefix_invariance"]
    prefix_checks = prefix.get("checks")
    compared_rows = prefix.get("compared_rows")
    probability_difference = prefix.get("max_probability_difference")
    if (
        not isinstance(prefix_checks, dict)
        or set(prefix_checks) != {
            "features", "matured_labels", "split_membership", "probabilities",
        }
        or not all(value is True for value in prefix_checks.values())
        or isinstance(compared_rows, (bool, np.bool_))
        or not isinstance(compared_rows, (int, np.integer))
        or compared_rows < 1
        or not _finite_number(probability_difference)
        or not 0.0 <= float(probability_difference) <= 1e-12
    ):
        raise ValueError("prefix evidence is incomplete or failed")
    return base, outer, holdout, attacks, attack_map


def _fold_results(outer, holdout):
    expected = {"outer_1", "outer_2", "outer_3"}
    if (
        len(outer) != 3
        or not all(isinstance(row, dict) for row in [*outer, holdout])
        or {row.get("fold") for row in outer} != expected
        or len({row.get("fold") for row in outer}) != 3
        or holdout.get("fold") != "holdout"
    ):
        raise ValueError("fold identities must be unique outer_1/outer_2/outer_3/holdout")
    return [*outer, holdout]


def _temporal_integrity(context, base):
    if "dataset" not in context or "partitions" not in context:
        return {}
    dataset = context["dataset"]
    partitions = context["partitions"]
    config = context.get("config", ResearchConfig())
    folds = [*partitions.get("outer_folds", ()), partitions["holdout_fold"]]
    results = [*base.get("outer_results", ()), base["holdout"]]
    if len(folds) != len(results):
        return {"frozen_partitions": False}
    observed = {}
    required_cutoffs = {
        "training_start", "training_cutoff", "label_cutoff",
        "evaluation_start", "evaluation_end",
    }
    for fold, result in zip(folds, results):
        train_times, evaluation_times = _partition_times(fold)
        start = evaluation_times[0]
        purged = purged_training_rows(
            dataset, train_times, start, config.embargo_bars
        )
        label_safe = (
            not purged.empty and (purged["label_end_time"] < start).all()
        )
        embargo_safe = True
        eligible = dataset[
            dataset["decision_time"].isin(train_times)
            & (dataset["label_end_time"] < start)
        ]
        for _, rows in eligible.groupby("symbol", sort=False):
            embargoed = rows.sort_values("decision_time").tail(config.embargo_bars)
            embargo_safe &= set(embargoed.index).isdisjoint(purged.index)
        evaluation = dataset[dataset["decision_time"].isin(evaluation_times)]
        expected_cutoffs = {
            "training_start": pd.Timestamp(purged["decision_time"].min()),
            "training_cutoff": pd.Timestamp(purged["decision_time"].max()),
            "label_cutoff": pd.Timestamp(purged["label_end_time"].max()),
            "evaluation_start": pd.Timestamp(evaluation["decision_time"].min()),
            "evaluation_end": pd.Timestamp(evaluation["decision_time"].max()),
        }
        cutoffs = result.get("split_cutoffs")
        cutoff_safe = (
            isinstance(cutoffs, dict)
            and set(cutoffs) == required_cutoffs
            and all(
                pd.Timestamp(cutoffs[name]) == expected_cutoffs[name]
                for name in required_cutoffs
            )
            and result.get("fold") == fold.name
        )
        observed[f"purge_{fold.name}"] = bool(label_safe and cutoff_safe)
        observed[f"embargo_{fold.name}"] = bool(embargo_safe)
    return observed


def evaluate_acceptance_gates(context):
    """Check supplied gate data for consistency; this does not authenticate origin."""
    gates = []
    try:
        base, outer, holdout, attacks, attack_map = _gate_inputs(context)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        reason = f"missing acceptance evidence: {exc}"
        return [
            _failed_gate(gate_id, required, reason)
            for gate_id, required in (
                ("integrity_checks", "all checks true"),
                ("auc_above_chance_each_fold", "> 0.50 each fold"),
                ("positive_5bps_each_fold", "> 0 each fold"),
                ("positive_bootstrap_lower_bound", "p05 > 0"),
                ("label_shuffle", "20 hostile permutations rejected"),
                ("feature_attacks", "AUC <= +0.01 and return <= +0.05"),
                ("positive_symbol_fraction", ">= 0.50"),
                ("positive_symbol_concentration", "top five <= 0.50"),
                ("ten_bps_resilience", "return > -0.10 and drawdown < 0.20"),
                ("cost_monotonicity", "0/2/5/10/20 bp non-increasing"),
            )
        ]

    try:
        checks = context["checks"]
        required_checks = {"structural", "causal", "ledger"}
        temporal_checks = _temporal_integrity(context, base)
        integrity = (
            isinstance(checks, dict)
            and required_checks.issubset(checks)
            and all(value is True for value in checks.values())
            and all(value is True for value in temporal_checks.values())
            and attack_map["prefix_invariance"].get("passed") is True
            and attack_map["feature_whitelist"].get("passed") is True
            and len(attack_map) == len(attacks)
        )
        observed = {
            **checks,
            **temporal_checks,
            "prefix_invariance": attack_map["prefix_invariance"].get("passed"),
            "feature_whitelist": attack_map["feature_whitelist"].get("passed"),
        }
        affected = next((name for name, passed in observed.items() if passed is not True), None)
        gates.append(_gate_record(
            "integrity_checks", integrity, observed, "all checks true", affected,
            "all integrity checks passed" if integrity else f"integrity check failed: {affected or 'invalid evidence'}",
        ))
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        gates.append(_failed_gate(
            "integrity_checks", "all checks true", f"invalid integrity evidence: {exc}"
        ))

    try:
        folds = _fold_results(outer, holdout)
        observed = {
            row["fold"]: row["predictive_metrics"]["roc_auc"] for row in folds
        }
        affected = next((
            name for name, value in observed.items()
            if not _finite_number(value) or float(value) <= 0.50
        ), None)
        passed = affected is None
        gates.append(_gate_record(
            "auc_above_chance_each_fold", passed, observed, "> 0.50 each fold",
            affected, "every fold AUC exceeds chance" if passed else f"AUC did not exceed chance: {affected}",
        ))
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        gates.append(_failed_gate(
            "auc_above_chance_each_fold", "> 0.50 each fold", f"invalid fold AUC evidence: {exc}"
        ))

    try:
        folds = _fold_results(outer, holdout)
        observed = {
            row["fold"]: row["cost_metrics"][5]["total_return"] for row in folds
        }
        affected = next((
            name for name, value in observed.items()
            if not _finite_number(value) or float(value) <= 0.0
        ), None)
        passed = affected is None
        gates.append(_gate_record(
            "positive_5bps_each_fold", passed, observed, "> 0 each fold", affected,
            "every fold is profitable at 5 bp" if passed else f"non-positive 5 bp return: {affected}",
        ))
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        gates.append(_failed_gate(
            "positive_5bps_each_fold", "> 0 each fold", f"invalid 5 bp evidence: {exc}"
        ))

    try:
        bootstrap = holdout["bootstrap"]
        p05 = bootstrap["p05"]
        passed = (
            bootstrap.get("samples") == 1000
            and bootstrap.get("block_days") == 5
            and _finite_number(p05)
            and float(p05) > 0.0
        )
        gates.append(_gate_record(
            "positive_bootstrap_lower_bound", passed, bootstrap,
            {"samples": 1000, "block_days": 5, "p05": "> 0"},
            None if passed else "holdout",
            "bootstrap lower bound is positive" if passed else "invalid or non-positive holdout bootstrap lower bound",
        ))
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        gates.append(_failed_gate(
            "positive_bootstrap_lower_bound", "1000 five-day samples and p05 > 0",
            f"invalid bootstrap evidence: {exc}", affected_fold="holdout",
        ))

    try:
        shuffled = attack_map["label_shuffle"]
        rows = shuffled["metrics"]
        aucs = np.asarray([row["roc_auc"] for row in rows], dtype=float)
        returns = np.asarray([row["return_5bps"] for row in rows], dtype=float)
        seeds = [row["seed"] for row in rows]
        maximum = float(aucs.max()) if len(aucs) else float("nan")
        median = float(np.median(returns)) if len(returns) else float("nan")
        holdout_auc = holdout["predictive_metrics"]["roc_auc"]
        summary_matches = (
            _finite_number(shuffled.get("max_auc"))
            and _finite_number(shuffled.get("median_return_5bps"))
            and np.isclose(shuffled["max_auc"], maximum, rtol=0.0, atol=1e-12)
            and np.isclose(shuffled["median_return_5bps"], median, rtol=0.0, atol=1e-12)
        )
        passed = (
            len(rows) == 20
            and seeds == list(range(42, 62))
            and np.isfinite(aucs).all()
            and np.isfinite(returns).all()
            and _finite_number(holdout_auc)
            and summary_matches
            and shuffled.get("passed") is True
            and float(holdout_auc) > maximum
            and median <= 0.0
        )
        observed = {
            "permutations": len(rows), "seeds": seeds,
            "holdout_auc": holdout_auc, "max_shuffled_auc": maximum,
            "median_shuffled_return_5bps": median,
        }
        gates.append(_gate_record(
            "label_shuffle", passed, observed,
            "20 seeds 42..61; holdout AUC > max shuffled AUC; median shuffled return <= 0",
            None if passed else "holdout",
            "shuffled labels failed to reproduce the baseline" if passed else "label shuffle remained profitable, predictive, incomplete, or invalid",
        ))
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        gates.append(_failed_gate(
            "label_shuffle", "20 hostile permutations rejected",
            f"invalid label shuffle evidence: {exc}", affected_fold="holdout",
        ))

    try:
        baseline_auc = holdout["predictive_metrics"]["roc_auc"]
        baseline_return = holdout["cost_metrics"][5]["total_return"]
        observed = {}
        passed = all(
            _finite_number(value) for value in (baseline_auc, baseline_return)
        )
        for attack_id in ("noise_features", "calendar_features"):
            attack = attack_map[attack_id]
            auc_gain = attack["roc_auc"] - baseline_auc
            return_gain = attack["return_5bps"] - baseline_return
            observed[attack_id] = {
                "auc_gain": auc_gain,
                "return_5bps_gain": return_gain,
            }
            passed &= bool(
                attack.get("passed") is True
                and _finite_number(attack["roc_auc"])
                and _finite_number(attack["return_5bps"])
                and auc_gain <= 0.01 + 1e-12
                and return_gain <= 0.05 + 1e-12
            )
        gates.append(_gate_record(
            "feature_attacks", passed, observed,
            "AUC gain <= 0.01 and 5 bp return gain <= 0.05",
            None if passed else "holdout",
            "feature attacks stayed below suspicion limits" if passed else "noise/calendar attack exceeded limits or changed the candidate",
        ))
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        gates.append(_failed_gate(
            "feature_attacks", "AUC gain <= 0.01 and return gain <= 0.05",
            f"invalid feature attack evidence: {exc}", affected_fold="holdout",
        ))

    symbol_rows = None
    symbol_evidence_valid = False
    try:
        eligible_source = context.get("eligible_symbols")
        if eligible_source is None:
            eligible_source = context["partitions"]["eligible_symbols"]
        eligible = tuple(eligible_source)
    except (AttributeError, KeyError, TypeError):
        eligible = tuple(context.get("eligible_symbols", ())) if isinstance(context, dict) else ()
    try:
        symbol_rows = holdout["symbol_metrics"]
        symbol_rows = symbol_rows[symbol_rows["cost_bps"].eq(5)]
        symbol_rows = symbol_rows[symbol_rows["symbol"].isin(eligible)]
        symbol_evidence_valid = (
            bool(eligible)
            and len(set(eligible)) == len(eligible)
            and len(symbol_rows) == len(eligible)
            and not symbol_rows["symbol"].duplicated().any()
            and set(symbol_rows["symbol"]) == set(eligible)
            and symbol_rows["total_return"].map(_finite_number).all()
        )
        fraction = float(symbol_rows["total_return"].gt(0.0).mean()) if symbol_evidence_valid else float("nan")
        passed = symbol_evidence_valid and fraction >= 0.50
        gates.append(_gate_record(
            "positive_symbol_fraction", passed,
            {"eligible_symbols": len(eligible), "positive_fraction": fraction},
            ">= 0.50", None if passed else "holdout",
            "at least half of eligible symbols are positive" if passed else "too few eligible symbols have positive 5 bp return",
        ))
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        gates.append(_failed_gate(
            "positive_symbol_fraction", ">= 0.50", f"invalid symbol evidence: {exc}", affected_fold="holdout",
        ))

    try:
        positive = symbol_rows.loc[symbol_rows["total_return"] > 0.0, "total_return"]
        total = float(positive.sum())
        concentration = float(positive.nlargest(5).sum() / total) if total > 0.0 else float("nan")
        passed = (
            symbol_evidence_valid
            and len(symbol_rows) == len(eligible)
            and np.isfinite(concentration)
            and concentration <= 0.50 + 1e-12
        )
        gates.append(_gate_record(
            "positive_symbol_concentration", passed,
            {"positive_symbols": int(len(positive)), "top_five_fraction": concentration},
            "top five <= 0.50", None if passed else "holdout",
            "positive contribution is not top-five dominated" if passed else "top five symbols dominate positive contribution",
        ))
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        gates.append(_failed_gate(
            "positive_symbol_concentration", "top five <= 0.50",
            f"invalid concentration evidence: {exc}", affected_fold="holdout",
        ))

    try:
        folds = _fold_results(outer, holdout)
        observed = {
            row["fold"]: {
                "total_return": row["cost_metrics"][10]["total_return"],
                "max_drawdown": row["cost_metrics"][10]["max_drawdown"],
            }
            for row in folds
        }
        affected = next((
            name for name, values in observed.items()
            if not all(_finite_number(value) for value in values.values())
            or values["total_return"] <= -0.10
            or values["max_drawdown"] >= 0.20
        ), None)
        passed = affected is None
        gates.append(_gate_record(
            "ten_bps_resilience", passed, observed,
            "return > -0.10 and drawdown < 0.20 each fold", affected,
            "all folds withstand 10 bp costs" if passed else f"10 bp resilience failed: {affected}",
        ))
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        gates.append(_failed_gate(
            "ten_bps_resilience", "return > -0.10 and drawdown < 0.20 each fold",
            f"invalid 10 bp evidence: {exc}",
        ))

    try:
        folds = _fold_results(outer, holdout)
        costs = (0, 2, 5, 10, 20)
        observed = {
            row["fold"]: [row["cost_metrics"][cost]["total_return"] for cost in costs]
            for row in folds
        }
        identity_columns = [
            "symbol", "decision_time", "entry_time", "exit_time", "direction",
            "entry_open", "exit_open",
        ]
        trade_signatures = {}
        identical_trades = True
        for row in folds:
            fold_signatures = {}
            for cost in costs:
                trades = row["trades"][cost]
                if not isinstance(trades, pd.DataFrame) or trades.empty:
                    raise ValueError("trade identity must be a non-empty data frame")
                identity = trades.loc[:, identity_columns].copy()
                if identity.isna().any().any():
                    raise ValueError("trade identity contains nulls")
                for column in ("decision_time", "entry_time", "exit_time"):
                    identity[column] = _parse_trade_time(identity[column])
                for column in ("direction", "entry_open", "exit_open"):
                    identity[column] = pd.to_numeric(identity[column], errors="coerce")
                    if not np.isfinite(identity[column]).all():
                        raise ValueError("trade identity contains non-finite values")
                identity["symbol"] = identity["symbol"].astype("string")
                identity = identity.sort_values(
                    identity_columns, kind="stable"
                ).reset_index(drop=True)
                hashes = pd.util.hash_pandas_object(
                    identity, index=False, categorize=True
                ).to_numpy(dtype="<u8")
                fold_signatures[cost] = {
                    "count": int(len(identity)),
                    "sha256": hashlib.sha256(hashes.tobytes()).hexdigest(),
                }
            reference = fold_signatures[costs[0]]
            identical_trades &= all(
                signature == reference for signature in fold_signatures.values()
            )
            trade_signatures[row["fold"]] = fold_signatures
        affected = next((
            name for name, values in observed.items()
            if not all(_finite_number(value) for value in values)
            or any(left < right for left, right in zip(values, values[1:]))
        ), None)
        if affected is None and not identical_trades:
            affected = "trade_identity"
        passed = affected is None
        observed = {
            "returns": observed,
            "trade_signatures": trade_signatures,
            "identical_trades": identical_trades,
        }
        gates.append(_gate_record(
            "cost_monotonicity", passed, observed,
            "0/2/5/10/20 bp returns monotonically non-increasing", affected,
            "identical-trade returns decline with costs" if passed else f"cost monotonicity failed: {affected}",
        ))
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        gates.append(_failed_gate(
            "cost_monotonicity", "0/2/5/10/20 bp non-increasing",
            f"invalid cost evidence: {exc}",
        ))
    return gates


ACCEPTANCE_GATE_IDS = (
    "integrity_checks", "auc_above_chance_each_fold",
    "positive_5bps_each_fold", "positive_bootstrap_lower_bound",
    "label_shuffle", "feature_attacks", "positive_symbol_fraction",
    "positive_symbol_concentration", "ten_bps_resilience",
    "cost_monotonicity",
)
GATE_FIELDS = {
    "id", "passed", "observed", "required", "affected_fold", "reason",
}


def research_status(gates):
    required = set(ACCEPTANCE_GATE_IDS)
    return (
        "RESEARCH_ACCEPTED"
        if isinstance(gates, (list, tuple))
        and len(gates) == len(required)
        and {gate.get("id") for gate in gates if isinstance(gate, dict)} == required
        and all(isinstance(gate, dict) and gate.get("passed") is True for gate in gates)
        else "RESEARCH_REJECTED"
    )


def _is_sha256(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _source_manifest(rows):
    manifest = sorted(
        ({
            "symbol": str(row["symbol"]),
            "source_path": str(row["source_path"]),
            "source_sha256": str(row["source_sha256"]),
        } for row in rows),
        key=lambda row: (row["symbol"], row["source_path"], row["source_sha256"]),
    )
    if (
        not manifest
        or any(
            not row["symbol"]
            or not row["source_path"]
            or not _is_sha256(row["source_sha256"])
            for row in manifest
        )
    ):
        raise ResearchRejected("invalid canonical source manifest")
    encoded = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return manifest, hashlib.sha256(encoded).hexdigest()


def _finite_evidence(value):
    if type(value) is dict:
        return all(
            type(key) is str and _finite_evidence(item)
            for key, item in value.items()
        )
    if type(value) is list:
        return all(_finite_evidence(item) for item in value)
    if type(value) in {str, bool}:
        return True
    if type(value) in {int, float}:
        return bool(np.isfinite(value))
    return False


def _validate_gate_bundle(status, gates, label):
    if status not in {"RESEARCH_ACCEPTED", "RESEARCH_REJECTED"}:
        raise RuntimeError(f"{label} gate bundle has invalid status")
    if not isinstance(gates, (list, tuple)) or not gates:
        raise RuntimeError(f"{label} gate bundle must be a non-empty sequence")
    if any(not isinstance(gate, dict) or set(gate) != GATE_FIELDS for gate in gates):
        raise RuntimeError(f"{label} gate bundle has invalid fields")
    for gate in gates:
        if (
            type(gate["passed"]) is not bool
            or not isinstance(gate["id"], str)
            or not isinstance(gate["reason"], str)
            or not gate["reason"]
            or gate["required"] is None
            or (gate["affected_fold"] is not None and not isinstance(
                gate["affected_fold"], str
            ))
            or not _finite_evidence(gate["observed"])
            or not _finite_evidence(gate["required"])
        ):
            raise RuntimeError(f"{label} gate bundle has invalid evidence")
    ids = [gate["id"] for gate in gates]
    if "RUN_PRECONDITION" in ids:
        if (
            ids != ["RUN_PRECONDITION"]
            or status != "RESEARCH_REJECTED"
            or gates[0]["passed"] is not False
        ):
            raise RuntimeError(f"{label} gate bundle mixes run preconditions")
        return
    if len(ids) != len(ACCEPTANCE_GATE_IDS) or set(ids) != set(ACCEPTANCE_GATE_IDS):
        raise RuntimeError(f"{label} gate bundle must contain ten exact unique gates")
    expected = (
        "RESEARCH_ACCEPTED"
        if all(gate["passed"] is True for gate in gates)
        else "RESEARCH_REJECTED"
    )
    if status != expected:
        raise RuntimeError(f"{label} gate bundle contradicts status")


def _validate_official_bundle(official):
    if not isinstance(official, dict):
        raise TypeError("official adversarial result must be a dictionary")
    if set(official) != {"attacks", "gates", "status"}:
        raise RuntimeError("official adversarial result has invalid fields")
    attacks = official["attacks"]
    if not isinstance(attacks, (list, tuple)) or any(
        not isinstance(attack, dict) or not isinstance(attack.get("id"), str)
        for attack in attacks
    ):
        raise TypeError("official adversarial attacks must be records")
    attack_ids = [attack["id"] for attack in attacks]
    if (
        len(attack_ids) != len(ATTACK_EVIDENCE)
        or set(attack_ids) != set(ATTACK_EVIDENCE)
    ):
        raise RuntimeError(
            "official adversarial attacks must contain five exact unique IDs"
        )
    _validate_gate_bundle(
        official["status"], official["gates"], "official adversarial"
    )


REPORT_FILES = (
    "report.md", "report.json", "data_quality.csv", "fold_metrics.csv",
    "symbol_metrics.csv", "trades.csv",
)
CSV_COLUMNS = {
    "data_quality.csv": ("run_id", "symbol", "status", "reason"),
    "fold_metrics.csv": (
        "run_id", "evaluation_kind", "fold", "cost_bps", "total_return",
        "trade_count", "trade_sleeve_pnl",
    ),
    "symbol_metrics.csv": (
        "run_id", "fold", "symbol", "cost_bps", "total_return",
    ),
    "trades.csv": (
        "run_id", "fold", "symbol", "cost_bps", "decision_time",
        "entry_time", "exit_time", "sleeve_pnl",
    ),
}
DISCLAIMER = "加权指数研究回测，不代表可成交合约或实盘收益"
LIMITATIONS = (
    DISCLAIMER,
    "仅用于离线研究；不是可执行策略、合约仿真或实盘收益证据。",
)


def _json_safe(value):
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, pd.DataFrame):
        return _json_safe(value.to_dict("records"))
    if isinstance(value, pd.Series):
        return _json_safe(value.tolist())
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, pd.Index, np.ndarray)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, pd.Timedelta):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _records(frame):
    if frame is None:
        return []
    if isinstance(frame, pd.DataFrame):
        return _json_safe(frame.to_dict("records"))
    if isinstance(frame, (list, tuple)):
        return _json_safe(list(frame))
    raise ResearchRejected("report table must be records or a data frame")


def _file_sha256(path):
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _git_provenance():
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--short"],
            cwd=Path(__file__).resolve().parents[1],
            check=True, capture_output=True, text=True,
        ).stdout.splitlines()
        return {
            "git_head": head or None,
            "git_dirty": bool(status),
            "git_status": status,
        }
    except (OSError, subprocess.CalledProcessError):
        return {"git_head": None, "git_dirty": None, "git_status": []}


def _config_json(config):
    return json.dumps(
        asdict(config), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )


def _parse_config_json(value):
    def reject_constant(constant):
        raise ValueError(f"non-standard JSON constant: {constant}")

    data = json.loads(value, parse_constant=reject_constant)
    if not isinstance(data, dict):
        raise TypeError("--config-json must contain one JSON object")
    for name in ("thresholds", "costs_bps"):
        if name in data:
            if not isinstance(data[name], (list, tuple)):
                raise TypeError(f"{name} must be a JSON array")
            data[name] = tuple(data[name])
    try:
        return ResearchConfig(**data)
    except TypeError as exc:
        raise TypeError(f"invalid research config: {exc}") from exc


def _replay_command(db_path, output_dir, config):
    argv = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--db-path", str(Path(db_path).resolve()),
        "--output-dir", str(Path(output_dir).resolve()),
        "--config-json", _config_json(config),
    ]
    return argv, shlex.join(argv)


def _fold_rows(base):
    return [*base.get("outer_results", ()), base.get("holdout", {})]


def _report_tables(context):
    base = context["base"]
    fold_metrics = []
    trades = []
    cutoffs = {}
    for fold_result in _fold_rows(base):
        if not fold_result:
            continue
        fold = fold_result["fold"]
        cutoffs[fold] = _json_safe(fold_result.get("split_cutoffs", {}))
        candidate = fold_result.get("candidate")
        common = {
            "evaluation_kind": "base", "fold": fold,
            "model_name": getattr(candidate, "model_name", fold_result.get("model_name")),
            "threshold": getattr(candidate, "threshold", fold_result.get("threshold")),
            **fold_result.get("sample_counts", {}),
            **fold_result.get("predictive_metrics", {}),
        }
        for cost, metrics in fold_result.get("cost_metrics", {}).items():
            ledger = fold_result.get("trades", {}).get(cost, pd.DataFrame())
            fold_metrics.append({
                **common, "cost_bps": cost, **metrics,
                "trade_count": int(len(ledger)),
                "trade_sleeve_pnl": (
                    float(ledger["sleeve_pnl"].sum())
                    if "sleeve_pnl" in ledger else 0.0
                ),
            })
            for row in _records(ledger):
                trades.append({**row, "fold": fold, "cost_bps": cost})
        for name, benchmark in fold_result.get("benchmarks", {}).items():
            for cost, metrics in benchmark.get("cost_metrics", {}).items():
                ledger = benchmark.get("trades", {}).get(cost, pd.DataFrame())
                fold_metrics.append({
                    "evaluation_kind": "benchmark", "benchmark": name,
                    "fold": fold, "cost_bps": cost,
                    **benchmark.get("predictive_metrics", {}), **metrics,
                    "trade_count": int(len(ledger)),
                    "trade_sleeve_pnl": (
                        float(ledger["sleeve_pnl"].sum())
                        if "sleeve_pnl" in ledger else 0.0
                    ),
                })
        inner = fold_result.get("inner_scores")
        for row in _records(inner):
            fold_metrics.append({
                "evaluation_kind": "inner", "selection_scope": fold, **row,
                "cost_bps": 5,
            })
    for row in _records(base.get("final_inner_scores")):
        fold_metrics.append({
            "evaluation_kind": "inner", "selection_scope": "holdout", **row,
            "cost_bps": 5,
        })
    for attack in context.get("attacks", ()):
        if attack.get("id") == "label_shuffle":
            for row in attack.get("metrics", ()):
                fold_metrics.append({
                    "evaluation_kind": "adversarial", "fold": "holdout",
                    "attack": attack["id"], "cost_bps": 5, **row,
                })
        else:
            fold_metrics.append({
                "evaluation_kind": "adversarial", "fold": "holdout",
                "attack": attack.get("id"), "passed": attack.get("passed"),
                "roc_auc": attack.get("roc_auc"), "cost_bps": 5,
                "total_return": attack.get("return_5bps"),
                "reason": attack.get("reason"),
            })
    holdout = base.get("holdout", {})
    return {
        "cutoffs": cutoffs,
        "data_quality": _records(context.get("quality", pd.DataFrame()).reset_index()),
        "fold_metrics": _json_safe(fold_metrics),
        "symbol_metrics": _records(holdout.get("symbol_metrics")),
        "trades": _json_safe(trades),
    }


def build_adversarial_context(
    run_id, bars, segmented, quality, dataset, partitions, base,
    config=ResearchConfig(),
):
    """Collect immutable run evidence; the official attack entry remains trusted."""
    manifest, manifest_hash = _source_manifest(
        bars.attrs.get("source_manifest", ())
    )
    return {
        "run_id": run_id,
        "bars": bars,
        "segmented": segmented,
        "quality": quality,
        "dataset": dataset,
        "partitions": partitions,
        "base": base,
        "config": config,
        "checks": {"structural": True, "causal": True, "ledger": True},
        "provenance": {
            "source_sha256": dict(bars.attrs.get("source_sha256", {})),
            "source_manifest": manifest,
            "source_manifest_sha256": manifest_hash,
            "bar_data_sha256": _canonical_attack_frame(bars)["sha256"],
        },
    }


def _metric_summary(base):
    rows = []
    for fold in _fold_rows(base):
        if not fold:
            continue
        rows.append({
            "fold": fold.get("fold"),
            "sample_counts": fold.get("sample_counts", {}),
            "predictive_metrics": fold.get("predictive_metrics", {}),
            "cost_metrics": fold.get("cost_metrics", {}),
            "bootstrap": fold.get("bootstrap"),
            "model_identity": fold.get("model_identity"),
            "model_parameters": fold.get("model_parameters", {}),
        })
    return _json_safe(rows)


def build_result(context, gates, status):
    _validate_gate_bundle(status, gates, "official result")
    base = context["base"]
    candidate = base.get("final_candidate")
    tables = _report_tables(context)
    return _json_safe({
        "run_id": context["run_id"],
        "status": status,
        "provenance": context.get("provenance", {}),
        "config": asdict(context.get("config", ResearchConfig())),
        "features": FEATURE_COLUMNS,
        "candidates": candidate_names(),
        "seed": context.get("config", ResearchConfig()).seed,
        "selected_candidate": candidate,
        "selection_scores": base.get("final_inner_scores", pd.DataFrame()),
        "metrics": _metric_summary(base),
        "attacks": context.get("attacks", ()),
        "gates": gates,
        "limitations": LIMITATIONS,
        **tables,
    })


def rejected_result(run_id, config, reason):
    return _json_safe({
        "run_id": run_id,
        "status": "RESEARCH_REJECTED",
        "provenance": {},
        "config": asdict(config),
        "features": FEATURE_COLUMNS,
        "candidates": candidate_names(),
        "seed": config.seed,
        "selected_candidate": None,
        "selection_scores": [],
        "cutoffs": {},
        "metrics": [],
        "attacks": [],
        "gates": [{
            "id": "RUN_PRECONDITION", "passed": False, "observed": reason,
            "required": "all run preconditions satisfied", "affected_fold": None,
            "reason": reason,
        }],
        "data_quality": [], "fold_metrics": [], "symbol_metrics": [],
        "trades": [], "limitations": LIMITATIONS,
    })


def _table_frame(result, key, filename):
    rows = _records(result.get(key, ()))
    run_id = str(result["run_id"])
    for row in rows:
        if "run_id" in row and str(row["run_id"]) != run_id:
            raise ResearchRejected(f"{filename} contains another run ID")
        row["run_id"] = run_id
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=CSV_COLUMNS[filename])
    columns = ["run_id", *[column for column in frame if column != "run_id"]]
    return frame.loc[:, columns]


def _spreadsheet_safe(value):
    if isinstance(value, str):
        candidate = value.lstrip(" ")
        if candidate and candidate[0] in "=+-@\t\r\n":
            return "'" + value
    return value


def _canonical_output_path(output_dir):
    supplied = Path(output_dir).expanduser()
    if ".." in supplied.parts:
        raise ValueError("output directory cannot contain parent traversal")
    output = Path(os.path.abspath(supplied))
    current = Path(output.anchor)
    for part in output.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError(f"output directory ancestor is a symlink: {current}")
    if output.name in {"", ".", ".."}:
        raise ValueError("output directory must be explicit")
    return output


def _markdown_report(payload):
    lines = [
        f"# {payload['status']}", "", DISCLAIMER, "",
        f"Run ID: `{payload['run_id']}`", "", "## Data exclusions", "",
    ]
    quality = payload.get("data_quality", ())
    lines.extend(
        f"- {row.get('symbol')}: {row.get('status')} {row.get('reason') or ''}".rstrip()
        for row in quality
    )
    if not quality:
        lines.append("- None recorded")
    lines.extend(["", "## Split cutoffs", ""])
    lines.extend(
        f"- {fold}: `{json.dumps(values, ensure_ascii=False, sort_keys=True)}`"
        for fold, values in payload.get("cutoffs", {}).items()
    )
    if not payload.get("cutoffs"):
        lines.append("- Not reached")
    lines.extend([
        "", "## Selected candidate", "",
        f"`{json.dumps(payload.get('selected_candidate'), ensure_ascii=False, sort_keys=True)}`",
        "", "## Cost tables", "",
    ])
    cost_rows = [
        row for row in payload.get("fold_metrics", ())
        if row.get("cost_bps") is not None
    ]
    lines.extend(
        "- {evaluation_kind}/{fold}/{cost_bps} bp: return={total_return}".format(
            evaluation_kind=row.get("evaluation_kind"), fold=row.get("fold"),
            cost_bps=row.get("cost_bps"), total_return=row.get("total_return"),
        )
        for row in cost_rows
    )
    if not cost_rows:
        lines.append("- Not reached")
    concentration = next((
        gate for gate in payload.get("gates", ())
        if gate.get("id") == "positive_symbol_concentration"
    ), None)
    lines.extend([
        "", "## Per-symbol concentration", "",
        f"`{json.dumps(concentration, ensure_ascii=False, sort_keys=True)}`",
        "", "## Adversarial checks", "",
    ])
    lines.extend(
        f"- {row.get('id')}: {row.get('reason') or row.get('passed')}"
        for row in payload.get("attacks", ())
    )
    if not payload.get("attacks"):
        lines.append("- Not reached")
    lines.extend(["", "## Gates", ""])
    lines.extend(
        f"- {row.get('id')}: passed={row.get('passed')}; reason={row.get('reason')}"
        for row in payload.get("gates", ())
    )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in payload.get("limitations", LIMITATIONS))
    return "\n".join(lines) + "\n"


def _reconcile_report(directory):
    def reject_constant(value):
        raise ValueError(f"non-standard JSON constant: {value}")

    payload = json.loads(
        (directory / "report.json").read_text(encoding="utf-8"),
        parse_constant=reject_constant,
    )
    _validate_gate_bundle(payload.get("status"), payload.get("gates"), "report")
    run_id = str(payload["run_id"])
    for filename, key in (
        ("data_quality.csv", "data_quality"),
        ("fold_metrics.csv", "fold_metrics"),
        ("symbol_metrics.csv", "symbol_metrics"),
        ("trades.csv", "trades"),
    ):
        frame = pd.read_csv(directory / filename, dtype=str, keep_default_na=False)
        if len(frame) != payload["row_counts"][filename]:
            raise ResearchRejected(f"{filename} row count mismatch")
        if len(frame) and set(frame["run_id"]) != {run_id}:
            raise ResearchRejected(f"{filename} run ID mismatch")
        if len(frame) != len(payload[key]):
            raise ResearchRejected(f"{filename} JSON row count mismatch")
    trade_frame = pd.read_csv(
        directory / "trades.csv", dtype=str, keep_default_na=False
    )
    identity = ("run_id", "fold", "symbol", "cost_bps", "decision_time")
    expected = [tuple(
        str(_spreadsheet_safe(row.get(name, ""))) for name in identity
    ) for row in payload["trades"]]
    observed = [tuple(row[name] for name in identity) for _, row in trade_frame.iterrows()]
    if expected != observed:
        raise ResearchRejected("trade JSON/CSV identity mismatch")
    for metric in payload["fold_metrics"]:
        if metric.get("evaluation_kind") != "base":
            continue
        matching = [
            trade for trade in payload["trades"]
            if str(trade.get("fold")) == str(metric.get("fold"))
            and float(trade.get("cost_bps")) == float(metric.get("cost_bps"))
        ]
        pnl = sum(float(trade["sleeve_pnl"]) for trade in matching)
        if (
            len(matching) != int(metric["trade_count"])
            or abs(pnl - float(metric["trade_sleeve_pnl"])) > 1e-12
            or abs(pnl - float(metric["total_return"])) > 1e-12
        ):
            raise ResearchRejected("trade summary mismatch")
    for trade in payload["trades"]:
        cutoff = payload.get("cutoffs", {}).get(str(trade.get("fold")))
        if not cutoff:
            raise ResearchRejected("trade has no fold cutoff")
        decision = pd.Timestamp(trade["decision_time"])
        if not pd.Timestamp(cutoff["evaluation_start"]) <= decision <= pd.Timestamp(
            cutoff["evaluation_end"]
        ):
            raise ResearchRejected("trade falls outside its evaluation domain")
    markdown = (directory / "report.md").read_text(encoding="utf-8")
    if not markdown.startswith(f"# {payload['status']}\n") or DISCLAIMER not in markdown:
        raise ResearchRejected("Markdown status mismatch")


def write_report(result, output_dir):
    _validate_gate_bundle(result.get("status"), result.get("gates"), "report")
    output = _canonical_output_path(output_dir)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise FileExistsError(f"refusing to overwrite report evidence: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        payload = _json_safe(dict(result))
        tables = {}
        for filename, key in (
            ("data_quality.csv", "data_quality"),
            ("fold_metrics.csv", "fold_metrics"),
            ("symbol_metrics.csv", "symbol_metrics"),
            ("trades.csv", "trades"),
        ):
            frame = _table_frame(payload, key, filename)
            csv_frame = frame.apply(lambda column: column.map(_spreadsheet_safe))
            csv_frame.to_csv(temporary / filename, index=False)
            records = _json_safe(frame.to_dict("records"))
            payload[key] = records
            tables[filename] = len(records)
        payload["row_counts"] = tables
        (temporary / "report.json").write_text(
            json.dumps(
                payload, ensure_ascii=False, indent=2, sort_keys=True,
                allow_nan=False,
            ) + "\n",
            encoding="utf-8",
        )
        (temporary / "report.md").write_text(
            _markdown_report(payload), encoding="utf-8"
        )
        _reconcile_report(temporary)
        if output.exists():
            output.rmdir()
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {name: str(output / name) for name in REPORT_FILES}


def run_research(db_path, output_dir, config=ResearchConfig()):
    run_id = uuid.uuid4().hex
    command_argv, command = _replay_command(db_path, output_dir, config)
    git = _git_provenance()
    provenance = {
        "database_sha256": _file_sha256(db_path),
        "database_path": str(Path(db_path).resolve()),
        "output_path": str(Path(output_dir).resolve()),
        "cwd": str(Path.cwd().resolve()),
        "module_sha256": _file_sha256(Path(__file__).resolve()),
        "code_revision": git["git_head"],
        **git,
        "command_argv": command_argv,
        "command": command,
    }
    try:
        bars = load_futures_bars(db_path)
        segmented, quality = validate_and_segment(bars, config)
        dataset = build_causal_dataset(segmented, config)
        eligible = dataset.groupby("symbol").size()
        eligible = eligible[eligible >= config.min_symbol_rows].index
        dataset = dataset[dataset["symbol"].isin(eligible)].copy()
        if len(eligible) < config.min_symbols:
            raise ResearchRejected("too few eligible symbols")
        partitions = make_temporal_partitions(dataset, config)
        eligible = pd.Index(partitions["eligible_symbols"])
        dataset = dataset[dataset["symbol"].isin(eligible)].copy()
        if len(eligible) < config.min_symbols:
            raise ResearchRejected("too few fold-eligible symbols")
        base = build_base_evaluation(dataset, segmented, partitions, config)
        context = build_adversarial_context(
            run_id, bars, segmented, quality, dataset, partitions, base, config
        )
        context["provenance"].update(provenance)
        official = run_adversarial_checks(
            base, bars, dataset, segmented, partitions, context["checks"], config
        )
        _validate_official_bundle(official)
        context["attacks"] = official["attacks"]
        gates = official["gates"]
        status = official["status"]
        result = build_result(context, gates, status)
    except ResearchRejected as exc:
        result = rejected_result(run_id, config, str(exc))
        result["provenance"].update(provenance)
    result["artifacts"] = write_report(result, output_dir)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config-json", default="{}")
    args = parser.parse_args(argv)
    try:
        result = run_research(
            args.db_path, args.output_dir, _parse_config_json(args.config_json)
        )
    except (RuntimeError, TypeError) as exc:
        print(json.dumps({
            "status": "INTERNAL_ERROR", "error": str(exc),
        }, ensure_ascii=False, allow_nan=False), file=sys.stderr)
        return 1
    print(json.dumps({
        "status": result["status"],
        "run_id": result["run_id"],
        "artifacts": result["artifacts"],
    }, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result["status"] == "RESEARCH_ACCEPTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
