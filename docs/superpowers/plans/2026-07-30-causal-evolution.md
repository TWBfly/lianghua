# Lianghua Causal Backtest and Safe Evolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a causal walk-forward backtest, one-account multi-stock simulator, persistent experience loop, and gated Champion/Challenger evolution while keeping SQLite and LightGBM.

**Architecture:** Keep `backtest_kline_engine.py` as the Web-facing orchestrator. Put deterministic account/order behavior in `portfolio_simulator.py`, and SQLite experience/model lifecycle behavior in `learning_loop.py`; repair causal ML in the existing `ml_ensemble.py` and signal files. Historical backtests use price/volume information only, trade at the next open, and write auditable decisions and outcomes.

**Tech Stack:** Python 3.10, pandas, NumPy, LightGBM, scikit-learn, SQLite, pytest.

## Global Constraints

- Keep SQLite as the only state store.
- Keep LightGBM as the first causal model; do not add dependencies.
- Do not implement PPO, SAC, contextual bandits, code-writing agents, microservices, or TradingView Markdown parsing.
- Historical decisions must not use current fundamentals, latest notices, news, or DeepSeek output.
- A prediction at time `t` may only use labels whose `label_end_time < t`.
- Signals are produced at close and orders are processed at the next open.
- Cash must never become negative; buy quantities are multiples of 100 shares.
- Model-controlled output cannot override risk limits.
- Existing `/api/run_backtest` and `/api/run_portfolio_backtest` response shapes remain compatible.
- The directory is not a Git repository. Replace commit checkpoints with a focused green pytest run and a file inventory check.

---

## File Map

- Modify `code/ml_ensemble.py`: causal labels, mature-label frame, expanding walk-forward LightGBM predictions, reproducible model metadata.
- Modify `code/tradingview_all_signals.py`: remove whole-period future-return feature selection.
- Modify `code/ashare_factor_pipeline.py`: remove target-driven row deletion from inference features and expose causal warm-up rows.
- Create `code/portfolio_simulator.py`: unified cash, positions, next-open orders, fees, limits, suspensions, risk stops, terminal liquidation.
- Create `code/learning_loop.py`: SQLite experience store, model registry, retrain trigger, evaluation metrics, promotion gate, evolution manager.
- Modify `code/backtest_kline_engine.py`: parameterized data loading, causal decisions, simulator orchestration, experience recording, response formatting.
- Modify `code/web_server.py`: validate symbols/dates/capital and pass optional portfolio symbols.
- Modify `code/deepseek_analyzer.py`: restore default TLS verification.
- Create `tests/conftest.py`: add `code/` to `sys.path`.
- Create `tests/test_causal_ml.py`: label maturity, prefix invariance, walk-forward causality.
- Create `tests/test_portfolio_simulator.py`: execution timing, cash, lot, shared account, limits, suspension, terminal close.
- Create `tests/test_learning_loop.py`: schema, idempotence, outcome updates, retrain trigger, promotion gate and atomic promotion.
- Create `tests/test_backtest_integration.py`: API-facing engine compatibility and small-capital regression.

---

### Task 1: Causal Labels and Signal Prefix Invariance

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_causal_ml.py`
- Modify: `code/ml_ensemble.py:64-148`
- Modify: `code/tradingview_all_signals.py:193-203`
- Modify: `code/ashare_factor_pipeline.py:21-101`

**Interfaces:**
- Produces: `build_label_frame(df_kline, forward_days=5, threshold=0.015) -> pd.DataFrame`
- Preserves: `build_labels(...) -> pd.Series`
- Produces: `causal_feature_frame(df_kline, df_factors) -> pd.DataFrame`
- Preserves: `TradingViewAllSignalsEngine.generate_all_signals(df) -> pd.DataFrame`

- [ ] **Step 1: Add the test import path**

```python
# tests/conftest.py
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parents[1] / "code"
sys.path.insert(0, str(CODE_DIR))
```

- [ ] **Step 2: Write failing maturity and prefix tests**

```python
# tests/test_causal_ml.py
import numpy as np
import pandas as pd

from ml_ensemble import build_label_frame, causal_feature_frame


def market_frame(rows=160):
    dates = pd.bdate_range("2025-01-01", periods=rows)
    close = 10 + np.arange(rows) * 0.03 + np.sin(np.arange(rows) / 5)
    return pd.DataFrame({
        "trade_date": dates.strftime("%Y-%m-%d"),
        "open": close - 0.02,
        "high": close + 0.10,
        "low": close - 0.10,
        "close": close,
        "volume": 1_000_000 + np.arange(rows) * 100,
        "amount": close * (1_000_000 + np.arange(rows) * 100),
        "pct_chg": pd.Series(close).pct_change().fillna(0).to_numpy() * 100,
    })


