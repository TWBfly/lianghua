"""
Database repair and data contract reconciliation script for ashare_quant.db.
1. Backs up database before any modification.
2. Moves mixed futures _IDX rows from stock_daily into stock_daily_futures_archive.
3. Removes 1970 Unix Epoch / NULL dirty records from futures_min_bars.
4. Reconciles and verifies stock_daily_catalog (sets asset_type='STOCK', price_mode='QFQ', exact row counts and dates).
5. Runs audit_database() to confirm 0 mismatches and 0 uncataloged symbols.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CODE_DIR.parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from data_contract import audit_database, ensure_asset_type_column


DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "ashare_quant.db"


def repair_database(db_path: Path | str = DEFAULT_DB_PATH, make_backup: bool = True) -> dict:
    target_path = Path(db_path).resolve()
    if not target_path.is_file():
        raise FileNotFoundError(f"Database file not found: {target_path}")

    # 1. Audit before
    before_audit = audit_database(target_path)
    print(f"=== Database Audit BEFORE Repair ({target_path.name}) ===")
    print(before_audit)

    # 2. Make backup
    if make_backup:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = target_path.parent / f"{target_path.name}.backup_{timestamp}"
        shutil.copy2(target_path, backup_path)
        print(f"[Backup] Created database backup at: {backup_path}")

    # 3. Perform repair in transaction
    with sqlite3.connect(target_path) as conn:
        conn.execute("PRAGMA busy_timeout = 30000;")
        ensure_asset_type_column(conn)

        # 3a. Archive and delete futures _IDX rows in stock_daily
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_daily_futures_archive (
                symbol TEXT, trade_date TEXT, open REAL, close REAL, high REAL,
                low REAL, volume REAL, amount REAL, amplitude REAL, pct_chg REAL,
                change_amount REAL, turnover_rate REAL
            );
        """)
        conn.execute("""
            INSERT INTO stock_daily_futures_archive
            SELECT * FROM stock_daily WHERE symbol LIKE '%_IDX';
        """)
        deleted_futures = conn.execute(
            "DELETE FROM stock_daily WHERE symbol LIKE '%_IDX';"
        ).rowcount
        print(f"[Repair] Cleaned {deleted_futures} futures _IDX rows from stock_daily.")

        # 3b. Clean dirty 1970/NULL rows in futures_min_bars
        deleted_dirty_bars = conn.execute("""
            DELETE FROM futures_min_bars 
            WHERE trade_time LIKE '1970%' 
               OR trade_time < '2000-01-01' 
               OR open IS NULL 
               OR close IS NULL;
        """).rowcount
        print(f"[Repair] Cleaned {deleted_dirty_bars} dirty bar rows from futures_min_bars.")

        # 3c. Remove ghost records in stock_daily_catalog that don't exist in stock_daily
        deleted_ghost_catalog = conn.execute("""
            DELETE FROM stock_daily_catalog
            WHERE symbol NOT IN (SELECT DISTINCT symbol FROM stock_daily);
        """).rowcount
        print(f"[Repair] Removed {deleted_ghost_catalog} ghost symbols from stock_daily_catalog.")

        # 3d. Reconcile all actual stocks into stock_daily_catalog
        conn.execute("""
            INSERT INTO stock_daily_catalog (
                symbol, price_mode, source, start_date, end_date,
                row_count, asset_type, updated_at
            )
            SELECT 
                symbol,
                'QFQ',
                'AKSHARE_STOCK_ZH_A_HIST',
                MIN(trade_date),
                MAX(trade_date),
                COUNT(*),
                'STOCK',
                CURRENT_TIMESTAMP
            FROM stock_daily
            GROUP BY symbol
            ON CONFLICT(symbol) DO UPDATE SET
                price_mode='QFQ',
                source='AKSHARE_STOCK_ZH_A_HIST',
                start_date=excluded.start_date,
                end_date=excluded.end_date,
                row_count=excluded.row_count,
                asset_type='STOCK',
                updated_at=CURRENT_TIMESTAMP;
        """)
        print("[Repair] Reconciled stock_daily_catalog with 100% accurate rows, dates, and asset_type='STOCK'.")

        # 3e. Reconcile futures_series_metadata with actual row counts and dates from futures_min_bars
        conn.execute("""
            UPDATE futures_series_metadata
            SET row_count = (SELECT count(*) FROM futures_min_bars WHERE futures_min_bars.symbol = futures_series_metadata.symbol AND futures_min_bars.timeframe = futures_series_metadata.timeframe),
                start_time = (SELECT min(trade_time) FROM futures_min_bars WHERE futures_min_bars.symbol = futures_series_metadata.symbol AND futures_min_bars.timeframe = futures_series_metadata.timeframe),
                end_time = (SELECT max(trade_time) FROM futures_min_bars WHERE futures_min_bars.symbol = futures_series_metadata.symbol AND futures_min_bars.timeframe = futures_series_metadata.timeframe)
            WHERE EXISTS (SELECT 1 FROM futures_min_bars WHERE futures_min_bars.symbol = futures_series_metadata.symbol AND futures_min_bars.timeframe = futures_series_metadata.timeframe);
        """)
        print("[Repair] Reconciled futures_series_metadata with exact futures_min_bars counts and timestamps.")

    # 4. Audit after
    after_audit = audit_database(target_path)
    print(f"\n=== Database Audit AFTER Repair ({target_path.name}) ===")
    print(after_audit)

    # 5. Assertions
    assert after_audit["stock"]["index_rows"] == 0, "Index rows in stock_daily must be 0"
    assert after_audit["stock"]["uncataloged_symbols"] == 0, "Uncataloged stock symbols must be 0"
    assert after_audit["stock"]["catalog_mismatch_count"] == 0, "Catalog mismatch count must be 0"
    print("\n[Success] All data contracts successfully verified and reconciled!")
    return after_audit


if __name__ == "__main__":
    repair_database()
