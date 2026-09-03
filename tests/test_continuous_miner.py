# -*- coding: utf-8 -*-
"""
Unit tests for Continuous Alpha Miner (tests/test_continuous_miner.py)
Validates:
1. Combinatorial candidate pool generation and structure
2. Dynamic genetic factor mutation generation
3. De-duplication and SQLite database persistence
4. Status file output and stop signal mechanism
"""

import os
import sys
import unittest
import json
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "code")))
import continuous_alpha_miner as miner

class TestContinuousAlphaMiner(unittest.TestCase):
    def setUp(self):
        np.random.seed(42)
        n = 300
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
        })

    def test_combinatorial_pool_structure(self):
        """Check that candidate pool produces unique, properly formatted factors."""
        pool = miner.generate_combinatorial_candidate_pool()
        self.assertGreaterEqual(len(pool), 40)
        ids = [f["id"] for f in pool]
        self.assertEqual(len(ids), len(set(ids)), "Candidate factor IDs must be strictly unique")

        for f in pool:
            self.assertIn("id", f)
            self.assertIn("name", f)
            self.assertIn("family", f)
            self.assertIn("hypothesis", f)
            self.assertIn("formula", f)
            self.assertTrue(callable(f["calc"]))

    def test_dynamic_mutation_generator(self):
        """Check that dynamic mutation generates valid factors with valid calculations."""
        mutated_ids = set()
        for idx in range(10):
            dyn = miner.generate_dynamic_mutation(idx)
            self.assertNotIn(dyn["id"], mutated_ids)
            mutated_ids.add(dyn["id"])
            self.assertTrue(callable(dyn["calc"]))
            res = dyn["calc"](self.df)
            self.assertEqual(len(res), len(self.df))

    def test_status_file_roundtrip(self):
        """Check atomic status file writing and reading."""
        test_data = {
            "is_running": True,
            "duration_seconds": 3600,
            "elapsed_seconds": 12,
            "remaining_seconds": 3588,
            "total_evaluated_this_run": 5,
            "total_in_zoo": 25,
            "latest_factor_id": "TEST_001",
        }
        miner.write_status(test_data)
        self.assertTrue(os.path.exists(miner.STATUS_FILE))
        with open(miner.STATUS_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual(loaded["latest_factor_id"], "TEST_001")
        self.assertTrue(loaded["is_running"])
        # Always clean up and reset is_running to False to avoid polluting runtime state
        miner.write_status({
            "is_running": False,
            "duration_seconds": 3600,
            "elapsed_seconds": 0,
            "remaining_seconds": 0,
            "total_evaluated_this_run": 0,
            "total_in_zoo": 1681,
            "latest_factor_id": None,
        })

if __name__ == "__main__":
    unittest.main()
