# TianJi ATR Data-Contract Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate causal ATR risk coverage from signal maturity so the TianJi ledger runs on valid holdout data and rejected reports identify the exact failed pipeline stage.

**Architecture:** Preserve one production module and one test module. `build_tianji_scores` retains every market row with independent `atr_ready` and `signal_ready` flags; target generation consumes only signal-ready rows, while the ledger accepts missing ATR on inactive bars and causally retains the last valid ATR for open positions. A mutable run-local counter dictionary captures stage evidence without adding a framework or changing the database.

**Tech Stack:** Python 3.10, pandas, NumPy, pytest, SQLite; no new dependency.

## Global Constraints

- Modify only `code/futures_research_backtest.py` and `tests/test_futures_research_backtest.py` for behavior.
- Preserve the old rejected report at `data/reports/tianji_15m_non_predictive_20260820/` unchanged.
- Keep factors, weights, rebalance cadence, stops, costs, holdout fraction, and gates frozen.
- A new position requires a finite positive decision-time ATR.
- An open position retains only its last causal ATR when a later bar has no mature ATR.
- A later valid ATR updates the trailing stop for the next bar, never the current bar.
- Missing ATR on inactive, non-target market rows must not reject the ledger.
- Non-finite OHLC, invalid target ATR, or an open position without prior valid ATR still fail closed.
- Every result records market, risk, signal, target, trade, and failure-stage counters.
- Run the repaired locked holdout once in a new output directory; do not tune or rerun after seeing it.

---

### Task 1: Split ATR readiness from signal readiness

**Files:**
- Modify: `code/futures_research_backtest.py:696-836`
- Test: `tests/test_futures_research_backtest.py`

**Interfaces:**
- Consumes: `build_tianji_scores(segmented: pd.DataFrame)` canonical 15-minute rows.
- Produces: the same data frame with every market key plus `atr`, `atr_pct`, `atr_ready`, `signal_ready`, directional features, liquidity, score, and sector.
- Produces: `build_tianji_targets` targets only from rows where `signal_ready is True`.

- [ ] **Step 1: Write failing readiness tests**

```python
def test_tianji_keeps_risk_atr_when_directional_signal_is_immature():
    market = make_tianji_market(25)

    scores = research.build_tianji_scores(market)
    last_time = market["trade_time"].max()
    row = scores[
        scores["symbol"].eq("AG_IDX")
        & scores["decision_time"].eq(last_time)
    ].iloc[0]

    assert row["atr_ready"]
    assert np.isfinite(row["atr"])
    assert not row["signal_ready"]
    assert np.isnan(row["score"])


def test_tianji_targets_exclude_immature_signal_rows():
    scores = research.build_tianji_scores(make_tianji_market(40))
    times = pd.DatetimeIndex(sorted(scores["decision_time"].unique()))
    rebalance_time = next(
        time for time in times[::research.TIANJI_REBALANCE_BARS]
        if scores[
            scores["decision_time"].eq(time) & scores["signal_ready"]
        ].shape[0]
    )
    immature = scores[
        scores["decision_time"].eq(rebalance_time) & scores["signal_ready"]
    ].iloc[0].copy()
    immature["signal_ready"] = False
    immature["score"] = 1.0
    decision_time = pd.Timestamp(immature["decision_time"])
    scores = pd.concat([
        scores[~(
            scores["symbol"].eq(immature["symbol"])
            & scores["decision_time"].eq(decision_time)
        )],
        immature.to_frame().T,
    ], ignore_index=True)

    targets, _ = research.build_tianji_targets(scores, decision_time)

    selected = targets[
        targets["decision_time"].eq(decision_time)
        & targets["symbol"].eq(immature["symbol"])
    ]
    assert selected.empty
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py \
  -k 'keeps_risk_atr or excludes_immature_signal'
```

Expected: FAIL because current scores discard the immature row and do not have readiness columns.

- [ ] **Step 3: Replace row deletion with explicit readiness flags**

In `build_tianji_scores`, replace the block beginning at `finite_columns` through score assignment with:

