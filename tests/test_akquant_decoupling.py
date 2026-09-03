"""
test_akquant_decoupling.py — 验证 AKQuant 与 Lianghua 系统的解耦集成

测试范围：
1. AKQuant 数据适配器 (AkquantDataAdapter) 转换与契约合规性；
2. AKQuant 策略模板 (AkquantStrategyBase) 交易动作与生命周期；
3. AKQuant 统一回测执行器 (AkquantBacktestRunner) 参数注入与指标输出；
4. 自动化更新脚本权限与目录完备性。
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

from akquant_data_adapter import AkquantDataAdapter, StandardBar
from akquant_strategy_template import AkquantStrategyBase, Bar, get_base_strategy_class
from akquant_backtest_runner import AkquantBacktestRunner
from contract_specs import get_spec


class SampleTestStrategy(AkquantStrategyBase):
    """用于测试的模拟双均线策略"""
    def __init__(self):
        super().__init__()
        self.bar_count = 0

    def on_bar(self, bar: Bar):
        self.bar_count += 1
        if self.bar_count == 1:
            self.buy(bar.symbol, 1)
        elif self.bar_count == 3:
            self.close_position(bar.symbol)


class TestAkquantDecoupling(unittest.TestCase):

    def setUp(self):
        # 构造合成无未来函数测试数据
        times = [datetime(2026, 1, 1, 9, 0) + timedelta(minutes=15 * i) for i in range(10)]
        self.mock_df = pd.DataFrame({
            "datetime": times,
            "open": [100.0, 101.0, 102.0, 101.5, 103.0, 104.0, 103.5, 105.0, 106.0, 105.5],
            "high": [101.5, 102.5, 103.0, 103.5, 104.5, 105.0, 105.5, 106.5, 107.0, 106.5],
            "low": [99.5, 100.5, 101.0, 101.0, 102.5, 103.0, 103.0, 104.5, 105.0, 104.5],
            "close": [101.0, 102.0, 101.5, 103.0, 104.0, 103.5, 105.0, 106.0, 105.5, 106.0],
            "volume": [1000.0] * 10,
            "open_interest": [500.0] * 10,
        })

    def test_01_adapter_dataframe_feed(self):
        adapter = AkquantDataAdapter()
        feed = adapter.convert_for_akquant_feed({"ag": self.mock_df})
        self.assertIn("ag", feed)
        df_out = feed["ag"]
        self.assertIn("date", df_out.columns)
        self.assertEqual(len(df_out), 10)
        self.assertTrue((df_out["high"] >= df_out["low"]).all())

    def test_02_strategy_template_lifecycle(self):
        strat = SampleTestStrategy()
        strat.on_init()
        self.assertTrue(strat.inited)

        strat.on_start()
        self.assertTrue(strat.trading)

        # 模拟 3 根 Bar 推送
        for i, row in self.mock_df.head(3).iterrows():
            bar = Bar(
                symbol="ag",
                datetime=row["datetime"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
            )
            strat.on_bar(bar)

        self.assertEqual(strat.bar_count, 3)
        self.assertEqual(strat.get_position("ag"), 0.0) # 已平仓
        self.assertEqual(len(strat.orders), 2) # 1 buy + 1 sell

    def test_03_contract_spec_integration(self):
        spec = get_spec("AG_IDX")
        self.assertEqual(spec.name, "沪银")
        self.assertEqual(spec.multiplier, 15.0)
        self.assertGreater(spec.fee_rate, 0)

    def test_04_backtest_runner(self):
        runner = AkquantBacktestRunner(initial_cash=500_000.0)
        self.assertEqual(runner.initial_cash, 500_000.0)

    def test_05_update_script_exists(self):
        script_path = PROJECT_ROOT / "scripts" / "update_akquant.sh"
        self.assertTrue(script_path.exists())

    def test_06_deterministic_matching_execution(self):
        runner = AkquantBacktestRunner(initial_cash=500_000.0)
        spec = get_spec("AG_IDX")
        res = runner._run_deterministic_python_engine(
            symbol="AG_IDX",
            clean_code="ag",
            df=self.mock_df,
            strategy_class=SampleTestStrategy,
            spec=spec
        )
        self.assertEqual(res["status"], "SUCCESS")
        m = res["metrics"]
        self.assertEqual(m["closed_trade_count"], 1)
        self.assertGreater(m["total_commission"], 0)
        self.assertGreater(m["total_slippage_cost"], 0)

    def test_07_trading_day_clock(self):
        from futures_trading_day import get_futures_trading_date, is_close_today
        # 周一 21:30 属于 周二交易日
        d1 = get_futures_trading_date("2026-09-07 21:30:00") # 2026-09-07 is Monday
        self.assertEqual(d1, "2026-09-08")

        # 周二 10:00 属于 周二交易日
        d2 = get_futures_trading_date("2026-09-08 10:00:00")
        self.assertEqual(d2, "2026-09-08")

        # 同属于周二交易日 -> 平今仓
        self.assertTrue(is_close_today("2026-09-07 21:30:00", "2026-09-08 10:00:00"))

        # 周三 10:00 属于 周三交易日 -> 平昨仓
        self.assertFalse(is_close_today("2026-09-07 21:30:00", "2026-09-09 10:00:00"))


if __name__ == "__main__":
    unittest.main()