def factor_frame(df):
    index = pd.to_datetime(df["trade_date"])
    return pd.DataFrame({
        "rsi_14": np.linspace(40, 60, len(df)),
        "macd_hist": np.sin(np.arange(len(df)) / 8),
        "bias_20": np.zeros(len(df)),
    }, index=index)


def test_last_forward_window_labels_are_unknown():
    labels = build_label_frame(market_frame(20), forward_days=5)
    assert labels["label"].tail(5).isna().all()
    assert labels["label_end_time"].tail(5).isna().all()


def test_feature_prefix_does_not_change_when_future_rows_are_appended():
    short = market_frame(120)
    long = market_frame(160)
    short_features = causal_feature_frame(short, factor_frame(short))
    long_features = causal_feature_frame(long, factor_frame(long))
    pd.testing.assert_frame_equal(
        short_features,
        long_features.loc[short_features.index],
        check_dtype=False,
    )
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
python3 -m pytest tests/test_causal_ml.py -q
```

Expected: collection fails because `build_label_frame` and `causal_feature_frame` do not exist.

- [ ] **Step 4: Implement mature labels and causal features**

Add to `code/ml_ensemble.py`:

```python
def build_label_frame(df_kline: pd.DataFrame, forward_days: int = 5,
                      threshold: float = 0.015) -> pd.DataFrame:
    df = df_kline.copy()
    index = pd.to_datetime(df["trade_date"])
    close = pd.Series(df["close"].to_numpy(dtype=float), index=index).sort_index()
    future_close = close.shift(-forward_days)
    future_return = future_close / close - 1.0
    label = (future_return > threshold).astype(float)
    label[future_close.isna()] = np.nan
    end_time = pd.Series(close.index, index=close.index).shift(-forward_days)
    return pd.DataFrame({
        "label": label,
        "future_return": future_return,
        "label_end_time": pd.to_datetime(end_time),
    }, index=close.index)


def build_labels(df_kline: pd.DataFrame, forward_days: int = 5,
                 threshold: float = 0.015) -> pd.Series:
    return build_label_frame(df_kline, forward_days, threshold)["label"]


def causal_feature_frame(df_kline: pd.DataFrame,
                         df_factors: pd.DataFrame) -> pd.DataFrame:
    return build_features(df_kline, df_factors)
```

In `build_features`, replace future-capable factor alignment:

```python
aligned = df_factors[col].reindex(df.index)
```

Do not use `method="nearest"`.

In `TradingViewAllSignalsEngine.generate_all_signals`, replace lines 193-203 with:

```python
return signals.fillna(0)
```

In `AShareFactorPipeline.extract_factors`, return rows after feature calculation without using `target_5d_return` to drop inference rows:

```python
df["target_5d_return"] = (
    np.log(df["close"].shift(-5) / df["close"])
)
return df
```

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```bash
python3 -m pytest tests/test_causal_ml.py -q
```

Expected: `2 passed`.

- [ ] **Step 6: Checkpoint**

Run:

```bash
python3 -m compileall -q code
python3 -m pytest tests/test_causal_ml.py -q
```

Expected: both commands exit `0`.

---

### Task 2: Strict Walk-Forward LightGBM Predictions

**Files:**
- Modify: `tests/test_causal_ml.py`
- Modify: `code/ml_ensemble.py:151-370`

**Interfaces:**
- Produces: `walk_forward_splits(label_frame, prediction_index, min_train_size=120, retrain_every=5) -> list[WalkForwardSplit]`
- Produces: `walk_forward_predict(df_kline, df_factors, symbol, min_train_size=120, retrain_every=5, model_factory=None) -> pd.DataFrame`
- Result columns: `score`, `probability`, `model_version`, `trained_until`

- [ ] **Step 1: Write failing split-causality test**

Append:

```python
from ml_ensemble import walk_forward_splits


def test_walk_forward_training_labels_mature_before_prediction():
    labels = build_label_frame(market_frame(160))
    splits = walk_forward_splits(
        labels,
        labels.index,
        min_train_size=40,
        retrain_every=5,
    )
    assert splits
    for split in splits:
        mature = labels.loc[split.train_index, "label_end_time"]
        assert (mature < split.prediction_start).all()
        assert split.prediction_start <= split.prediction_end
```

- [ ] **Step 2: Verify RED**

Run:

```bash
python3 -m pytest tests/test_causal_ml.py::test_walk_forward_training_labels_mature_before_prediction -q
```

Expected: import fails because `walk_forward_splits` is missing.

- [ ] **Step 3: Implement split generation**

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class WalkForwardSplit:
    prediction_start: pd.Timestamp
    prediction_end: pd.Timestamp
    train_index: pd.DatetimeIndex
    prediction_index: pd.DatetimeIndex


def walk_forward_splits(label_frame, prediction_index,
                        min_train_size=120, retrain_every=5):
    dates = pd.DatetimeIndex(prediction_index).sort_values()
    result = []
    for start in range(0, len(dates), retrain_every):
        prediction_dates = dates[start:start + retrain_every]
        if prediction_dates.empty:
            continue
        mature = label_frame[
            label_frame["label"].notna()
            & (label_frame["label_end_time"] < prediction_dates[0])
        ]
        if len(mature) < min_train_size:
            continue
        result.append(WalkForwardSplit(
            prediction_start=prediction_dates[0],
            prediction_end=prediction_dates[-1],
            train_index=mature.index,
            prediction_index=prediction_dates,
        ))
    return result
```

