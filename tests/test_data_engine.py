import sqlite3

import pandas as pd

import ashare_data_engine
from ashare_data_engine import AShareDataEngine


def history(symbol, closes):
    return pd.DataFrame({
        "股票代码": [symbol] * len(closes),
        "日期": pd.date_range("2024-01-01", periods=len(closes)),
        "开盘": closes,
        "收盘": closes,
        "最高": [value + 1 for value in closes],
        "最低": [value - 1 for value in closes],
        "成交量": [1_000] * len(closes),
        "成交额": [10_000] * len(closes),
        "振幅": [2.0] * len(closes),
        "涨跌幅": [0.0] * len(closes),
        "涨跌额": [0.0] * len(closes),
        "换手率": [1.0] * len(closes),
    })


def insert_bar(conn, symbol, date, close):
    conn.execute(
        "INSERT INTO stock_daily VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            symbol, date, close, close, close + 1, close - 1,
            1_000, 10_000, 2.0, 0.0, 0.0, 1.0,
        ),
    )


def test_qfq_sync_replaces_full_symbol_history_atomically(
        tmp_path, monkeypatch):
    engine = AShareDataEngine(tmp_path / "quant.db")
    with sqlite3.connect(engine.db_path) as conn:
        insert_bar(conn, "000001", "2023-01-01", 99.0)
        insert_bar(conn, "000002", "2024-01-01", 20.0)

    calls = []

    def fetch(**kwargs):
        calls.append(kwargs)
        result = history("000001", [10.0, 11.0])
        result["日期"] = pd.to_datetime(["2023-01-01", "2024-01-02"])
        return result

    monkeypatch.setattr(
        ashare_data_engine.ak, "stock_zh_a_hist", fetch
    )
    monkeypatch.setattr(ashare_data_engine.time, "sleep", lambda _: None)

    engine.sync_stock_daily(
        symbols=["000001"],
        start_date="20240101",
        end_date="20240103",
    )

    assert calls[0]["start_date"] == "20230101"
    with sqlite3.connect(engine.db_path) as conn:
        refreshed = conn.execute(
            "SELECT trade_date, close FROM stock_daily "
            "WHERE symbol='000001' ORDER BY trade_date"
        ).fetchall()
        untouched = conn.execute(
            "SELECT close FROM stock_daily WHERE symbol='000002'"
        ).fetchone()[0]
    assert refreshed == [("2023-01-01", 10.0),
                         ("2024-01-02", 11.0)]
    assert untouched == 20.0


def test_empty_qfq_refresh_preserves_existing_rows(tmp_path, monkeypatch):
    engine = AShareDataEngine(tmp_path / "quant.db")
    with sqlite3.connect(engine.db_path) as conn:
        insert_bar(conn, "000001", "2024-01-01", 10.0)

    monkeypatch.setattr(
        ashare_data_engine.ak,
        "stock_zh_a_hist",
        lambda *_, **__: pd.DataFrame(),
    )
    monkeypatch.setattr(
        ashare_data_engine.ak,
        "stock_zh_a_daily",
        lambda *_, **__: pd.DataFrame(),
    )
    monkeypatch.setattr(ashare_data_engine.time, "sleep", lambda _: None)

    result = engine.sync_stock_daily(
        symbols=["000001"],
        start_date="20240101",
        end_date="20240103",
    )

    assert result == {
        "requested": 1,
        "committed": [],
        "unchanged": [],
        "empty": ["000001"],
        "failed": [],
    }

    with sqlite3.connect(engine.db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM stock_daily WHERE symbol='000001'"
        ).fetchone()[0] == 1


