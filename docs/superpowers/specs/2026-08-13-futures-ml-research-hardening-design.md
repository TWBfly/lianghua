# Futures ML Research Hardening Design

Date: 2026-08-13
Status: Approved for specification

## Objective

Build one auditable machine-learning research backtest for the imported
five-minute futures weighted-index data. The path must detect data defects,
preserve causal time ordering, resist overfitting, reconcile every reported
return to a position ledger, and fail closed when adversarial checks expose an
untrustworthy result.

The output is research evidence only. It must never describe a weighted index
as a tradable futures contract or report lots, contract PnL, margin, liquidation,
or live-trading readiness.

## First-Principles Derivation

The real objective is not to maximize an historical return. It is to answer a
narrower falsifiable question:

> Given only information observable by the close of a five-minute weighted-
> index bar, is there a direction signal that remains useful on later unseen
> data after explicit costs and hostile validation?

That objective creates five non-negotiable invariants:

1. A decision may depend only on information available at its timestamp.
2. A reported return must be reconstructible from source prices, position
   state, and explicit entry and exit costs.
3. Training, model selection, and final evaluation must use disjoint future
   outcomes.
4. Data that cannot support an observation must remove that observation rather
   than be filled, inferred, or silently crossed.
5. A weighted index is a research series, not an executable contract.

Any component that violates one of these invariants is rejected regardless of
its Sharpe ratio.

## Scope

### In scope

- Preserve all useful fields available in the source export.
- Add provenance for each imported futures series.
- Validate and segment five-minute weighted-index data.
- Build a small causal feature set and six-bar direction label.
- Compare a dummy baseline, regularized logistic regression, and a constrained
  LightGBM classifier.
- Select a model and threshold only inside nested walk-forward validation.
- Evaluate one untouched final holdout.
- Simulate standardized, fixed-sleeve index returns with next-open execution.
- Run adversarial leakage, noise, time-feature, label-shuffle, concentration,
  discontinuity, and cost tests.
- Produce Markdown, JSON, and CSV evidence.

### Out of scope

- Tradable contract mapping, rolling orders, lots, multipliers, tick sizes,
  margin, daily settlement, liquidation, price-limit execution, or RMB PnL.
- Live trading, paper trading, Web/API registration, model persistence, or
  automatic model promotion.
- Repairing the existing V13/V14/V15, benchmark, self-evolving, or XAUUSD
  research engines.
- Adding model families, hyperparameter optimization frameworks, feature
  stores, experiment trackers, or dependencies.

## Production and Research Boundaries

The existing A-share `KLineBacktestEngine` and `simulate_portfolio` remain the
only production-trusted historical ML path. The new futures module is a
separate, offline research path with only two terminal states:

- `RESEARCH_ACCEPTED`: every predeclared gate passed;
- `RESEARCH_REJECTED`: one or more gates failed, with explicit reasons.

Neither state means live-trading ready. The new module must remain absent from
`hot_plugger.get_executable_strategies()` and `/api/strategies`.

The modules listed in `docs/research-only-ml-engines.md` remain
`RESEARCH_ONLY_INVALIDATED`. Their old JSON files are not inputs, benchmarks,
or evidence for the new path.

## Architecture

The implementation has one linear path:

```text
CSV / futures_min_bars
        |
        v
schema + provenance + quality validation
        |
        v
causal five-minute segments
        |
        v
features + matured six-bar labels
        |
        v
nested purged walk-forward selection
        |
        v
next-open fixed-sleeve return ledger
        |
        v
adversarial gates
        |
        v
Markdown + JSON + CSV research report
```

The implementation uses the existing Python, pandas, scikit-learn, LightGBM,
SQLite, and pytest stack. No new dependency is permitted.

## File Boundaries

The smallest useful change is four touched files plus documentation:

- Modify `code/import_futures_5m.py` for the extended source schema and series
  provenance.
- Create `code/futures_research_backtest.py` for data gates, causal datasets,
  nested validation, the standardized ledger, adversarial checks, and report
  writing. These steps deliberately share one module because no second caller
  exists yet.
- Extend `tests/test_import_futures_5m.py` for schema, provenance, and null
  amount behavior.
- Create `tests/test_futures_research_backtest.py` for causal, accounting,
  adversarial, and fail-closed behavior.
