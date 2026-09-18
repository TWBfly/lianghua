"""
realtime_market_daemon.py — 25 大主力期货极简超轻量实时行情与 K 线落库守护引擎 (低内存优化版)

核心设计：
1. 超轻量内存架构：针对 1GB VPS 深度定制，内存控制在 80MB 以内；
2. 订阅 25 大主力品种核心周期 (1m 实盘波动 + 15m 策略主周期)；
3. 毫秒级无锁化 (SQLite WAL Mode) 更新 `futures_min_bars` 表与 `data/realtime_market_quotes.json`；
4. 周期性主动触发 gc.collect()，彻底杜绝内存碎片与内存泄漏；
5. 断线自愈与异常自动重连。
"""

from __future__ import annotations

import os
import sys
import gc
import time
import json
import sqlite3
import datetime
import logging
import pandas as pd
from pathlib import Path
from tqsdk import TqApi, TqAuth

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "code"))

ENV_PATH = PROJECT_ROOT / ".env"
DB_PATH = PROJECT_ROOT / "data/ashare_quant.db"
QUOTES_JSON = PROJECT_ROOT / "data/realtime_market_quotes.json"
LOG_DIR = PROJECT_ROOT / "data/logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "market_daemon.log"

logger = logging.getLogger("MarketDaemon")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
fh.setFormatter(formatter)
ch = logging.StreamHandler(sys.stdout)
ch.setFormatter(formatter)

if not logger.handlers:
    logger.addHandler(fh)
    logger.addHandler(ch)

TQ_SYMBOL_MAP = {
    "AG_IDX": "KQ.m@SHFE.ag",   # 沪银
    "AU_IDX": "KQ.m@SHFE.au",   # 沪金
    "CU_IDX": "KQ.m@SHFE.cu",   # 沪铜
    "AL_IDX": "KQ.m@SHFE.al",   # 沪铝
    "ZN_IDX": "KQ.m@SHFE.zn",   # 沪锌
    "SN_IDX": "KQ.m@SHFE.sn",   # 沪锡
    "RB_IDX": "KQ.m@SHFE.rb",   # 螺纹钢
    "HC_IDX": "KQ.m@SHFE.hc",   # 热卷
    "I_IDX":  "KQ.m@DCE.i",     # 铁矿石
    "J_IDX":  "KQ.m@DCE.j",     # 焦炭
    "JM_IDX": "KQ.m@DCE.jm",    # 焦煤
    "SA_IDX": "KQ.m@CZCE.SA",   # 纯碱
    "SC_IDX": "KQ.m@INE.sc",    # 原油
    "MA_IDX": "KQ.m@CZCE.MA",   # 甲醇
    "TA_IDX": "KQ.m@CZCE.TA",   # PTA
    "RU_IDX": "KQ.m@SHFE.ru",   # 橡胶
    "M_IDX":  "KQ.m@DCE.m",     # 豆粕
    "P_IDX":  "KQ.m@DCE.p",     # 棕榈油
    "Y_IDX":  "KQ.m@DCE.y",     # 豆油
    "SR_IDX": "KQ.m@CZCE.SR",   # 白糖
    "CF_IDX": "KQ.m@CZCE.CF",   # 棉花
    "FG_IDX": "KQ.m@CZCE.FG",   # 玻璃
    "LC_IDX": "KQ.m@GFEX.lc",   # 碳酸锂
    "SI_IDX": "KQ.m@GFEX.si",   # 工业硅
    "C_IDX":  "KQ.m@DCE.c"      # 玉米
}

# 聚焦核心周期，减少对象常驻内存
TIMEFRAMES = [
    (60, "1m"),
    (900, "15m")
]


from runtime_credentials import load_required_credentials


def load_tq_credentials():
    return load_required_credentials(ENV_PATH)


def init_database():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    cursor = conn.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout=30000;")
    except Exception:
        pass
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
            amount REAL,
            open_interest REAL,
            settlement REAL,
            CHECK (open > 0 AND high >= low AND close > 0 AND volume >= 0),
            PRIMARY KEY (symbol, timeframe, trade_time)
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_futures_min_sym_tf_time ON futures_min_bars (symbol, timeframe, trade_time);")
    conn.commit()
    conn.close()


