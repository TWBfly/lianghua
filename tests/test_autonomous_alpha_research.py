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

class TestAutonomousAlphaResearch(unittest.TestCase):
    def setUp(self):
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
        """Verify SQLite table initialization and data persistence."""
        engine.init_db()
        conn = sqlite3.connect(engine.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='factor_zoo';")
        self.assertIsNotNone(cursor.fetchone(), "Table factor_zoo should exist")

        cursor.execute("SELECT count(*) FROM factor_zoo;")
        count = cursor.fetchone()[0]
        self.assertGreater(count, 0, "factor_zoo should contain evaluated factors")
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
        # Should NOT get free 85+ score or bypass 3x friction gate
        self.assertLess(res["total_score"], 60.0, "Composite factors must NOT receive name-based bonus points")
        self.assertEqual(res["status"], "GRAVEYARD", "Failing composite factor must be rejected into GRAVEYARD")
        self.assertIn("fail_reason", res)

if __name__ == "__main__":
    unittest.main()