- Update `docs/research-only-ml-engines.md` to distinguish the new audited
  research proxy from the invalidated legacy engines without making it an
  executable strategy.

The module may be split only if its final implementation becomes difficult to
understand or test as one file. No interface hierarchy or framework is added.

## Import and Data Contract

### Bar schema

`futures_min_bars` keeps its existing primary key
`(symbol, timeframe, trade_time)` and columns. Two nullable numeric columns are
added idempotently:

- `open_interest REAL`
- `settlement REAL`

The source export does not contain a trustworthy turnover/amount field.
Consequently, imported rows set the existing `amount` column to `NULL`; they
must not synthesize `close * volume`.

### Series provenance

A normalized `futures_series_metadata` table avoids repeating source strings
on every bar. Its primary key is `(symbol, timeframe)` and it records:

- `source_file`
- `source_title`
- `series_type`, restricted to `WEIGHTED_INDEX` or
  `MONTHLY_AVERAGE_WEIGHTED_INDEX`
- `source_encoding`
- `source_sha256`
- `row_count`
- `start_time`
- `end_time`
- `imported_at`

The importer derives `series_type` from the decoded first source line and
rejects an unknown title instead of guessing.

### Migration and replacement

Schema creation and `ALTER TABLE` operations are idempotent. Replacement of
existing five-minute rows occurs only through the import command's explicit
replace mode and inside one SQLite transaction per file. Metadata and bars
commit together. A parse, validation, or write error rolls back that file.

Before replacing the project database, the full import is exercised against a
temporary SQLite database and compared with the source files. The real database
is changed only after the temporary import passes.

### Row validation

Every row must satisfy:

- a parseable timestamp aligned to five minutes;
- finite open, high, low, close, volume, and any present optional number;
- `high >= max(open, close, low)`;
- `low <= min(open, close, high)`;
- non-negative volume and open interest;
- uniqueness of `(symbol, timeframe, trade_time)` within the source file.

Malformed rows reject the complete file. Silent dropping is prohibited.

## Research Dataset

### Eligibility and segmentation

Bars are sorted independently by symbol. A new causal segment starts when any
of the following is true:

- the timestamp difference is not exactly five minutes;
- either adjacent bar has zero volume;
- the absolute previous-close-to-current-open gap exceeds 3%;
- the absolute adjacent close-to-close return exceeds 3%.

Features may use only earlier bars in the same segment. A label or trade may
not cross a segment boundary. No missing bar is imputed.

A symbol is excluded with a recorded reason when any of these applies:

- more than 50% of its raw bars have zero volume;
- fewer than 1,000 usable labeled observations remain;
- it has fewer than 200 usable observations in any required outer evaluation
  window.

The complete run is rejected when fewer than 20 symbols, three development
outer folds, or one final holdout remain eligible.

### Causal features

The fixed first-version feature list is:

- close returns over 1, 3, 6, and 12 bars;
- rolling return standard deviation over 12 and 48 bars;
- `(high - low) / close`;
- `(close - open) / close`;
- close location within the high-low range;
- EMA-12 minus EMA-48, divided by EMA-48;
- current volume relative to the prior 48-bar mean and standard deviation.

Rolling statistics use only the current and earlier completed bars in the same
segment. Volume normalization uses a one-bar shift so the current completed
bar cannot alter its own baseline. No global scaler is fit before a training
split.

The production feature whitelist rejects symbol identifiers, filenames,
series titles, absolute timestamps, time-of-day, day-of-week, raw future
columns, labels, and columns not named above.

### Label

For a decision bar at position `t`:

- entry price is the open at `t + 1`;
- exit price is the open at `t + 7`;
- holding length is six five-minute intervals;
- label is `1` when `open[t+7] / open[t+1] - 1 > 0`, otherwise `0`;
- `label_end_time` is the timestamp at `t + 7`.

All eight bars from `t` through `t + 7` must be in the same segment. Rows
without a complete future path have no label and cannot train or evaluate a
model.

## Temporal Validation

### Locked final holdout

The last 20% of unique eligible timestamps is reserved before model selection.
It must contain at least 30 distinct trading dates. If it does not, the run is
rejected. Its labels, metrics, and returns cannot influence features, models,
thresholds, or gates chosen from development data.

