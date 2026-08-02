# HMM Market Regime Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in, causal three-state CSI 300 HMM entry filter to single-symbol and shared-account portfolio backtests.

**Architecture:** A focused `market_regime.py` module owns observations, fixed-window HMM fitting, causal forward filtering, stable state names, and the BUY overlay. `KLineBacktestEngine` loads one shared regime frame per run and applies it before creating decisions; the simulator remains unchanged.

**Tech Stack:** Python 3, pandas, NumPy, existing `hmmlearn==0.3.2` from `env10`, pytest, SQLite.

## Global Constraints

- Keep `regime_filter=False` as the default and preserve existing responses when disabled.
- Use CSI 300 (`000300`), 3 states, 504 observations, 21-day refits, diagonal covariance, and random seed 42.
- Use forward-filtered probabilities only; never Viterbi or smoothed full-sequence posteriors.
- SELL always passes; bear or unavailable regimes only block new BUY decisions.
- Do not modify the Web UI, execution simulator, legacy snapshot engines, or evolution training logic.
- Reject `regime_filter=True` with `run_evolution=True`.
- Preserve all unrelated dirty-worktree changes and stage only task files.

---

### Task 1: Causal market regime module

**Files:**
- Create: `code/market_regime.py`
- Create: `tests/test_market_regime.py`

**Interfaces:**
- Produces: `build_regime_observations(frame: pd.DataFrame) -> pd.DataFrame`
- Produces: `state_names_from_means(means: np.ndarray) -> dict[int, str]`
- Produces: `walk_forward_regimes(frame: pd.DataFrame, model_factory=None, training_window=504, retrain_every=21) -> pd.DataFrame`
- Produces: `apply_regime_overlay(action: str, reason: str, target_fraction: float, regime_row) -> tuple[str, str, float, dict]`

- [ ] **Step 1: Write the failing unit tests**

Create `tests/test_market_regime.py` with deterministic bars and a fake fitted model. Cover prefix invariance, strict training cutoffs, stable naming, BUY sizing, unavailable BUY blocking, and unconditional SELL pass-through.

```python
import numpy as np
import pandas as pd

from market_regime import (
    apply_regime_overlay,
    build_regime_observations,
    state_names_from_means,
    walk_forward_regimes,
)


class FakeHMM:
    def fit(self, values):
        self.startprob_ = np.array([0.8, 0.1, 0.1])
        self.transmat_ = np.array([
            [0.90, 0.05, 0.05],
            [0.05, 0.90, 0.05],
            [0.05, 0.05, 0.90],
        ])
        self.means_ = np.array([
            [0.0, 0.0, 1.0],
            [0.0, 0.0, -1.0],
            [0.0, 0.0, 0.0],
        ])
        self.covars_ = np.ones((3, 3))
        return self


def index_bars(rows=90):
    dates = pd.bdate_range("2025-01-01", periods=rows)
    close = 100 * np.exp(np.sin(np.arange(rows) / 7) * 0.01
                         + np.arange(rows) * 0.0003)
    return pd.DataFrame({
        "trade_date": dates,
        "close": close,
    })


def test_observations_are_prefix_invariant():
    short = build_regime_observations(index_bars(70))
    long = build_regime_observations(index_bars(90))
    pd.testing.assert_frame_equal(short, long.loc[short.index])


def test_walk_forward_probabilities_are_prefix_invariant_and_causal():
    short = walk_forward_regimes(
        index_bars(70), FakeHMM, training_window=30, retrain_every=5
    )
    long = walk_forward_regimes(
        index_bars(90), FakeHMM, training_window=30, retrain_every=5
    )
    pd.testing.assert_frame_equal(short, long.loc[short.index])
    available = short[short["status"] == "AVAILABLE"]
    assert not available.empty
    assert (pd.to_datetime(available["trained_until"]) < available.index).all()


def test_state_names_follow_trend_strength_mean():
    names = state_names_from_means(np.array([
        [0.0, 0.0, 0.1],
        [0.0, 0.0, -1.2],
        [0.0, 0.0, 0.8],
    ]))
    assert names == {0: "RANGE", 1: "HIGH_VOL_BEAR", 2: "LOW_VOL_BULL"}


def regime(state="RANGE", status="AVAILABLE"):
    return pd.Series({
        "state": state,
        "status": status,
        "p_low_vol_bull": 0.2,
        "p_range": 0.7,
        "p_high_vol_bear": 0.1,
        "model_version": "test-hmm",
        "trained_until": pd.Timestamp("2025-01-01"),
    })


def test_overlay_scales_range_and_blocks_bear_or_unavailable_buys():
    action, reason, fraction, features = apply_regime_overlay(
        "BUY", "ENTRY", 0.2, regime()
    )
    assert (action, reason, fraction) == ("BUY", "ENTRY|REGIME_RANGE_HALF", 0.1)
    assert features["market_regime"] == "RANGE"
    assert apply_regime_overlay(
        "BUY", "ENTRY", 0.2, regime("HIGH_VOL_BEAR")
    )[:3] == ("HOLD", "REGIME_HIGH_VOL_BEAR", 0.0)
    assert apply_regime_overlay(
        "BUY", "ENTRY", 0.2, regime(status="INSUFFICIENT_HISTORY")
    )[:3] == ("HOLD", "REGIME_UNAVAILABLE", 0.0)


def test_overlay_never_blocks_sell():
    assert apply_regime_overlay(
        "SELL", "EXIT", 0.2, regime("HIGH_VOL_BEAR")
    )[:3] == ("SELL", "EXIT", 0.2)
    assert apply_regime_overlay(
        "SELL", "EXIT", 0.2, None
    )[:3] == ("SELL", "EXIT", 0.2)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `../env10/bin/python -m pytest tests/test_market_regime.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'market_regime'`.

- [ ] **Step 3: Implement the minimum module**

Create `code/market_regime.py` with:

```python
"""Causal market-level Gaussian HMM regime filtering."""