```python
    directional_finite = np.isfinite(
        frame.loc[:, [*TIANJI_FEATURE_COLUMNS, "amihud_20", "close"]]
    ).all(axis=1)
    frame["atr_ready"] = (
        np.isfinite(frame["atr"])
        & np.isfinite(frame["close"])
        & frame["atr"].gt(0.0)
        & frame["close"].gt(0.0)
    )
    frame["atr_pct"] = np.where(
        frame["atr_ready"], frame["atr"] / frame["close"], np.nan
    )
    frame["signal_ready"] = False
    mature = frame[directional_finite & frame["atr_ready"]].copy()
    illiquidity_rank = mature.groupby("decision_time")["amihud_20"].rank(
        pct=True, method="average"
    )
    mature = mature[illiquidity_rank <= 0.80]
    frame.loc[mature.index, "signal_ready"] = True
    ranks = mature.groupby("decision_time")[list(TIANJI_FEATURE_COLUMNS)].rank(
        pct=True, method="average"
    )
    frame["score"] = np.nan
    frame.loc[mature.index, "score"] = ranks.mean(axis=1)
```

Keep all ordered market rows in the return frame. Remove the old `eligible`
column and change target filtering to:

```python
        group = scores[
            scores["decision_time"].eq(decision_time)
            & scores["signal_ready"]
            & scores["score"].notna()
        ]
```

In `build_tianji_evaluation`, count mature rows with:

```python
    mature = scores[scores["signal_ready"]].groupby("symbol").size()
```

Rebuild the fixed universe exactly as before when symbols fail
`config.min_symbol_rows`.

- [ ] **Step 4: Run focused and existing score/target tests**

Run:

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py \
  -k 'tianji_score or tianji_target or keeps_risk_atr or excludes_immature_signal'
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add code/futures_research_backtest.py tests/test_futures_research_backtest.py
git commit -m "fix: separate tianji risk and signal readiness"
```

---

### Task 2: Scope ATR validation to targets and open positions

**Files:**
- Modify: `code/futures_research_backtest.py:1293-1567`
- Modify: `code/futures_research_backtest.py:1665-1685`
- Test: `tests/test_futures_research_backtest.py`

**Interfaces:**
- Consumes: market ATR that may be `NaN` on immature inactive bars.
- Preserves: `simulate_tianji_ledger(targets, rebalance_times, market, cost_bps) -> (trades, bars, daily)`.
- Preserves: finite positive target ATR and position-stored last causal ATR.

- [ ] **Step 1: Write failing scoped-ATR tests**

```python
def test_tianji_inactive_symbol_without_atr_does_not_reject_ledger():
    active = make_tianji_market(4, symbols=("AG_IDX",))
    active["atr"] = 2.0
    inactive = make_tianji_market(4, symbols=("CU_IDX",))
    inactive["atr"] = np.nan
    targets = _single_tianji_target(active)
    decision = targets["decision_time"].item()

    trades, bars, _ = research.simulate_tianji_ledger(
        targets,
        pd.DatetimeIndex([decision]),
        pd.concat([active, inactive], ignore_index=True),
        5,
    )

    assert len(trades) == 1
    assert not bars.empty


def test_tianji_target_without_atr_still_fails_closed():
    market = make_tianji_market(4, symbols=("AG_IDX",))
    market["atr"] = np.nan
    targets = _single_tianji_target(market)
    targets["atr"] = np.nan

    with pytest.raises(ResearchRejected, match="target values"):
        research.simulate_tianji_ledger(
            targets,
            pd.DatetimeIndex([targets["decision_time"].item()]),
            market,
            5,
        )


def test_tianji_open_position_retains_last_atr_through_risk_gap():
    market = make_tianji_market(5, symbols=("AG_IDX",))
    market["atr"] = 2.0
    market.loc[2, ["high", "low", "close", "atr"]] = [110.0, 100.0, 109.0, np.nan]
    market.loc[3, ["open", "high", "low", "close"]] = [109.0, 109.5, 103.0, 104.0]
    targets = _single_tianji_target(market)
    decision = targets["decision_time"].item()

    trades, _, _ = research.simulate_tianji_ledger(
        targets, pd.DatetimeIndex([decision]), market, 0
    )

    assert trades["exit_time"].iloc[0] == market["trade_time"].iloc[3]
    assert trades["exit_open"].iloc[0] == pytest.approx(105.0)


