"""
Import and clean silver index (AGL9) multi-timeframe data from TongDaXin exported XLS files into ashare_quant.db.
Supports timeframes: 5m, 10m, 15m, 30m, 1h, 1d.
"""

import os
import sqlite3
import pandas as pd
import numpy as np

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
DB_PATH = os.path.join(DATA_DIR, "ashare_quant.db")

XLS_FILES = {
    "5m": os.path.join(DATA_DIR, "AGL9-5m.xls"),
    "10m": os.path.join(DATA_DIR, "AGL9-10m.xls"),
    "15m": os.path.join(DATA_DIR, "AGL9-15m.xls"),
    "30m": os.path.join(DATA_DIR, "AGL9-30m.xls"),
    "1h": os.path.join(DATA_DIR, "AGL9-1h.xls"),
    "1d": os.path.join(DATA_DIR, "AGL9.xls"),
}

SYMBOL = "AG_IDX"


def init_db_tables(conn):
    """Ensure futures_min_bars, stock_daily, and stock_basic tables exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS futures_min_bars (
            symbol TEXT,
            timeframe TEXT,
            trade_time TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            amount REAL,
            PRIMARY KEY (symbol, timeframe, trade_time)
        );
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_daily (
            symbol TEXT,
            trade_date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            amount REAL,
            PRIMARY KEY (symbol, trade_date)
        );
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_basic (
            symbol TEXT PRIMARY KEY,
            name TEXT,
            price REAL,
            pe_ttm REAL,
            pb REAL,
            total_mv REAL,
            circ_mv REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()


def clean_xls_file(filepath, is_daily=False):
    """Parse GB18030 encoded TongDaXin tab-separated text file."""
    df = pd.read_csv(filepath, sep=r'\s+', encoding='gb18030', skiprows=1)
    
    # Filter valid rows (remove header title remainder & footer comment lines)
    time_col = df.columns[0]
    df = df[df[time_col].notnull() & ~df[time_col].astype(str).str.contains('#')]
    
    # Parse OHLCV
    df['open'] = pd.to_numeric(df['开盘'], errors='coerce')
    df['high'] = pd.to_numeric(df['最高'], errors='coerce')
    df['low'] = pd.to_numeric(df['最低'], errors='coerce')
    df['close'] = pd.to_numeric(df['收盘'], errors='coerce')
    df['volume'] = pd.to_numeric(df['成交量'], errors='coerce').fillna(0.0)
    df['amount'] = np.round(df['close'] * df['volume'], 2)
    
    df = df.dropna(subset=['open', 'high', 'low', 'close'])
    
    # Standardize time
    raw_times = df[time_col].astype(str).str.strip()
    if is_daily:
        # Format: 2012/05/10 -> 2012-05-10
        dt = pd.to_datetime(raw_times, format='%Y/%m/%d', errors='coerce')
        df['trade_date'] = dt.dt.strftime('%Y-%m-%d')
        df['trade_time'] = dt.dt.strftime('%Y-%m-%d 00:00:00')
        df = df.dropna(subset=['trade_date'])
    else:
        # Format: 2026/06/16-22:35 -> 2026-06-16 22:35:00
        dt = pd.to_datetime(raw_times, format='%Y/%m/%d-%H:%M', errors='coerce')
        df['trade_time'] = dt.dt.strftime('%Y-%m-%d %H:%M:%S')
        df['trade_date'] = dt.dt.strftime('%Y-%m-%d')
        df = df.dropna(subset=['trade_time'])

    df['symbol'] = SYMBOL
    return df


def import_all_agl9_data():
    """Clean all AGL9 XLS files and import into SQLite db."""
    print("=" * 80)
    print(f"🚀 清洗白银指数 (AGL9) 多周期 K 线数据并落盘至数据库: {DB_PATH}")
    print("=" * 80)
    
    latest_close = 0.0

    with sqlite3.connect(DB_PATH) as conn:
        init_db_tables(conn)
        c = conn.cursor()

        for tf, filepath in XLS_FILES.items():
            if not os.path.exists(filepath):
                print(f"⚠️ 文件不存在，跳过: {filepath}")
                continue

            is_daily = (tf == "1d")
            print(f"\n[处理周期 {tf:>4}] 正在清洗并解析: {os.path.basename(filepath)} ...")
            df = clean_xls_file(filepath, is_daily=is_daily)

            if df.empty:
                print(f"  ❌ 清洗后无有效数据!")
                continue

            latest_close = float(df['close'].iloc[-1])
            start_t = df['trade_date'].iloc[0] if is_daily else df['trade_time'].iloc[0]
            end_t = df['trade_date'].iloc[-1] if is_daily else df['trade_time'].iloc[-1]

            # 1. 存入 futures_min_bars
            df['timeframe'] = tf
            sub_min = df[['symbol', 'timeframe', 'trade_time', 'open', 'high', 'low', 'close', 'volume', 'amount']].copy()
            c.execute("DELETE FROM futures_min_bars WHERE symbol = ? AND timeframe = ?;", (SYMBOL, tf))
            sub_min.to_sql('futures_min_bars', conn, if_exists='append', index=False, chunksize=1000)
            print(f"  ├─ [futures_min_bars ({tf:>3})]  成功插入 {len(sub_min)} 条 | 时间: {start_t} -> {end_t}")

            # 2. 如果是 1d，同时插入 stock_daily
            if is_daily:
                sub_daily = df[['symbol', 'trade_date', 'open', 'high', 'low', 'close', 'volume', 'amount']].copy()
                c.execute("DELETE FROM stock_daily WHERE symbol = ?;", (SYMBOL,))
                sub_daily.to_sql('stock_daily', conn, if_exists='append', index=False, chunksize=1000)
                print(f"  ├─ [stock_daily      ( 1d )]  成功插入 {len(sub_daily)} 条 | 时间: {start_t} -> {end_t}")

        # 3. 更新 stock_basic 元数据
        if latest_close > 0:
            c.execute("""
                INSERT OR REPLACE INTO stock_basic (symbol, name, price, pe_ttm, pb, total_mv, circ_mv, updated_at)
                VALUES (?, ?, ?, 0.0, 0.0, 50000000000.0, 50000000000.0, CURRENT_TIMESTAMP);
            """, (SYMBOL, "[期货加权] 沪银指数", latest_close))
            print(f"\n✅ 更新 stock_basic 资产元数据: {SYMBOL} -> 最新收盘价: {latest_close}")

        conn.commit()

    print("\n" + "=" * 80)
    print("🎉 白银指数 (AGL9) 6 大全周期 (5m, 10m, 15m, 30m, 1h, 1d) 数据清洗与落盘完成!")
    print("=" * 80)


if __name__ == "__main__":
    import_all_agl9_data()
