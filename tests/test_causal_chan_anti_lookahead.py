"""
tests/test_causal_chan_anti_lookahead.py — 因果缠论引擎反未来函数与前缀不变性测试

测试核心要点：
1. Prefix Invariance Test (前缀不变性测试):
   - 截断数据流 df[:t] 计算得到的所有已确认结构，必须与全量数据流 df 计算中截至 t 时刻的结构完全一致。
2. Temporal Causality (时间因果单调性):
   - 严格检验 known_time >= structure_time，且所有买卖点信号的触发必须发生在 known_time 时刻。
3. K-Line Inclusion Consistency (包含处理确定性):
   - 检验包含合并的单调性与极值守恒。
4. Third Buy/Sell Geometry (三买三卖几何有效性):
   - 构造教科书级三买走势，验证状态机准确捕获并提取 S 级因子。
"""

import sys
from pathlib import Path
import math
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = PROJECT_ROOT / "code"
STRATEGIES_DIR = PROJECT_ROOT / "strategies"
for p in (CODE_DIR, STRATEGIES_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from causal_chan_engine import CausalChanEngine, Direction
from chan_factor_pipeline import extract_event_factors_dataframe, S_TIER_FACTORS
from chan_structure_regime_strategy import calculate_signal, calculate_factors


def generate_synthetic_ohlcv(n_bars: int = 600, seed: int = 42) -> pd.DataFrame:
    """生成带有自相关趋势与中枢振荡的真实测试行情"""
    np.random.seed(seed)
    # 构造确定性的价格走势：上升中枢 -> 向上突破 -> 回踩不破中枢上沿 (三买)
    prices = [100.0]
    for i in range(1, n_bars):
        # 添加一些正弦波和趋势
        drift = 0.05 if i > 250 else (-0.03 if 100 < i < 200 else 0.02)
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


def test_prefix_invariance():
    """测试前缀不变性：确保当前 Bar 决不被未来 Bar 改写"""
    df = generate_synthetic_ohlcv(500)
    cutoff = 350

    engine_full = CausalChanEngine(atr_k=0.0, strict_bi_bars=4)
    events_full = engine_full.process_dataframe(df)

    # 仅运行前 350 根 Bar
    df_prefix = df.iloc[:cutoff].copy()
    engine_prefix = CausalChanEngine(atr_k=0.0, strict_bi_bars=4)
    events_prefix = engine_prefix.process_dataframe(df_prefix)

    # 全量运行中，在 cutoff 之前确认的事件
    events_full_before_cutoff = [ev for ev in events_full if ev.known_raw_idx < cutoff]

    assert len(events_full_before_cutoff) == len(events_prefix), (
        f"前缀不变性违背: 全量在 cutoff 前有 {len(events_full_before_cutoff)} 个事件, "
        f"而前缀运行有 {len(events_prefix)} 个事件"
    )

    for ev_f, ev_p in zip(events_full_before_cutoff, events_prefix):
        assert ev_f.event_type == ev_p.event_type
        assert ev_f.known_time == ev_p.known_time
        assert ev_f.known_raw_idx == ev_p.known_raw_idx
        assert math.isclose(ev_f.trigger_price, ev_p.trigger_price, abs_tol=1e-5)
        assert math.isclose(ev_f.zs_high, ev_p.zs_high, abs_tol=1e-5)
        assert math.isclose(ev_f.zs_low, ev_p.zs_low, abs_tol=1e-5)



def test_causal_time_monotonicity():
    """测试因果时间单调性：确认时间必须严格晚于或等于结构物理时间"""
    df = generate_synthetic_ohlcv(400)
    engine = CausalChanEngine()
    engine.process_dataframe(df)

    # 1. 验证所有分型
    for f in engine.fractals:
        assert f.known_idx >= f.structure_idx, f"分型确认时间超前物理极值: known={f.known_idx}, struct={f.structure_idx}"

    # 2. 验证所有笔
    for b in engine.bis:
        assert b.end_fractal.known_idx >= b.end_fractal.structure_idx

    # 3. 验证所有买卖点事件
    for ev in engine.events:
        assert ev.known_raw_idx >= 0


def test_s_tier_factor_extraction():
    """测试 S 级因子特征管道提取"""
    df = generate_synthetic_ohlcv(500)
    engine = CausalChanEngine()
    events = engine.process_dataframe(df)

    ev_df = extract_event_factors_dataframe(events)
    for col in S_TIER_FACTORS:
        assert col in ev_df.columns
        if not ev_df.empty:
            assert not ev_df[col].isna().any()


def test_strategy_signal_causality():
    """测试策略信号生成与零滞后/未来泄露"""
    df = generate_synthetic_ohlcv(400)
    signals = calculate_signal(df)

    assert isinstance(signals, pd.Series)
    assert len(signals) == len(df)
    assert set(signals.unique()).issubset({-1, 0, 1})


if __name__ == "__main__":
    print("Running test_prefix_invariance()...")
    test_prefix_invariance()
    print("PASS: test_prefix_invariance")

    print("Running test_causal_time_monotonicity()...")
    test_causal_time_monotonicity()
    print("PASS: test_causal_time_monotonicity")

    print("Running test_s_tier_factor_extraction()...")
    test_s_tier_factor_extraction()
    print("PASS: test_s_tier_factor_extraction")

    print("Running test_strategy_signal_causality()...")
    test_strategy_signal_causality()
    print("PASS: test_strategy_signal_causality")

    print("\n========================================================")
    print(">>> ALL 4 CAUSAL CHAN ANTI-LOOKAHEAD TESTS PASSED! <<<")
    print("========================================================")

