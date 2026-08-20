# TianJi Non-Predictive Automatic Research Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate and evaluate a finite deterministic OHLCV rule space with staged development-only screening, successive halving, robustness attacks, and payoff-3/drawdown-15 hard gates.

**Architecture:** Add `tianji_auto_research.py` for immutable search specs, IDs, staged orchestration, attacks, and selection. Extend the existing feature/ledger module only where automatic candidates need slow factor variants and per-target risk parameters. Add a small CLI writer that atomically emits the full search evidence bundle and refuses overwrite.

**Tech Stack:** Python 3.10, dataclasses, itertools, hashlib, JSON, pandas, NumPy, pytest; no new dependency.

## Global Constraints

- Use verified 5m weighted-index data reconstructed to 15m.
- All search timestamps must be `< 2026-06-26 10:45:00`.
- Runtime rules contain no labels, models, predictions, or probabilities.
- Search grammar is exactly 16 signal specs and 32 risk specs.
- Maximum Stage 2 expansion is 128 candidates; halving caps are 32 then 8.
- 5bps gates: payoff `>=3`, drawdown `<=0.15`, return `>0`, trades `>=200`, every fold return positive.
- The highest status is `AUTO_DEVELOPMENT_CANDIDATE`.
- Search output is development evidence, not final OOS evidence.
- Existing databases and report directories are immutable.

---

### Task 1: Define immutable search grammar, IDs, and hashes

**Files:**
- Create: `code/tianji_auto_research.py`
- Create: `tests/test_tianji_auto_research.py`

**Interfaces:**
- Produces: frozen `SignalSpec`, `RiskSpec`, `CandidateSpec` dataclasses.
- Produces: `signal_specs() -> tuple[SignalSpec, ...]` of length 16.
- Produces: `risk_specs() -> tuple[RiskSpec, ...]` of length 32.
- Produces: `candidate_specs(signals, risks) -> tuple[CandidateSpec, ...]`.
- Produces: `search_space_hash(signals, risks) -> str`.

- [ ] **Step 1: Write failing grammar/hash tests**

```python
import dataclasses
import inspect
import random

import tianji_auto_research as auto


def test_auto_research_grammar_has_exact_stable_counts():
    signals = auto.signal_specs()
    risks = auto.risk_specs()
    assert len(signals) == 16
    assert len(risks) == 32
    assert len({spec.id for spec in signals}) == 16
    assert len({spec.id for spec in risks}) == 32
    assert all(dataclasses.is_dataclass(spec) for spec in (*signals, *risks))


def test_search_hash_and_candidate_ids_ignore_input_order():
    signals = list(auto.signal_specs())
    risks = list(auto.risk_specs())
    expected_hash = auto.search_space_hash(signals, risks)
    expected_ids = sorted(spec.id for spec in auto.candidate_specs(signals, risks))
    random.Random(7).shuffle(signals)
    random.Random(8).shuffle(risks)
    assert auto.search_space_hash(signals, risks) == expected_hash
    assert sorted(spec.id for spec in auto.candidate_specs(signals, risks)) == expected_ids


def test_runtime_search_specs_have_no_predictive_fields():
    fields = {
        field.name
        for cls in (auto.SignalSpec, auto.RiskSpec, auto.CandidateSpec)
        for field in dataclasses.fields(cls)
    }
    assert fields.isdisjoint({"label", "prediction", "probability", "model"})
    assert all(
        token not in inspect.getsource(auto.signal_specs)
        for token in ("label", "predict", "probability")
    )
```

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m pytest -q tests/test_tianji_auto_research.py
```

Expected: collection FAIL because the module does not exist.

- [ ] **Step 3: Implement the exact finite grammar**

```python
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
            ("continuation", "reversal"), (20, 40), (0.05, 0.10), (2, 3)
        )
    ))


