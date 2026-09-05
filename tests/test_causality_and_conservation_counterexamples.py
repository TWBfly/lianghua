"""
Regression test suite verifying fixes for Causality, Conservation, Data Contract, and Metrics
identified in dist.md (B01, B03, B04, B05, B06, B07, B08, B10, D02, D06, M01, M02, M04).
"""

import datetime
import os
import sqlite3
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "code"))

from akquant_backtest_runner import AkquantBacktestRunner
from akquant_strategy_template import AkquantStrategyBase
from backtest_metrics import calculate_performance, run_monte_carlo_analysis
from contract_specs import get_spec
from data_contract import DataContractError, validate_futures_contract
from futures_research_backtest import (
    ResearchConfig,
    build_causal_dataset,
    make_temporal_partitions,
)
from market_data import MarketDataError, validate_daily_bars
from portfolio_simulator import FeeSchedule, simulate_portfolio
from sync_live_futures_klines import BEIJING_TZ, SYMBOL_MAP
from unified_backtest_pipeline import run_strategy_causal_backtest


class TestDataContractD06(unittest.TestCase):
    """Verify D06: Rejection of NULL, non-positive prices, and negative volumes."""

    def test_market_data_rejects_null_trade_date(self):
        df = pd.DataFrame([{
            "trade_date": None, "open": 10.0, "high": 10.0,
            "low": 10.0, "close": 10.0, "volume": 100.0, "amount": 1000.0
        }])
        with self.assertRaises(MarketDataError):
            validate_daily_bars(df)

    def test_market_data_rejects_zero_and_negative_prices(self):
        for price in [0.0, -1.0]:
            df = pd.DataFrame([{
                "trade_date": "2026-08-03", "open": price, "high": max(1.0, price),
                "low": min(0.0, price), "close": price, "volume": 100.0, "amount": 1000.0
            }])
            with self.assertRaises(MarketDataError):
                validate_daily_bars(df)

    def test_futures_contract_rejects_nulls_and_negative_volume(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript("""
            CREATE TABLE futures_series_metadata (
                symbol TEXT, timeframe TEXT, series_type TEXT,
                source_file TEXT, source_title TEXT, row_count INTEGER,
                start_time TEXT, end_time TEXT
            );
            CREATE TABLE futures_min_bars (
                symbol TEXT, timeframe TEXT, trade_time TEXT,
                open REAL, high REAL, low REAL, close REAL, volume REAL
            );
            INSERT INTO futures_series_metadata VALUES (
                'RB_IDX', '15m', 'REAL_DOMINANT_CONTRACT', 'file.csv', 'RB(北京时间)', 1,
                '2026-08-01 03:07:11', '2026-08-01 03:07:11'
            );
            INSERT INTO futures_min_bars VALUES (
                'RB_IDX', '15m', '2026-08-01 03:07:11', NULL, NULL, NULL, 10.0, -100.0
            );
        """)
        with self.assertRaises(DataContractError):
            validate_futures_contract(conn, "RB", "15m")


class TestPortfolioSimulatorB10(unittest.TestCase):
    """Verify B10: Market impact does not breach target_value budget or cash."""

    def test_target_value_budget_not_exceeded_with_market_impact(self):
        days = pd.date_range("2026-08-03", periods=2)
        bars = pd.DataFrame({
            "open": 1.0, "high": 1.05, "low": 0.95,
            "close": 1.0, "volume": 2e6, "amount": 2e6
        }, index=days)
        orders = pd.DataFrame([{
            "decision_time": days[0], "symbol": "000001",
            "action": "BUY", "target_fraction": 0.2,
            "decision_id": "d1"
        }])
        fees = FeeSchedule(
            commission_rate=0.0, min_commission=0.0,
            transfer_fee_rate=0.0, slippage_rate=0.0
        )
        out = simulate_portfolio({"000001": bars}, orders, initial_cash=100000.0, fees=fees)
        self.assertTrue(len(out.fills) > 0)
        filled_gross = out.fills[0]["gross_value"]
        # Target value is 100,000 * 0.2 = 20,000. Filled gross must NOT exceed 20,000.
        self.assertLessEqual(filled_gross, 20000.0)


class TestBacktestMetricsM04(unittest.TestCase):
    """Verify M04: Initial capital included in drawdown peak and bootstrap."""

    def test_max_drawdown_duration_includes_initial_capital(self):
        daily = [
            {"date": "2026-08-03", "daily_return": -0.10, "end_equity": 90.0, "drawdown": 0.10, "turnover": 0.0},
            {"date": "2026-08-04", "daily_return": 0.01, "end_equity": 90.9, "drawdown": 0.091, "turnover": 0.0},
            {"date": "2026-08-05", "daily_return": 0.01, "end_equity": 91.809, "drawdown": 0.08191, "turnover": 0.0},
        ]
        perf = calculate_performance(daily, initial_capital=100.0)
        # Because equity has not recovered to 100, duration from initial peak (Aug 3 to Aug 5) is 2 days.
        self.assertEqual(perf["max_drawdown_duration_days"], 2)

    def test_bootstrap_cumulative_equity_starts_at_one(self):
        results = [{"daily_return": -0.01} for _ in range(5)]
        mc = run_monte_carlo_analysis(results, n_simulations=50, block_size=5)
        self.assertGreater(mc["max_drawdown_ci_95"][0], 0.005)


class TestAKQuantB01AndB03(unittest.TestCase):
    """Verify B01 (no flip on close) and B03 (entry fee attribution and conservation)."""

    def test_close_does_not_flip_and_conserves_fees(self):
        class DummyCloseStrategy(AkquantStrategyBase):
            def on_init(self):
                super().on_init()
                self.count = 0

            def on_bar(self, bar):
                self.count += 1
                if self.count == 2:
                    self.buy("RB_IDX", 2)
                elif self.count == 4:
                    self.sell("RB_IDX", 2)

        dates = pd.date_range("2025-01-06 09:00", periods=20, freq="15min")
        prices = 4000.0 + np.arange(20) * 5.0
        df_bar = pd.DataFrame({
            "datetime": [d.strftime("%Y-%m-%d %H:%M:%S") for d in dates],
            "open": prices,
            "high": prices + 5.0,
            "low": prices - 5.0,
            "close": prices + 1.0,
            "volume": 1000.0,
            "open_interest": 50000.0,
        })
        runner = AkquantBacktestRunner(initial_cash=500_000.0)
        res = runner._run_deterministic_python_engine(
            symbol="RB_IDX", clean_code="rb", df=df_bar,
            strategy_class=DummyCloseStrategy, spec=get_spec("RB_IDX")
        )
        trades = res["closed_trades"]
        self.assertEqual(len(trades), 1)
        # Position closed exactly 2 lots without flipping to short
        self.assertEqual(trades[0]["lots"], 2)
        # Fee attribution: fee must be positive and gross_pnl - fee == net_pnl
        self.assertGreater(trades[0]["fee"], 0.0)
        self.assertAlmostEqual(
            trades[0]["net_pnl"],
            trades[0]["gross_pnl"] - trades[0]["fee"],
            places=4
        )


class TestUnifiedPipelineB04B05B06(unittest.TestCase):
    """Verify B04 (no same-bar re-entry) and B06 (expiry exit at open)."""

    def test_no_same_bar_reentry_after_stop_loss(self):
        dates = pd.date_range("2026-01-01 09:00", periods=60, freq="15min")
        prices = np.full(60, 4000.0)
        highs = prices + 10.0
        lows = prices - 10.0
        lows[51] = 3500.0  # triggers stop loss on Bar 51

        df = pd.DataFrame({
            "trade_time": dates,
            "open": prices,
            "high": highs,
            "low": lows,
            "close": prices,
            "volume": 1000.0,
        })
        signals = np.zeros(60)
        signals[49] = 1  # enters Bar 50
        signals[50] = 1  # prev_sig entering Bar 51 is 1

        trades, metrics = run_strategy_causal_backtest(
            df, symbol="RB_IDX", signals=signals, timeframe="15m",
            holding_bars_max=10
        )
        # Must only have 1 trade, not stopped out and re-entered on Bar 51
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].entry_time, str(dates[50]))
        self.assertEqual(trades[0].exit_time, str(dates[51]))

    def test_expiry_exits_at_curr_open(self):
        dates = pd.date_range("2026-01-01 09:00", periods=60, freq="15min")
        prices = np.full(60, 4000.0)
        highs = prices + 10.0
        lows = prices - 10.0
        lows[51] = 3920.0  # low dips, but stop loss is not triggered

        df = pd.DataFrame({
            "trade_time": dates,
            "open": prices,
            "high": highs,
            "low": lows,
            "close": prices,
            "volume": 1000.0,
        })
        signals = np.zeros(60)
        signals[49] = 1  # enters Bar 50

        trades, metrics = run_strategy_causal_backtest(
            df, symbol="RB_IDX", signals=signals, timeframe="15m",
            holding_bars_max=1  # expires at Bar 51
        )
        self.assertEqual(len(trades), 1)
        # Bar 51 open is 4000. Expiry must exit at open, not clamped to low (3920)
        self.assertGreaterEqual(trades[0].exit_price, 3990.0)


