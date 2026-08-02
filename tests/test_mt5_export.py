import sqlite3

import pandas as pd
import pytest

import mt5_export
from market_data import MarketDataError


def build_db(tmp_path, high=10.5, close=10.0):
    db_path = tmp_path / "quant.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE stock_daily (
                symbol TEXT, trade_date TEXT, open REAL, close REAL,
                high REAL, low REAL, volume REAL, amount REAL
            )
        """)
        conn.executemany(
            "INSERT INTO stock_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("603986", "2026-07-24", 9.8, close, high, 9.5, 1000, 10000),
                ("603986", "2026-07-27", 10.0, 10.2, 10.6, 9.9, 1200, 12240),
                ("603986", "2026-07-28", 10.2, 10.1, 10.4, 10.0, 900, 9090),
            ],
        )
    return db_path


def test_export_symbol_writes_mt5_bars_and_reference_signals(tmp_path):
    result = mt5_export.export_symbol(
        build_db(tmp_path), "603986", tmp_path / "out", "2026-07-28"
    )

    bars = pd.read_csv(result["bars_path"])
    signals = pd.read_csv(result["signals_path"])

    assert list(bars.columns) == [
        "Date", "Time", "Open", "High", "Low", "Close",
        "TickVolume", "Volume", "Spread",
    ]
    assert bars.iloc[0]["Date"] == "2026.07.24"
    assert bars.iloc[0]["Time"] == "09:30:00"
    assert signals.columns.tolist() == ["Date", "Direction"]
    assert set(signals["Direction"]) <= {-1, 1}
    assert result["row_count"] == 3
    assert result["first_date"] == "2026.07.24"
    assert result["last_date"] == "2026.07.28"


def test_export_symbol_rejects_invalid_ohlc_without_overwrite(tmp_path):
    output = tmp_path / "out"
    output.mkdir()
    old = output / "lianghua_603986_bars.csv"
    old.write_text("old", encoding="utf-8")

    with pytest.raises(MarketDataError, match="invalid OHLC"):
        mt5_export.export_symbol(
            build_db(tmp_path, high=8.0),
            "603986",
            output,
            "2026-07-28",
        )

    assert old.read_text(encoding="utf-8") == "old"
