import sqlite3
from pathlib import Path
from types import SimpleNamespace

import joblib
import numpy as np
import pandas as pd
import pytest

import backtest_kline_engine
from backtest_kline_engine import KLineBacktestEngine, _friction_summary
from learning_loop import ModelRegistry


class AlwaysHighProbabilityModel:
    def predict_proba(self, features):
        probability = np.full(len(features), 0.8)
        return np.column_stack([1 - probability, probability])


def test_backtest_engine_has_one_causal_implementation():
    source = (
        Path(backtest_kline_engine.__file__).read_text(encoding="utf-8")
    )

    assert source.count("    def run_kline_backtest(") == 1
    assert source.count("    def run_portfolio_backtest(") == 1
    assert ".bfill(" not in source
    assert "train_and_predict_ensemble" not in source
    assert "overall_max_dd_pct\": 6.85" not in source


def test_engine_keeps_manual_data_sync_capability(tmp_path):
    engine = KLineBacktestEngine(build_test_db(tmp_path))

    assert hasattr(engine, "data_engine")
    assert callable(engine.data_engine.sync_stock_daily)


def build_test_db(tmp_path, symbols=("000001",), price=10.0,
                  periods=220):
    db_path = tmp_path / "quant.db"
    dates = pd.bdate_range("2025-01-01", periods=periods)
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE stock_daily (
                symbol TEXT,
                trade_date TEXT,
                open REAL,
                close REAL,
                high REAL,
                low REAL,
                volume REAL,
                amount REAL,
                amplitude REAL,
                pct_chg REAL,
                change_amount REAL,
                turnover_rate REAL,
                PRIMARY KEY (symbol, trade_date)
            );
            CREATE TABLE stock_basic (
                symbol TEXT,
                name TEXT,
                price REAL,
                pe_ttm REAL,
                pb REAL,
                total_mv REAL,
                circ_mv REAL,
                updated_at TEXT
            );
        """)
        for symbol_index, symbol in enumerate(symbols):
            phase = symbol_index * 0.7
            close = price * (
                1
                + np.sin(np.arange(len(dates)) / 8 + phase) * 0.04
                + np.arange(len(dates)) * 0.0002
            )
            open_price = close * 0.998
            pct = pd.Series(close).pct_change().fillna(0).to_numpy() * 100
            rows = [
                (
                    symbol,
                    date.strftime("%Y-%m-%d"),
                    float(open_price[i]),
                    float(close[i]),
                    float(max(open_price[i], close[i]) * 1.01),
                    float(min(open_price[i], close[i]) * 0.99),
                    1_000_000.0,
                    float(close[i] * 1_000_000),
                    2.0,
                    float(pct[i]),
                    0.0,
                    1.0,
                )
                for i, date in enumerate(dates)
            ]
            conn.executemany(
                "INSERT INTO stock_daily VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.execute(
                "INSERT INTO stock_basic VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    symbol,
                    f"测试{symbol}",
                    float(close[-1]),
                    20.0,
                    2.0,
                    10_000_000_000.0,
                    8_000_000_000.0,
                    "2025-12-31",
                ),
            )
    return db_path


def deterministic_predictions(df_kline, df_factors, symbol, **_kwargs):
    index = pd.to_datetime(df_kline["trade_date"])
    probability = np.full(len(index), 0.45)
    probability[130:150] = 0.75
    probability[150:170] = 0.20
    result = pd.DataFrame(index=index)
    result["probability"] = probability
    result["score"] = probability * 10
    result["model_version"] = "test-causal-v1"
    result["trained_until"] = index - pd.offsets.BDay(1)
    return result


def insufficient_predictions(df_kline, df_factors, symbol, **_kwargs):
    index = pd.to_datetime(df_kline["trade_date"])
    return pd.DataFrame({
        "probability": np.nan,
        "score": np.nan,
        "model_version": "INSUFFICIENT_HISTORY",
        "trained_until": pd.NaT,
    }, index=index)


def catalog_symbol(engine, symbol, source="TEST_QFQ"):
    with engine.get_connection() as conn:
        start_date, end_date, row_count = conn.execute("""
            SELECT MIN(trade_date), MAX(trade_date), COUNT(*)
            FROM stock_daily WHERE symbol=?
        """, (symbol,)).fetchone()
        conn.execute("""
            INSERT INTO stock_daily_catalog (
                symbol, price_mode, source, start_date, end_date,
                row_count, updated_at
            ) VALUES (?, 'QFQ', ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (symbol, source, start_date, end_date, row_count))


