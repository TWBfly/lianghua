# Backtest Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove known backtest bias and accounting defects while keeping Backtrader outside the closed-source production runtime.

**Architecture:** Keep `KLineBacktestEngine` and its JSON contract. Repair the shared simulator, make learning explicitly causal, load pre-start warm-up history, expose honest metadata, and use a temporary external Backtrader installation only for differential verification.

**Tech Stack:** Python 3, pandas, SQLite, LightGBM, pytest; Backtrader 1.9.78.123 for an internal temporary oracle only.

## Global Constraints

- Production modules must not import or declare Backtrader.
- Existing Web API top-level response keys remain compatible.
- Historical data limitations are reported, not hidden or invented.
- Every behavior change starts with a failing focused test.
- This directory has no Git metadata, so test checkpoints replace commits.

---

### Task 1: Correct Shared-Account Execution

**Files:**
- Modify: `tests/test_portfolio_simulator.py`
- Modify: `code/portfolio_simulator.py`

**Interfaces:**
- Consumes: `simulate_portfolio(market, decisions, initial_cash, risk_limits=None, fees=None, names=None)`
- Produces: the existing `SimulationResult`, with marked open positions and no synthetic terminal trade.

- [ ] **Step 1: Write failing simulator regressions**

Add tests asserting that an end-date position remains open and marked to close,
same-day sells are rejected as `T_PLUS_ONE`, stamp duty is 0.1% before
2023-08-28 and 0.05% afterward, and `688` buys require at least 200 shares.

```python
def test_terminal_position_is_marked_not_forced_sold():
    result = simulate_portfolio(...)
    assert result.trades == []
    assert result.positions["000001"]["shares"] > 0
    assert result.final_equity == result.equity_curve[-1]["equity"]

def test_stamp_duty_changes_on_2023_08_28():
    before = _sell_proceeds(1000, 10, FeeSchedule(), pd.Timestamp("2023-08-25"))
    after = _sell_proceeds(1000, 10, FeeSchedule(), pd.Timestamp("2023-08-28"))
    assert before[2] - after[2] == 5.0
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `pytest -q tests/test_portfolio_simulator.py`

Expected: failures for forced liquidation, missing dated fee argument, T+1, and STAR quantity behavior.

- [ ] **Step 3: Implement the minimum execution fixes**

Add `stamp_duty_rate(date)`, `_minimum_buy_shares(symbol)`, and a serializable
position snapshot. Pass the execution date into `_sell_proceeds`, reject sells
whose date is not later than `entry_time`, delete terminal liquidation, and set
`final_equity` from the final marked curve.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `pytest -q tests/test_portfolio_simulator.py`

Expected: all simulator tests pass.

- [ ] **Step 5: Record checkpoint**

Run: `pytest -q tests/test_portfolio_simulator.py tests/test_backtest_integration.py`

### Task 2: Make Evolution Labels And Evaluation Causal

**Files:**
- Modify: `tests/test_learning_loop.py`
- Modify: `code/learning_loop.py`
- Modify: `code/backtest_kline_engine.py`

**Interfaces:**
- Produces: `ExperienceStore.complete_horizon(..., horizon_end_time)` and model `trained_until` equal to the latest matured label timestamp.

- [ ] **Step 1: Write failing maturity and overlap tests**

```python
def test_model_cutoff_uses_label_end_time(tmp_path):
    ...
    assert pd.Timestamp(registry.get(version)["trained_until"]) == dates[-1] + pd.offsets.BDay(5)

def test_evaluation_uses_non_overlapping_five_bar_returns():
    result = evaluate_predictions(returns, probabilities, folds=3, horizon_bars=5)
    assert result.evaluated_samples == len(returns.iloc[::5])
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `pytest -q tests/test_learning_loop.py tests/test_backtest_integration.py`

- [ ] **Step 3: Implement schema migration and purging**

Add nullable `horizon_end_time` to `experiences`, populate it from the actual
fifth future market index, include it in `completed_frame`, exclude it from
features, set `trained_until` to its maximum, and use
`TimeSeriesSplit(n_splits=3, gap=5)`.

