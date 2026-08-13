"""Import TongDaXin futures 5-minute exports into SQLite."""

import argparse
import csv
import hashlib
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
EXPORT_DIR = DATA_DIR / "export"
DB_PATH = DATA_DIR / "ashare_quant.db"
HEADER = ["日期", "时间", "开盘", "最高", "最低", "收盘", "成交量", "持仓量", "结算价"]
INSERT_SQL = """
INSERT INTO futures_min_bars (
    symbol, timeframe, trade_time, open, high, low, close,
    volume, amount, open_interest, settlement
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def symbol_from_path(path):
    code = path.stem.split("#", 1)[-1].upper()
    if not code.endswith("L9") or len(code) <= 2:
        raise ValueError(f"unsupported export filename: {path.name}")
    return f"{code[:-2]}_IDX"


def _series_type(title):
    if "月均价加权" in title:
        return "MONTHLY_AVERAGE_WEIGHTED_INDEX"
    if "加权" in title:
        return "WEIGHTED_INDEX"
    raise ValueError(f"unsupported futures series title: {title}")


def ensure_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS futures_min_bars (
            symbol TEXT, timeframe TEXT, trade_time TEXT,
            open REAL, high REAL, low REAL, close REAL,
            volume REAL, amount REAL,
            PRIMARY KEY (symbol, timeframe, trade_time)
        )
    """)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(futures_min_bars)")}
    for name in ("open_interest", "settlement"):
        if name not in columns:
            conn.execute(f"ALTER TABLE futures_min_bars ADD COLUMN {name} REAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS futures_series_metadata (
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            source_file TEXT NOT NULL,
            source_title TEXT NOT NULL,
            series_type TEXT NOT NULL CHECK (
                series_type IN (
                    'WEIGHTED_INDEX', 'MONTHLY_AVERAGE_WEIGHTED_INDEX'
                )
            ),
            source_encoding TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            PRIMARY KEY (symbol, timeframe)
        )
    """)


def read_export(path):
    path = Path(path)
    symbol = symbol_from_path(path)
    rows = []
    previous_when = None
    with path.open(encoding="gb18030", newline="") as stream:
        reader = csv.reader(stream, delimiter="\t")
        try:
            title = next(reader)[0].strip()
            header = [field.strip() for field in next(reader)]
        except (IndexError, StopIteration) as exc:
            raise ValueError(f"malformed export: {path.name}") from exc
        if header != HEADER:
            raise ValueError(f"unsupported export header: {path.name}")
        for line_number, fields in enumerate(reader, start=3):
            if fields == ["#数据来源:通达信"]:
                if next(reader, None) is not None:
                    raise ValueError(f"malformed row {line_number} in {path.name}")
                break
            if len(fields) != 9:
                raise ValueError(f"malformed row {line_number} in {path.name}")
            try:
                when = datetime.strptime(
                    fields[0].strip() + fields[1].strip().zfill(4),
                    "%Y/%m/%d%H%M",
                )
                while previous_when is not None and when <= previous_when:
                    when += timedelta(days=1)
                open_, high, low, close, volume, open_interest, settlement = map(
                    float, fields[2:9]
                )
            except ValueError as exc:
                raise ValueError(f"malformed row {line_number} in {path.name}") from exc
            values = (open_, high, low, close, volume, open_interest, settlement)
            if (
                not all(math.isfinite(value) for value in values)
                or min(open_, high, low, close) <= 0
                or volume < 0
                or high < max(open_, low, close)
                or low > min(open_, high, close)
            ):
                raise ValueError(f"invalid OHLC row {line_number} in {path.name}")
            previous_when = when
            when = when.strftime("%Y-%m-%d %H:%M:%S")
            rows.append((
                symbol, "5m", when, open_, high, low, close,
                volume, None, open_interest, settlement,
            ))
    if not rows:
        raise ValueError(f"no bars in {path.name}")
    metadata = {
        "symbol": symbol,
        "timeframe": "5m",
        "source_file": path.name,
        "source_title": title,
        "series_type": _series_type(title),
        "source_encoding": "gb18030",
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "row_count": len(rows),
        "start_time": rows[0][2],
        "end_time": rows[-1][2],
        "imported_at": datetime.now(timezone.utc).isoformat(),
    }
    return rows, {"raw": len(rows), "rows": len(rows), "invalid": 0, "duplicates": 0}, metadata


def import_exports(export_dir=EXPORT_DIR, db_path=DB_PATH, replace_existing=False):
    paths = sorted(Path(export_dir).glob("*.txt"))
    if not paths:
        raise ValueError(f"no export files in {export_dir}")
    symbols = [symbol_from_path(path) for path in paths]
    if len(symbols) != len(set(symbols)):
        raise ValueError("duplicate normalized symbol")
    totals = {
        "files": len(paths), "symbols": len(symbols), "raw": 0,
        "rows": 0, "invalid": 0, "duplicates": 0,
    }

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        for path in paths:
            rows, report, metadata = read_export(path)
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    "SELECT COUNT(*) FROM futures_min_bars WHERE symbol=? AND timeframe=?",
                    (metadata["symbol"], metadata["timeframe"]),
                ).fetchone()[0]
                if existing and not replace_existing:
                    raise ValueError("existing bars require --replace-existing")
                if replace_existing:
                    conn.execute(
                        "DELETE FROM futures_min_bars WHERE symbol=? AND timeframe=?",
                        (metadata["symbol"], metadata["timeframe"]),
                    )
                conn.executemany(INSERT_SQL, rows)
                conn.execute("""
                    INSERT INTO futures_series_metadata (
                        symbol, timeframe, source_file, source_title, series_type,
                        source_encoding, source_sha256, row_count, start_time, end_time,
                        imported_at
                    ) VALUES (
                        :symbol, :timeframe, :source_file, :source_title, :series_type,
                        :source_encoding, :source_sha256, :row_count, :start_time, :end_time,
                        :imported_at
                    ) ON CONFLICT(symbol, timeframe) DO UPDATE SET
                        source_file=excluded.source_file,
                        source_title=excluded.source_title,
                        series_type=excluded.series_type,
                        source_encoding=excluded.source_encoding,
                        source_sha256=excluded.source_sha256,
                        row_count=excluded.row_count,
                        start_time=excluded.start_time,
                        end_time=excluded.end_time,
                        imported_at=excluded.imported_at
                """, metadata)
            for key, value in report.items():
                totals[key] += value
    return totals


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-dir", type=Path, default=EXPORT_DIR)
    parser.add_argument("--db-path", type=Path, default=DB_PATH)
    parser.add_argument("--replace-existing", action="store_true")
    args = parser.parse_args(argv)
    print(import_exports(
        args.export_dir,
        args.db_path,
        replace_existing=args.replace_existing,
    ))


if __name__ == "__main__":
    main()