- [ ] **Step 4: Verify split test GREEN**

Run:

```bash
python3 -m pytest tests/test_causal_ml.py::test_walk_forward_training_labels_mature_before_prediction -q
```

Expected: `1 passed`.

- [ ] **Step 5: Write failing integration test**

```python
from ml_ensemble import walk_forward_predict


def test_walk_forward_predictions_report_training_cutoff():
    df = market_frame(160)
    result = walk_forward_predict(
        df,
        factor_frame(df),
        "000001",
        min_train_size=40,
        retrain_every=10,
    )
    covered = result.dropna(subset=["trained_until"])
    assert not covered.empty
    assert (
        pd.to_datetime(covered["trained_until"])
        < covered.index
    ).all()
    assert covered["probability"].between(0, 1).all()
```

- [ ] **Step 6: Verify integration RED**

Run:

```bash
python3 -m pytest tests/test_causal_ml.py::test_walk_forward_predictions_report_training_cutoff -q
```

Expected: fails because `walk_forward_predict` is missing.

- [ ] **Step 7: Implement minimal walk-forward predictor**

Use one LightGBM model per split:

```python
def _default_model():
    return lgb.LGBMClassifier(
        n_estimators=100,
        learning_rate=0.05,
        max_depth=4,
        num_leaves=15,
        class_weight="balanced",
        random_state=42,
        verbose=-1,
    )


def walk_forward_predict(df_kline, df_factors, symbol,
                         min_train_size=120, retrain_every=5,
                         model_factory=None):
    features = causal_feature_frame(df_kline, df_factors).fillna(0)
    labels = build_label_frame(df_kline)
    result = pd.DataFrame(index=features.index, columns=[
        "score", "probability", "model_version", "trained_until",
    ])
    factory = model_factory or _default_model
    for split in walk_forward_splits(
        labels, features.index, min_train_size, retrain_every
    ):
        train_index = split.train_index.intersection(features.index)
        if labels.loc[train_index, "label"].nunique() < 2:
            continue
        model = factory()
        model.fit(
            features.loc[train_index].to_numpy(np.float32),
            labels.loc[train_index, "label"].astype(int).to_numpy(),
        )
        predict_index = split.prediction_index.intersection(features.index)
        probability = model.predict_proba(
            features.loc[predict_index].to_numpy(np.float32)
        )[:, 1]
        trained_until = labels.loc[train_index, "label_end_time"].max()
        version = hashlib.sha256(
            f"{symbol}|{trained_until.isoformat()}|{','.join(features.columns)}".encode()
        ).hexdigest()[:16]
        result.loc[predict_index, "probability"] = probability
        result.loc[predict_index, "score"] = probability * 10
        result.loc[predict_index, "model_version"] = version
        result.loc[predict_index, "trained_until"] = trained_until
    fallback = _rule_score(features) / 10
    result["probability"] = result["probability"].astype(float).fillna(fallback)
    result["score"] = result["score"].astype(float).fillna(fallback * 10)
    result["model_version"] = result["model_version"].fillna("causal-rule-v1")
    return result
```

Add `import hashlib`.

- [ ] **Step 8: Verify all causal ML tests**

Run:

```bash
python3 -m pytest tests/test_causal_ml.py -q
```

Expected: `4 passed`.

---

### Task 3: Unified Portfolio Simulator Core

**Files:**
- Create: `tests/test_portfolio_simulator.py`
- Create: `code/portfolio_simulator.py`

**Interfaces:**
- Produces: `RiskLimits`
- Produces: `FeeSchedule`
- Produces: `simulate_portfolio(market, decisions, initial_cash, risk_limits=None, fees=None) -> SimulationResult`
- `market`: `dict[str, pd.DataFrame]`, indexed by trade date with OHLCV.
- `decisions`: columns `decision_time`, `symbol`, `action`, `target_fraction`, `reason`, `model_version`, `features_json`.

- [ ] **Step 1: Write failing next-open and cash tests**

