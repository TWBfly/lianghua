# TianJi Asynchronous Exposure Capacity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent asynchronous old-position exits and new entries from exceeding TianJi's frozen `0.4` side and `0.8` gross exposure caps.

**Architecture:** Keep the existing pending-order state machine. Immediately before each pending entry executes, recompute capacity from live positions after stops and exits at that timestamp, clip the requested weight to available side and gross capacity, and discard any unfilled remainder. Preserve post-event exposure assertions as the final invariant.

**Tech Stack:** Python 3.10, pandas, NumPy, pytest; no new dependency.

## Global Constraints

- Modify only `code/futures_research_backtest.py` and `tests/test_futures_research_backtest.py`.
- Do not change factors, target selection, requested weights, rebalance cadence, stops, costs, holdout fraction, or gates.
- Preserve each symbol's next-observed-open execution.
- Process stops and exits before capacity-limited entries at the same timestamp.
- Side exposure must remain `<= 0.4 + 1e-12`; gross exposure `<= 0.8 + 1e-12`; absolute net exposure `<= 0.4 + 1e-12`.
- Skipped or clipped weight remains cash and is never queued or retried.
- Preserve the old and ATR v2 report directories unchanged.
- Run exposure v3 once in a new directory after full verification.

---

### Task 1: Clamp pending entries to live execution capacity

**Files:**
- Modify: `code/futures_research_backtest.py:1410-1465`
- Test: `tests/test_futures_research_backtest.py`

**Interfaces:**
- Preserves: `simulate_tianji_ledger(targets, rebalance_times, market, cost_bps)`.
- Consumes: live `positions` and a pending entry order with requested positive `weight`.
- Produces: executed weight clipped to current side/gross capacity, or no entry.

- [ ] **Step 1: Write the failing asynchronous-session regression test**

```python
def make_async_exposure_case():
    first_longs = ("L1", "L2", "L3", "L4")
    first_shorts = ("SI_IDX", "S2", "S3", "S4")
    second_shorts = ("C_IDX", "S2", "S3", "S4")
    first_decision = pd.Timestamp("2026-01-02 09:00")
    second_decision = pd.Timestamp("2026-01-02 09:15")
    rows = []
    for decision_time, longs, shorts in (
        (first_decision, first_longs, first_shorts),
        (second_decision, first_longs, second_shorts),
    ):
        for direction, symbols in ((1, longs), (-1, shorts)):
            rows.extend({
                "decision_time": decision_time,
                "symbol": symbol,
                "direction": direction,
                "atr": 2.0,
                "atr_pct": 0.02,
                "score": float(number),
                "sector": "TEST",
            } for number, symbol in enumerate(symbols, start=1))
    targets = pd.DataFrame(rows)
    market_rows = []
    all_symbols = sorted(set((*first_longs, *first_shorts, *second_shorts)))
    times = pd.date_range(first_decision, periods=5, freq="15min")
    for time in times:
        for symbol in all_symbols:
            if time == times[2] and symbol == "SI_IDX":
                continue
            market_rows.append({
                "symbol": symbol,
                "trade_time": time,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "atr": 2.0,
            })
    return targets, pd.DatetimeIndex([first_decision, second_decision]), pd.DataFrame(market_rows)


def test_tianji_async_exit_reserves_capacity_until_actual_close():
    targets, rebalances, market = make_async_exposure_case()

    trades, bars, _ = research.simulate_tianji_ledger(
        targets, rebalances, market, 5
    )

    assert bars["gross_exposure"].max() <= 0.8 + 1e-12
    assert bars["net_exposure"].abs().max() <= 0.4 + 1e-12
    assert "C_IDX" not in set(trades["symbol"])
    assert "SI_IDX" in set(trades["symbol"])


def test_tianji_async_capacity_result_is_deterministic_and_not_retried():
    targets, rebalances, market = make_async_exposure_case()
    expected = research.simulate_tianji_ledger(targets, rebalances, market, 5)
    actual = research.simulate_tianji_ledger(
        targets.sample(frac=1, random_state=21),
        rebalances,
        market.sample(frac=1, random_state=22),
        5,
    )

    pd.testing.assert_frame_equal(expected[0], actual[0])
    pd.testing.assert_frame_equal(expected[1], actual[1])
    assert "C_IDX" not in set(actual[0]["symbol"])
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py \
  -k 'async_exit_reserves_capacity or async_capacity_result'
```

Expected: FAIL with `ResearchRejected: invalid TianJi exposure`.

- [ ] **Step 3: Implement entry-time capacity clipping**

Replace the pending-entry block with:

