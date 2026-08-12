from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from numbers import Real
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

    scored_required = {
        "symbol", "segment_id", "decision_time", "entry_time", "entry_open",
        "exit_time", "exit_open", "probability",
    }
    market_required = {"symbol", "segment_id", "trade_time", "open", "close"}
    missing = scored_required.difference(scored.columns)
    if missing:
        raise ResearchRejected(f"missing scored columns: {', '.join(sorted(missing))}")
    if scored.empty:
        return pd.DataFrame(columns=trade_columns), pd.DataFrame(columns=daily_columns)
    missing = market_required.difference(market.columns)
    if missing:
        raise ResearchRejected(f"missing market columns: {', '.join(sorted(missing))}")
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
        key: group.sort_values("trade_time", kind="stable").set_index("trade_time", drop=False)
        for key, group in marks.groupby(["symbol", "segment_id"], sort=False)
    }

    decisions = decisions.sort_values(
        ["entry_time", "symbol", "decision_time"], kind="stable"
    ).reset_index(drop=True)
    sleeve_cash = {symbol: 1.0 / symbol_count for symbol in symbols}
    available_after = {}
    trades = []
    accepted_paths = []
    for row in decisions.itertuples(index=False):
        group = market_groups.get((row.symbol, row.segment_id))
        if group is None:
            raise ResearchRejected("scored segment is missing from market")
        try:
            decision_position = group.index.get_loc(row.decision_time)
            entry_position = group.index.get_loc(row.entry_time)
            exit_position = group.index.get_loc(row.exit_time)
        except KeyError as exc:
            raise ResearchRejected("trade path is missing segmented market marks") from exc
        if entry_position != decision_position + 1:
            raise ResearchRejected("entry_time must be the first bar after decision")
        if exit_position <= entry_position:
            raise ResearchRejected("exit must follow entry")
        path = group.iloc[entry_position:exit_position + 1]
        if path["trade_time"].diff().dropna().ne(pd.Timedelta(minutes=5)).any():
            raise ResearchRejected("trade path is missing segmented market marks")

        terminal_close = pd.isna(row.exit_open)
        exit_open = float(row.terminal_open) if terminal_close else float(row.exit_open)
        if terminal_close and row.exit_time != group.index[-1]:
            raise ResearchRejected("terminal close is not the final segment open")
        if (
            not np.isclose(float(row.entry_open), float(path["open"].iloc[0]), rtol=0.0, atol=1e-12)
            or not np.isclose(exit_open, float(path["open"].iloc[-1]), rtol=0.0, atol=1e-12)
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
        accepted_paths.append((trade, path))
        sleeve_cash[row.symbol] = end_equity
        available_after[row.symbol] = row.exit_time

    trade_frame = pd.DataFrame(trades, columns=trade_columns)
    if trade_frame.empty:
        return trade_frame, pd.DataFrame(columns=daily_columns)

    unused_cash = 1.0 - len(symbols) / symbol_count
    events = []
    for trade, path in accepted_paths:
        for bar in path.itertuples(index=False):
            is_entry = bar.trade_time == trade["entry_time"]
            is_exit = bar.trade_time == trade["exit_time"]
            sleeve_value = (
                trade["sleeve_end_equity"]
                if is_exit
                else trade["sleeve_start_equity"] * (
                    1.0 - trade["entry_cost"]
                    + trade["direction"] * (float(bar.close) / trade["entry_open"] - 1.0)
                )
            )
            events.append({
                "trade_time": bar.trade_time,
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
    event_frame = pd.DataFrame(events).sort_values("trade_time", kind="stable")
    for timestamp, timestamp_events in event_frame.groupby("trade_time", sort=True):
        for event in timestamp_events.itertuples(index=False):
            sleeve_values[event.symbol] = float(event.sleeve_value)
            gross_exposure += float(event.exposure_delta)
        sleeve_equity = sum(sleeve_values.values())
        equity = unused_cash + sleeve_equity
        if not np.isfinite(equity) or equity <= 0.0:
            raise ResearchRejected("non-positive portfolio equity")
        if gross_exposure < -1e-12 or gross_exposure > 1.0 + 1e-12:
            raise ResearchRejected("invalid gross exposure")
        timestamp_rows.append({
            "trade_time": timestamp,
            "equity": equity,
            "gross_exposure": gross_exposure,
            "turnover": float(timestamp_events["turnover"].sum()),
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
