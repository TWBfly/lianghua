import sqlite3

import pandas as pd

import ashare_financial_fetcher
from ashare_financial_fetcher import AShareFinancialFetcher
from munger_stock_screener import MungerStockScreener


def create_basic_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_basic (
            symbol TEXT PRIMARY KEY,
            name TEXT,
            price REAL,
            pe_ttm REAL,
            pb REAL,
            total_mv REAL,
            circ_mv REAL,
            updated_at TEXT
        )
    """)


def insert_basic(conn, symbol="000001", pe=10.0, pb=1.0):
    conn.execute(
        "INSERT INTO stock_basic VALUES (?, '样本', 10, ?, ?, "
        "20000000000, 18000000000, '2026-01-01')",
        (symbol, pe, pb),
    )


def insert_income(conn, symbol="000001", profit=100_000_000):
    conn.execute(
        "INSERT INTO stock_income_statement VALUES "
        "(?, '2025-12-31', '样本', 1000000000, ?, '2026-03-01')",
        (symbol, profit),
    )


def test_missing_fundamentals_are_unknown_not_passed(tmp_path):
    fetcher = AShareFinancialFetcher(tmp_path / "quant.db")
    with fetcher.get_connection() as conn:
        create_basic_table(conn)
        result = fetcher.audit_financial_quality("000001", conn=conn)

    assert result["status"] == "UNKNOWN"
    assert result["is_passed"] is False
    assert result["quality_score"] is None
    assert all(
        check["status"] == "UNKNOWN"
        for check in result["checks"].values()
    )


def test_real_partial_fields_do_not_fabricate_roe_or_cash_flow(tmp_path):
    fetcher = AShareFinancialFetcher(tmp_path / "quant.db")
    with fetcher.get_connection() as conn:
        create_basic_table(conn)
        insert_basic(conn)
        insert_income(conn)
        result = fetcher.audit_financial_quality("000001", conn=conn)

    assert result["status"] == "UNKNOWN"
    assert result["is_passed"] is False
    assert result["roe_est"] is None
    assert result["cfo_ratio"] is None
    assert result["checks"]["valuation"]["status"] == "PASS"
    assert result["checks"]["reported_profit"]["status"] == "PASS"
    assert result["checks"]["roe"]["status"] == "UNKNOWN"
    assert result["checks"]["cash_flow"]["status"] == "UNKNOWN"
    assert result["checks"]["point_in_time"]["status"] == "UNKNOWN"


def test_reported_loss_is_a_real_failure(tmp_path):
    fetcher = AShareFinancialFetcher(tmp_path / "quant.db")
    with fetcher.get_connection() as conn:
        create_basic_table(conn)
        insert_basic(conn)
        insert_income(conn, profit=-1)
        result = fetcher.audit_financial_quality("000001", conn=conn)

    assert result["status"] == "FAIL"
    assert result["is_passed"] is False
    assert result["checks"]["reported_profit"]["status"] == "FAIL"


def test_database_error_never_fails_open(tmp_path):
    fetcher = AShareFinancialFetcher(tmp_path / "quant.db")
    conn = fetcher.get_connection()
    conn.close()

    result = fetcher.audit_financial_quality("000001", conn=conn)

    assert result["status"] == "UNKNOWN"
    assert result["is_passed"] is False
    assert result["quality_score"] is None


def test_financial_reads_bind_symbol_as_data(tmp_path, monkeypatch):
    fetcher = AShareFinancialFetcher(tmp_path / "quant.db")
    with fetcher.get_connection() as conn:
        create_basic_table(conn)
        insert_income(conn, symbol="000001")
        conn.execute(
            "INSERT INTO stock_notices VALUES "
            "('000001', '样本', '公告', '其他', '2026-01-01', 'now')"
        )
        income = fetcher.get_income_statement(
            "000001' OR 1=1 --", conn=conn
        )
        notices = fetcher.get_company_notices(
            "000001' OR 1=1 --", conn=conn
        )

    assert income.empty
    assert notices.empty


def test_legacy_munger_screener_returns_only_truthful_snapshot(tmp_path):
    db_path = tmp_path / "quant.db"
    fetcher = AShareFinancialFetcher(db_path)
    with fetcher.get_connection() as conn:
        create_basic_table(conn)
        insert_basic(conn)

    result = MungerStockScreener(db_path).screen_wonderful_companies()

    assert result["symbol"].tolist() == ["000001"]
    assert result["fundamental_status"].tolist() == ["UNKNOWN"]
    assert result["data_scope"].tolist() == ["CURRENT_VALUATION_SNAPSHOT"]
    assert "roe_est_pct" not in result
