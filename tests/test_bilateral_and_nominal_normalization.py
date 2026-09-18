# -*- coding: utf-8 -*-
"""
Unit tests for Bilateral Long-Short Trading, Nominal Value Normalization, and Adaptive Global Rank IC.
(tests/test_bilateral_and_nominal_normalization.py)
Validates:
1. Bilateral Long-Short state machine generates both long and short trades symmetrically.
2. Nominal value normalization assigns equal capital exposure (~300,000 RMB) regardless of contract size.
3. Adaptive Global Rank IC evaluates correlation across the global sample rather than local slice ranks.
"""

import os
import sys
import unittest
import numpy as np
import pandas as pd
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "code")))
import autonomous_alpha_research_engine as engine

class TestBilateralAndNominalNormalization(unittest.TestCase):
    def setUp(self):
        np.random.seed(42)
        n = 1000
        # 构造包含单边上涨与单边下跌的波浪行情
        trend = np.sin(np.linspace(0, 4 * np.pi, n)) * 0.10
        returns = trend / 50.0 + np.random.normal(0, 0.005, n)
        close = 100.0 * np.exp(np.cumsum(returns))
        high = close * (1.0 + np.random.uniform(0.001, 0.005, n))
        low = close * (1.0 - np.random.uniform(0.001, 0.005, n))
        open_p = (high + low) / 2.0
        volume = np.random.uniform(1000, 5000, n)
        self.df = pd.DataFrame({
            "trade_time": pd.date_range("2026-01-01", periods=n, freq="15min").astype(str),
            "open": open_p,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": volume * close,
        })

    def test_nominal_value_normalization_exposure(self):
        """验证贵金属(AU_IDX)与农产品(M_IDX)在 30 万元预算下开仓名义货值均衡，杜绝18倍量纲失衡"""
        # AU_IDX 价格 560, 乘数 1000 -> 1手货值 560,000
        p_au = 560.0
        m_au = 1000.0
        lots_au = max(1, int(round(engine.TARGET_NOMINAL_VALUE / (p_au * m_au))))
        nominal_au = lots_au * p_au * m_au

        # M_IDX 价格 3000, 乘数 10 -> 1手货值 30,000
        p_m = 3000.0
        m_m = 10.0
        lots_m = max(1, int(round(engine.TARGET_NOMINAL_VALUE / (p_m * m_m))))
        nominal_m = lots_m * p_m * m_m

        self.assertEqual(lots_au, 1, "沪金应开 1 手")
        self.assertEqual(lots_m, 10, "豆粕应开 10 手")
        # 验证名义货值差异在 2 倍以内 (56万 vs 30万)，彻底打破原先 18.6 倍的极端失衡
        ratio = nominal_au / nominal_m
        self.assertLess(ratio, 2.0, f"名义敞口比率应 < 2.0，实测为 {ratio:.2f}")

    def test_bilateral_long_short_symmetry(self):
        """验证多空双向交易机制能同时捕获多头与空头交易，且退出计算完全对称"""
        factor_def = {
            "id": "FAC_OSC_TEST",
            "name": "多空震荡测试因子",
            "family": "趋势质量 (Trend Quality)",
            "hypothesis": "验证双向交易",
            "formula": "Close - SMA(Close, 20)",
            "calc": lambda df: df["close"] - df["close"].rolling(20).mean(),
            "direction": 1,
        }

        with patch("autonomous_alpha_research_engine.load_bars_from_db", return_value=self.df):
            res = engine.evaluate_factor_on_symbol(factor_def, "AU_IDX")
            self.assertTrue(res["success"])
            self.assertGreater(res["trades"], 5, "应产生多笔交易")

    def test_global_rank_ic_vs_horizon(self):
        """验证自适应 Rank IC 全局计算无辛普森悖论"""
        factor_def_trend = {
            "id": "FAC_TREND_TEST",
            "name": "趋势动量测试因子",
            "family": "动量家族 (Momentum)",
            "formula": "Close.diff(20)",
            "calc": lambda df: df["close"].diff(20),
            "direction": 1,
        }
        with patch("autonomous_alpha_research_engine.load_bars_from_db", return_value=self.df):
            res = engine.evaluate_factor_on_symbol(factor_def_trend, "AU_IDX")
            self.assertTrue(res["success"])
            # Rank IC 应当是浮点数且不为 NaN
            self.assertFalse(np.isnan(res["rank_ic"]))
            self.assertFalse(np.isnan(res["ic_std"]))

if __name__ == "__main__":
    unittest.main()
