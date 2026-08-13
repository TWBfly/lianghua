"""
A-Share Quantitative Data Engine - TqSdk Multi-Timeframe (5m, 15m, 30m) Real Futures K-Line Downloader
【天勤量化 5m、15m、30m 多周期真实期货 K 线全量历史数据抓取与存储器】

核心功能：
1. 从 `.env` 文件安全读取天勤量化账号密码 (13800000000 / redacted_password)。
2. 通过 TqSdk 官方 `TqApi(auth=TqAuth(user, pass))` 连接天勤行情服务器。
3. 抓取 12 大热门期货品种 (AG, CU, RB, I, SA, SC, MA, TA, M, SN, LC, J) 的【5m (300s)、15m (900s)、30m (1800s)】全量真实 K 线数据。
4. 将纳秒时间戳转换转换为标准日期字符串 (YYYY-MM-DD HH:MM:SS)，写落至 SQLite `futures_min_bars` 表中。
"""

import os
import sys
import re
import sqlite3
import datetime
import pandas as pd
from pathlib import Path
from tqsdk import TqApi, TqAuth

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = str(PROJECT_ROOT / ".env")
DB_PATH = str(PROJECT_ROOT / "data/ashare_quant.db")

# 天勤官方主连合约代码映射表
TQ_SYMBOL_MAP = {
    "AG_IDX": "KQ.m@SHFE.ag",
    "CU_IDX": "KQ.m@SHFE.cu",
    "RB_IDX": "KQ.m@SHFE.rb",
    "I_IDX": "KQ.m@DCE.i",
    "SA_IDX": "KQ.m@CZCE.SA",
    "SC_IDX": "KQ.m@INE.sc",
    "MA_IDX": "KQ.m@CZCE.MA",
    "TA_IDX": "KQ.m@CZCE.TA",
    "M_IDX": "KQ.m@DCE.m",
    "SN_IDX": "KQ.m@SHFE.sn",
    "LC_IDX": "KQ.m@GFEX.lc",
    "J_IDX": "KQ.m@DCE.j"
}

# 目标周期映射 (秒数 -> timeframe 标识)
TIMEFRAMES = [
    (300, "5m"),
    (900, "15m"),
    (1800, "30m")
]


def load_tq_credentials():
    """解析 .env 配置文件中的天勤账号密码"""
    if not os.path.exists(ENV_PATH):
        raise FileNotFoundError(f"配置文件不存在: {ENV_PATH}")

    user = None
    password = None

    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "账号" in line:
                user = line.split("：")[-1].split(":")[-1].strip()
            elif "密码" in line:
                password = line.split("：")[-1].split(":")[-1].strip()

    if not user or not password:
        raise ValueError("未能从 .env 文件中提取到天勤量化的账号和密码！")

    return user, password


def download_all_tq_klines(data_length: int = 8000):
    user, password = load_tq_credentials()
    print("=" * 90)
    print(f"🔑 成功读取 .env 天勤凭据 -> 账号: {user[:3]}****{user[-4:]}")
    print(f"🚀 启动天勤量化全量 K 线下载 (覆盖 5m, 15m, 30m 多周期，单次请求 {data_length} 根)...")
    print("=" * 90)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 保证数据库索引存在
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_futures_min_sym_tf_time ON futures_min_bars (symbol, timeframe, trade_time);")
    conn.commit()

    api = TqApi(auth=TqAuth(user, password))

    total_inserted = 0

    try:
        for db_sym, tq_code in TQ_SYMBOL_MAP.items():
            print(f"\n📦 正在处理品种 [{db_sym:<8} | 天勤代码: {tq_code}]...")

            for duration_sec, tf_name in TIMEFRAMES:
                try:
                    # 调取天勤 K 线数据
                    klines = api.get_kline_serial(tq_code, duration_sec, data_length=data_length)
                    df_k = pd.DataFrame(klines)

                    if df_k.empty:
                        print(f"  ├─ [{tf_name:<3}] 未能调取到数据")
                        continue

                    # 时间戳转换 (纳秒 nanoseconds -> datetime str)
                    df_k["dt_str"] = pd.to_datetime(df_k["datetime"], unit="ns").dt.strftime("%Y-%m-%d %H:%M:%S")
                    df_k = df_k.sort_values("datetime").reset_index(drop=True)

                    bars_to_insert = []
                    for _, row in df_k.iterrows():
                        b_dt = row["dt_str"]
                        b_open = float(row["open"])
                        b_high = float(row["high"])
                        b_low = float(row["low"])
                        b_close = float(row["close"])
                        b_vol = int(row["volume"]) if "volume" in row and not pd.isna(row["volume"]) else 0
                        b_oi = int(row["open_oi"]) if "open_oi" in row and not pd.isna(row["open_oi"]) else 0

                        if b_open <= 0 or b_high <= 0 or b_low <= 0 or b_close <= 0:
                            continue

                        bars_to_insert.append((
                            db_sym, tf_name, b_dt,
                            round(b_open, 2), round(b_high, 2), round(b_low, 2), round(b_close, 2),
                            b_vol, round(b_close * b_vol, 2), b_oi, round(b_close, 2)
                        ))

                    if bars_to_insert:
                        cursor.executemany(
                            """
                            INSERT OR REPLACE INTO futures_min_bars 
                            (symbol, timeframe, trade_time, open, high, low, close, volume, amount, open_interest, settlement)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                            """,
                            bars_to_insert
                        )
                        conn.commit()
                        total_inserted += len(bars_to_insert)
                        print(f"  ├─ [{tf_name:<3}] 成功保存 {len(bars_to_insert):>5} 根真实 K线 (起止: {bars_to_insert[0][2]} 至 {bars_to_insert[-1][2]})")

                except Exception as e_tf:
                    print(f"  ├─ [{tf_name:<3}] 调取失败: {e_tf}")

    finally:
        api.close()
        conn.close()

    print("\n" + "=" * 90)
    print(f"🎉 天勤量化 5m/15m/30m 多周期真实 K 线全量下载完成！总计入库数据点: {total_inserted} 根！")
    print("=" * 90)


if __name__ == "__main__":
    download_all_tq_klines(data_length=8000)
