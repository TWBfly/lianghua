"""Clean TongDaXin futures 5-minute exports into the backtest SQLite database."""

import csv
import math
import sqlite3
from datetime import datetime
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent.parent / "data"
EXPORT_DIR = DATA_DIR / "export"
DB_PATH = DATA_DIR / "ashare_quant.db"
INSERT_SQL = "INSERT INTO futures_min_bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"


def symbol_from_path(path):
    code = path.stem.split("#", 1)[-1].upper()
    if not code.endswith("L9") or len(code) <= 2:
        raise ValueError(f"unsupported export filename: {path.name}")
    return f"{code[:-2]}_IDX"


def read_export(path):
    symbol = symbol_from_path(path)
    bars = {}
    raw = invalid = duplicates = 0
    with path.open(encoding="gb18030", newline="") as stream:
        reader = csv.reader(stream, delimiter="\t")
        next(reader, None)
        next(reader, None)
        for fields in reader:
            if not fields or fields[0].strip().startswith("#"):
                continue
            raw += 1
            try:
                when = datetime.strptime(
                    fields[0].strip() + fields[1].strip().zfill(4),
                    "%Y/%m/%d%H%M",
                ).strftime("%Y-%m-%d %H:%M:%S")
                open_, high, low, close, volume = map(float, fields[2:7])
                valid = (
                    all(
                        math.isfinite(value) and value > 0
                        for value in (open_, high, low, close)
                    )
                    and math.isfinite(volume)
                    and volume >= 0
                    and high >= max(open_, low, close)
                    and low <= min(open_, high, close)
                )
                if not valid:
                    raise ValueError("invalid OHLCV")
            except (IndexError, TypeError, ValueError):
                invalid += 1
                continue
            duplicates += when in bars
            bars[when] = (
                symbol,
                "5m",
                when,
                open_,
                high,
                low,
                close,
                volume,
                round(close * volume, 2),
            )
    rows = [bars[key] for key in sorted(bars)]
    return rows, {
        "raw": raw,
        "rows": len(rows),
        "invalid": invalid,
        "duplicates": duplicates,
    }


def import_exports(export_dir=EXPORT_DIR, db_path=DB_PATH):
    paths = sorted(Path(export_dir).glob("*.txt"))
    if not paths:
        raise ValueError(f"no export files in {export_dir}")
    symbols = [symbol_from_path(path) for path in paths]
    if len(symbols) != len(set(symbols)):
        raise ValueError("duplicate normalized symbol")
    totals = {
        "files": len(paths),
        "symbols": len(symbols),
        "raw": 0,
        "rows": 0,
        "invalid": 0,
        "duplicates": 0,
    }

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS futures_min_bars (
                symbol TEXT, timeframe TEXT, trade_time TEXT,
                open REAL, high REAL, low REAL, close REAL,
                volume REAL, amount REAL,
                PRIMARY KEY (symbol, timeframe, trade_time)
            )
        """)
        for path, symbol in zip(paths, symbols):
            rows, report = read_export(path)
            if not rows:
                raise ValueError(f"no valid bars in {path.name}")
            conn.execute(
                "DELETE FROM futures_min_bars WHERE symbol=? AND timeframe='5m'",
                (symbol,),
            )
            conn.executemany(INSERT_SQL, rows)
            for key, value in report.items():
                totals[key] += value
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return totals


if __name__ == "__main__":
    print(import_exports())
