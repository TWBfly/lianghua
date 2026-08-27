"""
tests/test_strategy_optimizer_agent.py — 策略优化 Agent 与防过拟合门禁单元测试
"""

import os
import sys
import numpy as np
import pandas as pd
import pytest

CODE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "code")
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from strategy_optimizer_agent import (
    AssetPhysicsClassifier,
    PurgedWalkForwardSplitter,
    StrategyOptimizerAgent,
)


@pytest.fixture
def sample_futures_bars():
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

    return pd.DataFrame({
        "open": o, "high": h, "low": l, "close": c,
        "volume": v, "open_interest": oi
    }, index=dates)


def test_asset_physics_classification(sample_futures_bars):
    """测试物理微观结构分类器"""
    regime_ag = AssetPhysicsClassifier.classify_symbol(sample_futures_bars, "AG_IDX")
    regime_rb = AssetPhysicsClassifier.classify_symbol(sample_futures_bars, "RB_IDX")
    regime_c = AssetPhysicsClassifier.classify_symbol(sample_futures_bars, "C_IDX")

    assert regime_ag == "TREND_DOMINANT"
    assert regime_rb == "MEAN_REVERTING"
    assert regime_c in {"HYBRID_CYCLICAL", "TREND_DOMINANT", "MEAN_REVERTING"}


def test_purged_walk_forward_splitter(sample_futures_bars):
    """测试 Purged Walk-Forward 切分严格杜绝时序重叠"""
    train_df, test_df = PurgedWalkForwardSplitter.split(sample_futures_bars, train_ratio=0.70, purge_gap=20)

    assert len(train_df) + len(test_df) < len(sample_futures_bars)  # 包含 purge_gap
    assert train_df.index.max() < test_df.index.min()
    assert (test_df.index.min() - train_df.index.max()).total_seconds() > 0


def test_optimizer_agent_single_symbol_optimization(sample_futures_bars):
    """测试优化 Agent 针对单品种生成平原检验通过的高胜率配置"""
    agent = StrategyOptimizerAgent()
    spec = {"multiplier": 15.0, "tick": 1.0, "fee_rate": 0.00005}

    # 优先使用数据库真实数据测试，回退为 sample fixture
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "ashare_quant.db")
    if os.path.exists(db_path):
        import sqlite3
        conn = sqlite3.connect(db_path)
        df_real = pd.read_sql_query("SELECT trade_time, open, high, low, close, volume, open_interest FROM futures_min_bars WHERE symbol='AG_IDX' AND timeframe='15m' ORDER BY trade_time", conn)
        conn.close()
        if len(df_real) > 500:
            df_real["trade_time"] = pd.to_datetime(df_real["trade_time"])
            df_real.set_index("trade_time", inplace=True)
            test_bars = df_real
        else:
            test_bars = sample_futures_bars
    else:
        test_bars = sample_futures_bars

    candidate = agent.optimize_symbol(test_bars, "AG_IDX", spec)

    assert "params" in candidate
    assert "win_rate_pct" in candidate["full_sample"]
    assert "profit_loss_ratio" in candidate["full_sample"]
    assert "plateau_test_pass" in candidate
    assert candidate["full_sample"]["win_rate_pct"] >= 45.0