After the holdout has been evaluated, the run configuration is immutable.
Failure on the holdout ends the run as `RESEARCH_REJECTED`; the implementation
must not tune again and re-evaluate the same holdout.

### Development outer folds

The first 80% of timestamps forms development data. Let its ordered unique
timestamp count be `D`. The first `floor(0.40 * D)` timestamps form the initial
outer training window. The remaining timestamps are divided, in order, into
three contiguous evaluation windows whose sizes differ by at most one. Outer
fold `k` trains on every development timestamp before evaluation window `k`
and evaluates only that window. The exact cut points are written to the report.

For every training/evaluation boundary:

- a training label is usable only when `label_end_time < evaluation_start`;
- the final six valid bars per symbol before the evaluation start are removed
  as an additional embargo;
- scalers and models fit only the surviving training rows;
- evaluation rows remain chronological and untouched.

### Inner selection

Each outer training window is divided into two expanding inner folds using the
same purge and embargo rules. Its first 50% of unique timestamps is the initial
inner training window; its remaining timestamps are divided into two contiguous
evaluation windows whose sizes differ by at most one. The only selectable
candidates are:

1. regularized logistic regression with `C=0.1`;
2. regularized logistic regression with `C=1.0`;
3. one constrained LightGBM configuration:
   `n_estimators=100`, `learning_rate=0.03`, `max_depth=3`,
   `num_leaves=7`, `min_child_samples=200`, `subsample=0.8`,
   `colsample_bytree=0.8`, `subsample_freq=1`, `reg_alpha=1.0`,
   `reg_lambda=5.0`, `objective="binary"`, `verbosity=-1`, `n_jobs=1`, and
   `random_state=42`.

Logistic regression uses L2 penalty, `solver="liblinear"`, `max_iter=1000`,
and `random_state=42`, and receives a scaler fitted on its own training fold.
LightGBM receives the finite causal values directly. Rows with incomplete
warm-up features are dropped, never filled. Training sample weights are the
product of inverse per-symbol row count and inverse class frequency, normalized
to mean one. Thus each symbol and class contributes equal total weight within a
fold, preventing longer night sessions or class imbalance from dominating the
pooled model.

The only selectable symmetric probability thresholds are 0.52, 0.55, and
0.58. For threshold `p`, probability at least `p` is long, probability at most
`1-p` is short, and the rest is flat.

A candidate is eligible only when both inner folds have positive standardized
portfolio return after 5 bp one-way costs. Among eligible candidates, selection
maximizes median inner-fold 5 bp return; ties within 0.10 percentage point use
lower turnover, then logistic regression, then the higher threshold. When no
candidate is eligible, that outer fold and the complete run are rejected.

The dummy prior classifier is always reported but cannot be selected.

After all development outer folds have been reported, the final configuration
is selected once by applying the same two-inner-fold procedure to the complete
development interval. It is then fit on all development samples whose labels
mature before the locked holdout and that survive its six-bar embargo. This one
fit produces the locked-holdout predictions. Outer-fold results and locked-
holdout data are never pooled to choose the final configuration.

## Standardized Return Ledger

### Portfolio meaning

Every eligible symbol owns a fixed `1 / N` sleeve, where `N` is the eligible
symbol count fixed at the start of the evaluated window. Inactive sleeves stay
in cash with zero return. Active sleeves take direction `+1` or `-1`; weights
are never redistributed to active symbols, so gross exposure cannot exceed
100%.

This is a standardized index-return portfolio. It is not a futures account.

### Position lifecycle

- A signal observed at close `t` queues entry at open `t+1`.
- A position exits at open `t+7`, six intervals after entry.
- A symbol cannot open another position while its sleeve is active.
- A queued entry is cancelled if its entry/exit path crosses a segment boundary.
- Both entry and exit pay the configured one-way cost.
- Let `price_ratio = exit_open / entry_open` and direction be `+1` for long or
  `-1` for short. Gross sleeve return is
  `direction * (price_ratio - 1)` on entry notional.
- With one-way cost rate `c`, entry cost is `c` and exit cost is
  `c * price_ratio`, both measured against entry notional. Net sleeve return is
  `gross_return - c * (1 + price_ratio)`.
