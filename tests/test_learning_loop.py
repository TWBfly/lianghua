from datetime import datetime
import math
import sqlite3

import numpy as np
import pandas as pd
import joblib
import pytest

import learning_loop
from learning_loop import (
    EvaluationMetrics,
    EvolutionManager,
    ExperienceStore,
    ModelRegistry,
    PromotionGate,
    evaluate_predictions,
)
from ml_ensemble import HOLDOUT_SIZE, MODEL_POLICY_VERSION, TRAINING_WINDOW
from portfolio_simulator import simulate_portfolio


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


class SignProbabilityModel:
    def predict_proba(self, features):
        probability = np.where(
            features.iloc[:, 0].to_numpy(dtype=float) > 0,
            0.8,
            0.2,
        )
        return np.column_stack([1 - probability, probability])


class ConstantProbabilityModel:
    def __init__(self, probability):
        self.probability = probability

    def predict_proba(self, features):
        probability = np.full(len(features), self.probability)
        return np.column_stack([1 - probability, probability])


def write_artifact(model_dir, symbol, version, probability,
                   feature_names=("momentum",)):
    path = model_dir / symbol / f"{version}.joblib"
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "model": ConstantProbabilityModel(probability),
        "feature_names": list(feature_names),
    }, path)
    return path


def evaluation_market(periods=40, price=10.0, start="2025-01-01"):
    index = pd.bdate_range(start, periods=periods)
    return pd.DataFrame({
        "open": price,
        "high": price * 1.01,
        "low": price * 0.99,
        "close": price,
        "volume": 1_000_000,
    }, index=index)


def neutral_decision_features(market):
    return pd.DataFrame({
        "close": market["close"],
        "ma20": market["close"],
        "rsi_14": 50.0,
        "macd_hist": 0.0,
    }, index=market.index)


def populate_completed_experiences(store, periods=800):
    dates = pd.bdate_range("2023-01-02", periods=periods)
    for i, date in enumerate(dates):
        item = sample_decision(f"d{i}")
        item["decision_time"] = date.isoformat()
        item["action"] = "HOLD"
        item["features"] = {
            "momentum": math.sin(i / 7),
            "volatility": 0.01 + (i % 5) * 0.001,
        }
        store.record_decision(item)
        outcome = math.sin(i / 7) * 0.03
        store.complete_horizon(
            f"d{i}", outcome, max(outcome, 0), min(outcome, 0),
            date + pd.offsets.BDay(5),
        )
    return dates


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

    store.complete_horizon(
        "d1", 0.02, 0.04, -0.01, "2026-01-12"
    )
    store.complete_trade("d1", 0.015, "2026-01-12", 10.5)

    row = store.get("d1")
    assert row["completed"] == 1
    assert row["horizon_return"] == 0.02
    assert row["trade_return"] == 0.015
    assert row["horizon_end_time"] == "2026-01-12"
    assert row["reward"] == 0.015 - 0.25 * 0.01


def test_sell_decision_completes_at_horizon_without_an_open_trade(tmp_path):
    store = ExperienceStore(tmp_path / "test.db")
    decision = sample_decision()
    decision["action"] = "SELL"
    store.record_decision(decision)

    store.complete_horizon("d1", -0.02, 0.01, -0.03)

    row = store.get("d1")
    assert row["completed"] == 1
    assert row["reward"] == -0.02


def test_label_without_causal_maturity_is_excluded(tmp_path):
    store = ExperienceStore(tmp_path / "test.db")
    decision = sample_decision()
    decision["action"] = "HOLD"
    store.record_decision(decision)
    store.complete_horizon("d1", 0.02, 0.03, -0.01)

    assert store.completed_frame("000001").empty
    assert store.completed_since("000001") == 0


