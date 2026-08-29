import sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "strategies"))

from strategies.supertrend_evolution_master import (
    compute_supertrend_bands,
    compute_kaufman_efficiency_ratio,
    compute_dynamic_supertrend,
    SuperTrendEvolutionEngine,
    calculate_volatility_targeted_lots
)


def _generate_synthetic_df(n: int = 200, trend: float = 0.001, seed: int = 42) -> pd.DataFrame:
    """生成确定性测试行情"""
    rng = np.random.default_rng(seed)
    prices = [1000.0]
    for _ in range(n - 1):
        ret = trend + rng.normal(0, 0.005)
        prices.append(prices[-1] * (1.0 + ret))
    
    closes = np.array(prices)
    highs = closes * (1.0 + np.abs(rng.normal(0, 0.003, n)))
    lows = closes * (1.0 - np.abs(rng.normal(0, 0.003, n)))
    opens = (highs + lows) / 2.0
    vols = np.full(n, 1000.0)

    df = pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": vols,
        "open_interest": vols * 10
    }, index=pd.date_range("2026-01-01", periods=n, freq="15min"))
    return df


def test_supertrend_bands_invariants():
    """测试 SuperTrend 轨线数学不变量与防回退锁定"""
    df = _generate_synthetic_df(n=100, trend=0.002)
    st_line, direction, final_upper, final_lower = compute_supertrend_bands(df, period=10, multiplier=3.0)
    
    assert len(st_line) == len(df)
    assert len(direction) == len(df)
    assert set(np.unique(direction)).issubset({-1, 0, 1})
    
    # 状态为多头时，SuperTrend 轨线必须位于下轨
    long_mask = direction == 1
    if np.any(long_mask):
        assert np.allclose(st_line[long_mask], final_lower[long_mask])

    # 状态为空头时，SuperTrend 轨线必须位于上轨
    short_mask = direction == -1
    if np.any(short_mask):
        assert np.allclose(st_line[short_mask], final_upper[short_mask])


def test_kaufman_efficiency_ratio():
    """测试考夫曼效率比率在单边与锯齿环境下的数值响应"""
    # 1. 完美单边行情 -> KER 接近 1.0
    perfect_trend = pd.Series(np.linspace(100, 200, 50))
    ker_trend = compute_kaufman_efficiency_ratio(perfect_trend, period=20)
    assert ker_trend.iloc[-1] >= 0.99

    # 2. 完美无位移锯齿行情 -> KER 接近 0.0
    zigzag = pd.Series([100, 105, 95, 105, 95] * 10)
    ker_zigzag = compute_kaufman_efficiency_ratio(zigzag, period=20)
    assert ker_zigzag.iloc[-1] <= 0.10


def test_volatility_targeting_sizing():
    """测试波动率目标仓位计算反比关系"""
    equity = 1_000_000.0
    mult = 10.0
    
    # 高波动率时仓位应该小
    lots_high_vol = calculate_volatility_targeted_lots(equity, atr_price=50.0, contract_multiplier=mult)
    # 低波动率时仓位应该大
    lots_low_vol = calculate_volatility_targeted_lots(equity, atr_price=10.0, contract_multiplier=mult)
    
    assert lots_low_vol > lots_high_vol
    assert lots_high_vol >= 1


def test_evolution_engine_signals_discrete():
    """测试各代际信号严格为离散值 {-1, 0, 1}"""
    df = _generate_synthetic_df(n=100)
    
    sig_st00 = SuperTrendEvolutionEngine.generate_st00_baseline(df)
    assert set(sig_st00.unique()).issubset({-1, 0, 1})
    
    sig_st01 = SuperTrendEvolutionEngine.generate_st01_regime_filtered(df)
    assert set(sig_st01.unique()).issubset({-1, 0, 1})

    sig_st03 = SuperTrendEvolutionEngine.generate_st03_independent_entry(df)
    assert set(sig_st03.unique()).issubset({-1, 0, 1})


if __name__ == "__main__":
    test_supertrend_bands_invariants()
    test_kaufman_efficiency_ratio()
    test_volatility_targeting_sizing()
    test_evolution_engine_signals_discrete()
    print("✅ All SuperTrend evolution unit tests passed successfully!")

