# Futures 15m First-Principles Hardening Design

Date: 2026-08-17
Status: Approved for implementation planning

## Objective

Replace the repository's competing 15-minute futures claims with one
falsifiable offline research path. The path must determine whether information
available at a completed 15-minute bar has stable value on later unseen data
after explicit costs. It must reject weak evidence instead of optimizing until
historical results look profitable.

The existing TqSim and live entry points are disabled during this phase. Live
execution cannot return until a separate design establishes broker-confirmed
orders, positions, fills, account risk, and restart reconciliation.

## First-Principles Invariants

1. A decision uses only information observable when its bar closes.
2. Unsupported or discontinuous observations are removed, never imputed or
   silently crossed.
3. Training, candidate selection, and final evaluation use disjoint future
   outcomes with purge and embargo protection.
4. Every reported return is reconstructible from source prices, position
   state, and explicit two-sided costs.
5. Model complexity is justified only by later unseen evidence against a
   simpler model and non-predictive baselines.
6. A weighted index is a research series, not a tradable contract.
7. A failed gate produces `RESEARCH_REJECTED`; no automatic tuning follows.
8. No code path may submit an order while the research path is isolated.

## Scope

### In scope

- Disable the shell, Python, and dashboard paths that start futures trading.
- Remove hard-coded trading credential defaults.
- Make `futures_research_backtest.py` the sole active 15-minute futures
  research authority.
- Correct causal 5m-to-15m segmentation and aggregation.
- Remove Qlib's duplicate train-as-validation data.
- Compare a regularized logistic model and constrained Qlib LightGBM against
  Dummy and equal-weight benchmarks.
- Strengthen fixed, nested temporal selection and adversarial gates.
- Extend atomic reports with data-loss, trial-count, baseline, bootstrap, and
  locked-holdout identity evidence.
- Add regression tests before each behavior change.

### Out of scope

- Re-enabling TqSim, CTP, or any real order path.
- Implementing an order/fill state machine.
- Claiming lots, margin, liquidation, exchange limits, RMB PnL, or live
  readiness from weighted-index data.
- Repairing V16, decoupled symbol engines, or the so-called PPO agent.
- New features, model families, hyperparameter frameworks, experiment
  trackers, or dependencies.
- Deleting historical reports or forensic source files.

## Architecture

The repository has one active research flow:

```text
provenance-approved 5m weighted-index bars
        |
        v
5m validation and causal segmentation
        |
        v
complete natural-boundary 15m windows
        |
        v
causal features and matured labels
        |
        v
nested purged walk-forward candidate selection
        |
        v
next-open fixed-horizon standardized ledger
        |
        v
baseline, cost, perturbation, shuffle, and stability gates
        |
        v
atomic RESEARCH_ACCEPTED or RESEARCH_REJECTED evidence
```

`futures_research_backtest.py` remains the single orchestrator because it has
one caller and its integrity checks share state. `qlib_model_adapter.py`
remains a narrow in-memory model bridge. No interface hierarchy or strategy
framework is introduced.

The V16, decoupled, live, and report-generator modules remain available for
forensic reading but are not active strategy sources.

## Data Contract

### Source

Only provenance-approved `5m` rows and their metadata are loaded from
`futures_min_bars` and `futures_series_metadata`. The existing database `15m`
table is not an input to the audited run.

Timestamps represent exchange-local wall-clock time. Aware, mixed, unparseable,
or non-five-minute timestamps are rejected. Source attributes and SHA256
manifests survive aggregation and enter the report.

### Segmentation before aggregation

Each symbol is sorted independently. A new 5-minute segment begins when:

- the timestamp difference is not exactly five minutes;
- either adjacent bar has zero volume;
- the previous-close-to-current-open absolute gap exceeds 3%; or
- the adjacent close-to-close absolute return exceeds 3%.

The raw 5-minute validation must run before aggregation. This prevents a
positive three-bar volume sum from hiding an internal zero-volume row and
prevents an internal jump from being averaged away.

### Natural 15-minute windows

Within each valid 5-minute segment, bars are assigned to the natural
15-minute window ending at `trade_time.ceil("15min")`. A window is emitted only
when it contains exactly three rows, each adjacent difference is five minutes,
and the first-to-last span is ten minutes. Partial windows are excluded.

OHLCV aggregation is fixed:

- timestamp: natural window end;
- open: first;
- high: maximum;
- low: minimum;
- close: last;
- volume and amount: sum;
- open interest and settlement: last;
- series type: first, after verifying it is constant.

The report records counts for raw rows, emitted windows, partial windows,
zero-volume boundaries, time gaps, and price-jump boundaries.

### Features and labels

The existing small dimensionless whitelist remains unchanged. Features may
use completed observations from the causal feature segment. Labels and trade
paths remain inside the stricter execution segment.

A decision is made at the completed 15-minute bar, enters at the next bar open,
and exits six bars later at the open. The binary target is the sign of that
future open-to-open return. The label is prediction by definition; reports
must not call the complete strategy non-predictive.

## Research Ledger

The audited ledger remains a fixed-sleeve weighted-index return ledger. It does
not simulate stops or use intrabar high/low, eliminating unknown OHLC path
ordering. Long, short, no-position, two-sided cost, turnover, exposure, equity,
and daily PnL identities must reconcile exactly.