def risk_specs():
    return tuple(sorted(
        RiskSpec(top_k, rebalance, exposure, *profile)
        for top_k, rebalance, exposure, profile in product(
            (1, 2), (16, 32), (0.20, 0.30), EXIT_PROFILES
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
```

- [ ] **Step 4: Run grammar tests**

```bash
python3 -m pytest -q tests/test_tianji_auto_research.py
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add code/tianji_auto_research.py tests/test_tianji_auto_research.py
git commit -m "feat: define tianji automatic search grammar"
```

---

### Task 2: Add slow OHLCV primitives and per-target risk semantics

**Files:**
- Modify: `code/futures_research_backtest.py`
- Modify: `tests/test_futures_research_backtest.py`
- Modify: `code/tianji_auto_research.py`
- Modify: `tests/test_tianji_auto_research.py`

**Interfaces:**
- Adds 40-bar KER/Donchian, 10/40 acceleration, and 20-bar intensity to scores.
- Adds optional target fields: `initial_stop_atr`, `trail_activation_r`, `trail_distance_atr`, `side_exposure`.
- Produces: `build_auto_targets(scores, candidate, fold_times) -> (targets, rebalances)`.

- [ ] **Step 1: Write failing slow-factor/risk tests**

```python
def test_tianji_scores_include_causal_slow_primitives():
    market = make_tianji_market(100)
    prefix = market[market["trade_time"] <= market["trade_time"].unique()[80]]
    expected = research.build_tianji_scores(prefix)
    actual = research.build_tianji_scores(market)
    actual = actual[actual["decision_time"] <= prefix["trade_time"].max()]
    for column in (
        "signed_kaufman_efficiency_40", "donchian_position_40",
        "momentum_acceleration_10_40", "intraday_intensity_20",
    ):
        assert column in actual
    pd.testing.assert_frame_equal(
        expected.reset_index(drop=True), actual.reset_index(drop=True)
    )


def test_per_target_stop_and_trail_distance_change_exit_levels():
    market = make_tianji_market(5, symbols=("AG_IDX",))
    market["atr"] = 2.0
    market.loc[2, ["high", "low", "close"]] = [108.0, 100.0, 107.0]
    market.loc[3, ["open", "high", "low", "close"]] = [107.0, 107.5, 101.0, 102.0]
    target = _single_tianji_target(market)
    target[[
        "initial_stop_atr", "trail_activation_r", "trail_distance_atr",
        "side_exposure",
    ]] = [0.75, 2.0, 3.0, 0.20]
    trades, bars, _ = research.simulate_tianji_ledger(
        target, pd.DatetimeIndex([target["decision_time"].item()]), market, 0
    )
    assert trades["exit_open"].iloc[0] == 102.0
    assert bars["gross_exposure"].max() <= 0.20 + 1e-12


def test_auto_target_builder_serializes_risk_spec_and_forbids_holdout():
    scores = auto_score_fixture()
    candidate = auto.CandidateSpec(auto.signal_specs()[0], auto.risk_specs()[0])
    targets, _ = auto.build_auto_targets(
        scores, candidate, pd.DatetimeIndex(scores["decision_time"].unique())
    )
    assert set((
        "initial_stop_atr", "trail_activation_r", "trail_distance_atr",
        "side_exposure",
    )).issubset(targets.columns)
    scores.loc[0, "decision_time"] = auto.FORBIDDEN_HOLDOUT_START
    with pytest.raises(research.ResearchRejected, match="holdout"):
        auto.build_auto_targets(
            scores, candidate, pd.DatetimeIndex(scores["decision_time"].unique())
        )
```

In `tests/test_tianji_auto_research.py`, define:

```python
def auto_score_fixture():
    symbols = (
        "AG_IDX", "AU_IDX", "AL_IDX", "CU_IDX", "RB_IDX", "I_IDX",
        "SC_IDX", "FU_IDX", "MA_IDX", "TA_IDX", "M_IDX", "C_IDX",
        "CF_IDX", "SR_IDX", "IF_IDX", "IC_IDX", "RU_IDX", "SA_IDX",
        "SN_IDX", "ZN_IDX",
    )
    frame = pd.DataFrame({
        "decision_time": pd.Timestamp("2026-01-02 09:00"),
        "symbol": symbols,
        "signal_ready": True,
        "score": np.linspace(0.01, 0.99, len(symbols)),
        "atr": 2.0,
        "atr_pct": 0.02,
        "sector": [research.TIANJI_SECTORS[symbol] for symbol in symbols],
    })
    for column in (
        "signed_kaufman_efficiency_20", "donchian_position_20",
        "momentum_acceleration_5_20", "intraday_intensity_10",
        "signed_kaufman_efficiency_40", "donchian_position_40",
        "momentum_acceleration_10_40", "intraday_intensity_20",
    ):
        frame[column] = np.linspace(-1.0, 1.0, len(frame))
    return frame
```

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py \
  -k 'slow_primitives or per_target_stop'
python3 -m pytest -q tests/test_tianji_auto_research.py \
  -k 'target_builder'
```

Expected: FAIL on missing primitives and optional risk behavior.

- [ ] **Step 3: Implement slow primitives and optional target risk**

In `_tianji_segment_features`, calculate slow primitives with the same causal
operations used for 20-bar fields:

```python
    path_40 = close.diff().abs().rolling(40).sum().replace(0.0, np.nan)
    channel_high_40 = high.rolling(40).max()
    channel_low_40 = low.rolling(40).min()
    span_40 = (channel_high_40 - channel_low_40).replace(0.0, np.nan)
    frame["signed_kaufman_efficiency_40"] = (
        np.sign(close.pct_change(40))
        * (close - close.shift(40)).abs() / path_40
    )
    frame["donchian_position_40"] = (
        2.0 * (close - channel_low_40) / span_40 - 1.0
    )
    frame["momentum_acceleration_10_40"] = (
        close.pct_change(10) - close.pct_change(40) / 4.0
    )
    frame["intraday_intensity_20"] = (
        clv * volume / volume.rolling(40).mean().replace(0.0, np.nan)
    ).rolling(20).mean()
```

Keep these columns in scores without adding them to the existing frozen
`TIANJI_FEATURE_COLUMNS` baseline.

In the ledger, copy optional risk fields from target to pending and position.
Use:

```python
initial_stop_atr = float(order.get("initial_stop_atr", 1.0))
trail_distance_atr = float(order.get("trail_distance_atr", TIANJI_TRAIL_ATR))
side_cap = float(order.get("side_exposure", TIANJI_SIDE_EXPOSURE))
```

The initial stop uses `initial_stop_atr * ATR`, trailing uses
`trail_distance_atr * ATR`, and entry-time capacity uses `side_cap` and
`2 * side_cap`. At rebalance, propagate the same fields from target rows.

Add `build_auto_targets` to `tianji_auto_research.py`. It chooses fast or slow
factor columns from `SignalSpec.lookback`, counts agreeing directional votes,
ranks the oriented score cross-sectionally, selects at most `RiskSpec.top_k`
per side with sector caps, and writes every risk field into each target. It
rejects any score/fold timestamp at or after `FORBIDDEN_HOLDOUT_START`.

Implement it with:

```python
from futures_research_backtest import ResearchRejected, _tianji_leg


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
    factor_signs = np.sign(frame.loc[:, columns])
    positive_votes = factor_signs.gt(0).sum(axis=1)
    negative_votes = factor_signs.lt(0).sum(axis=1)
    oriented_score = (
        frame["score"] if signal.orientation == "continuation"
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
```

- [ ] **Step 4: Run targeted and complete tests**

```bash
python3 -m pytest -q tests/test_tianji_auto_research.py \
  tests/test_futures_research_backtest.py tests/test_qlib_futures_backtest.py
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add code/tianji_auto_research.py tests/test_tianji_auto_research.py \
  code/futures_research_backtest.py tests/test_futures_research_backtest.py
git commit -m "feat: parameterize tianji automatic rule execution"
```

---

### Task 3: Implement Stage 1 screening and deterministic successive halving

**Files:**
- Modify: `code/tianji_auto_research.py`
- Modify: `tests/test_tianji_auto_research.py`

**Interfaces:**
- Produces: `stage1_screen(scores, market, folds) -> pd.DataFrame` with at most four survivors.
- Produces: `successive_halving(candidates, evaluate) -> dict` with stage caps 128/32/8.
- Produces: `auto_development_gates(metrics) -> dict`.

- [ ] **Step 1: Write failing stage/halving/gate tests**

```python
def test_stage1_keeps_at_most_four_with_stable_order():
    rows = pd.DataFrame([
        {"signal_id": f"s{number:02d}", "worst_payoff": number / 10,
         "worst_return": number / 100, "turnover": 20 - number}
        for number in range(16)
    ])
    survivors = auto.select_stage1_survivors(rows)
    assert len(survivors) == 4
    assert survivors["signal_id"].tolist() == ["s15", "s14", "s13", "s12"]


def test_successive_halving_caps_128_to_32_to_8_deterministically():
    signals = auto.signal_specs()[:4]
    candidates = auto.candidate_specs(signals, auto.risk_specs())
    calls = []
    def evaluate(candidate, fold):
        calls.append((candidate.id, fold))
        rank = int(hashlib.sha256(candidate.id.encode()).hexdigest()[:8], 16)
        return {
            "candidate_id": candidate.id, "fold": fold,
            "payoff_ratio": 1.1 + rank % 100 / 100,
            "max_drawdown": 0.05, "total_return": 0.01,
            "trades": 80, "turnover": 10.0,
        }
    result = auto.successive_halving(candidates, evaluate)
    assert len(result["stage1"]) == 128
    assert len(result["stage2"]) == 32
    assert len(result["stage3"]) == 8
    assert len(calls) == 128 + 32 + 8


def test_auto_gates_require_all_hard_thresholds_and_positive_folds():
    metrics = {
        "payoff_ratio": 3.0, "max_drawdown": 0.15,
        "total_return": 0.01, "trades": 200,
        "fold_returns": [0.01, 0.02, 0.01],
    }
    assert auto.auto_development_gates(metrics)["passed"]
    metrics["fold_returns"][1] = 0.0
    assert not auto.auto_development_gates(metrics)["passed"]
```

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m pytest -q tests/test_tianji_auto_research.py \
  -k 'stage1 or successive_halving or auto_gates'
```

Expected: FAIL on missing orchestration functions.

- [ ] **Step 3: Implement stable screening and halving**

```python
def select_stage1_survivors(rows):
    return rows.sort_values(
        ["worst_payoff", "worst_return", "turnover", "signal_id"],
        ascending=[False, False, True, True], kind="stable",
    ).head(4).reset_index(drop=True)


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
        np.isfinite(frame[["payoff_ratio", "max_drawdown", "total_return"]]).all(axis=1)
        & frame["total_return"].gt(0.0)
        & frame["payoff_ratio"].ge(1.0)
        & frame["max_drawdown"].le(0.15)
        & projected.ge(200)
    ]
    return frame.sort_values(
        ["payoff_ratio", "max_drawdown", "total_return", "turnover", "candidate_id"],
        ascending=[False, True, False, True, True], kind="stable",
    ).head(limit).reset_index(drop=True)


def successive_halving(candidates, evaluate):
    current = tuple(sorted(candidates))[:128]
    stage1 = [evaluate(candidate, 1) for candidate in current]
    keep1 = set(_stage_rank(stage1, 32)["candidate_id"])
    current = tuple(candidate for candidate in current if candidate.id in keep1)
    stage2 = [evaluate(candidate, 2) for candidate in current]
    aggregate2 = _aggregate_stage_rows(stage1, stage2)
    aggregate2 = aggregate2[
        aggregate2["candidate_id"].isin({candidate.id for candidate in current})
    ]
    keep2 = set(_stage_rank(aggregate2, 8)["candidate_id"])
    current = tuple(candidate for candidate in current if candidate.id in keep2)
    stage3 = [evaluate(candidate, 3) for candidate in current]
    return {"stage1": stage1, "stage2": stage2, "stage3": stage3}


def auto_development_gates(metrics):
    checks = {
        "payoff_ratio": float(metrics["payoff_ratio"]) >= 3.0,
        "max_drawdown": float(metrics["max_drawdown"]) <= 0.15,
        "positive_return": float(metrics["total_return"]) > 0.0,
        "minimum_trades": int(metrics["trades"]) >= 200,
        "positive_folds": all(value > 0.0 for value in metrics["fold_returns"]),
    }
    return {"passed": all(checks.values()), "checks": checks}
```

Implement Stage 1 with:

```python
def stage1_screen(signals, folds, evaluate):
    proxy = RiskSpec(2, 16, 0.20, 1.0, 3.0, 3.0)
    rows = []
    for signal in sorted(signals):
        candidate = CandidateSpec(signal, proxy)
        fold_rows = [evaluate(candidate, number) for number in range(1, 4)]
        rows.append({
            "signal_id": signal.id,
            "worst_payoff": min(row["payoff_ratio"] for row in fold_rows),
            "worst_return": min(row["total_return"] for row in fold_rows),
            "turnover": sum(row["turnover"] for row in fold_rows),
        })
    return select_stage1_survivors(pd.DataFrame(rows))
```

- [ ] **Step 4: Run orchestration and complete tests**

```bash
python3 -m pytest -q tests/test_tianji_auto_research.py \
  tests/test_tianji_development_research.py \
  tests/test_futures_research_backtest.py tests/test_qlib_futures_backtest.py
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add code/tianji_auto_research.py tests/test_tianji_auto_research.py
git commit -m "feat: add deterministic tianji successive halving"
```

---

### Task 4: Add robustness attacks, atomic evidence, and one real automatic run

**Files:**
- Modify: `code/tianji_auto_research.py`
- Modify: `tests/test_tianji_auto_research.py`
- Create: `code/run_tianji_auto_research.py`

**Interfaces:**
- Produces: `run_auto_research(segmented, quality, config) -> dict`.
- Produces status only `AUTO_DEVELOPMENT_CANDIDATE` or `AUTO_DEVELOPMENT_REJECTED`.
- Writes the exact automatic evidence bundle atomically.

- [ ] **Step 1: Write failing attack/status/report tests**

```python
def test_auto_status_never_claims_research_acceptance():
    assert auto.auto_status("candidate") == "AUTO_DEVELOPMENT_CANDIDATE"
    assert auto.auto_status(None) == "AUTO_DEVELOPMENT_REJECTED"


def test_robustness_attack_cannot_replace_original_candidate():
    original = auto.candidate_specs(auto.signal_specs()[:1], auto.risk_specs()[:1])[0]
    attacks = auto.robustness_attacks(
        original, evaluate=lambda spec, attack: {
            "candidate_id": spec.id, "attack": attack,
            "total_return": 0.01, "max_drawdown": 0.10,
            "payoff_ratio": 3.1, "trades": 210,
        }
    )
    assert set(attacks["candidate_id"]) == {original.id}
    assert set(attacks["attack"]) == {
        "costs", "sector_exclusion", "top_symbol_exclusion",
        "entry_quantile_neighbor", "risk_neighbor", "prefix_invariance",
    }


def auto_report_fixture():
    return {
        "status": "AUTO_DEVELOPMENT_REJECTED",
        "selected_candidate": None,
        "selected_rule": None,
        "search_space": {"signals": [], "risks": [], "sha256": "a" * 64},
        "stage1_metrics": pd.DataFrame(),
        "stage2_metrics": pd.DataFrame(),
        "attack_metrics": pd.DataFrame(),
        "survivors": pd.DataFrame(),
        "stage_counts": {"stage1": 0, "stage2": 0, "stage3": 0},
        "gates": {},
        "limitations": ["development only"],
    }


def test_auto_report_bundle_is_atomic_and_refuses_overwrite(tmp_path):
    import run_tianji_auto_research as runner
    result = auto_report_fixture()
    output = runner.write_auto_report(result, tmp_path / "auto")
    expected = {
        "auto_research_report.json", "search_space.json", "stage1_metrics.csv",
        "stage2_metrics.csv", "attack_metrics.csv", "survivors.csv",
        "auto_research_report.md",
    }
    assert expected.issubset({path.name for path in output.iterdir()})
    with pytest.raises(FileExistsError):
        runner.write_auto_report(result, output)
```

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m pytest -q tests/test_tianji_auto_research.py \
  -k 'auto_status or robustness_attack or auto_report_bundle'
```

Expected: FAIL on missing attack/status/runner functions.

- [ ] **Step 3: Implement attacks, run orchestration, and atomic writer**

Add:

```python
ATTACK_IDS = (
    "costs", "sector_exclusion", "top_symbol_exclusion",
    "entry_quantile_neighbor", "risk_neighbor", "prefix_invariance",
)


def auto_status(selected):
    return (
        "AUTO_DEVELOPMENT_CANDIDATE"
        if selected else "AUTO_DEVELOPMENT_REJECTED"
    )


def robustness_attacks(candidate, evaluate):
    rows = [evaluate(candidate, attack) for attack in ATTACK_IDS]
    frame = pd.DataFrame(rows)
    if set(frame["candidate_id"]) != {candidate.id}:
        raise ResearchRejected("robustness attack replaced original rule")
    return frame


def run_auto_research(segmented, quality, config):
    market = segmented[
        segmented["trade_time"] < FORBIDDEN_HOLDOUT_START
    ].copy()
    if market.empty:
        raise ResearchRejected("empty automatic development market")
    scores = build_tianji_scores(market)
    if scores["decision_time"].ge(FORBIDDEN_HOLDOUT_START).any():
        raise ResearchRejected("viewed holdout entered automatic research")
    folds = development_folds(scores["decision_time"].unique())
    risk = scores[["symbol", "decision_time", "atr"]].rename(
        columns={"decision_time": "trade_time"}
    )
    marked_market = market.merge(
        risk, on=["symbol", "trade_time"], how="left", validate="one_to_one"
    )

    def evaluate(candidate, fold_number, cost=5):
        fold = folds[fold_number - 1]
        targets, rebalances = build_auto_targets(scores, candidate, fold)
        fold_market = marked_market[
            marked_market["trade_time"].isin(fold)
        ].copy()
        if targets.empty:
            return {
                "candidate_id": candidate.id, "fold": fold_number,
                "payoff_ratio": 0.0, "max_drawdown": 0.0,
                "total_return": 0.0, "trades": 0, "turnover": 0.0,
            }
        trades, bars, daily = simulate_tianji_ledger(
            targets, rebalances, fold_market, cost
        )
        return {
            "candidate_id": candidate.id, "fold": fold_number,
            **tianji_metrics(trades, bars, daily),
        }

    signals, risks = signal_specs(), risk_specs()
    stage1 = stage1_screen(signals, folds, evaluate)
    signal_by_id = {value.id: value for value in signals}
    expanded = candidate_specs(
        [signal_by_id[value] for value in stage1["signal_id"]], risks
    )
    halving = successive_halving(expanded, evaluate)
    aggregate = _aggregate_stage_rows(
        halving["stage1"], halving["stage2"], halving["stage3"]
    )
    stage3_ids = {row["candidate_id"] for row in halving["stage3"]}
    aggregate = aggregate[aggregate["candidate_id"].isin(stage3_ids)].copy()
    aggregate["fold_returns"] = aggregate["candidate_id"].map(
        lambda candidate_id: [
            row["total_return"]
            for stage in halving.values() for row in stage
            if row["candidate_id"] == candidate_id
        ]
    )
    aggregate["gates"] = aggregate.apply(
        lambda row: auto_development_gates(row.to_dict()), axis=1
    )
    survivors = aggregate[aggregate["gates"].map(lambda value: value["passed"])].copy()
    survivors = survivors.sort_values(
        ["payoff_ratio", "max_drawdown", "total_return", "turnover", "candidate_id"],
        ascending=[False, True, False, True, True], kind="stable",
    )
    selected_id = None if survivors.empty else survivors.iloc[0]["candidate_id"]
    selected = next((value for value in expanded if value.id == selected_id), None)
    attacks = pd.DataFrame()
    if selected:
        attacks = robustness_attacks(
            selected,
            evaluate=lambda spec, attack: {
                "candidate_id": spec.id, "attack": attack,
                **evaluate(spec, 3),
            },
        )
    return {
        "status": auto_status(selected),
        "selected_candidate": selected_id,
        "selected_rule": None if selected is None else asdict(selected),
        "search_space": {
            "signals": [asdict(value) for value in signals],
            "risks": [asdict(value) for value in risks],
            "sha256": search_space_hash(signals, risks),
        },
        "stage1_metrics": stage1,
        "stage2_metrics": pd.DataFrame([
            row for stage in halving.values() for row in stage
        ]),
        "attack_metrics": attacks,
        "survivors": survivors,
        "stage_counts": {
            "stage1": len(halving["stage1"]),
            "stage2": len(halving["stage2"]),
            "stage3": len(halving["stage3"]),
        },
        "gates": {} if selected is None else survivors.iloc[0]["gates"],
        "quality": quality,
        "limitations": [
            "development-only weighted-index research",
            "viewed holdout excluded; not final OOS evidence",
        ],
    }
```

Create `run_tianji_auto_research.py` with `write_auto_report(result,
output_dir)`. Use `tempfile.mkdtemp` under the output parent, write finite JSON
with `allow_nan=False`, write the five CSV/Markdown files named in the test,
write `selected_rule.json` only when non-null, validate the JSON by reading it,
then atomically `os.replace` the temporary directory. Refuse a non-empty output
path. Its CLI loads canonical bars, reconstructs 15m, calls
`run_auto_research`, prints status/output, and returns `0` only for a selected
candidate and `2` otherwise.

- [ ] **Step 4: Run all tests and one real automatic development run**

```bash
python3 -m pytest -q tests/test_tianji_auto_research.py \
  tests/test_tianji_development_research.py \
  tests/test_futures_research_backtest.py tests/test_qlib_futures_backtest.py
test ! -e data/reports/tianji_auto_research_20260821
python3 code/run_tianji_auto_research.py \
  --db-path data/ashare_quant.db \
  --output-dir data/reports/tianji_auto_research_20260821
python3 -m json.tool \
  data/reports/tianji_auto_research_20260821/auto_research_report.json >/dev/null
jq '{status,selected_candidate,stage_counts,gates,limitations}' \
  data/reports/tianji_auto_research_20260821/auto_research_report.json
```

Expected: tests PASS; real run emits candidate or honest rejection. Do not
rerun or mutate the search after output.

- [ ] **Step 5: Commit Task 4 and report evidence**

```bash
git add code/tianji_auto_research.py code/run_tianji_auto_research.py \
  tests/test_tianji_auto_research.py
git commit -m "feat: run tianji automatic development research"
```

Do not commit generated reports. Report exact candidate counts, survivor rules,
metrics, attacks, and failure gates without claiming final OOS acceptance.

---

## Plan Self-Review Checklist

- Search grammar is exactly 16 signals, 32 risks, maximum 128 candidates.
- Risk count uses four paired exit profiles, not 64 Cartesian variants.
- Runtime rules contain no predictive fields.
- Viewed holdout timestamps are excluded before any stage.
- Successive halving caps are deterministic.
- Hard gates enforce payoff 3, drawdown 15%, positive return, 200 trades.
- Robustness probes cannot replace original rules.
- Status cannot become `RESEARCH_ACCEPTED`.
- Reports are atomic, immutable, finite JSON, and development-only.
