# TianJi Verified-Index Development Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair verified-index data and backtest evidence, evaluate three frozen non-predictive 15-minute candidates on development-only folds, and emit either `DEVELOPMENT_CANDIDATE` or `DEVELOPMENT_REJECTED` under payoff `>=3`, drawdown `<=15%`, positive-return, and 200-trade gates.

**Architecture:** Keep canonical loading, 5m-to-15m reconstruction, features, and execution in `futures_research_backtest.py`. Add complete sector/universe and attribution helpers there, while a small `tianji_development_research.py` module owns development folds, three fixed candidate target builders, deterministic selection, and development-only reporting. No viewed holdout timestamp enters candidate evaluation.

**Tech Stack:** Python 3.10, pandas, NumPy, pytest, SQLite; no new dependency.

## Global Constraints

- Official inputs remain provenance-approved `5m` weighted-index rows reconstructed to `15m`.
- Direct database `15m` rows remain forensic-only because they have no metadata.
- Development data ends at `2026-06-26 10:30:00`; all later viewed data is forbidden.
- Runtime candidates use OHLCV only, with no model, label, prediction, or probability.
- Development gates at 5 bps per entry and exit: payoff ratio `>=3.0`, bar drawdown `<=0.15`, total return `>0`, trades `>=200`.
- Candidate folds must all have positive return; costs must be monotone.
- Passing status is only `DEVELOPMENT_CANDIDATE`, never `RESEARCH_ACCEPTED`.
- Existing report directories and the database are immutable.

---

### Task 1: Complete the verified universe and sector data contract

**Files:**
- Modify: `code/futures_research_backtest.py:34-72`
- Modify: `code/futures_research_backtest.py:125-228`
- Test: `tests/test_futures_research_backtest.py`

**Interfaces:**
- Produces: `TIANJI_SECTORS: dict[str, str]` covering every metadata symbol.
- Produces: `validate_tianji_sector_map(symbols) -> None`.
- Produces: `tianji_universe_table(quality, scores, trades, manifest) -> pd.DataFrame`.

- [ ] **Step 1: Write failing sector and universe tests**

```python
def test_tianji_sector_map_covers_verified_metadata_symbols(tmp_path):
    db_path = tmp_path / "futures.db"
    bars = make_bars(60)
    _write_source(db_path, bars)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO futures_series_metadata VALUES "
            "('NEW_IDX','5m','new.txt','new weighted','WEIGHTED_INDEX',"
            "'utf-8',?,60,'2026-01-01','2026-01-02','now')",
            ("b" * 64,),
        )

    with pytest.raises(ResearchRejected, match="sector mapping"):
        research.validate_tianji_sector_map(("AG_IDX", "NEW_IDX"))


def test_tianji_universe_table_reconciles_included_mature_and_traded():
    quality = pd.DataFrame({
        "symbol": ["AG_IDX", "AU_IDX", "BB_IDX"],
        "status": ["INCLUDED", "INCLUDED", "EXCLUDED"],
        "reason": ["", "", "ZERO_VOLUME_FRACTION"],
    }).set_index("symbol")
    scores = pd.DataFrame({
        "symbol": ["AG_IDX", "AU_IDX"],
        "atr_ready": [True, True],
        "signal_ready": [True, False],
    })
    trades = pd.DataFrame({"symbol": ["AG_IDX"], "cost_bps": [5]})
    manifest = [
        {"symbol": "AG_IDX", "source_path": "ag.txt", "source_sha256": "a" * 64},
        {"symbol": "AU_IDX", "source_path": "au.txt", "source_sha256": "b" * 64},
    ]

    table = research.tianji_universe_table(quality, scores, trades, manifest)

    rows = table.set_index("symbol")
    assert rows.loc["AG_IDX", ["included", "mature", "traded"]].tolist() == [True, True, True]
    assert rows.loc["AU_IDX", ["included", "mature", "traded"]].tolist() == [True, False, False]
    assert rows.loc["BB_IDX", "excluded_reason"] == "ZERO_VOLUME_FRACTION"
```

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py \
  -k 'sector_map_covers or universe_table_reconciles'