```python
# tests/test_portfolio_simulator.py
import pandas as pd

from portfolio_simulator import simulate_portfolio


def bars(opens, closes=None, volumes=None):
    closes = closes or opens
    volumes = volumes or [1_000_000] * len(opens)
    dates = pd.bdate_range("2026-01-05", periods=len(opens))
    return pd.DataFrame({
        "open": opens,
        "high": [max(o, c) * 1.01 for o, c in zip(opens, closes)],
        "low": [min(o, c) * 0.99 for o, c in zip(opens, closes)],
        "close": closes,
        "volume": volumes,
    }, index=dates)


def decision(date, symbol="000001", action="BUY", fraction=0.5):
    return {
        "decision_time": pd.Timestamp(date),
        "symbol": symbol,
        "action": action,
        "target_fraction": fraction,
        "reason": "test",
        "model_version": "v1",
        "features_json": "{}",
    }


def test_close_signal_fills_at_next_open():
    frame = bars([10, 11, 12])
    result = simulate_portfolio(
        {"000001": frame},
        pd.DataFrame([decision(frame.index[0])]),
        initial_cash=100_000,
    )
    fill = result.fills[0]
    assert fill["fill_time"] == frame.index[1]
    assert fill["raw_price"] == 11


def test_insufficient_cash_is_rejected_without_negative_cash():
    frame = bars([1_500, 1_500, 1_500])
    result = simulate_portfolio(
        {"600519": frame},
        pd.DataFrame([decision(frame.index[0], "600519", fraction=0.9)]),
        initial_cash=1_000,
    )
    assert result.rejected_orders[0]["reason"] == "INSUFFICIENT_CASH"
    assert min(point["cash"] for point in result.equity_curve) >= 0
```

- [ ] **Step 2: Verify RED**

Run:

```bash
python3 -m pytest tests/test_portfolio_simulator.py -q
```

Expected: collection fails because `portfolio_simulator` is missing.

- [ ] **Step 3: Implement dataclasses and fee calculation**

```python
# code/portfolio_simulator.py
from dataclasses import dataclass, field
import math
import pandas as pd


@dataclass(frozen=True)
class FeeSchedule:
    commission_rate: float = 0.00025
    min_commission: float = 5.0
    stamp_duty_rate: float = 0.0005
    transfer_fee_rate: float = 0.00001
    slippage_rate: float = 0.001


@dataclass(frozen=True)
class RiskLimits:
    max_position_fraction: float = 0.20
    max_gross_exposure: float = 0.90
    daily_loss_limit: float = 0.03
    max_drawdown: float = 0.10


@dataclass
class Position:
    shares: int
    average_cost: float
    entry_time: pd.Timestamp
    peak_price: float


@dataclass
class SimulationResult:
    initial_cash: float
    final_equity: float
    fills: list[dict] = field(default_factory=list)
    rejected_orders: list[dict] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)
    positions: dict[str, Position] = field(default_factory=dict)
```

Implement `_buy_cost`, `_sell_proceeds`, `_limit_fraction`, lot rounding, pending-next-date lookup, and `simulate_portfolio`. Process orders before generating that date's decisions. Reject rather than borrowing.

- [ ] **Step 4: Verify initial simulator tests GREEN**

Run:

```bash
python3 -m pytest tests/test_portfolio_simulator.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Add failing shared-account, lot, limit and suspension tests**

Append tests that assert:

```python
def test_two_symbols_share_one_cash_balance():
    frame = bars([10, 10, 10])
    decisions = pd.DataFrame([
        decision(frame.index[0], "000001", fraction=0.9),
        decision(frame.index[0], "000002", fraction=0.9),
    ])
    result = simulate_portfolio(
        {"000001": frame, "000002": frame},
        decisions,
        initial_cash=100_000,
    )
    assert all(fill["shares"] % 100 == 0 for fill in result.fills)
    assert min(point["cash"] for point in result.equity_curve) >= 0
    assert sum(fill["gross_value"] for fill in result.fills
               if fill["side"] == "BUY") <= 90_000


def test_suspended_and_limit_locked_orders_are_rejected():
    dates = pd.bdate_range("2026-01-05", periods=3)
    suspended = bars([10, 10, 10], volumes=[1_000_000, 0, 1_000_000])
    limit_up = bars([10, 11, 11])
    decisions = pd.DataFrame([
        decision(dates[0], "000001"),
        decision(dates[0], "000002"),
    ])
    result = simulate_portfolio(
        {"000001": suspended, "000002": limit_up},
        decisions,
        initial_cash=100_000,
    )
    reasons = {item["symbol"]: item["reason"]
               for item in result.rejected_orders}
    assert reasons == {
        "000001": "SUSPENDED",
        "000002": "LIMIT_UP",
    }
```

- [ ] **Step 6: Verify RED, implement constraints, verify GREEN**

Run before implementation:

```bash
python3 -m pytest tests/test_portfolio_simulator.py -q
```

Expected: new tests fail on exposure/constraint behavior.

Implement:

- `ST` name support through an optional `names` mapping.
- 5/10/20/30 percent price limits.
- Missing row or `volume <= 0` rejection.
- Gross exposure calculated from current open.
- Stable order priority by `(execution_time, decision_time, symbol)`.

Run again; expected: `4 passed`.

- [ ] **Step 7: Add and satisfy terminal liquidation test**

```python
def test_terminal_day_liquidates_all_positions_with_fees():
    frame = bars([10, 10, 12])
    result = simulate_portfolio(
        {"000001": frame},
        pd.DataFrame([decision(frame.index[0])]),
        initial_cash=100_000,
    )
    assert result.positions == {}
    assert result.trades[-1]["exit_reason"] == "TERMINAL_LIQUIDATION"
    assert result.trades[-1]["sell_fees"] > 0
    assert result.final_equity == result.equity_curve[-1]["equity"]
