"""
tests/test_chanquant_v4_anti_lookahead.py — ChanQuant 4.0 全息反未来函数与前缀不变性测试
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = PROJECT_ROOT / "code"
STRATEGIES_DIR = PROJECT_ROOT / "strategies"
for p in (CODE_DIR, STRATEGIES_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from chanquant_v4_master_strategy import (
    calculate_signal,
    calculate_factors_v4,
    calculate_risk_parity_lots,
    get_asset_profile,
)


def generate_test_df(n_bars: int = 500, seed: int = 42) -> pd.DataFrame:
    np.random.seed(seed)
    prices = [100.0]
    for i in range(1, n_bars):
        drift = 0.08 if i > 250 else (-0.05 if 100 < i < 200 else 0.02)
        noise = np.random.normal(0, 0.4)
        prices.append(prices[-1] + drift + noise)

    prices = np.array(prices)
    highs = prices + np.random.uniform(0.2, 0.6, n_bars)
    lows = prices - np.random.uniform(0.2, 0.6, n_bars)
    opens = (highs + lows) / 2 + np.random.uniform(-0.1, 0.1, n_bars)
    closes = (highs + lows) / 2 + np.random.uniform(-0.1, 0.1, n_bars)
    volumes = np.random.randint(1000, 5000, n_bars).astype(float)
    dates = pd.date_range("2026-01-01", periods=n_bars, freq="15min")

    df = pd.DataFrame({
        "trade_time": dates.astype(str),
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "open_interest": volumes * 10,
    })
    return df


def test_v4_prefix_invariance():
    """测试 ChanQuant 4.0 策略前缀不变性"""
    df = generate_test_df(500)
    cutoff = 350

    sig_full = calculate_signal(df, symbol="AG_IDX")
    sig_prefix = calculate_signal(df.iloc[:cutoff].copy(), symbol="AG_IDX")

    diff = np.abs(sig_full.values[:cutoff] - sig_prefix.values)
    assert np.max(diff) == 0, "ChanQuant 4.0 策略前缀不变性失败"


def test_risk_parity_calculation():
    """测试波动率平价开仓手数"""
    lots_au = calculate_risk_parity_lots("AU_IDX", price=550.0, atr_val=10.0, capital=500_000)
    lots_ta = calculate_risk_parity_lots("TA_IDX", price=5000.0, atr_val=50.0, capital=500_000)

    assert lots_au >= 1, "AU 手数应大于等于 1"
    assert lots_ta > lots_au, "TA 手数应明显多于高价值 AU 手数以实现风险平价"


if __name__ == "__main__":
    print("Testing ChanQuant 4.0 prefix invariance...")
    test_v4_prefix_invariance()
    print("PASS: test_v4_prefix_invariance")

    print("Testing Risk-Parity calculation...")
    test_risk_parity_calculation()
    print("PASS: test_risk_parity_calculation")

    print("\n========================================================")
    print(">>> ALL CHANQUANT 4.0 ANTI-LOOKAHEAD TESTS PASSED! <<<")
    print("========================================================")
