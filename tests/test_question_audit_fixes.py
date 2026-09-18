# -*- coding: utf-8 -*-
"""
Unit tests for Question.md Systematic Audit Fixes (tests/test_question_audit_fixes.py)
Validates:
1. avg_oos_sharpe <= 0.0 and oos_pass_rate < 50% are strict non-exempt hard gates (rejected to GRAVEYARD).
2. Dynamic mutation generator breaks 65-formula limit via prime combinatorics (27,000+ space).
3. get_existing_formula_hashes excludes LEGACY_UNVERIFIED factors.
4. get_legacy_unverified_factors correctly loads legacy queue for prioritized re-evaluation.
"""

import os
import sys
import unittest
import sqlite3
import tempfile
from unittest.mock import patch
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "code")))
import continuous_alpha_miner as miner
import autonomous_alpha_research_engine as engine

class TestQuestionAuditFixes(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db = os.path.join(self.temp_dir.name, "test_quant.db")
        self.orig_miner_db = miner.DB_PATH
        self.orig_engine_db = engine.DB_PATH
        miner.DB_PATH = self.test_db
        engine.DB_PATH = self.test_db

    def tearDown(self):
        miner.DB_PATH = self.orig_miner_db
        engine.DB_PATH = self.orig_engine_db
        self.temp_dir.cleanup()

    def test_oos_hard_gate_rejection_negative_sharpe(self):
        """验证 avg_oos_sharpe <= 0.0 即使样本内指标优异也会被一票否决至 GRAVEYARD"""
        factor_def = {
            "id": "FAC_TEST_OOS_FAIL",
            "name": "测试OOS负收益因子",
            "family": "动量家族 (Momentum)",
            "hypothesis": "验证样本外一票否决",
            "formula": "Close.pct_change(5)",
            "calc": lambda df: df["close"].pct_change(5),
            "direction": 1,
        }

        # 模拟单次回测结果：IS 表现极佳（Sharpe 2.5），但 OOS 表现崩溃（Sharpe -0.3）
        mock_res = {
            "symbol": "AU_IDX",
            "success": True,
            "trades": 60,
            "win_rate": 55.0,
            "profit_factor": 1.6,
            "sharpe": 2.5,
            "oos_sharpe": -0.3, # 负 OOS
            "max_dd": 4.0,
            "net_pnl": 1000.0,
            "pnl_3x": 600.0,
            "rank_ic": 0.06,
            "ic_std": 0.02,
        }

        with patch("autonomous_alpha_research_engine.evaluate_factor_on_symbol", return_value=mock_res):
            res = engine.evaluate_and_score_factor(factor_def, test_symbols=["AU_IDX", "AG_IDX"])
            self.assertEqual(res["status"], "GRAVEYARD")
            self.assertIsNotNone(res.get("fail_reason"))
            self.assertIn("样本外 (OOS 20%) 表现崩塌", res["fail_reason"])

    def test_oos_hard_gate_rejection_low_pass_rate(self):
        """验证 oos_pass_rate < 50% 会触发一票否决至 GRAVEYARD"""
        factor_def = {
            "id": "FAC_TEST_OOS_LOW_PASS",
            "name": "测试OOS低通过率因子",
            "family": "动量家族 (Momentum)",
            "hypothesis": "验证多品种OOS通过率门槛",
            "formula": "Close.pct_change(10)",
            "calc": lambda df: df["close"].pct_change(10),
            "direction": 1,
        }

        # 构造 AU_IDX 盈利但 AG_IDX 和 CU_IDX 亏损 (通过率 33.3% < 50%)
        def mock_eval_symbol(fdef, s):
            if s == "AU_IDX":
                oos_sh = 1.2
            else:
                oos_sh = -0.1
            return {
                "symbol": s,
                "success": True,
                "trades": 60,
                "win_rate": 52.0,
                "profit_factor": 1.4,
                "sharpe": 1.5,
                "oos_sharpe": oos_sh,
                "max_dd": 5.0,
                "net_pnl": 1000.0,
                "pnl_3x": 500.0,
                "rank_ic": 0.05,
                "ic_std": 0.02,
            }

        with patch("autonomous_alpha_research_engine.evaluate_factor_on_symbol", side_effect=mock_eval_symbol):
            res = engine.evaluate_and_score_factor(factor_def, test_symbols=["AU_IDX", "AG_IDX", "CU_IDX"])
            self.assertEqual(res["status"], "GRAVEYARD")
            self.assertIsNotNone(res.get("fail_reason"))
            self.assertIn("跨品种样本外泛化失败", res["fail_reason"])

    def test_dynamic_mutation_diversity(self):
        """验证 1000 次变体生成器生成公式多样性，彻底破除 65 种上限"""
        formulas = set()
        for i in range(1000):
            dyn = miner.generate_dynamic_mutation(i)
            formulas.add(dyn["formula"])
        # 验证 1000 次抽取产生至少 800 个不同的公式字符串
        self.assertGreaterEqual(len(formulas), 800, f"Expected >= 800 unique formulas, got {len(formulas)}")

    def test_get_existing_formula_hashes_excludes_legacy(self):
        """验证 get_existing_formula_hashes 排除 LEGACY_UNVERIFIED"""
        conn = sqlite3.connect(self.test_db)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE factor_zoo (
                factor_id TEXT PRIMARY KEY,
                formula_hash TEXT,
                status TEXT
            )
        """)
        h_promoted = "hash_promoted_12345"
        h_legacy = "hash_legacy_67890"
        cur.execute("INSERT INTO factor_zoo VALUES ('F_PRO', ?, 'PROMOTED')", (h_promoted,))
        cur.execute("INSERT INTO factor_zoo VALUES ('F_LEG', ?, 'LEGACY_UNVERIFIED')", (h_legacy,))
        conn.commit()
        conn.close()

        hashes = miner.get_existing_formula_hashes()
        self.assertIn(h_promoted, hashes)
        self.assertNotIn(h_legacy, hashes)

    def test_get_legacy_unverified_factors(self):
        """验证 get_legacy_unverified_factors 读取待重验历史因子"""
        conn = sqlite3.connect(self.test_db)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE factor_zoo (
                factor_id TEXT PRIMARY KEY,
                name TEXT,
                family TEXT,
                hypothesis TEXT,
                formula_dsl TEXT,
                status TEXT
            )
        """)
        cur.execute("""
            INSERT INTO factor_zoo VALUES 
            ('FAC_MOM_W16', '16周期动量因子', '动量', '历史假设', 'Close.diff(16)', 'LEGACY_UNVERIFIED'),
            ('PROMOTED_01', '合格因子', '波动率', '已晋级', 'Close.std(10)', 'PROMOTED'),
            ('UNKNOWN_01', '未知遗留因子', '未知', '未知假设', 'Unknown()', 'LEGACY_UNVERIFIED')
        """)
        conn.commit()
        conn.close()

        legacy_factors = miner.get_legacy_unverified_factors()
        self.assertEqual(len(legacy_factors), 1)
        self.assertEqual(legacy_factors[0]["id"], "FAC_MOM_W16")
        self.assertTrue(callable(legacy_factors[0]["calc"]))

if __name__ == "__main__":
    unittest.main()
