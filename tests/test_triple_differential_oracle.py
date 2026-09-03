"""
test_triple_differential_oracle.py — 验证三轨差分预言机与 AKQuant 压力评分卡流水线
"""

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CODE_DIR = PROJECT_ROOT / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from akquant_strategy_template import AkquantStrategyBase, Bar
from triple_differential_oracle import TripleDifferentialOracle
from akquant_stress_and_scorecard import AkquantStressAndScorecardPipeline


class MockTrendStrategy(AkquantStrategyBase):
    strategy_name = "MockTrendStrategy"

    def __init__(self):
        super().__init__()
        self.count = 0

    def on_bar(self, bar: Bar):
        self.count += 1
        if self.count % 2 == 1:
            self.buy(bar.symbol, 1)
        else:
            self.close_position(bar.symbol)


class TestTripleDifferentialAndScorecard(unittest.TestCase):

    def test_01_triple_oracle_consistency(self):
        oracle = TripleDifferentialOracle()
        internal_mock = {
            "total_net_pnl": 12500.0,
            "total_trades": 10,
            "win_rate_pct": 60.0,
            "max_drawdown_pct": 4.5,
            "profit_factor": 1.85,
        }

        # 启动三轨差分审计
        audit_report = oracle.run_triple_audit(
            symbol="AG_IDX",
            strategy_class_akquant=MockTrendStrategy,
            internal_summary=internal_mock,
            timeframe="15m"
        )

        self.assertIn("status", audit_report)
        self.assertIn("results_summary", audit_report)
        self.assertIn("Lianghua_Internal", audit_report["results_summary"])
        self.assertIn("AKQuant", audit_report["results_summary"])

    def test_02_stress_and_scorecard_pipeline(self):
        pipeline = AkquantStressAndScorecardPipeline(initial_cash=1_000_000.0)
        report = pipeline.run_full_stress_and_scorecard(
            symbol="AG_IDX",
            strategy_class=MockTrendStrategy,
            timeframe="15m"
        )

        self.assertIn("scorecard", report)
        self.assertIn("baseline_1x_metrics", report)
        self.assertIn("stress_3x_metrics", report)
        self.assertTrue("total_score" in report["scorecard"] or "score_breakdown" in report["scorecard"])

    def test_03_oracle_strict_fail_closed_gates(self):
        oracle = TripleDifferentialOracle()
        # 构造故意不匹配的内部指标 (触发门禁失败)
        divergent_mock = {
            "total_net_pnl": 999999.0, # 巨大偏差
            "total_trades": 999,       # 笔数不一致
            "win_rate_pct": 99.0,
            "max_drawdown_pct": 1.0,
            "profit_factor": 10.0,
        }

        audit_report = oracle.run_triple_audit(
            symbol="AG_IDX",
            strategy_class_akquant=MockTrendStrategy,
            internal_summary=divergent_mock,
            timeframe="15m"
        )

        self.assertEqual(audit_report["status"], "FAIL_DIFF_GATE")
        self.assertGreater(len(audit_report["warnings"]), 0)


if __name__ == "__main__":
    unittest.main()
