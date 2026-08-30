# P0 Trust and Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make strategy approval, champion export, deployment, and remote code registration fail closed when evidence or real execution capability is absent.

**Architecture:** Preserve the existing research engines but put explicit gates at their trust boundaries. Reuse the current evaluator, audit scripts, Flask app, and credential loaders; delete favorable defaults and heartbeat theater instead of building new frameworks.

**Tech Stack:** Python 3.10, pytest, Flask, pandas, NumPy, SQLite, Paramiko, standard library.

## Global Constraints

- Do not mutate `data/ashare_quant.db` or generated historical bars.
- Do not add dependencies.
- Preserve unrelated dirty-worktree changes; use `apply_patch` for every edit.
- Missing, false, or non-finite trust evidence must reject.
- OOS data may be evaluated once after selection and must never drive selection.
- No implementation commit: target files contain pre-existing overlapping user changes and untracked work. Keep a reviewed working-tree diff instead of staging unrelated content.
- Batch-two issues remain deferred exactly as listed in the approved design.

---

### Task 1: Make the strategy evaluator fail closed

**Files:**
- Modify: `code/strategy_evaluator_agent.py:49-216`
- Modify: `tests/test_strategy_evaluator_agent.py`

**Interfaces:**
- Consumes: `metrics: dict`, `attack_results: dict`, `strategy_name: str`.
- Produces: unchanged `StrategyEvaluationDecision`; incomplete evidence produces score `0.0`, grade `C`, status `REJECTED`.

- [ ] **Step 1: Write failing tests for missing and non-finite evidence**

Add a complete reusable positive bundle and explicit rejection tests:

```python
COMPLETE_METRICS = {
    "trading_period": "2025-01-01 ~ 2025-12-31",
    "asset_type": "期货",
    "symbols_summary": "10 个标的",
    "total_net_pnl": 100_000.0,
    "profitable_symbols_ratio": 0.9,
    "mean_rank_ic": 0.045,
    "rank_icir": 2.2,
    "ic_positive_ratio": 0.62,
    "monotonicity": 0.95,
    "sharpe_ratio": 2.8,
    "sortino_ratio": 4.0,
    "calmar_ratio": 3.5,
    "profit_loss_ratio": 2.1,
    "max_drawdown": 0.06,
    "max_drawdown_duration_days": 20,
    "walk_forward_ratio": 0.88,
    "turnover_ratio": 12.0,
    "double_cost_profitable": True,
    "win_rate_pct": 60.0,
    "total_trades_count": 300,
}

COMPLETE_ATTACKS = {
    "label_shuffle_pass": True,
    "prefix_invariance_pass": True,
    "noise_features_pass": True,
    "calendar_features_pass": True,
    "ledger_reconciled": True,
    "tail_risk_pass": True,
    "leverage_safe": True,
    "execution_feasible": True,
}

def test_missing_trust_evidence_is_rejected():
    decision = StrategyEvaluatorAgent.evaluate_strategy({}, {})
    assert decision.status == "REJECTED"
    assert decision.total_score == 0.0
    assert any("缺少" in reason for reason in decision.hard_fail_reasons)

def test_non_finite_or_negative_pnl_is_rejected():
    for pnl in (float("nan"), float("inf"), -1.0):
        metrics = {**COMPLETE_METRICS, "total_net_pnl": pnl}
        decision = StrategyEvaluatorAgent.evaluate_strategy(metrics, COMPLETE_ATTACKS)
        assert decision.status == "REJECTED"
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
pytest -q tests/test_strategy_evaluator_agent.py
```

Expected: the new missing-evidence test fails because current defaults are favorable; existing approval tests may also expose incomplete bundles.

- [ ] **Step 3: Implement required evidence checks and measured scoring**

Define required keys inside `evaluate_strategy` and append hard failures before score calculation:

```python
required_metrics = {
    "total_net_pnl", "profitable_symbols_ratio", "max_drawdown",
    "turnover_ratio", "double_cost_profitable", "mean_rank_ic",
    "rank_icir", "ic_positive_ratio", "monotonicity", "sharpe_ratio",
    "sortino_ratio", "calmar_ratio", "profit_loss_ratio",
    "max_drawdown_duration_days", "walk_forward_ratio",
    "win_rate_pct", "total_trades_count",
}
required_attacks = {
    "label_shuffle_pass", "prefix_invariance_pass", "noise_features_pass",
    "calendar_features_pass", "ledger_reconciled", "tail_risk_pass",
    "leverage_safe", "execution_feasible",
}
missing_metrics = sorted(required_metrics - metrics.keys())
missing_attacks = sorted(required_attacks - attack_results.keys())
if missing_metrics:
    hard_fails.append(f"缺少必需指标: {', '.join(missing_metrics)}")
if missing_attacks:
    hard_fails.append(f"缺少必需审计证据: {', '.join(missing_attacks)}")
```

