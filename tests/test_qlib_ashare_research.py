"""
Tests for Qlib A-Share Data Adapter, Feature Extraction, and Quantitative Research Pipeline.
"""

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from data_contract import audit_database, validate_stock_universe
from qlib_ashare_adapter import (
    calculate_ashare_features,
    load_ashare_dataset,
    STOCK_FEATURE_COLUMNS,
)
from run_qlib_stock_research import calculate_ic_metrics, run_topk_backtest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "ashare_quant.db"


def test_repaired_database_contract_integrity():
    """Verify that the real database passes all data contract audit gates."""
    audit = audit_database(DB_PATH)
    assert audit["stock"]["index_rows"] == 0
    assert audit["stock"]["uncataloged_symbols"] == 0
    assert audit["stock"]["catalog_mismatch_count"] == 0
    assert audit["stock"]["symbols"] >= 300
    assert audit["stock"]["rows"] > 400000


def test_ashare_feature_calculation_causality():
    """Verify that calculated features have correct columns, non-empty values, and no future leakage."""
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    rng = np.random.default_rng(42)
    prices = 10.0 + np.cumsum(rng.normal(0.05, 0.2, size=100))
    
    mock_df = pd.DataFrame({
        "symbol": "000001",
        "trade_date": dates.strftime("%Y-%m-%d"),
        "open": prices * 0.99,
        "high": prices * 1.02,
        "low": prices * 0.98,
        "close": prices,
        "volume": 10000 + rng.integers(100, 5000, size=100),
        "amount": 100000.0,
        "turnover_rate": 1.5,
    })

    feat_df = calculate_ashare_features(mock_df, label_horizon=5)

    # Check that all feature columns are present
    for col in STOCK_FEATURE_COLUMNS:
        assert col in feat_df.columns, f"Missing feature: {col}"

    # Check that label is present
    assert "label" in feat_df.columns
    # Check that tail has valid features
    assert feat_df.iloc[-1][list(STOCK_FEATURE_COLUMNS)].notna().all()


def test_load_ashare_dataset_temporal_split():
    """Verify that load_ashare_dataset enforces non-overlapping temporal windows."""
    dataset = load_ashare_dataset(
        db_path=DB_PATH,
        symbols=["000001", "000063", "000333", "600036"],
        train_ratio=0.60,
        valid_ratio=0.20,
    )

    assert len(dataset.train_df) > 0
    assert len(dataset.valid_df) > 0
    assert len(dataset.test_df) > 0

    # Ensure strictly increasing date intervals
    assert dataset.train_dates[1] <= dataset.valid_dates[0]
    assert dataset.valid_dates[1] <= dataset.test_dates[0]


def test_ic_and_topk_backtest_execution():
    """Verify IC computation and Top-K portfolio simulation."""
    dates = pd.date_range("2025-01-01", periods=30, freq="B")
    symbols = ["000001", "000002", "000063", "000333", "600036"]
    
    rows = []
    rng = np.random.default_rng(123)
    for d in dates:
        for s in symbols:
            rows.append({
                "trade_date": d,
                "symbol": s,
                "close": 10.0 + rng.uniform(-1, 1),
                "score": rng.uniform(0, 1),
                "label": rng.uniform(-0.05, 0.05),
            })
    test_df = pd.DataFrame(rows)

    ic_metrics = calculate_ic_metrics(test_df)
    assert "mean_rank_ic" in ic_metrics
    assert "icir" in ic_metrics

    bt_result = run_topk_backtest(
        test_df=test_df,
        top_k=2,
        rebalance_days=5,
        initial_cash=100_000.0,
    )
    assert bt_result["final_equity"] > 0
    assert len(bt_result["daily_records"]) == len(dates)
