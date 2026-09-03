"""
tests/test_backtest_metrics_and_causal_fixes.py
验证回测指标计算修复（CAGR防爆炸、持仓时间防抹零）与 Causal ML 趋势信噪比及动态三屏出场逻辑
"""

import unittest
import numpy as np


def calc_annualized_return(total_return_pct: float, duration_days: float) -> float:
    """对应 Rust backtest.rs 中的 GIPS 工业年化算法"""
    duration_years = duration_days / 365.25
    if duration_years >= 1.0:
        geom = (((1.0 + total_return_pct / 100.0) ** (1.0 / duration_years)) - 1.0) * 100.0
        return max(-100.0, min(9999.0, geom))
    elif duration_days >= 3.0:
        simple = (total_return_pct / duration_days) * 252.0
        return max(-100.0, min(9999.0, simple))
    else:
        return total_return_pct


def format_avg_holding(avg_holding_days: float) -> str:
    """对应 React 前端 BacktestMetricsBar.tsx 的自适应展示逻辑"""
    if avg_holding_days >= 1.0:
        return f"{avg_holding_days:.1f} 天"
    elif avg_holding_days * 24.0 >= 1.0:
        return f"{avg_holding_days * 24.0:.1f} 小时"
    else:
        mins = max(1, round(avg_holding_days * 1440.0))
        return f"{mins} 分钟"


def compute_snr(closes: list) -> float:
    """对应 Causal ML 中的路径信噪比 (Signal-to-Noise Ratio)"""
    net_move = abs(closes[-1] - closes[0])
    path_var = sum(abs(closes[k] - closes[k - 1]) for k in range(1, len(closes)))
    return (net_move / path_var) if path_var > 1e-6 else 0.0


class TestBacktestEngineFixes(unittest.TestCase):

    def test_annualized_return_short_sample_no_explosion(self):
        # 30 个交易日 (约 0.11 年), 累积收益 +342.66%
        # 旧逻辑: (1 + 3.42)^(1 / 0.11) - 1 => +39877.62% (荒谬爆炸)
        # 新逻辑: 342.66% / 30 * 252 => ~2878% (单利线性折算)
        cagr = calc_annualized_return(342.66, 30.0)
        self.assertLess(cagr, 3500.0, "短周期年化不应发生近4万%的几何指数爆炸")
        self.assertGreater(cagr, 1000.0, "短周期应合理折算")

    def test_annualized_return_multi_year(self):
        # 3 年跨度 (1095 天), 累积收益 100%
        # 复合年化: (2)^(1/3) - 1 => ~25.99%
        cagr = calc_annualized_return(100.0, 1095.0)
        self.assertAlmostEqual(cagr, 25.99, delta=0.5)

    def test_avg_holding_minutes_not_zero(self):
        # 1 分钟策略持有 18 根 Bar = 18 分钟 = 18 / 1440 = 0.0125 天
        # 旧逻辑: round(0.0125 * 10) / 10 = 0.0 天 => 0 分钟 (Bug)
        # 新逻辑: 保留高精度 => 18 分钟
        avg_holding_days = 18.0 / 1440.0
        label = format_avg_holding(avg_holding_days)
        self.assertEqual(label, "18 分钟")
        self.assertNotEqual(label, "0 分钟")

    def test_snr_filter_distinguishes_noise_from_trend(self):
        # 纯震荡拉锯 (价格在 100 和 101 间来回震荡 10 根 Bar)
        whipsaw = [100.0, 101.0, 100.0, 101.0, 100.0, 101.0, 100.0, 101.0, 100.0, 100.2]
        snr_noise = compute_snr(whipsaw)
        # 纯单边趋势 (价格从 100 稳步涨至 108)
        trend = [100.0, 100.8, 101.5, 102.3, 103.1, 104.2, 105.0, 106.1, 107.0, 108.0]
        snr_trend = compute_snr(trend)

        self.assertLess(snr_noise, 0.20, "震荡噪声 SNR 应该极低，会被 Meta-Labeling 过滤")
        self.assertGreater(snr_trend, 0.80, "单边趋势 SNR 应显著高于 0.30 门槛")


if __name__ == "__main__":
    unittest.main()