def test_tianji_new_atr_updates_only_next_bar_stop():
    market = make_tianji_market(6, symbols=("AG_IDX",))
    market["atr"] = 2.0
    market.loc[2, ["high", "low", "close", "atr"]] = [110.0, 100.0, 109.0, 4.0]
    market.loc[3, ["open", "high", "low", "close", "atr"]] = [109.0, 112.0, 101.0, 111.0, 1.0]
    market.loc[4, ["open", "high", "low", "close"]] = [111.0, 111.5, 109.0, 110.0]
    targets = _single_tianji_target(market)
    decision = targets["decision_time"].item()

    trades, _, _ = research.simulate_tianji_ledger(
        targets, pd.DatetimeIndex([decision]), market, 0
    )

    assert trades["exit_time"].iloc[0] == market["trade_time"].iloc[4]
    assert trades["exit_open"].iloc[0] == pytest.approx(109.5)
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py \
  -k 'inactive_symbol_without_atr or target_without_atr or retains_last_atr or new_atr_updates'
```

Expected: the inactive and ATR-gap cases FAIL under global ATR validation.

- [ ] **Step 3: Implement scoped validation and causal ATR retention**

Replace global market validation with:

```python
    for column in ("open", "high", "low", "close", "atr"):
        marks[column] = pd.to_numeric(marks[column], errors="coerce")
    if (
        not np.isfinite(marks[["open", "high", "low", "close"]]).all().all()
        or marks[["open", "high", "low", "close"]].le(0.0).any().any()
        or marks["high"].lt(marks[["open", "close"]].max(axis=1)).any()
        or marks["low"].gt(marks[["open", "close"]].min(axis=1)).any()
    ):
        raise ResearchRejected("invalid TianJi market values")
```

Keep existing finite positive target ATR validation. Replace the stop-update ATR
assignment with:

```python
            if np.isfinite(row.atr) and float(row.atr) > 0.0:
                position["atr"] = float(row.atr)
```

Always update the favorable high/low and calculate the next stop from the
position's stored ATR. This retains the last causal ATR through a gap and uses a
new ATR only after the current bar is complete.

In `build_tianji_evaluation`, replace the complete-coverage rejection with:

```python
    target_keys = pd.MultiIndex.from_frame(
        targets.loc[:, ["symbol", "decision_time"]]
        .rename(columns={"decision_time": "trade_time"})
    )
    market_keys = pd.MultiIndex.from_frame(
        evaluation_market.loc[:, ["symbol", "trade_time"]]
    )
    target_market = evaluation_market[market_keys.isin(target_keys)]
    if target_market["atr"].isna().any():
        raise ResearchRejected("missing causal TianJi ATR for target")
```

The ledger's target check remains the final trust boundary.

- [ ] **Step 4: Run ledger and full targeted tests**

Run:

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py \
  -k 'tianji_ or ledger or strategy_metrics or cost_sensitivity'
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add code/futures_research_backtest.py tests/test_futures_research_backtest.py
git commit -m "fix: scope tianji atr validation to risk consumers"
```

---

### Task 3: Report pipeline stage counters on every result

**Files:**
- Modify: `code/futures_research_backtest.py:1633-1770`
- Modify: `code/futures_research_backtest.py:3955-4020`
- Modify: `code/futures_research_backtest.py:4110-4225`
- Modify: `code/futures_research_backtest.py:4320-4395`
- Test: `tests/test_futures_research_backtest.py`

**Interfaces:**
- Adds optional `pipeline_counts: dict | None = None` to `build_tianji_evaluation` and `rejected_result`.
- Adds top-level `pipeline_counts` to accepted and rejected JSON/Markdown/HTML evidence.

- [ ] **Step 1: Write failing counter/report tests**

