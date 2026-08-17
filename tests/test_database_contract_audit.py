import sqlite3

from data_contract import audit_database, ensure_asset_type_column


def test_database_audit_counts_mixed_stock_daily_domain(tmp_path):
    db_path = tmp_path / "audit.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
        CREATE TABLE stock_daily (
            symbol TEXT, trade_date TEXT, open REAL, close REAL, high REAL,
            low REAL, volume REAL, amount REAL, amplitude REAL, pct_chg REAL,
            change_amount REAL, turnover_rate REAL
        );
        CREATE TABLE stock_daily_catalog (
            symbol TEXT PRIMARY KEY, price_mode TEXT NOT NULL, source TEXT NOT NULL,
            start_date TEXT NOT NULL, end_date TEXT NOT NULL, row_count INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE futures_min_bars (
            symbol TEXT, timeframe TEXT, trade_time TEXT, open REAL, high REAL,
            low REAL, close REAL, volume REAL
        );
        """)
        conn.execute(
            "INSERT INTO stock_daily VALUES "
            "('000001','2025-01-02',10,10,11,9,100,1000,2,0,0,1)"
        )
        conn.execute(
            "INSERT INTO stock_daily VALUES "
            "('AG_IDX','2025-01-02',10,10,11,9,100,1000,2,0,0,1)"
        )
        conn.execute("""
            INSERT INTO stock_daily_catalog
            (symbol, price_mode, source, start_date, end_date, row_count, updated_at)
            VALUES ('000001','QFQ','TEST','2025-01-02','2025-01-02',1,'now')
        """)
        ensure_asset_type_column(conn)
        conn.execute(
            "UPDATE stock_daily_catalog SET asset_type='STOCK'"
        )
        conn.execute(
            "INSERT INTO futures_min_bars VALUES "
            "('AG_IDX','5m','2025-01-02 09:05',10,11,9,10,0)"
        )

    result = audit_database(db_path)

    assert result["stock"]["index_rows"] == 1
    assert result["stock"]["uncataloged_symbols"] == 1
    assert result["futures_5m"]["zero_volume"] == 1
