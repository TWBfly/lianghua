# TianJi 15M Non-Predictive Futures Strategy Design

## Goal

Replace the experimental predictive TianJi implementation with one auditable,
non-predictive 15-minute futures strategy in
`code/futures_research_backtest.py`. The locked holdout is evaluated with 5 bps
charged on entry and another 5 bps on exit, using the repository's existing
`cost_bps` convention.

The locked-holdout acceptance gates are all mandatory:

- average winning trade divided by average losing trade is at least `1.8`;
- 15-minute mark-to-market maximum drawdown is at most `10%`;
- at least `200` closed trades;
- total return is greater than zero.

Failure remains a truthful `RESEARCH_REJECTED`; the locked holdout is not used
to retune the strategy.

## Scope

The official path remains `code/futures_research_backtest.py`. The change uses
the existing provenance checks, causal 5-minute-to-15-minute aggregation,
segmentation, atomic evidence bundle, cost stress grid, and ledger
reconciliation. Tests remain in `tests/test_futures_research_backtest.py`.

The two untracked `scratch_test_tianji_15m_*` scripts are comparison artifacts,
not production inputs. They are not extended or promoted. No new strategy
framework, dependency, model adapter, or reporting path is added.

## Non-Predictive Contract

The TianJi run records `predictive=false` and one frozen rule set. It does not
create future-return labels, fit Qlib or another model, optimize thresholds,
select candidates, or use holdout returns to choose factors, weights, exits,
or exposure.

The holdout is the final chronological 20% of eligible decision times. The
preceding 80% may be used to verify data availability and operational
plausibility, but not to search parameters. The holdout is evaluated once after
tests and development checks pass.

## Data Flow

1. Load provenance-approved weighted-index 5-minute futures OHLCV rows.
2. Validate and segment unusable boundaries before aggregation.
3. Aggregate only complete natural-boundary three-bar windows to 15 minutes.
4. Compute causal features independently per symbol and feature segment.
5. Rank eligible symbols cross-sectionally at each completed 15-minute bar.
6. Rebalance every 16 bars, enforcing long, short, sector, and exposure caps.
7. Generate decisions at bar close and execute entries or signal exits at the
   next bar open.
8. Apply stops using only information available before the evaluated bar.
9. Mark every open position on every 15-minute close and reconcile cash,
   positions, costs, turnover, exposure, trade PnL, and portfolio equity.
10. Produce the existing JSON, CSV, Markdown, and HTML evidence bundle.

Missing, discontinuous, non-finite, duplicate, or provenance-invalid data fail
closed through the existing research rejection mechanism.

## Frozen OHLCV Score

The score uses four equally weighted cross-sectional percentile ranks whose
direction is explicit:

1. signed Kaufman efficiency: `sign(ret_20) * kaufman_efficiency_20`;
2. 20-bar Donchian position centered around zero;
3. 5/20-bar momentum acceleration;
4. 10-bar volume-weighted intraday intensity.

Amihud illiquidity is a filter, not a directional alpha: symbols in the worst
cross-sectional 20% at a decision time are ineligible. Volatility measures are
used for sizing and stops, not as directional forecasts. Each rolling input
uses only the current completed bar and earlier bars; the generated order is
delayed to the next open.

## Portfolio Construction

At each 16-bar rebalance, the strategy selects the four highest eligible scores
for longs and four lowest for shorts. Each side may contain at most two symbols
from one sector. Existing positions remain only while they are still selected;
signal removals execute at the next open.

Target gross exposure is `0.8x`: `0.4x` long and `0.4x` short, keeping target
net exposure at zero. Each side is weighted by inverse causal ATR percentage
and normalized back to its `0.4x` budget. A symbol cannot appear on both sides.
If a side cannot fill four valid symbols, its unused budget remains cash; the
opposite side is not enlarged.

## Execution and Risk

ATR uses the standard true range and a frozen 20-bar rolling mean. A position's
initial protective stop is one entry-time ATR from its entry price. The stop
then trails the favorable extreme by `2.5` current ATR while never loosening:

- long stop: maximum of the prior stop and prior completed-bar highest high
  minus `2.5 ATR`;
- short stop: minimum of the prior stop and prior completed-bar lowest low plus
  `2.5 ATR`.

The stop for a bar is frozen before that bar is inspected. If the bar opens
beyond it, execution uses the worse opening price; otherwise execution uses the
stop price when the bar range touches it. A protective stop takes priority over
a pending signal exit. No fixed take-profit is used.

Entry and exit each pay the configured cost. The primary acceptance ledger uses
`5` bps; `10`, `15`, and `20` bps are reported as stress results. Trade identity
and gross execution paths must remain frozen across cost runs.

## Metrics and Gates

Maximum drawdown is calculated from the full 15-minute marked equity path,
including open-position adverse excursion. Daily returns remain available for
annualized volatility and Sharpe calculations, but daily closes do not replace
the intraday drawdown metric.

The payoff ratio is exactly:

`mean(positive closed-trade PnL) / abs(mean(negative closed-trade PnL))`.

It is reported separately from profit factor, which is gross profit divided by
gross loss. Zero-loss or insufficient-trade inputs fail closed rather than
producing an infinite success metric.

Acceptance requires all four locked-holdout gates in the Goal section at 5 bps.
Existing integrity, causality, cost monotonicity, provenance, and report
consistency gates remain mandatory.

## Tests

The smallest focused tests prove:

- feature and score prefixes do not change when future bars are appended;
- signals at one close cannot trade before the next open;
- stop state uses only prior completed bars and handles gap-through fills
  conservatively;
- long and short budgets, zero target net exposure, symbol uniqueness, and
  sector caps hold;
- entry and exit both pay costs and higher costs cannot improve results;
- trade PnL, marked 15-minute equity, cash, exposure, turnover, and drawdown
  reconcile;
- payoff ratio differs correctly from profit factor;
- the TianJi run domain contains no labels, model fitting, candidate selection,
  or predictive metrics;
- a run passes only when all four 5 bps holdout gates pass.

The existing futures research test suite must remain green. The final real-data
run writes to a new evidence directory and never overwrites prior reports.

## Known Limitations

OHLCV cannot reveal the ordering of intrabar high and low. Stops are therefore
evaluated from a level frozen before the bar, with gap fills handled
conservatively. Weighted-index futures rows are research proxies rather than
tradable expiring contracts, so live trading remains disabled.
