"""
Unit tests for StrategyEvaluatorAgent and 100-Point Quantitative Evaluation System.
"""

import unittest
from pathlib import Path
import os
import sys

CODE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "code")
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from strategy_evaluator_agent import StrategyEvaluatorAgent, StrategyEvaluationDecision, audit_and_confirm


COMPLETE_METRICS = {
    "trading_period": "2025-01-01 ~ 2025-12-31",
    "asset_type": "期货",
    "symbols_summary": "10 个标的",
    "total_net_pnl": 100_000.0,
    "profitable_symbols_ratio": 0.9,
    "mean_rank_ic": 0.045,
    "rank_icir": 2.2,
    "ic_positive_ratio": 0.62,
    "monotonicity": 0.95,
    "sharpe_ratio": 2.8,
    "sortino_ratio": 4.0,
    "calmar_ratio": 3.5,
    "profit_loss_ratio": 2.1,
    "max_drawdown": 0.06,
    "max_drawdown_duration_days": 20,
    "walk_forward_ratio": 0.88,
    "turnover_ratio": 12.0,
    "double_cost_profitable": True,
    "win_rate_pct": 60.0,
    "total_trades_count": 300,
}

COMPLETE_ATTACKS = {
    "label_shuffle_pass": True,
    "prefix_invariance_pass": True,
    "noise_features_pass": True,
    "calendar_features_pass": True,
    "ledger_reconciled": True,
    "tail_risk_pass": True,
    "leverage_safe": True,
    "execution_feasible": True,
}


class TestStrategyEvaluatorAgent(unittest.TestCase):

    def test_high_performing_strategy_is_approved(self):
        """Verify that an excellent strategy receives S grade and execution confirmation."""
        decision = StrategyEvaluatorAgent.evaluate_strategy(
            COMPLETE_METRICS, COMPLETE_ATTACKS, "AlphaElite_15m"
        )
        self.assertGreaterEqual(decision.total_score, 85.0)
        self.assertEqual(decision.grade, "S")
        self.assertEqual(decision.status, "APPROVED")
        self.assertTrue(decision.execution_confirmed)
        self.assertEqual(len(decision.hard_fail_reasons), 0)

    def test_missing_trust_evidence_is_rejected(self):
        decision = StrategyEvaluatorAgent.evaluate_strategy({}, {})
        self.assertEqual(decision.status, "REJECTED")
        self.assertEqual(decision.total_score, 0.0)
        self.assertTrue(any("缺少" in reason for reason in decision.hard_fail_reasons))

    def test_non_finite_or_negative_pnl_is_rejected(self):
        for pnl in [float("nan"), float("inf"), -1.0]:
            decision = StrategyEvaluatorAgent.evaluate_strategy(
                {**COMPLETE_METRICS, "total_net_pnl": pnl},
                COMPLETE_ATTACKS,
            )
            self.assertEqual(decision.status, "REJECTED")
            self.assertEqual(decision.total_score, 0.0)

    def test_hard_fail_triggers_rejection_and_zero_score(self):
        """Verify that failing the label shuffle attack immediately triggers hard rejection."""
        metrics = {
            "mean_rank_ic": 0.08,
            "sharpe_ratio": 3.5,
            "max_drawdown": 0.04,
        }
        attack_results = {
            "label_shuffle_pass": False,  # Future data leakage!
            "prefix_invariance_pass": True,
        }
        decision = StrategyEvaluatorAgent.evaluate_strategy(metrics, attack_results, "LeakedStrategy")
        self.assertEqual(decision.total_score, 0.0)
        self.assertEqual(decision.grade, "C")
        self.assertEqual(decision.status, "REJECTED")
        self.assertFalse(decision.execution_confirmed)
        self.assertTrue(any("标签打乱" in reason for reason in decision.hard_fail_reasons))

    def test_marginal_strategy_gets_optimize_or_incubation(self):
        """Verify that a mediocre strategy is not approved for live trading."""
        metrics = {
            "mean_rank_ic": 0.015,
            "rank_icir": 0.8,
            "sharpe_ratio": 1.1,
            "sortino_ratio": 1.4,
            "calmar_ratio": 1.0,
            "max_drawdown": 0.22,
            "max_drawdown_duration_days": 75,
            "turnover_ratio": 45.0,
            "double_cost_profitable": False,
        }
        decision = StrategyEvaluatorAgent.evaluate_strategy(metrics, {}, "MarginalStrategy")
        self.assertLess(decision.total_score, 70.0)
        self.assertIn(decision.status, {"OPTIMIZE", "REJECTED"})
        self.assertFalse(decision.execution_confirmed)
        self.assertGreater(len(decision.recommendations), 0)

    def test_scorecard_render(self):
        """Verify scorecard text formatting and mandatory 6 core metrics."""
        metrics = {
            "sharpe_ratio": 1.6,
            "max_drawdown": 0.12,
            "trading_period": "2026-05-11 ~ 2026-07-28",
            "asset_type": "A股股票 (全市场多因子截面选股)",
            "win_rate_pct": 64.7,
            "profit_loss_ratio": 2.2,
            "total_trades_count": 112,
        }
        decision = StrategyEvaluatorAgent.evaluate_strategy(metrics, {}, "TestStrat")
        card = StrategyEvaluatorAgent.render_evaluation_card(decision)
        self.assertIn("QUANT STRATEGY EVALUATION SCORECARD", card)
        self.assertIn("TestStrat", card)
        self.assertIn("综合总分", card)
        # Mandatory 6 elements
        self.assertIn("交易时间区间", card)
        self.assertIn("交易资产种类", card)
        self.assertIn("策略综合胜率", card)
        self.assertIn("策略盈亏比率", card)
        self.assertIn("历史最大回撤", card)
        self.assertIn("累计交易次数", card)


if __name__ == "__main__":
    unittest.main()