def assert_enriched_backtest(result, metrics_key):
    metrics = result[metrics_key]
    assert len(result["daily_results"]) == len(result["equity_curve"])
    assert result["daily_results"][-1]["end_equity"] == pytest.approx(
        metrics["final_equity"], abs=0.01
    )
    for field in (
        "annualized_volatility_pct",
        "sharpe_ratio",
        "sortino_ratio",
        "calmar_ratio",
        "max_drawdown_duration_days",
        "total_turnover_cny",
        "turnover_ratio",
    ):
        assert field in metrics
    assert result["backtest_metadata"]["data_provenance"]


def test_insufficient_ml_history_creates_hold_without_orders(
        tmp_path, monkeypatch):
    monkeypatch.setattr(
        backtest_kline_engine,
        "walk_forward_predict",
        insufficient_predictions,
    )
    engine = KLineBacktestEngine(build_test_db(tmp_path))

    result = engine.run_kline_backtest(
        "000001",
        "2025-07-01",
        "2025-10-31",
        backtest_mode="RESEARCH_PROXY",
    )

    assert result["trades"] == []
    assert result["rejected_orders"] == []
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
        "000001",
        "2025-07-01",
        "2025-10-31",
        backtest_mode="RESEARCH_PROXY",
    )
    metadata = result["backtest_metadata"]

    assert metadata["training_window"] == 504
    assert metadata["retrain_every"] == 21
    assert metadata["label_horizon"] == 5
    assert metadata["holdout_size"] == 252


def test_strict_backtest_rejects_uncataloged_data(tmp_path):
    engine = KLineBacktestEngine(build_test_db(tmp_path))

    result = engine.run_kline_backtest(
        "000001", "2025-07-01", "2025-12-31", 100_000
    )

    assert result["error_code"] == "UNVERIFIED_DATA_PROVENANCE"


def test_strict_backtest_rejects_qfq_execution_proxy(tmp_path):
    engine = KLineBacktestEngine(build_test_db(tmp_path))
    catalog_symbol(engine, "000001")

    result = engine.run_kline_backtest(
        "000001", "2025-07-01", "2025-12-31", 100_000
    )

    assert result["error_code"] == "RAW_EXECUTION_UNAVAILABLE"


def test_explicit_research_proxy_labels_verified_qfq(
        tmp_path, monkeypatch):
    engine = KLineBacktestEngine(build_test_db(tmp_path))
    catalog_symbol(engine, "000001")
    monkeypatch.setattr(
        backtest_kline_engine,
        "walk_forward_predict",
        deterministic_predictions,
    )

    result = engine.run_kline_backtest(
        "000001", "2025-07-01", "2025-12-31", 100_000,
        backtest_mode="RESEARCH_PROXY",
    )

    assert "error" not in result
    metadata = result["backtest_metadata"]
    assert metadata["backtest_mode"] == "RESEARCH_PROXY"
    assert metadata["price_semantics"] == "ADJUSTED_PROXY"
    assert metadata["ai_used"] is False
    assert metadata["data_license_status"] == (
        "UNVERIFIED_FOR_COMMERCIAL_USE"
    )
    assert metadata["data_provenance"]["verification_status"] == (
        "VERIFIED"
    )


def test_explicit_research_proxy_labels_legacy_data(
        tmp_path, monkeypatch):
    engine = KLineBacktestEngine(build_test_db(tmp_path))
    monkeypatch.setattr(
        backtest_kline_engine,
        "walk_forward_predict",
        deterministic_predictions,
    )

    result = engine.run_kline_backtest(
        "000001", "2025-07-01", "2025-12-31", 100_000,
        backtest_mode="RESEARCH_PROXY",
    )

    provenance = result["backtest_metadata"]["data_provenance"]
    assert provenance["price_mode"] == "UNKNOWN"
    assert provenance["source"] == "LEGACY_UNCATALOGED"
    assert provenance["verification_status"] == "UNVERIFIED"
    assert result["backtest_metadata"]["price_semantics"] == (
        "LEGACY_UNVERIFIED"
    )


