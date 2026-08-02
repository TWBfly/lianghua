import sqlite3

import pandas as pd
import pytest

from ml_strategy_engine import AShareMLStrategyEngine


class FeatureEchoModel:
    def predict(self, features):
        return features["feature"].to_numpy(dtype=float)


class FutureReturningPipeline:
    def __init__(self):
        self.end_dates = []

    def extract_factors(self, symbol, start_date=None, end_date=None):
        self.end_dates.append(end_date)
        return pd.DataFrame({
            "feature": [1.0, 99.0],
            "close": [10.0, 20.0],
            "target_5d_return": [0.01, 0.02],
        }, index=pd.to_datetime(["2025-01-01", "2025-01-03"]))


def test_legacy_random_history_evaluation_is_disabled(tmp_path):
    engine = AShareMLStrategyEngine(tmp_path / "empty.db")

    with pytest.raises(RuntimeError, match="KLineBacktestEngine"):
        engine.train_and_eval(pd.DataFrame(), split_date="2025-01-01")


def test_current_fit_has_no_historical_performance_claim(tmp_path):
    engine = AShareMLStrategyEngine(tmp_path / "empty.db")
    dates = pd.bdate_range("2025-01-01", periods=20)
    panel = pd.DataFrame({
        "symbol": "000001",
        "feature": range(20),
        "target_5d_return": [0.01, -0.01] * 10,
    }, index=dates)

    metadata = engine.fit_current_model(panel)

    assert engine.is_trained
    assert metadata == {
        "scope": "CURRENT_SNAPSHOT_RESEARCH_ONLY",
        "historical_backtest": False,
        "point_in_time_universe": False,
        "training_samples": 20,
    }


def test_historical_prediction_uses_only_target_date_prefix(tmp_path):
    db_path = tmp_path / "test.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE stock_basic ("
            "symbol TEXT, name TEXT, price REAL, pe_ttm REAL, total_mv REAL)"
        )
        conn.execute(
            "INSERT INTO stock_basic VALUES (?, ?, ?, ?, ?)",
            ("000001", "测试", 10.0, 12.0, 100.0),
        )
    engine = AShareMLStrategyEngine(db_path)
    engine.pipeline = FutureReturningPipeline()
    engine.model = FeatureEchoModel()
    engine.feature_cols = ["feature"]
    engine.is_trained = True

    picks = engine.predict_top_stocks("2025-01-02", top_k=1)

    assert engine.pipeline.end_dates == ["2025-01-02"]
    assert picks.iloc[0]["predicted_5d_return_pct"] == 100.0
