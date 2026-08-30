"""
Quant Strategy 100-Point Evaluator and Execution Confirmation Agent.
Evaluates machine learning and algorithmic strategies across 5 core dimensions:
1. Prediction Quality & Factor Alpha (25 pt)
2. Risk-Adjusted Returns (25 pt)
3. Drawdown & Downside Risk Control (20 pt)
4. Anti-Overfitting & Adversarial Robustness (20 pt)
5. Live Execution Feasibility & Friction Tolerance (10 pt)

Determines final grade (S/A/B/C) and execution confirmation status (APPROVED/INCUBATION/OPTIMIZE/REJECTED).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any


@dataclass
class StrategyEvaluationDecision:
    strategy_name: str
    total_score: float
    grade: str
    status: str
    dimension_scores: Dict[str, float]
    # Mandatory 6-Core Backtest Audit Metrics
    trading_period: str = "N/A"
    asset_type: str = "A股/期货"
    symbols_summary: str = "全市场标的"
    win_rate_pct: float = 0.0
    profit_loss_ratio: float = 1.0
    max_drawdown_pct: float = 0.0
    total_trades_count: int = 0
    # Additional Audit Details
    hard_fail_reasons: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    execution_confirmed: bool = False


class StrategyEvaluatorAgent:
    """Agent responsible for auditing and scoring quantitative strategies."""

    APPROVAL_THRESHOLD = 85.0
    INCUBATION_THRESHOLD = 70.0
    PASS_THRESHOLD = 60.0

    @classmethod
    def evaluate_strategy(
        cls,
        metrics: Dict[str, Any],
        attack_results: Optional[Dict[str, Any]] = None,
        strategy_name: str = "Strategy",
    ) -> StrategyEvaluationDecision:
        attack_results = attack_results or {}
        hard_fails = []
        recommendations = []

        required_metrics = {
            "total_net_pnl", "profitable_symbols_ratio", "max_drawdown",
            "turnover_ratio", "double_cost_profitable", "mean_rank_ic",
            "rank_icir", "ic_positive_ratio", "monotonicity",
            "sharpe_ratio", "sortino_ratio", "calmar_ratio",
            "profit_loss_ratio", "max_drawdown_duration_days",
            "walk_forward_ratio", "win_rate_pct", "total_trades_count",
        }
        required_attacks = {
            "label_shuffle_pass", "prefix_invariance_pass",
            "noise_features_pass", "calendar_features_pass",
            "ledger_reconciled", "tail_risk_pass", "leverage_safe",
            "execution_feasible",
        }
        missing_metrics = sorted(required_metrics - metrics.keys())
        missing_attacks = sorted(required_attacks - attack_results.keys())
        if missing_metrics:
            hard_fails.append(
                f"缺少必需指标: {', '.join(missing_metrics)}"
            )
        if missing_attacks:
            hard_fails.append(
                f"缺少必需审计证据: {', '.join(missing_attacks)}"
            )

        numeric_metrics = required_metrics - {"double_cost_profitable"}
        invalid_metrics = []
        for key in sorted(numeric_metrics & metrics.keys()):
            try:
                value = float(metrics[key])
            except (TypeError, ValueError):
                invalid_metrics.append(key)
                continue
            if not math.isfinite(value):
                invalid_metrics.append(key)
        if invalid_metrics:
            hard_fails.append(
                f"指标必须为有限数值: {', '.join(invalid_metrics)}"
            )
        if (
            "double_cost_profitable" in metrics
            and metrics["double_cost_profitable"] is not True
        ):
            hard_fails.append("双倍成本压力测试未通过")

        def metric_float(key, default=0.0):
            try:
                value = float(metrics.get(key, default))
            except (TypeError, ValueError):
                return float(default)
            return value if math.isfinite(value) else float(default)

        # Extract Mandatory 6-Core Metrics
        trading_period = str(metrics.get("trading_period", metrics.get("date_range", "N/A")))
        asset_type = str(metrics.get("asset_type", "UNKNOWN"))
        symbols_summary = str(metrics.get("symbols_summary", "UNKNOWN"))
        win_rate_pct = metric_float("win_rate_pct")
        profit_loss_ratio = metric_float("profit_loss_ratio")
        raw_dd = metric_float("max_drawdown", metric_float("max_drawdown_pct"))
        max_drawdown_pct = abs(raw_dd) * 100.0 if abs(raw_dd) <= 1.0 else abs(raw_dd)
        total_trades_count = int(metric_float("total_trades_count"))

        # Check Hard Fail Gates
        if attack_results.get("label_shuffle_pass") is not True:
            hard_fails.append("标签打乱测试未通过 (Label Shuffle Leakage) - 判定存在未来数据泄漏")
        if attack_results.get("prefix_invariance_pass") is not True:
            hard_fails.append("前缀截断不变量测试未通过 (Prefix Invariance Failure) - 判定存在全局标准化未来函数")
        if attack_results.get("ledger_reconciled") is not True:
            hard_fails.append("账本资金流水未闭环对账 (Ledger Reconciliation Failure)")
        for key, label in (
            ("noise_features_pass", "噪声特征攻击"),
            ("calendar_features_pass", "日历特征攻击"),
            ("tail_risk_pass", "尾部风险压力测试"),
            ("leverage_safe", "杠杆安全检查"),
            ("execution_feasible", "实盘执行可行性检查"),
        ):
            if attack_results.get(key) is not True:
                hard_fails.append(f"{label}未通过")

        profitable_ratio = metric_float("profitable_symbols_ratio")
        total_pnl = metric_float("total_net_pnl")
        if profitable_ratio < 0.80:
            hard_fails.append(f"全市场品种盈利覆盖率过低 ({profitable_ratio*100:.1f}% < 80.0%) - 多数标的处于亏损磨损状态，严禁准入")
        if total_pnl <= 0:
            hard_fails.append("全市场累计净利润为负 (Total PnL <= 0) - 无法覆盖摩擦成本")

        # ----------------------------------------------------------------------
        # 1. Prediction Quality & Alpha (25 pt)
        # ----------------------------------------------------------------------
        rank_ic = metric_float("mean_rank_ic")
        icir = metric_float("rank_icir")
        ic_pos_ratio = metric_float("ic_positive_ratio")
        monotonicity = metric_float("monotonicity")

        s_ic = min(8.0, max(0.0, rank_ic / 0.035 * 8.0))
        s_icir = min(8.0, max(0.0, icir / 1.5 * 8.0))
        s_win = 5.0 if ic_pos_ratio >= 0.58 else (3.0 if ic_pos_ratio >= 0.52 else 1.0)
        s_mono = min(4.0, max(0.0, monotonicity * 4.0)) if monotonicity > 0 else 0.0
        score_prediction = round(s_ic + s_icir + s_win + s_mono, 1)

        if score_prediction < 12.0:
            recommendations.append("因子预测能力偏弱 (Rank IC / ICIR 偏低)，建议引入新的微观量价或另类特征")

        # ----------------------------------------------------------------------
        # 2. Risk-Adjusted Returns (25 pt)
        # ----------------------------------------------------------------------
        sharpe = metric_float("sharpe_ratio")
        sortino = metric_float("sortino_ratio")
        calmar = metric_float("calmar_ratio")
        profit_loss_ratio = metric_float("profit_loss_ratio")

        s_sharpe = min(10.0, max(0.0, sharpe / 2.5 * 10.0)) if sharpe > 0 else 0.0
        s_sortino = min(5.0, max(0.0, sortino / 3.5 * 5.0)) if sortino > 0 else 0.0
        s_calmar = min(6.0, max(0.0, calmar / 3.0 * 6.0)) if calmar > 0 else 0.0
        s_pl = 4.0 if profit_loss_ratio >= 1.8 else (2.5 if profit_loss_ratio >= 1.2 else 1.0)
        score_returns = round(s_sharpe + s_sortino + s_calmar + s_pl, 1)

        if sharpe < 1.5:
            recommendations.append("年化夏普比率低于 1.5，风险调整后收益不足以覆盖实盘不确定性")

        # ----------------------------------------------------------------------
        # 3. Drawdown & Downside Risk Control (20 pt)
        # ----------------------------------------------------------------------
        max_dd = abs(metric_float("max_drawdown"))
        if max_dd > 1.0:
            max_dd /= 100.0  # normalize percentage
        dd_days = int(metric_float("max_drawdown_duration_days"))

        s_dd = 8.0 if max_dd <= 0.08 else (5.0 if max_dd <= 0.15 else (2.0 if max_dd <= 0.25 else 0.0))
        s_dur = 5.0 if dd_days <= 30 else (3.0 if dd_days <= 60 else (1.0 if dd_days <= 90 else 0.0))
        s_tail = 4.0 if attack_results.get("tail_risk_pass") is True else 0.0
        s_leverage = 3.0 if attack_results.get("leverage_safe") is True else 0.0
        score_drawdown = round(s_dd + s_dur + s_tail + s_leverage, 1)

        if max_dd > 0.15:
            recommendations.append(f"最大回撤达到 {max_dd*100:.1f}%，需收紧 ATR 动态止损与持仓上限")

        # ----------------------------------------------------------------------
        # 4. Anti-Overfitting & Adversarial Robustness (20 pt)
        # ----------------------------------------------------------------------
        if hard_fails:
            score_robustness = 0.0
        else:
            noise_pass = attack_results.get("noise_features_pass") is True
            calendar_pass = attack_results.get("calendar_features_pass") is True
            walk_forward_ratio = metric_float("walk_forward_ratio")

            s_wf = min(6.0, max(0.0, walk_forward_ratio * 6.0))
            s_noise = 4.0 if noise_pass else 1.0
            s_cal = 4.0 if calendar_pass else 1.0
            s_prefix = 6.0 if attack_results.get("prefix_invariance_pass") is True else 0.0
            score_robustness = round(s_wf + s_noise + s_cal + s_prefix, 1)

        # ----------------------------------------------------------------------
        # 5. Live Feasibility & Friction Tolerance (10 pt)
        # ----------------------------------------------------------------------
        turnover_ratio = metric_float("turnover_ratio", float("inf"))
        cost_profitable = metrics.get("double_cost_profitable") is True

        s_turnover = 4.0 if turnover_ratio <= 25.0 else (2.0 if turnover_ratio <= 50.0 else 0.0)
        s_cost = 4.0 if cost_profitable else 0.0
        s_exec = 2.0 if attack_results.get("execution_feasible") is True else 0.0
        score_feasibility = round(s_turnover + s_cost + s_exec, 1)

        if not cost_profitable or turnover_ratio > 35.0:
            recommendations.append("换手率过高或滑点加倍后无法盈利，建议延长持仓周期或引入调仓滤波阈值")

        # Calculate Total Score & Decision
        if hard_fails:
            total_score = 0.0
            grade = "C"
            status = "REJECTED"
            confirmed = False
        else:
            total_score = round(score_prediction + score_returns + score_drawdown + score_robustness + score_feasibility, 1)
            total_score = min(100.0, max(0.0, total_score))

            if total_score >= cls.APPROVAL_THRESHOLD:
                grade = "S"
                status = "APPROVED"
                confirmed = True
            elif total_score >= cls.INCUBATION_THRESHOLD:
                grade = "A"
                status = "INCUBATION"
                confirmed = False
            elif total_score >= cls.PASS_THRESHOLD:
                grade = "B"
                status = "OPTIMIZE"
                confirmed = False
            else:
                grade = "C"
                status = "REJECTED"
                confirmed = False

        dim_scores = {
            "1. 预测质量与因子Alpha (25分)": score_prediction,
            "2. 风险调整后收益 (25分)": score_returns,
            "3. 回撤与尾部风控 (20分)": score_drawdown,
            "4. 抗过拟合与对抗鲁棒性 (20分)": score_robustness,
            "5. 实盘可行性与摩擦成本 (10分)": score_feasibility,
        }

        return StrategyEvaluationDecision(
            strategy_name=strategy_name,
            total_score=total_score,
            grade=grade,
            status=status,
            dimension_scores=dim_scores,
            trading_period=trading_period,
            asset_type=asset_type,
            symbols_summary=symbols_summary,
            win_rate_pct=win_rate_pct,
            profit_loss_ratio=profit_loss_ratio,
            max_drawdown_pct=max_drawdown_pct,
            total_trades_count=total_trades_count,
            hard_fail_reasons=hard_fails,
            recommendations=recommendations,
            execution_confirmed=confirmed,
        )

    @classmethod
    def render_evaluation_card(cls, decision: StrategyEvaluationDecision) -> str:
        """Render formatted terminal scorecard with mandatory 6-core backtest metrics."""
        status_map = {
            "APPROVED": "【准予执行 · 实盘候选】(APPROVED)",
            "INCUBATION": "【准予孵化 · 模拟跟踪】(INCUBATION)",
            "OPTIMIZE": "【建议优化 · 暂缓实盘】(OPTIMIZE)",
            "REJECTED": "【严格否决 · 禁止执行】(REJECTED)",
        }

        lines = [
            "=" * 70,
            f"       QUANT STRATEGY EVALUATION SCORECARD (100-POINT AGENT)",
            "=" * 70,
            f"  策略名称:   {decision.strategy_name}",
            f"  综合总分:   {decision.total_score:>5.1f} / 100.0 分",
            f"  评级等级:   {decision.grade} 级",
            f"  执行决策:   {status_map.get(decision.status, decision.status)}",
            "-" * 70,
            "  📋 回测报告六大核心要素 (MANDATORY BACKTEST CORE AUDIT):",
            f"    1. 交易时间区间:   {decision.trading_period}",
            f"    2. 交易资产种类:   {decision.asset_type} ({decision.symbols_summary})",
            f"    3. 策略综合胜率:   {decision.win_rate_pct:.2f} %",
            f"    4. 策略盈亏比率:   {decision.profit_loss_ratio:.2f}",
            f"    5. 历史最大回撤:   {decision.max_drawdown_pct:.2f} %",
            f"    6. 累计交易次数:   {decision.total_trades_count:,} 笔",
            "-" * 70,
            "  维度分项得分 (Dimension Scores):",
        ]

        for dim_name, score in decision.dimension_scores.items():
            lines.append(f"    ├─ {dim_name:<32}: {score:>4.1f} 分")

        if decision.hard_fail_reasons:
            lines.extend([
                "-" * 70,
                "  一票否决严重告警 (Hard Failures):",
            ])
            for reason in decision.hard_fail_reasons:
                lines.append(f"    ❌ {reason}")

        if decision.recommendations:
            lines.extend([
                "-" * 70,
                "  智能优化建议 (Recommendations):",
            ])
            for rec in decision.recommendations:
                lines.append(f"    💡 {rec}")

        lines.append("=" * 70)
        return "\n".join(lines)


def audit_and_confirm(
    metrics: Dict[str, Any],
    attack_results: Optional[Dict[str, Any]] = None,
    strategy_name: str = "Strategy",
) -> StrategyEvaluationDecision:
    """Convenience entrypoint for evaluating and printing decision card."""
    decision = StrategyEvaluatorAgent.evaluate_strategy(metrics, attack_results, strategy_name)
    card = StrategyEvaluatorAgent.render_evaluation_card(decision)
    print(card)
    return decision
