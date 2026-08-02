# Rolling Validation Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make fixed-window causal walk-forward evaluation the only historical ML path, fail closed on insufficient samples, and make model promotion continuous, holdout-based, and reproducible.

**Architecture:** Reuse the existing `ml_ensemble` split and prediction flow, the existing shared-account simulator, and the existing SQLite model registry. Add only policy constants, one canonical model-identity helper, explicit insufficient-history states, one registry cutoff for consumed holdout data, and a current-snapshot-only legacy fit method.

**Tech Stack:** Python 3.11, pandas, NumPy, LightGBM, scikit-learn, SQLite, pytest.

## Global Constraints

- Random train/test splitting is prohibited.
- Default mature-label training window is exactly 504 rows.
- Default label horizon and purge boundary are 5 trading days.
- Default retraining step is 21 trading days.
- Final holdout is the last 252 completed observations.
- Insufficient history produces `HOLD`, never a heuristic probability labelled as ML.
- No new dependency, model family, Web UI tuning control, or inferred point-in-time data.
- Strict provenance behavior remains unchanged.
- Existing user-owned uncommitted edits must not be reverted, overwritten wholesale, staged, or committed. Implementation tasks end with verified unstaged checkpoints because the target files already contain user changes.

---

### Task 1: Fixed-Window Splits and Fail-Closed Predictions

**Files:**
- Modify: `code/ml_ensemble.py:1-263`
- Test: `tests/test_causal_ml.py`

**Interfaces:**
- Consumes: existing `build_label_frame`, `WalkForwardSplit`, and `_default_causal_model`.
- Produces: `TRAINING_WINDOW`, `RETRAIN_EVERY`, `LABEL_HORIZON`, `LABEL_THRESHOLD`, `walk_forward_splits(..., max_train_size=504)`, and fail-closed `walk_forward_predict` rows.

- [ ] **Step 1: Write failing split and insufficient-history tests**

Add these tests to `tests/test_causal_ml.py`:

```python
from ml_ensemble import (
    LABEL_HORIZON,
    RETRAIN_EVERY,
    TRAINING_WINDOW,
)


def test_default_walk_forward_uses_latest_fixed_training_window():
    labels = build_label_frame(market_frame(800))
    splits = walk_forward_splits(labels, labels.index)

    assert splits
    assert len(splits[0].train_index) == TRAINING_WINDOW == 504
    assert (
        labels.loc[splits[0].train_index, "label_end_time"]
        < splits[0].prediction_start
    ).all()
    mature = labels[
        labels["label"].notna()
        & (labels["label_end_time"] < splits[0].prediction_start)
    ]
    assert splits[0].train_index.equals(mature.index[-TRAINING_WINDOW:])
    assert LABEL_HORIZON == 5


def test_default_prediction_batches_advance_twenty_one_rows():
    labels = build_label_frame(market_frame(800))
    splits = walk_forward_splits(labels, labels.index)

    assert RETRAIN_EVERY == 21
    assert len(splits[0].prediction_index) == RETRAIN_EVERY
    assert splits[1].prediction_start == labels.index[
        labels.index.get_loc(splits[0].prediction_start) + RETRAIN_EVERY
    ]


def test_insufficient_history_never_uses_rule_fallback():
    df = market_frame(TRAINING_WINDOW)
    result = walk_forward_predict(df, factor_frame(df), "000001")

    assert result["probability"].isna().all()
    assert result["score"].isna().all()
    assert set(result["model_version"]) == {"INSUFFICIENT_HISTORY"}
    assert result["trained_until"].isna().all()


def test_walk_forward_rejects_invalid_policy_values():
    labels = build_label_frame(market_frame(20))

    with pytest.raises(ValueError, match="min_train_size"):
        walk_forward_splits(labels, labels.index, min_train_size=0)
    with pytest.raises(ValueError, match="retrain_every"):
        walk_forward_splits(labels, labels.index, retrain_every=0)
    with pytest.raises(ValueError, match="max_train_size"):
        walk_forward_splits(
            labels,
            labels.index,
            min_train_size=10,
            max_train_size=9,
        )
```

Also change the existing probability assertion to cover only trained rows:

