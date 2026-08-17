# Futures 15m First-Principles Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Disable the unsafe futures trading paths and make the audited 15-minute weighted-index research path causally correct, baseline-controlled, adversarially gated, and evidence-complete.

**Architecture:** Keep `futures_research_backtest.py` as the single research orchestrator and `qlib_model_adapter.py` as the only Qlib bridge. Disable, rather than partially repair, all TqSim/live launch surfaces. Strengthen the existing linear research flow with pre-aggregation 5-minute segmentation, a fixed simple-versus-complex model domain, stricter baselines, and atomic research identity evidence.

**Tech Stack:** Python 3.10, pandas, NumPy, scikit-learn, LightGBM/Qlib, SQLite, Flask test client, pytest, Bash.

## Global Constraints

- No new dependency.
- Existing report directories and the untracked `qlib/` checkout are never modified or committed.
- Every production-code change follows a failing regression test.
- `embargo_bars >= horizon` is mandatory for official runs.
- The selectable Qlib domain is exactly L2 logistic regression `C=0.1` plus constrained Qlib LightGBM.
- Thresholds remain exactly the configured unique subset of `(0.52, 0.55, 0.58)`.
- Weighted-index output never claims lots, margin, liquidation, exchange execution, RMB PnL, or live readiness.
- A failed or incomplete gate produces `RESEARCH_REJECTED`; no fallback or automatic tuning is allowed.
- Futures live/TqSim execution remains disabled after this plan completes.

---

### Task 1: Fail-closed trading isolation

**Files:**

- Create: `tests/test_futures_trading_isolation.py`
- Modify: `run_tqsim_trader.sh`
- Modify: `code/futures_live_trader.py:396-410`
- Modify: `code/futures_dashboard_server.py:1-295,829-832`
- Modify: `docs/research-only-ml-engines.md`
- Modify: `tests/test_web_validation.py:13-24,253-275`

**Interfaces:**

- Produces: `TRADING_DISABLED_REASON: str`, `futures_live_trader.main() -> int`, dashboard HTTP 503 isolation responses.
- Consumes: existing Flask `app`; existing documentation boundary test.

- [ ] **Step 1: Write the failing isolation tests**

```python
# tests/test_futures_trading_isolation.py
import inspect
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_shell_trader_launcher_fails_closed():
    completed = subprocess.run(
        ["bash", str(ROOT / "run_tqsim_trader.sh")],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 2
    assert "TRADING_DISABLED" in completed.stderr


def test_python_trader_main_fails_before_credentials_or_tqsdk():
    import futures_live_trader

    source = inspect.getsource(futures_live_trader)
    assert futures_live_trader.main() == 2
    assert 'os.getenv("TQ_USER",' not in source
    assert 'os.getenv("TQ_PASS",' not in source
    assert "TqAuth(" not in inspect.getsource(futures_live_trader.main)


def test_dashboard_exposes_no_active_trading_or_legacy_backtest_api():
    from futures_dashboard_server import app

    client = app.test_client()
    for method, path in (
        (client.get, "/"),
        (client.get, "/api/status"),
        (client.get, "/api/kline?symbol=AG_IDX"),
        (client.get, "/api/trades"),
        (client.post, "/api/trader/restart"),
    ):
        response = method(path)
        assert response.status_code == 503
        payload = response.get_json()
        assert payload["status"] == "TRADING_DISABLED"
        assert "disabled_reason" in payload
```

Extend `RESEARCH_ONLY_INVALIDATED` in `tests/test_web_validation.py` with:

```python
RESEARCH_ONLY_INVALIDATED |= {
    "futures_v16_first_principles_engine",
    "copper_v16_engine",
    "symbol_strategies.decoupled_symbol_engines",
    "generate_futures_html_report",
    "futures_live_trader",
}
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
python3 -m pytest -q \
  tests/test_futures_trading_isolation.py \
  tests/test_web_validation.py::test_invalidated_ml_engines_are_documented_and_not_executable
```

Expected: failures because the launcher returns zero, `main()` does not exist, the dashboard returns active data/restart behavior, and the new modules are not documented.

- [ ] **Step 3: Implement the minimum isolation boundary**

Replace `run_tqsim_trader.sh` with:

```bash
#!/bin/bash
echo "TRADING_DISABLED: 15m futures research has not passed the required gates" >&2
exit 2
```

Replace the executable footer in `code/futures_live_trader.py` and remove all credential loading/defaults:

```python
TRADING_DISABLED_REASON = (
    "15m futures research has not passed the required gates; "
    "TqSim and live execution are isolated"
)


def main():
    print(f"TRADING_DISABLED: {TRADING_DISABLED_REASON}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

In `code/futures_dashboard_server.py`, remove the `subprocess` import and add:

```python
TRADING_DISABLED_REASON = (
    "15m futures research has not passed the required gates; "
    "legacy live and backtest dashboard sources are isolated"
)


