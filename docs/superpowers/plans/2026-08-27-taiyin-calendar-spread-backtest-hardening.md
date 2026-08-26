# Taiyin Calendar Spread Backtest Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Taiyin dual-contract 15-minute backtest causal, net-of-cost, mark-to-market, auditable, and explicit about its bar-data limits.

**Architecture:** Keep the existing signal rules and replace only the execution/accounting path in `Taiyin100PctRealSpreadEngine`. Signals are calculated from completed close bars, orders fill at the next open, every fill has explicit costs, and validation is computed from observed full-sample, holdout, parameter-grid, and cost-stress results.

**Tech Stack:** Python 3.10, pandas, NumPy, sqlite3, pytest; no new dependencies.

## Global Constraints

- Do not connect to paper or live trading.
- Do not use Tick, quote, or order-book claims; this remains a 15m bar-level model.
- Do not modify unrelated dirty files.
- Use net P&L for all trade metrics and mark-to-market equity for drawdown.
- Use completed-bar volume only; never use the fill bar's completed volume to decide its opening fill.
- A passing historical gate is named `BACKTEST_VALIDATED`, never approved for live execution.

---

### Task 1: Lock causal execution and accounting with failing tests

**Files:**
- Create: `tests/test_taiyin_calendar_spread.py`
- Modify: `code/taiyin_calendar_spread_100pct_real.py`

**Interfaces:**
- Consumes: `Taiyin100PctRealSpreadEngine.run_pair_real_backtest(df_near, df_far, profile, pair_info, initial_capital=..., fee_rate=..., slippage_ticks=..., min_leg_volume=...)`
- Produces: result keys `trades`, `equity_curve`, `ledger_reconciled`, `unclosed_position`, `max_drawdown_pct`, `win_rate_pct`, `profit_loss_ratio`, `net_profit_rmb`, `sharpe_ratio`, `sortino_ratio`, `calmar_ratio`.

- [ ] **Step 1: Write deterministic failing tests**

Create helpers that build aligned 15m frames and a cheap profile, then assert:

```python
import numpy as np
import pandas as pd

from taiyin_calendar_spread_15m import CommodityCarryCostProfile
from taiyin_calendar_spread_100pct_real import Taiyin100PctRealSpreadEngine


def make_leg(closes, opens=None, volumes=None):
    n = len(closes)
    opens = closes if opens is None else opens
    volumes = [100.0] * n if volumes is None else volumes
    return pd.DataFrame({
        "trade_time": pd.date_range("2026-01-01 09:00", periods=n, freq="15min").astype(str),
        "open": opens,
        "high": np.maximum(opens, closes),
        "low": np.minimum(opens, closes),
        "close": closes,
        "volume": volumes,
    })


def run_fixture(*, near_closes, near_opens=None, near_volume=None,
                fee_rate=0.0, slippage_ticks=0.0):
    far = [50.0] * len(near_closes)
    engine = Taiyin100PctRealSpreadEngine(z_entry=0.5, z_exit=0.2,
                                         z_stop=3.5, lookback_window=2)
    profile = CommodityCarryCostProfile(
        "TEST", "test", multiplier=1.0, tick_size=1.0,
        annual_interest_rate=0.0, storage_fee_per_day=0.0,
        delivery_fee_fixed=0.0, vat_capital_drag=0.0, default_lots=1,
    )
    pair = {"symbol": "TEST", "near": "TEST.n", "far": "TEST.f",
            "name": "test", "days_between_contracts": 30}
    return engine.run_pair_real_backtest(
        make_leg(near_closes, near_opens, near_volume), make_leg(far),
        profile, pair, fee_rate=fee_rate, slippage_ticks=slippage_ticks,
    )


def test_signal_fills_on_next_open(monkeypatch):
    result = run_fixture(
        near_closes=[100, 100, 80, 100, 100],
        near_opens=[100, 100, 80, 77, 103],
    )
    trade = result["trades"].iloc[0]
    assert trade["entry_time"] == "2026-01-01 09:45:00"
    assert trade["entry_spread"] == 27


def test_metrics_use_net_pnl_and_mtm_equity():
    result = run_fixture(
        near_closes=[100, 100, 80, 80, 80],
        near_opens=[100, 100, 80, 80, 80],
        fee_rate=0.1,
        slippage_ticks=1,
    )
    assert result["trades"].iloc[0]["net_pnl"] < result["trades"].iloc[0]["gross_pnl"]
    assert result["win_rate_pct"] == 0.0
    assert result["max_drawdown_pct"] > 0.0
    assert result["ledger_reconciled"] is True


def test_completed_bar_volume_controls_next_open_fill():
    result = run_fixture(
        near_closes=[100, 100, 80, 100, 100],
        near_volume=[100, 100, 0, 0, 0],
    )
    assert result["total_trades"] == 0


def test_end_of_data_reports_unclosed_when_last_bar_is_illiquid():
    result = run_fixture(
        near_closes=[100, 100, 80, 80],
        near_volume=[100, 100, 100, 0],
    )
    assert result["unclosed_position"] is True
    assert result["ledger_reconciled"] is False
```