```python
assert covered["probability"].between(0, 1).all()
assert (
    result.loc[result["trained_until"].isna(), "model_version"]
    == "INSUFFICIENT_HISTORY"
).all()
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
PYTHONPATH=code python3 -m pytest tests/test_causal_ml.py -q
```

Expected: collection/import failure for the missing constants or assertion failures showing the current 120-row expanding window and rule fallback.

- [ ] **Step 3: Implement the minimum fixed-window policy**

Add policy constants near the imports in `code/ml_ensemble.py`:

```python
TRAINING_WINDOW = 504
RETRAIN_EVERY = 21
LABEL_HORIZON = 5
LABEL_THRESHOLD = 0.015
MODEL_POLICY_VERSION = "fixed-window-walk-forward-v1"
```

Change `walk_forward_splits` to validate inputs and keep only the newest mature rows:

```python
def walk_forward_splits(label_frame: pd.DataFrame,
                        prediction_index: pd.DatetimeIndex,
                        min_train_size: int = TRAINING_WINDOW,
                        retrain_every: int = RETRAIN_EVERY,
                        max_train_size: int = TRAINING_WINDOW) -> list:
    if min_train_size < 1:
        raise ValueError("min_train_size must be positive")
    if retrain_every < 1:
        raise ValueError("retrain_every must be positive")
    if max_train_size < min_train_size:
        raise ValueError("max_train_size must be >= min_train_size")
    dates = pd.DatetimeIndex(prediction_index).sort_values()
    splits = []
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
        mature = mature.iloc[-max_train_size:]
        splits.append(WalkForwardSplit(
            prediction_start=prediction_dates[0],
            prediction_end=prediction_dates[-1],
            train_index=pd.DatetimeIndex(mature.index),
            prediction_index=prediction_dates,
        ))
    return splits
```

Change `walk_forward_predict` defaults, label construction, and initial status:

```python
def walk_forward_predict(df_kline: pd.DataFrame,
                         df_factors: pd.DataFrame,
                         symbol: str,
                         min_train_size: int = TRAINING_WINDOW,
                         retrain_every: int = RETRAIN_EVERY,
                         max_train_size: int = TRAINING_WINDOW,
                         forward_days: int = LABEL_HORIZON,
                         threshold: float = LABEL_THRESHOLD,
                         model_factory=None) -> pd.DataFrame:
    features = causal_feature_frame(df_kline, df_factors).fillna(0)
    labels = build_label_frame(df_kline, forward_days, threshold)
    result = pd.DataFrame(index=features.index)
    result["score"] = np.nan
    result["probability"] = np.nan
    result["model_version"] = "INSUFFICIENT_HISTORY"
    result["trained_until"] = pd.NaT
    factory = model_factory or _default_causal_model

    for split in walk_forward_splits(
        labels,
        features.index,
        min_train_size,
        retrain_every,
        max_train_size,
    ):
        train_index = split.train_index.intersection(features.index)
        target = labels.loc[train_index, "label"].astype(int)
        prediction_index = split.prediction_index.intersection(features.index)
        if target.nunique() < 2:
            result.loc[
                prediction_index, "model_version"
            ] = "INSUFFICIENT_CLASS_VARIATION"
            continue
        # Existing model fitting and probability assignment remain here.
```

Delete `_rule_score` and all `fillna(fallback)` assignments.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
PYTHONPATH=code python3 -m pytest tests/test_causal_ml.py -q
```

Expected: all tests in `tests/test_causal_ml.py` pass.

- [ ] **Step 5: Record an unstaged safety checkpoint**

Run:

```bash
git diff --check -- code/ml_ensemble.py tests/test_causal_ml.py
git status --short -- code/ml_ensemble.py tests/test_causal_ml.py
```

Expected: no whitespace errors; both files remain unstaged because they contain pre-existing user changes.

---

### Task 2: Canonical Model Identity

**Files:**
- Modify: `code/ml_ensemble.py`
- Modify: `code/learning_loop.py:630-741`
- Test: `tests/test_causal_ml.py`
- Test: `tests/test_learning_loop.py`

**Interfaces:**
- Consumes: fixed-window constants from Task 1 and estimators exposing `get_params()`.
- Produces: `build_model_identity(...) -> str`, used by walk-forward rows and evolution artifacts.

- [ ] **Step 1: Write failing identity tests**

Add to `tests/test_causal_ml.py`:

```python
from ml_ensemble import build_model_identity