def disabled_response():
    return jsonify({
        "status": "TRADING_DISABLED",
        "disabled_reason": TRADING_DISABLED_REASON,
    }), 503
```

Make `/`, `/api/status`, `/api/kline`, `/api/trades`, and
`/api/trader/restart` return `disabled_response()` immediately. Do not retain
any process restart call in a reachable route.

Add the five newly isolated modules to `docs/research-only-ml-engines.md` with
the exact `RESEARCH_ONLY_INVALIDATED` marker.

- [ ] **Step 4: Verify GREEN and the broader boundary**

Run:

```bash
python3 -m pytest -q \
  tests/test_futures_trading_isolation.py \
  tests/test_web_validation.py \
  tests/test_legacy_ml_boundary.py
```

Expected: all tests pass; no trader process is launched.

- [ ] **Step 5: Commit the isolation change**

```bash
git add run_tqsim_trader.sh code/futures_live_trader.py \
  code/futures_dashboard_server.py docs/research-only-ml-engines.md \
  tests/test_futures_trading_isolation.py tests/test_web_validation.py
git diff --cached --check
git commit -m "fix: isolate untrusted futures trading paths"
```

### Task 2: Segment 5-minute truth before natural 15-minute aggregation

**Files:**

- Modify: `code/futures_research_backtest.py:16,210-294`
- Modify: `tests/test_futures_research_backtest.py:1199-1244`

**Interfaces:**

- Produces: `_prepare_segmented_bars(bars, config) -> tuple[pd.DataFrame, pd.DataFrame]` with natural 15-minute windows and aggregation counters.
- Consumes: `validate_and_segment()` and the existing source manifest attributes.

- [ ] **Step 1: Add failing aggregation regressions**

```python
def _prepare_15m(bars):
    return research._prepare_segmented_bars(
        bars,
        ResearchConfig(
            timeframe="15m", min_symbol_rows=1,
            min_symbols=1, min_fold_rows=1,
        ),
    )


def test_15m_resampling_does_not_hide_internal_zero_volume():
    bars = make_bars(6)
    bars["trade_time"] = pd.date_range(
        "2026-01-02 09:05", periods=6, freq="5min"
    )
    bars.loc[1, "volume"] = 0.0

    segmented, quality = _prepare_15m(bars)

    assert segmented["trade_time"].tolist() == [pd.Timestamp("2026-01-02 09:30")]
    assert quality.loc["AG_IDX", "zero_volume_boundaries"] >= 1
    assert quality.loc["AG_IDX", "aggregated_15m_rows"] == 1


def test_15m_resampling_does_not_hide_internal_price_jump():
    bars = make_bars(6)
    bars["trade_time"] = pd.date_range(
        "2026-01-02 09:05", periods=6, freq="5min"
    )
    bars.loc[1, ["open", "high", "low", "close"]] *= 1.04

    segmented, quality = _prepare_15m(bars)

    assert segmented["trade_time"].tolist() == [pd.Timestamp("2026-01-02 09:30")]
    assert quality.loc["AG_IDX", "price_jump_boundaries"] >= 1


def test_15m_resampling_uses_natural_boundaries_and_drops_partials():
    bars = make_bars(6)
    bars["trade_time"] = pd.date_range(
        "2026-01-02 09:10", periods=6, freq="5min"
    )

    segmented, quality = _prepare_15m(bars)

    assert segmented["trade_time"].tolist() == [pd.Timestamp("2026-01-02 09:30")]
    assert quality.loc["AG_IDX", "partial_15m_windows"] == 2
```

Update the existing gap test for natural-boundary semantics:

```python
assert segmented["trade_time"].tolist() == [
    pd.Timestamp("2026-01-02 09:15"),
    pd.Timestamp("2026-01-02 09:45"),
    pd.Timestamp("2026-01-02 10:00"),
]
assert segmented.groupby("segment_id").size().tolist() == [1, 2]
assert quality.loc["AG_IDX", "partial_15m_windows"] == 2
assert segmented.attrs["source_manifest"] == manifest
```

- [ ] **Step 2: Run the aggregation tests and verify RED**

Run:

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py \
  -k '15m_resampling or prepare_segmented_bars'
```

Expected: the old count-based aggregator emits windows that contain the zero,
jump, or misaligned partial data, and the new quality columns are absent.

- [ ] **Step 3: Add source-boundary evidence**

Import `replace` from `dataclasses`. In `validate_and_segment`, add per-symbol
quality fields derived before `segment_id` assignment:

```python
quality_rows.append({
    "symbol": symbol,
    "raw_rows": len(group),
    "start_time": group["trade_time"].min(),
    "end_time": group["trade_time"].max(),
    "zero_volume_fraction": zero_fraction,
    "time_gap_boundaries": int(gap.iloc[1:].sum()),
    "zero_volume_boundaries": int(zero_neighbor.sum()),
    "price_jump_boundaries": int((open_gap | close_jump).sum()),
    "segment_count": int(group["segment_id"].nunique()),
    "status": "EXCLUDED" if excluded else "INCLUDED",
    "reason": "ZERO_VOLUME_FRACTION" if excluded else "",
})
```

- [ ] **Step 4: Replace count-based aggregation with natural windows**

Implement the 15-minute branch of `_prepare_segmented_bars` as:

```python
source, quality = validate_and_segment(
    bars, replace(config, timeframe="5m")
)
source.attrs = {}
source["_window_end"] = source["trade_time"].dt.ceil("15min")
keys = ["symbol", "segment_id", "_window_end"]
source["_window_size"] = source.groupby(keys, sort=False)[
    "trade_time"
].transform("size")

window_sizes = source.drop_duplicates(keys).loc[
    :, ["symbol", "_window_size"]
]
complete_counts = window_sizes["_window_size"].eq(3).groupby(
    window_sizes["symbol"]
).sum()
partial_counts = window_sizes["_window_size"].ne(3).groupby(
    window_sizes["symbol"]
).sum()
quality["aggregated_15m_rows"] = complete_counts.reindex(
    quality.index, fill_value=0
).astype(int)
quality["partial_15m_windows"] = partial_counts.reindex(
    quality.index, fill_value=0
).astype(int)

complete = source[source["_window_size"].eq(3)].copy()
if complete.empty:
    raise ResearchRejected("no complete natural-boundary 15m bars")
if "series_type" in complete and complete.groupby(keys)[
    "series_type"
].nunique().gt(1).any():
    raise ResearchRejected("15m window contains mixed series types")

aggregations = {
    "open": "first", "high": "max", "low": "min", "close": "last",
    "volume": "sum", "feature_segment_id": "first",
}
for column, method in (
    ("amount", lambda values: values.sum(min_count=1)),
    ("open_interest", "last"), ("settlement", "last"),
    ("series_type", "first"),
):
    if column in complete:
        aggregations[column] = method

result = complete.groupby(keys, sort=False, as_index=False).agg(aggregations)
result = result.rename(columns={"_window_end": "trade_time"})
result["timeframe"] = "15m"
result.attrs = source_attrs
return result, quality
```

Keep the existing 5-minute branch unchanged. Do not run a second segmentation
that could merge original 5-minute boundaries.

- [ ] **Step 5: Verify focused and causal suites GREEN**

Run:

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py \
  -k '15m_resampling or prepare_segmented_bars or causal or segment'
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit the causal aggregation change**

```bash
git add code/futures_research_backtest.py tests/test_futures_research_backtest.py
git diff --cached --check
git commit -m "fix: preserve causal boundaries in 15m bars"
```

### Task 3: Fixed simple-versus-Qlib model domain

**Files:**

- Modify: `code/qlib_model_adapter.py:78-162`
- Modify: `code/futures_research_backtest.py:305-386,3317-3342`
- Modify: `tests/test_qlib_futures_backtest.py`
- Modify: `tests/test_futures_research_backtest.py:351-636`

**Interfaces:**

- Produces: Qlib domain `("logistic_c0.1", "qlib_lightgbm_constrained")`; `_validate_research_config(config) -> None`.
- Consumes: existing `Candidate`, `_fit_matrix`, and nested candidate selection.

- [ ] **Step 1: Write failing model-domain tests**

```python
def test_qlib_domain_competes_with_one_simple_model():
    assert research.candidate_names("qlib") == (
        "logistic_c0.1", "qlib_lightgbm_constrained",
    )


def test_qlib_dataset_does_not_duplicate_train_as_validation():
    import qlib_model_adapter as adapter

    train = pd.concat({
        "feature": pd.DataFrame({"x": [0.0, 1.0]}),
        "label": pd.DataFrame({"label": [0, 1]}),
    }, axis=1)
    test = pd.concat({"feature": pd.DataFrame({"x": [0.5]})}, axis=1)
    dataset = adapter._FrameDataset(train, test)

    assert set(dataset.segments) == {"train", "test"}
    with pytest.raises(KeyError):
        dataset.prepare("valid", ["feature", "label"])


def test_official_config_requires_embargo_at_least_horizon():
    with pytest.raises(research.ResearchRejected, match="embargo"):
        research._validate_research_config(
            research.ResearchConfig(horizon=6, embargo_bars=5)
        )


def test_near_best_qlib_domain_prefers_logistic_at_equal_turnover():
    scores = _two_fold_scores([
        ("logistic_c0.1", 0.55, 0.0100, 1.0),
        ("qlib_lightgbm_constrained", 0.55, 0.0105, 1.0),
    ])
    assert research.choose_from_scores(scores, "qlib") == research.Candidate(
        "logistic_c0.1", 0.55
    )
```

