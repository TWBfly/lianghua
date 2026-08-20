from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from itertools import product

import pandas as pd

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

