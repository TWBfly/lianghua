"""
tests/test_taichong_elastoplastic_tensor.py — 「太冲·弹塑性张量」策略核心力学本构、因果性与卡方熔断单元测试
"""

import os
import sys
import unittest
import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
CODE_DIR = os.path.join(PROJECT_ROOT, "code")
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)
STRATEGIES_DIR = os.path.join(PROJECT_ROOT, "strategies")
if STRATEGIES_DIR not in sys.path:
    sys.path.insert(0, STRATEGIES_DIR)

from strategies.taichong_elastoplastic_tensor import (
    calculate_signal,
    calculate_factors,
    _ledoit_wolf_shrinkage_cov,
    STRATEGY_NAME,
)
from strategy_hot_plugger import hot_plugger


class TestTaichongElastoplasticTensor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        np.random.seed(42)
        cls.n = 350
        cls.dates = pd.date_range("2025-01-01", periods=cls.n, freq="15min")

        returns = np.random.normal(0.0001, 0.006, cls.n)
        # 植入极端相变单边断裂与大幅挤仓 (模拟 2022 伦镍式单边不可逆漂移)
        returns[150:180] = 0.025
        # 植入均值回归震荡
        returns[220:230] = -0.015
        returns[231:240] = 0.015

        close = 2000.0 * np.exp(np.cumsum(returns))
        high = close * (1.0 + np.abs(np.random.normal(0.002, 0.003, cls.n)))
        low = close * (1.0 - np.abs(np.random.normal(0.002, 0.003, cls.n)))
        open_p = (close + np.random.normal(0, 0.8, cls.n)).clip(min=low, max=high)
        volume = np.random.uniform(1000, 5000, cls.n)
        volume[150:180] *= 4.0
        oi = 100000.0 + np.cumsum(np.random.normal(20, 100, cls.n))

        cls.df = pd.DataFrame(
            {
                "open": open_p,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "open_interest": oi,
            },
            index=cls.dates,
        )

    def test_hot_plugger_discovery(self):
        """测试策略热插拔引擎能够自动发现并成功加载太冲策略"""
        hot_plugger.reload_plugins()
        available = hot_plugger.get_executable_strategies()
        self.assertIn(STRATEGY_NAME, available)
        self.assertIn("taichong_elastoplastic_tensor", available)

    def test_signal_output_contract(self):
        """测试标准输出契约：pd.Series, 取值属于 {-1, 0, 1}, 索引对齐"""
        signals = calculate_signal(self.df)
        self.assertIsInstance(signals, pd.Series)
        self.assertEqual(len(signals), len(self.df))
        self.assertTrue(set(signals.unique()).issubset({-1, 0, 1}))
        pd.testing.assert_index_equal(signals.index, self.df.index)

    def test_prefix_invariance_pure_causality(self):
        """严密因果测试：前缀截断不变量测试 (Prefix Invariance)，证明绝无未来函数"""
        prefix_len = 200
        df_prefix = self.df.iloc[:prefix_len].copy()

        full_signals = calculate_signal(self.df)
        prefix_signals = calculate_signal(df_prefix)

        # 比较前缀部分信号是否完全相同 (最后1个Bar由于动态内部状态需一致)
        pd.testing.assert_series_equal(
            full_signals.iloc[:prefix_len],
            prefix_signals,
            check_names=False,
        )

    def test_chi2_rupture_circuit_breaker(self):
        """测试卡方结构破裂硬熔断：在极端单边相变爆发期间，熔断关阀生效"""
        factors = calculate_factors(self.df)
        rupture = factors["rupture_breaker"]
        signals = calculate_signal(self.df)

        # 在破裂断裂区间 (150:180) 应出现卡方破裂熔断
        self.assertTrue(rupture.iloc[155:175].any())

        # 在熔断为 True 的时刻，信号必须被硬性置为 0 (禁止接飞刀逆势空)
        rupture_indices = rupture[rupture].index
        self.assertTrue((signals.loc[rupture_indices] == 0).all())

    def test_elastoplastic_strain_decomposition(self):
        """测试弹塑性应变分解：在持续单边漂移下，可逆弹性应变不发生无限爆炸，塑性滑移吸收永久位移"""
        factors = calculate_factors(self.df)
        elastic_z = factors["elastic_zscore"]
        plastic = factors["plastic_offset"]

        # 弹性应变上限被约束在屈服面附近 (不超过 2.5)
        self.assertLessEqual(elastic_z.abs().max(), 2.5)

        # 单边剧烈上涨时，塑性滑移应为正且显著吸收位移
        self.assertGreater(plastic.iloc[170:185].max(), 1.0)

    def test_ledoit_wolf_numerical_stability(self):
        """测试 Ledoit-Wolf 协方差估计在退化/奇异特征矩阵下的数值稳健性"""
        # 生成共线/奇异特征矩阵
        X_singular = np.ones((20, 4))
        X_singular[:, 1] = X_singular[:, 0] * 2.0
        cov_shrunk = _ledoit_wolf_shrinkage_cov(X_singular)

        self.assertEqual(cov_shrunk.shape, (4, 4))
        # 必须是半正定/正定矩阵，特征值非负
        eigvals = np.linalg.eigvalsh(cov_shrunk)
        self.assertTrue((eigvals >= -1e-10).all())

    def test_no_sma5_lookahead(self):
        """测试同柱 SMA5 止盈不使用未完成的收盘价：改变当根 Bar 收盘价，平仓价格保持确定性一致"""
        from run_taichong_multi_timeframe_deep_comparison import simulate_taichong
        spec = {"multiplier": 10.0, "tick": 0.5, "fee_rate": 0.00005}

        # 构造数据，第 20 根 Bar 进场多头，第 21 根 Bar 触发止盈
        df1 = self.df.iloc[:30].copy()
        signals = pd.Series(0, index=df1.index)
        signals.iloc[19] = 1  # 进场信号

        # 调整第 21 根 Bar (index 20) 的高点以触发 SMA5 止盈
        df1.iloc[20, df1.columns.get_loc("high")] = 3000.0
        df1.iloc[20, df1.columns.get_loc("close")] = 2500.0

        res1 = simulate_taichong(df1, signals, spec)
        trades1 = res1["trades"]
        self.assertFalse(trades1.empty, "应有交易生成")
        first_exit_p1 = trades1.iloc[0]["exit_price"]

        # 构造 df2: 保持 open, high, low 完全一致，仅改变当根 Bar 的 close
        df2 = df1.copy()
        df2.iloc[20, df2.columns.get_loc("close")] = 2000.0  # 剧烈改变当根收盘价

        res2 = simulate_taichong(df2, signals, spec)
        trades2 = res2["trades"]
        self.assertFalse(trades2.empty, "应有交易生成")
        first_exit_p2 = trades2.iloc[0]["exit_price"]

        # 因果断言：平仓成交价绝对不能受当根未完结收盘价的影响！
        self.assertEqual(first_exit_p1, first_exit_p2)

    def test_pessimistic_collision_priority(self):
        """测试同柱止盈止损碰撞时，必须悲观止损绝对优先，严禁乐观止盈"""
        from run_taichong_multi_timeframe_deep_comparison import simulate_taichong
        spec = {"multiplier": 10.0, "tick": 0.5, "fee_rate": 0.00005}

        df = self.df.iloc[:30].copy()
        signals = pd.Series(0, index=df.index)
        signals.iloc[19] = 1  # 进场信号

        # 在第 21 根 Bar 制造极端宽幅柱：最高价触及止盈，最低价暴跌触及硬止损
        df.iloc[20, df.columns.get_loc("open")] = 2000.0
        df.iloc[20, df.columns.get_loc("high")] = 4000.0  # 远超止盈线
        df.iloc[20, df.columns.get_loc("low")] = 500.0    # 远穿止损线
        df.iloc[20, df.columns.get_loc("close")] = 2000.0

        res = simulate_taichong(df, signals, spec)
        trades = res["trades"]
        self.assertFalse(trades.empty)
        # 必须是止损优先，绝不能是 take_profit_sma5
        self.assertIn("stop", trades.iloc[0]["exit_reason"])
        self.assertNotEqual("take_profit_sma5", trades.iloc[0]["exit_reason"])

    def test_directional_oi_filter(self):
        """测试非对称持仓量(OI)微观主动进攻过滤：下跌增仓拦截多头抄底"""
        df = self.df.copy()
        c = df["close"].values
        df["volume"] = 1000.0
        oi = np.full(len(df), 10000.0)
        # 模拟下跌增仓 (空头主动砸盘): 在 225 处价格低于前值且持仓量突增
        df.iloc[225, df.columns.get_loc("close")] = df.iloc[224]["close"] - 10.0
        oi[225] = oi[224] + 5000.0
        df["open_interest"] = oi

        factors = calculate_factors(df)
        # 此时下跌增仓，空头凶猛，做多持仓量过滤应为 False (拦截做多)
        self.assertFalse(factors["oi_filter_long"].iloc[225])
        # 做空过滤应不受影响
        self.assertTrue(factors["oi_filter_short"].iloc[225])

    def test_timeframe_scaling_differentiation(self):
        """测试多周期尺度计算自适应：1m 与 30m 的时间尺度与持仓小时数严格隔离"""
        from run_taichong_multi_timeframe_deep_comparison import summarize_simulation
        mock_result = {
            "trades": pd.DataFrame({
                "net_pnl": [100.0, -50.0],
                "entry_fee": [1.0, 1.0],
                "exit_fee": [1.0, 1.0],
                "slippage_cost": [2.0, 2.0],
                "gross_pnl": [104.0, -46.0],
                "holding_bars": [6, 12],
            }),
            "equity": pd.Series([1000000.0, 1000100.0, 1000050.0]),
            "final_equity": 1000050.0,
            "net_pnl": 50.0,
            "ledger_reconciled": True,
        }
        res_1m = summarize_simulation("AU", "沪金", "1m", "real", mock_result, 1000)
        res_30m = summarize_simulation("AU", "沪金", "30m", "real", mock_result, 1000)

        # 平均持仓 (6+12)/2 = 9 根 Bar
        # 9 根 Bar 在 1m 下是 9 * 1 / 60 = 0.15 小时
        self.assertAlmostEqual(res_1m["avg_holding_hours"], 0.15, places=2)
        # 9 根 Bar 在 30m 下是 9 * 30 / 60 = 4.5 小时
        self.assertAlmostEqual(res_30m["avg_holding_hours"], 4.5, places=2)
        # 1m 的持仓时间必须显著小于 30m，不得默认套用 30m
        self.assertLess(res_1m["avg_holding_hours"], res_30m["avg_holding_hours"])


if __name__ == "__main__":
    unittest.main()
