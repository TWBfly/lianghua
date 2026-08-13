from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
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
    return {
        "outer_results": outer_results,
        "final_candidate": final_candidate,
        "final_inner_scores": final_inner_scores,
        "holdout": holdout_result,
    }