def test_model_identity_changes_with_data_parameters_and_policy():
    features = pd.DataFrame({"x": [1.0, 2.0]})
    target = pd.Series([0, 1])

    class Model:
        def __init__(self, depth=2):
            self.depth = depth

        def get_params(self, deep=False):
            return {"depth": self.depth}

    base = build_model_identity(
        "000001", pd.Timestamp("2025-01-01"), features, target,
        Model(), {"training_window": 504},
    )
    changed_data = build_model_identity(
        "000001", pd.Timestamp("2025-01-01"), features * 2, target,
        Model(), {"training_window": 504},
    )
    changed_model = build_model_identity(
        "000001", pd.Timestamp("2025-01-01"), features, target,
        Model(depth=3), {"training_window": 504},
    )
    changed_policy = build_model_identity(
        "000001", pd.Timestamp("2025-01-01"), features, target,
        Model(), {"training_window": 252},
    )

    assert len(base) == 16
    assert len({base, changed_data, changed_model, changed_policy}) == 4
```

Add an evolution assertion to the existing artifact test in
`tests/test_learning_loop.py`:

```python
artifact = joblib.load(registry.get(version)["artifact_path"])
assert artifact["model_policy_version"] == MODEL_POLICY_VERSION
assert artifact["model_version"] == version
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
PYTHONPATH=code python3 -m pytest tests/test_causal_ml.py tests/test_learning_loop.py -q
```

Expected: import failure because `build_model_identity` does not exist, followed by missing artifact identity fields after the helper is introduced.

- [ ] **Step 3: Implement canonical identity and use it in both trainers**

Add to `code/ml_ensemble.py`:

```python
import json


def build_model_identity(symbol, trained_until, features, target,
                         model, policy):
    metadata = {
        "schema": MODEL_POLICY_VERSION,
        "symbol": str(symbol),
        "trained_until": pd.Timestamp(trained_until).isoformat(),
        "feature_names": list(features.columns),
        "model_class": (
            f"{model.__class__.__module__}.{model.__class__.__qualname__}"
        ),
        "model_params": model.get_params(deep=False),
        "policy": policy,
    }
    digest = hashlib.sha256(json.dumps(
        metadata, sort_keys=True, separators=(",", ":"), default=str,
    ).encode())
    digest.update(pd.util.hash_pandas_object(
        features, index=True,
    ).to_numpy().tobytes())
    digest.update(pd.util.hash_pandas_object(
        pd.Series(target, index=features.index), index=True,
    ).to_numpy().tobytes())
    return digest.hexdigest()[:16]
```

In `walk_forward_predict`, replace the old version hash with:

```python
policy = {
    "training_window": max_train_size,
    "min_train_size": min_train_size,
    "retrain_every": retrain_every,
    "label_horizon": forward_days,
    "label_threshold": threshold,
}
version = build_model_identity(
    symbol,
    trained_until,
    features.loc[train_index],
    target,
    model,
    policy,
)
```

Import the helper/constants in `code/learning_loop.py`, calculate the evolution
version from development features and targets, and persist these artifact keys:

```python
{
    "model": final_model,
    "model_version": version,
    "model_policy_version": MODEL_POLICY_VERSION,
    "feature_names": feature_names,
    "trained_until": trained_until.isoformat(),
    "data_hash": data_hash,
    "feature_hash": feature_hash,
}
```

If `artifact_path` already exists and the registry does not already point to it,
raise `FileExistsError`. If the same registered version already exists, return
that version without rewriting the artifact.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
PYTHONPATH=code python3 -m pytest tests/test_causal_ml.py tests/test_learning_loop.py -q
```

Expected: both files pass.

- [ ] **Step 5: Record an unstaged safety checkpoint**

Run:

```bash
git diff --check -- code/ml_ensemble.py code/learning_loop.py tests/test_causal_ml.py tests/test_learning_loop.py
```

Expected: no output and exit code 0.

---

### Task 3: Backtest HOLD Semantics and Policy Metadata

