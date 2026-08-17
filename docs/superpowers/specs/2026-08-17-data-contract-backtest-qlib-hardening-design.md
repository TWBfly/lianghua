# Data Contract, Backtest, and Qlib Boundary Hardening Design

Date: 2026-08-17
Status: Approved for implementation planning

## Objective

Make the stock and futures research surfaces truthful about the data they
consume, the returns they simulate, and the role Qlib plays. Existing rows are
preserved as forensic evidence; invalid or mixed data is blocked at the
backtest boundary instead of being silently repaired or reclassified.

## Root Truths

1. `stock_daily` and `futures_min_bars` are different asset domains.
2. A QFQ price is an adjusted research proxy, not a raw execution price.
3. A weighted futures index is not a tradable contract.
4. A backtest is reliable only for the data semantics and execution contract
   it explicitly declares.
5. Qlib is a model implementation, not a data validator, simulator, or broker.
6. Mixed, unprovenanced, or semantically incompatible data fails closed.

## Current Defects to Close

- `stock_daily` contains 24 `_IDX` futures-index symbols among stock-like rows.
- `stock_daily_catalog` covers only the cataloged subset; uncataloged symbols
  must not silently enter stock portfolios.
- Catalog coverage can be older or shorter than the actual table rows.
- QFQ data is useful for research but cannot be reported as RAW execution.
- Direct legacy futures 15m rows have different coverage and are not the
  canonical audited input.
- Strictness currently depends on individual callers instead of one shared
  asset/data contract.

## Scope

### In scope

- Add explicit `asset_type` and provenance validation for stock catalog data.
- Add a reusable stock asset/data-contract guard used by single and portfolio
  backtests.
- Reject `_IDX`, uncataloged, stale, mixed, or price-mode-incompatible stock
  rows before model or ledger work.
- Preserve QFQ as `ADJUSTED_PROXY` and RAW as `RAW_EXECUTION`.
- Require futures provenance-approved 5m input and retain the existing causal
  15m reconstruction.
- Add truthful report metadata for data mode, source, coverage, and known
  limitations.
- Make Qlib explicitly model-only, provenance-recorded, and fail-closed.
- Add regression tests for all boundaries and one database smoke audit.

### Out of scope

- Deleting or rewriting existing database rows.
- Downloading a new RAW stock history or corporate-action ledger in this phase.
- Claiming strict stock execution until RAW prices and corporate actions exist.
- Connecting Qlib Provider or Executor to replace the project data/ledger.
- Adding new model families, features, hyperparameter search, or dependencies.
- Re-enabling TqSim/live trading.

## Asset Contract

### Stock catalog

Extend `stock_daily_catalog` idempotently with:

- `asset_type`, restricted to `STOCK` or `ETF`;
- existing `price_mode`, restricted to `RAW` or `QFQ`;
- `source`, `start_date`, `end_date`, `row_count`, `updated_at`.

Existing catalogs without `asset_type` are not silently guessed. They remain
`LEGACY_UNVERIFIED` until an explicit migration or catalog refresh assigns the
asset type from a validated symbol registry.

### Stock rows

For a requested stock symbol, validation requires:

- symbol does not end with `_IDX`;
- exactly one catalog row exists;
- catalog `asset_type` is `STOCK` or `ETF` as requested;
- actual `MIN(trade_date)`, `MAX(trade_date)`, and `COUNT(*)` equal catalog;
- every OHLCV/amount value is finite and satisfies the daily-bar contract;
- requested range is fully covered;
- requested `price_mode` equals catalog `price_mode`.

No uncataloged symbol is eligible for a portfolio universe. No row from an
other asset domain is filtered in after loading; it is rejected before loading
the model.

### Price semantics

- `STRICT` requires `RAW` and a verified catalog.
- `RESEARCH_PROXY` permits `QFQ` and reports `ADJUSTED_PROXY`.
- QFQ must never be relabeled as RAW.
- A missing or mismatched catalog returns a structured data-contract error,
  not a legacy fallback.

### Futures rows

The audited futures path accepts only symbols registered in
`futures_series_metadata` with a valid SHA256 and an approved series type. It
loads canonical 5m rows, validates them, segments them, and reconstructs 15m
windows. Direct legacy 15m rows remain forensic-only.