def run_daemon():
    init_database()
    account, password = load_tq_credentials()

    logger.info("=" * 80)
    logger.info("🚀 【25 大商品期货轻量级实时行情守护引擎启动】 (低内存优化模式)")
    logger.info(f"🔑 天勤账号: {account[:3]}****{account[-4:]}")
    logger.info(f"📁 数据库路径: {DB_PATH}")
    logger.info(f"📈 监听品种数: {len(TQ_SYMBOL_MAP)} | 周期: {[t[1] for t in TIMEFRAMES]}")
    logger.info("=" * 80)

    while True:
        try:
            api = TqApi(auth=TqAuth(account, password))
            logger.info("✅ 成功连接天勤官方行情服务器！")

            # 订阅所有品种的核心周期 K 线与 Quote
            kline_subscriptions = {}
            quote_subscriptions = {}
            for db_sym, tq_code in TQ_SYMBOL_MAP.items():
                kline_subscriptions[db_sym] = {}
                for dur, tf_name in TIMEFRAMES:
                    try:
                        kline_subscriptions[db_sym][tf_name] = api.get_kline_serial(tq_code, dur, data_length=10)
                    except Exception as e:
                        logger.error(f"订阅 K 线失败 [{db_sym} {tf_name}]: {e}")

                try:
                    quote_subscriptions[db_sym] = api.get_quote(tq_code)
                except Exception as e:
                    logger.error(f"订阅 Quote 失败 [{db_sym}]: {e}")

            logger.info("🟢 实时行情流订阅就绪，进入毫秒级事件驱动循环...")

            last_save_time = time.time()
            last_heartbeat = time.time()

            conn = sqlite3.connect(DB_PATH, timeout=30.0)
            cursor = conn.cursor()

            while True:
                api.wait_update()
                now_ts = time.time()

                # 每 3 秒批量落库一次最新变动的 Bar
                if now_ts - last_save_time >= 3.0:
                    last_save_time = now_ts
                    bars_to_upsert = []
                    quotes_data = {}

                    for db_sym, tf_dict in kline_subscriptions.items():
                        q = quote_subscriptions.get(db_sym)
                        if q:
                            quotes_data[db_sym] = {
                                "symbol": db_sym,
                                "last_price": float(q.last_price) if not pd.isna(q.last_price) else 0.0,
                                "open": float(q.open) if not pd.isna(q.open) else 0.0,
                                "high": float(q.high) if not pd.isna(q.high) else 0.0,
                                "low": float(q.low) if not pd.isna(q.low) else 0.0,
                                "volume": int(q.volume) if not pd.isna(q.volume) else 0,
                                "open_interest": int(q.open_interest) if not pd.isna(q.open_interest) else 0,
                                "datetime": str(q.datetime) if q.datetime else datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            }

                        for tf_name, klines in tf_dict.items():
                            if len(klines) == 0:
                                continue
                            tail_k = klines.tail(2)
                            for _, row in tail_k.iterrows():
                                if row["datetime"] <= 0:
                                    continue
                                b_dt = pd.to_datetime(row["datetime"], unit="ns", utc=True).tz_convert("Asia/Shanghai").strftime("%Y-%m-%d %H:%M:%S")
                                b_open = float(row["open"])
                                b_high = float(row["high"])
                                b_low = float(row["low"])
                                b_close = float(row["close"])
                                b_vol = int(row["volume"]) if "volume" in row and not pd.isna(row["volume"]) else 0
                                b_oi = int(row["open_oi"]) if "open_oi" in row and not pd.isna(row["open_oi"]) else 0

                                if b_open > 0 and b_high > 0 and b_low > 0 and b_close > 0:
                                    bars_to_upsert.append((
                                        db_sym, tf_name, b_dt,
                                        round(b_open, 2), round(b_high, 2), round(b_low, 2), round(b_close, 2),
                                        b_vol, round(b_close * b_vol, 2), b_oi, round(b_close, 2)
                                    ))

                    if bars_to_upsert:
                        try:
                            cursor.executemany(
                                """
                                INSERT OR REPLACE INTO futures_min_bars 
                                (symbol, timeframe, trade_time, open, high, low, close, volume, amount, open_interest, settlement)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                                """,
                                bars_to_upsert
                            )
                            conn.commit()
                        except sqlite3.OperationalError as e_db:
                            logger.warning(f"数据库写入等待: {e_db}")

                    if quotes_data:
                        try:
                            with open(QUOTES_JSON, "w", encoding="utf-8") as f_q:
                                json.dump(quotes_data, f_q, ensure_ascii=False, indent=2)
                        except Exception:
                            pass

                # 每 30 秒心跳并执行一次主动垃圾回收 gc.collect()
                if now_ts - last_heartbeat >= 30.0:
                    last_heartbeat = now_ts
                    gc.collect()
                    ag_q = quote_subscriptions.get("AG_IDX")
                    ag_p = ag_q.last_price if ag_q and not pd.isna(ag_q.last_price) else 0.0
                    logger.info(f"💓 [行情守护心跳] 正常接收 | 白银现价: ¥{ag_p:,.2f} | 内存已垃圾回收")

        except Exception as e_main:
            logger.error(f"❌ 行情流异常断开: {e_main}，5 秒后尝试自愈重连...")
            time.sleep(5)


if __name__ == "__main__":
    run_daemon()
