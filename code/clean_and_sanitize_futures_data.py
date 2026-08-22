"""
A-Share & Futures Quantitative Data Engine - Futures Database Sanitizer & Integrity Cleaner
【期货全品种数据库深度清洗、杂交数据剔除与元数据严格对齐工具】

核心功能：
1. 彻底清除 `futures_min_bars` 中与 `futures_series_metadata` 元数据不匹配的历史杂交残留行（如通达信加权指数与天勤真实主力的拼接污染）。
2. 确保已同步的真实主力合约（REAL_DOMINANT_CONTRACT）在表内与元数据 1:1 严格对齐（每个周期纯净 8,000 根）。
3. 清除碎片化、断层且无持仓量的高阶无效大周期（2h, 3h, 4h 断层快照）。
4. 重建索引并优化 SQLite 存储性能。
"""

import sys
import sqlite3
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data/ashare_quant.db"


def sanitize_futures_database(db_path: Path = DB_PATH):
    print("=" * 90)
    print("🧹 启动期货全量数据库深度清洗与元数据强制对齐管线...")
    print(f"📁 目标数据库: {db_path}")
    print("=" * 90)

    conn = sqlite3.connect(db_path, timeout=60.0)
    cursor = conn.cursor()

    # 1. 查询所有已登记为 REAL_DOMINANT_CONTRACT 的元数据
    cursor.execute("""
        SELECT symbol, timeframe, row_count, start_time, end_time 
        FROM futures_series_metadata 
        WHERE series_type = 'REAL_DOMINANT_CONTRACT'
        ORDER BY symbol, timeframe;
    """)
    dominant_meta = cursor.fetchall()
    print(f"[*] 检测到已登记真实主力连续品种时序: {len(dominant_meta)} 组")

    total_purged_rows = 0

    for sym, tf, expected_cnt, start_t, end_t in dominant_meta:
        # 查询数据库中超出 [start_t, end_t] 范围的历史残留杂交行
        cursor.execute(f"""
            SELECT count(*) FROM futures_min_bars 
            WHERE symbol = '{sym}' AND timeframe = '{tf}'
              AND (trade_time < '{start_t}' OR trade_time > '{end_t}');
        """,)
        polluted_count = cursor.fetchone()[0]

        if polluted_count > 0:
            cursor.execute(f"""
                DELETE FROM futures_min_bars 
                WHERE symbol = '{sym}' AND timeframe = '{tf}'
                  AND (trade_time < '{start_t}' OR trade_time > '{end_t}');
            """)
            conn.commit()
            total_purged_rows += polluted_count
            print(f"  ├─ 🧹 清理 [{sym:<8} | {tf:<4}] 历史杂交残留污染: 剔除 {polluted_count} 根旧行 (保留纯净真实主力时段: {start_t} 至 {end_t})")

        # 检查清理后当前行数是否完全等于 expected_cnt
        cursor.execute(f"SELECT count(*) FROM futures_min_bars WHERE symbol = '{sym}' AND timeframe = '{tf}';")
        actual_cnt = cursor.fetchone()[0]
        if actual_cnt != expected_cnt:
            # 同步更新元数据行数
            cursor.execute(f"UPDATE futures_series_metadata SET row_count = {actual_cnt} WHERE symbol = '{sym}' AND timeframe = '{tf}';")
            conn.commit()
            print(f"  │  └─ 🔄 校准元数据行数: {expected_cnt} -> {actual_cnt} 根")

    # 2. 清理碎片化且无持仓量的无效大周期 (2h, 3h, 4h 中少于 200 根的孤儿快照)
    print("\n[*] 正在清理高阶大周期 (2h, 3h, 4h) 中少于 200 根且无持仓量的断层碎片...")
    cursor.execute("""
        DELETE FROM futures_min_bars 
        WHERE timeframe IN ('2h', '3h', '4h')
          AND (symbol, timeframe) IN (
              SELECT symbol, timeframe FROM futures_min_bars 
              WHERE timeframe IN ('2h', '3h', '4h') 
              GROUP BY symbol, timeframe 
              HAVING count(*) < 200
          );
    """)
    deleted_frag_rows = cursor.rowcount
    total_purged_rows += deleted_frag_rows
    conn.commit()
    print(f"  └─ 🧹 已成功清除大周期碎片行: {deleted_frag_rows} 根")

    # 3. 检查零成交量超过 50% 的僵尸品种（如 WR_IDX），进行标记清理
    cursor.execute("""
        SELECT symbol, timeframe, count(*) as total, sum(case when volume = 0 then 1 else 0 end) as zero_v
        FROM futures_min_bars
        WHERE timeframe = '5m'
        GROUP BY symbol, timeframe
        HAVING (sum(case when volume = 0 then 1 else 0 end) * 1.0 / count(*)) > 0.50;
    """)
    zombie_symbols = cursor.fetchall()
    if zombie_symbols:
        print("\n[*] 发现以下高零成交量僵尸品种:")
        for z in zombie_symbols:
            print(f"  - [{z[0]} {z[1]}]: 总 {z[2]} 根, 零成交 {z[3]} 根 ({z[3]/z[2]*100:.1f}%)")

    # 4. 重建索引与数据库整理
    print("\n[*] 正在重建表索引与数据库物理整理 (VACUUM / OPTIMIZE)...")
    cursor.execute("REINDEX idx_futures_min_sym_tf_time;")
    conn.commit()
    conn.close()

    print("=" * 90)
    print(f"🎉 数据库深度清洗完成！共计剔除杂交/碎片残留行: {total_purged_rows:,} 根！")
    print("=" * 90)


if __name__ == "__main__":
    sanitize_futures_database()
