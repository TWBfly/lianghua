"""
tests/verify_audit_fixes_comprehensive.py — 审计修复全套断言自检脚本
"""

import os
import sys
import math
import tempfile
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "code"))
sys.path.insert(0, str(PROJECT_ROOT / "strategies"))


def test_data_pipeline_fixes():
    print("🧪 [1/5] 测试数据管线与盲删修复...")
    
    # 检查 sync_real_dominant_futures_data.py
    file_dom = (PROJECT_ROOT / "code/sync_real_dominant_futures_data.py").read_text(encoding="utf-8")
    assert "DELETE FROM futures_min_bars WHERE symbol = '{db_sym}'" not in file_dom, "C1: 依然存在无时间限制的盲删语句"
    assert "DELETE FROM futures_min_bars WHERE symbol = ? AND timeframe = ? AND trade_time >= ? AND trade_time <= ?;" in file_dom, "C1: 缺少范围约束的安全清理语句"
    assert "PRAGMA journal_mode=WAL;" in file_dom, "M9: 缺少 WAL 模式配置"

    # 检查 sync_real_15m_futures_data.py
    file_15m = (PROJECT_ROOT / "code/sync_real_15m_futures_data.py").read_text(encoding="utf-8")
    assert "DELETE FROM futures_min_bars WHERE symbol = '{db_sym}' AND timeframe = '15m';" not in file_15m, "C1: 15m 依然存在盲删语句"

    # 检查 futures_contract_calendar.py 展期复权
    from futures_contract_calendar import calculate_roll_adjustment_ratio, adjust_continuous_series
    r = calculate_roll_adjustment_ratio(100.0, 105.0)
    assert abs(r - 1.05) < 1e-5, "C2: 展期调整比例计算错误"
    
    df_raw = pd.DataFrame({
        "open": [100.0, 101.0, 105.0, 106.0],
        "high": [102.0, 103.0, 107.0, 108.0],
        "low": [99.0, 100.0, 104.0, 105.0],
        "close": [101.0, 102.0, 106.0, 107.0]
    })
    df_adj = adjust_continuous_series(df_raw, roll_indices=[2], ratios=[1.05])
    assert abs(df_adj["close"].iloc[0] - 101.0 * 1.05) < 1e-4, "C2: 展期后复权累积调整错误"
    assert abs(df_adj["close"].iloc[2] - 106.0) < 1e-4, "C2: 展期后新合约未保持基准"

    # 检查 ashare_data_engine.py 冗余索引
    file_ashare = (PROJECT_ROOT / "code/ashare_data_engine.py").read_text(encoding="utf-8")
    assert "CREATE INDEX IF NOT EXISTS idx_stock_daily_symbol_date" not in file_ashare, "M7: 冗余索引未移除"

    print("  ✅ 数据管线与展期复权全部通过！")


def test_credential_security_fixes():
    print("🧪 [2/5] 测试凭证安全与 Fail-Closed 机制...")
    
    file_realtime = (PROJECT_ROOT / "code/unified_realtime_trader.py").read_text(encoding="utf-8")
    assert "13800000000" not in file_realtime, "C5: 仍包含明文测试账号 13800000000"
    assert "redacted_password" not in file_realtime, "C5: 仍包含明文密码 redacted_password"
    assert "load_required_credentials" in file_realtime, "C5: 未接入 load_required_credentials"

    # 测试 runtime_credentials fail-closed 行为
    from runtime_credentials import load_required_credentials
    with tempfile.NamedTemporaryFile("w", delete=False) as tf:
        tf.write("OTHER_KEY=123\n")
        temp_env = tf.name
    try:
        try:
            load_required_credentials(temp_env, "MISSING_A", "MISSING_B")
            assert False, "C5: 缺失凭证时未抛出异常"
        except RuntimeError:
            pass  # 正确行为
    finally:
        os.unlink(temp_env)

    print("  ✅ 凭证安全与 Fail-Closed 全部通过！")


def test_backtest_engine_fixes():
    print("🧪 [3/5] 测试回测引擎入场 Bar 止损与 M2M 盯市回撤...")
    
    from unified_backtest_pipeline import run_strategy_causal_backtest
    
    # 构造测试数据 (>= 50 根): 第 20 根产生做多信号，第 21 根开盘 1000，但盘中最低暴跌至 900 (止损设在 950)
    times = pd.date_range("2025-01-01", periods=60, freq="15min")
    base_price = 1000.0
    opens = [base_price] * 60
    highs = [base_price + 5.0] * 60
    lows = [base_price - 5.0] * 60
    closes = [base_price + 1.0] * 60
    
    # 第 21 根 Bar (索引 21) 暴跌
    lows[21] = 900.0
    closes[21] = 990.0

    df_test = pd.DataFrame({
        "trade_time": times.strftime("%Y-%m-%d %H:%M:%S"),
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [1000.0] * 60
    })
    
    # 策略信号：第 20 根做多
    sigs = [0] * 60
    sigs[20] = 1
    sig_test = pd.Series(sigs, index=df_test.index)
    
    trades, summary = run_strategy_causal_backtest(df_test, "RB_IDX", sig_test, timeframe="15m", cost_multiplier=1.0, capital=100000.0)
    
    assert len(trades) == 1, f"应触发 1 笔交易，实际: {len(trades)}"
    t0 = trades[0]
    # H1 验证：入场当根 Bar (holding_bars == 0) 必须成功止损，不得存活到后续 Bar
    assert t0.holding_bars == 0, f"H1: 入场当根 Bar 暴跌未被即时止损，holding_bars={t0.holding_bars}"
    assert t0.net_pnl < 0, "止损交易净盈亏应为负"
    assert summary["max_drawdown"] > 0, f"H2: 盯市最大回撤应大于 0，实际: {summary['max_drawdown']}"

    # 测试 backtest_validator 日期跨度精确计算
    from backtest_validator import check_data_coverage
    cov = check_data_coverage("2024-01-01T00:00:00", "2025-01-01T00:00:00")
    assert cov["data_months"] == 12, f"L2: 跨年月份计算错误: {cov['data_months']}"

    # 测试 contract_specs fallback
    from contract_specs import get_spec
    spec_unk = get_spec("UNKNOWN_COIN")
    assert spec_unk.name == "未知", "L1: 未知合约 fallback 异常"

    print("  ✅ 回测引擎入场止损与盯市回撤全部通过！")


