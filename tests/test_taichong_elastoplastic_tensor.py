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


if __name__ == "__main__":
    unittest.main()
