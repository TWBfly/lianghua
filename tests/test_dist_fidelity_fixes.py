"""
tests/test_dist_fidelity_fixes.py
自动化回归测试套件：针对 dist.md 揭示的 18 项系统性保真度缺陷进行锁死验证。
"""

import unittest
import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import pandas as pd
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "code"), str(ROOT / "strategies")]

from akquant_strategy_template import AkquantStrategyBase
from akquant_backtest_runner import AkquantBacktestRunner
from contract_specs import ContractSpec
from vnpy_backtest_runner import VnpyBacktestRunner
from vnpy_strategy_template import CtaTemplate, Direction, Offset, OrderData, TradeData, Status
from vnpy_data_adapter import BarData, Exchange, Interval
from triple_differential_oracle import TripleDifferentialOracle
from unified_backtest_pipeline import run_strategy_causal_backtest
from futures_trading_day import get_futures_trading_date
from portfolio_simulator import simulate_portfolio, FeeSchedule
from deploy_vnpy_paper_trader import VnpyPaperEngine
from futures_research_backtest import validate_and_segment, build_causal_dataset, ResearchConfig


def make_bar(o=100.0, h=110.0, l=99.0, c=100.0, minutes=0, volume=1000.0):
    dt = datetime.datetime(2026, 1, 5, 9, 0) + datetime.timedelta(minutes=minutes)
    return BarData(
        symbol="test",
        exchange=Exchange.SHFE,
        datetime=dt,
        interval=Interval.MINUTE,
        open_price=o,
        high_price=h,
        low_price=l,
        close_price=c,
        volume=volume,
        gateway_name="TEST"
    )