**Files:**
- Modify: `code/backtest_kline_engine.py:148-173,338-413,731-738,929-938`
- Test: `tests/test_backtest_integration.py`

**Interfaces:**
- Consumes: Task 1 insufficient states and policy constants.
- Produces: no-order `HOLD` decisions and explicit training-policy metadata.

- [ ] **Step 1: Write failing integration tests**

Add to `tests/test_backtest_integration.py`:

```python
def test_insufficient_ml_history_creates_hold_without_orders(
        tmp_path, monkeypatch):
    def insufficient(frame, factors, symbol):
        index = pd.to_datetime(frame["trade_date"])
        return pd.DataFrame({
            "probability": np.nan,
            "score": np.nan,
            "model_version": "INSUFFICIENT_HISTORY",
            "trained_until": pd.NaT,
        }, index=index)

    monkeypatch.setattr(backtest_kline_engine, "walk_forward_predict", insufficient)
    engine = KLineBacktestEngine(build_test_db(tmp_path))
    result = engine.run_kline_backtest(
        "000001", "2025-07-01", "2025-10-31",
        backtest_mode="RESEARCH_PROXY",
    )

    assert result["trades"] == []
    assert result["backtest_metadata"]["insufficient_history_count"] > 0
    assert result["backtest_metadata"]["training_mode"] == (
        "FIXED_WINDOW_WALK_FORWARD"
    )


def test_backtest_metadata_reports_fixed_training_policy(
        tmp_path, monkeypatch):
    monkeypatch.setattr(
        backtest_kline_engine,
        "walk_forward_predict",
        deterministic_predictions,
    )
    engine = KLineBacktestEngine(build_test_db(tmp_path))
    result = engine.run_kline_backtest(
        "000001", "2025-07-01", "2025-10-31",
        backtest_mode="RESEARCH_PROXY",
    )
    metadata = result["backtest_metadata"]

    assert metadata["training_window"] == 504
    assert metadata["retrain_every"] == 21
    assert metadata["label_horizon"] == 5
    assert metadata["holdout_size"] == 252
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
PYTHONPATH=code python3 -m pytest tests/test_backtest_integration.py -q
```

Expected: missing metadata keys and/or NaN decision behavior failure.

- [ ] **Step 3: Implement HOLD behavior and metadata**

Import the policy constants from `ml_ensemble`. In the causal decision loop,
handle missing probability before `ml_policy_action`:

```python
raw_probability = predictions.loc[date, "probability"]
model_version = str(predictions.loc[date, "model_version"])
if pd.isna(raw_probability):
    probability = None
    action = "HOLD"
    reason = model_version
else:
    probability = float(raw_probability)
    action, reason = ml_policy_action(
        probability,
        close.loc[date],
        ma20.loc[date],
        rsi.loc[date],
        macd.loc[date],
        previous_macd.loc[date],
    )
```

Use `probability` directly in the decision feature dictionary; JSON serializes
`None` as `null`.

Change `_backtest_metadata` to accept `insufficient_history_count` and add:

```python
"training_mode": "FIXED_WINDOW_WALK_FORWARD",
"training_window": TRAINING_WINDOW,
"retrain_every": RETRAIN_EVERY,
"label_horizon": LABEL_HORIZON,
"holdout_size": HOLDOUT_SIZE,
"insufficient_history_count": int(insufficient_history_count),
```

Count rows whose version starts with `INSUFFICIENT_`. Preserve
`fallback_signal_count` with value zero for response compatibility.

- [ ] **Step 4: Run integration tests and verify GREEN**

Run:

```bash
PYTHONPATH=code python3 -m pytest tests/test_backtest_integration.py -q
```

Expected: all integration tests pass.

- [ ] **Step 5: Record an unstaged safety checkpoint**

Run:

```bash
git diff --check -- code/backtest_kline_engine.py tests/test_backtest_integration.py
```

Expected: no output and exit code 0.

---

### Task 4: Continuous Candidate Evaluation and Untouched Holdout

**Files:**
- Modify: `code/learning_loop.py:21-224,228-378,630-836`
- Test: `tests/test_learning_loop.py`

**Interfaces:**
- Consumes: `simulate_portfolio`, Task 2 identity helper, completed experiences.
- Produces: one-simulation evaluation, `HOLDOUT_SIZE = 252`, and registry `evaluated_until` cutoff.

