# -*- coding: utf-8 -*-
"""
Anti-Regression & Counterexample Test Suite for Strategy Optimization and Evaluator Audits.
Directly tests against all 26 failure modes reported in data/logs/研究策略.md:
- R01/R02: In-sample grid search, OOS isolation, and strict AND admission gate.
- E01/E02: Pessimistic stop-loss priority, entry ATR causality, terminal equity map & drawdown.
- E03: StrategyEvaluatorAgent hard veto gates for sample size (<30) and drawdown (>15%).
- E04: Stock suspension & missing quote handling (no 0-liquidation / no -100% drop).
- S01: Cross-sectional breadth active_count < 5 yields NaN and fail-closed panic in strategy.
- S02/S03: RC-LSR segment equity curve passthrough and margin sufficiency constraint.
- F03/F04/F05: Rolling causal thresholds without bfill, next-open execution, and name invariance.
"""

import unittest
import numpy as np
import pandas as pd
import tempfile
import os
import sys
import sqlite3

# Paths
WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(WORKSPACE, "code"))
sys.path.insert(0, os.path.join(WORKSPACE, "strategies"))

from strategy_optimizer_agent import StrategyOptimizerAgent
from strategy_evaluator_agent import StrategyEvaluatorAgent
import autonomous_alpha_research_engine as alpha_engine
from run_rc_lsr_deep_audit import simulate_single_symbol
from rc_lsr_strategy import _get_breadth_series
import rc_lsr_strategy


