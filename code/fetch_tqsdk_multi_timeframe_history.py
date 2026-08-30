"""
A-Share & Futures Quantitative Data Engine - TqSdk Multi-Timeframe (1m, 5m, 15m, 30m) Real Futures K-Line Downloader
【天勤量化 1m、5m、15m、30m 多周期真实期货 K 线全量历史数据抓取与存储器】

核心功能：
1. 从 `.env` 文件安全读取天勤量化账号密码。
2. 通过 TqSdk 官方 `TqApi(auth=TqAuth(user, pass))` 连接天勤行情服务器。
3. 抓取 24 大热门高活跃期货品种的【1m (60s)、5m (300s)、15m (900s)、30m (1800s)】全量真实 K 线数据。
4. 将纳秒时间戳转换为标准日期字符串 (YYYY-MM-DD HH:MM:SS)，写落至 SQLite `futures_min_bars` 表中。
"""

import os
import sys
import time
import argparse
import sqlite3
import datetime
import pandas as pd
from pathlib import Path
from tqsdk import TqApi, TqAuth
from runtime_credentials import load_required_credentials

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = str(PROJECT_ROOT / ".env")
DB_PATH = str(PROJECT_ROOT / "data/ashare_quant.db")

# 天勤官方主连合约代码映射表 (覆盖 24 大高活跃期货品种)
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

# 目标周期映射 (秒数 -> timeframe 标识)
ALL_TIMEFRAMES = [
    (60, "1m"),
    (300, "5m"),
    (600, "10m"),
    (900, "15m"),
    (1800, "30m"),
    (3600, "1h"),
    (14400, "4h"),
    (86400, "1d")
]


def load_tq_credentials():
    return load_required_credentials(ENV_PATH)


def download_tq_klines(target_symbols=None, target_tfs=None, data_length: int = 8000):
    user, password = load_tq_credentials()
    
    symbols_to_fetch = {}
    if target_symbols:
        for s in target_symbols:
            if s in TQ_SYMBOL_MAP:
                symbols_to_fetch[s] = TQ_SYMBOL_MAP[s]
            else:
                print(f"⚠️ 未知品种: {s}，跳过")
    else:
        symbols_to_fetch = TQ_SYMBOL_MAP

    tfs_to_fetch = []
    if target_tfs:
        tf_dict = {tf_name: dur for dur, tf_name in ALL_TIMEFRAMES}
        for tf_req in target_tfs:
            if tf_req in tf_dict:
                tfs_to_fetch.append((tf_dict[tf_req], tf_req))
    else:
        tfs_to_fetch = ALL_TIMEFRAMES

    print("=" * 90)
    print(f"🔑 成功读取 .env 天勤凭据 -> 账号: {user[:3]}****{user[-4:]}")
    print(f"🚀 启动天勤量化 K 线全量下载 (品种数: {len(symbols_to_fetch)}, 周期: {[t[1] for t in tfs_to_fetch]}, 单次请求: {data_length} 根)...")
    print("=" * 90)

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

    api = TqApi(auth=TqAuth(user, password))
    total_inserted = 0

    try:
        for db_sym, tq_code in symbols_to_fetch.items():
            print(f"\n📦 正在处理品种 [{db_sym:<8} | 天勤代码: {tq_code}]...")

            for duration_sec, tf_name in tfs_to_fetch:
                try:
                    # 调取天勤 K 线数据
                    klines = api.get_kline_serial(tq_code, duration_sec, data_length=data_length)
                    
                    # 驱动 wait_update 获取完整行情包
                    for _ in range(15):
                        api.wait_update(deadline=time.time() + 1.5)
                        if len(klines) > 0 and klines.iloc[-1]["datetime"] > 0:
                            break

                    df_k = pd.DataFrame(klines)

                    if df_k.empty or df_k.iloc[-1]["datetime"] == 0:
                        print(f"  ├─ [{tf_name:<3}] 未能调取到有效数据")
                        continue

                    # 过滤无效行
                    df_k = df_k[df_k["datetime"] > 0].copy()
                    if df_k.empty:
                        print(f"  ├─ [{tf_name:<3}] 数据为空")
                        continue

                    # 时间戳转换 (纳秒 nanoseconds -> 标准北京时间 Asia/Shanghai -> datetime str)
                    df_k["dt_str"] = pd.to_datetime(df_k["datetime"], unit="ns", utc=True).dt.tz_convert("Asia/Shanghai").dt.strftime("%Y-%m-%d %H:%M:%S")
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
                        print(f"  ├─ [{tf_name:<3}] ✅ 成功保存 {len(bars_to_insert):>5} 根真实 K线 (起止: {bars_to_insert[0][2]} 至 {bars_to_insert[-1][2]})", flush=True)

                except Exception as e_tf:
                    print(f"  ├─ [{tf_name:<3}] ❌ 调取失败: {e_tf}", flush=True)

    finally:
        api.close()
        conn.close()

    print("\n" + "=" * 90, flush=True)
    print(f"🎉 天勤量化 K 线全量下载与入库完成！本次新增/更新数据点: {total_inserted} 根！", flush=True)
    print("=" * 90, flush=True)
    return total_inserted


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TqSdk Futures Multi-Timeframe Downloader")
    parser.add_argument("--symbols", type=str, default="", help="Comma separated symbols, e.g. AG_IDX,AU_IDX")
    parser.add_argument("--timeframes", type=str, default="", help="Comma separated timeframes, e.g. 1m,5m,15m,30m")
    parser.add_argument("--length", type=int, default=8000, help="Max bars per request (default 8000)")
    args = parser.parse_args()

    syms = [s.strip() for s in args.symbols.split(",") if s.strip()] if args.symbols else None
    tfs = [t.strip() for t in args.timeframes.split(",") if t.strip()] if args.timeframes else None

    download_tq_klines(target_symbols=syms, target_tfs=tfs, data_length=args.length)
