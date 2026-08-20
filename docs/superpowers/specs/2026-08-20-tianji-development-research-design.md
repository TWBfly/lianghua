# TianJi Verified-Index Development Research Design

## Objective

Repair the remaining research-data and backtest evidence gaps, then develop a
new non-predictive TianJi 15-minute strategy using only the pre-holdout
development period.

The development acceptance gates at 5 bps on entry and 5 bps on exit are:

- payoff ratio `>= 3.0`;
- 15-minute mark-to-market maximum drawdown `<= 0.15`;
- total return `> 0`;
- at least `200` closed trades;
- cost returns monotonically non-increasing across `0/2/5/10/15/20` bps.

These are rejection gates, not guaranteed outputs. A candidate that fails any
gate is rejected. Passing development gates does not authorize live trading or
claim out-of-sample success.

## Evidence Boundary

The following locked reports are immutable and excluded from all factor,
direction, threshold, and exit decisions:

- `data/reports/tianji_15m_non_predictive_20260820/`;
- `data/reports/tianji_15m_non_predictive_atr_v2_20260820/`;
- `data/reports/tianji_15m_non_predictive_exposure_v3_20260820/`.

Development data ends at `2026-06-26 10:30:00`. The viewed v3 holdout beginning
at `2026-06-26 10:45:00` cannot be reused as final evidence. A future final
acceptance requires newly imported, provenance-approved data later than the
viewed holdout and a new locked run identity.

## Phase 1: Data Contract

Only `5m` rows with a matching `futures_series_metadata` record, allowed
`series_type`, canonical SHA256, and exact source row contract are eligible.
The current verified universe consists exclusively of `WEIGHTED_INDEX` and
`MONTHLY_AVERAGE_WEIGHTED_INDEX` research proxies.

Direct database `15m` rows are forensic-only because all 25 symbols have zero
metadata records. They must never enter the official strategy path.

The data audit must export:

- the exact included, excluded, mature, and traded symbol lists;
- source filename, title, SHA256, series type, start/end time, and row count;
- raw 5-minute rows and complete reconstructed 15-minute rows;
- duplicate, non-finite OHLC, invalid OHLC geometry, zero-volume, price-jump,
  time-gap, partial-window, and feature-warmup counts;
- risk-ready and signal-ready counts per symbol;
- a complete sector mapping for every eligible symbol.

Unknown sector mappings fail closed. They no longer collapse into one `OTHER`
bucket. This fixes the current condition where 35 of 61 traded symbols share an
uninformative default sector.

The data report must say explicitly that weighted indices are not tradable
contracts and do not include roll yield, contract multipliers, margin, exchange
fees, or basis.

## Phase 2: Backtest Evidence

Keep the audited next-open, causal ATR, asynchronous-capacity, cost, and
15-minute mark-to-market ledger. Add evidence rather than a second simulator.

Every run exports:

- eligible-universe and actual-traded symbol lists;
- per-symbol trades, gross PnL, entry cost, exit cost, net PnL, return,
  win rate, payoff ratio, profit factor, maximum drawdown, exposure, turnover,
  and exit-reason counts;
- portfolio gross return, entry/exit costs, and net return reconciliation;
- bar-level long, short, gross, and net exposure;
- requested, executed, clipped, and skipped entry weights;
- capacity-limited entry counts;
- stop, signal, and terminal exit counts;
- all pipeline-stage counters already present.

The ledger remains a return-space weighted-index simulator. It does not add
contract lots, margin, daily settlement, price limits, order-book liquidity, or
market impact because the verified database cannot support them. Reports must
show these as hard limitations.

## Phase 3: Development-Only Strategy Research

The current always-invested cross-sectional composite is retired as a rejected
baseline. It lost `7.63%` before costs and `14.07%` at 5 bps, so changing only
fees cannot repair it.

Research is limited to three predeclared, non-predictive OHLCV candidates:

1. **Sparse cross-sectional continuation:** signed Kaufman efficiency,
   Donchian breakout, momentum acceleration, and same-direction intraday volume
   intensity must agree. Only extreme cross-sectional ranks may enter.
2. **Sparse cross-sectional reversal:** the same frozen inputs with reversed
   direction, included because the rejected baseline's orientation may be
   wrong. Entry and exit rules remain symmetric.
3. **Time-series Donchian trend:** each symbol trades its own confirmed breakout
   and volume regime; portfolio construction provides market-neutral and sector
   caps without cross-sectional direction prediction.

No ML model, probability, future-return label, adaptive parameter search, or
open-ended factor mining is allowed. Forward returns may be used only inside the
development evaluator to measure candidate outcomes, never as runtime inputs.

All candidates share:

- 15-minute completed-bar signals and next-observed-open execution;
- full sector map with maximum two positions per sector per side;
- inverse causal ATR sizing;
- live side-cap and gross-cap enforcement;
- one-ATR initial stop;
- no fixed profit target;
- trailing activation only after the position has achieved at least `3R`, so a
  development candidate cannot obtain payoff `>=3` by truncating winners;
- no forced four-hour exit; structural signal invalidation and protective stops
  own exits;
- unused capacity remains cash.

The development period is divided chronologically into four blocks. Block 1 is
warm-up and calibration-free history. Blocks 2-4 are three forward evaluation
folds. A candidate is development-eligible only when:

- combined folds pass every objective gate;
- no evaluation fold has non-positive return;
- every fold has finite payoff, drawdown, and reconciled costs;
- the same frozen trade identity is used across costs.

Selection is deterministic: highest worst-fold payoff ratio, then lowest
worst-fold drawdown, then lowest turnover. Ties use the candidate name. No
parameter is changed after fold results are visible.

## Reporting Status

The best possible current status is `DEVELOPMENT_CANDIDATE`. It is never
`RESEARCH_ACCEPTED`, because no untouched post-v3 data exists in the verified
database. If all candidates fail, status is `DEVELOPMENT_REJECTED`.

The report must include the rejected v3 baseline beside all three development
candidates and explain why the selected result is not an out-of-sample claim.

## Tests

Tests must prove:

- unprovenanced direct 15-minute rows cannot enter official research;
- every included symbol has a sector mapping;
- universe and per-symbol report tables reconcile with trades;
- requested/executed/clipped/skipped weights reconcile at each bar;
- gross return minus entry and exit costs equals net return;
- development folds are chronological and disjoint from the viewed holdout;
- runtime candidate functions contain no labels or predictive inputs;
- candidate and tie-break selection is deterministic;
- development gates cannot emit `RESEARCH_ACCEPTED`;
- all existing predictive, TianJi, Qlib, ledger, and report tests remain green.

## Scope

Prefer the existing `code/futures_research_backtest.py` and
`tests/test_futures_research_backtest.py`. A small focused development runner
may be added only if keeping candidate evaluation in the existing large module
would obscure the audited production path. No dependency or database mutation
is required.