Use the existing two-fold score helper in
`tests/test_futures_research_backtest.py` rather than creating a new helper
module; the final test should live beside that helper.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m pytest -q tests/test_qlib_futures_backtest.py \
  tests/test_futures_research_backtest.py \
  -k 'qlib or embargo or near_best'
```

Expected: Qlib has one selectable model, `_FrameDataset` exposes `valid`, and
the config validator is absent.

- [ ] **Step 3: Remove train-as-validation from Qlib**

Change `_FrameDataset` to:

```python
class _FrameDataset:
    def __init__(self, train, test):
        self.segments = {"train": "train", "test": "test"}
        self.frames = {"train": train, "test": test}

    def prepare(self, segment, col_set, data_key=None):
        frame = self.frames[segment]
        if isinstance(col_set, str):
            return frame[col_set]
        return frame.loc[:, list(col_set)]
```

Record the fixed validation policy and disable early stopping in the adapter:

```python
parameters.update({
    "validation": "external_nested_walk_forward",
    "boost_rounds": 100,
    "early_stopping_rounds": 0,
})
model = qlib_gbdt.LGBModel(
    num_boost_round=parameters["boost_rounds"],
    early_stopping_rounds=parameters["early_stopping_rounds"],
    **{
        key: value for key, value in parameters.items()
        if key not in {
            "backend", "qlib_version", "qlib_revision", "validation",
            "boost_rounds", "early_stopping_rounds",
        }
    },
)
```

- [ ] **Step 4: Route each candidate by name, not backend**

Change `candidate_names("qlib")` to return logistic then Qlib. In
`_fit_matrix`, use:

```python
if candidate.model_name == "qlib_lightgbm_constrained":
    from qlib_model_adapter import fit_qlib_lightgbm
    probability, model = fit_qlib_lightgbm(
        x_train, y_train, sample_weight, x_evaluation, config.seed
    )
elif candidate.model_name.startswith("logistic_c"):
    # keep the existing regularized logistic implementation
elif candidate.model_name == "lightgbm_constrained":
    # keep the existing native constrained LightGBM implementation
else:
    raise ResearchRejected(f"unknown model candidate: {candidate.model_name}")
```

Set `probability = model.predict_proba(x_evaluation)[:, 1]` only for non-Qlib
models.

Add the helper below and call `_validate_research_config(config)` as the first
statement inside `run_research`'s existing `try` block, so invalid official
configuration still produces an atomic rejected report:

```python
def _validate_research_config(config):
    horizon = config.horizon
    embargo = config.embargo_bars
    if (
        isinstance(horizon, (bool, np.bool_))
        or not isinstance(horizon, (int, np.integer))
        or horizon < 1
    ):
        raise ResearchRejected(
            "horizon must be an integer greater than or equal to one"
        )
    if (
        isinstance(embargo, (bool, np.bool_))
        or not isinstance(embargo, (int, np.integer))
        or embargo < horizon
    ):
        raise ResearchRejected("embargo_bars must be at least horizon")
```

- [ ] **Step 5: Verify model tests and full adapter behavior GREEN**

Run:

```bash
python3 -m pytest -q \
  tests/test_qlib_futures_backtest.py \
  tests/test_futures_research_backtest.py \
  -k 'qlib or candidate or config or embargo'
```

Expected: all selected tests pass and the real Qlib smoke fit still returns
finite probabilities.

- [ ] **Step 6: Commit the fixed model domain**

```bash
git add code/qlib_model_adapter.py code/futures_research_backtest.py \
  tests/test_qlib_futures_backtest.py tests/test_futures_research_backtest.py
git diff --cached --check
git commit -m "fix: constrain qlib model selection"
```

### Task 4: Baseline superiority and multi-horizon uncertainty gates

**Files:**

- Modify: `code/futures_research_backtest.py:1111-1136,1525-1575,2227-2574`
- Modify: `tests/test_futures_research_backtest.py:1140-1170,2103-2595`

**Interfaces:**

- Produces: `moving_block_return_interval(..., block_days)`, `moving_block_return_intervals(...)`, twelve exact acceptance gates.
- Consumes: fold `predictive_metrics`, `cost_metrics`, and existing benchmark dictionaries.

- [ ] **Step 1: Write failing uncertainty and baseline-gate tests**

```python
def test_moving_block_intervals_cover_5_10_and_20_days():
    returns = np.full(60, 0.001)
    result = research.moving_block_return_intervals(
        returns, ResearchConfig(seed=42)
    )

    assert set(result["blocks"]) == {"5", "10", "20"}
    assert result["worst_p05"] == min(
        row["p05"] for row in result["blocks"].values()
    )