def test_partial_qfq_refresh_preserves_existing_history(tmp_path, monkeypatch):
    engine = AShareDataEngine(tmp_path / "quant.db")
    with sqlite3.connect(engine.db_path) as conn:
        for day, close in enumerate([10.0, 11.0, 12.0], 1):
            insert_bar(conn, "000001", f"2024-01-0{day}", close)
        conn.execute("""
            INSERT INTO stock_daily_catalog VALUES (
                '000001', 'QFQ', 'OLD', '2024-01-01', '2024-01-03', 3,
                '2024-01-04 00:00:00'
            )
        """)

    partial = history("000001", [10.0, 12.0, 13.0])
    partial["日期"] = pd.to_datetime([
        "2024-01-01", "2024-01-03", "2024-01-04",
    ])
    monkeypatch.setattr(
        ashare_data_engine.ak,
        "stock_zh_a_hist",
        lambda **_: partial,
    )
    monkeypatch.setattr(ashare_data_engine.time, "sleep", lambda _: None)

    engine.sync_stock_daily(
        symbols=["000001"],
        start_date="20240101",
        end_date="20240104",
    )

    with sqlite3.connect(engine.db_path) as conn:
        assert conn.execute(
            "SELECT trade_date, close FROM stock_daily "
            "WHERE symbol='000001' ORDER BY trade_date"
        ).fetchall() == [
            ("2024-01-01", 10.0),
            ("2024-01-02", 11.0),
            ("2024-01-03", 12.0),
        ]
        assert conn.execute(
            "SELECT source, row_count FROM stock_daily_catalog "
            "WHERE symbol='000001'"
        ).fetchone() == ("OLD", 3)


def test_qfq_backfill_preserves_newer_existing_history(tmp_path, monkeypatch):
    engine = AShareDataEngine(tmp_path / "quant.db")
    with sqlite3.connect(engine.db_path) as conn:
        insert_bar(conn, "000001", "2024-01-01", 10.0)
        insert_bar(conn, "000001", "2026-01-01", 12.0)

    calls = []

    def fetch(**kwargs):
        calls.append(kwargs)
        result = history("000001", [9.0, 12.0])
        result["日期"] = pd.to_datetime(["2020-01-01", "2026-01-01"])
        return result

    monkeypatch.setattr(
        ashare_data_engine.ak, "stock_zh_a_hist", fetch
    )
    monkeypatch.setattr(ashare_data_engine.time, "sleep", lambda _: None)

    engine.sync_stock_daily(
        symbols=["000001"],
        start_date="20200101",
        end_date="20250101",
    )

    assert calls[0]["end_date"] == "20260101"


def test_qfq_refresh_updates_provenance_atomically(tmp_path, monkeypatch):
    engine = AShareDataEngine(tmp_path / "quant.db")
    monkeypatch.setattr(
        ashare_data_engine.ak,
        "stock_zh_a_hist",
        lambda **_: history("000001", [10.0, 11.0]),
    )
    monkeypatch.setattr(ashare_data_engine.time, "sleep", lambda _: None)

    engine.sync_stock_daily(
        symbols=["000001"],
        start_date="20240101",
        end_date="20240103",
    )

    provenance = engine.get_stock_daily_provenance("000001")
    assert {key: provenance[key] for key in (
        "symbol", "price_mode", "source", "start_date", "end_date",
        "row_count",
    )} == {
        "symbol": "000001",
        "price_mode": "QFQ",
        "source": "AKSHARE_STOCK_ZH_A_HIST",
        "start_date": "2024-01-01",
        "end_date": "2024-01-02",
        "row_count": 2,
    }
    assert provenance["updated_at"]
    assert provenance["verification_status"] == "VERIFIED"


def test_qfq_catalog_failure_rolls_back_price_replacement(
        tmp_path, monkeypatch):
    engine = AShareDataEngine(tmp_path / "quant.db")
    with sqlite3.connect(engine.db_path) as conn:
        insert_bar(conn, "000001", "2024-01-01", 99.0)
        conn.execute("""
            INSERT INTO stock_daily_catalog VALUES (
                '000001', 'QFQ', 'OLD', '2024-01-01', '2024-01-01', 1,
                '2024-01-02 00:00:00'
            )
        """)
        conn.execute("""
            CREATE TRIGGER fail_catalog
            BEFORE UPDATE ON stock_daily_catalog
            BEGIN
                SELECT RAISE(ABORT, 'catalog failure');
            END
        """)
    monkeypatch.setattr(
        ashare_data_engine.ak,
        "stock_zh_a_hist",
        lambda **_: history("000001", [10.0, 11.0]),
    )
    monkeypatch.setattr(ashare_data_engine.time, "sleep", lambda _: None)

    engine.sync_stock_daily(
        symbols=["000001"],
        start_date="20240101",
        end_date="20240103",
    )

    with sqlite3.connect(engine.db_path) as conn:
        assert conn.execute(
            "SELECT close FROM stock_daily WHERE symbol='000001'"
        ).fetchall() == [(99.0,)]
        assert conn.execute(
            "SELECT source FROM stock_daily_catalog WHERE symbol='000001'"
        ).fetchone()[0] == "OLD"


