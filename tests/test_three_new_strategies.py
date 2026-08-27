"""
tests/test_three_new_strategies.py — 三大新策略与特征工程单元测试与对抗安全审计
"""

import os
import sys
import numpy as np
import pandas as pd
import pytest

CODE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "code")
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from alpha_factor_miner import FactorRegistry
from strategy_hot_plugger import hot_plugger


@pytest.fixture
def sample_market_data():
    """生成具备真实波动的因果行情序列 (包含 OHLCV + OpenInterest)"""
    np.random.seed(42)
    n = 300
    dates = pd.date_range("2025-01-01", periods=n, freq="15min")
    
    # 几何布朗运动构造价格
    returns = np.random.normal(0.0002, 0.008, n)
    # 植入局部的挤压与大幅突破
    returns[100:110] = 0.0001
    returns[111:115] = 0.025
    # 植入局部的极值超卖与反转
    returns[200:205] = -0.03
    returns[206] = 0.02
    
    close = 1000.0 * np.exp(np.cumsum(returns))
    high = close * (1.0 + np.abs(np.random.normal(0.002, 0.003, n)))
    low = close * (1.0 - np.abs(np.random.normal(0.002, 0.003, n)))
    open_p = (close + np.random.normal(0, 0.5, n)).clip(min=low, max=high)
    volume = np.random.uniform(500, 2000, n)
    volume[111:115] *= 3.0  # 放量
    volume[205:207] *= 2.5
    
    oi = 50000.0 + np.cumsum(np.random.normal(10, 50, n))
    oi[111:115] += 1000.0  # 机构建仓
    
    df = pd.DataFrame({
        "open": open_p,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "open_interest": oi,
        "amount": close * volume
    }, index=dates)
    return df


def test_new_factors_registration(sample_market_data):
    """测试四大新因子在 FactorRegistry 中成功注册并正确因果计算"""
    factors = ["vol_squeeze_energy", "connors_rsi_2", "pinbar_absorption_ratio", "oi_momentum_surge"]
    for factor_name in factors:
        func = FactorRegistry.get_factor(factor_name)
        assert func is not None, f"因子 {factor_name} 未在 FactorRegistry 中注册！"
        result = func(sample_market_data)
        assert isinstance(result, pd.Series)
        assert len(result) == len(sample_market_data)
        assert not result.dropna().empty


def test_hot_plugger_loads_three_strategies():
    """测试热插拔引擎正确加载并注册三大新策略"""
    hot_plugger.reload_plugins()
    available = hot_plugger.get_executable_strategies()
    
    assert "tianji_orderflow_breakout" in available
    assert "guiyuan_zscore_reversion" in available
    assert "xuanwu_macro_momentum" in available


@pytest.mark.parametrize("strat_name", [
    "tianji_orderflow_breakout",
    "guiyuan_zscore_reversion",
    "xuanwu_macro_momentum",
])
def test_strategy_signal_generation(strat_name, sample_market_data):
    """测试三大策略信号生成格式符合 [-1, 0, 1] 规范且索引一致"""
    signals = hot_plugger.calculate_signal(strat_name, sample_market_data)
    assert isinstance(signals, pd.Series)
    assert len(signals) == len(sample_market_data)
    assert set(signals.unique()).issubset({-1, 0, 1})


@pytest.mark.parametrize("strat_name", [
    "tianji_orderflow_breakout",
    "guiyuan_zscore_reversion",
    "xuanwu_macro_momentum",
])
def test_prefix_invariance_adversarial_check(strat_name, sample_market_data):
    """
    强因果对抗测试：前缀截断不变量测试 (Prefix Invariance Test)
    针对任意历史截断点 T，输入前 T 根数据计算的信号必须与全量数据在 T 点处的信号 100% 严格一致！
    杜绝任何全局 min-max 标准化、向后 shift 等未来函数。
    """
    full_signals = hot_plugger.calculate_signal(strat_name, sample_market_data)
    
    # 随机选取 5 个不同时间截断点进行压力测试
    test_cutoffs = [60, 120, 180, 240, 290]
    for cutoff in test_cutoffs:
        truncated_df = sample_market_data.iloc[:cutoff].copy()
        truncated_signals = hot_plugger.calculate_signal(strat_name, truncated_df)
        
        expected_signal = full_signals.iloc[cutoff - 1]
        actual_signal = truncated_signals.iloc[-1]
        
        assert actual_signal == expected_signal, (
            f"策略 {strat_name} 在截断点 {cutoff} 出现前缀不一致 (未来函数泄漏)！"
            f"预期: {expected_signal}, 实际: {actual_signal}"
        )
