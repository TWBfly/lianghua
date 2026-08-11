# ML Strategy Trust Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the trusted A-share ML path temporally causal, position-aware, liquidity-constrained, and promotion-safe while keeping invalid futures/XAUUSD experiments outside executable surfaces.

**Architecture:** Keep `KLineBacktestEngine` as the decision producer and `simulate_portfolio` as the only execution/state owner. Fix regime routing inside the existing walk-forward loop, attach a small fixed ATR policy to BUY decisions, enforce the existing volume-fraction field in the shared simulator, and evaluate Champion and Challenger artifacts on one identical shadow frame. Do not add a framework, dependency, model family, or partial-position ledger.

**Tech Stack:** Python 3, pandas, NumPy, scikit-learn-compatible estimators, joblib, SQLite, pytest, Flask test client, Node syntax checker.

## Global Constraints

- Follow strict RED → GREEN → refactor cycles; do not edit production code before the named failing test has been observed.
- Preserve all pre-existing dirty-worktree changes. Stage and commit only files named by the current task.
- Reuse `walk_forward_splits`, `_buy_quantity`, `_buy_cost`, `_sell_proceeds`, `evaluate_predictions`, `PromotionGate`, and the executable strategy registry.
- Keep `FeeSchedule.max_bar_volume_fraction` as the only liquidity setting.
- Keep risk parameters fixed in one decision payload; do not introduce a configuration class.
- No partial fills for exits. An exit above the volume ceiling fails closed and leaves the position unchanged.
- Do not touch, rewrite, or relabel historical futures/XAUUSD result JSON.
- Run all Python tests from the repository root so `tests/conftest.py` installs the correct `code/` import path.
- Before each commit, run `git diff --check` and stage only the task's files.

---

## Task 1: Freeze the trusted production boundary

**Files:**

- Create: `docs/research-only-ml-engines.md`
- Modify: `tests/test_web_validation.py`

- [ ] **Step 1: Write the failing boundary test**

Append this module list and test to `tests/test_web_validation.py`:

```python
RESEARCH_ONLY_INVALIDATED = {
    "futures_ml_strategy_engine",
    "futures_self_evolving_holy_grail_engine",
    "futures_v14_complete_self_evolving_engine",
    "futures_v15_anti_degradation_engine",
    "multi_timeframe_benchmark_evaluator",
    "xauusd_ml_strategy",
    "xauusd_self_evolving_engine",
    "xauusd_hardcore_multi_tf",
    "xauusd_hardcore_stress_test",
    "xauusd_m5_runner",
}


def test_invalidated_ml_engines_are_documented_and_not_executable():
    from strategy_hot_plugger import hot_plugger
    from web_server import app

    root = Path(__file__).resolve().parents[1]
    status_path = root / "docs" / "research-only-ml-engines.md"
    assert status_path.exists()
    status = status_path.read_text(encoding="utf-8")
    executable = set(hot_plugger.get_executable_strategies())
    response = app.test_client().get("/api/strategies")
    assert response.status_code == 200
    exposed = {
        item["name"] if isinstance(item, dict) else item
        for item in response.get_json()
    }

    for module in RESEARCH_ONLY_INVALIDATED:
        assert (root / "code" / f"{module}.py").exists()
        assert f"`{module}` — `RESEARCH_ONLY_INVALIDATED`" in status
        assert module not in executable
        assert module not in exposed
```

- [ ] **Step 2: Run the test and confirm RED**

Run: `pytest -q tests/test_web_validation.py::test_invalidated_ml_engines_are_documented_and_not_executable`

Expected: FAIL because `docs/research-only-ml-engines.md` does not exist.

- [ ] **Step 3: Add the research-status document**

Create `docs/research-only-ml-engines.md` with this exact contract:

```markdown
# Research-only invalidated ML engines

These modules are retained only for forensic review. Their reported results
failed the trusted simulator or temporal-validation contract and must not be
offered by `hot_plugger.get_executable_strategies()` or `/api/strategies`.

- `futures_ml_strategy_engine` — `RESEARCH_ONLY_INVALIDATED`
- `futures_self_evolving_holy_grail_engine` — `RESEARCH_ONLY_INVALIDATED`
- `futures_v14_complete_self_evolving_engine` — `RESEARCH_ONLY_INVALIDATED`
- `futures_v15_anti_degradation_engine` — `RESEARCH_ONLY_INVALIDATED`
- `multi_timeframe_benchmark_evaluator` — `RESEARCH_ONLY_INVALIDATED`
- `xauusd_ml_strategy` — `RESEARCH_ONLY_INVALIDATED`
- `xauusd_self_evolving_engine` — `RESEARCH_ONLY_INVALIDATED`
- `xauusd_hardcore_multi_tf` — `RESEARCH_ONLY_INVALIDATED`
- `xauusd_hardcore_stress_test` — `RESEARCH_ONLY_INVALIDATED`
- `xauusd_m5_runner` — `RESEARCH_ONLY_INVALIDATED`

Re-entry requires timestamp-aligned real market data, the shared execution
contract, causal validation, and reconciled fills, positions, cash, and PnL.
Historical JSON output is not evidence of validity.
```

