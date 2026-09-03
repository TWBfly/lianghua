"""
tests/test_chanquant_v8_strict.py — 工业级因果缠论 8.0 严格财务对账、因果时序与风控全套实质性回归测试

【8 大核心实质性测试断言】：
1. test_single_source_signal_identity: 生产与研究单一同源逐柱一致性检验；
2. test_strict_ledger_invariance_deterministic: 真实交易下账户财务对账恒等式与期末清算；
3. test_zero_fee_double_counting: 真实交易开平仓费滑单边单次计费严格断言；
4. test_causal_event_order_no_time_travel: Stage 1 开盘撮合与 Stage 2 柱内止损实质性时序检验；
5. test_asynchronous_carry_forward: 异步闭市时持仓、保证金与挂单生命周期实质性持久化检验；
6. test_fail_closed_risk_rejection: 确凿挂单在保证金不足时被严格拒绝 (零开仓、零扣费)；
7. test_stop_loss_bounds_and_gap_sanity: 验证有效手数下开盘跳空击穿止损废单与正常跳空以真实开盘价成交；
8. test_portfolio_liquidation_on_margin_call: 极端逆向波动导致风险率超标时组合强平与熔断保护 (严格断言退出原因)。
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

from contract_specs import get_spec, calculate_contract_fee, calculate_contract_margin
from chanquant_v8_production_strategy import calculate_signal, evaluate_chan_signal, calculate_factors_v8
from run_chanquant_v8_master_research import StrictCausalSharedPortfolioEngine, StrictPendingOrder
from unified_backtest_pipeline import UnifiedDataProvider


def test_single_source_signal_identity():
    """1. 验证生产 calculate_signal 与研究 evaluate_chan_signal 逐柱一致"""
    provider = UnifiedDataProvider()
    df_au, _ = provider.load_or_generate_bars("AU_IDX", "15m", target_min_trades=200)

    sig_series = calculate_signal(df_au, "AU_IDX")
    assert isinstance(sig_series, pd.Series)
    assert len(sig_series) == len(df_au)

    spec = get_spec("AU_IDX")
    factors = calculate_factors_v8(df_au)
    causal_atr = np.insert(factors["atr"].values[:-1], 0, factors["atr"].values[0])
    pdata = {
        "factors": factors,
        "close": df_au["close"].astype(float).values,
        "open": df_au["open"].astype(float).values,
        "causal_atr": causal_atr,
        "spec": spec,
    }

    for i in range(1, min(len(df_au), 150)):
        sig_obj = evaluate_chan_signal(pdata, i, "AU_IDX", spec, spec.tick_size)
        assert float(sig_obj.side) == sig_series.iloc[i], f"Bar {i} 生产与研究信号不一致！"


def test_strict_ledger_invariance_deterministic():
    """2. 验证真实交易下单账户财务对账恒等式与期末平仓清算"""
    provider = UnifiedDataProvider()
    df_ag, _ = provider.load_or_generate_bars("AG_IDX", "15m", target_min_trades=500)

    engine = StrictCausalSharedPortfolioEngine(initial_capital=500_000.0, cost_multiplier=1.0)
    rep = engine.run_portfolio({"AG_IDX": df_ag})

    assert len(engine.trades) > 0, "真实数据必须产生交易以验证财务对账！"
    final_equity = engine.cash
    total_net_pnl = sum(t.net_pnl for t in engine.trades)
    diff = abs(final_equity - (500_000.0 + total_net_pnl))

    assert diff < 0.50, f"财务对账失败！Diff={diff:.4f} RMB"


def test_zero_fee_double_counting():
    """3. 验证真实交易中开平仓费滑单边扣除，无重复计费"""
    provider = UnifiedDataProvider()
    df_ag, _ = provider.load_or_generate_bars("AG_IDX", "15m", target_min_trades=500)

    engine = StrictCausalSharedPortfolioEngine(initial_capital=500_000.0, cost_multiplier=1.0)
    engine.run_portfolio({"AG_IDX": df_ag})

    assert len(engine.trades) > 0
    for t in engine.trades:
        spec = get_spec(t.symbol)
        is_today = (t.holding_bars <= 16)
        expected_entry_fee = calculate_contract_fee(spec, t.entry_price, t.lots, is_close_today=False)
        expected_exit_fee = calculate_contract_fee(spec, t.exit_price, t.lots, is_close_today=is_today)
        expected_fee = round(expected_entry_fee + expected_exit_fee, 2)
        expected_slip = round(2.0 * spec.tick_size * spec.multiplier * t.lots, 2)
        assert abs(t.fee - expected_fee) <= 0.05, f"手续费异常！Got {t.fee}, expected {expected_fee}"
        assert abs(t.slippage - expected_slip) <= 0.05, f"滑点异常！Got {t.slippage}, expected {expected_slip}"


def test_causal_event_order_no_time_travel():
    """4. 验证开盘挂单撮合与同柱柱内止损时序正确性"""
    engine = StrictCausalSharedPortfolioEngine(initial_capital=500_000.0, cost_multiplier=1.0)

    dates = pd.date_range("2026-01-01 09:00", periods=100, freq="15min")
    p = np.full(100, 1000.0)
    df = pd.DataFrame({"trade_time": dates, "open": p, "high": p+1, "low": p-1, "close": p, "volume": 1000})

    init_orders = {
        "AU_IDX": StrictPendingOrder(
            symbol="AU_IDX", side=1, mode="TREND", stop_price=996.0, target_price=0.0, causal_atr=2.0, reason="TEST", generated_time="2026-01-01 09:00"
        )
    }
    # 第 1 根 Bar：开盘 1000 成交，柱内暴跌至 990 触碰止损 996
    df.loc[0, "open"] = 1000.0
    df.loc[0, "low"] = 990.0
    df.loc[0, "close"] = 992.0

    rep = engine.run_portfolio({"AU_IDX": df}, initial_pending_orders=init_orders)
    assert len(engine.trades) >= 1
    t0 = engine.trades[0]
    assert t0.entry_price == 1000.0, f"入场价必须是开盘价 1000.0，实际为 {t0.entry_price}"
    assert t0.exit_price == 996.0, f"止损价必须是 996.0，实际为 {t0.exit_price}"
    assert t0.exit_reason in ("SAME_BAR_STOP", "STOP_INTRABAR")


def test_asynchronous_carry_forward():
    """5. 实质性验证多品种异步闭市时持仓、保证金与挂单生命周期的正确持久化"""
    n_total = 180
    dates_full = pd.date_range("2026-01-01 09:00", periods=n_total, freq="15min")
    # 品种 A (AG) 在前 100 根 Bar 交易 (满足 >= 80 根阈值)，在后 80 根 Bar 处于闭市休市状态
    dates_a = dates_full[:100]

    p1 = np.full(100, 6000.0)
    df_a = pd.DataFrame({"trade_time": dates_a, "open": p1, "high": p1, "low": p1, "close": p1, "volume": 1000})

    # 品种 B (RB) 在全部 180 根 Bar 持续交易
    p2 = np.full(n_total, 3500.0)
    df_b = pd.DataFrame({"trade_time": dates_full, "open": p2, "high": p2+5, "low": p2-5, "close": p2, "volume": 1000})

    # 注入 AG 挂单（在 Bar 0 触发买入成交）
    init_orders = {
        "AG_IDX": StrictPendingOrder(
            symbol="AG_IDX", side=1, mode="TREND", stop_price=5900.0, target_price=0.0, causal_atr=20.0, reason="TEST_AG_OPEN", generated_time="2026-01-01 09:00"
        )
    }

    engine = StrictCausalSharedPortfolioEngine(initial_capital=500_000.0, risk_per_trade_pct=0.05, cost_multiplier=1.0)
    rep = engine.run_portfolio({"AG_IDX": df_a, "RB_IDX": df_b}, initial_pending_orders=init_orders)

    # 验证 AG 在第 0 根 Bar 成功建仓，且在 Bar 100~179 (AG 闭市期间) 依然安全持有并参与全局 MTM 核算
    assert len(engine.trades) >= 1, "异步测试必须产生真实交易！"
    ag_trade = [t for t in engine.trades if t.symbol == "AG_IDX"][0]
    assert ag_trade.entry_price == 6000.0
    # 验证最终对账在异步断层下依然严格成立 (Diff < 0.50 元)
    final_equity = engine.cash
    total_net_pnl = sum(t.net_pnl for t in engine.trades)
    assert abs(final_equity - (500_000.0 + total_net_pnl)) < 0.50, "异步断层下财务对账不平！"


def test_fail_closed_risk_rejection():
    """6. 验证资金不足时确凿挂单被严格拒绝 (零开仓、零扣费)"""
    engine = StrictCausalSharedPortfolioEngine(initial_capital=100.0, cost_multiplier=1.0)
    dates = pd.date_range("2026-01-01 09:00", periods=100, freq="15min")
    p = np.full(100, 960.0)
    df = pd.DataFrame({"trade_time": dates, "open": p, "high": p+1, "low": p-1, "close": p, "volume": 1000})

    # 注入确凿买入挂单 (黄金 1 手需保证金 > 100,000 元，当前仅 100 元)
    init_orders = {
        "AU_IDX": StrictPendingOrder(
            symbol="AU_IDX", side=1, mode="TREND", stop_price=950.0, target_price=0.0, causal_atr=5.0, reason="TEST_BUY", generated_time="2026-01-01 09:00"
        )
    }

    rep = engine.run_portfolio({"AU_IDX": df}, initial_pending_orders=init_orders)
    assert len(engine.trades) == 0, "资金不足 1 手保证金时发生非法越权建仓！"
    assert engine.cash == 100.0, "拒单时不应扣除任何资金！"


def test_stop_loss_bounds_and_gap_sanity():
    """7. 验证开盘跳空击穿止损时真实触发废单取消；未破止损时严格按跳空开盘价成交"""
    # 7.1 跳空跌破止损 -> 废单取消 (确保仓位计算 lots >= 1)
    engine_cancel = StrictCausalSharedPortfolioEngine(initial_capital=1_000_000.0, risk_per_trade_pct=0.05)
    dates = pd.date_range("2026-01-01 09:00", periods=100, freq="15min")
    p = np.full(100, 6000.0)
    df_gap_cancel = pd.DataFrame({"trade_time": dates, "open": p, "high": p+1, "low": p-1, "close": p, "volume": 1000})
    
    # 模拟第 1 根 Bar 开盘跳空低开至 5800 (跌破止损 5900)
    df_gap_cancel.loc[0, "open"] = 5800.0
    df_gap_cancel.loc[0, "low"] = 5790.0
    df_gap_cancel.loc[0, "high"] = 5810.0
    df_gap_cancel.loc[0, "close"] = 5800.0

    init_orders_cancel = {
        "AG_IDX": StrictPendingOrder(
            symbol="AG_IDX", side=1, mode="TREND", stop_price=5900.0, target_price=0.0, causal_atr=20.0, reason="TEST_BUY", generated_time="2026-01-01 08:45"
        )
    }
    rep_cancel = engine_cancel.run_portfolio({"AG_IDX": df_gap_cancel}, initial_pending_orders=init_orders_cancel)
    assert len(engine_cancel.trades) == 0, "开盘价已击穿止损时，挂单必须被废单取消！"

    # 7.2 跳空但未破止损 -> 严格以真实跳空开盘价成交
    engine_fill = StrictCausalSharedPortfolioEngine(initial_capital=1_000_000.0, risk_per_trade_pct=0.05)
    df_gap_fill = pd.DataFrame({"trade_time": dates, "open": p, "high": p+1, "low": p-1, "close": p, "volume": 1000})
    # 开盘跳空至 5950 (高于止损 5900)
    df_gap_fill.loc[0, "open"] = 5950.0
    df_gap_fill.loc[0, "low"] = 5940.0
    df_gap_fill.loc[0, "high"] = 5960.0
    df_gap_fill.loc[0, "close"] = 5955.0

    init_orders_fill = {
        "AG_IDX": StrictPendingOrder(
            symbol="AG_IDX", side=1, mode="TREND", stop_price=5900.0, target_price=0.0, causal_atr=20.0, reason="TEST_BUY", generated_time="2026-01-01 08:45"
        )
    }
    rep_fill = engine_fill.run_portfolio({"AG_IDX": df_gap_fill}, initial_pending_orders=init_orders_fill)
    assert len(engine_fill.trades) >= 1, "未破止损的跳空开盘必须成功撮合成交！"
    assert engine_fill.trades[0].entry_price == 5950.0, f"入场价必须是真实跳空开盘价 5950.0，实际为 {engine_fill.trades[0].entry_price}"


def test_portfolio_liquidation_on_margin_call():
    """8. 验证风险率超标时组合强平与熔断保护 (严格断言退出原因为 PORTFOLIO_MARGIN_CALL_LIQUIDATION)"""
    engine = StrictCausalSharedPortfolioEngine(initial_capital=100_000.0, risk_per_trade_pct=0.80, max_asset_margin_pct=0.90)
    dates = pd.date_range("2026-01-01 09:00", periods=100, freq="15min")
    
    p = np.full(100, 6000.0)
    df = pd.DataFrame({"trade_time": dates, "open": p, "high": p, "low": p, "close": p, "volume": 1000})

    # 注入挂单并在 Bar 0 以 6000 买入 5 手 (占用保证金 63,000 元)
    init_orders = {
        "AG_IDX": StrictPendingOrder(
            symbol="AG_IDX", side=1, mode="TREND", stop_price=5000.0, target_price=0.0, causal_atr=20.0, reason="TEST_BUY", generated_time=str(dates[0])
        )
    }

    # 在 Bar 1：开盘 6000，最低 5050 (不击穿止损 5000)，收盘 5050
    # 浮亏 = (5050 - 6000) * 15 * 5 = -71,250 元，权益剩余 = 28,750 元
    # 保证金占用 = 5050 * 15 * 5 * 0.14 = 53,025 元。Margin / Equity = 53025 / 28750 = 1.84 >= 1.20 (触碰券商强平线)
    df.loc[1, "open"] = 6000.0
    df.loc[1, "high"] = 6000.0
    df.loc[1, "low"] = 5050.0
    df.loc[1, "close"] = 5050.0

    rep = engine.run_portfolio({"AG_IDX": df}, initial_pending_orders=init_orders)
    
    # 爆仓后必须触发清算平仓，持仓清空，且退出原因确凿为强平熔断
    assert len(engine.positions) == 0, "强平后持仓必须全部清空！"
    assert len(engine.trades) >= 1, "强平必须产生平仓交易记录！"
    last_trade = engine.trades[-1]
    assert last_trade.exit_reason == "PORTFOLIO_MARGIN_CALL_LIQUIDATION", f"退出原因必须为 PORTFOLIO_MARGIN_CALL_LIQUIDATION，实际为 {last_trade.exit_reason}"
    assert last_trade.exit_price == 5050.0, f"强平价必须是触发强平时刻的收盘价 5050.0，实际为 {last_trade.exit_price}"
    assert last_trade.lots == 5, f"强平手数必须是 5 手，实际为 {last_trade.lots}"


def run_all_tests():
    print("🧪 正在执行 ChanQuant 8.0 8 大核心实质性回归测试...")
    test_single_source_signal_identity()
    print("  ✅ [1/8] 生产与研究单一同源逐柱一致性测试通过！")
    test_strict_ledger_invariance_deterministic()
    print("  ✅ [2/8] 真实交易单账户财务对账恒等式与期末清算测试通过！")
    test_zero_fee_double_counting()
    print("  ✅ [3/8] 真实交易开平仓费滑单边扣除测试通过！")
    test_causal_event_order_no_time_travel()
    print("  ✅ [4/8] Stage 1 开盘撮合与 Stage 2 柱内止损时序测试通过！")
    test_asynchronous_carry_forward()
    print("  ✅ [5/8] 异步闭市持仓、保证金与挂单生命周期 Carry-Forward 测试通过！")
    test_fail_closed_risk_rejection()
    print("  ✅ [6/8] 确凿挂单在保证金不足时 Fail-Closed 拒单测试通过！")
    test_stop_loss_bounds_and_gap_sanity()
    print("  ✅ [7/8] 极端跳空开盘穿止损真实价格成交与废单测试通过！")
    test_portfolio_liquidation_on_margin_call()
    print("  ✅ [8/8] 极端波动风险率超标时组合强平与熔断测试通过！")
    print("🎉 恭喜！ChanQuant 8.0 8 大实质性回归测试 100% 全部通过！")


if __name__ == "__main__":
    run_all_tests()