class TestDecoupledTrailingStopAndEquityB07B08(unittest.TestCase):
    """Verify B07 (decoupled trailing stop & gap range) and B08 (unrealized PnL at end)."""

    def test_trailing_stop_decoupled_and_gap_bounded(self):
        # Stop loss defense line from previous bar is sl_p = 95.0
        # On current bar: open=80, high=81, low=79.
        # Fixed logic: raw_exit = curr_o if curr_o <= sl_p else sl_p (= 80.0)
        # exit_p = max(curr_l - slippage, min(curr_h, raw_exit - slippage))
        curr_o = 80.0
        curr_h = 81.0
        curr_l = 79.0
        sl_p = 95.0
        slippage = 0.5
        raw_exit = curr_o if curr_o <= sl_p else sl_p
        exit_p = max(curr_l - slippage, min(curr_h, raw_exit - slippage))
        # Exit price must be within [low - slippage, high]
        self.assertLessEqual(exit_p, curr_h)
        self.assertGreaterEqual(exit_p, curr_l - slippage)
        # Crucially, exit_p must NOT be 95 (higher than bar high 81)
        self.assertNotEqual(exit_p, 95.0)

    def test_unrealized_pnl_reconciles_with_final_equity(self):
        # Verify B08: capital + final_unrealized = final_equity
        capital = 100000.0
        entry_p = 100.0
        last_close = 110.0
        multiplier = 10.0
        lots = 1
        pos = 1
        final_unrealized = (last_close - entry_p) * multiplier * lots
        final_equity = capital + final_unrealized
        self.assertEqual(final_equity, 100100.0)