## Backtest Contract

### Stock engine

`KLineBacktestEngine` must call the stock contract before feature construction.
Its existing close-to-next-open causal execution remains the only execution
semantics. The output metadata must include:

- `asset_type`;
- `price_mode`;
- `price_semantics` (`RAW_EXECUTION`, `ADJUSTED_PROXY`, or
  `LEGACY_UNVERIFIED`);
- source and verification status;
- actual coverage range;
- `backtest_mode`;
- limitations including no point-in-time universe, no historical ST/IPO
  status, no corporate-action cash ledger, and approximate transaction rules.

Strict mode rejects QFQ and unverified data. Research-proxy mode runs only
with explicit user selection and labels every artifact accordingly.

Portfolio mode accepts an explicit symbol list. Automatic discovery filters
through the same contract and excludes unregistered or wrong-domain symbols;
it never treats all `stock_daily` symbols as stocks.

### Futures engine

The audited futures engine remains a weighted-index research proxy. It keeps
the existing next-open, fixed-horizon ledger, causal segmentation, nested
temporal validation, cost grid, and adversarial gates. It does not emit
contract-level PnL or live-readiness claims.

### Fail-closed behavior

The following conditions return a structured rejection before model fitting:

- asset type mismatch;
- `_IDX` in a stock run;
- missing catalog or provenance mismatch;
- range or row-count coverage mismatch;
- QFQ requested in STRICT mode;
- direct legacy futures 15m input;
- missing futures metadata or invalid source hash;
- model/ledger identity mismatch.

No fallback to uncataloged data, raw SQL without provenance, another price
mode, or another model is permitted.

## Qlib Boundary

The active flow is:

```text
project data contract
  -> project causal features and labels
  -> Qlib LGBModel or regularized logistic regression
  -> project temporal selection and gates
  -> project ledger and report
```

Qlib receives only validated in-memory matrices. It does not own the market
provider, feature computation, labels, temporal folds, execution, or cash
ledger. Qlib version, local revision, model parameters, and model identity are
recorded in the report.

If Qlib is unavailable or fails, the run is rejected. There is no silent native
fallback. The Qlib candidate competes only with the fixed `C=0.1` logistic
candidate and cannot be selected without later-fold evidence.

Anti-overfitting remains the project's responsibility:

- nested purged walk-forward folds;
- embargo at least as long as the label horizon;
- fixed candidate and threshold domains;
- Dummy and equal-weight baselines;
- label-shuffle, noise, calendar, prefix, and cost attacks;
- multi-block bootstrap and concentration gates.

## Reporting

Every stock report includes the data contract result and price semantics.
Every futures report includes source manifests, raw/aggregated quality counts,
research domain, Qlib provenance, run identity, and rejection reasons.

Report wording is constrained:

- `RAW_EXECUTION` is the only label allowed to describe raw-price execution
  semantics;
- `ADJUSTED_PROXY` means research-only adjusted-price evidence;
- weighted-index futures reports always state that they are not tradable
  contract or live-profit evidence;
- rejected runs retain complete evidence and are not treated as failed builds.

## Test Strategy

Every behavior change follows red-green TDD. Tests cover:

- catalog migration and explicit asset type;
- stock `_IDX` rejection;
- uncataloged symbol rejection;
- catalog row-count/date mismatch;
- QFQ STRICT rejection and QFQ proxy acceptance;
- RAW strict acceptance with verified provenance;
- portfolio filtering of mixed domains;
- futures metadata and canonical 5m-only input;
- report semantics and structured rejection reasons;
- Qlib model-only provenance and no-fallback behavior;
- existing causal, ledger, adversarial, and boundary suites.

A read-only database audit reports current mixed domains and catalog coverage.
It does not mutate the production database. A real stock and real futures smoke
run each produce truthful accepted or rejected evidence with no parameter
retuning after observing results.

## Success Criteria

- Stock and futures assets cannot enter each other's backtests.
- QFQ is never reported as raw execution.
- Uncataloged or stale stock data cannot silently enter a portfolio.
- Futures research continues to use canonical 5m-to-15m reconstruction.
- Qlib is explicitly a model plugin and cannot bypass project validation.
- Reports explain exactly what data and semantics were used.
- All existing tests plus new contract tests pass.