```

Expected: FAIL because the validator/table do not exist and `OTHER` is still allowed.

- [ ] **Step 3: Replace the partial sector map and add universe helpers**

Use exact broad asset groups:

```python
TIANJI_SECTOR_GROUPS = {
    "PRECIOUS": ("AG_IDX", "AU_IDX", "PD_IDX", "PT_IDX"),
    "BASE_METALS": (
        "AD_IDX", "AL_IDX", "AO_IDX", "BC_IDX", "CU_IDX", "LC_IDX",
        "NI_IDX", "PB_IDX", "PS_IDX", "SI_IDX", "SN_IDX", "SS_IDX", "ZN_IDX",
    ),
    "FERROUS": ("HC_IDX", "I_IDX", "JM_IDX", "J_IDX", "RB_IDX", "SF_IDX", "SM_IDX", "WR_IDX"),
    "ENERGY": ("BU_IDX", "FU_IDX", "LU_IDX", "PG_IDX", "SC_IDX"),
    "CHEMICALS": (
        "BR_IDX", "BZ_IDX", "EB_IDX", "EG_IDX", "L-F_IDX", "L_IDX",
        "MA_IDX", "NR_IDX", "PF_IDX", "PL_IDX", "PP-F_IDX", "PP_IDX",
        "PR_IDX", "PX_IDX", "RU_IDX", "SA_IDX", "SH_IDX", "TA_IDX",
        "UR_IDX", "V-F_IDX", "V_IDX",
    ),
    "AGRICULTURE": (
        "AP_IDX", "A_IDX", "B_IDX", "CF_IDX", "CJ_IDX", "CS_IDX", "CY_IDX",
        "C_IDX", "JD_IDX", "LH_IDX", "M_IDX", "OI_IDX", "PK_IDX", "P_IDX",
        "RM_IDX", "RR_IDX", "RS_IDX", "SR_IDX", "Y_IDX",
    ),
    "FORESTRY_BUILDING": ("BB_IDX", "FB_IDX", "FG_IDX", "LG_IDX", "OP_IDX", "SP_IDX"),
    "FINANCIAL": ("IC_IDX", "IF_IDX", "IH_IDX", "IM_IDX", "TF_IDX", "TL_IDX", "TS_IDX", "T_IDX"),
    "SHIPPING": ("EC_IDX",),
}
TIANJI_SECTORS = {
    symbol: sector
    for sector, symbols in TIANJI_SECTOR_GROUPS.items()
    for symbol in symbols
}


def validate_tianji_sector_map(symbols):
    missing = sorted(set(map(str, symbols)) - set(TIANJI_SECTORS))
    if missing:
        raise ResearchRejected(
            f"missing TianJi sector mapping: {', '.join(missing)}"
        )


def tianji_universe_table(quality, scores, trades, manifest):
    symbols = sorted(set(quality.index.astype(str)) | set(scores["symbol"].astype(str)))
    validate_tianji_sector_map(symbols)
    manifest_by_symbol = {row["symbol"]: row for row in manifest}
    mature = set(scores.loc[scores["signal_ready"], "symbol"].astype(str))
    traded = set(trades.loc[trades["cost_bps"].eq(5), "symbol"].astype(str))
    rows = []
    for symbol in symbols:
        q = quality.loc[symbol] if symbol in quality.index else pd.Series(dtype=object)
        source = manifest_by_symbol.get(symbol, {})
        rows.append({
            "symbol": symbol,
            "sector": TIANJI_SECTORS[symbol],
            "included": q.get("status") == "INCLUDED",
            "mature": symbol in mature,
            "traded": symbol in traded,
            "excluded_reason": q.get("reason", ""),
            "source_path": source.get("source_path"),
            "source_sha256": source.get("source_sha256"),
        })
    return pd.DataFrame(rows)
```

Call `validate_tianji_sector_map` before target construction. Replace
`.fillna("OTHER")` with `.map(TIANJI_SECTORS)` and fail if any value is null.

- [ ] **Step 4: Run data-contract and full current suites**

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py \
  -k 'sector or universe or load_rejects or 15m_resampling'
python3 -m pytest -q tests/test_futures_research_backtest.py tests/test_qlib_futures_backtest.py
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add code/futures_research_backtest.py tests/test_futures_research_backtest.py
git commit -m "fix: complete tianji universe data contract"
```

---

### Task 2: Export capacity, cost, and per-symbol attribution

**Files:**
- Modify: `code/futures_research_backtest.py:1303-1625`
- Modify: `code/futures_research_backtest.py:3900-4400`
- Test: `tests/test_futures_research_backtest.py`

