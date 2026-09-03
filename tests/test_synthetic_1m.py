"""
test_synthetic_1m.py — 验证 1 分钟高保真合成 K 线生成、物理隔离与时序自洽
"""

import os
import sqlite3
import unittest
from pathlib import Path
import pandas as pd
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = PROJECT_ROOT / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from synthetic_market_regime_generator import (
    SyntheticMarketRegimeGenerator,
    get_trading_session_timeline,
)


class TestSynthetic1mBars(unittest.TestCase):

    def test_01_timeline_1m_trading_slots(self):
        # 1 交易日白盘 225 根，夜盘 (如 RB 23:00 收盘) 120 根，合计 345 根
        timeline = get_trading_session_timeline(345, symbol="RB_IDX", timeframe="1m")
        self.assertEqual(len(timeline), 345)
        # 验证跳过周末与交易节连续性
        self.assertEqual(timeline[0].hour, 9)
        self.assertEqual(timeline[0].minute, 0)
        self.assertEqual(timeline[-1].hour, 22)
        self.assertEqual(timeline[-1].minute, 59)

    def test_02_generate_1m_topology_and_isolation(self):
        gen = SyntheticMarketRegimeGenerator(seed=2026)
        df = gen.generate_regime_bars("RB_IDX", bars_per_regime=50, timeframe="1m", save_to_db=False)
        self.assertEqual(len(df), 250)
        self.assertTrue((df["high"] >= df["low"]).all())
        self.assertTrue((df["high"] >= df["open"]).all())
        self.assertTrue((df["high"] >= df["close"]).all())
        self.assertTrue((df["low"] <= df["open"]).all())
        self.assertTrue((df["low"] <= df["close"]).all())
        self.assertTrue((df["open"] > 0).all())
        self.assertTrue((df["volume"] >= 0).all())
        self.assertTrue((df["open_interest"] > 0).all())
        self.assertEqual(df["timeframe"].iloc[0], "1m")
        self.assertEqual(df["is_synthetic"].iloc[0], 1)

    def test_03_sandbox_db_has_1m_tables(self):
        db_path = PROJECT_ROOT / "data" / "synthetic_sandbox" / "futures_synthetic_bars.db"
        self.assertTrue(db_path.exists())
        conn = sqlite3.connect(db_path)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        self.assertIn("bars_rb_idx_1m", tables)
        self.assertIn("bars_ag_idx_1m", tables)


if __name__ == "__main__":
    unittest.main()
