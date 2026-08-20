# TianJi Non-Predictive Automatic Research Layer Design

## Goal

Build a deterministic automatic strategy-research layer for non-predictive
15-minute OHLCV futures rules. The layer generates a finite declared rule
space, evaluates it only on chronological development folds, eliminates weak or
unstable candidates, and emits a reproducible development candidate or an
honest rejection.

Development gates at 5 bps on entry and 5 bps on exit remain:

- payoff ratio `>= 3.0`;
- 15-minute maximum drawdown `<= 0.15`;
- total return `> 0`;
- closed trades `>= 200`;
- every evaluation fold has positive return;
- costs are monotonically non-increasing across `0/2/5/10/15/20` bps.

These are rejection gates, not guaranteed outputs.

## Data and Evidence Boundary

Use only provenance-approved 5-minute weighted-index rows reconstructed to
15-minute bars. Direct unprovenanced 15-minute database rows remain forbidden.

Automatic search uses timestamps strictly earlier than
`2026-06-26 10:45:00`. All viewed holdout reports and timestamps are excluded
from generation, ranking, elimination, tie-breaking, and robustness tests.

The strongest status is `AUTO_DEVELOPMENT_CANDIDATE`. Final acceptance requires
new provenance-approved data later than the viewed holdout.

## Runtime Rule Grammar

Runtime candidates are deterministic OHLCV rules. They contain no trained
model, label, probability, prediction, adaptive coefficient, or online
learning.

### Factor primitives

- signed Kaufman efficiency at 20 and 40 bars;
- Donchian channel position at 20 and 40 bars;
- momentum acceleration at 5/20 and 10/40 bars;
- volume-weighted intraday intensity at 10 and 20 bars;
- causal ATR percentage;
- Amihud liquidity filter;
- volume z-score and volatility-regime filters.

### Signal skeletons

The automatic generator declares exactly 16 signal skeletons from:

- orientation: continuation or reversal;
- lookback family: fast (`20`) or slow (`40`);
- extreme cross-sectional entry quantile: `5%` or `10%`;
- minimum agreeing directional factors: `2` or `3`.

A signal skeleton determines direction and eligibility only. It does not own
position size or exit parameters.

### Execution/risk variants

Stage 2 combines the surviving signal skeletons with a finite risk grammar:

- positions per side: `1` or `2`;
- rebalance check interval: `16` or `32` bars;
- side exposure: `0.20` or `0.30`;
- four predeclared exit profiles, rather than a Cartesian product:
  - `(initial_stop=0.75 ATR, activation=2R, trail=2.5 ATR)`;
  - `(initial_stop=0.75 ATR, activation=3R, trail=3.0 ATR)`;
  - `(initial_stop=1.00 ATR, activation=2R, trail=2.5 ATR)`;
  - `(initial_stop=1.00 ATR, activation=3R, trail=3.0 ATR)`.

Positions per side, rebalance interval, side exposure, and the four exit
profiles form exactly `2 × 2 × 2 × 4 = 32` risk variants.

Unused capacity remains cash. Entries execute at each symbol's next observed
open with live capacity clipping. Stops and exits retain the audited ledger
semantics.

## Staged Search Budget

The search is finite and deterministic.

### Stage 1: Vectorized signal screening

Evaluate all 16 signal skeletons on development folds with a fixed neutral
weight proxy, next-open returns, and 5 bps entry/exit costs. Record payoff,
return, trade count, turnover, and fold stability. Keep at most four skeletons,
ranked by:

1. highest worst-fold payoff ratio;
2. highest worst-fold return;
3. lowest turnover;
4. lexical skeleton ID.

No Stage 1 result may pass final gates; it only reduces the declared search.

### Stage 2: Audited ledger successive halving

Expand at most four Stage 1 survivors across the 32 fixed risk variants, for a
maximum of 128 full candidates.

- Evaluate all candidates on fold 1; keep 32.
- Evaluate those 32 on fold 2; keep 8.
- Evaluate those 8 on fold 3.

At every halving boundary, eliminate candidates with non-finite metrics,
non-positive return, payoff below `1.0`, drawdown above `0.15`, or insufficient
projected combined trades. Rank remaining candidates using the same stable
worst-fold ordering. Candidate IDs and rule dictionaries are immutable.

### Stage 3: Robustness attacks

Candidates passing all development gates undergo:

- costs `0/2/5/10/15/20` bps;
- one-at-a-time sector exclusion;
- removal of the top PnL-contributing symbol;
- adjacent entry-quantile perturbation;
- adjacent stop/trailing perturbation;
- chronological prefix-invariance replay.

A development candidate survives only if the original rule passes every hard
gate and attacks do not make cost ordering invalid, drawdown exceed `0.15`, or
return non-positive. Perturbed variants are robustness probes, not replacement
candidates.

## Selection

Select deterministically among survivors by:

1. highest worst-fold payoff ratio;
2. lowest worst-fold maximum drawdown;
3. highest combined 5 bps return;
4. lowest turnover;
5. lexical candidate ID.

No result-dependent parameter mutation or second search run is allowed. If no
candidate survives, status is `AUTO_DEVELOPMENT_REJECTED`.

## Architecture

Keep `futures_research_backtest.py` as the audited data/feature/ledger owner.
Add a focused automatic-research module responsible for:

- frozen search-space generation;
- vectorized Stage 1 screening;
- successive-halving orchestration;
- robustness attacks;
- deterministic selection;
- development report serialization.

The existing manual three-candidate development report remains evidence but is
not part of the automatic search.

## Evidence Bundle

Write atomically to a new directory:

- `auto_research_report.json`;
- `search_space.json`;
- `stage1_metrics.csv`;
- `stage2_metrics.csv`;
- `attack_metrics.csv`;
- `survivors.csv`;
- `selected_rule.json` when a survivor exists;
- `auto_research_report.md`.

Every report records database hash, code revision, development cutoff, search
space hash, candidate counts at each stage, deterministic seed, rules, metrics,
gates, attacks, and limitations. Refuse overwrite.

## Tests

Tests prove:

- the search grammar generates exactly 16 signal skeletons and 32 risk variants;
- candidate IDs and search-space hashes are stable under input ordering;
- runtime rules contain no predictive fields;
- no timestamp at or after the forbidden holdout enters any stage;
- Stage 1 keeps at most four skeletons;
- successive halving is exactly `128 -> 32 -> 8` at maximum;
- elimination and tie-breaking are deterministic;
- robustness probes cannot replace the original rule;
- hard gates require payoff 3, drawdown 15%, positive return, and 200 trades;
- status can never be `RESEARCH_ACCEPTED`;
- report files reconcile and refuse overwrite;
- all existing data, ledger, Qlib, and manual-development tests remain green.

## Scope and Safety

No new dependency, database mutation, network data source, predictive model, or
live-trading path is added. The automatic layer can discover and reject rules;
it cannot guarantee that the market contains a qualifying strategy.
