# Backtest Reliability Design

## Goal

Make the existing A-share backtest suitable for commercial closed-source
distribution while using Backtrader only as an internal, non-shipping oracle.

## Licensing Boundary

- Production code must not import, vendor, copy, or declare Backtrader as a
  runtime dependency.
- Backtrader may be installed temporarily outside the project and used by an
  internal differential check that is not part of the product distribution.
- The production simulator remains independently implemented from documented
  A-share rules and the existing public result contract.

## Production Architecture

`KLineBacktestEngine` remains the API facade and signal builder.
`simulate_portfolio` remains the single shared-account execution path. The Web
API and chart payload keep their current top-level shape so the UI does not need
a migration.

The simulator will:

- execute close decisions at the following open;
- enforce non-negative cash, board-specific buy quantities, T+1 sells, fees,
  slippage, suspension checks, and price limits;
- use date-versioned stamp duty;
- leave positions open at the requested end date and mark them to market;
- keep the final equity-curve return consistent with final equity;
- expose open positions rather than fabricating a terminal sale.

## Causal ML And Learning

Backtests load history before the requested start date for indicator and model
warm-up, but only execute and report decisions inside the requested interval.

The learning store records the actual five-bar label maturity date. Model
metadata uses that maturity date as `trained_until`, time-series validation has
a five-row gap, and policy-return evaluation samples non-overlapping five-bar
horizons. Historical backtests are pure by default: experience persistence and
model evolution require explicit opt-in.

## Data Integrity

Forward-adjusted daily data is refreshed as a full symbol history before it is
replaced, avoiding mixed adjustment bases after corporate actions. Results
declare the adjusted-price proxy and current-snapshot universe limitations.
Because the database has no point-in-time constituents, delisted securities, or
historical ST status, the code will not claim survivorship-bias-free results.

The existing automatic portfolio universe stays available for UI compatibility,
but is reported as `CURRENT_SNAPSHOT` and carries a warning. Explicit symbol
lists are reported as `USER_SELECTED` and carry a selection-bias warning.

## Reporting

- The reported period uses actual first and last simulated bars.
- Annual returns come from year-end equity changes, not trade exit-year PnL.
- The fake Kelly aliases and zero win-rate/profit-loss values are replaced by a
  truthful fixed-risk allocation payload; the frontend wording is updated.
- Results include engine, price mode, universe mode, fallback-signal count, and
  research limitations.

## Verification

Tests are written before each production change. Focused regression tests cover
terminal open positions, T+1, fee cutover, STAR quantities, label maturity,
purged/non-overlapping evaluation, warm-up behavior, pure defaults, yearly
equity returns, and metadata warnings.

An internal temporary Backtrader check compares a simple multi-asset scenario
for next-open timing, shared cash, commissions, slippage, and final marked
equity. Backtrader is not added to production requirements or imports.

## Non-Goals

- Reconstructing historical constituents, delisted stocks, ST intervals, cash
  dividends, rights issues, or tick-level order books from unavailable data.
- Claiming the adjusted-price proxy is broker-statement exact.
- Replacing the existing ML strategy or Web API with Backtrader types.