def test_brier_gate_requires_model_to_beat_dummy_in_every_fold():
    context = passing_gate_context()
    context["outer_results"][1]["predictive_metrics"][
        "brier_score"
    ] = context["outer_results"][1]["benchmarks"][
        "dummy_prior"
    ]["predictive_metrics"]["brier_score"]

    gate = next(
        row for row in research.evaluate_acceptance_gates(context)
        if row["id"] == "brier_better_than_dummy_each_fold"
    )
    assert gate["passed"] is False
    assert gate["affected_fold"] == "outer_2"


def test_baseline_gate_requires_5bp_return_to_beat_both_benchmarks():
    context = passing_gate_context()
    holdout = context["holdout"]
    holdout["benchmarks"]["equal_weight_long_only"]["cost_metrics"][5][
        "total_return"
    ] = holdout["cost_metrics"][5]["total_return"]

    gate = next(
        row for row in research.evaluate_acceptance_gates(context)
        if row["id"] == "baseline_superiority_each_fold"
    )
    assert gate["passed"] is False
    assert gate["affected_fold"] == "holdout"


def test_bootstrap_gate_uses_worst_of_all_required_blocks():
    context = passing_gate_context()
    context["holdout"]["bootstrap"]["blocks"]["20"]["p05"] = 0.0
    context["holdout"]["bootstrap"]["worst_p05"] = 0.0

    gate = next(
        row for row in research.evaluate_acceptance_gates(context)
        if row["id"] == "positive_bootstrap_lower_bound"
    )
    assert gate["passed"] is False
```

Update the `fold(name)` return value inside `passing_gate_context()` with:

```python
"predictive_metrics": {"roc_auc": 0.60, "brier_score": 0.20},
"benchmarks": {
    "dummy_prior": {
        "predictive_metrics": {"brier_score": 0.25},
        "cost_metrics": {5: {"total_return": 0.01}},
    },
    "equal_weight_long_only": {
        "cost_metrics": {5: {"total_return": 0.02}},
    },
},
```

Also change its configuration to `ResearchConfig(embargo_bars=6)` so the
passing fixture satisfies the official `horizon=6` relationship and recomputes
its cutoffs and attack identities from that configuration.

Replace its holdout bootstrap with:

```python
holdout["bootstrap"] = {
    "blocks": {
        str(days): {
            "samples": 1000, "block_days": days,
            "p05": 0.01, "p50": 0.10, "p95": 0.20,
        }
        for days in (5, 10, 20)
    },
    "worst_p05": 0.01,
}
```

- [ ] **Step 2: Run the gate tests and verify RED**

Run:

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py \
  -k 'moving_block or brier_gate or baseline_gate or bootstrap_gate or acceptance_gate'
```

Expected: new helper/gate IDs are absent and the old bootstrap contains one
five-day block.

- [ ] **Step 3: Generalize the existing moving-block calculation**

Use:

```python
def moving_block_return_interval(
        daily_returns, config=ResearchConfig(), block_days=5):
    try:
        returns = np.asarray(daily_returns, dtype=float)
        rng = np.random.default_rng(config.seed + int(block_days))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ResearchRejected("invalid moving-block interval input") from exc
    if (
        isinstance(block_days, (bool, np.bool_))
        or not isinstance(block_days, (int, np.integer))
        or block_days < 1
        or returns.ndim != 1
        or len(returns) < block_days
        or not np.isfinite(returns).all()
    ):
        raise ResearchRejected("invalid moving-block interval input")
    totals = []
    for _ in range(1000):
        sample = []
        while len(sample) < len(returns):
            start = int(rng.integers(0, len(returns) - block_days + 1))
            sample.extend(returns[start:start + block_days])
        totals.append(float(np.prod(1.0 + sample[:len(returns)]) - 1.0))
    p05, p50, p95 = np.percentile(totals, [5, 50, 95])
    return {
        "samples": 1000, "block_days": int(block_days),
        "p05": float(p05), "p50": float(p50), "p95": float(p95),
    }


def moving_block_return_intervals(daily_returns, config=ResearchConfig()):
    blocks = {
        str(days): moving_block_return_interval(
            daily_returns, config, block_days=days
        )
        for days in (5, 10, 20)
    }
    return {
        "blocks": blocks,
        "worst_p05": min(row["p05"] for row in blocks.values()),
    }
```