- [ ] **Step 4: Run the focused test and confirm GREEN**

Run: `pytest -q tests/test_web_validation.py::test_invalidated_ml_engines_are_documented_and_not_executable`

Expected: PASS.

- [ ] **Step 5: Commit the boundary**

```bash
git add docs/research-only-ml-engines.md tests/test_web_validation.py
git diff --check --cached
git commit -m "docs: quarantine invalid ML research engines"
```

---

## Task 2: Route every prediction date through its own regime

**Files:**

- Modify: `tests/test_causal_ml.py`
- Modify: `code/ml_ensemble.py`

- [ ] **Step 1: Add a mixed-regime regression test**

Add this test to `tests/test_causal_ml.py`:

```python
def test_walk_forward_routes_each_prediction_row_by_its_own_regime(
        monkeypatch):
    import ml_ensemble

    routed = []
    probability_by_regime = {
        "LOW_VOL_BULL": 0.8,
        "HIGH_VOL_BEAR": 0.2,
        "RANGE": 0.5,
    }

    class IdentityModel:
        def get_params(self, deep=False):
            return {}

    class RecordingEnsemble:
        def __init__(self, base_factory=None):
            self.global_model = IdentityModel()

        def fit(self, features, target, regimes):
            return self

        def predict_proba(self, features, current_regime=None):
            routed.append((current_regime, len(features)))
            value = probability_by_regime[current_regime]
            return np.column_stack([
                np.full(len(features), 1.0 - value),
                np.full(len(features), value),
            ])

    monkeypatch.setattr(
        ml_ensemble, "RegimeConditionedMLEnsemble", RecordingEnsemble
    )
    monkeypatch.setattr(
        ml_ensemble, "build_model_identity", lambda *_args, **_kwargs: "v"
    )
    frame = market_frame(180)
    result = walk_forward_predict(
        frame,
        factor_frame(frame),
        "000001",
        min_train_size=40,
        max_train_size=40,
        retrain_every=21,
    )

    close = frame["close"]
    vol20 = close.pct_change().rolling(20).std()
    ma60 = close.rolling(60).mean()
    median = vol20.expanding(min_periods=20).median().fillna(0.02)
    expected_regime = np.where(
        (close >= ma60) & (vol20 < median),
        "LOW_VOL_BULL",
        np.where(close < ma60, "HIGH_VOL_BEAR", "RANGE"),
    )
    covered = result["model_version"].eq("v")
    expected = pd.Series(expected_regime, index=result.index).map(
        probability_by_regime
    )

    assert covered.any()
    assert len({state for state, _ in routed}) > 1
    pd.testing.assert_series_equal(
        result.loc[covered, "probability"],
        expected.loc[covered],
        check_names=False,
    )
```

The existing `test_regime_conditioned_ml_ensemble_training_and_routing`
continues to prove that an unavailable regime-specific model falls back to the
global model.

- [ ] **Step 2: Run the new test and confirm RED**

Run: `pytest -q tests/test_causal_ml.py::test_walk_forward_routes_each_prediction_row_by_its_own_regime`

Expected: FAIL because each 21-row batch currently receives the final row's regime and therefore one constant routed probability.

- [ ] **Step 3: Group predictions by their own causal regime**

Replace the batch-final regime block in `walk_forward_predict` with:

```python
        pred_locs = np.array([
            features.index.get_loc(idx) for idx in prediction_index
        ])
        prediction_regimes = regimes[pred_locs]
        probability = np.full(len(prediction_index), np.nan)
        prediction_values = features.loc[prediction_index].to_numpy(
            dtype=np.float32
        )
        for state in pd.unique(prediction_regimes):
            state_mask = prediction_regimes == state
            state_probability = ensemble.predict_proba(
                prediction_values[state_mask],
                current_regime=state,
            )[:, 1]
            probability[state_mask] = np.where(
                np.isfinite(state_probability), state_probability, np.nan
            )
```

Do not alter training indices, label maturity, batch size, model identity, or
result index assignment.

- [ ] **Step 4: Run causal ML tests and confirm GREEN**

Run: `pytest -q tests/test_causal_ml.py`

Expected: PASS, including prefix invariance and the global fallback test.

- [ ] **Step 5: Commit the causal routing fix**

```bash
git add code/ml_ensemble.py tests/test_causal_ml.py
git diff --check --cached
git commit -m "fix: route ML predictions by causal regime"
```

---

## Task 3: Attach causal ATR policy metadata to BUY decisions

**Files:**

