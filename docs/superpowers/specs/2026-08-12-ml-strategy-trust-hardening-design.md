# ML Strategy Trust Hardening Design

Date: 2026-08-12
Status: Approved for planning

## Objective

Harden the trusted A-share causal ML path without adding model families or
rewriting the backtest architecture. The change removes batch-level regime
look-ahead, makes ATR exits use actual filled-position state, enforces the
existing liquidity ceiling, and compares Challenger and Champion models on the
same shadow observations.

Standalone futures and XAUUSD research engines remain on disk but are formally
classified as invalidated research artifacts and kept outside every executable
strategy and API registry.

This phase does not procure, infer, or fabricate point-in-time universes, raw
execution prices, corporate actions, licensed market data, or historical
security-status records. Those remain separate data-provider work.

## Chosen Approach

Apply root-cause fixes in the existing shared functions and simulator. Do not
introduce a stateful strategy framework, evaluator hierarchy, or new model
abstraction.

The alternatives were rejected for this phase:

- a new strategy-context and evaluator framework would enlarge the diff across
  an already dirty working tree;
- disabling regime filtering, evolution, and ATR risk entirely would remove
  behavior that can be made truthful with smaller shared fixes.

## Production Boundary

`KLineBacktestEngine` and `simulate_portfolio` remain the only trusted
historical ML decision and execution path.

The standalone futures and XAUUSD modules remain in their existing locations.
They are listed in a research-status document as
`RESEARCH_ONLY_INVALIDATED`. A regression test asserts that none of their
module or strategy names appears in `hot_plugger.get_executable_strategies()`
or the `/api/strategies` response.

Existing JSON outputs from those modules remain historical artifacts. They are
not rewritten into valid results and are not used by the trusted path.

## Per-Date Regime Inference

`ml_ensemble.walk_forward_predict` continues to fit one ensemble per causal
walk-forward split using the existing fixed policy:

- 504 mature training labels;
- 21-date prediction batches;
- five-trading-day label horizon;
- only labels whose `label_end_time` is strictly earlier than the first
  prediction date.

The fitted ensemble no longer selects one regime from the final date and uses
it for the full prediction batch. Prediction rows are grouped by their own
causally calculated regime. Each group is predicted with its matching
regime-specific model when available; otherwise it uses the fitted global
model. Results are written back in the original prediction-index order.

Appending future rows must not change previously emitted probabilities.

## Position-Aware ATR Risk Exits

Signal generation remains stateless. A causal-ML BUY decision carries the
signal-date ATR and fixed risk parameters:

- stop: `max(entry_price - 1.25 * entry_atr, entry_price * 0.972)`;
- take profit: `entry_price + 2.5 * entry_atr`;
- trailing activation: prior peak above `entry_price * 1.03`;
- trailing stop: `prior_peak - 1.0 * entry_atr`.

The shared simulator owns all position-dependent state. After a BUY actually
fills, the position records its real fill price, entry ATR, enabled risk policy,
and peak price. The policy layer never fabricates a position from a signal.

For each session the simulator applies this order:

1. execute queued explicit orders at the open, with SELL before BUY;
2. for positions held from an earlier trading date, evaluate intraday ATR
   exits using that session's high and low;
3. mark the remaining position at the close;
4. update the stored peak only after the current session's exit decision.

This preserves A-share T+1. A position cannot be risk-exited on its entry date.
If stop and take-profit levels are both touched in one bar, the stop wins.
Trailing decisions use only the peak known before the current bar, avoiding an
unknown intrabar high/low sequence.

Risk exits use the existing sell-cost function, including commission, transfer
fee, stamp duty, and adverse slippage. They create an auditable terminal fill
and close the original entry trade with an explicit exit reason.

When ATR is missing or non-positive, the BUY decision records
`risk_exit_status=UNAVAILABLE`, no ATR policy is attached to the filled
position, and existing explicit MA/probability exits remain available.

## Liquidity Ceiling

`FeeSchedule.max_bar_volume_fraction` becomes an enforced execution constraint.
The executable volume is the existing causal mean of up to 20 prior bars; the
current bar's final volume is not used to size an opening order.

For BUY orders, maximum shares equal executable volume multiplied by the
configured fraction and rounded down to the symbol's valid trading unit. The
filled order is capped at that quantity. If the cap is below the minimum lot,
the order is rejected with `LIQUIDITY_LIMIT`.

