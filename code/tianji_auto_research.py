from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from itertools import product

import numpy as np
import pandas as pd

from futures_research_backtest import ResearchRejected, _tianji_leg

FORBIDDEN_HOLDOUT_START = pd.Timestamp("2026-06-26 10:45:00")


@dataclass(frozen=True, order=True)
class SignalSpec:
    orientation: str
    lookback: int
    entry_quantile: float
    confirmations: int

    @property
    def id(self):
        return (
            f"sig-{self.orientation}-l{self.lookback}-"
            f"q{int(self.entry_quantile * 100):02d}-c{self.confirmations}"
        )


@dataclass(frozen=True, order=True)
class RiskSpec:
    top_k: int
    rebalance_bars: int
    side_exposure: float
    initial_stop_atr: float
    trail_activation_r: float
    trail_distance_atr: float

    @property
    def id(self):
        return (
            f"risk-k{self.top_k}-r{self.rebalance_bars}-"
            f"x{int(self.side_exposure * 100):02d}-"
            f"s{self.initial_stop_atr:g}-a{self.trail_activation_r:g}-"
            f"t{self.trail_distance_atr:g}"
        )


@dataclass(frozen=True, order=True)
class CandidateSpec:
    signal: SignalSpec
    risk: RiskSpec

    @property
    def id(self):
        return f"{self.signal.id}__{self.risk.id}"


EXIT_PROFILES = (
    (0.75, 2.0, 2.5),
    (0.75, 3.0, 3.0),
    (1.00, 2.0, 2.5),
    (1.00, 3.0, 3.0),
)


def signal_specs():
    return tuple(sorted(
        SignalSpec(*values)
        for values in product(
            ("continuation", "reversal"),
            (20, 40),
            (0.05, 0.10),
            (2, 3),
        )
    ))


def risk_specs():
    return tuple(sorted(
        RiskSpec(top_k, rebalance, exposure, *profile)
        for top_k, rebalance, exposure, profile in product(
            (1, 2),
            (16, 32),
            (0.20, 0.30),
            EXIT_PROFILES,
        )
    ))


def candidate_specs(signals, risks):
    return tuple(sorted(
        CandidateSpec(signal, risk)
        for signal, risk in product(tuple(signals), tuple(risks))
    ))


def search_space_hash(signals, risks):
    payload = {
        "signals": [asdict(value) for value in sorted(signals)],
        "risks": [asdict(value) for value in sorted(risks)],
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_auto_targets(scores, candidate, fold_times):
    frame = scores[scores["decision_time"].isin(fold_times)].copy()
    if frame["decision_time"].ge(FORBIDDEN_HOLDOUT_START).any():
        raise ResearchRejected("viewed holdout entered automatic targets")
    signal, risk = candidate.signal, candidate.risk
    if signal.lookback == 20:
        columns = (
            "signed_kaufman_efficiency_20", "donchian_position_20",
            "momentum_acceleration_5_20", "intraday_intensity_10",
        )
    else:
        columns = (
            "signed_kaufman_efficiency_40", "donchian_position_40",
            "momentum_acceleration_10_40", "intraday_intensity_20",
        )
    missing = {
        "decision_time", "symbol", "signal_ready", "score", "atr",
        "atr_pct", "sector", *columns,
    }.difference(frame.columns)
    if missing:
        raise ResearchRejected(
            f"missing automatic target columns: {', '.join(sorted(missing))}"
        )
    factor_signs = np.sign(frame.loc[:, columns])
    positive_votes = factor_signs.gt(0).sum(axis=1)
    negative_votes = factor_signs.lt(0).sum(axis=1)
    oriented_score = (
        frame["score"]
        if signal.orientation == "continuation"
        else 1.0 - frame["score"]
    )
    percentile = oriented_score.groupby(frame["decision_time"]).rank(
        pct=True, method="average"
    )
    long_mask = (
        frame["signal_ready"]
        & positive_votes.ge(signal.confirmations)
        & percentile.ge(1.0 - signal.entry_quantile)
    )
    short_mask = (
        frame["signal_ready"]
        & negative_votes.ge(signal.confirmations)
        & percentile.le(signal.entry_quantile)
    )
    if signal.orientation == "reversal":
        long_mask, short_mask = short_mask, long_mask
    rows = []
    times = pd.DatetimeIndex(sorted(frame["decision_time"].unique()))
    rebalances = times[::risk.rebalance_bars]
    for time in rebalances:
        at_time = frame[frame["decision_time"].eq(time)].copy()
        at_time["score"] = oriented_score.loc[at_time.index]
        longs = _tianji_leg(
            at_time[long_mask.reindex(at_time.index, fill_value=False)], 1
        )[:risk.top_k]
        shorts = _tianji_leg(
            at_time[short_mask.reindex(at_time.index, fill_value=False)], -1
        )[:risk.top_k]
        count = min(len(longs), len(shorts))
        rows.extend(longs[:count])
        rows.extend(shorts[:count])
    targets = pd.DataFrame(rows, columns=(
        "decision_time", "symbol", "direction", "atr", "atr_pct", "score",
        "sector",
    ))
    targets["initial_stop_atr"] = risk.initial_stop_atr
    targets["trail_activation_r"] = risk.trail_activation_r
    targets["trail_distance_atr"] = risk.trail_distance_atr
    targets["side_exposure"] = risk.side_exposure
    return targets, rebalances