- [ ] **Step 1: Write failing continuous-evaluation and holdout tests**

Add to `tests/test_learning_loop.py`:

```python
def test_evaluate_predictions_uses_one_continuous_simulation(monkeypatch):
    calls = []
    real_simulator = learning_loop.simulate_portfolio

    def counting_simulator(*args, **kwargs):
        calls.append(args[2])
        return real_simulator(*args, **kwargs)

    monkeypatch.setattr(learning_loop, "simulate_portfolio", counting_simulator)
    market = evaluation_market(90)
    returns = pd.Series(0.02, index=market.index)
    probabilities = pd.Series(
        np.where(np.arange(len(market)) % 20 < 10, 0.8, 0.2),
        index=market.index,
    )

    metrics = evaluate_predictions(
        returns,
        probabilities,
        market,
        "000001",
        folds=3,
        horizon_bars=1,
        decision_features=neutral_decision_features(market),
    )

    assert calls == [1_000_000.0]
    assert metrics.folds == 3
    assert len(metrics.window_metrics) == 3


def populate_completed_experiences(store, periods=800):
    dates = pd.bdate_range("2023-01-02", periods=periods)
    for i, date in enumerate(dates):
        item = sample_decision(f"holdout-{i}")
        item["decision_time"] = date.isoformat()
        item["action"] = "HOLD"
        item["features"] = {
            "momentum": math.sin(i / 7),
            "volatility": 0.01 + (i % 5) * 0.001,
        }
        store.record_decision(item)
        horizon_return = math.sin(i / 7) * 0.03
        store.complete_horizon(
            item["decision_id"],
            horizon_return,
            max(horizon_return, 0),
            min(horizon_return, 0),
            date + pd.offsets.BDay(5),
        )
    return dates


def test_candidate_training_excludes_last_252_completed_rows(tmp_path):
    store = ExperienceStore(tmp_path / "test.db")
    registry = ModelRegistry(tmp_path / "test.db")
    dates = populate_completed_experiences(store)
    market = evaluation_market(
        len(dates) + 6, start=dates[0].strftime("%Y-%m-%d")
    )
    manager = EvolutionManager(store, registry, tmp_path / "models")

    version = manager.maybe_train(
        "000001", market.index.max().to_pydatetime(), market,
    )
    row = registry.get(version)
    artifact = joblib.load(row["artifact_path"])
    completed = store.completed_frame("000001")

    expected_holdout = completed.iloc[-HOLDOUT_SIZE:]
    assert pd.Timestamp(artifact["trained_until"]) < (
        expected_holdout["horizon_end_time"].min()
    )
    assert pd.Timestamp(row["evaluated_until"]) == (
        expected_holdout["horizon_end_time"].max()
    )


def test_shadow_uses_only_rows_after_consumed_holdout(tmp_path):
    store = ExperienceStore(tmp_path / "test.db")
    registry = ModelRegistry(tmp_path / "test.db")
    dates = populate_completed_experiences(store)
    market = evaluation_market(
        len(dates) + 6, start=dates[0].strftime("%Y-%m-%d")
    )
    manager = EvolutionManager(store, registry, tmp_path / "models")
    version = manager.maybe_train(
        "000001", market.index.max().to_pydatetime(), market,
    )

    result = manager.evaluate_shadow("000001", market)

    assert result["version"] == version
    assert result["shadow_samples"] == 0
```

