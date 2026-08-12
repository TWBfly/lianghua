import sqlite3

from import_futures_5m import import_exports


def test_import_exports_cleans_and_replaces_only_target_5m(tmp_path):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    text = """AGL9 白银加权 5分钟线 不复权
      日期\t    时间\t    开盘\t    最高\t    最低\t    收盘\t    成交量\t    持仓量\t    结算价
2026/08/12\t0905\t10\t12\t9\t11\t5\t100\t0
2026/08/12\t0905\t11\t13\t10\t12\t6\t101\t0
2026/08/12\t0910\t10\t9\t8\t11\t5\t100\t0
2026/08/12\t0915\t12\t14\t11\t13\t7\t102\t0
#数据来源:通达信
"""
    (export_dir / "30#AGL9.txt").write_bytes(text.encode("gb18030"))
    db_path = tmp_path / "quant.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE futures_min_bars (
                symbol TEXT, timeframe TEXT, trade_time TEXT,
                open REAL, high REAL, low REAL, close REAL,
                volume REAL, amount REAL,
                PRIMARY KEY (symbol, timeframe, trade_time)
            )
        """)
        conn.executemany(
            "INSERT INTO futures_min_bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("AG_IDX", "5m", "2020-01-01 09:05:00", 1, 1, 1, 1, 1, 1),
                ("AG_IDX", "15m", "2020-01-01 09:15:00", 1, 1, 1, 1, 1, 1),
                ("OTHER_IDX", "5m", "2020-01-01 09:05:00", 1, 1, 1, 1, 1, 1),
            ],
        )

    result = import_exports(export_dir, db_path)
    import_exports(export_dir, db_path)

    assert result == {
        "files": 1, "symbols": 1, "raw": 4,
        "rows": 2, "invalid": 1, "duplicates": 1,
    }
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT trade_time, open, high, low, close, volume, amount "
            "FROM futures_min_bars WHERE symbol='AG_IDX' AND timeframe='5m' "
            "ORDER BY trade_time"
        ).fetchall() == [
            ("2026-08-12 09:05:00", 11.0, 13.0, 10.0, 12.0, 6.0, 72.0),
            ("2026-08-12 09:15:00", 12.0, 14.0, 11.0, 13.0, 7.0, 91.0),
        ]
        assert conn.execute(
            "SELECT COUNT(*) FROM futures_min_bars "
            "WHERE (symbol='AG_IDX' AND timeframe='15m') "
            "OR symbol='OTHER_IDX'"
        ).fetchone()[0] == 2