def test_qfq_provider_error_is_reported_not_counted(tmp_path, monkeypatch):
    engine = AShareDataEngine(tmp_path / "quant.db")

    def fail(**_):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(ashare_data_engine.ak, "stock_zh_a_hist", fail)
    monkeypatch.setattr(ashare_data_engine.ak, "stock_zh_a_daily", fail)
    monkeypatch.setattr(ashare_data_engine.time, "sleep", lambda _: None)

    result = engine.sync_stock_daily(
        symbols=["000001"],
        start_date="20240101",
        end_date="20240103",
    )

    assert result["committed"] == []
    assert result["empty"] == []
    assert result["failed"] == [{
        "symbol": "000001",
        "error": "provider unavailable",
    }]


def test_verified_covered_symbol_is_reported_unchanged(
        tmp_path, monkeypatch):
    engine = AShareDataEngine(tmp_path / "quant.db")
    with sqlite3.connect(engine.db_path) as conn:
        insert_bar(conn, "000001", "2024-01-01", 10.0)
        conn.execute("""
            INSERT INTO stock_daily_catalog VALUES (
                '000001', 'QFQ', 'TEST', '2024-01-01', '2024-01-01', 1,
                '2024-01-02 00:00:00'
            )
        """)

    def unexpected_fetch(**_):
        raise AssertionError("verified data should not refresh")

    monkeypatch.setattr(
        ashare_data_engine.ak, "stock_zh_a_hist", unexpected_fetch
    )

    result = engine.sync_stock_daily(
        symbols=["000001"],
        start_date="20240101",
        end_date="20240101",
    )

    assert result == {
        "requested": 1,
        "committed": [],
        "unchanged": ["000001"],
        "empty": [],
        "failed": [],
    }


def test_uncataloged_covered_symbol_is_refreshed(tmp_path, monkeypatch):
    engine = AShareDataEngine(tmp_path / "quant.db")
    with sqlite3.connect(engine.db_path) as conn:
        insert_bar(conn, "000001", "2024-01-01", 99.0)
    calls = []

    def fetch(**kwargs):
        calls.append(kwargs)
        return history("000001", [10.0])

    monkeypatch.setattr(ashare_data_engine.ak, "stock_zh_a_hist", fetch)
    monkeypatch.setattr(ashare_data_engine.time, "sleep", lambda _: None)

    result = engine.sync_stock_daily(
        symbols=["000001"],
        start_date="20240101",
        end_date="20240101",
    )

    assert calls
    assert result["committed"] == ["000001"]
    assert engine.get_stock_daily_provenance("000001")[
        "verification_status"
    ] == "VERIFIED"


def test_stock_basic_refresh_preserves_symbol_primary_key(
        tmp_path, monkeypatch):
    db_path = tmp_path / "quant.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE stock_basic (
                symbol TEXT, name TEXT, price REAL, pe_ttm REAL, pb REAL,
                total_mv REAL, circ_mv REAL, updated_at TEXT
            )
        """)
        conn.execute(
            "INSERT INTO stock_basic VALUES "
            "('old', 'old', 1, 1, 1, 1, 1, 'old')"
        )

    spot = pd.DataFrame({
        "代码": ["000001"],
        "名称": ["平安银行"],
        "最新价": [10.0],
        "市盈率-动态": [6.0],
        "市净率": [0.7],
        "总市值": [100.0],
        "流通市值": [90.0],
    })
    monkeypatch.setattr(
        ashare_data_engine.ak, "stock_zh_a_spot_em", lambda: spot
    )

    engine = AShareDataEngine(db_path)
    engine.sync_stock_basic()

    with sqlite3.connect(db_path) as conn:
        columns = conn.execute("PRAGMA table_info(stock_basic)").fetchall()
        rows = conn.execute(
            "SELECT symbol, name FROM stock_basic"
        ).fetchall()
    symbol = next(column for column in columns if column[1] == "symbol")
    assert symbol[5] == 1
    assert rows == [("000001", "平安银行")]
