# vn.py-Inspired Backtest, Indicator, and Data Design

Date: 2026-08-01
Status: Approved design, pending implementation plan

## Objective

Improve the reliability and maintainability of the A-share daily-bar data,
technical indicator, and strategy backtest paths while preserving every
existing Web API request parameter and response field. New response fields
may be added, but existing fields must not be removed, renamed, or change
units.

The design borrows boundaries from vn.py without adding vn.py or TA-Lib as a
runtime dependency. The commercial distribution remains closed source.

## Reference Boundaries

The useful vn.py patterns are:

- explicit market-data contracts and provenance;
- separation of database access from strategy execution;
- a bounded indicator container with explicit warm-up state;
- deterministic order processing before the strategy sees the current bar;
- daily mark-to-market results separated from aggregate statistics.

References:

- https://github.com/vnpy/vnpy/blob/master/vnpy/trader/object.py
- https://github.com/vnpy/vnpy/blob/master/vnpy/trader/database.py
- https://github.com/vnpy/vnpy/blob/master/vnpy/trader/utility.py
- https://github.com/vnpy/vnpy_ctastrategy/blob/main/vnpy_ctastrategy/backtesting.py

This project will not copy those implementations. It will keep its existing
Pandas and SQLite architecture and apply only the boundaries that remove
current ambiguity.

## Scope

### Included

1. A canonical daily-bar DataFrame contract and quality validation.
2. Parameterized data reads and explicit QFQ dataset provenance.
3. Causal technical indicators with documented warm-up behavior.
4. Separation of feature calculation from future-return label calculation.
5. A reconciled daily backtest ledger and richer risk statistics.
6. Explicit expiry records for terminal orders that cannot reach a next bar.
7. Backward-compatible Web API output.

### Excluded

- Tick or intraday bar aggregation.
- A generic plugin or gateway framework.
- Partial-fill simulation without historical order-book data.
- Stop and arbitrary limit order support not used by the current strategy.
- Replacing the current ML strategy or shared-account simulator.
- Point-in-time universe, historical ST/IPO state, or cash corporate-action
  reconstruction where the source data is unavailable.

## Architecture

The end-to-end path remains:

`SQLite/AKShare -> validated bars -> causal indicators -> strategy decisions
-> shared-account simulator -> daily ledger -> aggregate metrics -> Web API`

### Market Data Contract

`AShareDataEngine` remains the only synchronization owner. A small pure
validation function will normalize a loaded frame and reject unsafe data
before indicators or backtests consume it.

Required columns:

- `trade_date`, `open`, `high`, `low`, `close`, `volume`, `amount`;
- `symbol` when a frame contains more than one security.

Invariants:

- dates are valid, unique, and strictly increasing after normalization;
- OHLC and volume fields are finite;
- prices are positive and volume/amount are non-negative;
- `low <= open/close <= high` for each bar;
- a single-symbol load contains only the requested symbol.

Duplicate dates, invalid OHLC relationships, non-finite values, and mixed
symbols are hard errors. Unsorted but otherwise valid rows are sorted.

All SQLite data reads touched by this work use bound parameters. Existing
`stock_daily` rows are not migrated to a wider schema because that would
break existing inserts. Dataset-level provenance is stored in a separate
small catalog keyed by symbol:

- price mode: `QFQ`;
- source: `AKSHARE_STOCK_ZH_A_HIST`;
- earliest and latest trade date;
- row count and refresh time.

The catalog update occurs in the same transaction as full-symbol QFQ
replacement. Existing atomic fetch-before-delete behavior remains.

### Technical Indicators

A pure indicator function receives a validated OHLCV frame and returns an
index-aligned feature frame. It must not read the database and must not create
labels.

Existing public feature names remain stable. Formulas are standardized as:

- simple moving averages: rolling arithmetic mean;
- EMA/MACD: recursive EMA with `adjust=False`;
- RSI(14): Wilder smoothing with alpha `1/14`;
- ATR(14): true range followed by Wilder smoothing with alpha `1/14`;
- Bollinger(20, 2): population standard deviation (`ddof=0`);
- volume ratio: current volume divided by 20-day mean volume;
- returns and bias features: unchanged units from the existing API.

