"""
Check date ranges and bar counts for all 27 commodity symbols
"""

import sys
import sqlite3
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "code"))

from symbol_strategies.decoupled_5m_symbol_engines import SYMBOL_5M_CONFIGS

DB_PATH = str(PROJECT_ROOT / "data/ashare_quant.db")

conn = sqlite3.connect(DB_PATH)
rows = []
for sym, cfg in SYMBOL_5M_CONFIGS.items():
    q = f"""
        SELECT MIN(trade_time) as start_time, MAX(trade_time) as end_time, COUNT(*) as total_bars
        FROM futures_min_bars
        WHERE symbol = '{sym}' AND timeframe = '5m';
    """
    df = pd.read_sql(q, conn)
    rows.append({
        "symbol": sym,
        "name": cfg["name"],
        "category": cfg["category"],
        "start_time": df.iloc[0]["start_time"],
        "end_time": df.iloc[0]["end_time"],
        "total_bars": df.iloc[0]["total_bars"]
    })
conn.close()

res_df = pd.DataFrame(rows)
print(res_df.to_string(index=False))