def test_portfolio_uses_same_strict_provenance_gate(tmp_path):
    engine = KLineBacktestEngine(build_test_db(
        tmp_path, symbols=("000001", "000002")
    ))

    result = engine.run_portfolio_backtest(
        100_000,
        "2025-07-01",
        "2025-12-31",
        symbols=["000001", "000002"],
    )

    assert result["error_code"] == "UNVERIFIED_DATA_PROVENANCE"


def test_mechanical_strategy_uses_shared_simulator_not_ml_pipeline(
        tmp_path, monkeypatch):
    engine = KLineBacktestEngine(build_test_db(tmp_path))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("mechanical strategy used ML factors")

    monkeypatch.setattr(engine.ml_engine.pipeline, "extract_factors", forbidden)
    original = backtest_kline_engine.simulate_portfolio
    seen = {}

    def recording_simulator(market, decisions, initial_cash, **kwargs):
        seen["decisions"] = decisions.copy()
        return original(market, decisions, initial_cash, **kwargs)

    monkeypatch.setattr(
        backtest_kline_engine, "simulate_portfolio", recording_simulator
    )

    result = engine.run_kline_backtest(
        "000001",
        "2025-01-01",
        "2025-12-31",
        100_000,
        backtest_mode="RESEARCH_PROXY",
        strategy="macd_cross",
    )

    assert "error" not in result
    assert result["backtest_metadata"]["strategy_name"] == "macd_cross"
    assert not seen["decisions"].empty
    assert set(seen["decisions"]["action"]).issubset({
        "BUY", "SELL", "HOLD",
    })
    assert set(seen["decisions"]["model_version"]) == {
        "mechanical:macd_cross:v1"
    }


def test_unknown_strategy_is_rejected_before_market_work(tmp_path):
    engine = KLineBacktestEngine(build_test_db(tmp_path))

    result = engine.run_kline_backtest(
        "000001",
        "2025-01-01",
        "2025-12-31",
        100_000,
        backtest_mode="RESEARCH_PROXY",
        strategy="not-real",
    )

    assert result["error_code"] == "UNKNOWN_STRATEGY"


def test_benchmark_uses_first_and_last_common_reporting_dates(
        tmp_path, monkeypatch):
    engine = KLineBacktestEngine(build_test_db(tmp_path))
    monkeypatch.setattr(
        backtest_kline_engine,
        "walk_forward_predict",
        deterministic_predictions,
    )
    with engine.get_connection() as conn:
        dates = [row[0] for row in conn.execute("""
            SELECT trade_date FROM stock_daily
            WHERE symbol='000001' AND trade_date >= '2025-07-01'
            ORDER BY trade_date
        """).fetchall()]
        conn.executemany(
            "INSERT INTO index_daily VALUES "
            "('000300', ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (dates[0], 100.0, 100.0, 101.0, 99.0, 1, 1, 0.0),
                (dates[-1], 110.0, 110.0, 111.0, 109.0, 1, 1, 10.0),
            ],
        )

    result = engine.run_kline_backtest(
        "000001",
        "2025-07-01",
        "2025-12-31",
        100_000,
        backtest_mode="RESEARCH_PROXY",
    )

    benchmark = result["metrics"]["benchmark"]
    assert benchmark == {
        "status": "AVAILABLE",
        "benchmark_code": "000300",
        "start_date": dates[0],
        "end_date": dates[-1],
        "return_pct": 10.0,
        "excess_return_pct": pytest.approx(
            result["metrics"]["total_return_pct"] - 10.0,
            abs=0.01,
        ),
    }


def test_missing_benchmark_is_unknown_not_zero(tmp_path, monkeypatch):
    engine = KLineBacktestEngine(build_test_db(tmp_path))
    monkeypatch.setattr(
        backtest_kline_engine,
        "walk_forward_predict",
        deterministic_predictions,
    )

    result = engine.run_portfolio_backtest(
        100_000,
        "2025-07-01",
        "2025-12-31",
        symbols=["000001"],
        backtest_mode="RESEARCH_PROXY",
    )

    assert result["portfolio_metrics"]["benchmark"] == {
        "status": "UNKNOWN",
        "benchmark_code": "000300",
        "start_date": None,
        "end_date": None,
        "return_pct": None,
        "excess_return_pct": None,
    }


