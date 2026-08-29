"""
code/sync_calendar_spread_pairs.py — 跨期套利双合约独立历史 K 线抓取与入库引擎
TqSdk Dual-Contract Real K-Line Downloader & SQLite Synchronizer

核心职责：
1. 从 .env 读取天勤量化账号密码，建立安全 API 隧道；
2. 批量拉取真实独立的近月与远月主力合约 (15m 周期，8000 根真实 Bar)；
3. 将近远月真实成交数据入库至 `futures_contract_bars` 表，为 100% 真实订单簿级跨期套利提供原始数据底座。
"""

from __future__ import annotations

import os
import sys
import time
import sqlite3
import datetime
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = str(PROJECT_ROOT / ".env")
DB_PATH = str(PROJECT_ROOT / "data/ashare_quant.db")

# 跨期套利核心真实合约配对表 (近月 + 远月)
CALENDAR_SPREAD_PAIRS = [
    # 贵金属
    {"symbol": "AG_IDX", "near": "SHFE.ag2606", "far": "SHFE.ag2612", "name": "白银 2606-2612", "days_between_contracts": 183},
    {"symbol": "AU_IDX", "near": "SHFE.au2606", "far": "SHFE.au2612", "name": "黄金 2606-2612", "days_between_contracts": 183},
    # 黑色系
    {"symbol": "RB_IDX", "near": "SHFE.rb2610", "far": "SHFE.rb2701", "name": "螺纹 2610-2701", "days_between_contracts": 92},
    {"symbol": "HC_IDX", "near": "SHFE.hc2610", "far": "SHFE.hc2701", "name": "热卷 2610-2701", "days_between_contracts": 92},
    {"symbol": "I_IDX",  "near": "DCE.i2609",   "far": "DCE.i2701",   "name": "铁矿 2609-2701", "days_between_contracts": 122},
    {"symbol": "J_IDX",  "near": "DCE.j2609",   "far": "DCE.j2701",   "name": "焦炭 2609-2701", "days_between_contracts": 122},
    {"symbol": "JM_IDX", "near": "DCE.jm2609",  "far": "DCE.jm2701",  "name": "焦煤 2609-2701", "days_between_contracts": 122},
    # 农产品
    {"symbol": "M_IDX",  "near": "DCE.m2609",   "far": "DCE.m2701",   "name": "豆粕 2609-2701", "days_between_contracts": 122},
    {"symbol": "Y_IDX",  "near": "DCE.y2609",   "far": "DCE.y2701",   "name": "豆油 2609-2701", "days_between_contracts": 122},
    {"symbol": "P_IDX",  "near": "DCE.p2609",   "far": "DCE.p2701",   "name": "棕榈 2609-2701", "days_between_contracts": 122},
    {"symbol": "SR_IDX", "near": "CZCE.SR609",  "far": "CZCE.SR701",  "name": "白糖 2609-2701", "days_between_contracts": 122},
    {"symbol": "CF_IDX", "near": "CZCE.CF609",  "far": "CZCE.CF701",  "name": "棉花 2609-2701", "days_between_contracts": 122},
    # 能化系
    {"symbol": "TA_IDX", "near": "CZCE.TA609",  "far": "CZCE.TA701",  "name": "PTA 2609-2701", "days_between_contracts": 122},
    {"symbol": "MA_IDX", "near": "CZCE.MA609",  "far": "CZCE.MA701",  "name": "甲醇 2609-2701", "days_between_contracts": 122},
    {"symbol": "SA_IDX", "near": "CZCE.SA609",  "far": "CZCE.SA701",  "name": "纯碱 2609-2701", "days_between_contracts": 122},
    {"symbol": "FG_IDX", "near": "CZCE.FG609",  "far": "CZCE.FG701",  "name": "玻璃 2609-2701", "days_between_contracts": 122},
    # 有色系 (月间轮转)
    {"symbol": "CU_IDX", "near": "SHFE.cu2609", "far": "SHFE.cu2610", "name": "沪铜 2609-2610", "days_between_contracts": 30},
    {"symbol": "AL_IDX", "near": "SHFE.al2609", "far": "SHFE.al2610", "name": "沪铝 2609-2610", "days_between_contracts": 30},
    {"symbol": "ZN_IDX", "near": "SHFE.zn2609", "far": "SHFE.zn2610", "name": "沪锌 2609-2610", "days_between_contracts": 30},
]