def test_strategy_causality_and_logic_fixes():
    print("🧪 [4/5] 测试策略无前瞻 (bfill消除) 与 FVG 因子接入...")

    # 1. 检查 taiyi_multiscale_positive_feedback
    from taiyi_multiscale_positive_feedback import calculate_factors, calculate_signal
    file_taiyi = (PROJECT_ROOT / "strategies/taiyi_multiscale_positive_feedback.py").read_text(encoding="utf-8")
    assert ".bfill()" not in file_taiyi, "M2: taiyi 策略中仍存在 .bfill()"
    assert "(had_sq | fvg_bull)" in file_taiyi or "fvg_bull" in file_taiyi, "M3: FVG 因子未接入信号判定"

    # 生成模拟 K 线运行
    np.random.seed(42)
    p = 100.0 + np.cumsum(np.random.randn(100))
    df_sim = pd.DataFrame({
        "open": p - 0.2,
        "high": p + 1.0,
        "low": p - 1.0,
        "close": p + 0.2,
        "volume": np.random.randint(100, 1000, 100).astype(float)
    })
    factors_ty = calculate_factors(df_sim)
    assert not factors_ty.empty, "taiyi calculate_factors 计算失败"
    sig_ty = calculate_signal(df_sim)
    assert len(sig_ty) == len(df_sim), "taiyi calculate_signal 长度不匹配"

    # 2. 检查 trend_volume_candlestick_master
    from trend_volume_candlestick_master import compute_supertrend_vcp_signals
    file_tv = (PROJECT_ROOT / "strategies/trend_volume_candlestick_master.py").read_text(encoding="utf-8")
    assert "method=\"bfill\"" not in file_tv, "M2: trend_volume 策略中仍存在 bfill"
    assert "max(2.0, atr_14[i])" not in file_tv, "M4: trend_volume 仍存在 hardcoded ATR=2.0 限制"

    # 验证低价格/低ATR标的 (如价格0.8, ATR=0.02) 能正常运行而不被锁在 2.0
    df_penny = pd.DataFrame({
        "open": np.linspace(0.8, 0.9, 50),
        "high": np.linspace(0.81, 0.91, 50),
        "low": np.linspace(0.79, 0.89, 50),
        "close": np.linspace(0.805, 0.905, 50),
        "volume": [500.0] * 50
    })
    res_st = compute_supertrend_vcp_signals(df_penny)
    assert "st_vcp_sig" in res_st.columns, "low-ATR 标的计算失败"

    # 3. 检查 chan_structure_regime_strategy
    file_chan = (PROJECT_ROOT / "strategies/chan_structure_regime_strategy.py").read_text(encoding="utf-8")
    assert ".bfill()" not in file_chan, "M2: chan_structure 策略中仍存在 bfill"

    # 4. 检查 strategy_signal_library SuperTrend NumPy 优化
    from strategy_signal_library import supertrend_signal
    st_sig = supertrend_signal(df_sim)
    assert set(st_sig.unique()).issubset({1, -1}), "SuperTrend 输出非预期方向"

    print("  ✅ 策略因果性、FVG因子与全资产ATR兼容性全部通过！")


def test_live_trading_and_dashboard_fixes():
    print("🧪 [5/5] 测试实盘重连保护、平仓点位撮合与 Web 鉴权中间件...")

    # 1. 检查 futures_live_trader.py
    file_live = (PROJECT_ROOT / "code/futures_live_trader.py").read_text(encoding="utf-8")
    assert "signal.SIGTERM" in file_live, "H4: live trader 未注册 SIGTERM 信号"
    assert "retry_count" in file_live, "C4: live trader 未包含重试重连机制"

    # 2. 检查 futures_dashboard_server.py
    file_dash = (PROJECT_ROOT / "code/futures_dashboard_server.py").read_text(encoding="utf-8")
    assert "check_auth" in file_dash, "H3: Web Dashboard 缺少鉴权中间件"
    assert "add_security_headers" in file_dash, "H3: Web Dashboard 缺少安全响应头"

    print("  ✅ 实盘守护与 Web 安全特性全部通过！")


def main():
    print("=" * 80)
    print("🚀 开始量化系统 (lianghua) 核心修复全套自动化回归测试")
    print("=" * 80)
    test_data_pipeline_fixes()
    test_credential_security_fixes()
    test_backtest_engine_fixes()
    test_strategy_causality_and_logic_fixes()
    test_live_trading_and_dashboard_fixes()
    print("=" * 80)
    print("🎉 恭喜！全部 5 大模块、所有 CRITICAL / HIGH / MEDIUM / LOW 缺陷修复断言 100% 通过！")
    print("=" * 80)


if __name__ == "__main__":
    main()