- A final incomplete path cannot be opened. Any defensive residual position is
  closed at the last available open in its segment, pays exit cost, and is
  marked `TERMINAL_CLOSE`.

Every trade record contains symbol, signal time, entry time, exit time,
direction, raw prices, gross return, each cost, net return, fold, model identity,
threshold, and exit reason.

### Mark-to-market equity

Each symbol sleeve keeps its own equity and compounds only its own sequential
trades. While a position is active, the sleeve is marked on every available bar
close from its entry price, including the entry cost already paid. The exit
mark applies the exit cost and becomes that sleeve's new cash balance. Inactive
sleeves remain unchanged and are never redistributed to active symbols.

Portfolio equity at each timestamp is the sum of every sleeve's marked equity.
Daily equity is the final timestamp mark for that date. Drawdown, volatility,
and Sharpe are calculated from this marked daily path, not from returns booked
only when trades close. Thus an interim loss remains visible even if the trade
later exits profitably.

### Reconciliation

Daily and total returns are calculated only from the trade/position ledger and
its bar-by-bar marks. The report writer independently recomputes every trade,
sleeve transition, timestamp equity, and daily portfolio return. A discrepancy
greater than `1e-12` rejects the run.

## Model and Strategy Metrics

Each inner fold, outer fold, final holdout, symbol, and aggregate report
includes:

- row and date coverage;
- class balance;
- ROC AUC, balanced accuracy, Brier score, and rank correlation;
- trade count, exposure, turnover, win rate, and profit factor;
- total and annualized return, annualized volatility, Sharpe, and maximum
  drawdown;
- positive-symbol fraction and positive-PnL concentration;
- model parameters, selected threshold, training cutoff, label cutoff, and
  evaluation interval.

Annualization uses daily aggregated portfolio returns and 252 days. No
five-minute bar count is hard-coded as a trading year.

## Adversarial Review

All adversarial checks use deterministic seed 42 and write their evidence to
the report.

### Causality attacks

1. Append future bars and rerun dataset and prediction construction. Features,
   labels already matured before the append cutoff, chosen split membership,
   and emitted predictions before the cutoff must match exactly within `1e-12`.
2. Attempt to insert a future-return column and an unapproved column into the
   model matrix. The feature whitelist must reject both.
3. Assert for every split that the maximum training `label_end_time` is earlier
   than evaluation start and the six-bar embargo is present for every symbol.

### Data attacks

Synthetic duplicate timestamps, out-of-order bars, non-finite values, invalid
OHLC relations, zero-volume spans, missing five-minute bars, and greater-than-
3% discontinuities must either reject the symbol or create a segment boundary.
No label or trade may cross the boundary.

### Execution attacks

- Repeated same-direction and alternating signals cannot overlap positions for
  one symbol.
- Costs at 0, 2, 5, 10, and 20 bp must produce monotonically non-increasing net
  return for the identical trades.
- A terminal residual position must close and reconcile.
- Reversing trade iteration order must not change aggregate results.

### Statistical attacks

1. Run 20 deterministic, within-symbol training-label permutations for the
   selected model on the locked holdout. Observed holdout AUC must exceed the
   maximum permuted AUC, and median permuted 5 bp return must be non-positive.
2. Add five deterministic hash-derived noise features, retrain only on
   development data, and evaluate the locked holdout. AUC improvement greater
   than 0.01 or 5 bp return improvement greater than 5 percentage points marks
   the baseline result suspicious and rejects the run.
3. Repeat with sine/cosine time-of-day and day-of-week features. The same 0.01
   AUC and 5 percentage-point limits apply.
4. Report the dummy classifier and equal-weight long-only sleeve benchmark on
   exactly the same evaluation timestamps and cost assumptions.

The adversarial variants never replace the preselected baseline model, even
when they appear better.

## Acceptance Gates

`RESEARCH_ACCEPTED` requires every condition below:

1. All structural, causal, ledger, and prefix-invariance checks pass.
2. All three outer folds and the locked holdout have ROC AUC greater than 0.50.
3. All three outer folds and the locked holdout have positive total return at
   5 bp one-way cost.
4. A 1,000-sample, five-day moving-block bootstrap of locked-holdout daily
   returns has a 90% total-return lower bound greater than zero.