```

Run RED, implement close-price terminal liquidation with sell slippage and fees, run GREEN.

Checkpoint:

```bash
python3 -m pytest tests/test_portfolio_simulator.py -q
```

Expected: `5 passed`.

---

### Task 4: Persistent Experience Store and Retrain Trigger

**Files:**
- Create: `tests/test_learning_loop.py`
- Create: `code/learning_loop.py`

**Interfaces:**
- Produces: `ExperienceStore(db_path)`
- Produces: `record_decision`, `record_order_result`, `complete_horizon`, `complete_trade`
- Produces: `completed_since(symbol, since) -> int`
- Produces: `retrain_due(symbol, now, completed_threshold=50, interval_days=7) -> bool`

- [ ] **Step 1: Write failing schema and idempotence tests**

```python
# tests/test_learning_loop.py
from datetime import datetime, timedelta
import sqlite3

from learning_loop import ExperienceStore


def sample_decision(decision_id="d1"):
    return {
        "decision_id": decision_id,
        "run_id": "run-1",
        "decision_time": "2026-01-05",
        "symbol": "000001",
        "features": {"ret_1d": 0.01},
        "model_version": "v1",
        "action": "BUY",
        "desired_shares": 100,
    }


def test_experience_write_is_idempotent(tmp_path):
    store = ExperienceStore(tmp_path / "test.db")
    store.record_decision(sample_decision())
    store.record_decision(sample_decision())
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM experiences"
        ).fetchone()[0] == 1


def test_outcomes_can_be_completed_by_horizon_and_trade(tmp_path):
    store = ExperienceStore(tmp_path / "test.db")
    store.record_decision(sample_decision())
    store.complete_horizon("d1", 0.02, 0.04, -0.01)
    store.complete_trade("d1", 0.015, "2026-01-12", 10.5)
    row = store.get("d1")
    assert row["completed"] == 1
    assert row["horizon_return"] == 0.02
    assert row["trade_return"] == 0.015
    assert row["reward"] == 0.015 - 0.25 * 0.01
```

- [ ] **Step 2: Verify RED**

Run:

```bash
python3 -m pytest tests/test_learning_loop.py -q
```

Expected: import fails because `learning_loop` is missing.

- [ ] **Step 3: Implement SQLite schema and methods**

Use `sqlite3`, JSON with sorted keys, SHA-256 feature hashes, parameterized SQL, and `INSERT ... ON CONFLICT(decision_id) DO NOTHING`.

Create indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_experience_symbol_completed
ON experiences(symbol, completed, decision_time);
CREATE INDEX IF NOT EXISTS idx_experience_run
ON experiences(run_id, decision_time);
```

`complete_horizon` must not mark a filled/open trade complete until `complete_trade`; HOLD and rejected decisions become complete at horizon.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
python3 -m pytest tests/test_learning_loop.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Write failing retrain trigger tests**

```python
def test_retrain_due_after_50_completed_experiences(tmp_path):
    store = ExperienceStore(tmp_path / "test.db")
    for i in range(50):
        item = sample_decision(f"d{i}")
        item["action"] = "HOLD"
        store.record_decision(item)
        store.complete_horizon(f"d{i}", 0.01, 0.02, -0.01)
    assert store.retrain_due(
        "000001", datetime(2026, 1, 6),
        completed_threshold=50, interval_days=7,
    )


def test_retrain_due_after_seven_days_with_new_experience(tmp_path):
    store = ExperienceStore(tmp_path / "test.db")
    store.record_training("000001", "v1", datetime(2026, 1, 1))
    item = sample_decision()
    item["action"] = "HOLD"
    store.record_decision(item)
    store.complete_horizon("d1", 0.01, 0.02, -0.01)
    assert store.retrain_due("000001", datetime(2026, 1, 8))
```

- [ ] **Step 6: Verify RED, implement trigger, verify GREEN**

Implement a `training_events` table and compare completed decision timestamps with the latest event. Expected final result: `4 passed`.

---

### Task 5: Model Registry, Evaluation, Shadow and Atomic Promotion

**Files:**
- Modify: `tests/test_learning_loop.py`
- Modify: `code/learning_loop.py`

**Interfaces:**
- Produces: `EvaluationMetrics`
- Produces: `PromotionGate.passes(challenger, champion) -> tuple[bool, list[str]]`
- Produces: `ModelRegistry`
- Produces: `EvolutionManager.maybe_train(symbol, now) -> str | None`
- Produces: `EvolutionManager.promote_if_ready(version) -> bool`