- Modify: `tests/test_backtest_integration.py`
- Modify: `code/backtest_kline_engine.py`

- [ ] **Step 1: Add available/missing ATR decision tests**

Add the imports `json` and the following parametrized test to
`tests/test_backtest_integration.py`:

```python
@pytest.mark.parametrize(("atr_value", "expected_status"), [
    (0.8, "AVAILABLE"),
    (np.nan, "UNAVAILABLE"),
])
def test_causal_ml_buy_decision_carries_atr_risk_metadata(
        tmp_path, monkeypatch, atr_value, expected_status):
    seen = {}
    real_simulator = backtest_kline_engine.simulate_portfolio

    def recording_simulator(market, decisions, initial_cash, **kwargs):
        seen["decisions"] = decisions.copy()
        return real_simulator(market, decisions, initial_cash, **kwargs)

    monkeypatch.setattr(
        backtest_kline_engine, "walk_forward_predict",
        deterministic_predictions,
    )
    monkeypatch.setattr(
        backtest_kline_engine,
        "calculate_atr",
        lambda frame, n=14: pd.Series(atr_value, index=frame.index),
    )
    monkeypatch.setattr(
        backtest_kline_engine, "simulate_portfolio", recording_simulator
    )
    monkeypatch.setattr(
        KLineBacktestEngine,
        "_load_market_regimes",
        staticmethod(lambda _conn, _end_date: None),
    )
    engine = KLineBacktestEngine(build_test_db(tmp_path))
    engine.run_kline_backtest(
        "000001", "2025-07-01", "2025-10-31",
        backtest_mode="RESEARCH_PROXY",
    )

    buy = seen["decisions"].loc[
        seen["decisions"]["action"] == "BUY"
    ].iloc[0]
    features = json.loads(buy["features_json"])
    assert buy["risk_exit_status"] == expected_status
    assert features["risk_exit_status"] == expected_status
    if expected_status == "AVAILABLE":
        assert buy["risk_exit"] == {
            "entry_atr": 0.8,
            "stop_atr_multiple": 1.25,
            "stop_floor_fraction": 0.972,
            "take_profit_atr_multiple": 2.5,
            "trailing_activation_fraction": 1.03,
            "trailing_atr_multiple": 1.0,
        }
    else:
        assert buy["risk_exit"] is None
```

- [ ] **Step 2: Run the test and confirm RED**

Run: `pytest -q tests/test_backtest_integration.py::test_causal_ml_buy_decision_carries_atr_risk_metadata`

Expected: FAIL because `calculate_atr` is not imported and decisions do not contain the risk fields.

- [ ] **Step 3: Calculate ATR once and serialize the fixed policy**

In `code/backtest_kline_engine.py`, import the existing indicator:

```python
from technical_indicators import calculate_atr
```

Define one immutable module constant:

```python
ATR_RISK_POLICY = {
    "stop_atr_multiple": 1.25,
    "stop_floor_fraction": 0.972,
    "take_profit_atr_multiple": 2.5,
    "trailing_activation_fraction": 1.03,
    "trailing_atr_multiple": 1.0,
}
```

After creating `index`, build the indexed market frame once:

```python
        market_frame = frame.copy()
        market_frame.index = index
```

Keep the existing mechanical-strategy early return. Immediately after that
branch, calculate ATR only for the causal-ML path:

```python
        atr = calculate_atr(market_frame, 14)
```

Inside the causal-ML decision loop, after regime overlay decides the final
action, attach policy metadata only to an actual BUY:

```python
            atr_value = atr.loc[date]
            risk_available = (
                action == "BUY"
                and pd.notna(atr_value)
                and math.isfinite(float(atr_value))
                and float(atr_value) > 0
            )
            risk_exit = (
                {"entry_atr": float(atr_value), **ATR_RISK_POLICY}
                if risk_available else None
            )
            risk_exit_status = (
                "AVAILABLE" if risk_available else "UNAVAILABLE"
            )
            features["risk_exit_status"] = risk_exit_status
```

Add these keys to the decision dictionary:

```python
                "risk_exit_status": risk_exit_status,
                "risk_exit": risk_exit,
```

Reuse the already-indexed `market_frame` in both return paths; do not calculate
ATR or attach an ATR policy to mechanical strategies.

- [ ] **Step 4: Run integration tests and confirm GREEN**

Run: `pytest -q tests/test_backtest_integration.py`

Expected: PASS.

- [ ] **Step 5: Commit ATR decision metadata**

```bash
git add code/backtest_kline_engine.py tests/test_backtest_integration.py
git diff --check --cached
git commit -m "feat: attach causal ATR risk metadata"
```

---

## Task 4: Enforce the existing liquidity ceiling

**Files:**

- Modify: `tests/test_portfolio_simulator.py`
- Modify: `code/portfolio_simulator.py`

- [ ] **Step 1: Add entry cap, below-lot, and oversized-exit tests**

