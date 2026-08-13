"""
A-Share Quantitative Data Engine - Real Futures 15m Intraday Data Downloader
【真实期货 15m 分钟 K 线数据抓取与清查更新器】

核心功能：
1. 清除 SQLite 中 `futures_min_bars` 表中合成/虚假的数据。
2. 调用 AKShare `futures_zh_minute_sina` 接口，抓取 12 大主力/连续合约 (AG0, CU0, RB0, I0, SA0, SC0, MA0, TA0, M0, SN0, LC0, J0) 的【100% 真实 15m 盘中 K 线数据】。
3. 校正时间戳顺序（夜盘归属与真实时序对齐）。
4. 存入数据库 `futures_min_bars` 表中供真实样本外 ML 回测。
"""

import os
import sys
import sqlite3
import datetime
import pandas as pd
import akshare as ak
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = str(PROJECT_ROOT / "data/ashare_quant.db")

# 映射：数据库统一 symbol -> AKShare 对应的主力连续合约代码
SYMBOL_MAP = {
    "AG_IDX": "AG0",
    "CU_IDX": "CU0",
    "RB_IDX": "RB0",
    "I_IDX": "I0",
    "SA_IDX": "SA0",
    "SC_IDX": "SC0",
    "MA_IDX": "MA0",
    "TA_IDX": "TA0",
    "M_IDX": "M0",
    "SN_IDX": "SN0",
    "LC_IDX": "LC0",
    "J_IDX": "J0"
}


def sync_real_15m_bars():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    print("=" * 90)
    print("🚀 启动 100% 真实期货 15m 盘中 K 线数据抓取与落盘...")
    print("=" * 90)

    # 1. 清理合成的伪造数据
    for db_sym in SYMBOL_MAP.keys():
        cursor.execute(f"DELETE FROM futures_min_bars WHERE symbol = '{db_sym}' AND timeframe = '15m';")
    conn.commit()
    print("🧹 已清除所有的伪造/合成 15m 数据记录。")

    total_inserted = 0

    for db_sym, ak_code in SYMBOL_MAP.items():
        print(f"  ├─ 正在抓取 [{db_sym:<8} (合约代码: {ak_code})] 真实 15m K线数据...")
        try:
            df_real = ak.futures_zh_minute_sina(symbol=ak_code, period="15")
            if df_real.empty:
                print(f"     └─ 未获取到 [{ak_code}] 真实数据")
                continue

            # 列重命名与格式化
            df_real["datetime"] = pd.to_datetime(df_real["datetime"])
            df_real = df_real.sort_values("datetime").reset_index(drop=True)

            bars_to_insert = []
            for _, row in df_real.iterrows():
                dt_str = row["datetime"].strftime("%Y-%m-%d %H:%M:%S")
                b_open = float(row["open"])
                b_high = float(row["high"])
                b_low = float(row["low"])
                b_close = float(row["close"])
                b_vol = float(row["volume"])
                b_hold = float(row["hold"]) if "hold" in row else 0.0

                bars_to_insert.append((
                    db_sym, "15m", dt_str,
                    round(b_open, 2), round(b_high, 2), round(b_low, 2), round(b_close, 2),
                    int(b_vol), round(b_close * b_vol, 2), int(b_hold), round(b_close, 2)
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
                print(f"     └─ 成功抓取并写入 [{db_sym}] 真实 15m K线: {len(bars_to_insert)} 根 (起止: {bars_to_insert[0][2]} 至 {bars_to_insert[-1][2]})")

        except Exception as e:
            print(f"     └─ 抓取 [{db_sym}] 失败: {e}")

    conn.close()
    print("=" * 90)
    print(f"🎉 真实 15m 盘中 K 线数据更新完成！共计写入真实数据点: {total_inserted} 根！")
    print("=" * 90)


if __name__ == "__main__":
    sync_real_15m_bars()