**Interfaces:**
- Extends TianJi bar rows with requested/executed/clipped/skipped entry evidence.
- Produces: `tianji_symbol_metrics(trades) -> pd.DataFrame`.
- Adds `universe` and non-empty `symbol_metrics` tables to TianJi reports.

- [ ] **Step 1: Write failing attribution tests**

```python
def test_tianji_ledger_reconciles_requested_executed_and_clipped_weight():
    targets, rebalances, market = make_async_exposure_case()

    trades, bars, _ = research.simulate_tianji_ledger(targets, rebalances, market, 5)

    assert bars["requested_entry_weight"].sum() >= bars["executed_entry_weight"].sum()
    assert bars["requested_entry_weight"].sum() == pytest.approx(
        bars["executed_entry_weight"].sum() + bars["clipped_entry_weight"].sum()
    )
    assert bars["skipped_entries"].sum() >= 1


def test_tianji_symbol_metrics_reconcile_trade_pnl_and_costs():
    trades = pd.DataFrame({
        "symbol": ["AG_IDX", "AG_IDX", "AU_IDX"],
        "cost_bps": [5, 5, 5],
        "sleeve_pnl": [0.03, -0.01, 0.02],
        "gross_return": [0.04, -0.005, 0.03],
        "weight": [1.0, 1.0, 1.0],
        "entry_cost": [0.005, 0.0025, 0.005],
        "exit_cost": [0.005, 0.0025, 0.005],
        "exit_reason": ["SIGNAL", "STOP", "STOP"],
        "exit_time": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-01"]),
    })

    metrics = research.tianji_symbol_metrics(trades).set_index("symbol")

    assert metrics.loc["AG_IDX", "net_pnl"] == pytest.approx(0.02)
    assert metrics.loc["AG_IDX", "entry_cost"] == pytest.approx(0.0075)
    assert metrics.loc["AG_IDX", "exit_cost"] == pytest.approx(0.0075)
    assert metrics.loc["AG_IDX", "trades"] == 2
    assert metrics.loc["AG_IDX", "payoff_ratio"] == pytest.approx(3.0)
```

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py \
  -k 'requested_executed_and_clipped or symbol_metrics_reconcile'
```

Expected: FAIL because the evidence columns/helper do not exist.

- [ ] **Step 3: Add minimal ledger counters and trade attribution**

Initialize per timestamp:

```python
        requested_entry_weight = 0.0
        executed_entry_weight = 0.0
        clipped_entry_weight = 0.0
        skipped_entries = 0
```

At each pending entry:

```python
                    requested_entry_weight += requested_weight
                    executed_entry_weight += weight
                    clipped_entry_weight += requested_weight - weight
                    skipped_entries += int(weight <= 1e-12)
```

Do not `continue` before recording skipped evidence. Open only when
`weight > 1e-12`. Add all four values to each bar row.

Implement:

```python
def tianji_symbol_metrics(trades):
    columns = (
        "symbol", "cost_bps", "trades", "gross_pnl", "entry_cost",
        "exit_cost", "net_pnl", "win_rate", "payoff_ratio", "profit_factor",
        "closed_trade_max_drawdown", "stop_exits", "signal_exits",
        "terminal_exits",
    )
    rows = []
    for (symbol, cost_bps), group in trades.groupby(["symbol", "cost_bps"], sort=True):
        pnl = group["sleeve_pnl"].astype(float)
        winners = pnl[pnl > 0.0]
        losers = -pnl[pnl < 0.0]
        curve = pnl.cumsum().to_numpy(float)
        peak = np.maximum.accumulate(np.r_[0.0, curve])
        drawdown = peak - np.r_[0.0, curve]
        reasons = group["exit_reason"].value_counts()
        rows.append({
            "symbol": symbol,
            "cost_bps": float(cost_bps),
            "trades": int(len(group)),
            "gross_pnl": float((group["gross_return"] * group["weight"]).sum()),
            "entry_cost": float(group["entry_cost"].sum()),
            "exit_cost": float(group["exit_cost"].sum()),
            "net_pnl": float(pnl.sum()),
            "win_rate": float((pnl > 0.0).mean()),
            "payoff_ratio": float(winners.mean() / losers.mean()) if len(winners) and len(losers) else 0.0,
            "profit_factor": float(winners.sum() / losers.sum()) if len(winners) and len(losers) else 0.0,
            "closed_trade_max_drawdown": float(drawdown.max()),
            "stop_exits": int(reasons.get("STOP", 0)),
            "signal_exits": int(reasons.get("SIGNAL", 0)),
            "terminal_exits": int(reasons.get("TERMINAL_CLOSE", 0)),
        })
    return pd.DataFrame(rows, columns=columns)