5. The 20 label permutations pass the stated AUC and return conditions.
6. Noise and calendar feature attacks remain below both suspicion limits.
7. At least 50% of eligible symbols have positive locked-holdout 5 bp return.
8. The five largest positive symbol contributions account for no more than 50%
   of total positive symbol PnL.
9. At 10 bp one-way cost, each outer fold and the locked holdout have total
   return greater than -10% and maximum drawdown below 20%.
10. Returns at 0, 2, 5, 10, and 20 bp are monotonically non-increasing.

A failed condition records its identifier, observed value, required value, and
affected fold. There is no discretionary override.

## Failure Handling

- A malformed source file rolls back its complete import.
- An invalid symbol is excluded and reported; it cannot contribute partial
  features, labels, predictions, or returns.
- Too few symbols, folds, dates, or observations reject the run before fitting.
- A model fitting or prediction exception rejects the affected candidate. If no
  candidate remains, the run is rejected.
- Non-finite probability, price, cost, return, or metric rejects the run.
- A ledger mismatch rejects the run.
- Any final holdout or adversarial gate failure produces `RESEARCH_REJECTED`.
- Report generation preserves the failure evidence instead of suppressing the
  exception or returning an empty successful report.

Warnings are not globally disabled.

## Report Outputs

The command accepts an explicit output directory and creates:

- `report.md`: human-readable conclusion, data exclusions, selected model,
  fold tables, stress tests, gates, and limitations;
- `report.json`: complete machine-readable configuration, provenance, split
  boundaries, metrics, gates, and final status;
- `data_quality.csv`: one row per included or excluded symbol;
- `fold_metrics.csv`: one row per inner, outer, holdout, benchmark, and
  adversarial evaluation;
- `symbol_metrics.csv`: locked-holdout per-symbol results;
- `trades.csv`: the reconciled standardized return ledger.

Every file includes or references one `run_id`. JSON records the source SHA256
values, code revision when available, feature list, model parameters, seed,
thresholds, costs, and exact temporal boundaries.

## Testing Strategy

Implementation follows red-green TDD. Minimum behavioral coverage includes:

1. importer retains open interest and settlement;
2. imported amount is null rather than fabricated;
3. provenance classification and hash are correct;
4. malformed files roll back bars and metadata together;
5. feature values are prefix invariant;
6. future and unknown features are rejected;
7. labels use next open through six-interval-later open;
8. labels do not cross gaps, zero volume, or 3% discontinuities;
9. split labels mature before evaluation and include the embargo;
10. scalers fit only training data;
11. one symbol cannot hold overlapping positions;
12. long and short return formulas and double-sided costs reconcile;
13. terminal close reconciles;
14. cost sensitivity is monotonic for identical trades;
15. fixed sleeves keep gross exposure at or below 100%;
16. a failed data, fold, final, or adversarial gate fails closed;
17. report artifacts agree with the ledger and one another;
18. invalidated legacy engines remain absent from the registry and API;
19. the existing complete Python test suite remains green.

A real-database smoke run must finish with either `RESEARCH_ACCEPTED` or
`RESEARCH_REJECTED`; an unexplained exception, non-finite metric, or partial
report is a test failure.

## Acceptance Criteria

- The database preserves every meaningful numeric source field and honest
  provenance without fabricating amount.
- No feature, scaler, label, split, threshold, or model uses future information.
- No trade crosses a detected data discontinuity or overlaps another position
  in the same symbol.
- Every reported return reconciles to the standardized fixed-sleeve ledger.
- Model selection never observes the locked final holdout.
- All adversarial checks run automatically and determine the terminal status.
- Existing invalidated futures engines remain isolated.
- No lots, multiplier, margin, liquidation, RMB PnL, or live-readiness claim is
  emitted from weighted-index data.
- No new dependency or speculative framework is introduced.
- Existing unrelated dirty-worktree changes are preserved.

## Deferred Work

- Acquiring and validating individual tradable contract data.
- A contract-level roll map and execution simulator.
- Exchange-specific sessions, tick sizes, limits, fees, margin, daily
  settlement, and liquidation.
- Model persistence, registry promotion, paper trading, Web/API exposure, and
  scheduling.

These items are reconsidered only if the offline research path passes its gates
and the project obtains the data needed to make them truthful.