Change `evaluate_predictions` to evaluate each fold on non-overlapping
`horizon_bars` rows before compounding.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `pytest -q tests/test_learning_loop.py tests/test_backtest_integration.py`

### Task 3: Warm Up Before Start And Make Backtests Pure

**Files:**
- Modify: `tests/test_causal_ml.py`
- Modify: `tests/test_backtest_integration.py`
- Modify: `code/backtest_kline_engine.py`

**Interfaces:**
- `run_kline_backtest(..., persist_experiences=False, run_evolution=False)`
- `run_portfolio_backtest(..., persist_experiences=False, run_evolution=False)`

- [ ] **Step 1: Write failing start-invariance and purity tests**

Assert that a prediction on a shared date is unchanged when the reporting start
date moves later, and that default runs do not create `experiences` or training
events.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q tests/test_causal_ml.py tests/test_backtest_integration.py`

- [ ] **Step 3: Load causal warm-up history**

Load all available bars through `end_date`, build factors and predictions once,
then slice market, decisions, and returned model versions to `start_date`.
Change persistence/evolution defaults to false.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `pytest -q tests/test_causal_ml.py tests/test_backtest_integration.py`

### Task 4: Refresh Adjusted Data Atomically

**Files:**
- Create: `tests/test_data_engine.py`
- Modify: `code/ashare_data_engine.py`

**Interfaces:**
- `sync_stock_daily` fetches a full qfq range per requested symbol and replaces that symbol only after a successful fetch.

- [ ] **Step 1: Write a failing atomic-refresh test**

Mock one successful full-history response and assert stale symbol rows are
replaced, while another symbol remains untouched. Mock an empty response and
assert existing rows remain.

- [ ] **Step 2: Run test and verify RED**

Run: `pytest -q tests/test_data_engine.py`

- [ ] **Step 3: Implement fetch-before-delete replacement**

Fetch from `start_date` through `end_date`, normalize first, then delete and
append inside one SQLite transaction.

- [ ] **Step 4: Run test and verify GREEN**

Run: `pytest -q tests/test_data_engine.py`

### Task 5: Report Honest Metrics And Limitations

**Files:**
- Modify: `tests/test_backtest_integration.py`
- Modify: `code/backtest_kline_engine.py`
- Modify: `web/app.js`

**Interfaces:**
- Preserve `portfolio_metrics`, `yearly_breakdown`, and `kelly_allocations` keys.
- Add `backtest_metadata` and make `kelly_allocations` a compatibility alias of truthful fixed-risk allocations.

- [ ] **Step 1: Write failing reporting tests**

Assert actual period endpoints, year-to-year equity returns, `engine`,
`price_mode`, `universe_mode`, fallback count, and research warnings. Assert no
Kelly field claims computed win rates or ratios.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q tests/test_backtest_integration.py`

- [ ] **Step 3: Implement reporting and frontend wording**

Derive annual PnL/returns from equity endpoints, add metadata, return fixed-risk
allocation fields, and replace visible Kelly claims with fixed-risk wording.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `pytest -q tests/test_backtest_integration.py tests/test_web_validation.py`

### Task 6: Differential Backtrader Oracle And Full Verification

**Files:**
- Temporary only: `/private/tmp/lianghua-backtrader-oracle/`
- Temporary only: `/private/tmp/verify_lianghua_backtrader.py`

**Interfaces:**
- No production or project import of Backtrader.

- [ ] **Step 1: Install Backtrader outside the project**

Run: `python3 -m pip install --target /private/tmp/lianghua-backtrader-oracle backtrader==1.9.78.123`

- [ ] **Step 2: Run a deterministic differential scenario**

The temporary script uses `Cerebro(cheat_on_open=True)` and equivalent pandas
feeds, cash, commission, and slippage. Assert next-open timestamps, shared cash,
position sizes, and final marked equity match within one cent on a scenario
without A-share-only rejections.

- [ ] **Step 3: Verify GPL isolation**

Run: `rg -n "import backtrader|from backtrader" code web`

Expected: no matches.

- [ ] **Step 4: Run the complete suite**

Run: `pytest -q`

Expected: all tests pass.
