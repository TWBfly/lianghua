from __future__ import annotations

import numpy as np
import pandas as pd

from futures_research_backtest import (
    ResearchRejected,
    TIANJI_REBALANCE_BARS,
    _tianji_leg,
)

CANDIDATES = ("continuation", "reversal", "timeseries_donchian")
FORBIDDEN_HOLDOUT_START = pd.Timestamp("2026-06-26 10:45:00")


def development_folds(times, forbidden_start=FORBIDDEN_HOLDOUT_START):
    times = pd.DatetimeIndex(sorted(pd.DatetimeIndex(times).unique()))
    times = times[times < forbidden_start]
    blocks = np.array_split(times, 4)
    folds = tuple(pd.DatetimeIndex(block) for block in blocks[1:])
    if len(folds) != 3 or any(fold.empty for fold in folds):
        raise ResearchRejected("insufficient TianJi development folds")
    return folds


def candidate_targets(scores, market, candidate, fold_times):
    if candidate not in CANDIDATES:
        raise ResearchRejected("unknown TianJi development candidate")
    required = {
        "decision_time", "symbol", "signal_ready", "score",
        "signed_kaufman_efficiency_20", "donchian_position_20",
        "momentum_acceleration_5_20", "intraday_intensity_10",
        "prior_breakout_up_20", "prior_breakout_down_20", "atr", "atr_pct",
        "sector",
    }
    missing = required.difference(scores.columns)
    if missing:
        raise ResearchRejected(
            f"missing TianJi development columns: {', '.join(sorted(missing))}"
        )
    frame = scores[
        scores["decision_time"].isin(fold_times) & scores["signal_ready"]
    ].copy()
    percentile = frame.groupby("decision_time")["score"].rank(
        pct=True, method="average"
    )
    continuation_long = (
        (percentile >= 0.90)
        & frame["signed_kaufman_efficiency_20"].gt(0.30)
        & frame["donchian_position_20"].gt(0.80)
        & frame["momentum_acceleration_5_20"].gt(0.0)
        & frame["intraday_intensity_10"].gt(0.0)
    )
    continuation_short = (
        (percentile <= 0.10)
        & frame["signed_kaufman_efficiency_20"].lt(-0.30)
        & frame["donchian_position_20"].lt(-0.80)
        & frame["momentum_acceleration_5_20"].lt(0.0)
        & frame["intraday_intensity_10"].lt(0.0)
    )
    if candidate == "continuation":
        long_mask, short_mask = continuation_long, continuation_short
    elif candidate == "reversal":
        long_mask, short_mask = continuation_short, continuation_long
    else:
        long_mask = frame["prior_breakout_up_20"].astype(bool) & continuation_long
        short_mask = frame["prior_breakout_down_20"].astype(bool) & continuation_short

    rows = []
    times = pd.DatetimeIndex(sorted(frame["decision_time"].unique()))
    rebalance_times = times[::TIANJI_REBALANCE_BARS]
    for time in rebalance_times:
        at_time = frame[frame["decision_time"].eq(time)]
        longs = _tianji_leg(
            at_time[long_mask.reindex(at_time.index, fill_value=False)], 1
        )[:2]
        shorts = _tianji_leg(
            at_time[short_mask.reindex(at_time.index, fill_value=False)], -1
        )[:2]
        count = min(len(longs), len(shorts))
        rows.extend(longs[:count])
        rows.extend(shorts[:count])
    targets = pd.DataFrame(rows, columns=(
        "decision_time", "symbol", "direction", "atr", "atr_pct", "score",
        "sector",
    ))
    targets["trail_activation_r"] = 3.0
    return targets, rebalance_times