def test_backtest_loads_history_before_reporting_start(
        tmp_path, monkeypatch):
    db_path = build_test_db(tmp_path)
    seen_starts = []

    def recording_predictions(df_kline, df_factors, symbol, **kwargs):
        seen_starts.append(pd.to_datetime(df_kline["trade_date"]).min())
        return deterministic_predictions(
            df_kline, df_factors, symbol, **kwargs
        )

    monkeypatch.setattr(
        backtest_kline_engine,
        "walk_forward_predict",
        recording_predictions,
    )

    result = KLineBacktestEngine(db_path).run_kline_backtest(
        "000001", "2025-07-01", "2025-12-31", 100_000,
        persist_experiences=False,
        run_evolution=False,
        backtest_mode="RESEARCH_PROXY",
    )

    assert seen_starts == [pd.Timestamp("2025-01-01")]
    assert result["category_dates"][0] >= "2025-07-01"
    assert len(result["kline_chart_data"]) == len(result["category_dates"])


def test_backtest_is_pure_by_default(tmp_path, monkeypatch):
    db_path = build_test_db(tmp_path)
    monkeypatch.setattr(
        backtest_kline_engine,
        "walk_forward_predict",
        deterministic_predictions,
    )
    engine = KLineBacktestEngine(db_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("default backtest mutated learning state")

    monkeypatch.setattr(engine, "_persist_experiences", forbidden)
    monkeypatch.setattr(engine, "_run_evolution", forbidden)

    result = engine.run_kline_backtest(
        "000001", "2025-01-01", "2025-12-31", 100_000,
        backtest_mode="RESEARCH_PROXY",
    )

    assert "error" not in result


def test_single_stock_backtest_is_causal_and_closes_positions(
        tmp_path, monkeypatch):
    db_path = build_test_db(tmp_path)
    monkeypatch.setattr(
        backtest_kline_engine,
        "walk_forward_predict",
        deterministic_predictions,
        raising=False,
    )

    result = KLineBacktestEngine(db_path).run_kline_backtest(
        "000001",
        "2025-01-01",
        "2025-12-31",
        100_000,
        skip_ai=True,
        run_evolution=False,
        backtest_mode="RESEARCH_PROXY",
    )

    assert "error" not in result
    assert result["metrics"]["final_equity"] >= 0
    assert result["open_positions"] == {}
    assert result["model_versions"]
    assert all(
        pd.Timestamp(item["trained_until"])
        < pd.Timestamp(item["prediction_time"])
        for item in result["model_versions"]
        if item["trained_until"]
    )
    assert_enriched_backtest(result, "metrics")


def test_invalid_market_data_returns_existing_error_shape(
        tmp_path, monkeypatch):
    db_path = build_test_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE stock_daily SET high=0 "
            "WHERE symbol='000001' AND trade_date='2025-01-01'"
        )
    monkeypatch.setattr(
        backtest_kline_engine,
        "walk_forward_predict",
        deterministic_predictions,
    )

    result = KLineBacktestEngine(db_path).run_kline_backtest(
        "000001", "2025-01-01", "2025-12-31", 100_000
    )

    assert set(result) == {"error"}
    assert result["error"].startswith("行情数据质量错误:")


def test_small_capital_rejects_unaffordable_lot_without_crashing(
        tmp_path, monkeypatch):
    db_path = build_test_db(tmp_path, symbols=("600519",), price=1_500)
    monkeypatch.setattr(
        backtest_kline_engine,
        "walk_forward_predict",
        deterministic_predictions,
        raising=False,
    )

    result = KLineBacktestEngine(db_path).run_kline_backtest(
        "600519",
        "2025-01-01",
        "2025-12-31",
        1_000,
        skip_ai=True,
        run_evolution=False,
        backtest_mode="RESEARCH_PROXY",
    )

    assert "error" not in result
    assert result["metrics"]["final_equity"] == 1_000
    assert result["metrics"]["total_return_pct"] == 0
    assert result["rejected_orders"]


