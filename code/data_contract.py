from __future__ import annotations

import sqlite3
from pathlib import Path

from market_data import MarketDataError


class DataContractError(MarketDataError):
    def __init__(self, message, error_code="DATA_CONTRACT_INVALID"):
        super().__init__(message)
        self.error_code = error_code


def ensure_asset_type_column(conn):
    columns = {
        row[1] for row in conn.execute(
            "PRAGMA table_info(stock_daily_catalog)"
        )
    }
    if "asset_type" not in columns:
        conn.execute(
            "ALTER TABLE stock_daily_catalog ADD COLUMN "
            "asset_type TEXT NOT NULL DEFAULT 'LEGACY_UNVERIFIED'"
        )


def _reject_symbol(symbol):
    value = str(symbol).strip().upper()
    if value.endswith("_IDX"):
        raise DataContractError(
            f"{value} is a futures index, not a stock asset",
            "ASSET_TYPE_MISMATCH",
        )
    return value


def validate_stock_contract(conn, symbol, start_date, end_date, backtest_mode):
    value = _reject_symbol(symbol)
    if backtest_mode not in {"STRICT", "RESEARCH_PROXY"}:
        raise DataContractError(
            "invalid stock backtest mode", "INVALID_BACKTEST_MODE"
        )
    ensure_asset_type_column(conn)
    catalog = conn.execute("""
        SELECT symbol, asset_type, price_mode, source, start_date, end_date,
               row_count, updated_at
        FROM stock_daily_catalog WHERE symbol=?
    """, (value,)).fetchone()
    if catalog is None:
        raise DataContractError(
            f"stock symbol {value} has no catalog provenance",
            "UNCATALOGED_STOCK",
        )
    keys = (
        "symbol", "asset_type", "price_mode", "source", "start_date",
        "end_date", "row_count", "updated_at",
    )
    provenance = dict(zip(keys, catalog))
    if provenance["asset_type"] not in {"STOCK", "ETF"}:
        raise DataContractError(
            f"stock symbol {value} has unverified asset type",
            "UNVERIFIED_ASSET_TYPE",
        )
    actual = conn.execute("""
        SELECT MIN(trade_date), MAX(trade_date), COUNT(*)
        FROM stock_daily WHERE symbol=?
    """, (value,)).fetchone()
    if tuple(actual) != (
        provenance["start_date"], provenance["end_date"], provenance["row_count"]
    ):
        raise DataContractError(
            f"stock catalog coverage mismatch for {value}",
            "CATALOG_COVERAGE_MISMATCH",
        )
    if provenance["start_date"] > start_date or provenance["end_date"] < end_date:
        raise DataContractError(
            f"stock data does not cover requested range for {value}",
            "INSUFFICIENT_DATA_COVERAGE",
        )
    if provenance["price_mode"] not in {"RAW", "QFQ"}:
        raise DataContractError(
            f"stock symbol {value} has unknown price mode",
            "UNKNOWN_PRICE_MODE",
        )
    if backtest_mode == "STRICT" and provenance["price_mode"] != "RAW":
        raise DataContractError(
            "strict stock backtest requires RAW prices",
            "RAW_EXECUTION_UNAVAILABLE",
        )
    provenance["verification_status"] = "VERIFIED"
    provenance["price_semantics"] = (
        "RAW_EXECUTION" if provenance["price_mode"] == "RAW"
        else "ADJUSTED_PROXY"
    )
    return provenance


def validate_stock_universe(conn, symbols, start_date, end_date, backtest_mode):
    values = [str(symbol).strip().upper() for symbol in symbols]
    if not values or len(set(values)) != len(values):
        raise DataContractError("stock universe must be non-empty and unique")
    return [
        validate_stock_contract(
            conn, value, start_date, end_date, backtest_mode
        )
        for value in values
    ]


def audit_database(db_path):
    path = Path(db_path)
    if not path.is_file():
        raise DataContractError("database is missing", "DATABASE_MISSING")
    with sqlite3.connect(path) as conn:
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        catalog_columns = {
            row[1] for row in conn.execute(
                "PRAGMA table_info(stock_daily_catalog)"
            )
        }
        asset_type_available = "asset_type" in catalog_columns
        stock = conn.execute("""
            SELECT COUNT(*) AS rows, COUNT(DISTINCT symbol) AS symbols,
                   SUM(symbol LIKE '%_IDX') AS index_rows
            FROM stock_daily
        """).fetchone()
        uncataloged = conn.execute("""
            SELECT COUNT(DISTINCT d.symbol) FROM stock_daily d
            LEFT JOIN stock_daily_catalog c ON c.symbol=d.symbol
            WHERE c.symbol IS NULL
        """).fetchone()[0]
        asset_type_clause = (
            "c.asset_type='LEGACY_UNVERIFIED'"
            if asset_type_available else "1=1"
        )
        mismatch = conn.execute(f"""
            SELECT COUNT(*) FROM stock_daily_catalog c
            WHERE {asset_type_clause}
               OR c.row_count != (
                   SELECT COUNT(*) FROM stock_daily d WHERE d.symbol=c.symbol
               )
               OR c.start_date != (
                   SELECT MIN(trade_date) FROM stock_daily d WHERE d.symbol=c.symbol
               )
               OR c.end_date != (
                   SELECT MAX(trade_date) FROM stock_daily d WHERE d.symbol=c.symbol
               )
        """).fetchone()[0]
        futures = (
            conn.execute("""
                SELECT COUNT(*) rows, COUNT(DISTINCT symbol) symbols,
                       SUM(volume=0) zero_volume
                FROM futures_min_bars WHERE timeframe='5m'
            """).fetchone()
            if "futures_min_bars" in tables else (0, 0, 0)
        )
    return {
        "stock": {
            "rows": stock[0], "symbols": stock[1],
            "index_rows": stock[2] or 0,
            "uncataloged_symbols": uncataloged,
            "catalog_mismatch_count": mismatch,
        },
        "futures_5m": {
            "rows": futures[0], "symbols": futures[1],
            "zero_volume": futures[2] or 0,
        },
    }
