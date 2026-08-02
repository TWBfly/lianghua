# Truth-First Backtest Repair Design

Date: 2026-08-01
Status: Approved

## Objective

Repair the audited correctness failures without claiming capabilities that the
available data and code cannot support. Accuracy and reproducibility take
priority over returning a result.

This design supplements the existing reliability and vn.py-inspired designs.
Their validated market-data contract, causal indicators, shared-account
simulator, daily ledger, and API compatibility rules remain authoritative.

## Truth Policy

The default behavior is fail-closed:

- unknown data lineage rejects a strict backtest;
- missing point-in-time fields produce `UNKNOWN`, never an optimistic default;
- empty or failed synchronization is not reported as success;
- unavailable AI, deep-learning, or reinforcement-learning execution is
  reported as unavailable, never simulated by a simpler model;
- an approximate research result is allowed only when the caller explicitly
  selects that mode and the result identifies every approximation.

No response may describe a component as updated, executed, or validated unless
that component actually completed.

## Phase 1 Scope

### 1. Data Synchronization And Provenance

`AShareDataEngine.sync_stock_daily` keeps its current storage path but returns a
structured summary with successful, empty, and failed symbols. A symbol counts
as successful only after validated rows and provenance commit atomically.

The Web synchronization endpoint derives its message and status from that
summary. Daily-bar synchronization must not claim that fundamentals were also
updated.

Existing `stock_daily` rows without a matching catalog record remain
`LEGACY_UNVERIFIED`; code must not infer `QFQ` provenance from the table name or
current fetch settings. Strict backtests reject such rows. Research-proxy mode
may use them only after explicit caller opt-in and must expose the warning in
`backtest_metadata`.

### 2. Price Semantics

The result metadata distinguishes:

- `RAW_EXECUTION`: raw market prices plus complete corporate-action inputs;
- `ADJUSTED_PROXY`: adjusted prices used as an explicitly approximate research
  proxy;
- `LEGACY_UNVERIFIED`: unknown lineage, rejected by default.

The current database does not contain a complete raw-price and corporate-action
history. Phase 1 therefore does not claim broker-statement-exact execution.
Strict raw execution remains unavailable until an authorized source supplies
raw bars, adjustment factors, cash dividends, rights issues, and split events.

QFQ data may continue to build causal features. It must not be relabeled as raw
execution data.

### 3. Fundamental Audit

The audit consumes only stored source fields. It removes derived placeholders
such as `pb / pe` labelled as ROE and cash-flow values derived from unrelated
ratios.

Each check returns `PASS`, `FAIL`, or `UNKNOWN`. Missing company basics,
financial statements, announcement time, or required fields yield `UNKNOWN`.
The aggregate audit cannot pass when a required check is unknown.

Because the current statements lack announcement timestamps and revision
history, historical fundamental screening is identified as non-point-in-time
and is disabled in strict mode.

### 4. A-Share Execution Rules

Trading-rule fixes stay in the existing simulator helpers so every caller gets
the same behavior. Phase 1 covers the dates represented by the current daily
database:

- Beijing Stock Exchange codes, including `920`, use the correct 30% limit;
- STAR codes, including `689`, use the correct 20% limit and minimum buy size;
- ChiNext risk-warning securities retain the applicable 20% limit after the
  registration reform rather than falling through to a generic 5% ST rule;
- transfer fees use the historical 2022-04-29 cutover;
- the existing 2023-08-28 stamp-duty cutover remains unchanged;
- missing historical listing, ST interval, or IPO no-limit state is disclosed
  and strict simulation rejects an order when that state is required but
  unknowable.

No generic exchange-rule framework is added. Pure simulator helpers and
date-boundary tests are sufficient for the rules currently used.

### 5. Mechanical And ML Strategy Execution

`simulate_portfolio` remains the only production execution ledger. Existing
mechanical signals and ML predictions are converted to the same dated decision
shape before entering it.

A small explicit strategy-name map is sufficient; no plugin framework, event
bus, or abstract base class is introduced. Only strategies that pass causal
prefix-invariance tests are exposed.

The known mechanical defects are repaired at their source:

- Supertrend crossover must use element-wise boolean operations;
- pivot breakout must not use centered rolling windows;
- market structure must not use future rows.

The UI and API report the exact number and names of executable strategies.
TradingView files that are merely discoverable on disk are not counted as
translated or runnable strategies.

