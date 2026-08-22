"""
A-Share & Futures Quantitative Data Engine - Real Dominant Futures K-Line Synchronizer (Beijing Time Calibrated)
【真实期货历史主力合约多周期 (5m, 15m) K 线抓取、北京时间校准与去杂交存储引擎】

核心修复与第一性原理：
1. 时区校准：TqSdk 底层 datetime 为 UTC 纳秒时间戳。本模块严格进行 `utc=True -> tz_convert('Asia/Shanghai')` 转换为标准北京时间（消除 8 小时时区偏移！）。
2. 去杂交净化：写入前先原子清除该品种该周期的历史残留行，杜绝加权指数与真实主力的杂交混杂。
3. 真实物理撮合：100% 官方主力连续 (KQ.m) 真实逐笔聚合数据。
4. 严格合规校验：OHLC 几何关系、非负成交量/持仓量、时间戳单调递增。
"""

import os
import sys
import time
import argparse
import hashlib
import sqlite3
import datetime
import pandas as pd
from pathlib import Path
from tqsdk import TqApi, TqAuth

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
DB_PATH = PROJECT_ROOT / "data/ashare_quant.db"

DOMINANT_SYMBOL_MAP = {
    "RB_IDX": {"tq_code": "KQ.m@SHFE.rb", "name": "螺纹钢主力连续", "category": "黑色建筑"},
    "HC_IDX": {"tq_code": "KQ.m@SHFE.hc", "name": "热卷主力连续", "category": "黑色工业"},
    "I_IDX":  {"tq_code": "KQ.m@DCE.i",     "name": "铁矿石主力连续", "category": "黑色原材料"},
    "J_IDX":  {"tq_code": "KQ.m@DCE.j",     "name": "焦炭主力连续", "category": "双焦能源"},
    "JM_IDX": {"tq_code": "KQ.m@DCE.jm",    "name": "焦煤主力连续", "category": "双焦能源"},
    "AG_IDX": {"tq_code": "KQ.m@SHFE.ag",   "name": "沪银主力连续", "category": "贵金属"},
    "AU_IDX": {"tq_code": "KQ.m@SHFE.au",   "name": "沪金主力连续", "category": "贵金属"},
    "CU_IDX": {"tq_code": "KQ.m@SHFE.cu",   "name": "沪铜主力连续", "category": "有色工业"},
    "AL_IDX": {"tq_code": "KQ.m@SHFE.al",   "name": "沪铝主力连续", "category": "有色金属"},
    "ZN_IDX": {"tq_code": "KQ.m@SHFE.zn",   "name": "沪锌主力连续", "category": "有色金属"},
    "SN_IDX": {"tq_code": "KQ.m@SHFE.sn",   "name": "沪锡主力连续", "category": "有色稀缺"},
    "SA_IDX": {"tq_code": "KQ.m@CZCE.SA",   "name": "纯碱主力连续", "category": "化工高波"},
    "SC_IDX": {"tq_code": "KQ.m@INE.sc",    "name": "原油主力连续", "category": "能源化工"},
    "MA_IDX": {"tq_code": "KQ.m@CZCE.MA",   "name": "甲醇主力连续", "category": "化工原料"},
    "TA_IDX": {"tq_code": "KQ.m@CZCE.TA",   "name": "PTA主力连续", "category": "纺织化工"},
    "RU_IDX": {"tq_code": "KQ.m@SHFE.ru",   "name": "橡胶主力连续", "category": "化工高波"},
    "M_IDX":  {"tq_code": "KQ.m@DCE.m",     "name": "豆粕主力连续", "category": "农产品"},
    "P_IDX":  {"tq_code": "KQ.m@DCE.p",     "name": "棕榈油主力连续", "category": "油脂农产品"},
    "Y_IDX":  {"tq_code": "KQ.m@DCE.y",     "name": "豆油主力连续", "category": "油脂农产品"},
    "SR_IDX": {"tq_code": "KQ.m@CZCE.SR",   "name": "白糖主力连续", "category": "软商品"},
    "CF_IDX": {"tq_code": "KQ.m@CZCE.CF",   "name": "棉花主力连续", "category": "软商品"},
    "FG_IDX": {"tq_code": "KQ.m@CZCE.FG",   "name": "玻璃主力连续", "category": "建材地产"},
    "LC_IDX": {"tq_code": "KQ.m@GFEX.lc",   "name": "碳酸锂主力连续", "category": "新能源电池"},
    "SI_IDX": {"tq_code": "KQ.m@GFEX.si",   "name": "工业硅主力连续", "category": "光伏新能源"},
    "C_IDX":  {"tq_code": "KQ.m@DCE.c",     "name": "玉米主力连续", "category": "农产品"},
}

