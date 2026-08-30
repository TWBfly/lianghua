# P0 Trust and Security Hardening Design

## Goal

Make every production-facing strategy decision fail closed: missing evidence,
negative validation results, unavailable execution code, or missing credentials
must block approval, export, deployment, and remote code registration.

This is the first of two repair batches. It does not change historical market
data, implement a new broker adapter, or redesign the futures backtest engine.

## Scope

### Included

1. Make `StrategyEvaluatorAgent` reject incomplete evidence instead of filling
   missing inputs with favorable defaults.
2. Replace hard-coded audit scores and verdicts with measured gates in the
   Tianji V2 and optimized macro-trend audit paths.
3. Train and select AutoQuant genomes only on the training partition, evaluate
   the selected champion once on OOS data, and block export when OOS gates fail.
4. Remove backward filling from AutoQuant causal features.
5. Disable HTTP submission and execution of Python strategy source.
6. Remove committed credential fallbacks and require explicit environment
   configuration.
7. Require SSH host-key verification in deployment scripts.
8. Mark the Tianji V2 heartbeat-only daemon as unavailable and prevent deploy
   scripts and dashboard status from presenting it as a live trading engine.
9. Add focused regression tests for every changed trust boundary.

### Deferred to batch two

- Main-continuous to tradable-contract mapping and roll execution.
- One canonical futures contract-specification table and shared simulator.
- Qlib label-boundary purge and next-open portfolio execution.
- A-share ATR gap-stop and open-position trade-statistic corrections.
- Data freshness, raw payload hashes, and source-manifest redesign.
- Project packaging and default pytest collection cleanup.

## Design Principles

- Missing evidence is failure, never success.
- Generated prose, grades, and verdicts must derive from stored numeric facts.
- OOS data is read once after selection and never influences optimization.
- A process heartbeat is not market connectivity or execution readiness.
- Remote Python execution is disabled instead of attempting to build a sandbox.
- Secrets have no source-code fallback.
- Existing public interfaces remain where safe; unsafe interfaces return an
  explicit stable error rather than silently continuing.

## Components

### 1. Fail-closed strategy evaluation

`StrategyEvaluatorAgent.evaluate_strategy` will require these evidence fields
before an approval-capable score can be produced:

- Metrics: `total_net_pnl`, `profitable_symbols_ratio`, `max_drawdown`,
  `turnover_ratio`, `double_cost_profitable`, and the existing prediction and
  risk metrics used by the scorecard.
- Attacks: `label_shuffle_pass`, `prefix_invariance_pass`,
  `ledger_reconciled`, `noise_features_pass`, and
  `calendar_features_pass`.

Absent, non-finite, or false required evidence creates a hard-fail reason and a
zero score. Tail-risk, leverage-safety, prefix, and execution points are awarded
only from explicit true evidence; they are not constants.

Callers that currently fabricate values must either supply measured evidence or
receive `REJECTED`. Batch one will not invent replacement measurements.

### 2. Audit verdict integrity

The Tianji V2 comparative audit will build its scorecard from current computed
PnL and robustness values. A negative full-sample or IS PnL cannot receive a
positive profitability or generalization claim.

The optimized macro-trend audit verdict will require every declared hard gate,
including minimum sample size, positive OOS result, plateau stability, positive
three-times-friction result, and a computed ledger reconciliation result. A gate
will never be assigned `True` without an actual comparison.

Reports retain their current JSON format where possible, adding explicit gate
records and reasons. Existing stale report files are not hand-edited; rerunning
the corrected generators produces authoritative replacements.

### 3. AutoQuant temporal isolation

The evolutionary loop evaluates genomes against `train_data` only. After the
last generation, the frozen best genome is evaluated exactly once against
`oos_data`.

Champion source export requires all of the following:

- positive aggregate OOS PnL;
- a finite OOS result;
- at least one completed OOS trade;
- non-negative three-times-friction OOS PnL;
- causal feature-prefix invariance.

Failure writes a rejected health report but does not overwrite the production
strategy file. Rolling features retain `NaN` during warm-up; signal masks treat
non-finite inputs as unavailable. No `bfill()` is used.

### 4. Remote strategy registration

`POST /api/register_strategy` remains as a compatibility endpoint but always
returns HTTP 403 with error code `REMOTE_STRATEGY_REGISTRATION_DISABLED`.
It performs no validation, file write, import, or execution.

Trusted local strategy files may still be discovered at process startup. This
batch does not claim that local plugin files form a security sandbox.

### 5. Credential and SSH handling

TqSdk and deployment scripts must obtain credentials from environment or the
existing ignored `.env` file. Missing values raise a clear configuration error
before any network or database mutation.

All non-empty account and password literals are removed. Deployment scripts
call `load_system_host_keys()` and use `RejectPolicy`; unknown host keys abort.
Credentials already committed must be rotated outside this repository. Code can
remove exposure but cannot revoke an external account secret.

### 6. Heartbeat-only daemon quarantine

`deploy_tianji_v2_tier1_trader.py` and `server_tianji_v2_daemon.py` will not
claim to listen to market data. Their entrypoints return a non-zero status with
`NOT_IMPLEMENTED_LIVE_EXECUTION` unless and until a real market and order adapter
exists.

Deployment helpers must refuse to start this disabled daemon. Dashboard status
must report it as unavailable rather than inferring readiness from a PID or
state-file heartbeat.

## Data Flow

```text
measured metrics + explicit attack evidence
                    |
                    v
             fail-closed evaluator
                    |
          +---------+----------+
          |                    |
       APPROVED             REJECTED
   all evidence true     missing/false/non-finite

train partition -> genome evolution -> frozen champion -> one OOS evaluation
                                                       |
                                             pass gates? export : reject
```

## Error Handling

- Configuration errors identify the missing variable without printing secret
  values.
- Audit generators emit a complete rejected result instead of raising after
  partial report creation.
- Disabled remote registration and disabled live daemons return stable machine-
  readable error codes.
- No repair path mutates `ashare_quant.db`.

## Testing

Every production change begins with a failing regression test.

Required tests:

1. Evaluator rejects missing attack evidence, missing PnL, non-finite metrics,
   negative PnL, and false friction evidence.
2. Evaluator approves only a complete positive evidence bundle.
3. Tianji V2 negative IS/full PnL cannot produce a positive scorecard verdict.
4. Optimized macro-trend verdict fails when any declared gate fails, including
   three-times-friction or ledger reconciliation.
5. AutoQuant evolution never calls fitness with OOS data, evaluates OOS once,
   and does not export a failing champion.
6. AutoQuant feature prefixes are invariant when future rows are appended.
7. Remote strategy registration returns 403 and creates no file.
8. Credential loaders fail without configured credentials and contain no secret
   literal fallback.
9. Deployment clients reject unknown SSH host keys.
10. Heartbeat-only daemon and dashboard report `NOT_IMPLEMENTED_LIVE_EXECUTION`.

Verification runs focused tests first, then the complete project-owned
`tests/` suite. Vendored Qlib tests remain outside batch-one scope.

## Acceptance Criteria

- No approval-capable path has favorable defaults for missing evidence.
- No current negative audit can produce `APPROVED`, `BACKTEST_VALIDATED`, AAA,
  or champion export.
- No HTTP request can write or import Python strategy source.
- No non-empty credential fallback remains in project Python source.
- No deployment path starts or advertises the heartbeat-only daemon.
- All new regression tests pass and no previously passing project-owned test
  regresses.