Append these tests to `tests/test_portfolio_simulator.py`:

```python
def test_buy_fill_never_exceeds_causal_volume_ceiling():
    frame = bars([10, 10, 10], volumes=[10_000, 10_000, 10_000])
    result = simulate_portfolio(
        {"000001": frame},
        pd.DataFrame([decision(frame.index[0], fraction=0.9)]),
        initial_cash=100_000,
    )

    assert result.fills[0]["shares"] == 100


def test_below_lot_volume_ceiling_rejects_buy():
    frame = bars([10, 10, 10], volumes=[9_999, 9_999, 9_999])
    result = simulate_portfolio(
        {"000001": frame},
        pd.DataFrame([decision(frame.index[0], fraction=0.9)]),
        initial_cash=100_000,
    )

    assert result.fills == []
    assert result.rejected_orders[0]["reason"] == "LIQUIDITY_LIMIT"


def test_oversized_exit_is_rejected_and_position_is_preserved():
    frame = bars(
        [10, 10, 10, 10],
        volumes=[1_000_000, 100, 100, 100],
    )
    result = simulate_portfolio(
        {"000001": frame},
        pd.DataFrame([
            decision(frame.index[0], action="BUY", fraction=0.9),
            decision(frame.index[1], action="SELL"),
        ]),
        initial_cash=100_000,
        risk_limits=RiskLimits(
            max_position_fraction=0.9,
            max_gross_exposure=0.9,
        ),
    )

    assert any(
        item["side"] == "SELL" and item["reason"] == "LIQUIDITY_LIMIT"
        for item in result.rejected_orders
    )
    assert result.trades == []
    assert result.positions["000001"]["shares"] > 0
```

- [ ] **Step 2: Run the three tests and confirm RED**

Run: `pytest -q tests/test_portfolio_simulator.py -k 'volume_ceiling or oversized_exit'`

Expected: FAIL because `max_bar_volume_fraction` is not enforced.

- [ ] **Step 3: Add one trading-unit-aware cap helper**

Add beside `_buy_quantity`:

```python
def _share_limit(symbol, executable_volume, fraction):
    _, minimum_shares, share_step = _buy_quantity(symbol, 0, 1)
    shares = max(0, int(float(executable_volume) * float(fraction)))
    shares = shares // share_step * share_step
    return (
        shares if shares >= minimum_shares else 0,
        minimum_shares,
    )
```

In the order loop, retain the causal prior-volume estimate but never fall back
to the current bar for sizing:

```python
            hist_vol_s = frame.loc[frame.index < date, "volume"]
            exec_volume = (
                float(hist_vol_s.tail(20).mean())
                if not hist_vol_s.empty else 0.0
            )
            volume_limit, volume_minimum = _share_limit(
                symbol,
                exec_volume,
                fee_schedule.max_bar_volume_fraction,
            )
```

Before the BUY cash loop:

```python
                if volume_limit < volume_minimum:
                    rejected.append(_reject(order, date, "LIQUIDITY_LIMIT"))
                    continue
                shares = min(shares, volume_limit)
```

Before explicit SELL settlement:

```python
                if position.shares > volume_limit:
                    rejected.append(_reject(order, date, "LIQUIDITY_LIMIT"))
                    continue
```

Keep current-bar volume only for suspension detection. Pass `exec_volume` to
the existing slippage functions exactly as today.

- [ ] **Step 4: Run the complete simulator test file and confirm GREEN**

Run: `pytest -q tests/test_portfolio_simulator.py`

Expected: PASS.

- [ ] **Step 5: Commit liquidity enforcement**

```bash
git add code/portfolio_simulator.py tests/test_portfolio_simulator.py
git diff --check --cached
git commit -m "fix: enforce causal execution volume limits"
```

---

## Task 5: Execute ATR exits from real filled-position state

**Files:**

- Modify: `tests/test_portfolio_simulator.py`
- Modify: `code/portfolio_simulator.py`

- [ ] **Step 1: Extend the test decision helper**

Change the helper signature without affecting existing callers:

```python
def decision(date, symbol="000001", action="BUY", fraction=0.5,
             risk_exit=None):
    return {
        "decision_time": pd.Timestamp(date),
        "symbol": symbol,
        "action": action,
        "target_fraction": fraction,
        "reason": "test",
        "model_version": "v1",
        "features_json": "{}",
        "risk_exit": risk_exit,
    }
```

Add a fixed test helper:

```python
def atr_policy(atr=1.0):
    return {
        "entry_atr": atr,
        "stop_atr_multiple": 1.25,
        "stop_floor_fraction": 0.972,
        "take_profit_atr_multiple": 2.5,
        "trailing_activation_fraction": 1.03,
        "trailing_atr_multiple": 1.0,
    }
```

- [ ] **Step 2: Add focused position-state exit tests**

Add tests covering the five required mechanics:

```python
@pytest.mark.parametrize(("high", "low", "reason"), [
    (10.2, 9.6, "ATR_STOP"),
    (13.0, 10.0, "ATR_TAKE_PROFIT"),
])
def test_atr_stop_and_take_profit_use_actual_fill_state(
        high, low, reason):
    frame = bars([10, 10, 10, 10])
    frame.loc[frame.index[2], ["high", "low"]] = [high, low]
    result = simulate_portfolio(
        {"000001": frame},
        pd.DataFrame([
            decision(frame.index[0], risk_exit=atr_policy()),
        ]),
        initial_cash=100_000,
    )

    assert result.trades[0]["exit_reason"] == reason
    sell = next(fill for fill in result.fills if fill["side"] == "SELL")
    expected = _sell_proceeds(
        sell["shares"], sell["raw_price"], FeeSchedule(),
        sell["fill_time"], symbol="000001",
        daily_volume=1_000_000,
    )
    assert sell["fill_price"] == pytest.approx(expected[0])
    assert sell["fees"] == pytest.approx(expected[2])


def test_t_plus_one_prevents_entry_day_atr_exit():
    frame = bars([10, 10, 10])
    frame.loc[frame.index[1], "low"] = 1.0
    result = simulate_portfolio(
        {"000001": frame},
        pd.DataFrame([
            decision(frame.index[0], risk_exit=atr_policy()),
        ]),
        initial_cash=100_000,
    )

    assert result.trades == []
    assert "000001" in result.positions


def test_same_bar_stop_wins_over_take_profit():
    frame = bars([10, 10, 10, 10])
    frame.loc[frame.index[2], ["high", "low"]] = [20.0, 1.0]
    result = simulate_portfolio(
        {"000001": frame},
        pd.DataFrame([
            decision(frame.index[0], risk_exit=atr_policy()),
        ]),
        initial_cash=100_000,
    )

    assert result.trades[0]["exit_reason"] == "ATR_STOP"


def test_trailing_exit_uses_prior_peak_not_current_bar_high():
    frame = bars([10, 10, 10])
    frame.loc[frame.index[2], ["high", "low"]] = [12.0, 10.0]
    result = simulate_portfolio(
        {"000001": frame},
        pd.DataFrame([
            decision(frame.index[0], risk_exit=atr_policy()),
        ]),
        initial_cash=100_000,
    )

    assert result.trades == []
    assert result.positions["000001"]["shares"] > 0


def test_missing_atr_policy_leaves_signal_exit_available():
    frame = bars([10, 10, 10, 10])
    result = simulate_portfolio(
        {"000001": frame},
        pd.DataFrame([
            decision(frame.index[0], action="BUY"),
            decision(frame.index[1], action="SELL"),
        ]),
        initial_cash=100_000,
    )

    assert result.trades[0]["exit_reason"] == "test"
```

When implementing, tune only bar values that interact with existing adverse
slippage; do not weaken the assertions.

- [ ] **Step 3: Run the ATR tests and confirm RED**

Run: `pytest -q tests/test_portfolio_simulator.py -k 'atr or trailing_exit or missing_atr'`

Expected: FAIL because positions do not store the filled entry price/policy and
the simulator does not evaluate intraday risk exits.

- [ ] **Step 4: Store actual fill state and calculate one conservative trigger**

Extend `Position`:

```python
@dataclass
class Position:
    shares: int
    average_cost: float
    entry_time: pd.Timestamp
    entry_price: float
    peak_price: float
    entry_value: float
    buy_fees: float
    decision_id: str
    risk_exit: dict | None = None
```

At BUY fill, set:

```python
                    entry_price=fill_price,
                    risk_exit=order.get("risk_exit"),
```

Add the pure trigger helper:

```python
def _atr_exit(position, bar):
    policy = position.risk_exit
    if not policy:
        return None
    atr = float(policy["entry_atr"])
    entry = position.entry_price
    base_stop = max(
        entry - float(policy["stop_atr_multiple"]) * atr,
        entry * float(policy["stop_floor_fraction"]),
    )
    trailing_stop = None
    if position.peak_price >= (
        entry * float(policy["trailing_activation_fraction"])
    ):
        trailing_stop = (
            position.peak_price
            - float(policy["trailing_atr_multiple"]) * atr
        )
    stop = max(
        level for level in (base_stop, trailing_stop)
        if level is not None
    )
    if float(bar["low"]) <= stop:
        reason = (
            "ATR_TRAILING_STOP"
            if trailing_stop is not None and stop == trailing_stop
            else "ATR_STOP"
        )
        return reason, min(float(bar["open"]), stop)
    take = entry + float(policy["take_profit_atr_multiple"]) * atr
    if float(bar["high"]) >= take:
        return "ATR_TAKE_PROFIT", take
    return None
```