An exit that exceeds the same ceiling is rejected with `LIQUIDITY_LIMIT` and
the position remains open. Later explicit or risk-exit attempts may retry. This
phase deliberately avoids partial-position accounting.

No order may fill above the configured ceiling.

## Same-Window Champion/Challenger Evaluation

The offline candidate holdout remains unchanged. Shadow promotion changes only
after new completed observations arrive beyond the candidate's
`evaluated_until` cutoff.

For the same shadow frame, `EvolutionManager.evaluate_shadow`:

1. loads and validates the Challenger artifact;
2. loads and validates the current Champion artifact when one exists;
3. aligns each model to its own declared feature list;
4. produces dated probabilities for both models on the identical shadow index;
5. evaluates both through separate calls to `evaluate_predictions`, which uses
   the same market slice, initial cash, decision policy, costs, and production
   simulator;
6. applies the existing return, drawdown, turnover, Brier, kill-switch, and
   per-window gates to the two contemporaneous metric objects.

When no Champion exists, the existing absolute baseline gate applies to the
Challenger. When a Champion exists but its artifact is missing, escapes the
model directory, has incompatible features, or cannot predict, promotion fails
closed and returns an explicit error. Stored historical Champion holdout
metrics are never substituted for same-window metrics.

`promote_if_ready` must require contemporaneous Champion metrics whenever a
Champion exists. Calling it without those metrics returns `False`.

## Error Handling

- A missing regime-specific model falls back to the fitted global model for
  only those prediction rows.
- Non-finite regime predictions remain unavailable and do not borrow another
  date's state.
- Missing ATR disables only ATR exits and is recorded in decision features.
- A liquidity ceiling below one valid lot produces `LIQUIDITY_LIMIT`.
- A failed liquidity-constrained exit leaves the position intact.
- Invalid Challenger or Champion artifacts fail promotion without replacing
  same-window evidence with stored historical metrics.
- Invalidated research modules remain importable for forensic review but are
  never executable through the trusted registry.

## Testing

Implementation follows test-first red-green cycles. Required checks are:

1. A mixed-regime prediction batch routes each row to the correct sub-model.
2. Appending future dates does not change existing walk-forward predictions.
3. Missing regime sub-models use the global model only for affected rows.
4. A causal-ML BUY decision records ATR risk metadata when ATR is available.
5. Missing ATR records `risk_exit_status=UNAVAILABLE`.
6. ATR stop, take-profit, and trailing exits use actual fill state and existing
   sell costs.
7. T+1 prevents an ATR exit on the entry date.
8. A same-bar stop/take-profit collision exits at the stop.
9. The current bar cannot raise a trailing peak before its exit check.
10. Filled BUY shares never exceed the causal volume ceiling.
11. A below-lot ceiling rejects an entry with `LIQUIDITY_LIMIT`.
12. An oversized exit is rejected and preserves the position.
13. Challenger and Champion predictions use the identical shadow index.
14. A Champion cannot be compared through its old holdout metrics.
15. Missing or incompatible Champion artifacts block promotion explicitly.
16. Invalidated futures and XAUUSD modules remain absent from the executable
    strategy registry and `/api/strategies`.
17. The complete existing Python test suite remains green.
18. The Web JavaScript syntax check remains green.
19. A real-database research-proxy smoke test returns a truthful result or an
    expected fail-closed error.

## Acceptance Criteria

- No prediction row uses a later date's regime.
- ATR exits are based on filled-position state, never precomputed assumed
  positions.
- No fill exceeds `max_bar_volume_fraction`.
- A model cannot become Champion by comparing different evaluation periods.
- Invalidated research engines cannot enter the trusted executable surface.
- No new dependency, model family, strategy framework, or data claim is added.
- Existing dirty-worktree changes unrelated to this phase are preserved.

## Deferred Work

- Licensed point-in-time universe and security-status history.
- Raw execution bars and a complete corporate-action cash ledger.
- A single timestamp-aligned futures evaluator with margin and liquidation.
- Real XAUUSD data and a position-reconciled evaluator.
- Reconsidering any invalidated engine only after it passes the same trusted
  simulator and temporal-validation contract.

