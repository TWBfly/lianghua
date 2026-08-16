"""
Unit tests for Decoupled 1-Minute ML+PPO Futures Strategy Engine
【1分钟期货专属机器学习 + 微观 PPO 策略引擎与回测验证测试】
"""

import pytest
import numpy as np
import pandas as pd
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "code"))

from symbol_strategies.decoupled_1m_symbol_engines import (
    MicroPPOExecutionAgent,
    SYMBOL_1M_CONFIGS,
    Decoupled1mSymbolStrategyRunner
)


def test_symbol_1m_configs_integrity():
    """验证 25 大品种 1m 独立配置表的完整性与字段合规性"""
    assert len(SYMBOL_1M_CONFIGS) == 25, f"预期 25 个品种配置，实际得到 {len(SYMBOL_1M_CONFIGS)}"

    required_keys = [
        "name", "category", "multiplier", "margin", "tick_size",
        "prob_thresh", "target_atr", "sl_atr", "be_atr", "trail_atr",
        "max_lots", "max_holding_bars", "fee_rate", "feature_set"
    ]
    for sym, cfg in SYMBOL_1M_CONFIGS.items():
        for k in required_keys:
            assert k in cfg, f"品种 {sym} 缺少配置字段 {k}"
        assert cfg["multiplier"] > 0
        assert 0 < cfg["margin"] < 1.0
        assert cfg["prob_thresh"] >= 0.20
        assert cfg["target_atr"] > cfg["sl_atr"], f"{sym} 的止盈 ATR 必须大于止损 ATR"


def test_micro_ppo_agent_actions():
    """验证微观 PPO 执行智能体的动作转移逻辑"""
    agent = MicroPPOExecutionAgent()
    dummy_state = np.zeros(7)

    # 1. 正常波动，未触及保本与止损 -> HOLD (0)
    act = agent.select_action(dummy_state, pnl_atrs=0.5, be_thr=1.4, trail_thr=3.2, holding_bars=10, max_holding_bars=35)
    assert act == 0

    # 2. 达到保本阈值 -> TIGHTEN_STOP (1)
    act = agent.select_action(dummy_state, pnl_atrs=1.5, be_thr=1.4, trail_thr=3.2, holding_bars=10, max_holding_bars=35)
    assert act == 1

    # 3. 达到吊灯锁利阈值 -> LOCK_PROFIT_HALF (2)
    act = agent.select_action(dummy_state, pnl_atrs=3.5, be_thr=1.4, trail_thr=3.2, holding_bars=10, max_holding_bars=35)
    assert act == 2

    # 4. 触及硬止损边界 -> EXIT_IMMEDIATELY (3)
    act = agent.select_action(dummy_state, pnl_atrs=-1.1, be_thr=1.4, trail_thr=3.2, holding_bars=10, max_holding_bars=35)
    assert act == 3

    # 5. 超过最大持仓时间且无显著浮盈 -> 时间衰减 EXIT (3)
    act = agent.select_action(dummy_state, pnl_atrs=0.2, be_thr=1.4, trail_thr=3.2, holding_bars=36, max_holding_bars=35)
    assert act == 3


def test_feature_engineering_causality():
    """验证 1m 微观特征计算与 5m 宏观护城河的绝对因果性与零前瞻"""
    runner = Decoupled1mSymbolStrategyRunner()

    # 构造合规微观行情
    dates = pd.date_range("2026-08-01 09:00:00", periods=200, freq="1min")
    df_fake = pd.DataFrame({
        "datetime": dates,
        "open": np.linspace(100, 110, 200) + np.random.randn(200) * 0.1,
        "high": np.linspace(100.5, 110.5, 200) + np.random.randn(200) * 0.1,
        "low": np.linspace(99.5, 109.5, 200) + np.random.randn(200) * 0.1,
        "close": np.linspace(100, 110, 200) + np.random.randn(200) * 0.1,
        "volume": np.random.randint(100, 500, size=200),
        "open_interest": np.random.randint(10000, 20000, size=200)
    })

    cfg = SYMBOL_1M_CONFIGS["AG_IDX"]
    df_feat = runner.compute_1m_features_and_labels(df_fake, cfg)

    assert "micro_squeeze" in df_feat.columns
    assert "micro_accel" in df_feat.columns
    assert "vol_burst" in df_feat.columns
    assert "macro_trend_5m" in df_feat.columns
    assert "label_long" in df_feat.columns
    assert "label_short" in df_feat.columns

    # 验证 macro_trend_5m 的初始行不存在未来数据渗透
    assert df_feat["macro_trend_5m"].iloc[0] == 0


def test_1m_single_symbol_backtest_execution():
    """针对实际落盘的 AG_IDX 1 分钟真实数据运行一次完整回测校验"""
    runner = Decoupled1mSymbolStrategyRunner()
    res = runner.run_single_symbol_1m_backtest("AG_IDX")

    assert res["symbol"] == "AG_IDX"
    assert "win_rate" in res
    assert "profit_factor" in res
    assert "sharpe_ratio" in res
    assert "max_drawdown_pct" in res
    assert "total_pnl" in res
    assert isinstance(res["trades"], list)