```python
def test_tianji_rejection_reports_pipeline_stage_counts():
    counts = {
        "market_15m_rows": 100,
        "risk_ready_rows": 80,
        "signal_ready_rows": 60,
        "holdout_market_rows": 20,
        "holdout_risk_ready_rows": 15,
        "target_rows": 4,
        "trade_rows_5bps": 0,
        "failure_stage": "ledger",
    }

    result = research.rejected_result(
        "fixture",
        ResearchConfig(strategy_mode="tianji", timeframe="15m"),
        "fixture rejection",
        pipeline_counts=counts,
    )

    assert result["pipeline_counts"] == counts


def test_tianji_report_renders_pipeline_counts(tmp_path):
    result = research.rejected_result(
        "fixture",
        ResearchConfig(strategy_mode="tianji", timeframe="15m"),
        "fixture rejection",
        pipeline_counts={
            "market_15m_rows": 100, "risk_ready_rows": 80,
            "signal_ready_rows": 60, "holdout_market_rows": 20,
            "holdout_risk_ready_rows": 15, "target_rows": 4,
            "trade_rows_5bps": 0, "failure_stage": "ledger",
        },
    )

    paths = research.write_report(result, tmp_path / "report")

    payload = json.loads(Path(paths["report.json"]).read_text())
    markdown = Path(paths["report.md"]).read_text()
    html = Path(paths["report.html"]).read_text()
    assert payload["pipeline_counts"]["failure_stage"] == "ledger"
    assert "Pipeline counts" in markdown
    assert "流水线计数" in html
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py \
  -k 'pipeline_stage_counts or renders_pipeline_counts'
```

Expected: FAIL because the optional argument and report field do not exist.

- [ ] **Step 3: Add one run-local counter dictionary**

At the start of `run_research`, add:

```python
    pipeline_counts = {}
```

After TianJi segmentation, initialize exact fields:

```python
            pipeline_counts.update({
                "market_15m_rows": int(len(segmented)),
                "risk_ready_rows": 0,
                "signal_ready_rows": 0,
                "holdout_market_rows": 0,
                "holdout_risk_ready_rows": 0,
                "target_rows": 0,
                "trade_rows_5bps": 0,
                "failure_stage": "features",
            })
            base, checks = build_tianji_evaluation(
                segmented, config, pipeline_counts
            )
```

Inside `build_tianji_evaluation`, update after each completed boundary:

```python
    pipeline_counts = pipeline_counts if pipeline_counts is not None else {}
    pipeline_counts["risk_ready_rows"] = int(scores["atr_ready"].sum())
    pipeline_counts["signal_ready_rows"] = int(scores["signal_ready"].sum())
    pipeline_counts["failure_stage"] = "holdout"
```

Immediately after constructing `evaluation_market`, write:

```python
    pipeline_counts["holdout_market_rows"] = int(len(evaluation_market))
    pipeline_counts["holdout_risk_ready_rows"] = int(
        evaluation_market["atr"].notna().sum()
    )
```

Immediately after constructing targets, write:

```python
    pipeline_counts["target_rows"] = int(len(targets))
    pipeline_counts["failure_stage"] = "ledger"
```

After all cost ledgers complete, write:

```python
    pipeline_counts["trade_rows_5bps"] = int(len(trades_by_cost[5]))
    pipeline_counts["failure_stage"] = "complete"
```

Set `context["pipeline_counts"] = pipeline_counts` before `build_result`.
Add `"pipeline_counts": _json_safe(context.get("pipeline_counts", {}))` to
`build_result`.

Change the rejected result signature and payload:

```python
def rejected_result(
    run_id, config, reason, quality=None, pipeline_counts=None
):
    quality_rows = (
        [] if quality is None else _records(quality.reset_index())
    )
    domain = _research_domain(config)
    tianji = getattr(config, "strategy_mode", "predictive") == "tianji"
    return _json_safe({
        "run_id": run_id,
        "status": "RESEARCH_REJECTED",
        "provenance": {},
        "research_domain": domain,
        "run_identity": None,
        "config": asdict(config),
        "features": TIANJI_FEATURE_COLUMNS if tianji else FEATURE_COLUMNS,
        "candidates": domain["selectable_models"],
        "seed": config.seed,
        "selected_candidate": None,
        "selection_scores": [],
        "cutoffs": {},
        "metrics": [],
        "attacks": [],
        "gates": [{
            "id": "RUN_PRECONDITION", "passed": False, "observed": reason,
            "required": "all run preconditions satisfied",
            "affected_fold": None, "reason": reason,
        }],
        "data_quality": quality_rows,
        "fold_metrics": [],
        "symbol_metrics": [],
        "trades": [],
        "limitations": LIMITATIONS,
        "pipeline_counts": pipeline_counts or {},
    })
```