```python
                if order["direction"] and position is None:
                    direction = int(order["direction"])
                    requested_weight = max(0.0, float(order["weight"]))
                    side_used = sum(
                        live["weight"] for live in positions.values()
                        if live["direction"] == direction
                    )
                    gross_used = sum(
                        live["weight"] for live in positions.values()
                    )
                    weight = min(
                        requested_weight,
                        max(0.0, TIANJI_SIDE_EXPOSURE - side_used),
                        max(0.0, 2.0 * TIANJI_SIDE_EXPOSURE - gross_used),
                    )
                    if weight <= 1e-12:
                        continue
                    entry_cost = weight * cost
                    realized_sleeve_pnl -= entry_cost
                    timestamp_turnover += weight
                    positions[symbol] = {
                        "direction": direction,
                        "weight": weight,
                        "entry_time": timestamp,
                        "entry_price": float(row.open),
                        "entry_cost": entry_cost,
                        "atr": float(order["atr"]),
                        "stop": float(row.open) - direction * float(order["atr"]),
                        "favorable": float(row.open),
                        "decision_time": order["decision_time"],
                    }
```

Do not create another pending entry for the unfilled amount. Keep the existing
post-mark exposure rejection unchanged.

- [ ] **Step 4: Run targeted and complete regression tests**

Run:

```bash
python3 -m pytest -q tests/test_futures_research_backtest.py \
  -k 'async_ or tianji_ or ledger or strategy_metrics or cost_sensitivity'
python3 -m pytest -q \
  tests/test_futures_research_backtest.py tests/test_qlib_futures_backtest.py
```

Expected: all tests PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add code/futures_research_backtest.py tests/test_futures_research_backtest.py
git commit -m "fix: enforce tianji entry-time exposure capacity"
```

---

### Task 2: Verify and run exposure v3 once

**Files:**
- Preserve: `data/reports/tianji_15m_non_predictive_20260820/`
- Preserve: `data/reports/tianji_15m_non_predictive_atr_v2_20260820/`
- Generate, do not commit: `data/reports/tianji_15m_non_predictive_exposure_v3_20260820/`

**Interfaces:**
- Consumes: committed capacity repair and `data/ashare_quant.db`.
- Produces: one new immutable report bundle.

- [ ] **Step 1: Verify preconditions**

Run:

```bash
python3 -m pytest -q \
  tests/test_futures_research_backtest.py tests/test_qlib_futures_backtest.py
git diff --check
test -f data/reports/tianji_15m_non_predictive_20260820/report.json
test -f data/reports/tianji_15m_non_predictive_atr_v2_20260820/report.json
test ! -e data/reports/tianji_15m_non_predictive_exposure_v3_20260820
```

Expected: tests PASS; both old reports exist; v3 does not.

- [ ] **Step 2: Run the locked v3 exactly once**

Run:

```bash
python3 code/futures_research_backtest.py \
  --db-path data/ashare_quant.db \
  --output-dir data/reports/tianji_15m_non_predictive_exposure_v3_20260820 \
  --config-json '{"strategy_mode":"tianji","timeframe":"15m","min_symbols":8,"min_symbol_rows":1000,"costs_bps":[0,2,5,10,15,20]}'
```

Expected: exit `0` for accepted or `2` for a truthful rejection. Do not alter
code or parameters after output.

- [ ] **Step 3: Audit v3 without rerunning**

Run:

```bash
python3 -m json.tool \
  data/reports/tianji_15m_non_predictive_exposure_v3_20260820/report.json >/dev/null
jq '{status,run_id,pipeline_counts,metrics,gates,row_counts}' \
  data/reports/tianji_15m_non_predictive_exposure_v3_20260820/report.json
```

Expected: valid JSON. If the ledger completes, `trade_rows_5bps > 0` and the
four performance gates contain observed values.

- [ ] **Step 4: Run final verification**

Run:

```bash
python3 -m pytest -q \
  tests/test_futures_research_backtest.py tests/test_qlib_futures_backtest.py
git status --short
```

Expected: tests PASS; all report directories remain uncommitted.

- [ ] **Step 5: Report observed performance or rejection**

Report only v3 evidence. Do not claim improvement unless payoff ratio,
15-minute drawdown, trade count, and return are present in the 5 bps holdout.

---

## Plan Self-Review Checklist

- The real `SI_IDX` asynchronous-exit pattern has a deterministic regression.
- Capacity is calculated from live positions, not intended post-exit positions.
- Unfilled weight remains cash and never becomes a delayed stale entry.
- Existing exposure assertions remain unchanged.
- Old evidence is immutable and v3 has one run command.
- No factor, parameter, gate, dependency, database, or live-trading change exists.