- [ ] **Step 1: Write failing promotion-gate tests**

```python
from learning_loop import EvaluationMetrics, PromotionGate


def metrics(net=0.10, drawdown=0.05, turnover=0.20,
            brier=0.20, folds=3, hit_kill_switch=False):
    return EvaluationMetrics(
        net_return=net,
        max_drawdown=drawdown,
        turnover=turnover,
        brier_score=brier,
        folds=folds,
        hit_kill_switch=hit_kill_switch,
    )


def test_challenger_must_pass_every_gate():
    gate = PromotionGate()
    champion = metrics()
    assert gate.passes(metrics(net=0.11), champion)[0]
    assert not gate.passes(metrics(net=0.09), champion)[0]
    assert not gate.passes(metrics(drawdown=0.06), champion)[0]
    assert not gate.passes(metrics(turnover=0.23), champion)[0]
    assert not gate.passes(metrics(brier=0.21), champion)[0]
    assert not gate.passes(metrics(folds=2), champion)[0]
    assert not gate.passes(
        metrics(hit_kill_switch=True), champion
    )[0]
```

- [ ] **Step 2: Verify RED, implement `EvaluationMetrics` and `PromotionGate`, verify GREEN**

The turnover threshold is `champion.turnover * 1.10`; all other relative metrics must not degrade, and folds must be at least 3.

- [ ] **Step 3: Write failing registry transaction tests**

```python
from learning_loop import ModelRegistry


def test_promotion_requires_shadow_samples_and_retires_old_champion(tmp_path):
    registry = ModelRegistry(tmp_path / "test.db")
    registry.register(
        "old", "000001", "CHAMPION", metrics().as_dict(), "old.joblib"
    )
    registry.register(
        "new", "000001", "SHADOW", metrics(net=0.11).as_dict(),
        "new.joblib",
    )
    assert not registry.promote("new", min_shadow_samples=50)
    registry.add_shadow_samples("new", 50)
    assert registry.promote("new", min_shadow_samples=50)
    assert registry.get("new")["status"] == "CHAMPION"
    assert registry.get("old")["status"] == "RETIRED"
```

- [ ] **Step 4: Verify RED, implement registry, verify GREEN**

Use one SQLite transaction with `BEGIN IMMEDIATE`, retire the old Champion, promote the selected row, then commit. Roll back on any exception.

- [ ] **Step 5: Write failing rolling-evaluation test**

Use a deterministic 180-row feature dataset and assert evaluation returns at least three non-overlapping time folds, finite Brier score, actual compounded return, computed drawdown and turnover.

- [ ] **Step 6: Implement minimal `EvolutionManager`**

Behavior:

1. Query completed experiences for a symbol.
2. Require 120 rows and a retrain trigger.
3. Expand `features_json` into numeric columns.
4. Use `horizon_return > 0.015` as the classification label.
5. Evaluate three chronological folds; train only on rows before each validation fold.
6. Estimate policy return as:

```python
position = (probability >= 0.55).astype(float)
strategy_return = position * (horizon_return - 0.0015)
```

7. Calculate turnover from absolute position changes, Brier score and compounded equity drawdown.
8. Fit the final LightGBM model on all mature rows.
9. Save under `data/ml_models/evolution/<symbol>/<version>.joblib`.
10. Register as `CHALLENGER`; move to `SHADOW` only when the offline gate passes.
11. Never replace the Champion inside `maybe_train`.

- [ ] **Step 7: Verify learning-loop suite**

Run:

```bash
python3 -m pytest tests/test_learning_loop.py -q
```

Expected: all tests pass.

---

### Task 6: Integrate Causal Single-Stock Backtest

**Files:**
- Create: `tests/test_backtest_integration.py`
- Modify: `code/backtest_kline_engine.py:27-469`

**Interfaces:**
- Preserves: `KLineBacktestEngine.run_kline_backtest(...) -> dict`
- Adds optional: `persist_experiences=True`
- Uses: `walk_forward_predict`, `simulate_portfolio`, `ExperienceStore`

- [ ] **Step 1: Write failing synthetic integration test**

Create a temporary SQLite DB with `stock_daily` and `stock_basic`, insert 180 deterministic rows, then:

```python
def test_single_stock_backtest_is_causal_and_closes_positions(tmp_path):
    db_path = build_test_db(tmp_path)
    result = KLineBacktestEngine(db_path).run_kline_backtest(
        "000001",
        "2025-01-01",
        "2025-12-31",
        100_000,
        skip_ai=True,
    )
    assert "error" not in result
    assert result["metrics"]["final_equity"] >= 0
    assert result["open_positions"] == {}
    assert result["model_versions"]
    assert all(
        pd.Timestamp(item["trained_until"]) < pd.Timestamp(item["prediction_time"])
        for item in result["model_versions"]
        if item["trained_until"]
    )
```