```

Populate `holdout["symbol_metrics"]` from all cost trades and include the
universe table in `build_result`. Add `universe.csv` to `REPORT_FILES`,
`CSV_COLUMNS`, writer tables, row-count reconciliation, Markdown, and HTML.

- [ ] **Step 4: Run attribution/report and complete suites**

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py \
  -k 'tianji_ or report or reconcile'
python3 -m pytest -q tests/test_futures_research_backtest.py tests/test_qlib_futures_backtest.py
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add code/futures_research_backtest.py tests/test_futures_research_backtest.py
git commit -m "feat: add tianji universe and attribution evidence"
```

---

### Task 3: Add three frozen development candidates and chronological folds

**Files:**
- Create: `code/tianji_development_research.py`
- Create: `tests/test_tianji_development_research.py`
- Modify: `code/futures_research_backtest.py` for optional trailing activation

**Interfaces:**
- Produces: `development_folds(times, forbidden_start) -> tuple[DatetimeIndex, ...]`.
- Produces: `candidate_targets(scores, market, candidate, fold_times) -> (targets, rebalance_times)`.
- Produces exactly three candidate names: `continuation`, `reversal`, `timeseries_donchian`.

- [ ] **Step 1: Write failing fold, candidate, and runtime-contract tests**

```python
def test_development_folds_are_chronological_and_before_viewed_holdout():
    times = pd.date_range("2025-10-16", "2026-06-26 10:30", freq="15min")
    folds = development.development_folds(
        times, pd.Timestamp("2026-06-26 10:45")
    )
    assert len(folds) == 3
    assert all(fold.max() < pd.Timestamp("2026-06-26 10:45") for fold in folds)
    assert all(left.max() < right.min() for left, right in zip(folds, folds[1:]))


def test_development_candidate_domain_is_exact_and_non_predictive():
    assert development.CANDIDATES == (
        "continuation", "reversal", "timeseries_donchian"
    )
    source = inspect.getsource(development.candidate_targets)
    assert all(word not in source for word in ("label", "probability", "predict"))


def test_candidate_targets_are_sparse_paired_and_use_three_r_trailing():
    symbols = (
        "AG_IDX", "AU_IDX", "AL_IDX", "CU_IDX", "RB_IDX", "I_IDX",
        "SC_IDX", "FU_IDX", "MA_IDX", "TA_IDX", "M_IDX", "C_IDX",
        "CF_IDX", "SR_IDX", "IF_IDX", "IC_IDX", "RU_IDX", "SA_IDX",
        "SN_IDX", "ZN_IDX",
    )
    scores = research.build_tianji_scores(make_tianji_market(96, symbols=symbols))
    scores["prior_breakout_up_20"] = False
    scores["prior_breakout_down_20"] = False
    rebalance_time = pd.Timestamp(sorted(scores["decision_time"].unique())[40])
    at_time = scores["decision_time"].eq(rebalance_time)
    selected = scores[at_time].sort_values("symbol").index
    scores.loc[selected, "signal_ready"] = True
    scores.loc[selected, "score"] = np.linspace(0.01, 0.99, len(selected))
    scores.loc[selected, [
        "signed_kaufman_efficiency_20", "donchian_position_20",
        "momentum_acceleration_5_20", "intraday_intensity_10",
    ]] = 0.0
    shorts, longs = selected[:2], selected[-2:]
    scores.loc[longs, [
        "signal_ready", "score", "signed_kaufman_efficiency_20",
        "donchian_position_20", "momentum_acceleration_5_20",
        "intraday_intensity_10",
    ]] = [True, 0.99, 0.5, 0.9, 0.1, 0.5]
    scores.loc[shorts, [
        "signal_ready", "score", "signed_kaufman_efficiency_20",
        "donchian_position_20", "momentum_acceleration_5_20",
        "intraday_intensity_10",
    ]] = [True, 0.01, -0.5, -0.9, -0.1, -0.5]
    fold = pd.DatetimeIndex([rebalance_time])
    targets, _ = development.candidate_targets(
        scores, pd.DataFrame(), "continuation", fold
    )
    for _, group in targets.groupby("decision_time"):
        assert group["direction"].eq(1).sum() == group["direction"].eq(-1).sum()
        assert group["direction"].eq(1).sum() <= 2
    assert targets["trail_activation_r"].eq(3.0).all()
```

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m pytest -q tests/test_tianji_development_research.py
```

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement fixed folds, candidates, and 3R trailing**

Create `code/tianji_development_research.py` with:

```python
from __future__ import annotations
import numpy as np
import pandas as pd
from futures_research_backtest import (
    ResearchRejected, TIANJI_REBALANCE_BARS, TIANJI_SECTOR_LIMIT,
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
    frame = scores[scores["decision_time"].isin(fold_times) & scores["signal_ready"]].copy()
    percentile = frame.groupby("decision_time")["score"].rank(pct=True, method="average")
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
    rebalance_times = pd.DatetimeIndex(sorted(frame["decision_time"].unique()))[::TIANJI_REBALANCE_BARS]
    for time in rebalance_times:
        at_time = frame[frame["decision_time"].eq(time)]
        longs = _tianji_leg(at_time[long_mask.loc[at_time.index]], 1)[:2]
        shorts = _tianji_leg(at_time[short_mask.loc[at_time.index]], -1)[:2]
        count = min(len(longs), len(shorts))
        rows.extend(longs[:count])
        rows.extend(shorts[:count])
    targets = pd.DataFrame(rows, columns=(
        "decision_time", "symbol", "direction", "atr", "atr_pct", "score",
        "sector",
    ))
    targets["trail_activation_r"] = 3.0
    return targets, rebalance_times
```

Extend `_tianji_segment_features` with prior channel breakout booleans based on
shifted 20-bar highs/lows, and keep them in scores.

In `simulate_tianji_ledger`, copy `trail_activation_r` from target to pending
and position, defaulting to `0.0`. Update a trailing stop only when favorable
movement divided by entry ATR is at least that value. The initial one-ATR stop
always remains active.

- [ ] **Step 4: Run candidate and complete existing tests**

```bash
python3 -m pytest -q tests/test_tianji_development_research.py
python3 -m pytest -q tests/test_futures_research_backtest.py tests/test_qlib_futures_backtest.py
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add code/tianji_development_research.py tests/test_tianji_development_research.py \
  code/futures_research_backtest.py
git commit -m "feat: add frozen tianji development candidates"
```

---

### Task 4: Evaluate deterministic development gates and emit report

**Files:**
- Modify: `code/tianji_development_research.py`
- Modify: `tests/test_tianji_development_research.py`
- Create: `code/run_tianji_development_research.py`

**Interfaces:**
- Produces: `evaluate_development(segmented, quality, config) -> dict`.
- Produces: `select_development_candidate(candidate_rows) -> str | None`.
- Writes: `development_report.json`, `candidate_metrics.csv`, `symbol_metrics.csv`, `development_report.md`.

- [ ] **Step 1: Write failing gate and selection tests**

```python
def test_development_gates_require_payoff_three_drawdown_and_positive_return():
    passing = {"payoff_ratio": 3.0, "max_drawdown": 0.15, "total_return": 0.01, "trades": 200}
    assert development.development_gates(passing)["passed"]
    for name, value in (("payoff_ratio", 2.99), ("max_drawdown", 0.151), ("total_return", 0.0), ("trades", 199)):
        metrics = {**passing, name: value}
        assert not development.development_gates(metrics)["passed"]


def test_development_selection_uses_worst_fold_then_drawdown_then_turnover():
    rows = pd.DataFrame([
        {"candidate": "continuation", "eligible": True, "worst_payoff": 3.2, "worst_drawdown": 0.12, "turnover": 10.0},
        {"candidate": "reversal", "eligible": True, "worst_payoff": 3.2, "worst_drawdown": 0.10, "turnover": 12.0},
        {"candidate": "timeseries_donchian", "eligible": True, "worst_payoff": 3.1, "worst_drawdown": 0.08, "turnover": 5.0},
    ])
    assert development.select_development_candidate(rows) == "reversal"


def test_development_status_never_claims_research_acceptance():
    assert development.development_status("continuation") == "DEVELOPMENT_CANDIDATE"
    assert development.development_status(None) == "DEVELOPMENT_REJECTED"
```

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m pytest -q tests/test_tianji_development_research.py \
  -k 'development_gates or development_selection or development_status'
```

Expected: FAIL because evaluation/gate helpers do not exist.

- [ ] **Step 3: Implement fixed gates, selection, and atomic report**

Add:

```python
def development_gates(metrics):
    checks = {
        "payoff_ratio": float(metrics["payoff_ratio"]) >= 3.0,
        "max_drawdown": float(metrics["max_drawdown"]) <= 0.15,
        "positive_return": float(metrics["total_return"]) > 0.0,
        "minimum_trades": int(metrics["trades"]) >= 200,
    }
    return {"passed": all(checks.values()), "checks": checks}


def select_development_candidate(rows):
    eligible = rows[rows["eligible"]].sort_values(
        ["worst_payoff", "worst_drawdown", "turnover", "candidate"],
        ascending=[False, True, True, True], kind="stable",
    )
    return None if eligible.empty else str(eligible.iloc[0]["candidate"])


def development_status(selected):
    return "DEVELOPMENT_CANDIDATE" if selected else "DEVELOPMENT_REJECTED"


def _combined_metrics(fold_results):
    trades = pd.concat(
        [result["trades"] for result in fold_results], ignore_index=True
    )
    pnl = trades["sleeve_pnl"].astype(float) if len(trades) else pd.Series(dtype=float)
    winners = pnl[pnl > 0.0]
    losers = -pnl[pnl < 0.0]
    return {
        "payoff_ratio": float(winners.mean() / losers.mean())
        if len(winners) and len(losers) else 0.0,
        "max_drawdown": max(
            (result["metrics"]["max_drawdown"] for result in fold_results),
            default=0.0,
        ),
        "total_return": float(np.prod([
            1.0 + result["metrics"]["total_return"] for result in fold_results
        ]) - 1.0),
        "trades": int(len(trades)),
        "turnover": float(sum(
            result["metrics"]["turnover"] for result in fold_results
        )),
    }


def evaluate_development(segmented, quality, config):
    if pd.Timestamp(segmented["trade_time"].max()) >= FORBIDDEN_HOLDOUT_START:
        segmented = segmented[
            segmented["trade_time"] < FORBIDDEN_HOLDOUT_START
        ].copy()
    scores = build_tianji_scores(segmented)
    if scores["decision_time"].ge(FORBIDDEN_HOLDOUT_START).any():
        raise ResearchRejected("viewed holdout entered development scores")
    folds = development_folds(scores["decision_time"].unique())
    atr = scores[["symbol", "decision_time", "atr"]].rename(
        columns={"decision_time": "trade_time"}
    )
    market = segmented.merge(
        atr, on=["symbol", "trade_time"], how="left", validate="one_to_one"
    )
    candidate_rows = []
    fold_rows = []
    candidate_fold_results = {}
    for candidate in CANDIDATES:
        results = []
        for number, fold in enumerate(folds, start=1):
            targets, rebalances = candidate_targets(
                scores, market, candidate, fold
            )
            fold_market = market[market["trade_time"].isin(fold)].copy()
            if targets.empty:
                trades = pd.DataFrame(columns=["sleeve_pnl"])
                metrics = {
                    "payoff_ratio": 0.0, "max_drawdown": 0.0,
                    "total_return": 0.0, "trades": 0, "turnover": 0.0,
                }
            else:
                trades, bars, daily = simulate_tianji_ledger(
                    targets, rebalances, fold_market, 5
                )
                metrics = tianji_metrics(trades, bars, daily)
            results.append({"trades": trades, "metrics": metrics})
            fold_rows.append({
                "candidate": candidate, "fold": number, "cost_bps": 5,
                **metrics,
            })
        combined = _combined_metrics(results)
        gate = development_gates(combined)
        fold_returns = [result["metrics"]["total_return"] for result in results]
        candidate_rows.append({
            "candidate": candidate,
            "eligible": bool(gate["passed"] and all(value > 0.0 for value in fold_returns)),
            "worst_payoff": min(
                result["metrics"]["payoff_ratio"] for result in results
            ),
            "worst_drawdown": max(
                result["metrics"]["max_drawdown"] for result in results
            ),
            **combined,
            "gates": gate,
        })
        candidate_fold_results[candidate] = results
    candidate_frame = pd.DataFrame(candidate_rows)
    selected = select_development_candidate(candidate_frame)
    stress_rows = []
    if selected:
        for cost in (0, 2, 10, 15, 20):
            results = []
            for fold in folds:
                targets, rebalances = candidate_targets(
                    scores, market, selected, fold
                )
                fold_market = market[market["trade_time"].isin(fold)].copy()
                trades, bars, daily = simulate_tianji_ledger(
                    targets, rebalances, fold_market, cost
                )
                results.append({
                    "trades": trades,
                    "metrics": tianji_metrics(trades, bars, daily),
                })
            stress_rows.append({"cost_bps": cost, **_combined_metrics(results)})
    return {
        "status": development_status(selected),
        "selected_candidate": selected,
        "candidate_metrics": candidate_frame,
        "fold_metrics": pd.DataFrame(fold_rows),
        "stress_metrics": pd.DataFrame(stress_rows),
        "quality": quality,
        "forbidden_holdout_start": FORBIDDEN_HOLDOUT_START,
    }
```

Create `run_tianji_development_research.py`:

```python
from __future__ import annotations
import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path
import pandas as pd
from futures_research_backtest import (
    ResearchConfig, _json_safe, _prepare_segmented_bars, load_futures_bars,
)
from tianji_development_research import evaluate_development


def write_development_report(result, output_dir):
    output = Path(output_dir).resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise FileExistsError(f"refusing to overwrite development evidence: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        candidate_frame = result["candidate_metrics"].copy()
        candidate_frame["gates"] = candidate_frame["gates"].map(
            lambda value: json.dumps(value, sort_keys=True)
        )
        candidate_frame.to_csv(temporary / "candidate_metrics.csv", index=False)
        result["fold_metrics"].to_csv(temporary / "fold_metrics.csv", index=False)
        result["stress_metrics"].to_csv(temporary / "stress_metrics.csv", index=False)
        payload = _json_safe(result)
        (temporary / "development_report.json").write_text(
            json.dumps(
                payload, ensure_ascii=False, indent=2, sort_keys=True,
                allow_nan=False,
            ) + "\n",
            encoding="utf-8",
        )
        lines = [
            f"# {payload['status']}", "",
            f"Selected candidate: `{payload['selected_candidate']}`", "",
            "Development-only weighted-index research; not final OOS evidence.",
        ]
        (temporary / "development_report.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
        json.loads((temporary / "development_report.json").read_text())
        if output.exists():
            output.rmdir()
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    config = ResearchConfig(
        strategy_mode="tianji", timeframe="15m",
        min_symbols=8, min_symbol_rows=1000,
    )
    bars = load_futures_bars(args.db_path)
    segmented, quality = _prepare_segmented_bars(bars, config)
    result = evaluate_development(segmented, quality, config)
    write_development_report(result, args.output_dir)
    print(json.dumps({
        "status": result["status"],
        "selected_candidate": result["selected_candidate"],
        "output_dir": str(args.output_dir.resolve()),
    }, ensure_ascii=False))
    return 0 if result["selected_candidate"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run all tests and the real development research once**

```bash
python3 -m pytest -q tests/test_tianji_development_research.py \
  tests/test_futures_research_backtest.py tests/test_qlib_futures_backtest.py
test ! -e data/reports/tianji_development_20260820
python3 code/run_tianji_development_research.py \
  --db-path data/ashare_quant.db \
  --output-dir data/reports/tianji_development_20260820
python3 -m json.tool data/reports/tianji_development_20260820/development_report.json >/dev/null
jq '{status,selected_candidate,candidate_metrics,fold_metrics,stress_metrics}' \
  data/reports/tianji_development_20260820/development_report.json
```

Expected: tests PASS; report is either development candidate or rejection.

- [ ] **Step 5: Commit Task 4 and report evidence**

```bash
git add code/tianji_development_research.py code/run_tianji_development_research.py \
  tests/test_tianji_development_research.py
git commit -m "feat: evaluate tianji development candidates"
```

Do not commit generated reports. Report exact candidate/fold metrics and do not
claim final OOS acceptance.

---

## Plan Self-Review Checklist

- Verified 5m metadata remains the only official data input.
- Sector mapping covers every current metadata symbol and unknowns fail closed.
- Universe, symbol, cost, and capacity evidence reconcile.
- Exactly three non-predictive candidates exist.
- Viewed holdout timestamps are absent from development folds.
- Payoff 3, drawdown 15%, positive return, and 200 trades are hard gates.
- Status cannot become `RESEARCH_ACCEPTED`.
- No data fabrication, dependency, database mutation, or live-trading claim exists.
