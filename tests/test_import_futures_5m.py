import hashlib
import sqlite3

import pytest

from import_futures_5m import import_exports


VALID_EXPORT = """AGL9 白银加权 5分钟线 不复权
日期\t时间\t开盘\t最高\t最低\t收盘\t成交量\t持仓量\t结算价
2026/08/12\t0905\t10\t12\t9\t11\t5\t100\t10.5
2026/08/12\t0910\t11\t13\t10\t12\t6\t101\t11.5
"""


def _write_export(directory, text=VALID_EXPORT):
    path = directory / "30#AGL9.txt"
    path.write_bytes(text.encode("gb18030"))
    return path


def _counts(db_path):
    with sqlite3.connect(db_path) as conn:
        return tuple(
            conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("futures_min_bars", "futures_series_metadata")
        )


def test_import_preserves_source_fields_and_provenance(tmp_path):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    source = _write_export(export_dir)
    db_path = tmp_path / "quant.db"

    result = import_exports(export_dir, db_path)

    assert result == {
        "files": 1, "symbols": 1, "raw": 2,
        "rows": 2, "invalid": 0, "duplicates": 0,
    }
    with sqlite3.connect(db_path) as conn:
        bars = conn.execute(
            "SELECT trade_time, open, high, low, close, volume, amount, "
            "open_interest, settlement FROM futures_min_bars ORDER BY trade_time"
        ).fetchall()
        metadata = conn.execute(
            "SELECT source_file, source_title, series_type, source_encoding, "
            "source_sha256, row_count, start_time, end_time "
            "FROM futures_series_metadata WHERE symbol='AG_IDX' AND timeframe='5m'"
        ).fetchone()
    assert bars == [
        ("2026-08-12 09:05:00", 10.0, 12.0, 9.0, 11.0, 5.0, None, 100.0, 10.5),
        ("2026-08-12 09:10:00", 11.0, 13.0, 10.0, 12.0, 6.0, None, 101.0, 11.5),
    ]
    assert metadata == (
        source.name,
        "AGL9 白银加权 5分钟线 不复权",
        "WEIGHTED_INDEX",
        "gb18030",
        hashlib.sha256(source.read_bytes()).hexdigest(),
        2,
        "2026-08-12 09:05:00",
        "2026-08-12 09:10:00",
    )


def test_import_accepts_tongdaxin_source_footer(tmp_path):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    _write_export(export_dir, VALID_EXPORT + "#数据来源:通达信\n")

    result = import_exports(export_dir, tmp_path / "quant.db")

    assert result["rows"] == 2


@pytest.mark.parametrize(
    "suffix",
    [
        "#数据来源:通达信\n2026/08/12\t0915\t12\t14\t11\t13\t7\t102\t12.5\n",
        "#数据来源:通达信\n\n",
        "#数据来源:通达信\t\n",
        " #数据来源:通达信\n",
    ],
    ids=["valid_row_after_footer", "blank_after_footer", "trailing_tab", "leading_space"],
)
def test_import_rejects_non_exact_or_non_final_source_footer(tmp_path, suffix):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    _write_export(export_dir, VALID_EXPORT + suffix)

    with pytest.raises(ValueError, match="malformed row"):
        import_exports(export_dir, tmp_path / "quant.db")


@pytest.mark.parametrize(
    "text",
    [
        VALID_EXPORT.replace("\t12\t9\t11\t5", "\t9\t8\t11\t5", 1),
        VALID_EXPORT.replace(
            "2026/08/12\t0910", "2026/08/12\t0905", 1
        ),
        VALID_EXPORT.replace("白银加权", "白银主连"),
    ],
    ids=["invalid_ohlc", "duplicate_timestamp", "unknown_title"],
)
def test_invalid_export_rolls_back_bars_and_metadata(tmp_path, text):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    _write_export(export_dir, text)
    db_path = tmp_path / "quant.db"

    with pytest.raises(ValueError):
        import_exports(export_dir, db_path)

    assert _counts(db_path) == (0, 0)


@pytest.mark.parametrize(
    "text",
    [
        VALID_EXPORT.replace("成交量", "成交额", 1),
        VALID_EXPORT.replace("成交量\t持仓量", "持仓量\t成交量", 1),
    ],
    ids=["wrong_column_name", "wrong_column_order"],
)
def test_import_rejects_export_with_drifted_header(tmp_path, text):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    _write_export(export_dir, text)

    with pytest.raises(ValueError, match="header"):
        import_exports(export_dir, tmp_path / "quant.db")


def test_import_requires_explicit_replacement_and_preserves_other_series(tmp_path):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    _write_export(export_dir)
    db_path = tmp_path / "quant.db"

    import_exports(export_dir, db_path)
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO futures_min_bars "
            "(symbol, timeframe, trade_time, open, high, low, close, volume, amount) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("AG_IDX", "15m", "2020-01-01 09:15:00", 1, 1, 1, 1, 1, None),
                ("OTHER_IDX", "5m", "2020-01-01 09:05:00", 1, 1, 1, 1, 1, None),
            ],
        )

    with pytest.raises(ValueError, match="--replace-existing"):
        import_exports(export_dir, db_path)
    import_exports(export_dir, db_path, replace_existing=True)

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM futures_min_bars "
            "WHERE symbol='AG_IDX' AND timeframe='5m'"
        ).fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM futures_min_bars "
            "WHERE (symbol='AG_IDX' AND timeframe='15m') OR symbol='OTHER_IDX'"
        ).fetchone()[0] == 2


def test_replace_rolls_back_bars_and_metadata_when_metadata_upsert_fails(tmp_path):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    _write_export(export_dir)
    db_path = tmp_path / "quant.db"
    import_exports(export_dir, db_path)

    with sqlite3.connect(db_path) as conn:
        old_bars = conn.execute(
            "SELECT * FROM futures_min_bars WHERE symbol='AG_IDX' AND timeframe='5m'"
        ).fetchall()
        old_metadata = conn.execute(
            "SELECT * FROM futures_series_metadata "
            "WHERE symbol='AG_IDX' AND timeframe='5m'"
        ).fetchall()
        conn.execute("""
            CREATE TRIGGER fail_metadata_update
            BEFORE UPDATE ON futures_series_metadata
            BEGIN
                SELECT RAISE(ABORT, 'metadata upsert failure');
            END
        """)

    _write_export(
        export_dir,
        VALID_EXPORT.replace("\t10\t12\t9\t11\t5\t100", "\t20\t22\t19\t21\t5\t100", 1),
    )
    with pytest.raises(sqlite3.IntegrityError, match="metadata upsert failure"):
        import_exports(export_dir, db_path, replace_existing=True)

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT * FROM futures_min_bars WHERE symbol='AG_IDX' AND timeframe='5m'"
        ).fetchall() == old_bars
        assert conn.execute(
            "SELECT * FROM futures_series_metadata "
            "WHERE symbol='AG_IDX' AND timeframe='5m'"
        ).fetchall() == old_metadata
