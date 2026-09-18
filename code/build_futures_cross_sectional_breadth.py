"""
code/build_futures_cross_sectional_breadth.py
预计算商品期货 30m 截面异动与系统性暴跌广度矩阵 (Breadth Matrix)
遵循 ponytail 极简原则：纯因果、单文件、无额外依赖、保持原始数据库只读。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "ashare_quant.db"
OUTPUT_CSV = DATA_DIR / "futures_breadth_30m.csv"


def calculate_cross_sectional_breadth(timeframe: str = "30m") -> pd.DataFrame:
    """
    从 futures_min_bars 提取指定周期的全部主力序列，构建截面收益率与暴跌广度矩阵。
    """
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found at {DB_PATH}")

    conn = sqlite3.connect(str(DB_PATH))
    query = """
    SELECT trade_time, symbol, close
    FROM futures_min_bars
    WHERE timeframe = ?
    ORDER BY trade_time ASC, symbol ASC
    """
    df_raw = pd.read_sql_query(query, conn, params=(timeframe,))
    conn.close()

    if df_raw.empty:
        raise ValueError(f"No bars found for timeframe {timeframe}")

    df_raw["trade_time"] = pd.to_datetime(df_raw["trade_time"])
    df_pivot = df_raw.pivot(index="trade_time", columns="symbol", values="close")
    df_pivot.sort_index(inplace=True)

    # 1. 逐品种单步因果收益率
    ret_df = df_pivot.pct_change(1, fill_method=None)

    # 2. 逐品种因果滚动波动率 (40 周期)
    roll_std = ret_df.rolling(40, min_periods=10).std(ddof=0) + 1e-8

    # 3. 逐品种无量纲 Z-Score
    z_ret = ret_df / roll_std

    # 4. 截面指标计算
    # 有效在场品种数
    active_count = z_ret.notna().sum(axis=1)

    # 极端下潜合约数 (收益率低于 -2.0 个局部标准差)
    # S01: 样本不足 (< 5) 时标记为 NaN (未知覆盖)，严禁编码为 0.0 伪造市场平静
    down_extreme_count = (z_ret < -2.0).sum(axis=1)
    down_breadth = np.where(active_count >= 5, down_extreme_count / active_count, np.nan)

    # 极端冲顶合约数 (收益率高于 +2.0 个局部标准差)
    up_extreme_count = (z_ret > 2.0).sum(axis=1)
    up_breadth = np.where(active_count >= 5, up_extreme_count / active_count, np.nan)

    # 截面中位数收益率 (系统性共模分量 Common Return)
    median_ret = ret_df.median(axis=1).fillna(0.0)

    breadth_df = pd.DataFrame({
        "trade_time": df_pivot.index,
        "active_symbols": active_count.values,
        "down_breadth": down_breadth,
        "up_breadth": up_breadth,
        "common_return": median_ret.values,
    })
    breadth_df.set_index("trade_time", inplace=True)
    return breadth_df


def main():
    print(f"[*] 正在从 {DB_PATH.name} 读取 30m 主力连续行情...")
    breadth_df = calculate_cross_sectional_breadth(timeframe="30m")
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    breadth_df.to_csv(OUTPUT_CSV)
    print(f"[+] 截面广度矩阵生成完毕: {len(breadth_df)} 行时间戳, 输出路径: {OUTPUT_CSV}")
    print(f"    - 平均在场品种数: {breadth_df['active_symbols'].mean():.1f}")
    print(f"    - 严重系统性暴跌 (down_breadth > 0.35) 次数: {(breadth_df['down_breadth'] > 0.35).sum()}")
    print(f"    - 严重系统性冲顶 (up_breadth > 0.35) 次数: {(breadth_df['up_breadth'] > 0.35).sum()}")


if __name__ == "__main__":
    main()