- [ ] **Step 2: Run tests and confirm the old engine fails**

Run: `pytest -q tests/test_taiyin_calendar_spread.py`

Expected: failures for missing next-open execution, `net_pnl`, mark-to-market equity, and open-position audit fields.

- [ ] **Step 3: Implement the minimal causal state machine**

Replace same-close fills with one pending action executed at the next bar open:

```python
pending: Optional[Dict[str, Any]] = None
for i in range(self.window, n):
    if pending and pending["fill_index"] == i:
        execute_at_open(i, pending)
        pending = None

    equity_curve.append(cash + (pos * (raw_spreads[i] - entry_spread) * mult * lots if pos else 0.0))

    liquid = near_vols[i] >= min_leg_volume and far_vols[i] >= min_leg_volume
    if i + 1 < n and liquid:
        pending = signal_from_completed_close(i, fill_index=i + 1)
```

Each closed trade must store:

```python
{
    "gross_pnl": gross_pnl,
    "entry_fee": entry_fee,
    "exit_fee": exit_fee,
    "entry_slippage": entry_slippage,
    "exit_slippage": exit_slippage,
    "net_pnl": gross_pnl - entry_fee - exit_fee - entry_slippage - exit_slippage,
}
```

At end of data, close at the last close only when the completed final bar is liquid; otherwise retain mark-to-market equity and set `unclosed_position=True`. Reconcile realized cash to closed trade net P&L within `0.01`.

- [ ] **Step 4: Run target tests**

Run: `pytest -q tests/test_taiyin_calendar_spread.py`

Expected: all tests pass.

- [ ] **Step 5: Commit causal execution and accounting**

Run: `git add code/taiyin_calendar_spread_100pct_real.py tests/test_taiyin_calendar_spread.py && git commit -m "fix: make taiyin spread backtest causal"`

---

### Task 2: Replace fake scoring with observed validation gates

**Files:**
- Modify: `code/taiyin_calendar_spread_100pct_real.py`
- Modify: `tests/test_taiyin_calendar_spread.py`

**Interfaces:**
- Produces: `classify_validation(holdout_trades: int, holdout_net_profit: float, profitable_parameter_sets: int, triple_cost_net_profit: float, ledger_reconciled: bool, unclosed_position: bool) -> str`.
- Produces: `validate_pair(df_near, df_far, profile, pair_info) -> Dict[str, Any]` with `holdout_trades`, `holdout_net_profit`, `profitable_parameter_sets`, `triple_cost_net_profit`, and `status`.

- [ ] **Step 1: Add failing validation tests**

```python
def test_validation_requires_enough_holdout_trades():
    assert classify_validation(8, 1, 16, 1, True, False) == "INSUFFICIENT_EVIDENCE"


def test_validation_rejects_negative_holdout():
    assert classify_validation(40, -1, 16, 1, True, False) == "REJECTED"


def test_validation_passes_only_all_observed_gates():
    assert classify_validation(40, 1, 12, 1, True, False) == "BACKTEST_VALIDATED"
```

- [ ] **Step 2: Run the new tests and verify failure**

Run: `pytest -q tests/test_taiyin_calendar_spread.py -k validation`

Expected: failure because `validate_pair` does not exist.

- [ ] **Step 3: Implement validation and honest reporting**

Use a chronological 70/30 split, the fixed 16-combination grid, and 1x/2x/3x costs. Compute status with exact gates:

```python
if not ledger_reconciled or unclosed_position or triple_cost_net_profit <= 0 or holdout_net_profit <= 0:
    status = "REJECTED"
elif holdout_trades < 30 or profitable_parameter_sets < 12:
    status = "INSUFFICIENT_EVIDENCE"
else:
    status = "BACKTEST_VALIDATED"
```

Remove hard-coded IC, Sharpe, Sortino, Calmar, and attack booleans. Print every pair, profitable-pair ratio, cost assumptions, holdout result, grid count, triple-cost P&L, ledger flags, and status.

- [ ] **Step 4: Run target tests**

Run: `pytest -q tests/test_taiyin_calendar_spread.py`