The stop branch deliberately precedes take profit, and the helper reads
`position.peak_price` before the current bar can update it.

- [ ] **Step 5: Reuse one sell-settlement path**

Extract the existing explicit SELL accounting into this small shared helper.
Both explicit SELL and ATR terminal SELL call it; do not duplicate fee
arithmetic:

```python
def _close_position(symbol, position, order, date, raw_price,
                    limit_down, exec_volume, fee_schedule):
    fill_price, gross, sell_fees, net_proceeds = _sell_proceeds(
        position.shares,
        raw_price,
        fee_schedule,
        date,
        limit_down,
        symbol,
        daily_volume=exec_volume,
    )
    transfer_fee = gross * _transfer_fee_rate(
        fee_schedule, symbol, date
    )
    stamp_duty = gross * _stamp_duty_rate(fee_schedule, date)
    pnl = net_proceeds - (position.entry_value + position.buy_fees)
    fill = {
        "decision_id": order["decision_id"],
        "symbol": symbol,
        "side": "SELL",
        "decision_time": order["decision_time"],
        "fill_time": date,
        "raw_price": raw_price,
        "fill_price": fill_price,
        "shares": position.shares,
        "gross_value": gross,
        "fees": sell_fees,
        "commission": sell_fees - transfer_fee - stamp_duty,
        "transfer_fee": transfer_fee,
        "stamp_duty": stamp_duty,
        "slippage": abs(fill_price - raw_price) * position.shares,
        "status": "FILLED",
        "model_version": order.get("model_version", ""),
    }
    trade = {
        "decision_id": position.decision_id,
        "symbol": symbol,
        "buy_date": position.entry_time,
        "buy_price": position.average_cost,
        "sell_date": date,
        "sell_price": fill_price,
        "shares": position.shares,
        "pnl_amount": pnl,
        "pnl_pct": (
            pnl / (position.entry_value + position.buy_fees) * 100
        ),
        "buy_fees": position.buy_fees,
        "sell_fees": sell_fees,
        "exit_reason": order.get("reason", "SIGNAL"),
    }
    return net_proceeds, fill, trade
```

After queued explicit orders, iterate over `list(positions.items())`. For a
position whose normalized `entry_time` is earlier than `date`:

```python
            trigger = _atr_exit(position, bar)
            if trigger is not None:
                reason, risk_price = trigger
                risk_order = {
                    "decision_id": (
                        f"{position.decision_id}:risk:{date.date()}"
                    ),
                    "decision_time": date,
                    "symbol": symbol,
                    "action": "SELL",
                    "reason": reason,
                    "model_version": "terminal",
                }
```

Apply the same suspension, limit-down lock, and `_share_limit` checks as an
explicit SELL. On rejection, append a record built by `_reject` and retain the
position. On success, settle through `_close_position`, append its fill/trade,
add cash, and delete the position.

Only after all risk checks, update every remaining position:

```python
            position.peak_price = max(
                position.peak_price, float(frame.loc[date, "high"])
            )
```

- [ ] **Step 6: Run simulator tests and confirm GREEN**

Run: `pytest -q tests/test_portfolio_simulator.py`

Expected: PASS, including existing T+1, fee reconciliation, limit lock, and
terminal-position tests.

- [ ] **Step 7: Commit filled-state risk exits**

```bash
git add code/portfolio_simulator.py tests/test_portfolio_simulator.py
git diff --check --cached
git commit -m "feat: execute ATR exits from filled positions"
```

---

## Task 6: Compare Champion and Challenger on the identical shadow window

**Files:**

- Modify: `tests/test_learning_loop.py`
- Modify: `code/learning_loop.py`

- [ ] **Step 1: Make the direct promotion test reject stale Champion metrics**

Replace the final assertions in
`test_shadow_model_must_pass_second_gate_before_promotion` with:

```python
    registry.record_shadow_metrics(
        "new", metrics(net=0.12).as_dict(), sample_count=50
    )
    assert not manager.promote_if_ready("new")
    assert manager.promote_if_ready(
        "new", champion_metrics=metrics(net=0.10)
    )
    assert registry.get("new")["status"] == "CHAMPION"
```

- [ ] **Step 2: Add identical-index and invalid-Champion tests**

Add a top-level test model:

```python
class ConstantProbabilityModel:
    def __init__(self, probability):
        self.probability = probability

    def predict_proba(self, features):
        probability = np.full(len(features), self.probability)
        return np.column_stack([1 - probability, probability])
```

Add a helper that writes an artifact below `model_dir`:

```python
def write_artifact(model_dir, symbol, version, probability,
                   feature_names=("momentum",)):
    path = model_dir / symbol / f"{version}.joblib"
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "model": ConstantProbabilityModel(probability),
        "feature_names": list(feature_names),
    }, path)
    return path
```