Use neutral display defaults only after recording hard failures. Reject non-finite numeric evidence. Replace constant points with explicit evidence:

```python
s_tail = 4.0 if attack_results.get("tail_risk_pass") is True else 0.0
s_leverage = 3.0 if attack_results.get("leverage_safe") is True else 0.0
s_prefix = 6.0 if attack_results.get("prefix_invariance_pass") is True else 0.0
s_exec = 2.0 if attack_results.get("execution_feasible") is True else 0.0
```

All attack lookups use `is True`; none uses a true default.

- [ ] **Step 4: Run evaluator tests and verify GREEN**

Run:

```bash
pytest -q tests/test_strategy_evaluator_agent.py
```

Expected: all evaluator tests pass; the positive test supplies the complete evidence bundle.

- [ ] **Step 5: Checkpoint the task without staging user work**

Run:

```bash
git diff --check -- code/strategy_evaluator_agent.py tests/test_strategy_evaluator_agent.py
```

Expected: no whitespace errors.

---

### Task 2: Derive audit verdicts from measured gates

**Files:**
- Modify: `code/run_tianji_v2_optimized_deep_audit.py:309-425`
- Modify: `code/run_optimized_macro_trend_island_audit.py:333-495`
- Create: `tests/test_p0_audit_integrity.py`

**Interfaces:**
- Produces: `build_tianji_scorecard(...) -> list[tuple]`.
- Produces: `evaluate_macro_audit_gates(...) -> tuple[list[dict], str]`.
- Existing JSON keys remain; reports add `gates` and measured descriptions.

- [ ] **Step 1: Write failing pure-function tests**

```python
from run_optimized_macro_trend_island_audit import evaluate_macro_audit_gates
from run_tianji_v2_optimized_deep_audit import build_tianji_scorecard

def test_negative_tianji_results_cannot_receive_positive_profitability_claims():
    card = build_tianji_scorecard(-2_000_000.0, -2_400_000.0, 600_000.0)
    assert sum(row[2] for row in card) < 85.0
    assert not any("全历史大赚" in row[3] or "双红" in row[3] for row in card)

def test_macro_verdict_requires_every_declared_gate():
    gates, verdict = evaluate_macro_audit_gates(
        min_trades=809,
        oos_pnl=358_295.0,
        plateau_ratio=84.4,
        stressed_pnl=-62_971_534.0,
        ledger_reconciled=True,
    )
    assert verdict == "REJECTED"
    assert next(g for g in gates if g["id"] == "three_x_friction")["passed"] is False
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest -q tests/test_p0_audit_integrity.py
```

Expected: import failures because the pure gate functions do not exist.

- [ ] **Step 3: Implement the minimal measured helpers**

`build_tianji_scorecard` awards profitability/generalization points only when
their numeric predicates pass and inserts actual formatted PnL in descriptions.
Keep unrelated dimensions at zero unless their measured inputs are supplied.

`evaluate_macro_audit_gates` creates five records:

```python
checks = (
    ("minimum_trades", min_trades >= 200, min_trades, ">= 200"),
    ("positive_oos", oos_pnl > 0.0, oos_pnl, "> 0"),
    ("plateau_stability", plateau_ratio >= 50.0, plateau_ratio, ">= 50%"),
    ("three_x_friction", stressed_pnl > 0.0, stressed_pnl, "> 0"),
    ("ledger_reconciled", ledger_reconciled is True, ledger_reconciled, True),
)
gates = [
    {"id": gate_id, "passed": bool(passed), "observed": observed, "required": required}
    for gate_id, passed, observed, required in checks
]
return gates, "BACKTEST_VALIDATED" if all(g["passed"] for g in gates) else "REJECTED"
```

Compute ledger reconciliation from every simulator result as
`abs(result["pnl"] - sum(result["trades_list"])) <= 0.01`; never assign a constant.

- [ ] **Step 4: Replace hard-coded scorecard and verdict calls**

Use the helpers in both report generators, store the resulting `gates`, and
remove positive fixed prose. Current negative artifacts must be rejected when
the generators are rerun.

- [ ] **Step 5: Verify GREEN and preserve report serialization**

Run:

