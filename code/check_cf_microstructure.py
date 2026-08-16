import sys
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "code"))
from technical_indicators import calculate_atr, calculate_ema

DB_PATH = str(PROJECT_ROOT / "data/ashare_quant.db")
conn = sqlite3.connect(DB_PATH, timeout=30.0)
df = pd.read_sql("SELECT trade_time as datetime, open, high, low, close, volume FROM futures_min_bars WHERE symbol = 'CF_IDX' AND timeframe = '5m' ORDER BY trade_time ASC;", conn)
conn.close()
df["datetime"] = pd.to_datetime(df["datetime"])
df = df[(df["volume"] > 0) & (df["close"] > 0)].sort_values("datetime").reset_index(drop=True)

c = df["close"].values
h = df["high"].values
l = df["low"].values

df_temp = pd.DataFrame({"open": df["open"], "high": h, "low": l, "close": c})
atr = calculate_atr(df_temp, 14).fillna(pd.Series(c * 0.008)).values

print(f"CF_IDX 5m Total Bars: {len(df)}")
print(f"Mean ATR: {np.mean(atr):.2f}, Median ATR: {np.median(atr):.2f}, Min ATR: {np.min(atr):.2f}, Max ATR: {np.max(atr):.2f}")
print(f"Tick Size: 5.0 RMB. Mean ATR in Ticks: {np.mean(atr)/5.0:.2f} ticks!")