Add a test that records 60 post-cutoff experiences, registers one Champion
and one Shadow artifact, monkeypatches `learning_loop.evaluate_predictions` to
capture `probabilities.index`, and returns passing deterministic metrics:

```python
def test_shadow_models_are_evaluated_on_identical_dates(
        tmp_path, monkeypatch):
    store = ExperienceStore(tmp_path / "test.db")
    registry = ModelRegistry(tmp_path / "test.db")
    model_dir = tmp_path / "models"
    dates = pd.bdate_range("2026-01-01", periods=60)
    for i, date in enumerate(dates):
        item = sample_decision(f"d{i}")
        item["decision_time"] = date.isoformat()
        item["action"] = "HOLD"
        item["features"] = {"momentum": float(i % 2)}
        store.record_decision(item)
        store.complete_horizon(
            f"d{i}", 0.01, 0.02, -0.01,
            date + pd.offsets.BDay(5),
        )
    champion_path = write_artifact(
        model_dir, "000001", "old", 0.6
    )
    shadow_path = write_artifact(
        model_dir, "000001", "new", 0.7
    )
    registry.register(
        "old", "000001", "CHAMPION", metrics().as_dict(),
        champion_path, evaluated_until="2025-12-31",
    )
    registry.register(
        "new", "000001", "SHADOW", metrics(net=0.11).as_dict(),
        shadow_path, evaluated_until="2025-12-31",
    )
    seen = []

    def recording_evaluation(returns, probabilities, **kwargs):
        seen.append(probabilities.index.copy())
        return metrics(net=float(probabilities.iloc[0]))

    monkeypatch.setattr(
        learning_loop, "evaluate_predictions", recording_evaluation
    )
    manager = EvolutionManager(store, registry, model_dir)
    result = manager.evaluate_shadow(
        "000001", evaluation_market(60, start="2026-01-01")
    )

    assert len(seen) == 2
    assert seen[0].equals(seen[1])
    assert seen[0].equals(store.completed_frame("000001").index)
    assert result["champion_version"] == "old"
```

Add this parametrized fail-closed test for a missing artifact and an
incompatible feature list:

```python
@pytest.mark.parametrize("invalid_kind", ["missing", "incompatible"])
def test_invalid_champion_artifact_blocks_shadow_promotion(
        tmp_path, invalid_kind):
    store = ExperienceStore(tmp_path / "test.db")
    registry = ModelRegistry(tmp_path / "test.db")
    model_dir = tmp_path / "models"
    dates = populate_completed_experiences(store, periods=60)
    cutoff = (dates[0] - pd.offsets.BDay(1)).isoformat()
    shadow_path = write_artifact(
        model_dir, "000001", "new", 0.7
    )
    if invalid_kind == "missing":
        champion_path = model_dir / "000001" / "old.joblib"
    else:
        champion_path = write_artifact(
            model_dir,
            "000001",
            "old",
            0.6,
            feature_names=("missing_feature",),
        )
    registry.register(
        "old", "000001", "CHAMPION", metrics().as_dict(),
        champion_path, evaluated_until=cutoff,
    )
    registry.register(
        "new", "000001", "SHADOW", metrics(net=0.11).as_dict(),
        shadow_path, evaluated_until=cutoff,
    )
    manager = EvolutionManager(store, registry, model_dir)
    result = manager.evaluate_shadow(
        "000001",
        evaluation_market(60, start=str(dates[0].date())),
    )

    assert result["promoted"] is False
    assert "old" in result["error"]
    assert registry.get("new")["status"] == "SHADOW"
```

- [ ] **Step 3: Run the focused tests and confirm RED**

Run: `pytest -q tests/test_learning_loop.py -k 'shadow_models_are_evaluated_on_identical_dates or shadow_model_must_pass_second_gate or invalid_champion'`

Expected: FAIL because `promote_if_ready` reads the Champion's old
`metrics_json` and `evaluate_shadow` does not load/evaluate the Champion.

- [ ] **Step 4: Add one validated artifact prediction helper**

Add this private method to `EvolutionManager`:

```python
    def _artifact_probabilities(self, record, frame):
        artifact_path = Path(record["artifact_path"]).resolve()
        if self.model_dir not in artifact_path.parents:
            raise ValueError(
                f"{record['version']} artifact path escapes model directory"
            )
        artifact = joblib.load(artifact_path)
        feature_names = list(artifact["feature_names"])
        missing = sorted(set(feature_names) - set(frame.columns))
        if missing:
            raise ValueError(
                f"{record['version']} artifact has incompatible features: "
                + ", ".join(missing)
            )
        features = frame.loc[:, feature_names].apply(
            pd.to_numeric, errors="coerce"
        ).fillna(0.0)
        values = np.asarray(
            artifact["model"].predict_proba(features)[:, 1],
            dtype=float,
        )
        if len(values) != len(frame) or not np.isfinite(values).all():
            raise ValueError(
                f"{record['version']} artifact returned invalid probabilities"
            )
        return pd.Series(values, index=frame.index)
```

