# Rolling Validation Hardening Design

Date: 2026-08-02
Status: Approved

## Objective

Make the causal walk-forward path the only historical ML evaluation path, raise
the minimum evidence required before an ML prediction is emitted, and make model
artifacts reproducible from their data, features, label policy, parameters, and
code identity.

This phase changes code and tests only. Point-in-time market data, historical
universes, corporate actions, financial announcement timestamps, and revision
history remain a separate data-provider phase. Strict backtests continue to
reject data that cannot support those claims.

## Chosen Approach

Use a fixed-window, nested walk-forward design. A single date split remains too
easy to contaminate at the label boundary, while the current expanding window
keeps obsolete regimes forever and starts a 55-feature model after only 120
overlapping labels. Random splitting is prohibited.

Defaults are deliberately fixed rather than configurable through the Web UI:

- training window: 504 mature trading-day labels;
- label horizon and purge boundary: 5 trading days;
- retraining step: 21 trading days;
- final holdout: the last 252 completed observations;
- outer evaluation: at least 3 chronological windows;
- insufficient history: `HOLD`, never a rule score labelled as ML;
- model parameters: one shared configuration, never tuned per symbol.

These values are policy defaults, not historically optimized claims. Changing
one requires a new model-policy version and a new untouched holdout period.

## Architecture

### 1. Prediction Splits

`ml_ensemble.walk_forward_splits` remains the single split constructor. It will
select only rows whose `label_end_time` is strictly earlier than the first
prediction date, then retain only the most recent 504 mature rows. Prediction
batches advance 21 trading days at a time.

The split object will continue to expose explicit train and prediction indexes.
No general cross-validation framework or strategy abstraction is added.

Before 504 mature rows exist, `walk_forward_predict` returns a row with:

- `probability = NaN`;
- `score = NaN`;
- `model_version = "INSUFFICIENT_HISTORY"`;
- `trained_until = NaT`.

The backtest decision builder converts such rows to `HOLD` with reason
`INSUFFICIENT_HISTORY`. The existing `causal-rule-v1` fallback is removed from
the ML path so a heuristic can no longer inflate ML coverage.

### 2. Nested Temporal Evaluation

Hyperparameter selection, if introduced later, may run only inside the 504-row
training window with chronological folds and a five-row gap. This phase keeps
the current fixed LightGBM parameters and does not add a search dependency.

The final 252 completed observations are excluded from candidate fitting and
inner validation. They are evaluated once as the candidate's outer holdout.
Candidates with fewer than three valid chronological evaluation windows are not
eligible for shadow status.

The holdout model is trained only on observations before the holdout. It is not
refit on holdout outcomes before entering shadow mode. Later observations must
arrive chronologically through the experience store before promotion.

### 3. Continuous Portfolio Evaluation

`learning_loop.evaluate_predictions` will submit all dated decisions to one
`simulate_portfolio` call with one initial cash balance. Fold metrics are slices
of that continuous ledger; folds must not reset cash or independently compound
returns.

The same next-open execution, fees, slippage, T+1, price limits, and shared cash
rules therefore determine backtest reporting and model promotion.

### 4. Reproducible Model Identity

Every trained model version must change when any of the following changes:

- symbol and `trained_until`;
- ordered feature names;
- exact training feature values and labels;
- label horizon and threshold;
- training window and retraining step;
- model class and `get_params()` output;
- an explicit model-policy schema version.

Canonical JSON plus SHA-256 is sufficient. No external registry service is
added. Both walk-forward predictions and evolution artifacts use the same
identity helper. Artifacts are written only after the identity is calculated;
an existing registry row must never silently refer to newly overwritten model
bytes.

### 5. Legacy Path Boundary

`AShareMLStrategyEngine.train_and_eval` is disabled as a historical evaluation
entry point and raises a clear error directing callers to
`KLineBacktestEngine`. The legacy current-selection flows may continue to build
the current snapshot model through a separate `fit_current_model` method, but
they must return metadata stating:

- `scope = CURRENT_SNAPSHOT_RESEARCH_ONLY`;
- `historical_backtest = false`;
- `point_in_time_universe = false`.

`AShareHybridBacktester` keeps its compatibility class name but may not print or
return historical performance claims. It remains a proposed current allocation
helper, not a backtester.

### 6. Reporting

Backtest metadata adds:

- `training_mode = FIXED_WINDOW_WALK_FORWARD`;
- `training_window = 504`;
- `retrain_every = 21`;
- `label_horizon = 5`;
- `holdout_size = 252`;
- `insufficient_history_count`;
- model and policy hashes used by each prediction batch.

Existing strict/research-proxy provenance fields remain authoritative. These
training improvements do not upgrade QFQ or legacy data into point-in-time data.

## Error Handling

- Invalid window, horizon, or retraining values raise `ValueError` before model
  fitting.
- Fewer than 504 mature labels produce explicit insufficient-history rows and
  no model fit.
- A one-class training window produces `INSUFFICIENT_CLASS_VARIATION` and no
  probability.
- Missing market coverage still fails promotion evaluation.
- A version collision with different artifact bytes fails closed rather than
  overwriting the registered artifact.

## Testing

Tests use deterministic data and real split/model code where practical.

Required checks:

1. A training split contains at most 504 rows and uses the newest mature rows.
2. Every training label matures before its prediction batch.
3. Default prediction batches advance 21 trading days.
4. Fewer than 504 mature labels never produce a model probability or rule
   fallback.
5. The backtest converts missing probabilities to `HOLD` without an order.
6. Model identity changes when data, labels, parameters, or policy changes.
7. Candidate evaluation invokes the simulator once and derives chronological
   window metrics from one continuous equity curve.
8. The last 252 completed observations are absent from candidate fitting.
9. The legacy single-split evaluation entry point is disabled.
10. Existing market-data, signal prefix-invariance, execution, ledger, API, and
    full-suite tests remain green.

## Operational Rollout

The change is fail-closed. Stocks with insufficient history will show no ML
trades until 504 mature labels exist. This is an expected reduction in apparent
coverage, not a regression.

No existing pickle under `data/ml_models/` is promoted automatically. Models
without the new policy identity are legacy artifacts and remain unused by the
causal registry.

## Deferred Data Phase

The following remain blockers for investable or strict historical claims:

- raw prices and complete corporate actions;
- point-in-time universe membership, listing, delisting, and ST intervals;
- timestamped financial announcements and revision history;
- licensed data provenance and immutable snapshots;
- currency and FX ledgers before any non-CNY asset is added.

No placeholder schema or inferred historical value will be added in this phase.

## Non-Goals

- Random train/test splitting.
- Automated hyperparameter search.
- Per-symbol parameter tuning.
- New model families or ensembles.
- Translating additional TradingView scripts.
- Making research-proxy results look like strict backtests.
- Procuring or fabricating point-in-time data.
