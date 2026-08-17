import sqlite3

import pytest

from data_contract import (
    DataContractError,
    audit_database,
    ensure_asset_type_column,
    validate_stock_contract,
    validate_stock_universe,
)


def make_db(tmp_path, *, catalog=True, asset_type="STOCK", price_mode="QFQ"):
    db_path = tmp_path / "contract.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
        CREATE TABLE stock_daily (
            symbol TEXT, trade_date TEXT, open REAL, close REAL, high REAL,
            low REAL, volume REAL, amount REAL, amplitude REAL, pct_chg REAL,
            change_amount REAL, turnover_rate REAL,
            PRIMARY KEY(symbol, trade_date)
        );
        CREATE TABLE stock_daily_catalog (
            symbol TEXT PRIMARY KEY, price_mode TEXT NOT NULL, source TEXT NOT NULL,
            start_date TEXT NOT NULL, end_date TEXT NOT NULL, row_count INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE stock_basic (symbol TEXT, name TEXT);
        """)
        for day in ("2025-01-02", "2025-01-03"):
            conn.execute(
                "INSERT INTO stock_daily VALUES (?, ?, 10, 10, 11, 9, 100, 1000, 2, 0, 0, 1)",
                ("000001", day),
            )
        conn.execute("INSERT INTO stock_basic VALUES ('000001', 'sample')")
        if catalog:
            conn.execute("""
                INSERT INTO stock_daily_catalog
                (symbol, price_mode, source, start_date, end_date, row_count, updated_at)
                VALUES ('000001', ?, 'TEST', '2025-01-02', '2025-01-03', 2, 'now')
            """, (price_mode,))
        ensure_asset_type_column(conn)
        if catalog:
            conn.execute(
                "UPDATE stock_daily_catalog SET asset_type=? WHERE symbol='000001'",
                (asset_type,),
            )
    return db_path


def test_qfq_proxy_is_verified_but_strict_raw_is_rejected(tmp_path):
    db_path = make_db(tmp_path, price_mode="QFQ")

    with sqlite3.connect(db_path) as conn:
        proxy = validate_stock_contract(
            conn, "000001", "2025-01-02", "2025-01-03", "RESEARCH_PROXY"
        )
        assert proxy["price_semantics"] == "ADJUSTED_PROXY"
        with pytest.raises(DataContractError, match="RAW"):
            validate_stock_contract(
                conn, "000001", "2025-01-02", "2025-01-03", "STRICT"
            )


def test_idx_and_uncataloged_symbols_are_rejected(tmp_path):
    db_path = make_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        with pytest.raises(DataContractError, match="asset"):
            validate_stock_contract(
                conn, "AG_IDX", "2025-01-02", "2025-01-03", "RESEARCH_PROXY"
            )
        with pytest.raises(DataContractError, match="catalog"):
            validate_stock_contract(
                conn, "000002", "2025-01-02", "2025-01-03", "RESEARCH_PROXY"
            )


def test_universe_validation_rejects_any_invalid_member(tmp_path):
    db_path = make_db(tmp_path)
    with sqlite3.connect(db_path) as conn:
        with pytest.raises(DataContractError, match="000002"):
            validate_stock_universe(
                conn, ["000001", "000002"],
                "2025-01-02", "2025-01-03", "RESEARCH_PROXY"
            )


def test_audit_is_read_only_and_reports_mixed_domains(tmp_path):
    db_path = make_db(tmp_path)
    before = db_path.read_bytes()

    audit = audit_database(db_path)

    assert audit["stock"]["catalog_mismatch_count"] == 0
    assert "uncataloged_symbols" in audit["stock"]
    assert db_path.read_bytes() == before