Entries use the next available open in the same segment. Exits use the fixed
horizon open in the same segment. Missing paths reject the observation; they
do not fall back to another price.

## Model Domain

The selectable models are deliberately small:

- L2 logistic regression with fixed `C=0.1`;
- constrained Qlib LightGBM with fixed depth, leaves, learning rate, seed,
  thread count, regularization, and boost rounds.

Dummy prior and equal-weight long-only remain non-selectable benchmarks.
Thresholds are the fixed set `(0.52, 0.55, 0.58)`. No automatic search or
feature expansion is permitted.

Qlib receives a training segment and a prediction segment. It must not expose
the training frame again as `valid`. Boost rounds are fixed so training data
cannot act as its own early-stopping evidence. Model and threshold selection
remain outside Qlib in the nested temporal pipeline.

Each parent fold contains two inner purged walk-forward folds. Labels must end
strictly before evaluation begins, and `embargo_bars >= horizon` is mandatory.
If candidate returns are within the predeclared near-best tolerance, selection
prefers lower turnover and then logistic regression.

The final holdout identity includes data rows, market marks, candidate domain,
threshold domain, cost domain, seed, database hash, and code hash. Reusing the
holdout after a code, data, feature, candidate, or threshold change creates a
new research identity and cannot be represented as the original locked test.

## Acceptance Gates

An accepted run must supply complete, finite evidence and pass every gate:

1. Structural, causal, ledger, prefix, purge, embargo, and identity checks.
2. AUC greater than 0.50 in every outer fold and holdout.
3. Brier score strictly better than Dummy prior in every outer fold and
   holdout.
4. Positive 5bp return in every outer fold and holdout.
5. 5bp return greater than both Dummy prior and equal-weight long-only in every
   outer fold and holdout.
6. Twenty deterministic within-symbol label permutations; baseline holdout AUC
   must exceed the maximum shuffled AUC and shuffled median return must be
   non-positive. This bounds the empirical permutation probability at `1/21`.
7. Moving-block bootstrap at block lengths 5, 10, and 20 trading days; the
   worst 5th-percentile compounded return must be positive.
8. Noise and calendar features may not improve AUC by more than 0.01 or 5bp
   return by more than 0.05.
9. At least half of eligible symbols have positive 5bp return, with the top
   five contributing no more than half of total positive contribution.
10. Every fold remains above -10% return and below 20% drawdown at 10bp.
11. Returns are monotonically non-increasing across the fixed cost grid on an
    identical frozen trade set.

Missing, contradictory, duplicate, non-finite, or foreign evidence fails
closed. A rejected run still writes the complete atomic evidence bundle.

## Trading Isolation

`run_tqsim_trader.sh` exits non-zero before launching Python.
`futures_live_trader.main()` exits non-zero before loading credentials or
opening TqSdk. Credential environment variables have no non-empty defaults.

Dashboard endpoints that can start the trader return an explicit disabled
response and do not spawn a process. Dashboard status must not add historical
backtest profit to current account equity or describe it as live PnL.

Tests and documentation enforce that V16, decoupled engines, report generators,
and the audited research proxy are absent from executable strategy registries.

## Error Handling and Reporting

All trust-boundary violations raise `ResearchRejected` with a specific reason.
Dependency failures, insufficient data, invalid configuration, baseline
failure, and failed attacks produce `RESEARCH_REJECTED`, not fallback behavior.

Atomic report output adds:

- raw and aggregated exclusion counts;
- fixed candidate and threshold trial counts;
- Dummy and equal-weight comparisons by fold;
- all three block-bootstrap intervals and the worst lower bound;
- locked-holdout identity and provenance;
- every failed gate and affected fold.

Existing report directories are never overwritten.

## Test Strategy

Every behavior change follows red-green TDD. Regression tests cover:

- zero-volume rows hidden by a non-zero aggregate;
- internal price jumps hidden by aggregation;
- gaps, partial natural windows, and misaligned source starts;
- source attribute and aggregation preservation;
- Qlib training without a duplicate validation frame;
- fixed candidate and threshold domains;
- simple-model preference within the near-best tolerance;
- invalid embargo/horizon relationships;
- Brier, benchmark-superiority, and multi-block bootstrap gates;
- foreign, incomplete, contradictory, and non-finite evidence;
- shell, Python, dashboard, and registry trading isolation;
- report reconciliation for accepted and rejected results.

Verification runs focused tests after each task, the complete futures research
and boundary suites at the end, and one new real-data 15-minute Qlib run into a
new evidence directory. Exit code 0 is valid only for `RESEARCH_ACCEPTED`; exit
code 2 is valid for an evidence-complete `RESEARCH_REJECTED`.

## Success Criteria

- No repository entry point can start futures trading.
- No hard-coded trading credentials remain.
- Invalid 5-minute observations cannot be hidden inside a 15-minute aggregate.
- Qlib does not reuse its training frame as validation evidence.
- Complex models must beat simpler and non-predictive baselines on every
  required later fold.
- All acceptance evidence is atomic, reproducible, and fail-closed.
- The relevant automated suites pass.
- The real-data run reports its actual accepted or rejected state without
  manual parameter adjustment.