Expected: all tests pass.

- [ ] **Step 5: Commit observed validation**

Run: `git add code/taiyin_calendar_spread_100pct_real.py tests/test_taiyin_calendar_spread.py && git commit -m "feat: validate taiyin backtests with observed gates"`

---

### Task 3: Correct contract intervals and credential handling

**Files:**
- Modify: `code/sync_calendar_spread_pairs.py`
- Modify: `code/taiyin_calendar_spread_100pct_real.py`
- Modify: `tests/test_taiyin_calendar_spread.py`

**Interfaces:**
- `pair_info["days_between_contracts"] -> int`
- `load_tq_credentials() -> Tuple[str, str]`, raising `RuntimeError` when either credential is missing.

- [ ] **Step 1: Add failing metadata and credential tests**

```python
def test_every_pair_has_real_contract_interval():
    assert {p["days_between_contracts"] for p in CALENDAR_SPREAD_PAIRS} <= {30, 92, 122, 183}


def test_missing_tq_credentials_fail_closed(monkeypatch, tmp_path):
    monkeypatch.delenv("TQ_ACCOUNT", raising=False)
    monkeypatch.delenv("TQ_PASSWORD", raising=False)
    monkeypatch.setattr(sync_module, "ENV_PATH", str(tmp_path / "missing.env"))
    with pytest.raises(RuntimeError, match="TQ_ACCOUNT"):
        sync_module.load_tq_credentials()
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pytest -q tests/test_taiyin_calendar_spread.py -k 'interval or credentials'`

Expected: missing metadata assertion and credential fallback failure.

- [ ] **Step 3: Add explicit intervals and fail-closed credentials**

Add `days_between_contracts` to each pair: 183 for 06–12, 122 for 09–01, 92 for 10–01, and 30 for adjacent months. Read credentials from environment first, then `.env`, and finish with:

```python
if not user or not password:
    raise RuntimeError("TQ_ACCOUNT and TQ_PASSWORD are required")
return user, password
```

Mask the account in logs with `user[:3] + "***" + user[-2:]`.

- [ ] **Step 4: Run target tests**

Run: `pytest -q tests/test_taiyin_calendar_spread.py`

Expected: all tests pass.

- [ ] **Step 5: Commit interval and credential fixes**

Run: `git add code/sync_calendar_spread_pairs.py code/taiyin_calendar_spread_100pct_real.py tests/test_taiyin_calendar_spread.py && git commit -m "fix: secure taiyin data inputs"`

---

### Task 4: Prevent synthetic/real confusion and verify end to end

**Files:**
- Modify: `code/taiyin_calendar_spread_15m.py`
- Test: `tests/test_taiyin_calendar_spread.py`

**Interfaces:**
- The synthetic entrypoint prints `SYNTHETIC RESEARCH ONLY` before any result.

- [ ] **Step 1: Add a source-level warning test**

```python
def test_synthetic_runner_is_explicitly_labeled():
    source = Path("code/taiyin_calendar_spread_15m.py").read_text(encoding="utf-8")
    assert "SYNTHETIC RESEARCH ONLY" in source
```

- [ ] **Step 2: Run the warning test and verify failure**

Run: `pytest -q tests/test_taiyin_calendar_spread.py -k synthetic`

Expected: failure because the warning is absent.

- [ ] **Step 3: Add the warning without changing synthetic calculations**

Add the warning to the module docstring and print it at the start of `run_full_calendar_spread_research()`.

- [ ] **Step 4: Run focused and related tests**

Run: `pytest -q tests/test_taiyin_calendar_spread.py tests/test_strategy_evaluator_agent.py tests/test_backtest_metrics.py`

Expected: all tests pass.

- [ ] **Step 5: Execute the real database backtest**

Run: `python3 code/taiyin_calendar_spread_100pct_real.py`

Expected: all 19 pairs printed with observed full/holdout/grid/cost metrics; no fake 100-point score; each pair classified as `BACKTEST_VALIDATED`, `INSUFFICIENT_EVIDENCE`, or `REJECTED`; process exits 0.

- [ ] **Step 6: Final integrity checks**

Run: `python3 -m py_compile code/taiyin_calendar_spread_15m.py code/taiyin_calendar_spread_100pct_real.py code/sync_calendar_spread_pairs.py`

Run: `git diff --check`

Expected: both commands exit 0.

- [ ] **Step 7: Commit the synthetic warning**

Run: `git add code/taiyin_calendar_spread_15m.py tests/test_taiyin_calendar_spread.py && git commit -m "docs: label synthetic taiyin research"`