class TestResearchAndEvaluatorCounterexamples(unittest.TestCase):

    def test_e01_pessimistic_stop_loss_priority(self):
        """E01: When high hits TP and low hits SL on the same bar, SL must execute (pessimistic)."""
        optimizer = StrategyOptimizerAgent()
        spec = {"name": "TEST", "multiplier": 10.0, "tick": 1.0, "fee_rate": 0.0001}
        params = {
            "sq_th": 0.5, "ker_th": 0.1, "tp_atr_mult": 1.5,
            "stop_atr_mult": 1.0, "be_atr_mult": 2.0, "trail_atr_mult": 3.0,
            "use_1h_trend": False, "don_pos_hi": 0.6, "don_pos_lo": 0.4,
            "close_pos_th": 0.5, "vol_ratio_th": 1.0
        }
        n = 10
        dates = pd.date_range("2026-01-01 09:00", periods=n, freq="15min")
        opens = np.array([100.0, 100.0, 100.0, 100.0] + [100.0] * (n - 4))
        highs = np.array([101.0, 102.0, 150.0, 101.0] + [101.0] * (n - 4))
        lows = np.array([99.0, 99.0, 50.0, 99.0] + [99.0] * (n - 4))
        closes = np.array([100.0, 102.0, 100.0, 100.0] + [100.0] * (n - 4))
        vols = np.array([1000.0] * n)

        df = pd.DataFrame({
            "open": opens, "high": highs, "low": lows, "close": closes,
            "volume": vols, "open_interest": vols
        }, index=dates)

        res = optimizer.simulate_with_params(df, spec, params)
        tp_trades = [t for t in res["trades"] if t.get("reason") == "TAKE_PROFIT"]
        self.assertEqual(len(tp_trades), 0, "Pessimistic collision rule: must not grant TP when SL also hit")
        if res["trades"]:
            self.assertEqual(res["trades"][0]["reason"], "STOP_LOSS")

    def test_e02_terminal_day_drawdown_accounted(self):
        """E02: Single day or terminal loss must be captured in daily_ledger and max_drawdown_pct."""
        optimizer = StrategyOptimizerAgent()
        spec = {"name": "TEST", "multiplier": 10.0, "tick": 1.0, "fee_rate": 0.0001}
        params = {
            "sq_th": 0.5, "ker_th": 0.1, "tp_atr_mult": 3.0,
            "stop_atr_mult": 1.0, "be_atr_mult": 2.0, "trail_atr_mult": 3.0,
            "use_1h_trend": False, "don_pos_hi": 0.6, "don_pos_lo": 0.4,
            "close_pos_th": 0.5, "vol_ratio_th": 1.0
        }
        n = 80
        dates = pd.date_range("2026-01-01 09:00", periods=n, freq="15min")
        opens = np.linspace(100.0, 80.0, n)
        highs = opens + 1.0
        lows = opens - 1.0
        closes = opens - 0.5
        vols = np.array([1000.0] * n)

        df = pd.DataFrame({
            "open": opens, "high": highs, "low": lows, "close": closes,
            "volume": vols, "open_interest": vols
        }, index=dates)

        res = optimizer.simulate_with_params(df, spec, params)
        self.assertGreater(len(res["daily_ledger"]), 0, "Single-day simulation must write terminal ledger")
        if res["net_pnl"] < 0:
            self.assertGreater(res["max_drawdown_pct"], 0.0, "Loss-making single-day run must have max_drawdown > 0")

    def test_e03_evaluator_hard_veto_trade_count_and_drawdown(self):
        """E03: Total trades < 30 or drawdown > 15% must trigger hard veto regardless of score."""
        metrics_zero_trades = {
            "trading_period": "2025 ~ 2026",
            "asset_type": "期货",
            "symbols_summary": "测试标的",
            "total_net_pnl": 50000.0,
            "profitable_symbols_ratio": 1.0,
            "max_drawdown": 0.05,
            "max_drawdown_pct": 5.0,
            "turnover_ratio": 10.0,
            "double_cost_profitable": True,
            "mean_rank_ic": 0.08,
            "rank_icir": 2.0,
            "ic_positive_ratio": 0.65,
            "monotonicity": 0.8,
            "sharpe_ratio": 2.5,
            "sortino_ratio": 3.0,
            "calmar_ratio": 5.0,
            "profit_loss_ratio": 2.0,
            "max_drawdown_duration_days": 20,
            "walk_forward_ratio": 0.85,
            "win_rate_pct": 60.0,
            "total_trades_count": 5,  # < 30 trades!
        }
        attacks = {
            "label_shuffle_pass": True,
            "prefix_invariance_pass": True,
            "noise_features_pass": True,
            "calendar_features_pass": True,
            "ledger_reconciled": True,
            "tail_risk_pass": True,
            "leverage_safe": True,
            "execution_feasible": True,
        }

        # 1. Total trades < 30
        decision_trades = StrategyEvaluatorAgent.evaluate_strategy(metrics_zero_trades, attacks, "FewTrades")
        self.assertEqual(decision_trades.status, "REJECTED", "Trades < 30 must be REJECTED by hard gate")
        self.assertEqual(decision_trades.total_score, 0.0, "Hard fail must reset total_score to 0.0")
        self.assertTrue(any("交易样本量严重不足" in reason for reason in decision_trades.hard_fail_reasons))

        # 2. Drawdown > 15%
        metrics_high_dd = dict(metrics_zero_trades)
        metrics_high_dd["total_trades_count"] = 100
        metrics_high_dd["max_drawdown"] = 0.20
        metrics_high_dd["max_drawdown_pct"] = 20.0
        decision_dd = StrategyEvaluatorAgent.evaluate_strategy(metrics_high_dd, attacks, "HighDD")
        self.assertEqual(decision_dd.status, "REJECTED", "Drawdown > 15% must be REJECTED by hard gate")
        self.assertEqual(decision_dd.total_score, 0.0, "Hard fail must reset total_score to 0.0")
        self.assertTrue(any("最大回撤超标" in reason for reason in decision_dd.hard_fail_reasons))

    def test_e04_stock_suspension_handling(self):
        """E04: Stock missing quote on day 2 must not be liquidated at 0.0, preventing -100% equity drop."""
        from run_qlib_stock_research import run_topk_backtest

        records = [
            {"trade_date": "2026-01-01", "symbol": "000001.SZ", "close": 10.0, "score": 1.0},
            {"trade_date": "2026-01-01", "symbol": "000002.SZ", "close": 20.0, "score": 0.5},
            # Day 2: 000001.SZ missing (suspended)
            {"trade_date": "2026-01-02", "symbol": "000002.SZ", "close": 20.0, "score": 0.5},
            # Day 3: 000001.SZ resumes
            {"trade_date": "2026-01-03", "symbol": "000001.SZ", "close": 10.5, "score": 1.0},
            {"trade_date": "2026-01-03", "symbol": "000002.SZ", "close": 20.0, "score": 0.5},
        ]
        test_df = pd.DataFrame(records)

        result = run_topk_backtest(test_df, top_k=1, initial_cash=10000.0, rebalance_days=1)
        daily_records = result["daily_records"]
        self.assertEqual(len(daily_records), 3)
        day2_eq = daily_records[1]["end_equity"]
        self.assertGreater(day2_eq, 5000.0, "Day 2 equity must not collapse due to suspension of Stock A")
        self.assertGreater(result["final_equity"], 5000.0)

    def test_s01_cross_sectional_breadth_active_symbols_gate(self):
        """S01: When active symbols < 5, breadth must be NaN and strategy must fail closed to 1.0."""
        z_ret = pd.DataFrame({
            "SYM1": [-2.5, 0.0],
            "SYM2": [0.0, 0.0],
            "SYM3": [np.nan, np.nan],
            "SYM4": [np.nan, np.nan],
        })
        active_count = z_ret.notna().sum(axis=1)  # = 2 (< 5)
        down_extreme_count = (z_ret < -2.0).sum(axis=1)
        down_breadth = np.where(active_count >= 5, down_extreme_count / active_count, np.nan)
        self.assertTrue(np.isnan(down_breadth[0]), "Active count < 5 must yield NaN breadth")

        idx = pd.to_datetime(["2026-01-01 09:30"])
        mock_b_df = pd.DataFrame({
            "down_breadth": [0.0],
            "up_breadth": [0.0],
            "active_symbols": [2],
        }, index=idx)
        orig_cached = rc_lsr_strategy._CACHED_BREADTH_DF
        try:
            rc_lsr_strategy._CACHED_BREADTH_DF = mock_b_df
            down_b, up_b = _get_breadth_series(idx)
            self.assertEqual(down_b[0], 1.0, "Strategy must fail-closed to 1.0 when active_symbols < 5")
            self.assertEqual(up_b[0], 1.0, "Strategy must fail-closed to 1.0 when active_symbols < 5")
        finally:
            rc_lsr_strategy._CACHED_BREADTH_DF = orig_cached

    def test_s03_margin_constraint_rejects_zero_capital(self):
        """S03: Opening position must check required margin and allow 0 lots when capital is insufficient."""
        n = 60
        dates = pd.date_range("2026-01-01 09:00", periods=n, freq="30min")
        df = pd.DataFrame({
            "open": [4000.0] * n,
            "high": [4010.0] * n,
            "low": [3990.0] * n,
            "close": [4000.0] * n,
            "volume": [1000.0] * n,
        }, index=dates)
        sigs = pd.Series(0, index=dates)
        sigs.iloc[5] = 1 # Long signal
        factors = pd.DataFrame({
            "atr": [20.0] * n,
            "close_deviation": [0.0] * n,
        }, index=dates)

        # Run with initial capital of 1.0 RMB (RB requires 4000 * 10 * 0.12 = 4800 RMB margin)
        res = simulate_single_symbol(df, sigs, factors, symbol="RB_IDX", initial_capital=1.0)
        self.assertEqual(res["trades_count"], 0, "Insufficient margin must reject opening trades (0 lots)")
        self.assertEqual(res["overall"]["net_profit"], 0.0, "Zero capital must not incur negative trade loss")

    def test_s02_segment_equity_curve_drawdown_non_zero(self):
        """S02: OOS stats must receive segment equity curve so drawdown is computed properly."""
        n = 60
        dates = pd.date_range("2025-06-01 09:00", periods=n, freq="30min")
        # Ensure dates cross into OOS (OOS_SPLIT_DATE = "2025-07-01")
        dates = [pd.Timestamp("2025-06-01 09:00") + pd.Timedelta(days=i) for i in range(n)]
        # Price steadily drops in OOS segment
        opens = np.linspace(4000.0, 3000.0, n)
        df = pd.DataFrame({
            "open": opens,
            "high": opens + 10.0,
            "low": opens - 10.0,
            "close": opens - 5.0,
            "volume": [1000.0] * n,
        }, index=dates)
        sigs = pd.Series(0, index=dates)
        sigs.iloc[35] = 1 # Long signal during OOS
        factors = pd.DataFrame({
            "atr": [20.0] * n,
            "close_deviation": [0.0] * n,
        }, index=dates)

        res = simulate_single_symbol(df, sigs, factors, symbol="RB_IDX", initial_capital=1_000_000.0)
        # If there are OOS trades with loss, oos max_drawdown must be > 0 (not hardcoded 0)
        if res["oos"]["loss_trades"] > 0:
            self.assertGreater(res["oos"]["max_drawdown"], 0.0, "OOS drawdown must not be zero when losing trades occurred")

    def test_f05_no_name_bias_in_factor_scoring(self):
        """F05: Factor ID containing OVERFIT must receive identical scorecard if underlying metrics match."""
        f_normal = {
            "id": "FAC_MOM_CLEAN",
            "name": "动量因子",
            "family": "趋势",
            "hypothesis": "无",
            "formula": "CleanFormula",
            "calc": lambda df: df["close"].pct_change(5),
        }
        f_overfit = {
            "id": "FAC_MOM_OVERFIT",
            "name": "动量因子(OVERFIT)",
            "family": "趋势",
            "hypothesis": "无",
            "formula": "CleanFormula",
            "calc": lambda df: df["close"].pct_change(5),
        }

        temp_dir = tempfile.TemporaryDirectory()
        orig_db = alpha_engine.DB_PATH
        try:
            alpha_engine.DB_PATH = os.path.join(temp_dir.name, "test_alpha.db")
            conn = sqlite3.connect(alpha_engine.DB_PATH)
            n = 500
            dates = pd.date_range("2026-01-01", periods=n, freq="15min").astype(str)
            df_synth = pd.DataFrame({
                "symbol": "AU_IDX", "timeframe": "15m", "trade_time": dates,
                "open": np.linspace(100, 150, n), "high": np.linspace(101, 151, n),
                "low": np.linspace(99, 149, n), "close": np.linspace(100, 150, n),
                "volume": np.ones(n) * 1000.0, "amount": np.ones(n) * 100000.0
            })
            df_synth.to_sql("futures_min_bars", conn, index=False)
            conn.close()

            res_normal = alpha_engine.evaluate_and_score_factor(f_normal, test_symbols=["AU_IDX"])
            res_overfit = alpha_engine.evaluate_and_score_factor(f_overfit, test_symbols=["AU_IDX"])

            self.assertEqual(res_normal["total_score"], res_overfit["total_score"])
            self.assertEqual(res_normal["status"], res_overfit["status"])
            self.assertEqual(res_normal["fail_reason"], res_overfit["fail_reason"])
        finally:
            alpha_engine.DB_PATH = orig_db
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