def test_portfolio_engine_uses_one_account_and_real_drawdown(
        tmp_path, monkeypatch):
    db_path = build_test_db(
        tmp_path,
        symbols=("000001", "000002"),
    )
    monkeypatch.setattr(
        backtest_kline_engine,
        "walk_forward_predict",
        deterministic_predictions,
        raising=False,
    )

    result = KLineBacktestEngine(db_path).run_portfolio_backtest(
        100_000,
        "2025-01-01",
        "2025-12-31",
        symbols=["000001", "000002"],
        run_evolution=False,
        backtest_mode="RESEARCH_PROXY",
    )

    metrics = result["portfolio_metrics"]
    assert metrics["final_equity"] == result["equity_curve"][-1]["equity"]
    assert metrics["overall_max_dd_pct"] != 6.85
    assert sum(
        item["safe_allocation_pct"]
        for item in result["allocations"]
    ) <= 90
    assert min(point["cash"] for point in result["equity_curve"]) >= 0
    assert result["open_positions"] == {}
    assert metrics["backtest_period"] == (
        f"{result['equity_curve'][0]['date']} 至 "
        f"{result['equity_curve'][-1]['date']}"
    )
    assert result["backtest_metadata"] == {
        "engine": "NATIVE_A_SHARE_EVENT_V2",
        "price_mode": "LEGACY_UNVERIFIED",
        "price_semantics": "LEGACY_UNVERIFIED",
        "backtest_mode": "RESEARCH_PROXY",
        "strategy_name": "causal_ml",
        "ai_used": False,
        "data_license_status": "UNVERIFIED_FOR_COMMERCIAL_USE",
        "universe_mode": "USER_SELECTED",
        "fallback_signal_count": 0,
        "training_mode": "FIXED_WINDOW_WALK_FORWARD",
        "training_window": 504,
        "retrain_every": 21,
        "label_horizon": 5,
        "holdout_size": 252,
        "insufficient_history_count": 0,
        "research_limitations": [
            "NO_POINT_IN_TIME_UNIVERSE",
            "NO_HISTORICAL_ST_STATUS",
            "NO_HISTORICAL_IPO_LIMIT_STATUS",
            "NO_CORPORATE_ACTION_CASH_LEDGER",
            "TRANSACTION_RULES_APPROXIMATE",
        ],
        "data_provenance": [{
            "symbol": symbol,
            "price_mode": "UNKNOWN",
            "source": "LEGACY_UNCATALOGED",
            "start_date": result["equity_curve"][0]["date"],
            "end_date": result["equity_curve"][-1]["date"],
            "row_count": len(result["equity_curve"]),
            "updated_at": None,
            "verification_status": "UNVERIFIED",
        } for symbol in ("000001", "000002")],
    }
    allocation = result["kelly_allocations"][0]
    assert allocation["allocation_method"] == "FIXED_RISK_CAP"
    assert "allocation_pct" in allocation
    assert "kelly_fraction_pct" not in allocation
    assert "win_rate_pct" not in allocation
    assert_enriched_backtest(result, "portfolio_metrics")


def test_yearly_breakdown_uses_equity_for_every_calendar_year(
        tmp_path, monkeypatch):
    db_path = build_test_db(
        tmp_path, symbols=("000001", "000002"), periods=300
    )
    monkeypatch.setattr(
        backtest_kline_engine,
        "walk_forward_predict",
        deterministic_predictions,
    )

    result = KLineBacktestEngine(db_path).run_portfolio_backtest(
        100_000,
        "2025-01-01",
        "2026-12-31",
        symbols=["000001", "000002"],
        backtest_mode="RESEARCH_PROXY",
    )

    assert [item["year"] for item in result["yearly_breakdown"]] == [
        "2025", "2026",
    ]
    assert sum(
        item["net_pnl"] for item in result["yearly_breakdown"]
    ) == pytest.approx(result["portfolio_metrics"]["total_pnl"], abs=0.02)


def test_friction_summary_uses_recorded_historical_stamp_duty():
    simulation = SimpleNamespace(fills=[{
        "side": "SELL",
        "gross_value": 10_000.0,
        "raw_price": 10.0,
        "fill_price": 9.99,
        "shares": 1_000,
        "fees": 15.1,
        "stamp_duty": 9.99,
    }])

    summary = _friction_summary(simulation)

    assert summary["total_stamp_duty_cny"] == 9.99


