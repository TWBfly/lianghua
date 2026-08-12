# Futures 5m Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean all TongDaXin 5-minute futures exports and atomically load them into the existing SQLite table used by backtests.

**Architecture:** Add one standard-library importer that parses each GB18030 tab-separated file into validated, de-duplicated rows before opening a single SQLite write transaction. Reuse `futures_min_bars` and its existing `(symbol, timeframe, trade_time)` primary key; replace only the imported symbols' `5m` rows.

**Tech Stack:** Python standard library (`csv`, `datetime`, `math`, `pathlib`, `sqlite3`), pytest, SQLite.

## Global Constraints

- Input is `data/export/*.txt`; target is `data/ashare_quant.db.futures_min_bars`.
- Symbols remove the terminal `L9` and append `_IDX`, including hyphenated codes such as `PP-F_IDX`.
- Store only `timeframe='5m'`; do not create derived timeframes or new database tables.
- Reject invalid timestamps, non-finite/non-positive OHLC, negative/non-finite volume, and inconsistent OHLC ranges.
- Keep the last duplicate timestamp in each file and import all files in one SQLite transaction.
- Do not modify unrelated symbols or non-`5m` rows.
- Add no dependencies.

---

### Task 1: Standard-library cleaner and atomic importer

**Files:**
- Create: `tests/test_import_futures_5m.py`
- Create: `code/import_futures_5m.py`

**Interfaces:**
- Consumes: GB18030 tab-separated exports named like `30#AGL9.txt`; the existing `futures_min_bars` schema.
- Produces: `symbol_from_path(path: Path) -> str`, `read_export(path: Path) -> tuple[list[tuple], dict[str, int]]`, and `import_exports(export_dir: Path = EXPORT_DIR, db_path: Path = DB_PATH) -> dict[str, int]`.

- [ ] **Step 1: Write the failing end-to-end test**

```python
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
```

- [ ] **Step 2: Run the test and verify RED**

Run: `pytest -q tests/test_import_futures_5m.py`

Expected: collection fails with `ModuleNotFoundError: No module named 'import_futures_5m'` because production code does not exist.

- [ ] **Step 3: Add the minimal implementation**

```python
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
                    all(math.isfinite(value) and value > 0
                        for value in (open_, high, low, close))
                    and math.isfinite(volume) and volume >= 0
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
                symbol, "5m", when, open_, high, low, close,
                volume, round(close * volume, 2),
            )
    rows = [bars[key] for key in sorted(bars)]
    return rows, {
        "raw": raw, "rows": len(rows),
        "invalid": invalid, "duplicates": duplicates,
    }


def import_exports(export_dir=EXPORT_DIR, db_path=DB_PATH):
    paths = sorted(Path(export_dir).glob("*.txt"))
    if not paths:
        raise ValueError(f"no export files in {export_dir}")
    symbols = [symbol_from_path(path) for path in paths]
    if len(symbols) != len(set(symbols)):
        raise ValueError("duplicate normalized symbol")
    totals = {"files": len(paths), "symbols": 0, "raw": 0,
              "rows": 0, "invalid": 0, "duplicates": 0}
    totals["symbols"] = len(symbols)

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
```

- [ ] **Step 4: Run focused and related tests and verify GREEN**

Run: `pytest -q tests/test_import_futures_5m.py tests/test_backtest_integration.py`

Expected: all selected tests pass with no warnings introduced by the importer.

- [ ] **Step 5: Commit the tested importer**

```bash
git add code/import_futures_5m.py tests/test_import_futures_5m.py
git commit -m "feat: import futures 5m exports"
```

### Task 2: Full import and database acceptance checks

**Files:**
- Modify data only: `data/ashare_quant.db`

**Interfaces:**
- Consumes: `import_exports()` from Task 1 and all `data/export/*.txt` files.
- Produces: 85 queryable `*_IDX` symbols at `timeframe='5m'` in `futures_min_bars`.

- [ ] **Step 1: Run the full import**

Run: `python code/import_futures_5m.py`

Expected: exit code 0 and a summary dictionary containing `files: 85`, `symbols: 85`, positive `rows`, and explicit invalid/duplicate counts.

- [ ] **Step 2: Verify aggregate database invariants**

Run:

```bash
sqlite3 -header -column data/ashare_quant.db "
SELECT COUNT(DISTINCT symbol) AS symbols, COUNT(*) AS rows,
       MIN(trade_time) AS first_bar, MAX(trade_time) AS last_bar
FROM futures_min_bars
WHERE timeframe='5m' AND symbol IN (
  SELECT DISTINCT substr(symbol, 1, length(symbol))
  FROM futures_min_bars WHERE timeframe='5m' AND symbol LIKE '%_IDX'
);
SELECT COUNT(*) AS invalid_rows
FROM futures_min_bars
WHERE timeframe='5m' AND (
  open<=0 OR high<=0 OR low<=0 OR close<=0 OR volume<0
  OR high<open OR high<low OR high<close
  OR low>open OR low>high OR low>close
);
SELECT COUNT(*) - COUNT(DISTINCT symbol || '|' || timeframe || '|' || trade_time)
       AS duplicate_keys
FROM futures_min_bars WHERE timeframe='5m';
"
```

Expected: `symbols` is at least 85, `rows` is positive, `invalid_rows=0`, and `duplicate_keys=0`.

- [ ] **Step 3: Verify the existing backtest query contract**

Run:

```bash
sqlite3 -header -column data/ashare_quant.db "
SELECT trade_time AS datetime, open, high, low, close, volume, amount
FROM futures_min_bars
WHERE symbol='AG_IDX' AND timeframe='5m'
ORDER BY trade_time DESC LIMIT 3;
"
```

Expected: three chronologically descending `AG_IDX` rows with non-null OHLCV and amount values.

- [ ] **Step 4: Run final regression verification**

Run: `pytest -q tests/test_import_futures_5m.py tests/test_backtest_integration.py`

Expected: all selected tests pass after the real database import.
