"""
Unit tests for StrategyEvaluatorAgent and 100-Point Quantitative Evaluation System.
"""

from pathlib import Path
import pytest

from strategy_evaluator_agent import StrategyEvaluatorAgent, StrategyEvaluationDecision, audit_and_confirm


def test_high_performing_strategy_is_approved():
    """Verify that an excellent strategy receives S grade and execution confirmation."""
    metrics = {
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
    }
    attack_results = {
        "label_shuffle_pass": True,
        "prefix_invariance_pass": True,
        "noise_features_pass": True,
        "calendar_features_pass": True,
        "ledger_reconciled": True,
    }

    decision = StrategyEvaluatorAgent.evaluate_strategy(metrics, attack_results, "AlphaElite_15m")
    assert decision.total_score >= 85.0
    assert decision.grade == "S"
    assert decision.status == "APPROVED"
    assert decision.execution_confirmed is True
    assert len(decision.hard_fail_reasons) == 0


def test_hard_fail_triggers_rejection_and_zero_score():
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
    assert decision.total_score == 0.0
    assert decision.grade == "C"
    assert decision.status == "REJECTED"
    assert decision.execution_confirmed is False
    assert any("标签打乱" in reason for reason in decision.hard_fail_reasons)


def test_marginal_strategy_gets_optimize_or_incubation():
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
    assert decision.total_score < 70.0
    assert decision.status in {"OPTIMIZE", "REJECTED"}
    assert decision.execution_confirmed is False
    assert len(decision.recommendations) > 0


def test_scorecard_render():
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
    assert "QUANT STRATEGY EVALUATION SCORECARD" in card
    assert "TestStrat" in card
    assert "综合总分" in card
    # Mandatory 6 elements
    assert "交易时间区间" in card
    assert "交易资产种类" in card
    assert "策略综合胜率" in card
    assert "策略盈亏比率" in card
    assert "历史最大回撤" in card
    assert "累计交易次数" in card