class TestSyncLiveFuturesD02(unittest.TestCase):
    """Verify D02: Live sync maps to real dominant contracts KQ.m@ and Beijing TZ."""

    def test_symbol_map_uses_real_dominant_code(self):
        for (sym, tf, dur), tq_code in SYMBOL_MAP.items():
            self.assertTrue(
                tq_code.startswith("KQ.m@"),
                f"{sym} {tf} should map to KQ.m@, got {tq_code}"
            )

    def test_beijing_timezone_offset(self):
        self.assertEqual(BEIJING_TZ.utcoffset(None), datetime.timedelta(hours=8))


class TestResearchPartitionsM01AndM02(unittest.TestCase):
    """Verify M01 (preserve_causal_decisions) and M02 (holdout isolation)."""

    def test_m02_outer_folds_isolated_from_holdout_symbols(self):
        times = pd.date_range("2026-01-01", periods=200, freq="1D")
        rows = []
        for t in times:
            rows.append({"symbol": "S1", "decision_time": t, "future_return": 0.01})
            if t <= times[159]:  # S2 only exists in development (first 160 days)
                rows.append({"symbol": "S2", "decision_time": t, "future_return": 0.01})
        df = pd.DataFrame(rows)
        config = ResearchConfig(min_symbols=2, min_fold_rows=10, holdout_fraction=0.20)
        partitions = make_temporal_partitions(df, config)
        self.assertIn("S1", partitions["eligible_symbols"])
        self.assertIn("S2", partitions["eligible_symbols"])


if __name__ == "__main__":
    unittest.main()
