"""
tests/test_tianquan_strategy.py — 「天权·极值条件相变反转策略」因果性与对抗鲁棒性单元测试集
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STRATEGIES_DIR = PROJECT_ROOT / "strategies"
if str(STRATEGIES_DIR) not in sys.path:
    sys.path.insert(0, str(STRATEGIES_DIR))

import tianquan_extreme_phase_reversal as tianquan


def generate_synthetic_ohlcv(n_bars: int = 300, seed: int = 42) -> pd.DataFrame:
    """生成具备真实波动特性的模拟 OHLCV 数据"""
    np.random.seed(seed)
    base_price = 1000.0
    returns = np.random.normal(0.0002, 0.01, n_bars)
    if n_bars > 110:
        returns[100:105] = -0.025
    if n_bars > 210:
        returns[200:205] = 0.025

    close = base_price * np.cumprod(1.0 + returns)
    high = close * (1.0 + np.abs(np.random.normal(0.002, 0.005, n_bars)))
    low = close * (1.0 - np.abs(np.random.normal(0.002, 0.005, n_bars)))
    open_ = np.roll(close, 1)
    open_[0] = base_price

    if n_bars > 110:
        # 针对第 105 根 Bar 构造探底长下影阳线 (Bullish Absorption)
        close[105] = open_[105] + 5.0
        low[105] = open_[105] - 30.0
        high[105] = close[105] + 2.0

    if n_bars > 210:
        # 针对第 205 根 Bar 构造冲顶长上影阴线 (Bearish Absorption)
        close[205] = open_[205] - 5.0
        high[205] = open_[205] + 30.0
        low[205] = close[205] - 2.0

    volume = np.random.uniform(500, 2000, n_bars)
    open_interest = 50000 + np.cumsum(np.random.normal(0, 50, n_bars))

    df = pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "open_interest": open_interest,
    }, index=pd.date_range("2026-01-01", periods=n_bars, freq="15min"))
    return df


def test_metadata_and_interfaces():
    """验证模块接口与元数据规范"""
    assert tianquan.STRATEGY_NAME == "tianquan_extreme_phase_reversal"
    assert "天权" in tianquan.STRATEGY_DESCRIPTION
    assert hasattr(tianquan, "calculate_signal")
    assert hasattr(tianquan, "calculate_factors")


def test_factors_integrity():
    """验证因子输出完整性与数值健壮性"""
    df = generate_synthetic_ohlcv(200)
    factors = tianquan.calculate_factors(df)
    assert len(factors) == len(df)
    expected_cols = [
        "atr", "filt_fast", "filt_slow", "trend_up", "trend_dn",
        "hurst", "zscore", "rsi_2", "extreme_oversold_band",
        "extreme_overbought_band", "bullish_absorption", "bearish_absorption",
        "oi_filter_long", "oi_filter_short", "vol_ma20"
    ]
    for col in expected_cols:
        assert col in factors.columns, f"Missing factor column: {col}"
    # 验证后半段因果计算无 NaN 和 Inf
    assert not factors.iloc[30:]["zscore"].isna().any()
    assert np.isfinite(factors.iloc[30:]["zscore"].values).all()


def test_prefix_invariance_attack():
    """
    核心前缀不变性对抗攻击 (Prefix Invariance Attack):
    向序列追加数据或截断尾部，历史任何时刻的信号必须 100% 保持不变，证明绝无未来函数或前瞻偏差。
    """
    df_full = generate_synthetic_ohlcv(250)
    sig_full = tianquan.calculate_signal(df_full)

    for cutoff in (120, 180, 220):
        df_sub = df_full.iloc[:cutoff].copy()
        sig_sub = tianquan.calculate_signal(df_sub)
        # 前 cutoff 根 K 线的信号必须逐元素完全相等
        np.testing.assert_array_equal(
            sig_sub.values,
            sig_full.iloc[:cutoff].values,
            err_msg=f"Prefix invariance failed at cutoff={cutoff}!"
        )


def test_open_interest_veto():
    """
    验证持仓量衰竭门禁 (OI Filter):
    当持仓量爆发逼仓时，严禁逆势摸顶抄底，必须一票否决信号。
    """
    df = generate_synthetic_ohlcv(150)
    # 正常状态下的信号
    sig_normal = tianquan.calculate_signal(df)

    # 模拟在超卖点 105 出现持仓量暴增 10,000 手 (强力逼仓)
    df_spiked = df.copy()
    df_spiked.loc[df_spiked.index[105], "open_interest"] = df_spiked.loc[df_spiked.index[104], "open_interest"] + 15000.0

    sig_spiked = tianquan.calculate_signal(df_spiked)

    # 在持仓暴增点，多头反转信号必须被强制压制为 0
    factors_spiked = tianquan.calculate_factors(df_spiked)
    assert not factors_spiked.loc[df_spiked.index[105], "oi_filter_long"]
    assert sig_spiked.iloc[105] == 0


def test_cooldown_mechanism():
    """验证动态冷却窗口 (Cooldown)，杜绝连续信号同向轰炸"""
    df = generate_synthetic_ohlcv(150)
    signals = tianquan.calculate_signal(df, cooldown_bars=6)

    # 检查任意非零信号之间，同向信号距离必须 >= 6
    active_indices = np.where(signals.values != 0)[0]
    for i in range(1, len(active_indices)):
        prev_idx = active_indices[i - 1]
        curr_idx = active_indices[i]
        if signals.iloc[curr_idx] == signals.iloc[prev_idx]:
            assert curr_idx - prev_idx >= 6, (
                f"Cooldown violation: signal {signals.iloc[curr_idx]} at {curr_idx} "
                f"fired only {curr_idx - prev_idx} bars after previous at {prev_idx}"
            )


if __name__ == "__main__":
    print("Running Tianquan Strategy Self-Checks...")
    test_metadata_and_interfaces()
    print("✓ test_metadata_and_interfaces passed")
    test_factors_integrity()
    print("✓ test_factors_integrity passed")
    test_prefix_invariance_attack()
    print("✓ test_prefix_invariance_attack passed")
    test_open_interest_veto()
    print("✓ test_open_interest_veto passed")
    test_cooldown_mechanism()
    print("✓ test_cooldown_mechanism passed")
    print("ALL TIANQUAN TESTS PASSED SUCCESSFULLY!")

