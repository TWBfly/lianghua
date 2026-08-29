import sys
import math
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "code"))

from technical_indicators import (
    calculate_ehlers_supersmoother,
    calculate_kalman_velocity_tracker,
    calculate_permutation_entropy,
    calculate_dfa_hurst_exponent
)


def test_ehlers_supersmoother_attenuation():
    """验证 Ehlers SuperSmoother 对高频白噪声的平滑衰减能力"""
    n = 200
    t = np.linspace(0, 10, n)
    trend = 100.0 + 2.0 * t
    rng = np.random.default_rng(2026)
    noise = rng.normal(0, 2.5, size=n)
    price = pd.Series(trend + noise)

    smoothed = calculate_ehlers_supersmoother(price, period=14)
    assert len(smoothed) == n
    # 平滑后序列的二阶方差应明显小于带噪原序列
    assert smoothed.diff().dropna().std() < price.diff().dropna().std()
    # 尾部应贴近真实线性趋势
    assert abs(smoothed.iloc[-1] - trend[-1]) < 3.0



def test_kalman_velocity_tracker():
    """验证一阶卡尔曼速度跟踪器能够正确估计单边上升与下降的速度"""
    n = 100
    # 上涨阶段：斜率 +1.5
    up_trend = 100.0 + 1.5 * np.arange(50)
    # 下跌阶段：斜率 -2.0
    down_trend = up_trend[-1] - 2.0 * np.arange(50)
    price = pd.Series(np.concatenate([up_trend, down_trend]))

    est_p, est_v = calculate_kalman_velocity_tracker(price, q_factor=0.01)
    assert len(est_p) == n
    assert len(est_v) == n

    # 上涨段速度应稳定为正 (> 0.5)
    assert est_v.iloc[20:45].mean() > 0.5
    # 下跌段速度应稳定为负 (< -0.5)
    assert est_v.iloc[65:90].mean() < -0.5


def test_permutation_entropy_order_vs_chaos():
    """验证纯单调趋势的排列熵极低 (有序)，白噪声的排列熵极高 (混乱)"""
    n = 100
    # 1. 严格单调递增序列 (有序低熵)
    monotonic_price = pd.Series(100.0 + np.arange(n) * 0.5)
    pe_order = calculate_permutation_entropy(monotonic_price, order=3, delay=1, window=30)
    # 尾部熵值应接近 0.0
    assert pe_order.iloc[-1] < 0.20

    # 2. 纯随机高斯噪声 (混乱高熵)
    rng = np.random.default_rng(2026)
    noise_price = pd.Series(100.0 + rng.normal(0, 1.0, size=n))
    pe_chaos = calculate_permutation_entropy(noise_price, order=3, delay=1, window=30)
    # 尾部熵值应明显高于单调序列 (> 0.75)
    assert pe_chaos.iloc[-1] > 0.75


def test_dfa_hurst_exponent():
    """验证 DFA Hurst 指数能够正确计算长度并输出合法区间 [0, 1]"""
    n = 250
    rng = np.random.default_rng(42)
    # 几何布朗运动
    rets = rng.normal(0.001, 0.02, size=n)
    price = pd.Series(100.0 * np.exp(np.cumsum(rets)))

    hurst = calculate_dfa_hurst_exponent(price, window=100)
    assert len(hurst) == n
    assert (hurst.dropna() >= 0.0).all()
    assert (hurst.dropna() <= 1.0).all()


if __name__ == "__main__":
    test_ehlers_supersmoother_attenuation()
    test_kalman_velocity_tracker()
    test_permutation_entropy_order_vs_chaos()
    test_dfa_hurst_exponent()
    print("✅ All 4 Modern Quant Toolkit tests passed successfully!")

