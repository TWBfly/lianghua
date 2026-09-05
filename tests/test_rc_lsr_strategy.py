"""
tests/test_rc_lsr_strategy.py — 「RC-LSR·市场状态条件化流动性冲击反转策略」因果性与对抗鲁棒性测试集
"""

import sys
import unittest
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STRATEGIES_DIR = PROJECT_ROOT / "strategies"
if str(STRATEGIES_DIR) not in sys.path:
    sys.path.insert(0, str(STRATEGIES_DIR))

import rc_lsr_strategy as rc_lsr


def generate_synthetic_ohlcv(n_bars: int = 300, seed: int = 42) -> pd.DataFrame:
    """构造具有真实微观波动特征的合成 30m OHLCV 数据"""
    np.random.seed(seed)
    base_price = 3500.0
    returns = np.random.normal(0.0001, 0.008, n_bars)

    # 注入流动性踩踏事件 1: 下行冲击 (bars 100~104 连续暴跌)
    if n_bars > 115:
        returns[100:104] = -0.022
        # 第 105 根 Bar: 探底长下影阳线 (Absorption + Failed Breakdown + Reclaim)
        returns[104] = 0.005

    # 注入流动性踩踏事件 2: 冲顶挤压 (bars 200~204 连续暴涨)
    if n_bars > 215:
        returns[200:204] = 0.022
        returns[204] = -0.005

    close = base_price * np.cumprod(1.0 + returns)
    high = close * (1.0 + np.abs(np.random.normal(0.002, 0.004, n_bars)))
    low = close * (1.0 - np.abs(np.random.normal(0.002, 0.004, n_bars)))
    open_ = np.roll(close, 1)
    open_[0] = base_price

    if n_bars > 115:
        # 特别雕琢第 104 根 Bar 的长下影探底
        low[104] = close[104] - 65.0
        open_[104] = close[104] - 8.0
        high[104] = close[104] + 5.0

    if n_bars > 215:
        # 特别雕琢第 204 根 Bar 的长上影冲顶
        high[204] = close[204] + 65.0
        open_[204] = close[204] + 8.0
        low[204] = close[204] - 5.0

    volume = np.random.uniform(2000, 5000, n_bars)
    if n_bars > 115:
        volume[100:105] = volume[100:105] * 2.5  # 放量冲击
    if n_bars > 215:
        volume[200:205] = volume[200:205] * 2.5

    open_interest = 100000 + np.cumsum(np.random.normal(0, 100, n_bars))

    date_idx = pd.date_range("2026-01-01 09:00", periods=n_bars, freq="30min")
    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "open_interest": open_interest,
    }, index=date_idx)


class TestRCLSRStrategy(unittest.TestCase):
    """RC-LSR 单元测试与对抗鲁棒性审计"""

    def test_01_metadata_and_interfaces(self):
        """验证策略元数据与标准接口"""
        self.assertEqual(rc_lsr.STRATEGY_NAME, "rc_lsr_strategy")
        self.assertIn("RC-LSR", rc_lsr.STRATEGY_DESCRIPTION)
        self.assertTrue(hasattr(rc_lsr, "calculate_factors"))
        self.assertTrue(hasattr(rc_lsr, "calculate_signal"))

    def test_02_factors_integrity_and_finiteness(self):
        """验证因果因子矩阵数值完整性与边界安全性"""
        df = generate_synthetic_ohlcv(200)
        factors = rc_lsr.calculate_factors(df)
        self.assertEqual(len(factors), len(df))

        expected_columns = [
            "atr", "ema_base", "ema_macro", "down_excursion", "up_excursion", "close_deviation",
            "er", "vr", "rvol", "impact_decay_down", "impact_decay_up",
            "failed_breakdown", "failed_breakout", "clv",
            "down_breadth", "up_breadth", "oi_safe_long", "oi_safe_short"
        ]
        for col in expected_columns:
            self.assertIn(col, factors.columns, f"Missing expected factor column: {col}")

        # 检查成熟区间 (t >= 30) 无任何 NaN 或 Inf 异常值
        mature_factors = factors.iloc[30:]
        numeric_cols = [c for c in factors.columns if c not in ("oi_safe_long", "oi_safe_short")]
        for col in numeric_cols:
            self.assertFalse(mature_factors[col].isna().any(), f"NaN detected in {col}")
            self.assertTrue(np.isfinite(mature_factors[col].values).all(), f"Non-finite value in {col}")

    def test_03_prefix_invariance_attack(self):
        """
        核心前缀不变性对抗攻击 (Prefix Invariance Attack):
        向数据序列追加数据或截断尾部，历史任意时刻的信号必须 100% 逐元素绝对一致。
        这是彻底证明零未来函数、纯因果计算的数学铁证。
        """
        df_full = generate_synthetic_ohlcv(280)
        sig_full = rc_lsr.calculate_signal(df_full)

        for cutoff in (110, 150, 200, 240):
            df_sub = df_full.iloc[:cutoff].copy()
            sig_sub = rc_lsr.calculate_signal(df_sub)

            np.testing.assert_array_equal(
                sig_sub.values,
                sig_full.iloc[:cutoff].values,
                err_msg=f"Prefix Invariance Failed at cutoff {cutoff}! Potential lookahead bias detected."
            )

    def test_04_cooldown_and_signal_bounds(self):
        """验证信号值域 [-1, 0, 1] 以及冷却窗口非连续重复发单特性"""
        df = generate_synthetic_ohlcv(250)
        sig = rc_lsr.calculate_signal(df, cooldown_bars=8)

        # 验证信号值域严格限于 {-1, 0, 1}
        unique_signals = set(sig.unique())
        self.assertTrue(unique_signals.issubset({-1, 0, 1}))

        # 验证冷却窗口：发出信号后的接下来 8 根 Bar 内绝不能有新的同向开仓
        sig_arr = sig.values
        nonzero_indices = np.where(sig_arr != 0)[0]
        for i in range(len(nonzero_indices) - 1):
            gap = nonzero_indices[i + 1] - nonzero_indices[i]
            self.assertGreaterEqual(gap, 8, f"Cooldown violated: gap {gap} < 8 bars between signals")


if __name__ == "__main__":
    unittest.main()