def test_order_result_updates_fill_or_rejection(tmp_path):
    store = ExperienceStore(tmp_path / "test.db")
    store.record_decision(sample_decision())

    store.record_order_result(
        "d1",
        status="FILLED",
        fill_time="2026-01-06",
        fill_price=10.2,
        fees=5.1,
    )

    row = store.get("d1")
    assert row["order_status"] == "FILLED"
    assert row["fill_time"] == "2026-01-06"
    assert row["fill_price"] == 10.2
    assert row["fees"] == 5.1


def test_retrain_due_after_50_completed_experiences(tmp_path):
    store = ExperienceStore(tmp_path / "test.db")
    for i in range(50):
        item = sample_decision(f"d{i}")
        item["action"] = "HOLD"
        store.record_decision(item)
        store.complete_horizon(
            f"d{i}", 0.01, 0.02, -0.01, "2026-01-10"
        )

    assert store.retrain_due(
        "000001",
        datetime(2026, 1, 6),
        completed_threshold=50,
        interval_days=7,
    )


def test_retrain_due_after_seven_days_with_new_experience(tmp_path):
    store = ExperienceStore(tmp_path / "test.db")
    store.record_training("000001", "v1", datetime(2026, 1, 1))
    item = sample_decision()
    item["action"] = "HOLD"
    store.record_decision(item)
    store.complete_horizon(
        "d1", 0.01, 0.02, -0.01, "2026-01-10"
    )

    assert store.retrain_due("000001", datetime(2026, 1, 8))


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


def test_challenger_must_improve_each_out_of_sample_window():
    champion = EvaluationMetrics(
        net_return=0.10,
        max_drawdown=0.05,
        turnover=0.20,
        brier_score=0.20,
        folds=3,
        window_metrics=(
            {
                "net_return": 0.03,
                "max_drawdown": 0.05,
                "turnover": 0.20,
                "brier_score": 0.20,
            },
        ) * 3,
    )
    challenger = EvaluationMetrics(
        net_return=0.11,
        max_drawdown=0.05,
        turnover=0.20,
        brier_score=0.19,
        folds=3,
        window_metrics=(
            {
                "net_return": 0.04,
                "max_drawdown": 0.04,
                "turnover": 0.20,
                "brier_score": 0.19,
            },
            {
                "net_return": 0.04,
                "max_drawdown": 0.04,
                "turnover": 0.20,
                "brier_score": 0.19,
            },
            {
                "net_return": 0.02,
                "max_drawdown": 0.04,
                "turnover": 0.20,
                "brier_score": 0.19,
            },
        ),
    )

    passed, reasons = PromotionGate().passes(challenger, champion)

    assert not passed
    assert "WINDOW_3_RETURN_NOT_IMPROVED" in reasons


def test_promotion_requires_shadow_samples_and_retires_old_champion(tmp_path):
    registry = ModelRegistry(tmp_path / "test.db")
    registry.register(
        "old",
        "000001",
        "CHAMPION",
        metrics().as_dict(),
        "old.joblib",
    )
    registry.register(
        "new",
        "000001",
        "SHADOW",
        metrics(net=0.11).as_dict(),
        "new.joblib",
    )

    assert not registry.promote("new", min_shadow_samples=50)
    registry.add_shadow_samples("new", 50)
    assert registry.promote("new", min_shadow_samples=50)
    assert registry.get("new")["status"] == "CHAMPION"
    assert registry.get("old")["status"] == "RETIRED"


def test_evaluate_predictions_returns_finite_rolling_metrics():
    returns = pd.Series(
        np.sin(np.arange(180) / 7) * 0.02,
        index=pd.bdate_range("2025-01-01", periods=180),
    )
    probabilities = pd.Series(
        np.where(returns > 0, 0.7, 0.3),
        index=returns.index,
    )

    result = evaluate_predictions(
        returns,
        probabilities,
        market=evaluation_market(180),
        symbol="000001",
        folds=3,
        horizon_bars=5,
    )

    assert result.folds == 3
    assert math.isfinite(result.net_return)
    assert 0 <= result.max_drawdown <= 1
    assert result.turnover >= 0
    assert 0 <= result.brier_score <= 1
    assert result.evaluated_samples == 36


