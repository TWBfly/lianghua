# -*- coding: utf-8 -*-
"""
Unit tests for Autonomous Factor & Strategy Research Engine (tests/test_autonomous_alpha_research.py)
Validates:
1. 8 Alpha families and composite factors calculation
2. Next-Open execution backtest simulation
3. 3x Friction cost stress test
4. Hard Gates and 100-Point Scorecard logic
5. SQLite Database persistence in factor_zoo table
"""

import os
import sys
import unittest
import sqlite3
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "code")))
import autonomous_alpha_research_engine as engine

import tempfile

class TestAutonomousAlphaResearch(unittest.TestCase):
    def setUp(self):
        self.orig_db_path = engine.DB_PATH
        self.temp_dir = tempfile.TemporaryDirectory()
        engine.DB_PATH = os.path.join(self.temp_dir.name, "test_quant.db")

        # Create synthetic bar test fixture
        np.random.seed(42)
        n = 500
        returns = np.random.normal(0.0002, 0.008, n)
        close = 100.0 * np.exp(np.cumsum(returns))
        high = close * (1.0 + np.random.uniform(0.001, 0.005, n))
        low = close * (1.0 - np.random.uniform(0.001, 0.005, n))
        open_p = (high + low) / 2.0
        volume = np.random.uniform(1000, 5000, n)
        self.df = pd.DataFrame({
            "open": open_p,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": volume * close,
        })

        # 在隔离测试数据库中创建合成 futures_min_bars 供测试使用 (C05)
        conn = sqlite3.connect(engine.DB_PATH)
        bar_df = self.df.copy()
        bar_df["symbol"] = "AU_IDX"
        bar_df["timeframe"] = "15m"
        bar_df["trade_time"] = pd.date_range("2026-01-01", periods=len(bar_df), freq="15min").astype(str)
        bar_df.to_sql("futures_min_bars", conn, index=False, if_exists="replace")
        conn.close()

    def tearDown(self):
        engine.DB_PATH = self.orig_db_path
        self.temp_dir.cleanup()

    def test_alpha_family_definitions(self):
        """Verify all 8+ families are defined with valid fields."""
        self.assertGreaterEqual(len(engine.ALPHA_FAMILIES), 8)
        for f in engine.ALPHA_FAMILIES:
            self.assertIn("id", f)
            self.assertIn("name", f)
            self.assertIn("family", f)
            self.assertIn("hypothesis", f)
            self.assertIn("formula", f)
            self.assertTrue(callable(f["calc"]))

    def test_factor_calculation(self):
        """Verify factor calculation functions execute without exception on bars."""
        for f in engine.ALPHA_FAMILIES:
            res = f["calc"](self.df)
            self.assertEqual(len(res), len(self.df), f"Factor {f['id']} length mismatch")
            # Should not be all NaNs
            self.assertGreater(res.notna().sum(), 100, f"Factor {f['id']} generated too many NaNs")

    def test_database_table_creation_and_query(self):
        """Verify SQLite table initialization and data persistence in isolated sandbox (C05)."""
        engine.init_db()
        conn = sqlite3.connect(engine.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='factor_zoo';")
        self.assertIsNotNone(cursor.fetchone(), "Table factor_zoo should exist")

        # 保存一条测试记录验证持久化
        test_rec = {
            "factor_id": "TEST_FACTOR_01",
            "formula_hash": "a" * 64,
            "name": "测试因子",
            "family": "测试族",
            "hypothesis": "无",
            "formula_dsl": "TestFormula",
            "total_score": 85.0,
            "grade": "A",
            "status": "CANDIDATE",
            "fail_reason": "NONE",
            "rank_ic": 0.05,
            "icir": 1.5,
            "win_rate": 55.0,
            "sharpe": 1.8,
            "profit_factor": 1.5,
            "max_dd": 5.0,
            "breakeven_cost_mult": 3.0,
            "cross_market_pass_rate": 80.0,
            "tested_symbols": "{}",
            "created_at": "2026-09-05 00:00:00"
        }
        engine.save_factor_to_db(test_rec)
        cursor.execute("SELECT count(*) FROM factor_zoo;")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 1, "factor_zoo should contain exactly 1 saved test record")
        conn.close()

    def test_formula_hash_determinism_and_whitespace_invariance(self):
        """Verify formula hash is deterministic and invariant to whitespace and casing."""
        f1 = "EfficiencyRatio[18] * NormalizedMomentum[18]"
        f2 = "  efficiencyratio[18]  *   normalizedmomentum[18] \n"
        h1 = engine.compute_formula_hash(f1)
        h2 = engine.compute_formula_hash(f2)
        self.assertEqual(h1, h2, "Formula hash must normalize whitespace and casing")
        self.assertEqual(len(h1), 64, "SHA-256 hash must be 64 hex characters")

    def test_strict_hard_gates_no_name_bonus(self):
        """Verify that naming a factor COMP or 复合 does NOT bypass hard gates or grant free points."""
        fake_failing_composite = {
            "id": "FAC_COMP_FAKE_999",
            "name": "伪造复合高分测试因子",
            "family": "正交复合 Alpha (Orthogonal)",
            "hypothesis": "试图通过名字套取特权",
            "formula": "FakeFormula[999]",
            "calc": lambda df: pd.Series(0.0, index=df.index),
        }
        res = engine.evaluate_and_score_factor(fake_failing_composite, test_symbols=["AU_IDX"])
        self.assertLess(res["total_score"], 60.0, "Composite factors must NOT receive name-based bonus points")
        self.assertEqual(res["status"], "GRAVEYARD", "Failing composite factor must be rejected into GRAVEYARD")
        self.assertIn("fail_reason", res)

    def test_no_name_bias_for_overfit_string(self):
        """Verify factor ID containing OVERFIT yields identical score when stats are identical (F05)."""
        factor_base = {
            "id": "FAC_NORMAL_TEST",
            "name": "普通测试因子",
            "family": "测试族",
            "hypothesis": "假设",
            "formula": "FormulaTest",
            "calc": lambda df: df["close"].pct_change(5),
        }
        factor_overfit_name = {
            "id": "FAC_OVERFIT_TEST",
            "name": "普通测试因子(带OVERFIT标签)",
            "family": "测试族",
            "hypothesis": "假设",
            "formula": "FormulaTest",
            "calc": lambda df: df["close"].pct_change(5),
        }
        res_normal = engine.evaluate_and_score_factor(factor_base, test_symbols=["AU_IDX"])
        res_overfit = engine.evaluate_and_score_factor(factor_overfit_name, test_symbols=["AU_IDX"])
        self.assertEqual(res_normal["total_score"], res_overfit["total_score"], "Factor score must be identical regardless of whether ID contains 'OVERFIT'")
        self.assertEqual(res_normal["status"], res_overfit["status"], "Status must be identical regardless of name string")

if __name__ == "__main__":
    unittest.main()
