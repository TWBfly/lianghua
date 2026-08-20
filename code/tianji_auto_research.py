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


def select_stage1_survivors(rows):
    return rows.sort_values(
        ["worst_payoff", "worst_return", "turnover", "signal_id"],
        ascending=[False, False, True, True],
        kind="stable",
    ).head(4).reset_index(drop=True)


def stage1_screen(signals, folds, evaluate):
    proxy = RiskSpec(2, 16, 0.20, 1.0, 3.0, 3.0)
    rows = []
    for signal in sorted(signals):
        candidate = CandidateSpec(signal, proxy)
        fold_rows = [
            evaluate(candidate, number)
            for number in range(1, len(folds) + 1)
        ]
        rows.append({
            "signal_id": signal.id,
            "worst_payoff": min(
                row["payoff_ratio"] for row in fold_rows
            ),
            "worst_return": min(
                row["total_return"] for row in fold_rows
            ),
            "turnover": sum(row["turnover"] for row in fold_rows),
        })
    return select_stage1_survivors(pd.DataFrame(rows))


def _aggregate_stage_rows(*stages):
    frame = pd.DataFrame([
        row for stage in stages for row in stage
    ])
    rows = []
    for candidate_id, group in frame.groupby("candidate_id", sort=True):
        rows.append({
            "candidate_id": candidate_id,
            "fold": int(group["fold"].max()),
            "payoff_ratio": float(group["payoff_ratio"].min()),
            "max_drawdown": float(group["max_drawdown"].max()),
            "total_return": float(
                (1.0 + group["total_return"].astype(float)).prod() - 1.0
            ),
            "trades": int(group["trades"].sum()),
            "turnover": float(group["turnover"].sum()),
        })
    return pd.DataFrame(rows)


def _stage_rank(rows, limit):
    frame = pd.DataFrame(rows)
    projected = frame["trades"] * 3
    frame = frame[
        np.isfinite(frame[[
            "payoff_ratio", "max_drawdown", "total_return",
        ]]).all(axis=1)
        & frame["total_return"].gt(0.0)
        & frame["payoff_ratio"].ge(1.0)
        & frame["max_drawdown"].le(0.15)
        & projected.ge(200)
    ]
    return frame.sort_values(
        [
            "payoff_ratio", "max_drawdown", "total_return", "turnover",
            "candidate_id",
        ],
        ascending=[False, True, False, True, True],
        kind="stable",
    ).head(limit).reset_index(drop=True)


def successive_halving(candidates, evaluate):
    current = tuple(sorted(candidates))[:128]
    stage1 = [evaluate(candidate, 1) for candidate in current]
    keep1 = set(_stage_rank(stage1, 32)["candidate_id"])
    current = tuple(
        candidate for candidate in current if candidate.id in keep1
    )
    stage2 = [evaluate(candidate, 2) for candidate in current]
    aggregate2 = _aggregate_stage_rows(stage1, stage2)
    aggregate2 = aggregate2[
        aggregate2["candidate_id"].isin({candidate.id for candidate in current})
    ]
    keep2 = set(_stage_rank(aggregate2, 8)["candidate_id"])
    current = tuple(
        candidate for candidate in current if candidate.id in keep2
    )
    stage3 = [evaluate(candidate, 3) for candidate in current]
    return {"stage1": stage1, "stage2": stage2, "stage3": stage3}


def auto_development_gates(metrics):
    checks = {
        "payoff_ratio": float(metrics["payoff_ratio"]) >= 3.0,
        "max_drawdown": float(metrics["max_drawdown"]) <= 0.15,
        "positive_return": float(metrics["total_return"]) > 0.0,
        "minimum_trades": int(metrics["trades"]) >= 200,
        "positive_folds": all(
            value > 0.0 for value in metrics["fold_returns"]
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}
