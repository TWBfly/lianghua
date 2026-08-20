# TianJi ATR Data-Contract Repair Design

## Problem

The first locked TianJi holdout ended at `RUN_PRECONDITION` with
`missing causal TianJi ATR in holdout`. This is not a strategy-performance
failure: the trade ledger never ran.

Read-only diagnosis established the exact boundary:

- 1,200,061 canonical 5-minute rows;
- 382,997 audited 15-minute rows;
- 82 eligible symbols;
- 349,563 mature score rows;
- 69,014 holdout market rows;
- 6,324 ATR join misses across 43 symbols.

Of the missing rows, 4,421 had an immature ATR. The remaining rows lost an
otherwise usable ATR because `build_tianji_scores` discarded the entire row
when any directional factor was immature. `build_tianji_evaluation` then joined
ATR from that filtered signal table to every holdout market row and required
complete coverage. One miss rejected the run. `rejected_result` correctly
preserved the rejection but emitted empty metrics and trade tables because the
ledger had not run.

## Goal

Separate causal risk data from signal eligibility so the ledger can mark every
position without inventing factor values. Preserve fail-closed behavior,
next-open execution, the frozen TianJi rule set, and the original rejected
evidence. A new versioned locked holdout may run once only after the repair and
full regression verification.

## Architecture

Keep `code/futures_research_backtest.py` as the only production path. One
feature calculation produces two explicit views:

1. **Risk view:** one row per symbol and completed 15-minute market bar with
   causal ATR when its 20-bar window is mature. This view does not depend on
   Kaufman efficiency, Donchian position, momentum acceleration, intraday
   intensity, liquidity filtering, or cross-sectional ranks.
2. **Signal view:** rows whose complete frozen directional factor set and
   liquidity eligibility permit ranking and new target generation.

`build_tianji_scores` keeps all causal feature rows, records separate
`atr_ready` and `signal_ready` booleans, and calculates `score` only for
`signal_ready` rows. It no longer deletes valid risk rows because an unrelated
directional factor is immature.

## Data Flow

1. Load and validate canonical 5-minute weighted-index data.
2. Aggregate complete natural-boundary 15-minute windows.
3. Calculate per-symbol causal ATR and directional factors independently.
4. Keep every market row; annotate risk and signal readiness.
5. Build cross-sectional targets only from `signal_ready` rows.
6. Merge the independent risk view onto market bars by `(symbol, trade_time)`.
7. Run the ledger with risk validation scoped to new targets and open
   positions, not inactive market observations.
8. Write bar equity, trades, metrics, exact gates, and stage diagnostics through
   the existing atomic report bundle.

## ATR Rules

- A new position requires a finite positive ATR at its decision time.
- A position stores the last finite positive ATR observed for its symbol.
- If a later market bar has no newly mature ATR, the position retains that last
  known value; this is causal forward propagation, not future filling.
- When a new finite ATR arrives, it becomes the value used to calculate the
  next bar's trailing stop.
- A gap-through protective stop is still checked at the current open before a
  pending signal exit.
- A symbol with no mature ATR cannot open a new position.
- Non-held, non-target market rows may have an immature ATR without rejecting
  the run.
- Non-finite OHLC, duplicate timestamps, invalid target ATR, or an open position
  without any prior valid ATR still fail closed.

## Reporting

Every result, including a precondition rejection, records a `pipeline_counts`
object with:

- `market_15m_rows`;
- `risk_ready_rows`;
- `signal_ready_rows`;
- `holdout_market_rows`;
- `holdout_risk_ready_rows`;
- `target_rows`;
- `trade_rows_5bps`;
- `failure_stage`.

Rejected reports keep these counters instead of presenting unexplained empty
tables. Empty metrics and trades remain correct when the ledger was never
reached, but the stage and row counts must make that explicit.

## Tests

Add focused tests proving:

- a finite ATR survives when intraday intensity or another directional factor
  is still immature;
- immature signal rows cannot create targets;
- inactive market rows without ATR do not reject the ledger;
- a new target without ATR is rejected;
- an open position retains only its last causal ATR through a later ATR gap;
- a later valid ATR updates only the next bar's trailing stop;
- pipeline counters identify the failure stage and reconcile with report row
  counts;
- existing predictive and TianJi tests remain green.

## Locked-Run Policy

The prior report at `data/reports/tianji_15m_non_predictive_20260820/` remains
unchanged. The repair changes infrastructure semantics, so any new evidence has
a new code revision, run ID, research identity, and output directory. It is not
parameter tuning: factors, weights, rebalance cadence, stops, costs, holdout
fraction, and gates remain frozen. The repaired locked holdout runs once; an
acceptance or rejection is reported without post-result tuning.

## Scope

Production and test changes are limited to:

- `code/futures_research_backtest.py`;
- `tests/test_futures_research_backtest.py`.

No new dependency, strategy framework, model, Qlib training path, database
mutation, or live-trading capability is added.
