"""
code/sync_live_futures_klines.py — 全品种商品期货实时 K 线秒级同步网关
(将天勤 TqSdk 实时 10m/15m/30m K 线无缝同步至本地 SQLite 数据库与实时 JSON 缓存)
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path
import pandas as pd
import numpy as np
try:
    from tqsdk import TqApi, TqAuth
except ImportError:
    TqApi, TqAuth = None, None
from runtime_credentials import load_required_credentials

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "ashare_quant.db"

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("KlineSync")

BEIJING_TZ = datetime.timezone(datetime.timedelta(hours=8))

SYMBOL_MAP = {
    # 15m 品种
    ("AG_IDX", "15m", 900): "KQ.m@SHFE.ag",
    ("AU_IDX", "15m", 900): "KQ.m@SHFE.au",
    ("CU_IDX", "15m", 900): "KQ.m@SHFE.cu",
    ("LC_IDX", "15m", 900): "KQ.m@GFEX.lc",
    ("P_IDX",  "15m", 900): "KQ.m@DCE.p",
    ("SC_IDX", "15m", 900): "KQ.m@INE.sc",
    ("TA_IDX", "15m", 900): "KQ.m@CZCE.TA",
    ("MA_IDX", "15m", 900): "KQ.m@CZCE.MA",
    ("SA_IDX", "15m", 900): "KQ.m@CZCE.SA",
    ("HC_IDX", "15m", 900): "KQ.m@SHFE.hc",
    ("RB_IDX", "15m", 900): "KQ.m@SHFE.rb",
    ("RU_IDX", "15m", 900): "KQ.m@SHFE.ru",
    ("J_IDX",  "15m", 900): "KQ.m@DCE.j",
    # 10m 品种
    ("SN_IDX", "10m", 600): "KQ.m@SHFE.sn",
    ("AU_IDX", "10m", 600): "KQ.m@SHFE.au",
    ("AG_IDX", "10m", 600): "KQ.m@SHFE.ag",
    ("P_IDX",  "10m", 600): "KQ.m@DCE.p",
    ("MA_IDX", "10m", 600): "KQ.m@CZCE.MA",
    # 30m 品种
    ("SC_IDX", "30m", 1800): "KQ.m@INE.sc",
    ("LC_IDX", "30m", 1800): "KQ.m@GFEX.lc",
    ("J_IDX",  "30m", 1800): "KQ.m@DCE.j",
    ("AL_IDX", "30m", 1800): "KQ.m@SHFE.al",
    ("TA_IDX", "30m", 1800): "KQ.m@CZCE.TA",
    ("SI_IDX", "30m", 1800): "KQ.m@GFEX.si",
}


def get_tq_credentials():
    return load_required_credentials(PROJECT_ROOT / ".env")


def sync_all_klines():
    acc, pwd = get_tq_credentials()
    logger.info("Connecting to TqSdk to fetch latest real-time K-lines...")
    api = TqApi(auth=TqAuth(acc, pwd))

    kline_handles = {}
    for (sym, tf, dur), tq_sym in SYMBOL_MAP.items():
        kline_handles[(sym, tf)] = api.get_kline_serial(tq_sym, duration_seconds=dur, data_length=300)

    # 等待至少 1 个完整 update
    api.wait_update()
    logger.info("Data received, saving live K-lines to JSON cache and SQLite...")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS futures_min_bars (
            symbol TEXT,
            timeframe TEXT,
            trade_time TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            open_interest REAL,
            CHECK (open > 0 AND high >= low AND close > 0 AND volume >= 0),
            PRIMARY KEY (symbol, timeframe, trade_time)
        )
    """)

    for (sym, tf), kl_df in kline_handles.items():
        if kl_df is None or len(kl_df) == 0:
            continue

        rows = []
        db_records = []
        for _, r in kl_df.iterrows():
            dt_ns = r["datetime"]
            dt_beijing = datetime.datetime.fromtimestamp(dt_ns / 1e9, tz=datetime.timezone.utc).astimezone(BEIJING_TZ)
            dt_str = dt_beijing.strftime("%Y-%m-%d %H:%M:%S")
            o = float(r["open"])
            h = float(r["high"])
            l = float(r["low"])
            c = float(r["close"])
            v = float(r.get("volume", 0.0))
            oi = float(r.get("close_oi", r.get("open_interest", 0.0)))

            rows.append({
                "trade_time": dt_str,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
                "open_interest": oi
            })
            db_records.append((sym, tf, dt_str, o, h, l, c, v, oi))

        # 写入 JSON 缓存
        json_file = DATA_DIR / f"live_klines_{sym}_{tf}.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False)

        # 批量 upsert SQLite
        cursor.executemany("""
            INSERT OR REPLACE INTO futures_min_bars
            (symbol, timeframe, trade_time, open, high, low, close, volume, open_interest)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, db_records)

        # 同步更新元数据行数与时段
        cursor.execute("""
            SELECT COUNT(*), MIN(trade_time), MAX(trade_time)
            FROM futures_min_bars
            WHERE symbol = ? AND timeframe = ?
        """, (sym, tf))
        cnt, st, et = cursor.fetchone()
        cursor.execute("""
            UPDATE futures_series_metadata
            SET row_count = ?, start_time = ?, end_time = ?, imported_at = ?
            WHERE symbol = ? AND timeframe = ?
        """, (cnt, st, et, datetime.datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S"), sym, tf))

    conn.commit()
    conn.close()
    api.close()
    logger.info(f"✅ Successfully synchronized {len(SYMBOL_MAP)} symbol-timeframe series up to latest live bar!")


if __name__ == "__main__":
    sync_all_klines()