This replaces the current inline Challenger artifact loading; do not add an
artifact/evaluator class hierarchy.

- [ ] **Step 5: Require contemporaneous metrics for promotion**

Change the signature and Champion branch:

```python
    def promote_if_ready(self, version, min_shadow_samples=50,
                         champion_metrics=None):
```

```python
        champion = self.registry.champion(candidate["symbol"])
        if champion:
            if champion_metrics is None:
                return False
            passed = self.gate.passes(
                shadow_metrics, champion_metrics
            )[0]
        else:
            passed = self.gate.passes_baseline(shadow_metrics)[0]
```

Never read `champion["metrics_json"]` in `promote_if_ready`.

- [ ] **Step 6: Evaluate both artifacts on one frame and fail closed**

Inside `evaluate_shadow`, after market validation:

```python
        champion = self.registry.champion(symbol)
        try:
            shadow_probabilities = self._artifact_probabilities(
                candidate, frame
            )
            shadow_metrics = evaluate_predictions(
                frame["horizon_return"],
                shadow_probabilities,
                market=market,
                symbol=symbol,
                folds=3,
                decision_features=frame,
            )
            champion_metrics = None
            if champion is not None:
                champion_probabilities = self._artifact_probabilities(
                    champion, frame
                )
                champion_metrics = evaluate_predictions(
                    frame["horizon_return"],
                    champion_probabilities,
                    market=market,
                    symbol=symbol,
                    folds=3,
                    decision_features=frame,
                )
        except Exception as exc:
            result["error"] = str(exc)
            return result
```

Then record only the Challenger's shadow metrics, expose audit fields, and
pass the contemporaneous Champion metrics into the gate:

```python
        result["challenger_metrics"] = shadow_metrics.as_dict()
        result["champion_version"] = (
            champion["version"] if champion is not None else None
        )
        result["champion_metrics"] = (
            champion_metrics.as_dict()
            if champion_metrics is not None else None
        )
        result["promoted"] = self.promote_if_ready(
            candidate["version"],
            min_shadow_samples,
            champion_metrics=champion_metrics,
        )
```

- [ ] **Step 7: Run learning-loop tests and confirm GREEN**

Run: `pytest -q tests/test_learning_loop.py`

Expected: PASS.

- [ ] **Step 8: Commit same-window promotion**

```bash
git add code/learning_loop.py tests/test_learning_loop.py
git diff --check --cached
git commit -m "fix: compare shadow models on the same window"
```

---

## Task 7: Verify the trusted path end to end

**Files:**

- Modify only if a regression is found: files already named in Tasks 1–6

- [ ] **Step 1: Run the focused trust suite**

Run:

```bash
pytest -q \
  tests/test_causal_ml.py \
  tests/test_portfolio_simulator.py \
  tests/test_backtest_integration.py \
  tests/test_learning_loop.py \
  tests/test_web_validation.py
```

Expected: PASS.

- [ ] **Step 2: Run the complete Python suite**

Run: `pytest -q tests`

Expected: all tests pass; the optional `hmmlearn` test may remain skipped when
that optional package is unavailable.

- [ ] **Step 3: Check frontend syntax**

Run: `node --check web/app.js`

Expected: exit code 0.

- [ ] **Step 4: Run a real-database research-proxy smoke test**

Run from the repository root:

```bash
PYTHONPATH=code python -c 'from backtest_kline_engine import KLineBacktestEngine; r=KLineBacktestEngine("data/ashare_quant.db").run_kline_backtest("600519", "2024-01-01", "2025-12-31", backtest_mode="RESEARCH_PROXY"); print({k:r.get(k) for k in ("error_code", "error")}); print(r.get("overall_metrics", {}))'
```

Expected: a finite, reconciled result with explicit `RESEARCH_PROXY`
limitations, or an expected fail-closed provenance/data error. It must not
silently claim a successful strict/raw/PIT backtest.

- [ ] **Step 5: Inspect scope and whitespace**

Run:

```bash
git diff --check
git status --short
git log --oneline -7
```

Expected: no whitespace errors; unrelated pre-existing changes remain present
and uncommitted; only the plan's files appear in the phase commits.

- [ ] **Step 6: Request final code review**

Review specifically for temporal leakage, accounting reconciliation,
same-window index equality, fail-closed artifact handling, and accidental
exposure of invalidated engines. Resolve only findings within this approved
phase, then rerun Steps 1–5.

## Completion Definition

The phase is complete only when every acceptance criterion in
`docs/superpowers/specs/2026-08-12-ml-strategy-trust-hardening-design.md` is
covered by a passing test, the complete suite and JavaScript syntax check are
green, the real-database smoke test is truthful/fail-closed, and no unrelated
dirty-worktree content has been staged or overwritten.