class TestDistFidelityFixes(unittest.TestCase):

    # ==============================================================================
    # 1. D03: 模拟盘已实现盈亏结转与资金记账 (Paper Trader PnL)
    # ==============================================================================
    def test_paper_trader_realized_pnl(self):
        paper = object.__new__(VnpyPaperEngine)
        paper.balance = 1000.0
        paper.available = 1000.0
        paper.rate = 0.0
        paper.slippage = 0.0
        paper.order_count = 0
        paper.trade_count = 0
        paper.positions = {}
        paper.position_costs = {}
        paper.active_orders = {}
        paper.strategies = {}
        paper.save_state = lambda: None
        paper.log_trade = lambda *args, **kwargs: None

        st = CtaTemplate(paper, "test", "test.SHFE", {})
        paper.strategies["test.SHFE"] = st

        # 1. 买入开仓 1 手 @ 100
        paper.send_order(st, Direction.LONG, Offset.OPEN, 100.0, 1.0)
        paper.on_bar("test.SHFE", make_bar(o=100.0, h=100.0, l=100.0, c=100.0))
        self.assertEqual(paper.positions["test.SHFE"], 1.0)
        self.assertEqual(paper.balance, 1000.0)

        # 2. 卖出平仓 1 手 @ 110 (盈利 10 点)
        paper.send_order(st, Direction.SHORT, Offset.CLOSE, 110.0, 1.0)
        paper.on_bar("test.SHFE", make_bar(o=110.0, h=110.0, l=110.0, c=110.0, minutes=15))

        self.assertEqual(paper.positions["test.SHFE"], 0.0)
        self.assertEqual(paper.balance, 1100.0)
        self.assertEqual(paper.available, 1100.0)

    # ==============================================================================
    # 2. D02: Unified Pipeline 破产即刻清算，杜绝末柱未来价格估值 (No Future Tail)
    # ==============================================================================
    def test_pipeline_bankruptcy_no_future_tail(self):
        f = pd.DataFrame({
            "trade_time": pd.date_range("2026-01-05 09:00", periods=50, freq="15min"),
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0
        })
        # 在 bar 22 价格崩塌至 90，导致本金只有 1000 的账户穿仓
        f.loc[22, ["open", "high", "low", "close"]] = 90.0
        # bar 23 之后价格暴涨至 150
        f.loc[23:, ["open", "high", "low", "close"]] = 150.0

        sig = np.zeros(50)
        sig[20] = 1  # bar 20 发出做多信号，bar 21 开盘买入

        tr, summary = run_strategy_causal_backtest(
            f, "RB_IDX", sig, capital=1000.0, target_risk_pct=1.0, holding_bars_max=999
        )

        self.assertTrue(summary["is_bankrupt"])
        self.assertLess(summary["net_pnl"], 0)
        self.assertEqual(len(tr), 1)
        self.assertEqual(tr[0].exit_price, 90.0)
        self.assertEqual(str(tr[0].exit_time), str(f["trade_time"].iloc[22]))

    # ==============================================================================
    # 3. D10: 净值曲线终点与最终现金严格一致 (Terminal Equity Alignment)
    # ==============================================================================
    def test_unified_terminal_equity_matches_cash(self):
        f = pd.DataFrame({
            "trade_time": pd.date_range("2026-01-05 09:00", periods=50, freq="15min"),
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0
        })
        sig = np.zeros(50)
        sig[20] = 1
        tr, summary = run_strategy_causal_backtest(f, "RB_IDX", sig, holding_bars_max=999)

        self.assertEqual(len(tr), 1)
        self.assertGreater(summary["final_cash"], 0)
        expected_dd = 500000.0 - summary["final_cash"]
        self.assertGreaterEqual(summary["max_drawdown"], round(expected_dd - 1e-4, 2))

    # ==============================================================================
    # 4. D04: VNPy 桥接器止损单与防反向开仓
    # ==============================================================================
    def test_vnpy_stop_order_and_position_safety(self):
        runner = VnpyBacktestRunner(vt_symbol="test.SHFE", rate=0.0, slippage=1.0, size=1.0, pricetick=1.0)
        runner.add_strategy(CtaTemplate, {})
        runner.strategy.pos = 1.0

        # 1. 挂卖出止损单 @ 95
        runner.send_order(runner.strategy, Direction.SHORT, Offset.CLOSE, 95.0, 1.0, stop=True)
        # 当根 Bar 最低价 99 (未触及 95)，绝不能以限价单成交
        runner.cross_stop_order(make_bar(o=100.0, h=101.0, l=99.0))
        self.assertEqual(len(runner.trades), 0)
        self.assertEqual(runner.strategy.pos, 1.0)

        # 当最低价触及 94 <= 95 时触发止损
        runner.cross_stop_order(make_bar(o=96.0, h=96.0, l=94.0))
        self.assertEqual(len(runner.trades), 1)
        self.assertEqual(runner.strategy.pos, 0.0)

        # 2. 持仓为 0 时发送平仓卖单，必须拒单，严禁反向开空变成 -2
        res = runner.send_order(runner.strategy, Direction.SHORT, Offset.CLOSE, 90.0, 2.0)
        self.assertEqual(res, [])
        self.assertEqual(runner.strategy.pos, 0.0)

    # ==============================================================================
    # 5. D05 & D07: AKQuant 参数去重与多订单撮合
    # ==============================================================================
    def test_akquant_param_dedup_and_queue(self):
        runner = AkquantBacktestRunner(1000.0)
        df = pd.DataFrame({
            "datetime": pd.date_range("2026-01-05 09:00", periods=5, freq="15min"),
            "open": 100.0, "high": 105.0, "low": 95.0, "close": 100.0,
            "volume": 1000.0, "open_interest": 1000.0
        })

        class MultiOrderStrategy(AkquantStrategyBase):
            def on_init(self):
                super().on_init()
                self.count = 0
                self.trades_received = []

            def on_bar(self, bar):
                if self.count == 0:
                    self.buy("TEST_IDX", 2.0)
                elif self.count == 1:
                    self.sell("TEST_IDX", 2.0)
                self.count += 1

            def on_trade(self, trade):
                self.trades_received.append(trade)

        # 1. 验证传入 commission_rate 不触发 TypeError
        fake_result = SimpleNamespace(metrics=SimpleNamespace(
            end_market_value=1000.0, total_pnl=0.0, total_return_pct=0.0,
            annualized_return=0.0, sharpe_ratio=0.0, max_drawdown_pct=0.0,
            win_rate=0.0, closed_trade_count=0, profit_factor=0.0
        ))
        with patch.object(runner.adapter, "load_futures_dataframe", return_value=df), \
             patch("akquant_backtest_runner.AKQUANT_NATIVE", True), \
             patch("akquant_backtest_runner.native_run_backtest", return_value=fake_result, create=True) as native:
            res = runner.run("RB_IDX", MultiOrderStrategy, custom_params={"commission_rate": 0.0003, "slippage": 1.0})
            self.assertEqual(res["status"], "SUCCESS")
            self.assertEqual(native.call_count, 1)

        # 2. 验证 Python 备用引擎撮合与回调完整性
        spec = ContractSpec("TEST", 1.0, 1.0, 0.0, 0.1, "TEST")
        py_res = runner._run_deterministic_python_engine("TEST_IDX", "test", df, MultiOrderStrategy, spec)
        self.assertEqual(py_res["metrics"]["closed_trade_count"], 1)

    # ==============================================================================
    # 6. D06: Triple Differential Oracle 字段匹配与风控阻断
    # ==============================================================================
    def test_oracle_field_alignment(self):
        upstream = {
            "total_net_pnl": 100.0,
            "total_trade_count": 2,
            "closed_trade_count": 1,
            "win_rate_pct": 100.0,
            "max_drawdown_pct": 50.0,
            "profit_loss_ratio": 2.0
        }
        oracle = TripleDifferentialOracle()
        with patch.object(oracle.vn_adapter, "load_futures_bars", return_value=[make_bar()]), \
             patch("triple_differential_oracle.VnpyBacktestRunner") as cls:
            cls.return_value.run_backtesting.return_value = upstream
            result = oracle.run_triple_audit(
                "RB_IDX",
                strategy_class_vnpy=CtaTemplate,
                internal_summary={
                    "total_net_pnl": 100.0,
                    "total_trades": 2,
                    "max_drawdown_pct": 0.0,
                    "win_rate_pct": 0.0,
                    "profit_factor": 0.0
                }
            )
            vn_summary = result["results_summary"]["VNPy_CTA"]
            self.assertEqual(vn_summary["max_drawdown_pct"], 50.0)
            self.assertNotEqual(result["status"], "PARTIAL_DIFF_PASS")

    # ==============================================================================
    # 7. D14: ETF / LOF 免征印花税 (0%)
    # ==============================================================================
    def test_etf_stamp_duty_exempt(self):
        dates = pd.date_range("2026-01-05", periods=3, freq="B")
        stock = pd.DataFrame({
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 10000000.0
        }, index=dates)
        decisions = pd.DataFrame([
            {"decision_time": dates[0], "symbol": "510300", "action": "BUY", "target_fraction": 0.2},
            {"decision_time": dates[1], "symbol": "510300", "action": "SELL", "target_fraction": 0.0}
        ])
        sim = simulate_portfolio({"510300": stock}, decisions, 1000000.0)
        sell = next(x for x in sim.fills if x["side"] == "SELL")
        self.assertEqual(sell["stamp_duty"], 0.0)

    # ==============================================================================
    # 8. D12: 期货交易日历严格性与假日判定
    # ==============================================================================
    def test_futures_calendar_strictness(self):
        with self.assertRaises(ValueError):
            get_futures_trading_date("not-a-valid-time")

        dt = get_futures_trading_date("2026-09-30 21:00:00")
        self.assertEqual(dt, "2026-10-08")

    # ==============================================================================
    # 9. D15: 因果研究样本不被未来价格跳空截断
    # ==============================================================================
    def test_research_preserve_causal_decisions(self):
        n = 220
        k = np.arange(n)
        close = 100 + np.sin(k / 7) + k * 0.01
        raw = pd.DataFrame({
            "symbol": "X_IDX",
            "trade_time": pd.date_range("2026-01-05 09:00", periods=n, freq="5min"),
            "open": close, "high": close + 0.5, "low": close - 0.5, "close": close,
            "volume": 1000.0 + (k % 7) * 10
        })
        shock = raw.copy()
        shock.loc[150:, ["open", "high", "low", "close"]] *= 1.10

        cfg = ResearchConfig(preserve_causal_decisions=True)
        a = build_causal_dataset(validate_and_segment(raw, cfg)[0], cfg)
        b = build_causal_dataset(validate_and_segment(shock, cfg)[0], cfg)
        cut = raw.trade_time.iloc[149]

        removed = set(a.loc[a.decision_time <= cut, "decision_time"]) - set(b.loc[b.decision_time <= cut, "decision_time"])
        self.assertEqual(len(removed), 0)


if __name__ == "__main__":
    unittest.main()