def test_evaluate_predictions_uses_one_continuous_simulation(monkeypatch):
    calls = []
    real_simulator = learning_loop.simulate_portfolio

    def counting_simulator(*args, **kwargs):
        calls.append(args[2])
        return real_simulator(*args, **kwargs)

    monkeypatch.setattr(
        learning_loop, "simulate_portfolio", counting_simulator
    )
    market = evaluation_market(90)
    returns = pd.Series(
        np.sin(np.arange(90) / 7) * 0.02, index=market.index
    )
    probabilities = pd.Series(
        np.where(returns > 0, 0.7, 0.3), index=market.index
    )

    result = evaluate_predictions(
        returns,
        probabilities,
        market=market,
        symbol="000001",
        folds=3,
        horizon_bars=1,
        decision_features=neutral_decision_features(market),
    )

    assert calls == [1_000_000.0]
    assert len(result.window_metrics) == 3


def test_prediction_evaluation_equals_shared_simulator_after_costs():
    market = evaluation_market(8)
    probabilities = pd.Series(
        [0.8, 0.8, 0.2, 0.2, 0.8, 0.8, 0.2, 0.2],
        index=market.index,
    )
    returns = pd.Series(0.02, index=market.index)
    actions = ["BUY", "HOLD", "SELL", "SELL",
               "BUY", "HOLD", "SELL", "SELL"]
    decisions = pd.DataFrame([{
        "decision_id": f"expected:{date.date()}",
        "decision_time": date,
        "symbol": "000001",
        "action": action,
        "target_fraction": 0.20,
        "reason": "test",
        "model_version": "candidate",
    } for date, action in zip(market.index, actions)])
    expected = simulate_portfolio(
        {"000001": market}, decisions, 1_000_000
    )

    result = evaluate_predictions(
        returns,
        probabilities,
        market=market,
        symbol="000001",
        decision_features=neutral_decision_features(market),
        folds=1,
        horizon_bars=1,
    )

    assert result.net_return == pytest.approx(
        expected.final_equity / expected.initial_cash - 1.0
    )
    assert result.net_return < 0


def test_prediction_evaluation_does_not_book_unfilled_limit_up_return():
    market = evaluation_market(4)
    market.iloc[1, market.columns.get_loc("open")] = 11.0
    market.iloc[1, market.columns.get_loc("high")] = 11.0
    market.iloc[1, market.columns.get_loc("low")] = 11.0
    market.iloc[1, market.columns.get_loc("close")] = 11.0
    probabilities = pd.Series([0.8, 0.5, 0.5, 0.5], index=market.index)

    result = evaluate_predictions(
        pd.Series(0.20, index=market.index),
        probabilities,
        market=market,
        symbol="000001",
        decision_features=neutral_decision_features(market),
        folds=1,
        horizon_bars=1,
    )

    assert result.net_return == 0


def test_prediction_evaluation_rejects_unaligned_market_dates():
    market = evaluation_market(5)
    probabilities = pd.Series(0.8, index=market.index)
    probabilities.index = probabilities.index + pd.offsets.BDay(20)

    with pytest.raises(ValueError, match="market"):
        evaluate_predictions(
            pd.Series(0.02, index=probabilities.index),
            probabilities,
            market=market,
            symbol="000001",
            folds=1,
            horizon_bars=1,
        )