- [ ] **Step 2: Write small-capital regression test**

```python
def test_small_capital_rejects_unaffordable_lot_without_crashing(tmp_path):
    db_path = build_test_db(tmp_path, price=1_500)
    result = KLineBacktestEngine(db_path).run_kline_backtest(
        "600519", "2025-01-01", "2025-12-31", 1_000, skip_ai=True,
    )
    assert "error" not in result
    assert result["metrics"]["final_equity"] == 1_000
    assert result["metrics"]["total_return_pct"] == 0
    assert result["rejected_orders"]
```

- [ ] **Step 3: Verify RED**

Run:

```bash
python3 -m pytest tests/test_backtest_integration.py -q
```

Expected: failures because the engine still executes same-close trades and forces 100 shares.

- [ ] **Step 4: Replace single-stock orchestration**

Keep data query and response formatting, but:

- Validate symbol/date input.
- Parameterize all SQL.
- Do not call `audit_financial_quality`, current notice lookup or DeepSeek in the historical decision loop.
- Calculate factors without backfill.
- Call `walk_forward_predict`.
- Create one decision row per trading date:
  - `BUY` when causal MACD/RSI/trend rule passes and ML probability is at least `0.55`.
  - `SELL` when ML probability is below `0.38` or causal MACD death cross occurs.
  - Otherwise `HOLD`.
- Pass decisions to the simulator.
- Convert simulator fills/trades/equity into existing `metrics`, `category_dates`, `kline_chart_data`, and `trades`.
- Include `open_positions`, `rejected_orders`, `model_versions`, `run_id`, and `experience_stats`.
- Store every decision, then fill and horizon/trade outcomes in `ExperienceStore`.

- [ ] **Step 5: Verify GREEN**

Run:

```bash
python3 -m pytest tests/test_backtest_integration.py -q
```

Expected: `2 passed`.

---

### Task 7: Integrate True Multi-Stock Portfolio Backtest

**Files:**
- Modify: `tests/test_backtest_integration.py`
- Modify: `code/backtest_kline_engine.py:471-600`
- Modify: `code/web_server.py:113-131`

**Interfaces:**
- Preserves: `run_portfolio_backtest(initial_capital, start_date, end_date) -> dict`
- Adds: `symbols: list[str] | None = None`

- [ ] **Step 1: Write failing shared-account engine test**

Create two symbols with overlapping BUY dates and assert:

```python
def test_portfolio_engine_uses_one_account_and_real_drawdown(tmp_path):
    db_path = build_multi_symbol_db(tmp_path)
    result = KLineBacktestEngine(db_path).run_portfolio_backtest(
        100_000,
        "2025-01-01",
        "2025-12-31",
        symbols=["000001", "000002"],
    )
    metrics = result["portfolio_metrics"]
    assert metrics["final_equity"] == result["equity_curve"][-1]["equity"]
    assert metrics["overall_max_dd_pct"] != 6.85
    assert sum(
        item["safe_allocation_pct"]
        for item in result["allocations"]
    ) <= 90
    assert min(point["cash"] for point in result["equity_curve"]) >= 0
```

- [ ] **Step 2: Verify RED**

Expected: hardcoded drawdown and missing unified equity curve fail.

- [ ] **Step 3: Replace scaled single-stock aggregation**

Implementation:

1. Load all selected symbols into one `market` dictionary.
2. Build causal predictions and decisions independently per symbol.
3. Concatenate decisions and call `simulate_portfolio` once.
4. Use equal target fractions capped by 20% per symbol and 90% total.
5. Compute final equity, returns, yearly PnL, win rate, profit/loss ratio and max drawdown from unified trades/equity.
6. Remove Kelly scaling and the `6.85` constant.
7. Return existing keys plus `equity_curve`, `rejected_orders`, `allocations`, `experience_stats`, and `evolution_status`.
8. If symbols are omitted, choose up to 12 symbols with rows on or before `start_date`; do not filter with current PE/PB/market cap.

- [ ] **Step 4: Update API validation**

In `web_server.py`, accept `symbols` only as a list of at most 20 six-digit strings, and pass it through.

- [ ] **Step 5: Verify GREEN**

Run:

```bash
python3 -m pytest tests/test_backtest_integration.py -q
```

Expected: all integration tests pass.

---

### Task 8: Input Security, TLS and Historical-Path Audit

**Files:**
- Modify: `tests/test_backtest_integration.py`
- Modify: `code/web_server.py`
- Modify: `code/deepseek_analyzer.py`
- Modify: `code/deepseek_quant_copilot.py`

**Interfaces:**
- Produces: `validate_backtest_request(data, portfolio=False) -> dict`

- [ ] **Step 1: Write failing validation tests**

Cover:

- symbol must match `^\d{6}$`;
- dates parse as `%Y-%m-%d`;
- start date is not after end date;
- capital is finite and positive;
- portfolio symbol list has at most 20 entries.

- [ ] **Step 2: Verify RED, implement validator, verify GREEN**

Use `datetime.strptime`, `math.isfinite`, and compiled regular expressions. Routes return HTTP 400 with the validation error.

- [ ] **Step 3: Restore TLS verification**

Delete both uses of `ssl._create_unverified_context()` and call `urllib.request.urlopen` without a custom context.

- [ ] **Step 4: Add historical-path static test**

Read only the specific function source through `inspect.getsource` and assert:

```python
assert ".bfill(" not in source
assert "method='nearest'" not in source
assert "overall_max_dd_pct\": 6.85" not in source
```

Do not assert implementation formatting outside these banned behaviors.

- [ ] **Step 5: Verify security and integration tests**

Run:

```bash
python3 -m pytest tests/test_backtest_integration.py -q
```

Expected: all pass.

---

### Task 9: Wire Automatic Challenger Creation Without Automatic Promotion

**Files:**
- Modify: `tests/test_backtest_integration.py`
- Modify: `code/backtest_kline_engine.py`
- Modify: `code/learning_loop.py`

**Interfaces:**
- `EvolutionManager.run_after_backtest(symbols, now) -> list[dict]`

- [ ] **Step 1: Write failing lifecycle integration test**

Populate 120 mature experiences for one symbol, run `run_after_backtest`, and assert:

- one model version is registered;
- status is `CHALLENGER` or `SHADOW`;
- no unverified version becomes Champion;
- artifact path is within `data/ml_models/evolution`;
- `trained_until`, feature hash and metrics exist.

- [ ] **Step 2: Verify RED**

Expected: `run_after_backtest` is missing.

- [ ] **Step 3: Implement post-run evolution hook**

For every symbol:

1. Check `retrain_due`.
2. Train/evaluate the candidate.
3. Register it.
4. If offline gate passes, mark it `SHADOW`.
5. During future backtests, record shadow probabilities and mature shadow outcomes.
6. Call `promote_if_ready` only after 50 shadow samples.
7. Catch training errors per symbol and return an error status without affecting backtest output or the current Champion.

- [ ] **Step 4: Call hook after experience outcomes are finalized**

Expose returned rows in `evolution_status`; do not use a newly created model in the same historical run.

- [ ] **Step 5: Verify lifecycle test GREEN**

Run focused and full suites.

---

### Task 10: Full Verification and Requirement Audit

**Files:**
- Verify all modified and created files.

- [ ] **Step 1: Run the complete test suite**

```bash
python3 -m pytest tests -q
```

Expected: all tests pass with no warnings from project code.

- [ ] **Step 2: Compile all Python files**

```bash
python3 -m compileall -q code tests
```

Expected: exit `0`.

- [ ] **Step 3: Run leakage and hardcode searches**

```bash
rg -n '\.bfill\(|method=.nearest.|future_ret.*filter_features|overall_max_dd_pct.: 6\.85|_create_unverified_context' code
```

Expected: no matches in active historical execution paths. Legacy unused files may only remain if explicitly marked and not imported by Web paths; otherwise remove the offending code.

- [ ] **Step 4: Run a real-data read-only smoke backtest**

Copy `data/ashare_quant.db` to a temporary directory, point the engine at the copy, and run:

```bash
PYTHONPATH=code python3 -c "
from backtest_kline_engine import KLineBacktestEngine
r = KLineBacktestEngine('/tmp/lianghua-smoke.db').run_kline_backtest(
    '600519', '2024-01-01', '2026-07-28', 1_000_000, skip_ai=True
)
assert 'error' not in r
assert r['metrics']['final_equity'] >= 0
assert not r['open_positions']
print(r['metrics'])
"
```

Expected: exit `0`, nonnegative cash/equity, zero open positions.

- [ ] **Step 5: Run the small-capital real-data regression**

Run the same copied DB with `initial_capital=1_000`. Expected: no exception, no filled unaffordable lot, final equity `1_000`.

- [ ] **Step 6: Inspect SQLite lifecycle state**

Query the copied DB:

```sql
SELECT COUNT(*) FROM experiences;
SELECT status, COUNT(*) FROM model_versions GROUP BY status;
SELECT MIN(completed), MAX(completed) FROM experiences;
```

Expected: experiences exist; model statuses are valid enum values; completion values are `0` or `1`.

- [ ] **Step 7: Review spec coverage**

Check every acceptance criterion in `docs/superpowers/specs/2026-07-30-causal-evolution-design.md` against a passing test or smoke output. Report any unmet item instead of claiming completion.

- [ ] **Step 8: Local checkpoint**

Run:

```bash
rg --files code tests docs/superpowers | sort
```

Record the touched-file inventory in the final handoff. Git commit is unavailable because the project has no `.git` repository.