import hashlib
import json

import numpy as np
import pandas as pd

INDEX_CODE = "000300"
N_STATES = 3
TRAINING_WINDOW = 504
RETRAIN_EVERY = 21
POLICY_VERSION = "hmm-market-regime-v1"
STATE_COLUMNS = {
    "LOW_VOL_BULL": "p_low_vol_bull",
    "RANGE": "p_range",
    "HIGH_VOL_BEAR": "p_high_vol_bear",
}


def build_regime_observations(frame):
    clean = frame.copy()
    clean.index = pd.to_datetime(clean["trade_date"])
    close = pd.Series(clean["close"].to_numpy(dtype=float), index=clean.index)
    log_return = np.log(close / close.shift(1))
    volatility = log_return.rolling(20).std(ddof=0)
    return pd.DataFrame({
        "log_return": log_return,
        "realized_volatility_20": volatility,
        "trend_strength_20": log_return.rolling(20).mean()
        / volatility.replace(0, np.nan),
    }, index=clean.index)


def state_names_from_means(means):
    order = np.argsort(np.asarray(means)[:, 2])
    return {
        int(order[0]): "HIGH_VOL_BEAR",
        int(order[1]): "RANGE",
        int(order[2]): "LOW_VOL_BULL",
    }


def _default_model():
    from hmmlearn.hmm import GaussianHMM
    return GaussianHMM(
        n_components=N_STATES,
        covariance_type="diag",
        n_iter=200,
        random_state=42,
    )
```

Add small private helpers for diagonal Gaussian likelihood, numerically stable
normalization, and forward recursion. `walk_forward_regimes` must initialize all
dated rows as unavailable, fit only rows before each batch, freeze training
normalization, set probabilities by economic state name, record
`trained_until`, and store JSON-safe fit parameters in `result.attrs["fits"]`.
Catch dependency, fit, convergence, and numeric failures and record an explicit
status without emitting a state.

`apply_regime_overlay` must return unchanged values and `{}` when `regime_row`
is `None`; otherwise it must include state probabilities, status, model version,
trained cutoff, base fraction, and scaled fraction in the feature dictionary.

- [ ] **Step 4: Run unit tests and verify GREEN**

Run: `../env10/bin/python -m pytest tests/test_market_regime.py -q`

Expected: all Task 1 tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add code/market_regime.py tests/test_market_regime.py
git commit -m "feat: add causal HMM market regimes"
```

---

### Task 2: Backtest decision integration

**Files:**
- Modify: `code/backtest_kline_engine.py`
- Modify: `tests/test_market_regime.py`

**Interfaces:**
- Consumes: `walk_forward_regimes(...)` and `apply_regime_overlay(...)`
- Produces: `regime_filter: bool = False` on both backtest methods
- Produces: conditional `backtest_metadata["market_regime"]`