Warm-up values remain `NaN`. They are never backfilled from future rows.
Factor extraction returns the same row index as the validated market frame.
Future-return labels are built by a separate offline-only function.
For backward compatibility, `extract_factors` may attach the existing
`target_5d_return` column by calling that label function; the pure indicator
function itself never creates or consumes future data.

`prepare_drl_environment_matrix` must not normalize using statistics from the
entire dataset. Each sample uses expanding statistics available before that
sample, so later observations cannot change an earlier state tensor.

Causality invariant: calculating indicators for a prefix must equal the same
rows from a longer dataset, including `NaN` placement.

### Strategy Backtest

`simulate_portfolio` remains the single execution and risk engine. Its
current sequencing remains authoritative:

1. execute previously queued orders on the new bar;
2. mark the account at the bar close;
3. evaluate the strategy using information available through that close;
4. queue actionable decisions for the next available bar.

This work will not add a generic event bus or strategy base class. The
current system has one daily strategy path, so those abstractions would not
remove present complexity.

The final reporting date has no next bar. Any BUY or SELL decision created on
that date is returned as an order audit item with status `EXPIRED` and reason
`END_OF_DATA`. HOLD decisions remain non-orders.

### Daily Ledger

A pure ledger builder converts the simulation equity curve and fills into one
row per trading day. Each row contains:

- start and end equity;
- cash and market value at close;
- holding PnL and trading PnL;
- commission, stamp duty, transfer fee where recorded, and slippage;
- turnover and fill count;
- net PnL, daily return, and drawdown.

Reconciliation rules:

- end equity equals cash plus marked position value;
- the sum of daily net PnL equals final equity minus initial capital within
  one cent;
- recorded daily costs sum to the friction summary within one cent;
- the last daily ledger equity equals `simulation.final_equity`.

The current simulator fill schema records total fees. Fee subcomponents will
be added without removing `fees` so the daily ledger can reconcile exactly.

### Aggregate Statistics

The existing metrics stay unchanged. The following fields are appended:

- `annualized_volatility_pct`;
- `sharpe_ratio`, using 252 trading days and zero risk-free rate;
- `sortino_ratio`, using downside deviation;
- `calmar_ratio`, annualized return divided by absolute maximum drawdown;
- `max_drawdown_duration_days`;
- `total_turnover_cny` and `turnover_ratio`.

Undefined ratios return `0.0`, never `NaN` or infinity. Statistics are always
derived from the daily ledger rather than realized trades alone.

## API Compatibility

Existing request parameters, defaults, response keys, field names, and units
remain compatible. The API only appends:

- `daily_results` at the result root;
- the new aggregate metric fields under the existing metrics object;
- dataset provenance under `backtest_metadata.data_provenance`.

Both single-stock and portfolio responses receive the same ledger and metric
semantics. Existing `kelly_allocations` remains as a compatibility key even
though its items already identify the fixed-risk allocation method.

## Error Handling

- Invalid market data is caught at the backtest boundary and returned through
  the existing `{ "error": "..." }` response shape; it is not silently
  repaired except for row sorting.
- An empty or insufficient reporting range keeps the current API error shape.
- A failed remote QFQ refresh leaves both price rows and provenance unchanged.
- Indicator warm-up does not become an error; the strategy receives `NaN`
  until each indicator is ready.
- Metric calculations guard zero balance, zero variance, and empty results.

## Tests and Acceptance

Implementation follows test-first changes. Acceptance requires:

1. Existing 54 tests pass without API compatibility changes.
2. Market-data tests cover sorting, duplicates, invalid OHLC, non-finite
   values, provenance, and atomic refresh rollback.
3. Indicator tests cover known RSI/ATR/Bollinger values, prefix invariance,
   and causal DRL normalization.
4. Backtest tests cover terminal order expiry and next-bar sequencing.
5. Ledger tests reconcile equity and costs to one cent.
6. Single-stock and portfolio integration tests expose the new fields.
7. `python3 -m compileall -q code tests` and `node --check web/app.js` pass.
8. Production `code/` and `web/` contain no vn.py, Backtrader, GPL, or TA-Lib
   import.

## Licensing

vn.py and vnpy_ctastrategy use the MIT License. This implementation uses no
vn.py source or runtime package, so no additional vn.py distribution artifact
is introduced. Backtrader remains an external, temporary differential oracle
only and is not shipped.