Import `HOLDOUT_SIZE` from `learning_loop` and add the exact
`populate_completed_experiences` helper above beside `evaluation_market`.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
PYTHONPATH=code python3 -m pytest tests/test_learning_loop.py -q
```

Expected: simulator call count is three, `HOLDOUT_SIZE` or `evaluated_until` is
missing, and holdout rows are included in fitting.

- [ ] **Step 3: Evaluate all decisions through one simulator call**

In `evaluate_predictions`, build the complete decision list first, call
`simulate_portfolio` once, then partition the resulting equity curve into
chronological windows:

```python
simulation = simulate_portfolio(
    {str(symbol): evaluation_market},
    pd.DataFrame(decisions),
    float(initial_cash),
)
points = pd.DataFrame(simulation.equity_curve)
point_windows = np.array_split(np.arange(len(points)), folds)
prediction_windows = np.array_split(np.arange(len(frame)), folds)
fold_metrics = []
for point_indices, prediction_indices in zip(
        point_windows, prediction_windows):
    window_points = points.iloc[point_indices]
    window_predictions = frame.iloc[prediction_indices]
    start_equity = float(window_points.iloc[0]["start_equity"])
    end_equity = float(window_points.iloc[-1]["equity"])
    running_peak = np.maximum.accumulate(
        np.r_[start_equity, window_points["equity"].to_numpy(dtype=float)]
    )
    equities = np.r_[start_equity, window_points["equity"].to_numpy(dtype=float)]
    fold_metrics.append({
        "net_return": end_equity / start_equity - 1.0,
        "max_drawdown": float(((running_peak - equities) / running_peak).max()),
        "turnover": float(window_points["turnover"].sum() / start_equity),
        "brier_score": float((
            (window_predictions["probability"]
             - (window_predictions["return"] > 0.015).astype(float)) ** 2
        ).mean()),
    })
```

Global `net_return`, drawdown, turnover, and Brier score come directly from the
same simulation and full prediction frame; do not multiply independently reset
fold returns.

- [ ] **Step 4: Add holdout cutoff to model registry and training**

Add `HOLDOUT_SIZE = 252`. Extend `model_versions` with nullable
`evaluated_until TEXT`, including the same additive migration pattern already
used for `shadow_metrics_json`.

Extend `register(..., evaluated_until=None)` and persist it. In `maybe_train`:

```python
if len(frame) < TRAINING_WINDOW + HOLDOUT_SIZE:
    return None
development = frame.iloc[:-HOLDOUT_SIZE]
holdout = frame.iloc[-HOLDOUT_SIZE:]
development = development.iloc[-TRAINING_WINDOW:]
```

Run the existing three-fold `TimeSeriesSplit(n_splits=3, gap=LABEL_HORIZON)` only
inside `development` as a temporal sanity gate. Fit the candidate on all
development rows, predict the 252 holdout rows, and calculate candidate metrics
from holdout predictions through `evaluate_predictions`.

Set:

```python
trained_until = pd.to_datetime(
    development["horizon_end_time"]
).max()
evaluated_until = pd.to_datetime(
    holdout["horizon_end_time"]
).max()
```

Register both values. In `evaluate_shadow`, filter with
`candidate["evaluated_until"] or candidate["trained_until"]` so the consumed
holdout can never count as live shadow data.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```bash
PYTHONPATH=code python3 -m pytest tests/test_learning_loop.py -q
```

Expected: all learning-loop tests pass.

- [ ] **Step 6: Record an unstaged safety checkpoint**

Run:

```bash
git diff --check -- code/learning_loop.py tests/test_learning_loop.py
```

Expected: no output and exit code 0.

---

### Task 5: Disable Legacy Historical Evaluation

**Files:**
- Modify: `code/ml_strategy_engine.py:23-155`
- Modify: `code/backtest_hybrid_engine.py:42-53`
- Modify: `code/ashare_3d_fusion_engine.py:29-39`
- Create: `tests/test_legacy_ml_boundary.py`

**Interfaces:**
- Consumes: existing factor panel and `HistGradientBoostingRegressor`.
- Produces: `fit_current_model(panel_df) -> dict` and a disabled
  `train_and_eval` compatibility boundary.

- [ ] **Step 1: Write failing legacy-boundary tests**

Create `tests/test_legacy_ml_boundary.py`:

```python
import pandas as pd
import pytest

from ml_strategy_engine import AShareMLStrategyEngine


def panel_frame():
    dates = pd.bdate_range("2024-01-01", periods=20)
    return pd.DataFrame({
        "symbol": ["000001"] * len(dates),
        "close": range(10, 10 + len(dates)),
        "target_5d_return": [0.01] * (len(dates) - 5) + [None] * 5,
    }, index=dates)


def test_legacy_single_split_evaluation_is_disabled():
    engine = AShareMLStrategyEngine()

    with pytest.raises(RuntimeError, match="KLineBacktestEngine"):
        engine.train_and_eval(panel_frame())