def load_tq_credentials():
    user = os.getenv("TQ_ACCOUNT", "").strip()
    password = os.getenv("TQ_PASSWORD", "").strip()
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip().replace("：", ":")
                separator = "=" if "=" in line else ":"
                if separator not in line:
                    continue
                key, value = (part.strip() for part in line.split(separator, 1))
                value = value.strip("\"'")
                if key == "TQ_ACCOUNT" and not user:
                    user = value
                elif key == "TQ_PASSWORD" and not password:
                    password = value
    if not user or not password:
        raise RuntimeError("TQ_ACCOUNT and TQ_PASSWORD are required")
    return user, password


def init_db(conn: sqlite3.Connection):
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS futures_contract_bars (
        symbol TEXT NOT NULL,
        contract TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        trade_time TEXT NOT NULL,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        volume REAL,
        open_interest REAL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (contract, timeframe, trade_time)
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fc_bars_time ON futures_contract_bars (contract, trade_time);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fc_bars_sym ON futures_contract_bars (symbol, timeframe);")
    conn.commit()


def sync_contract_pair_bars(data_length: int = 8000):
    from tqsdk import TqApi, TqAuth
    user, password = load_tq_credentials()
    masked_user = f"{user[:3]}***{user[-2:]}" if len(user) > 5 else "***"
    print(f"[Sync Engine] 🔌 连接天勤量化官方行情服务器 (Account: {masked_user})...")
    api = TqApi(auth=TqAuth(user, password))

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    total_inserted = 0

    all_contracts = set()
    for item in CALENDAR_SPREAD_PAIRS:
        all_contracts.add((item["symbol"], item["near"]))
        all_contracts.add((item["symbol"], item["far"]))

    print(f"[Sync Engine] 📋 准备下载 {len(all_contracts)} 个真实独立合约的 15m 历史 K 线 (每合约 {data_length} 根)...")

    for sym, contract in sorted(all_contracts):
        try:
            print(f"[Sync Engine] ⏳ 正在拉取合约 {contract} (品种: {sym}) 15m K线...")
            klines = api.get_kline_serial(contract, duration_seconds=900, data_length=data_length)
            for _ in range(15):
                api.wait_update(deadline=time.time() + 1.5)
                if len(klines) > 0 and klines.iloc[-1]["datetime"] > 0:
                    break

            if klines is None or len(klines) == 0:
                print(f"[Sync Engine] ⚠️ 合约 {contract} 未能获取到 K 线数据，跳过")
                continue

            df = klines.copy()
            df["trade_time"] = pd.to_datetime(df["datetime"]).dt.strftime("%Y-%m-%d %H:%M:%S")
            df["symbol"] = sym
            df["contract"] = contract
            df["timeframe"] = "15m"

            records = []
            for _, row in df.iterrows():
                if pd.isna(row["close"]) or row["close"] == 0:
                    continue
                records.append((
                    row["symbol"],
                    row["contract"],
                    row["timeframe"],
                    str(row["trade_time"]),
                    float(row["open"]),
                    float(row["high"]),
                    float(row["low"]),
                    float(row["close"]),
                    float(row.get("volume", 0)),
                    float(row.get("open_interest", 0))
                ))

            cursor = conn.cursor()
            cursor.executemany("""
            INSERT OR REPLACE INTO futures_contract_bars
            (symbol, contract, timeframe, trade_time, open, high, low, close, volume, open_interest)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, records)
            conn.commit()

            print(f"[Sync Engine] ✅ 合约 {contract} 成功写入 {len(records)} 根 15m K线 ({records[0][3]} ~ {records[-1][3]})")
            total_inserted += len(records)
            time.sleep(0.5)

        except Exception as e:
            print(f"[Sync Engine] ❌ 拉取合约 {contract} 异常: {e}")

    conn.close()
    api.close()
    print(f"\n🎉 [Sync Engine] 全部真实双合约历史数据下载完毕！累计入库: {total_inserted:,} 条记录。")


if __name__ == "__main__":
    sync_contract_pair_bars()
