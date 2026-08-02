# HMM Market Regime Filter Design

Date: 2026-08-02
Status: Approved for implementation

## Objective

Add a causal, market-level Hidden Markov Model regime filter to the trusted
`KLineBacktestEngine` path. The filter identifies three latent states from the
CSI 300 index and changes new-entry exposure without changing execution rules
or claiming that HMM predicts returns.

The first release is a research-proxy experiment. It must make the baseline and
filtered policies directly comparable through the existing shared-account
simulator.

## Scope

The implementation includes:

- one three-state Gaussian HMM using CSI 300 (`000300`) daily bars;
- fixed-window, monthly walk-forward fitting;
- causal forward-filtered state probabilities;
- stable economic state names across refits;
- entry filtering and position-size scaling before decisions enter the
  simulator;
- audit metadata and deterministic tests.

It excludes:

- hierarchical or multi-timescale HMMs;
- forced liquidation on a regime change;
- feeding regime decisions into Champion/Challenger evolution;
- Web UI controls;
- per-symbol HMMs or per-strategy parameter tuning;
- translating the licensed TradingView HMM source.

## Existing Boundaries

`KLineBacktestEngine` is the only historical strategy entry point. It generates
close-time decisions and submits them to `simulate_portfolio`, which executes
orders at the next available open with the existing A-share constraints.

The legacy hybrid and 3D fusion classes remain current-snapshot research tools
and are unchanged. `simulate_portfolio` remains strategy-agnostic and is also
unchanged.

The local `env10` environment already provides `hmmlearn==0.3.2`; no HMM
algorithm is reimplemented. Import failure when the filter is enabled produces
an explicit unavailable result instead of silently running an unfiltered
strategy.

## Market Observations

The model consumes three causal observations calculated from CSI 300 closes:

1. one-day log return;
2. 20-day realized volatility of log returns;
3. 20-day mean log return divided by 20-day volatility.

Observation normalization is fitted only on each training window. Prediction
observations use that frozen training mean and standard deviation.

The index query loads all rows through `end_date`, including pre-reporting
history needed for the 504-day training window. State outputs are aligned to
stock decision dates by exact trading date. A missing state on a decision date
is unavailable; no forward fill across missing market dates is allowed.

## Walk-Forward Policy

Policy constants are fixed:

- hidden states: 3;
- covariance type: diagonal;
- training window: 504 valid observations;
- refit interval: 21 trading days;
- random seed: 42;
- market index: `000300`.

For each 21-day prediction batch, parameters are fitted on the newest 504 valid
observations strictly earlier than the first prediction date. The fitted
transition matrix, emission means, and variances are frozen for the batch.

Inference uses the forward recursion and reports
`P(z_t | x_1, ..., x_t)`. Full-sequence Viterbi paths, smoothed posteriors, and
future observations are prohibited.

Before 504 valid training observations exist, output rows have status
`INSUFFICIENT_HISTORY` and no state probabilities.

## Stable State Naming

Raw HMM state identifiers are permutation-invariant. After each fit, states are
named from their emission means in the normalized trend-strength dimension:

- largest mean: `LOW_VOL_BULL`;
- smallest mean: `HIGH_VOL_BEAR`;
- remaining state: `RANGE`.

The names are audit labels, not constraints forced during model fitting. The
output preserves all three posterior probabilities and the raw state
parameters so weak or economically implausible separation remains visible.

A batch is unavailable when fitting fails, probabilities are non-finite, or a
state receives no effective training occupancy. The failure is recorded rather
than replaced by a baseline signal.

## Decision Overlay

The regime result is calculated once per backtest and shared by every symbol.
Each strategy first produces its existing raw action. The overlay then applies:

| Regime | BUY | SELL | Target fraction |
|---|---|---|---|
| `LOW_VOL_BULL` | unchanged | unchanged | 100% of base |
| `RANGE` | unchanged | unchanged | 50% of base |
| `HIGH_VOL_BEAR` | convert to `HOLD` | unchanged | 0% for new entries |

`HOLD` remains `HOLD`. Existing positions are not force-sold. Every overlaid
decision records state, probabilities, status, and base/scaled target fraction
inside `features_json`.

When regime filtering is enabled and the state is unavailable, a raw `BUY`
becomes `HOLD` with a regime-unavailable reason. `SELL` remains allowed so the
filter can never trap an existing position.

## Backtest Interface and Metadata

Both single-symbol and portfolio backtests add a backend-only
`regime_filter=False` argument. The default preserves all current behavior and
API responses.

When enabled, metadata adds one `market_regime` object containing:

- enabled flag and policy version;
- index code, training window, refit interval, and state count;
- coverage and unavailable counts;
- per-state day counts;
- filtered-buy and scaled-buy counts.

The Web API does not expose the flag in this phase. Direct Python tests and
research calls opt in explicitly.

`persist_experiences=True` remains supported for audit storage, but combining
`regime_filter=True` with `run_evolution=True` is rejected until experience
queries are isolated by strategy policy. This prevents filtered, unfiltered,
and mechanical decisions from being mixed by `completed_frame`.

## Data and Truthfulness

The current database has no verified `index_daily` provenance catalog and its
`stock_daily_catalog` is empty. Enabling HMM does not upgrade the backtest to an
investable or strict historical claim.

Research-proxy metadata therefore adds `UNVERIFIED_MARKET_REGIME_DATA` to the
limitations when the filter is enabled. Existing strict stock-data gates remain
authoritative.

## Error Handling

- Invalid or missing CSI 300 bars produce `REGIME_DATA_UNAVAILABLE`.
- Missing `hmmlearn` produces `REGIME_DEPENDENCY_UNAVAILABLE`.
- Insufficient history produces dated unavailable outputs and no entry bypass.
- Model convergence or numeric failure produces `REGIME_MODEL_UNAVAILABLE`.
- Missing state alignment on a stock decision date blocks only BUY decisions.
- SELL decisions always pass through.

## Testing

Tests must prove:

1. Appending future rows does not change earlier observation values or filtered
   probabilities.
2. Every HMM training row is earlier than its prediction batch.
3. Raw state identifiers are mapped to stable economic names.
4. Bull entries retain base exposure, range entries use half exposure, and bear
   entries become HOLD.
5. SELL passes through every state and unavailable status.
6. A portfolio computes one shared regime frame for all symbols.
7. The default-disabled path preserves existing metadata and behavior.
8. Filter plus evolution is rejected explicitly.
9. The complete existing test suite remains green.

## Rollout Decision

The first evaluation compares identical fixed symbol lists and dates with the
filter off and on through the same simulator. Evidence focuses on net return
after costs, maximum drawdown, Calmar, Sortino, turnover, state occupancy, and
per-window behavior.

Hierarchical HMMs, soft probability sizing, forced exits, and evolution support
are added only if this single-layer overlay shows stable out-of-sample benefit.