Assign the multi-block result to `holdout_result["bootstrap"]`.

- [ ] **Step 4: Add exact Brier and benchmark-superiority gates**

Add these IDs immediately after AUC and positive-5bp respectively:

```python
"brier_better_than_dummy_each_fold"
"baseline_superiority_each_fold"
```

Add the configuration relationship to `_temporal_integrity` before returning
its evidence:

```python
observed["embargo_covers_horizon"] = bool(
    isinstance(config.embargo_bars, (int, np.integer))
    and not isinstance(config.embargo_bars, (bool, np.bool_))
    and config.embargo_bars >= config.horizon
)
```

Implement the Brier comparison with:

```python
folds = _fold_results(outer, holdout)
observed = {
    row["fold"]: {
        "candidate": row["predictive_metrics"]["brier_score"],
        "dummy_prior": row["benchmarks"]["dummy_prior"][
            "predictive_metrics"
        ]["brier_score"],
    }
    for row in folds
}
affected = next((
    name for name, values in observed.items()
    if not all(_finite_number(value) for value in values.values())
    or values["candidate"] >= values["dummy_prior"]
), None)
gates.append(_gate_record(
    "brier_better_than_dummy_each_fold", affected is None, observed,
    "candidate Brier < Dummy Brier each fold", affected,
    "candidate calibration beats Dummy" if affected is None
    else f"candidate Brier did not beat Dummy: {affected}",
))
```

Implement benchmark return comparison with:

```python
observed = {
    row["fold"]: {
        "candidate": row["cost_metrics"][5]["total_return"],
        "dummy_prior": row["benchmarks"]["dummy_prior"][
            "cost_metrics"
        ][5]["total_return"],
        "equal_weight_long_only": row["benchmarks"][
            "equal_weight_long_only"
        ]["cost_metrics"][5]["total_return"],
    }
    for row in folds
}
affected = next((
    name for name, values in observed.items()
    if not all(_finite_number(value) for value in values.values())
    or values["candidate"] <= values["dummy_prior"]
    or values["candidate"] <= values["equal_weight_long_only"]
), None)
gates.append(_gate_record(
    "baseline_superiority_each_fold", affected is None, observed,
    "candidate 5bp return > Dummy and equal-weight each fold", affected,
    "candidate beats both return baselines" if affected is None
    else f"candidate did not beat both baselines: {affected}",
))
```

Replace the bootstrap gate's validation with exact keys `{"5", "10", "20"}`,
`samples == 1000`, matching `block_days`, finite percentiles, a recomputed
`worst_p05`, and `worst_p05 > 0`.

```python
bootstrap = holdout["bootstrap"]
blocks = bootstrap["blocks"]
required_days = {"5": 5, "10": 10, "20": 20}
valid_blocks = (
    set(blocks) == set(required_days)
    and all(
        blocks[key].get("samples") == 1000
        and blocks[key].get("block_days") == days
        and all(
            _finite_number(blocks[key].get(name))
            for name in ("p05", "p50", "p95")
        )
        for key, days in required_days.items()
    )
)
recomputed = min(
    (blocks[key]["p05"] for key in required_days), default=float("nan")
)
passed = bool(
    valid_blocks
    and _finite_number(bootstrap.get("worst_p05"))
    and np.isclose(
        bootstrap["worst_p05"], recomputed, rtol=0.0, atol=1e-12
    )
    and recomputed > 0.0
)
gates.append(_gate_record(
    "positive_bootstrap_lower_bound", passed, bootstrap,
    "5/10/20-day worst p05 > 0", None if passed else "holdout",
    "all block bootstrap lower bounds are positive" if passed
    else "invalid or non-positive multi-block bootstrap lower bound",
))
```

Update `ACCEPTANCE_GATE_IDS`, missing-evidence fallback construction, official
gate fixtures, expected gate counts, and report bundle tests from ten to twelve
gates.

The final exact order is:

```python
ACCEPTANCE_GATE_IDS = (
    "integrity_checks", "auc_above_chance_each_fold",
    "brier_better_than_dummy_each_fold", "positive_5bps_each_fold",
    "baseline_superiority_each_fold", "positive_bootstrap_lower_bound",
    "label_shuffle", "feature_attacks", "positive_symbol_fraction",
    "positive_symbol_concentration", "ten_bps_resilience",
    "cost_monotonicity",
)
```

- [ ] **Step 5: Verify every gate is independently non-negotiable**

Run:

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py \
  -k 'moving_block or gate or baseline or brier or bootstrap'