- [ ] **Step 1: Add failing integration tests**

Append tests that build the existing temporary integration database, monkeypatch
`walk_forward_regimes` with a dated deterministic regime frame, and assert:

```python
def test_portfolio_builds_one_shared_regime_frame(monkeypatch, tmp_path):
    # Import build_test_db and deterministic_predictions from the existing
    # integration test module, run two symbols with regime_filter=True, and
    # assert the patched regime builder was called exactly once.
    # Assert metadata reports enabled=True and both filtered/scaled counts.


def test_regime_filter_and_evolution_are_rejected(tmp_path):
    # Call run_kline_backtest(regime_filter=True, run_evolution=True) and assert
    # error_code == "REGIME_EVOLUTION_UNSUPPORTED" before model or market work.
```

Add a single-symbol test that records simulator decisions and proves a dated
bear BUY becomes HOLD while a SELL remains SELL.

- [ ] **Step 2: Run integration tests and verify RED**

Run: `../env10/bin/python -m pytest tests/test_market_regime.py -q`

Expected: failures report unexpected `regime_filter` arguments and missing
metadata.

- [ ] **Step 3: Implement the backtest wiring**

In `code/backtest_kline_engine.py`:

```python
from market_regime import (
    INDEX_CODE as REGIME_INDEX_CODE,
    N_STATES as REGIME_STATES,
    POLICY_VERSION as REGIME_POLICY_VERSION,
    RETRAIN_EVERY as REGIME_RETRAIN_EVERY,
    TRAINING_WINDOW as REGIME_TRAINING_WINDOW,
    apply_regime_overlay,
    walk_forward_regimes,
)
```

Add `_load_market_regimes(conn, end_date)` to query `index_daily` once and call
`walk_forward_regimes`. Add an optional `regimes=None` argument to
`_build_symbol_run`. At both existing action creation sites, look up the exact
date, call `apply_regime_overlay`, use the returned fraction for
`target_fraction` and `desired_shares`, merge regime features into the existing
feature dictionary, and keep raw SELL behavior.

Add `regime_filter=False` to `run_kline_backtest` and
`run_portfolio_backtest`. Reject filter plus evolution immediately. Load the
regime frame once per run when enabled and pass the same frame to every symbol.

Extend `_backtest_metadata` with an optional `market_regime=None` argument. Add
no key when disabled. When enabled, summarize dated coverage, state counts,
blocked BUY decisions, half-sized BUY decisions, and include
`UNVERIFIED_MARKET_REGIME_DATA` in research limitations.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `../env10/bin/python -m pytest tests/test_market_regime.py tests/test_backtest_integration.py tests/test_web_validation.py -q`

Expected: all focused tests pass and default metadata assertions remain
unchanged.

- [ ] **Step 5: Commit Task 2**

```bash
git add code/backtest_kline_engine.py tests/test_market_regime.py
git commit -m "feat: filter backtest entries by market regime"
```

---

### Task 3: Full verification and research smoke test

**Files:**
- Modify only if verification exposes a defect: files already listed above

**Interfaces:**
- Verifies the approved spec end to end.

- [ ] **Step 1: Run syntax and diff checks**

Run: `../env10/bin/python -m py_compile code/market_regime.py code/backtest_kline_engine.py`

Expected: exit code 0 with no output.

Run: `git diff --check HEAD~2..HEAD`

Expected: exit code 0 with no output.

- [ ] **Step 2: Run the complete suite in the HMM-capable environment**

Run: `../env10/bin/python -m pytest -q`

Expected: all existing and new tests pass.

- [ ] **Step 3: Verify the disabled path in the default interpreter**

Run: `python3 -m pytest -q`

Expected: all tests that do not require the opt-in HMM dependency pass; the lazy
import keeps the default-disabled production path importable.

- [ ] **Step 4: Run one read-only research-proxy smoke test**

Run a temporary Python command using `env10` that calls
`KLineBacktestEngine.run_kline_backtest` with a fixed symbol/date range,
`backtest_mode="RESEARCH_PROXY"`, and `regime_filter=True`. Do not persist
experiences or run evolution.

Expected: the response contains `backtest_metadata.market_regime`, dated regime
coverage, and no serialization errors.

- [ ] **Step 5: Inspect final scope**

Run: `git status --short`

Expected: only pre-existing unrelated user changes remain; task files are
committed.