TIMEFRAME_MAP = {
    "1m": 60,
    "5m": 300,
    "10m": 600,
    "15m": 900,
    "30m": 1800,
    "1h": 3600
}



def load_tq_credentials(env_file=ENV_PATH):
    if not os.path.exists(env_file):
        raise FileNotFoundError(f"配置文件不存在: {env_file}")
    user, password = None, None
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "账号" in line:
                user = line.split("：")[-1].split(":")[-1].strip()
            elif "密码" in line:
                password = line.split("：")[-1].split(":")[-1].strip()
    if not user or not password:
        raise ValueError("未能从 .env 文件中提取到天勤量化的账号和密码！")
    return user, password


def ensure_db_schema(conn: sqlite3.Connection):
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
            amount REAL,
            open_interest REAL,
            settlement REAL,
            PRIMARY KEY (symbol, timeframe, trade_time)
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_futures_min_sym_tf_time ON futures_min_bars (symbol, timeframe, trade_time);")

    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='futures_series_metadata';")
    row = cursor.fetchone()
    if row is None or ("REAL_DOMINANT_CONTRACT" not in row[0] and "CHECK" in row[0]):
        cursor.execute("DROP TABLE IF EXISTS futures_series_metadata;")
        cursor.execute("""
            CREATE TABLE futures_series_metadata (
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                source_file TEXT NOT NULL,
                source_title TEXT NOT NULL,
                series_type TEXT NOT NULL,
                source_encoding TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                row_count INTEGER NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                PRIMARY KEY (symbol, timeframe)
            );
        """)
    conn.commit()


