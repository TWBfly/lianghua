"""
tests/test_strategy_optimizer_agent.py — 策略优化 Agent 与防过拟合门禁单元测试
"""

import os
import sys
import unittest
import numpy as np
import pandas as pd

CODE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "code")
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from strategy_optimizer_agent import (
    AssetPhysicsClassifier,
    PurgedWalkForwardSplitter,
    StrategyOptimizerAgent,
)


class TestStrategyOptimizerAgent(unittest.TestCase):

    def setUp(self):
        np.random.seed(42)
        n = 600
        dates = pd.date_range("2025-01-01", periods=n, freq="15min")
        ret = np.random.normal(0.0002, 0.004, n)
        
        # 局部植入多次经典波动挤压与向上/向下真突破
        for start_idx in [50, 150, 250, 350, 450]:
            ret[start_idx:start_idx+10] = 0.0001
            ret[start_idx+11:start_idx+16] = 0.015  # 爆发拉升
            ret[start_idx+20:start_idx+25] = -0.008

        c = 5000.0 * np.exp(np.cumsum(ret))
        h = c * (1.0 + np.abs(np.random.normal(0.001, 0.002, n)))
        l = c * (1.0 - np.abs(np.random.normal(0.001, 0.002, n)))
        o = (c + np.random.normal(0, 0.5, n)).clip(min=l, max=h)
        v = np.random.uniform(1000, 5000, n)
        for start_idx in [50, 150, 250, 350, 450]:
            v[start_idx+11:start_idx+16] *= 2.5
        oi = 100000.0 + np.cumsum(np.random.normal(20, 100, n))

        self.sample_futures_bars = pd.DataFrame({
            "open": o, "high": h, "low": l, "close": c,
            "volume": v, "open_interest": oi
        }, index=dates)

    def test_asset_physics_classification(self):
        """测试物理微观结构分类器"""
        regime_ag = AssetPhysicsClassifier.classify_symbol(self.sample_futures_bars, "AG_IDX")
        regime_rb = AssetPhysicsClassifier.classify_symbol(self.sample_futures_bars, "RB_IDX")
        regime_c = AssetPhysicsClassifier.classify_symbol(self.sample_futures_bars, "C_IDX")

        self.assertEqual(regime_ag, "TREND_DOMINANT")
        self.assertEqual(regime_rb, "MEAN_REVERTING")
        self.assertIn(regime_c, {"HYBRID_CYCLICAL", "TREND_DOMINANT", "MEAN_REVERTING"})

    def test_purged_walk_forward_splitter(self):
        """测试 Purged Walk-Forward 切分严格杜绝时序重叠"""
        train_df, test_df = PurgedWalkForwardSplitter.split(self.sample_futures_bars, train_ratio=0.70, purge_gap=20)

        self.assertLess(len(train_df) + len(test_df), len(self.sample_futures_bars))  # 包含 purge_gap
        self.assertLess(train_df.index.max(), test_df.index.min())
        self.assertGreater((test_df.index.min() - train_df.index.max()).total_seconds(), 0)

    def test_optimizer_agent_single_symbol_optimization(self):
        """测试优化 Agent 针对单品种生成平原检验通过的高胜率配置"""
        agent = StrategyOptimizerAgent()
        spec = {"multiplier": 15.0, "tick": 1.0, "fee_rate": 0.00005}

        candidate = agent.optimize_symbol(self.sample_futures_bars, "AG_IDX", spec)

        self.assertIn("params", candidate)
        self.assertIn("win_rate_pct", candidate["full_sample"])
        self.assertIn("profit_loss_ratio", candidate["full_sample"])
        self.assertIn("plateau_test_pass", candidate)


if __name__ == "__main__":
    unittest.main()