ML walk-forward prediction keeps its mature-label and temporal split rules.
Model evaluation and evolution must use decisions passed through
`simulate_portfolio`; simplified future-return arithmetic is not a backtest and
must not determine production promotion.

### 6. AI, DL, And DRL Claims

AI is not part of historical backtest execution in Phase 1. The API and UI must
state that clearly. AI failures do not fall back to an ML result labelled as an
AI result.

The existing matrix-window helper is supervised sequence-data preparation, not
a reinforcement-learning environment. Its public compatibility name may remain
temporarily, but metadata and UI must not claim an RL agent, actions, rewards,
episodes, or training.

No placeholder LSTM, Transformer, PPO, or SAC implementation is added. These
become supported only after they have a real training path, walk-forward
evaluation, reproducible model artifact, and the same execution-ledger test as
other strategies.

### 7. Benchmark And Reporting

When matching `index_daily` data is available, the report adds benchmark return
and excess-return metrics using the same actual reporting dates. Missing
benchmark data yields `UNKNOWN`; it does not silently become zero alpha.

All result modes expose:

- data lineage and price semantics;
- strict or research-proxy mode;
- point-in-time limitations;
- strategy implementation actually executed;
- model/data version where applicable;
- rejected and expired order reasons.

## API Behavior

Existing successful response fields remain additive and compatible. Correctness
errors use the existing error response shape plus a stable machine-readable
code where practical.

The following conditions are errors in strict mode:

- missing or unverified daily-bar provenance;
- invalid daily bars;
- unavailable point-in-time data required by the selected strategy;
- requested strategy not present in the executable strategy map;
- a synchronization request where no symbol commits successfully.

Partial synchronization returns the actual counts and symbol-level failures.

## Commercial Distribution Boundary

The application remains independently implemented and must not ship Backtrader,
vn.py, or copied source from either project. Existing internal differential
checks may continue as non-shipping validation.

AKShare-backed acquisition is not treated as a licensed commercial data source.
Commercial release remains blocked until the distributor supplies and contracts
for a provider whose license covers redistribution or the intended deployed
usage. Phase 1 makes this limitation enforceable and visible; it does not hide
it behind a generic adapter.

API credentials must remain outside source control, and production endpoints
must not expose synchronization or backtest mutation routes without
authentication. Credential rotation and deployment authentication are release
requirements, not optional research warnings.

## Verification And Acceptance

Implementation follows test-first changes. Acceptance requires:

1. Empty and failed synchronization cannot produce a success-only response.
2. Uncataloged legacy bars are rejected in strict mode and labelled in explicit
   research-proxy mode.
3. Fundamental missing data and fabricated ratios can never yield `PASS`.
4. Rule tests cover `920`, `689`, ChiNext ST behavior, transfer-fee cutover,
   stamp-duty cutover, and unknown IPO state.
5. Every exposed mechanical strategy passes prefix-invariance and runtime tests.
6. Mechanical and ML decisions both reconcile through the shared simulator and
   daily ledger.
7. ML promotion evaluation includes simulated costs, T+1, limits, and cash.
8. UI and API contain no false AI, DL, DRL, model-count, or strategy-count claim.
9. Existing tests remain green, plus compile and JavaScript syntax checks.
10. A real database smoke test either returns a truthful result or the expected
    fail-closed error; silent fallback is a failure.

## Deferred Work And Entry Gates

### Licensed Point-In-Time Data

Add raw execution, corporate actions, historical universe, delisting, ST, IPO,
financial announcement, and revision history only after a licensed provider,
schema samples, timestamp semantics, and usage rights are available.

### Deep Learning

Add a sequence model only when it improves a declared baseline in nested
walk-forward evaluation after transaction costs and produces reproducible
artifacts. One working model is sufficient before adding a model family.

### Reinforcement Learning

Add DRL only after the execution environment defines observations, legal
actions, fills, costs, rewards, terminal states, and leakage tests. A NumPy
window builder alone does not satisfy this gate.

### Document-Grounded AI

Add AI-assisted decisions only when inputs are point-in-time documents with
source IDs and timestamps, outputs use a validated schema, cache keys include
model/prompt/data versions, and every decision retains citations. Until then AI
may analyze current information outside historical backtests but cannot be
reported as a causal backtest strategy.

## Non-Goals

- Translating hundreds of TradingView files before one is requested and tested.
- Building a generic strategy framework for hypothetical future engines.
- Inventing unavailable corporate actions, fundamentals, order books, or AI
  evidence.
- Claiming commercial-data readiness without an executed data contract.