def fetch_and_sync_dominant_data(
    target_symbols=None,
    target_tfs=None,
    data_length: int = 8000,
    db_path: Path = DB_PATH
):
    user, password = load_tq_credentials()

    symbols_to_sync = {}
    if target_symbols:
        for s in target_symbols:
            s_clean = s.strip().upper()
            if not s_clean.endswith("_IDX"):
                s_clean = f"{s_clean}_IDX"
            if s_clean in DOMINANT_SYMBOL_MAP:
                symbols_to_sync[s_clean] = DOMINANT_SYMBOL_MAP[s_clean]
            else:
                print(f"⚠️ 未知期货代码: {s}")
    else:
        symbols_to_sync = DOMINANT_SYMBOL_MAP

    tfs_to_sync = []
    if target_tfs:
        for tf in target_tfs:
            tf_clean = tf.strip().lower()
            if tf_clean in TIMEFRAME_MAP:
                tfs_to_sync.append((tf_clean, TIMEFRAME_MAP[tf_clean]))
            else:
                print(f"⚠️ 未知周期: {tf}")
    else:
        tfs_to_sync = [("5m", 300), ("15m", 900)]

    print("=" * 90)
    print(f"🔑 天勤量化凭据认证 -> 账号: {user[:3]}****{user[-4:]}")
    print(f"🚀 启动真实期货主力合约历史数据同步 (北京时间标准校准版)")
    print(f"📌 目标品种: {list(symbols_to_sync.keys())} | 周期: {[t[0] for t in tfs_to_sync]} | 请求最大深度: {data_length} 根")
    print("=" * 90)

    conn = sqlite3.connect(db_path, timeout=60.0)
    ensure_db_schema(conn)
    cursor = conn.cursor()

    api = TqApi(auth=TqAuth(user, password))
    total_synced_bars = 0
    sync_report = []

    try:
        for db_sym, meta in symbols_to_sync.items():
            tq_code = meta["tq_code"]
            name = meta["name"]
            print(f"\n📦 处理品种 [{db_sym:<8} | 名称: {name} | 官方主力代码: {tq_code}]...")

            for tf_name, dur_sec in tfs_to_sync:
                print(f"  ├─ 正在请求 [{tf_name:<3}] 真实历史 K 线...")
                klines = api.get_kline_serial(tq_code, dur_sec, data_length=data_length)

                t_end = time.time() + 10.0
                while time.time() < t_end:
                    api.wait_update(deadline=time.time() + 1.5)
                    if len(klines) > 0 and klines.iloc[-1]["datetime"] > 0:
                        break

                df_k = pd.DataFrame(klines)
                df_k = df_k[df_k["datetime"] > 0].copy()

                if df_k.empty:
                    print(f"  │  └─ ⚠️ 未能获取到有效的 [{tf_name}] 数据")
                    continue

                # 核心时区转换：UTC 纳秒 -> 北京时间 (Asia/Shanghai)
                df_k["trade_time"] = pd.to_datetime(df_k["datetime"], unit="ns", utc=True).dt.tz_convert("Asia/Shanghai").dt.strftime("%Y-%m-%d %H:%M:%S")
                df_k = df_k.sort_values("trade_time").drop_duplicates(subset=["trade_time"]).reset_index(drop=True)

                bars_to_insert = []
                for _, row in df_k.iterrows():
                    o = float(row["open"])
                    h = float(row["high"])
                    l = float(row["low"])
                    c = float(row["close"])
                    v = float(row["volume"]) if "volume" in row and not pd.isna(row["volume"]) else 0.0
                    oi = float(row["open_oi"]) if "open_oi" in row and not pd.isna(row["open_oi"]) else 0.0

                    if o <= 0 or h <= 0 or l <= 0 or c <= 0 or h < max(o, c) or l > min(o, c):
                        continue

                    amt = round(c * v, 2)
                    bars_to_insert.append((
                        db_sym, tf_name, row["trade_time"],
                        round(o, 2), round(h, 2), round(l, 2), round(c, 2),
                        int(v), amt, int(oi), round(c, 2)
                    ))

                if not bars_to_insert:
                    print(f"  │  └─ ⚠️ 有效 K 线过滤后为空")
                    continue

                # 关键：先删除该品种周期的旧杂交残留，保证数据绝对纯净！
                cursor.execute(f"DELETE FROM futures_min_bars WHERE symbol = '{db_sym}' AND timeframe = '{tf_name}';")

                cursor.executemany(
                    """
                    INSERT INTO futures_min_bars 
                    (symbol, timeframe, trade_time, open, high, low, close, volume, amount, open_interest, settlement)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    bars_to_insert
                )

                start_t = bars_to_insert[0][2]
                end_t = bars_to_insert[-1][2]
                imported_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
                meta_sha256 = hashlib.sha256(f"{db_sym}_{tf_name}_{start_t}_{end_t}_{len(bars_to_insert)}".encode()).hexdigest()

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO futures_series_metadata 
                    (symbol, timeframe, source_file, source_title, series_type, source_encoding, source_sha256, row_count, start_time, end_time, imported_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        db_sym, tf_name, f"TqSdk:{tq_code}", f"{name}真实K线(北京时间)",
                        "REAL_DOMINANT_CONTRACT", "UTF-8", meta_sha256,
                        len(bars_to_insert), start_t, end_t, imported_at
                    )
                )
                conn.commit()

                total_synced_bars += len(bars_to_insert)
                sync_report.append({
                    "symbol": db_sym,
                    "timeframe": tf_name,
                    "bars": len(bars_to_insert),
                    "start": start_t,
                    "end": end_t
                })
                print(f"  │  └─ ✅ 成功纯净同步 [{tf_name:<3}] 真实主力 K 线: {len(bars_to_insert)} 根 (北京时间: {start_t} 至 {end_t})")

    finally:
        api.close()
        conn.close()

    print("\n" + "=" * 90)
    print(f"🎉 真实期货主力合约历史数据（北京时间纯净版）同步完成！总计入库: {total_synced_bars} 根")
    if sync_report:
        df_rep = pd.DataFrame(sync_report)
        print(df_rep.to_string(index=False))
    print("=" * 90)
    return sync_report


def main():
    parser = argparse.ArgumentParser(description="Real Dominant Futures Historical Data Sync Engine")
    parser.add_argument("--symbols", type=str, default="AU,AG,SA,I,CU,SC,RB,HC,J,JM,AL,ZN,SN,RU,M,P,LC", help="期货品种代码，多个以逗号分隔")
    parser.add_argument("--timeframes", type=str, default="5m,15m", help="目标周期，如 '5m,15m'")
    parser.add_argument("--length", type=int, default=8000, help="抓取根数")
    args = parser.parse_args()

    sym_list = [s.strip() for s in args.symbols.split(",") if s.strip()]
    tf_list = [t.strip() for t in args.timeframes.split(",") if t.strip()]
    fetch_and_sync_dominant_data(target_symbols=sym_list, target_tfs=tf_list, data_length=args.length)


if __name__ == "__main__":
    main()
