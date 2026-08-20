# TianJi Asynchronous Exposure Capacity Design

## Root Cause

The ATR v2 holdout reached the ledger but failed with
`invalid TianJi exposure`. Runtime evidence captured the first violation at
`2026-06-26 21:30:00`:

- long weight: `0.4000000000`;
- short weight: `0.4863912365`;
- gross exposure: `0.8863912365`;
- pending exit: `SI_IDX`, short `0.0863912365`;
- `SI_IDX` had no market bar at that timestamp.

The rebalance allocator excluded positions scheduled for exit when calculating
new capacity. New short targets therefore filled the assumed released budget at
their next opens while the old `SI_IDX` short remained live until its own next
open. The bug is an asynchronous execution-budget race, not a strategy signal,
ATR, or market-data failure.

## Decision

Enforce capacity at actual entry execution. Preserve each symbol's next-open
execution and deterministic symbol ordering. Immediately before opening a
pending position, calculate capacity from live positions after all stops and
exits already processed at that timestamp.

For requested direction `d` and requested weight `w`:

- `side_used = sum(weight for live positions with direction d)`;
- `gross_used = sum(weight for all live positions)`;
- `side_available = max(0, 0.4 - side_used)`;
- `gross_available = max(0, 0.8 - gross_used)`;
- `executed_weight = min(w, side_available, gross_available)`.

If `executed_weight <= 1e-12`, skip the entry. If it is smaller than requested,
open only the executable portion. The remainder stays cash and is neither
queued nor retried. This preserves next-open semantics and prevents stale
signals from entering later.

The existing post-event invariants remain mandatory:

- long weight `<= 0.4 + 1e-12`;
- short weight `<= 0.4 + 1e-12`;
- gross exposure `<= 0.8 + 1e-12`;
- absolute net exposure `<= 0.4 + 1e-12`.

## Event Order

At each market timestamp and deterministic symbol order:

1. process gap-through protective stops;
2. process pending exits or direction changes;
3. recompute live capacity;
4. execute a new entry at the current open, clipped to capacity;
5. process the current bar's frozen protective stop;
6. mark equity and verify exposure invariants;
7. update ATR and trailing stop for the next bar;
8. create the next rebalance's pending intentions after the close.

## Tests

Add one exact regression fixture with an old short whose symbol has no bar at
the new targets' entry timestamp. Assert:

- the old short remains live;
- new shorts are clipped or skipped;
- short exposure never exceeds `0.4`;
- gross exposure never exceeds `0.8`;
- net exposure remains within `[-0.4, 0.4]`;
- input row shuffling produces identical trades and bar equity;
- a later old-position exit does not trigger delayed entry of skipped weight.

Keep all existing TianJi, predictive, report, and Qlib tests green.

## Evidence Policy

The prior reports remain immutable:

- `data/reports/tianji_15m_non_predictive_20260820/`;
- `data/reports/tianji_15m_non_predictive_atr_v2_20260820/`.

After tests pass on a new commit, run one new locked holdout in
`data/reports/tianji_15m_non_predictive_exposure_v3_20260820/`. Factors,
ranking, weights, stops, costs, holdout fraction, and performance gates remain
unchanged. Report the result without post-run tuning.

## Scope

Modify only:

- `code/futures_research_backtest.py`;
- `tests/test_futures_research_backtest.py`.

No new class, dependency, model, database mutation, or live-trading path is
added.