def test_current_snapshot_fit_is_explicitly_not_a_backtest():
    engine = AShareMLStrategyEngine()

    metadata = engine.fit_current_model(panel_frame())

    assert engine.is_trained
    assert metadata == {
        "scope": "CURRENT_SNAPSHOT_RESEARCH_ONLY",
        "historical_backtest": False,
        "point_in_time_universe": False,
        "training_samples": 15,
    }
```

- [ ] **Step 2: Run the new test and verify RED**

Run:

```bash
PYTHONPATH=code python3 -m pytest tests/test_legacy_ml_boundary.py -q
```

Expected: `fit_current_model` is missing and `train_and_eval` does not raise.

- [ ] **Step 3: Add current-only fit and disable legacy evaluation**

In `AShareMLStrategyEngine` add:

```python
def fit_current_model(self, panel_df):
    self.feature_cols = [
        column for column in panel_df.columns
        if column not in {"symbol", "target_5d_return"}
    ]
    training = panel_df.dropna(subset=["target_5d_return"])
    if training.empty:
        raise ValueError("no mature labels for current snapshot training")
    self.model.fit(
        training[self.feature_cols],
        training["target_5d_return"],
    )
    self.is_trained = True
    return {
        "scope": "CURRENT_SNAPSHOT_RESEARCH_ONLY",
        "historical_backtest": False,
        "point_in_time_universe": False,
        "training_samples": len(training),
    }

def train_and_eval(self, panel_df, split_date="2025-01-01"):
    del panel_df, split_date
    raise RuntimeError(
        "legacy single-split historical evaluation is disabled; "
        "use KLineBacktestEngine"
    )
```

Delete obsolete regression metric imports and evaluation code. Update both
legacy callers and the module `__main__` to call `fit_current_model`; print the
returned scope metadata without historical R², RMSE, IC, or return claims.

When an explicit historical `target_date` is supplied to `predict_top_stocks`,
select only `df.loc[df.index <= pd.Timestamp(target_date)]`; skip the symbol if
that prefix is empty. Never use `df.iloc[-1]` after a missing historical date.

- [ ] **Step 4: Run legacy and integration tests and verify GREEN**

Run:

```bash
PYTHONPATH=code python3 -m pytest tests/test_legacy_ml_boundary.py tests/test_backtest_integration.py tests/test_web_validation.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Record an unstaged safety checkpoint**

Run:

```bash
git diff --check -- code/ml_strategy_engine.py code/backtest_hybrid_engine.py code/ashare_3d_fusion_engine.py tests/test_legacy_ml_boundary.py
```

Expected: no output and exit code 0.

---

### Task 6: Full Verification and Real-Database Fail-Closed Smoke Check

**Files:**
- Verify only; do not modify the real SQLite database.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: fresh evidence that the suite passes and the real legacy database is still rejected by strict mode.

- [ ] **Step 1: Run the complete automated suite**

Run:

```bash
PYTHONPATH=code python3 -m pytest -q
```

Expected: all tests pass with zero failures.

- [ ] **Step 2: Compile Python and validate JavaScript syntax**

Run:

```bash
python3 -m compileall -q code tests
node --check web/app.js
```

Expected: both commands exit 0 without output.

- [ ] **Step 3: Verify strict real-data rejection without invoking mutations**

Run the read-only SQL predicate that strict mode depends on:

```bash
sqlite3 -readonly data/ashare_quant.db \
  "SELECT COUNT(*) FROM stock_daily_catalog WHERE price_mode='RAW';"
```

Expected with the current database: `0`. Report that strict historical ML
remains unavailable until the separate data-provider phase supplies verified raw
data.

- [ ] **Step 4: Review only the touched paths**

Run:

```bash
git diff --check -- code/ml_ensemble.py code/learning_loop.py code/backtest_kline_engine.py code/ml_strategy_engine.py code/backtest_hybrid_engine.py code/ashare_3d_fusion_engine.py tests/test_causal_ml.py tests/test_learning_loop.py tests/test_backtest_integration.py tests/test_legacy_ml_boundary.py
git status --short
```

Expected: no whitespace errors. Preserve and report all unrelated pre-existing
dirty files; do not stage, reset, or commit them.