def test_star_market_allocation_respects_200_share_minimum(
        tmp_path, monkeypatch):
    db_path = build_test_db(tmp_path, symbols=("688001",), price=10)
    monkeypatch.setattr(
        backtest_kline_engine,
        "walk_forward_predict",
        deterministic_predictions,
    )

    result = KLineBacktestEngine(db_path).run_portfolio_backtest(
        8_000,
        "2025-01-01",
        "2025-12-31",
        symbols=["688001"],
        backtest_mode="RESEARCH_PROXY",
    )

    assert result["kelly_allocations"][0]["recommend_shares"] == 0


def test_backtest_runs_evolution_after_experiences_complete(
        tmp_path, monkeypatch):
    db_path = build_test_db(tmp_path)
    monkeypatch.setattr(
        backtest_kline_engine,
        "walk_forward_predict",
        deterministic_predictions,
    )

    class FakeEvolutionManager:
        def __init__(self, *_args, **_kwargs):
            pass

        def run_after_backtest(self, symbols, now, market):
            assert set(market) == {symbols[0]}
            return [{
                "symbol": symbols[0],
                "trained_version": "candidate-v2",
                "promoted": False,
                "now": now.isoformat(),
            }]

    monkeypatch.setattr(
        backtest_kline_engine,
        "EvolutionManager",
        FakeEvolutionManager,
        raising=False,
    )

    result = KLineBacktestEngine(db_path).run_kline_backtest(
        "000001",
        "2025-01-01",
        "2025-12-31",
        100_000,
        persist_experiences=True,
        run_evolution=True,
        backtest_mode="RESEARCH_PROXY",
    )

    assert result["evolution_status"][0]["trained_version"] == "candidate-v2"


def test_repeated_historical_run_does_not_duplicate_experiences(
        tmp_path, monkeypatch):
    db_path = build_test_db(tmp_path)
    monkeypatch.setattr(
        backtest_kline_engine,
        "walk_forward_predict",
        deterministic_predictions,
    )
    engine = KLineBacktestEngine(db_path)

    for _ in range(2):
        engine.run_kline_backtest(
            "000001",
            "2025-01-01",
            "2025-12-31",
            100_000,
            persist_experiences=True,
            run_evolution=False,
            backtest_mode="RESEARCH_PROXY",
        )

    with sqlite3.connect(db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM experiences"
        ).fetchone()[0]
    assert count == 220


def test_champion_is_used_only_after_its_training_cutoff(
        tmp_path, monkeypatch):
    db_path = build_test_db(tmp_path)
    monkeypatch.setattr(
        backtest_kline_engine,
        "walk_forward_predict",
        deterministic_predictions,
    )
    model_dir = tmp_path / "ml_models" / "evolution" / "000001"
    model_dir.mkdir(parents=True)
    artifact = model_dir / "champion-v1.joblib"
    joblib.dump({
        "model": AlwaysHighProbabilityModel(),
        "feature_names": ["close"],
    }, artifact)
    registry = ModelRegistry(db_path)
    registry.register(
        "champion-v1",
        "000001",
        "CHAMPION",
        {
            "net_return": 0.1,
            "max_drawdown": 0.05,
            "turnover": 0.2,
            "brier_score": 0.2,
            "folds": 3,
            "hit_kill_switch": False,
        },
        artifact,
        trained_until="2025-06-30",
        evaluated_until="2025-07-31",
    )

    result = KLineBacktestEngine(db_path).run_kline_backtest(
        "000001",
        "2025-01-01",
        "2025-12-31",
        100_000,
        persist_experiences=False,
        run_evolution=False,
        backtest_mode="RESEARCH_PROXY",
    )

    cutoff = pd.Timestamp("2025-07-31")
    before = [
        item for item in result["model_versions"]
        if pd.Timestamp(item["prediction_time"]) <= cutoff
    ]
    after = [
        item for item in result["model_versions"]
        if pd.Timestamp(item["prediction_time"]) > cutoff
    ]
    assert before
    assert all(
        item["model_version"] != "champion-v1" for item in before
    )
    assert after
    assert all(
        item["model_version"] == "champion-v1" for item in after
    )