In the `ResearchRejected` handler pass `pipeline_counts=pipeline_counts`.
Render it in Markdown:

```python
    lines.extend([
        "", "## Pipeline counts", "",
        "```json",
        json.dumps(payload.get("pipeline_counts", {}), ensure_ascii=False, sort_keys=True),
        "```",
    ])
```

Render it in HTML as a section using `_html_value`:

```python
    pipeline_html = (
        "<section><h2>流水线计数</h2><pre>"
        f"{_html_value(payload.get('pipeline_counts', {}))}</pre></section>"
    )
```

Insert `pipeline_html` after the research-domain section.

- [ ] **Step 4: Run report tests and the complete futures suites**

Run:

```bash
python3 -m pytest -q \
  tests/test_futures_research_backtest.py tests/test_qlib_futures_backtest.py
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add code/futures_research_backtest.py tests/test_futures_research_backtest.py
git commit -m "feat: report tianji pipeline stage counts"
```

---

### Task 4: Verify and run the repaired locked holdout once

**Files:**
- Preserve: `data/reports/tianji_15m_non_predictive_20260820/`
- Generate, do not commit: `data/reports/tianji_15m_non_predictive_atr_v2_20260820/`

**Interfaces:**
- Consumes: committed repair and `data/ashare_quant.db`.
- Produces: one immutable versioned evidence bundle.

- [ ] **Step 1: Verify before accessing the repaired holdout**

Run:

```bash
python3 -m pytest -q \
  tests/test_futures_research_backtest.py tests/test_qlib_futures_backtest.py
git diff --check
test -f data/reports/tianji_15m_non_predictive_20260820/report.json
test ! -e data/reports/tianji_15m_non_predictive_atr_v2_20260820
```

Expected: tests PASS, old evidence exists, new directory does not.

- [ ] **Step 2: Run the new locked holdout exactly once**

Run:

```bash
python3 code/futures_research_backtest.py \
  --db-path data/ashare_quant.db \
  --output-dir data/reports/tianji_15m_non_predictive_atr_v2_20260820 \
  --config-json '{"strategy_mode":"tianji","timeframe":"15m","min_symbols":8,"min_symbol_rows":1000,"costs_bps":[0,2,5,10,15,20]}'
```

Expected: exit `0` for `RESEARCH_ACCEPTED` or exit `2` for a truthful
`RESEARCH_REJECTED`. Do not change code, factors, risk, or gates after output.

- [ ] **Step 3: Audit the new evidence without rerunning**

Run:

```bash
python3 -m json.tool \
  data/reports/tianji_15m_non_predictive_atr_v2_20260820/report.json >/dev/null
jq '{status,run_id,research_domain,pipeline_counts,metrics,gates,row_counts}' \
  data/reports/tianji_15m_non_predictive_atr_v2_20260820/report.json
```

Expected: valid JSON with non-empty stage counters. If the ledger was reached,
5 bps trades and all four performance gates are explicit.

- [ ] **Step 4: Run final regression verification**

Run:

```bash
python3 -m pytest -q \
  tests/test_futures_research_backtest.py tests/test_qlib_futures_backtest.py
git status --short
```

Expected: tests PASS; old and new report directories remain uncommitted.

- [ ] **Step 5: Report only the observed evidence**

If accepted, report 5 bps payoff ratio, bar drawdown, trades, return, and stress
costs. If rejected, report the exact failed stage/gates and stop without tuning.

---

## Plan Self-Review Checklist

- Risk ATR and directional signal maturity are separate.
- Targets require `signal_ready`; entries require positive target ATR.
- Missing inactive ATR no longer empties the run.
- Open positions never consume future ATR.
- Rejections explain their stage with exact row counts.
- The old report is immutable and the new holdout has one run command.
- No new dependency, database write, model, or live-trading path exists.
