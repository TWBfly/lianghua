"""
tests/test_chanquant_v3_anti_lookahead.py — ChanQuant 3.0 全息反未来函数与前缀不变性测试
"""

import math
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

from chan_regime_classifier import classify_kinetic_regime, calculate_causal_hurst
from chan_microstructure_gate import extract_microstructure_features
from chanquant_v3_master_strategy import calculate_signal, calculate_factors


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


def test_regime_prefix_invariance():
    """测试机制分类器的前缀不变性"""
    df = generate_test_df(400)
    cutoff = 250

    regime_full = classify_kinetic_regime(df)
    regime_prefix = classify_kinetic_regime(df.iloc[:cutoff].copy())

    for col in ["hurst", "ss_price", "ss_slope", "regime"]:
        diff = np.abs(regime_full[col].values[:cutoff] - regime_prefix[col].values)
        assert np.max(diff) < 1e-5, f"机制分类器前缀不变性失败: {col}"


def test_microstructure_prefix_invariance():
    """测试微观订单流门禁的前缀不变性"""
    df = generate_test_df(400)
    cutoff = 250

    micro_full = extract_microstructure_features(df)
    micro_prefix = extract_microstructure_features(df.iloc[:cutoff].copy())

    for col in ["ofi_zscore", "vol_density"]:
        diff = np.abs(micro_full[col].values[:cutoff] - micro_prefix[col].values)
        assert np.max(diff) < 1e-5, f"微观结构特征前缀不变性失败: {col}"


def test_v3_strategy_prefix_invariance():
    """测试 ChanQuant 3.0 策略的前缀不变性"""
    df = generate_test_df(500)
    cutoff = 350

    sig_full = calculate_signal(df)
    sig_prefix = calculate_signal(df.iloc[:cutoff].copy())

    diff = np.abs(sig_full.values[:cutoff] - sig_prefix.values)
    assert np.max(diff) == 0, "ChanQuant 3.0 策略前缀不变性失败 (存在未来信号重绘)"


if __name__ == "__main__":
    print("Testing regime prefix invariance...")
    test_regime_prefix_invariance()
    print("PASS: test_regime_prefix_invariance")

    print("Testing microstructure prefix invariance...")
    test_microstructure_prefix_invariance()
    print("PASS: test_microstructure_prefix_invariance")

    print("Testing ChanQuant 3.0 strategy prefix invariance...")
    test_v3_strategy_prefix_invariance()
    print("PASS: test_v3_strategy_prefix_invariance")

    print("\n========================================================")
    print(">>> ALL CHANQUANT 3.0 ANTI-LOOKAHEAD TESTS PASSED! <<<")
    print("========================================================")
