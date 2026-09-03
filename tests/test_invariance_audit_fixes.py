"""
tests/test_invariance_audit_fixes.py — 核心不变量与审计修复自动化回归测试套件
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in (PROJECT_ROOT / "code", PROJECT_ROOT / "strategies", PROJECT_ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from portfolio_simulator import _atr_exit, _sell_proceeds, FeeSchedule, Position
from unified_backtest_pipeline import run_strategy_causal_backtest, UnifiedDataProvider
from vnpy_differential_oracle import VnpyDifferentialOracle
from vnpy_tianji_strategy import VnpyTianjiStrategy
from backtest_kline_engine import KLineBacktestEngine, _yearly_equity_breakdown
from test_p0_credentials_and_ssh import _is_secret_name


def test_ashare_gap_stop_physical_price_bounds():
    """1. A股跳空止损价格物理界限：成交价必落在 [low, high] 区间内"""
    pos = Position(
        shares=100, average_cost=100.0, entry_time=pd.Timestamp('2025-01-01'),
        entry_price=100.0, peak_price=100.0, entry_value=10000.0, buy_fees=5.0,
        decision_id='d1',
        risk_exit={'entry_atr': 2.0, 'stop_atr_multiple': 1.5, 'stop_floor_fraction': 0.8,
                   'take_profit_atr_multiple': 3.0, 'trailing_activation_fraction': 1.1,
                   'trailing_atr_multiple': 2.0}
    )
    bar = {'open': 80.0, 'high': 82.0, 'low': 75.0, 'close': 78.0}
    reason, exit_bench = _atr_exit(pos, bar)
    assert reason == "ATR_STOP"
    assert exit_bench == 80.0, f"Expected exit benchmark 80.0, got {exit_bench}"

    fee = FeeSchedule()
    fill_price, gross, sell_fees, net_proceeds = _sell_proceeds(
        pos.shares, exit_bench, fee, '2025-01-02', None, '600519'
    )
    assert fill_price <= bar['high'], f"Fill price {fill_price} > day high {bar['high']}"
    assert fill_price >= bar['low'], f"Fill price {fill_price} < day low {bar['low']}"


def test_single_loss_drawdown_anchored_to_initial_capital():
    """2. 单笔亏损最大回撤必须大于0 (锚定初始资金)"""
    dates = pd.date_range('2025-01-01', periods=60, freq='15min')
    df = pd.DataFrame({
        'trade_time': dates,
        'open': [100.0] * 60,
        'high': [101.0] * 60,
        'low': [99.0] * 60,
        'close': [100.0] * 60,
        'volume': [1000] * 60,
    })
    df.loc[25, 'low'] = 90.0
    df.loc[25, 'close'] = 90.0
    sigs = np.zeros(60)
    sigs[20] = 1

    trades, summary = run_strategy_causal_backtest(df, 'RB_IDX', sigs, capital=100_000)
    assert len(trades) >= 1
    assert summary['max_drawdown'] > 0, f"Expected positive max_drawdown, got {summary['max_drawdown']}"


def test_bankruptcy_terminates_further_trading():
    """3. 穿仓/破产后立即停止所有后续交易"""
    dates = pd.date_range('2025-01-01', periods=60, freq='15min')
    df = pd.DataFrame({
        'trade_time': dates,
        'open': [100.0] * 60,
        'high': [101.0] * 60,
        'low': [99.0] * 60,
        'close': [100.0] * 60,
        'volume': [1000] * 60,
    })
    df.loc[25, 'open'] = 1.0
    df.loc[25, 'high'] = 1.0
    df.loc[25, 'low'] = 1.0
    df.loc[25, 'close'] = 1.0
    sigs = np.zeros(60)
    sigs[20] = 1
    sigs[30] = 1
    sigs[40] = 1

    trades, summary = run_strategy_causal_backtest(df, 'RB_IDX', sigs, capital=5000, target_risk_pct=0.50)
    assert summary.get('is_bankrupt') is True
    assert len(trades) == 1, f"Expected exactly 1 trade before bankruptcy halt, got {len(trades)}"


def test_future_data_prefix_invariance():
    """4. 未来数据前缀不变性：修改 t 柱之后的数据不影响 t 柱开盘决策"""
    dates = pd.date_range('2025-01-01', periods=60, freq='15min')
    df1 = pd.DataFrame({
        'trade_time': dates,
        'open': [100.0] * 60,
        'high': [102.0] * 60,
        'low': [98.0] * 60,
        'close': [100.0] * 60,
        'volume': [1000] * 60,
    })
    df2 = df1.copy()
    df2.loc[30:, 'high'] = 200.0
    df2.loc[30:, 'low'] = 50.0

    sigs = np.zeros(60)
    sigs[20] = 1

    trades1, _ = run_strategy_causal_backtest(df1, 'RB_IDX', sigs, capital=100_000)
    trades2, _ = run_strategy_causal_backtest(df2, 'RB_IDX', sigs, capital=100_000)

    assert len(trades1) > 0 and len(trades2) > 0
    t1, t2 = trades1[0], trades2[0]
    assert t1.entry_price == t2.entry_price
    assert t1.lots == t2.lots
    assert t1.entry_time == t2.entry_time


def test_differential_oracle_fails_closed():
    """5. 差分预言机在无输入时返回 NOT_RUN，在交易数不符时返回 FAIL_AUDIT"""
    oracle = VnpyDifferentialOracle()
    res_empty = oracle.run_oracle_verification('AG_IDX', '15m', VnpyTianjiStrategy, {}, internal_metrics=None)
    assert res_empty['status'] == 'NOT_RUN'

    # 注入交易数不符的 internal_metrics
    fake_metrics = {'total_net_pnl': 1000.0, 'total_trade_count': 99999}
    res_mismatch = oracle.run_oracle_verification('AG_IDX', '15m', VnpyTianjiStrategy, {}, internal_metrics=fake_metrics)
    assert res_mismatch['status'] == 'FAIL_AUDIT'
    assert any('交易笔数不匹配' in w for w in res_mismatch['warnings'])


def test_secret_scanner_detection():
    """6. 凭证扫描器可有效识别敏感词"""
    assert _is_secret_name('tq_user') is True
    assert _is_secret_name('tq_pass') is True
    assert _is_secret_name('server_pwd') is True
    assert _is_secret_name('author') is False


if __name__ == '__main__':
    test_ashare_gap_stop_physical_price_bounds()
    test_single_loss_drawdown_anchored_to_initial_capital()
    test_bankruptcy_terminates_further_trading()
    test_future_data_prefix_invariance()
    test_differential_oracle_fails_closed()
    test_secret_scanner_detection()
    print('ALL 6 INVARIANCE TESTS PASSED!')