def test_evolution_manager_registers_auditable_challenger(tmp_path):
    store = ExperienceStore(tmp_path / "test.db")
    registry = ModelRegistry(tmp_path / "test.db")
    dates = populate_completed_experiences(store)

    manager = EvolutionManager(
        store,
        registry,
        tmp_path / "models",
    )
    version = manager.maybe_train(
        "000001",
        datetime(2027, 1, 1),
        evaluation_market(len(dates) + 2, start=str(dates[0].date())),
    )

    assert version
    row = registry.get(version)
    assert row["status"] in {"CHALLENGER", "SHADOW"}
    assert pd.Timestamp(row["trained_until"]) == (
        dates[-HOLDOUT_SIZE - 1] + pd.offsets.BDay(5)
    )
    assert pd.Timestamp(row["evaluated_until"]) == (
        dates[-1] + pd.offsets.BDay(5)
    )
    assert row["feature_hash"]
    assert row["metrics_json"]
    assert str(tmp_path / "models") in row["artifact_path"]
    artifact = joblib.load(row["artifact_path"])
    assert artifact["model_policy_version"] == MODEL_POLICY_VERSION
    assert artifact["model_version"] == version
    assert artifact["evaluated_until"] == row["evaluated_until"]

    registry.set_status(version, "SHADOW")
    shadow = manager.evaluate_shadow("000001")
    assert shadow["shadow_samples"] == 0


def test_evolution_manager_requires_training_window_plus_holdout(tmp_path):
    store = ExperienceStore(tmp_path / "test.db")
    registry = ModelRegistry(tmp_path / "test.db")
    dates = populate_completed_experiences(
        store, TRAINING_WINDOW + HOLDOUT_SIZE - 1
    )
    manager = EvolutionManager(store, registry, tmp_path / "models")

    assert manager.maybe_train(
        "000001",
        datetime(2027, 1, 1),
        evaluation_market(len(dates) + 2, start=str(dates[0].date())),
    ) is None


def test_shadow_model_must_pass_second_gate_before_promotion(tmp_path):
    registry = ModelRegistry(tmp_path / "test.db")
    store = ExperienceStore(tmp_path / "test.db")
    registry.register(
        "old", "000001", "CHAMPION", metrics().as_dict(), "old.joblib"
    )
    registry.register(
        "new", "000001", "SHADOW", metrics(net=0.11).as_dict(),
        "new.joblib",
    )
    manager = EvolutionManager(store, registry, tmp_path / "models")

    registry.record_shadow_metrics(
        "new", metrics(net=0.09).as_dict(), sample_count=50
    )
    assert not manager.promote_if_ready("new")

    registry.record_shadow_metrics(
        "new", metrics(net=0.12).as_dict(), sample_count=50
    )
    assert not manager.promote_if_ready("new")
    assert manager.promote_if_ready(
        "new", champion_metrics=metrics(net=0.10)
    )
    assert registry.get("new")["status"] == "CHAMPION"


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


def test_run_after_backtest_keeps_unprofitable_shadow(tmp_path):
    store = ExperienceStore(tmp_path / "test.db")
    registry = ModelRegistry(tmp_path / "test.db")
    dates = pd.bdate_range("2026-01-01", periods=60)
    for i, date in enumerate(dates):
        item = sample_decision(f"d{i}")
        item["decision_time"] = date.isoformat()
        item["action"] = "HOLD"
        positive = i % 20 < 10
        item["features"] = {"momentum": 1.0 if positive else -1.0}
        store.record_decision(item)
        outcome = 0.03 if positive else -0.02
        store.complete_horizon(
            f"d{i}", outcome, max(outcome, 0), min(outcome, 0),
            date + pd.offsets.BDay(5),
        )

    artifact = tmp_path / "models" / "000001" / "shadow.joblib"
    artifact.parent.mkdir(parents=True)
    joblib.dump({
        "model": SignProbabilityModel(),
        "feature_names": ["momentum"],
    }, artifact)
    registry.register(
        "shadow",
        "000001",
        "SHADOW",
        metrics(net=0.01).as_dict(),
        artifact,
        trained_until="2025-12-31",
    )
    manager = EvolutionManager(store, registry, tmp_path / "models")

    status = manager.run_after_backtest(
        ["000001"],
        datetime(2026, 4, 1),
        {"000001": evaluation_market(60, start="2026-01-01")},
    )

    assert status[0]["shadow_samples"] == 60
    assert not status[0]["promoted"]
    assert registry.get("shadow")["status"] == "SHADOW"