```

Expected: all selected tests pass, including the parameterized test that
mutates each gate independently.

- [ ] **Step 6: Commit the stronger evidence gates**

```bash
git add code/futures_research_backtest.py tests/test_futures_research_backtest.py
git diff --cached --check
git commit -m "feat: require baseline and uncertainty evidence"
```

### Task 5: Bind reports to the fixed research domain and run identity

**Files:**

- Modify: `code/futures_research_backtest.py:1197-1242,2839-3015,3053-3269,3317-3390`
- Modify: `tests/test_futures_research_backtest.py:840-980,2598-2965`
- Modify: `tests/test_qlib_futures_backtest.py:36-51`

**Interfaces:**

- Produces: `research_domain` and `run_identity` in JSON, Markdown, and HTML evidence.
- Consumes: database/module hashes, source manifest, holdout evaluation identity, candidate and threshold domains.

- [ ] **Step 1: Write failing report identity tests**

```python
def test_research_domain_records_fixed_trial_count():
    config = ResearchConfig(model_backend="qlib")
    domain = research._research_domain(config)

    assert domain == {
        "selectable_models": [
            "logistic_c0.1", "qlib_lightgbm_constrained",
        ],
        "thresholds": [0.52, 0.55, 0.58],
        "candidate_threshold_pairs": 6,
        "feature_names": list(research.FEATURE_COLUMNS),
        "horizon": 6,
        "embargo_bars": 6,
    }


def test_run_identity_changes_with_database_or_module_hash():
    domain = research._research_domain(
        ResearchConfig(model_backend="qlib")
    )
    evaluation = {"id": "evaluation"}
    first = research._run_identity(
        domain, evaluation, "a" * 64, "b" * 64
    )
    second = research._run_identity(
        domain, evaluation, "c" * 64, "b" * 64
    )
    assert first["id"] != second["id"]
    assert len(first["id"]) == 64


def test_report_contains_domain_identity_and_aggregation_evidence(tmp_path):
    result = rejected_result_fixture()
    result["research_domain"] = research._research_domain(
        ResearchConfig(model_backend="qlib")
    )
    result["run_identity"] = {
        "id": "a" * 64, "evaluation_identity": "evaluation",
    }
    result["data_quality"] = [{
        "symbol": "AG_IDX", "aggregated_15m_rows": 10,
        "partial_15m_windows": 2, "zero_volume_boundaries": 1,
        "price_jump_boundaries": 1, "time_gap_boundaries": 1,
    }]

    paths = research.write_report(result, tmp_path / "evidence")
    payload = json.loads(Path(paths["report.json"]).read_text())
    markdown = Path(paths["report.md"]).read_text()
    html = Path(paths["report.html"]).read_text()
    assert payload["research_domain"]["candidate_threshold_pairs"] == 6
    assert payload["run_identity"]["id"] == "a" * 64
    assert "Research domain" in markdown
    assert "Run identity" in html
```

Extend the existing `rejected_result_fixture()` rather than creating a second
report fixture.

- [ ] **Step 2: Run report tests and verify RED**

Run:

```bash
python3 -m pytest -q \
  tests/test_futures_research_backtest.py \
  tests/test_qlib_futures_backtest.py \
  -k 'research_domain or run_identity or report_contains or html'
```

Expected: identity helpers and report sections are absent.

- [ ] **Step 3: Implement canonical domain and run identity helpers**

```python
def _research_domain(config):
    models = list(candidate_names(config.model_backend))
    thresholds = [float(value) for value in config.thresholds]
    return {
        "selectable_models": models,
        "thresholds": thresholds,
        "candidate_threshold_pairs": len(models) * len(thresholds),
        "feature_names": list(FEATURE_COLUMNS),
        "horizon": int(config.horizon),
        "embargo_bars": int(config.embargo_bars),
    }


