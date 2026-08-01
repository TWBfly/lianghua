import numpy as np
import pandas as pd
import pytest

from market_data import MarketDataError, validate_daily_bars


def valid_bars():
    return pd.DataFrame({
        "trade_date": ["2026-01-06", "2026-01-05"],
        "open": [10.5, 10.0],
        "high": [10.8, 10.2],
        "low": [10.4, 9.9],
        "close": [10.7, 10.1],
        "volume": [1_200, 1_000],
        "amount": [12_840, 10_100],
        "symbol": ["000001", "000001"],
    })


def test_valid_daily_bars_are_sorted_and_normalized():
    result = validate_daily_bars(valid_bars(), "000001")

    assert result["trade_date"].tolist() == [
        pd.Timestamp("2026-01-05"),
        pd.Timestamp("2026-01-06"),
    ]


@pytest.mark.parametrize("mutation", [
    lambda frame: pd.concat([frame, frame.iloc[[0]]], ignore_index=True),
    lambda frame: frame.assign(high=[10.0, 10.2]),
    lambda frame: frame.assign(close=[np.inf, 10.1]),
    lambda frame: frame.assign(volume=[-1, 1_000]),
    lambda frame: frame.assign(symbol=["000001", "000002"]),
])
def test_invalid_daily_bars_raise(mutation):
    with pytest.raises(MarketDataError):
        validate_daily_bars(mutation(valid_bars()), "000001")


def test_missing_required_column_raises():
    with pytest.raises(MarketDataError, match="missing bar columns"):
        validate_daily_bars(valid_bars().drop(columns="amount"))


def test_factor_query_treats_symbol_as_data(tmp_path, monkeypatch):
    import ashare_factor_pipeline
    from ashare_data_engine import AShareDataEngine
    from ashare_factor_pipeline import AShareFactorPipeline

    calls = []

    def read_sql(query, _conn, params=None):
        calls.append((query, params))
        return pd.DataFrame()

    monkeypatch.setattr(
        ashare_factor_pipeline.pd, "read_sql_query", read_sql
    )
    engine = AShareDataEngine(tmp_path / "quant.db")
    pipeline = AShareFactorPipeline(engine.db_path)

    assert pipeline.extract_factors("000001' OR 1=1 --") is None
    assert "symbol=?" in calls[0][0]
    assert calls[0][1][0] == "000001' OR 1=1 --"