```bash
pytest -q tests/test_p0_audit_integrity.py
python3 -m py_compile code/run_tianji_v2_optimized_deep_audit.py code/run_optimized_macro_trend_island_audit.py
git diff --check -- code/run_tianji_v2_optimized_deep_audit.py code/run_optimized_macro_trend_island_audit.py tests/test_p0_audit_integrity.py
```

Expected: tests pass, modules compile, no report generator is executed.

---

### Task 3: Isolate AutoQuant training from OOS and remove backward fill

**Files:**
- Modify: `code/autoquant_dual_agent_evolution_engine.py:112-194,347-450,595-end`
- Modify: `strategies/autoquant_champion_strategy.py:40-103`
- Create: `tests/test_autoquant_temporal_isolation.py`

**Interfaces:**
- `compute_fast_fitness(dataset, gene)` keeps its signature but receives training data during evolution.
- `generate_champion_health_report(gene, oos_data) -> dict` returns its report after writing it.
- `champion_passes_oos(report) -> bool` gates source export.

- [ ] **Step 1: Write failing temporal-isolation and prefix tests**

Use monkeypatches and one generation to prove the dataset identity:

```python
def test_evolution_selects_on_train_and_blocks_negative_oos_export(monkeypatch):
    train = {"TRAIN": object()}
    oos = {"OOS": object()}
    seen = []
    monkeypatch.setattr(engine, "load_precomputed_market_data", lambda: (train, oos))
    monkeypatch.setattr(engine, "compute_fast_fitness", lambda data, gene: (seen.append(data) or (1.0, 1.0, 1.0)))
    monkeypatch.setattr(engine, "generate_champion_health_report", lambda gene, data: {"oos_total_pnl": -1.0, "oos_total_trades": 1, "oos_3x_pnl": -2.0})
    exported = []
    monkeypatch.setattr(engine, "export_production_champion_strategy", lambda gene: exported.append(gene))
    engine.run_autoquant_50_generations(pop_size=2, generations=1)
    assert seen and all(data is train for data in seen)
    assert exported == []

def test_champion_features_are_prefix_invariant():
    short = market_frame(80)
    long = market_frame(100)
    pd.testing.assert_frame_equal(
        champion.calculate_factors(short),
        champion.calculate_factors(long).loc[short.index],
    )
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest -q tests/test_autoquant_temporal_isolation.py
```

Expected: evolution records `oos`, exports the negative champion, or prefix comparison fails because of `bfill()`.

- [ ] **Step 3: Change selection to train-only and add the export gate**

Call `compute_fast_fitness(train_data, individual)` in the evolutionary loop.
After freezing `best_genome`, generate one OOS report, then:

```python
if champion_passes_oos(report):
    export_production_champion_strategy(best_genome)
else:
    print("[AutoQuant] OOS gates failed; champion export blocked")
```

The gate requires finite positive `oos_total_pnl`, positive trade count, and
non-negative `oos_3x_pnl`.

- [ ] **Step 4: Remove every AutoQuant `bfill()`**

Leave rolling warm-up values as `NaN` and add a finite mask to signals:

```python
finite = np.isfinite(atr) & np.isfinite(hurst) & np.isfinite(roll_high) & np.isfinite(roll_low)
signals[~finite] = 0
```

Apply the same source template change so future exports remain causal.

- [ ] **Step 5: Verify GREEN**

Run:

```bash
pytest -q tests/test_autoquant_temporal_isolation.py
rg -n '\.bfill\(' code/autoquant_dual_agent_evolution_engine.py strategies/autoquant_champion_strategy.py
```

Expected: tests pass and `rg` returns no matches.

---

### Task 4: Disable remote Python strategy registration

**Files:**
- Modify: `code/web_server.py:105-124`
- Modify: `tests/test_web_validation.py`

**Interfaces:**
- `POST /api/register_strategy` always returns HTTP 403 and JSON error code `REMOTE_STRATEGY_REGISTRATION_DISABLED`.
- Local plugin discovery remains unchanged.

- [ ] **Step 1: Write a failing endpoint test**

```python
def test_remote_strategy_registration_is_disabled(monkeypatch):
    from web_server import app, hot_plugger
    called = []
    monkeypatch.setattr(hot_plugger, "save_custom_strategy_code", lambda *args: called.append(args))
    response = app.test_client().post("/api/register_strategy", json={
        "strategy_name": "remote_code",
        "code_content": "def calculate_signal(df): return 0",
    })
    assert response.status_code == 403
    assert response.get_json()["error_code"] == "REMOTE_STRATEGY_REGISTRATION_DISABLED"
    assert called == []
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest -q tests/test_web_validation.py::test_remote_strategy_registration_is_disabled
```