def _run_identity(domain, evaluation_identity, database_sha256, module_sha256):
    payload = {
        "research_domain": domain,
        "evaluation_identity": evaluation_identity,
        "database_sha256": database_sha256,
        "module_sha256": module_sha256,
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode()
    return {"id": hashlib.sha256(encoded).hexdigest(), **payload}
```

After provenance is attached to the adversarial context in `run_research`, set:

```python
context["research_domain"] = _research_domain(config)
context["run_identity"] = _run_identity(
    context["research_domain"],
    base["holdout"]["evaluation_identity"],
    provenance["database_sha256"],
    provenance["module_sha256"],
)
```

Include both fields in `build_result`. Rejected precondition results include the
research domain and `run_identity: None`.

- [ ] **Step 4: Render and reconcile the evidence**

Add compact “Research domain” and “Run identity” sections to Markdown:

```python
lines.extend([
    "## Research domain", "",
    f"```json\n{json.dumps(payload.get('research_domain'), ensure_ascii=False, sort_keys=True)}\n```",
    "", "## Run identity", "",
    f"`{(payload.get('run_identity') or {}).get('id', 'Not reached')}`",
    "",
])
```

Add the equivalent escaped HTML fragments inside `_html_report`:

```python
domain_text = json.dumps(
    payload.get("research_domain"), ensure_ascii=False, sort_keys=True
)
run_identity = (payload.get("run_identity") or {}).get("id", "Not reached")
identity_html = (
    f"<h2>Research domain</h2><pre>{_html_value(domain_text)}</pre>"
    f"<h2>Run identity</h2><p><code>{_html_value(run_identity)}</code></p>"
)
```

Insert `identity_html` after the status/config summary and before metric tables.
Extend `_reconcile_report` to require:

```python
domain = payload.get("research_domain")
if (
    not isinstance(domain, dict)
    or domain.get("candidate_threshold_pairs")
       != len(domain.get("selectable_models", ())) * len(domain.get("thresholds", ()))
):
    raise RuntimeError("report research domain mismatch")
identity = payload.get("run_identity")
if identity is not None and (
    not isinstance(identity, dict) or not _is_sha256(identity.get("id"))
):
    raise RuntimeError("report run identity mismatch")
```

The existing `data_quality.csv` automatically carries the new aggregation
columns; assert them in reconciliation when the run reached aggregation.

- [ ] **Step 5: Verify report and provenance suites GREEN**

Run:

```bash
python3 -m pytest -q \
  tests/test_futures_research_backtest.py \
  tests/test_qlib_futures_backtest.py \
  -k 'report or reconcile or identity or provenance or html'
```

Expected: all selected tests pass and rejected reports remain self-contained.

- [ ] **Step 6: Commit report identity evidence**

```bash
git add code/futures_research_backtest.py \
  tests/test_futures_research_backtest.py tests/test_qlib_futures_backtest.py
git diff --cached --check
git commit -m "feat: bind futures reports to research identity"
```

### Task 6: Full adversarial verification and new real-data evidence

**Files:**

- Modify only if a test exposes a root cause: files already listed above.
- Generate but do not commit: `data/reports/qlib_futures_15m_20260817_v3/`

**Interfaces:**

- Produces: verified source tree and a new immutable accepted-or-rejected report bundle.
- Consumes: all prior tasks.

- [ ] **Step 1: Run the complete relevant suite**

```bash
python3 -m pytest -q \
  tests/test_futures_trading_isolation.py \
  tests/test_qlib_futures_backtest.py \
  tests/test_futures_research_backtest.py \
  tests/test_financial_truth.py \
  tests/test_web_validation.py \
  tests/test_legacy_ml_boundary.py
```

Expected: zero failures. If any test fails, return to root-cause investigation
and add a focused failing regression before changing production code.

- [ ] **Step 2: Run the real 15-minute Qlib research once**

```bash
python3 code/futures_research_backtest.py \
  --db-path data/ashare_quant.db \
  --output-dir data/reports/qlib_futures_15m_20260817_v3 \
  --config-json '{"timeframe":"15m","model_backend":"qlib","min_symbols":12,"min_fold_rows":125}'
```

Expected: exit 0 only for `RESEARCH_ACCEPTED`, or exit 2 for an evidence-complete
`RESEARCH_REJECTED`. Do not change parameters after observing the result.

- [ ] **Step 3: Reconcile generated evidence independently**

```bash
python3 -m json.tool \
  data/reports/qlib_futures_15m_20260817_v3/report.json >/dev/null
rg -n "RESEARCH_(ACCEPTED|REJECTED)|Research domain|Run identity|15m|Qlib" \
  data/reports/qlib_futures_15m_20260817_v3/report.html \
  data/reports/qlib_futures_15m_20260817_v3/report.md
git diff --check
git status --short
```

Expected: valid JSON, all markers present, no whitespace errors, generated v3
evidence and the pre-existing `qlib/` checkout remain untracked.

- [ ] **Step 4: Run final tests once more after the real-data run**

```bash
python3 -m pytest -q \
  tests/test_futures_trading_isolation.py \
  tests/test_qlib_futures_backtest.py \
  tests/test_futures_research_backtest.py \
  tests/test_financial_truth.py \
  tests/test_web_validation.py \
  tests/test_legacy_ml_boundary.py
```

Expected: zero failures.

- [ ] **Step 5: Commit only any final code/test correction**

If Step 1 or Step 4 required a tested correction:

```bash
git add code tests docs/research-only-ml-engines.md run_tqsim_trader.sh
git diff --cached --check
git commit -m "fix: complete futures hardening verification"
```

Never add `data/reports/qlib_futures_15m_20260817_v3/` or `qlib/`.