Expected: current endpoint calls the save/import path or returns 200/500.

- [ ] **Step 3: Replace the route body with a fixed denial**

```python
return jsonify({
    "error": "远程策略代码注册已禁用",
    "error_code": "REMOTE_STRATEGY_REGISTRATION_DISABLED",
}), 403
```

Do not parse request source or call the hot plugger.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
pytest -q tests/test_web_validation.py::test_remote_strategy_registration_is_disabled
```

Expected: one pass.

---

### Task 5: Remove credential fallbacks and unsafe SSH policies

**Files:**
- Create: `code/runtime_credentials.py`
- Modify: `code/deploy_ek_supertrend_v7_trader.py:96-108`
- Modify: `code/deploy_taichong_squads_trader.py:73-85`
- Modify: `code/sync_live_futures_klines.py:59-71`
- Modify: `code/fetch_tqsdk_multi_timeframe_history.py:68-88`
- Modify: `code/deploy_to_server.py:70-84`
- Modify: `code/fix_and_restore_production.py:25-35`
- Modify: `code/deploy_and_restart_web_dashboard.py:20-32`
- Modify: `code/auto_deploy_to_opt_lianghua.py`
- Modify: `code/push_tianji_v2_to_server.py`
- Create: `tests/test_p0_credentials_and_ssh.py`

**Interfaces:**
- `load_required_credentials(env_path, account_key="TQ_ACCOUNT", password_key="TQ_PASSWORD") -> tuple[str, str]`.
- Missing values raise `RuntimeError("missing required credentials: ...")` without values.

- [ ] **Step 1: Write failing credential and source-policy tests**

```python
def test_required_credentials_have_no_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("TQ_ACCOUNT", raising=False)
    monkeypatch.delenv("TQ_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="TQ_ACCOUNT, TQ_PASSWORD"):
        load_required_credentials(tmp_path / ".env")

def test_deployment_sources_require_known_hosts_and_contain_no_password_literal():
    paths = DEPLOYMENT_PATHS
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "AutoAddPolicy" not in source
        assert "WarningPolicy" not in source
        assert "load_system_host_keys()" in source or "NOT_IMPLEMENTED_LIVE_EXECUTION" in source
```

Add an AST-based test that fails on non-empty string literals assigned to names
containing `password`, `secret`, `api_key`, or `token`; never print literal values.

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest -q tests/test_p0_credentials_and_ssh.py
```

Expected: missing helper import, committed password literals, and unsafe policies fail.

- [ ] **Step 3: Implement the standard-library credential loader**

Read environment first, then simple `KEY=value` lines from the ignored file.
Strip optional quotes. Raise with missing key names only.

```python
def load_required_credentials(env_path, account_key="TQ_ACCOUNT", password_key="TQ_PASSWORD"):
    values = {account_key: os.environ.get(account_key, ""), password_key: os.environ.get(password_key, "")}
    if Path(env_path).is_file():
        for raw in Path(env_path).read_text(encoding="utf-8").splitlines():
            key, separator, value = raw.partition("=")
            if separator and key.strip() in values and not values[key.strip()]:
                values[key.strip()] = value.strip().strip('"\'')
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise RuntimeError(f"missing required credentials: {', '.join(missing)}")
    return values[account_key], values[password_key]
```

Make the four TqSdk wrappers call this helper.

- [ ] **Step 4: Enforce host-key verification**

For active Paramiko clients:

```python
ssh.load_system_host_keys()
ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
```

Remove password defaults. The two Tianji V2 deployment helpers are disabled in
Task 6, so they contain no SSH connection code.

- [ ] **Step 5: Verify GREEN and rescan without exposing secrets**

Run:

```bash
pytest -q tests/test_p0_credentials_and_ssh.py
rg -n 'AutoAddPolicy|WarningPolicy' code -g '*.py'
```

Expected: tests pass and policy search returns no matches.

---

### Task 6: Quarantine heartbeat-only Tianji deployment and dashboard status

**Files:**
- Modify: `code/deploy_tianji_v2_tier1_trader.py`
- Modify: `code/server_tianji_v2_daemon.py`
- Modify: `code/auto_deploy_to_opt_lianghua.py`
- Modify: `code/push_tianji_v2_to_server.py`
- Modify: `code/futures_dashboard_server.py:53-70,692-857,877-896`
- Modify: `tests/test_futures_trading_isolation.py`

**Interfaces:**
- Both daemon `main()` functions return `2` and emit `NOT_IMPLEMENTED_LIVE_EXECUTION`.
- Both dedicated deployment helpers return `2` without networking.
- Dashboard strategy metadata and status expose `execution_status: NOT_IMPLEMENTED_LIVE_EXECUTION`, `running: false`.

- [ ] **Step 1: Write failing daemon and dashboard tests**

```python
def test_tianji_heartbeat_daemons_fail_closed(capsys):
    import deploy_tianji_v2_tier1_trader as local
    import server_tianji_v2_daemon as server
    assert local.main() == 2
    assert server.main() == 2
    assert "NOT_IMPLEMENTED_LIVE_EXECUTION" in capsys.readouterr().out

def test_dashboard_never_reports_tianji_v2_as_running():
    from futures_dashboard_server import app
    payload = app.test_client().get("/api/status?strategy=tianji_dual_island_v2").get_json()
    assert payload["running"] is False
    assert payload["execution_status"] == "NOT_IMPLEMENTED_LIVE_EXECUTION"
```

- [ ] **Step 2: Verify RED**

Run:

```bash
pytest -q tests/test_futures_trading_isolation.py -k 'tianji or dashboard'
```

Expected: daemon loops/writes a fake running state or dashboard infers readiness.

- [ ] **Step 3: Replace heartbeat daemons and dedicated deployers with explicit disabled entrypoints**

Use the minimum executable script:

```python
ERROR_CODE = "NOT_IMPLEMENTED_LIVE_EXECUTION"

def main():
    print(ERROR_CODE)
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
```

Do not retain Paramiko, state-file writes, infinite sleeps, or production claims
in these four dedicated files.

- [ ] **Step 4: Add a dashboard early return for the disabled strategy**

Mark the registry record and return before process/state inspection:

```python
if strat_cfg.get("execution_status") == "NOT_IMPLEMENTED_LIVE_EXECUTION":
    return {
        "strategy_id": strat_key,
        "strategy_name": strat_cfg["name"],
        "running": False,
        "execution_status": "NOT_IMPLEMENTED_LIVE_EXECUTION",
        "active_positions": 0,
        "symbols": [],
    }
```

Expose the same field from `/api/strategies`.

- [ ] **Step 5: Verify GREEN**

Run:

```bash
pytest -q tests/test_futures_trading_isolation.py -k 'tianji or dashboard'
python3 code/deploy_tianji_v2_tier1_trader.py; test $? -eq 2
```

Expected: focused tests pass; CLI prints the stable code and exits 2.

---

### Task 7: Run batch-one regression and trust-boundary verification

**Files:**
- Verify all files touched by Tasks 1-6.

**Interfaces:**
- No new behavior; this task proves the batch meets the approved design.

- [ ] **Step 1: Run all focused P0 tests**

```bash
pytest -q \
  tests/test_strategy_evaluator_agent.py \
  tests/test_p0_audit_integrity.py \
  tests/test_autoquant_temporal_isolation.py \
  tests/test_p0_credentials_and_ssh.py \
  tests/test_web_validation.py \
  tests/test_futures_trading_isolation.py
```

Expected: all focused tests pass. The pre-existing `/api/logs` expectation must
be updated only if the approved API contract explicitly requires that endpoint;
do not hide unrelated failures.

- [ ] **Step 2: Run core backtest regressions**

```bash
pytest -q \
  tests/test_backtest_integration.py \
  tests/test_portfolio_simulator.py \
  tests/test_data_contract.py \
  tests/test_causal_ml.py \
  tests/test_futures_research_backtest.py
```

Expected: no new failures. If the known `max_drawdown_intrabar` mapping-size
test remains stale, update its expected mapping to include the already existing
field and rerun.

- [ ] **Step 3: Run the complete project-owned test suite**

```bash
pytest -q tests --disable-warnings
```

Expected: zero failures. Vendored `qlib/` collection is intentionally excluded.

- [ ] **Step 4: Run static trust scans**

```bash
rg -n '\.bfill\(' code/autoquant_dual_agent_evolution_engine.py strategies/autoquant_champion_strategy.py
rg -n 'AutoAddPolicy|WarningPolicy' code -g '*.py'
git diff --check
```

Expected: both `rg` commands return no matches and diff check is clean.

- [ ] **Step 5: Review the final diff against the design**

Confirm:

- no database or generated report artifact changed;
- no unrelated dirty file was overwritten;
- negative audit inputs cannot approve;
- OOS does not select AutoQuant genomes;
- remote Python registration is disabled;
- committed secret fallbacks are gone;
- heartbeat-only Tianji processes cannot deploy or appear live.

Do not stage or commit mixed user changes. Report exact test counts and any
remaining batch-two debt.

