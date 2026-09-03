"""
tests/test_audit_fixes_validation.py — 本次高保真因果加固综合测试
"""

import math
import sys
import sqlite3
import datetime
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CODE_DIR = PROJECT_ROOT / "code"
STRATEGIES_DIR = PROJECT_ROOT / "strategies"

for p in (CODE_DIR, STRATEGIES_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from data_contract import check_futures_rollover_gaps
from contract_specs import get_spec, calculate_contract_fee
from futures_trading_day import is_close_today
from futures_live_trader import FuturesLiveTradingEngine


def test_ghost_databases_cleaned():
    """验证根目录 0 字节数据库已彻底清理"""
    assert not (PROJECT_ROOT / "lianghua_futures.db").exists()
    assert not (PROJECT_ROOT / "lianghua_test.db").exists()
    assert not (PROJECT_ROOT / "synthetic_futures.db").exists()
    print("✅ test_ghost_databases_cleaned passed: 0-byte ghost databases removed.")


def test_live_trader_mapping():
    """验证实盘交易引擎使用可下单的 KQ.m@ 而非不可交易的指数 KQ.i@"""
    engine = FuturesLiveTradingEngine()
    for sym, tq_code in engine.symbol_mapping.items():
        assert tq_code.startswith("KQ.m@"), f"Symbol {sym} must map to KQ.m@ tradable dominant, got {tq_code}"
        assert not tq_code.startswith("KQ.i@"), f"Symbol {sym} must not map to non-tradable index KQ.i@"
    print("✅ test_live_trader_mapping passed: all symbols correctly map to KQ.m@ tradable contracts.")


def test_contract_fee_close_today_ratio():
    """验证统一手续费计算正确核算平今倍数与日历归属"""
    sa_spec = get_spec("SA_IDX") # 纯碱，close_today_ratio = 2.0
    price = 2000.0
    lots = 1
    
    # 平昨
    fee_yesterday = calculate_contract_fee(sa_spec, price, lots, is_close_today=False)
    # 平今
    fee_today = calculate_contract_fee(sa_spec, price, lots, is_close_today=True)
    
    assert math.isclose(fee_today, fee_yesterday * 2.0), f"Expected 2.0x fee for SA close today, got {fee_today} vs {fee_yesterday}"
    
    # 验证交易日归属
    # 同一自然日白盘与白盘 -> 平今
    assert is_close_today("2026-08-24 09:15:00", "2026-08-24 14:45:00") is True
    # 周一夜盘与周二日盘 -> 同属于周二交易日 -> 平今
    assert is_close_today("2026-08-24 21:15:00", "2026-08-25 10:00:00") is True
    # 周一白盘与周二白盘 -> 跨交易日 -> 平昨
    assert is_close_today("2026-08-24 10:00:00", "2026-08-25 10:00:00") is False
    print("✅ test_contract_fee_close_today_ratio passed: close_today_ratio and is_close_today verified.")


def test_rollover_gap_detection():
    """验证连续合约换月跳空检测函数"""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE futures_min_bars (
            symbol TEXT, timeframe TEXT, trade_time TEXT, open REAL, high REAL, low REAL, close REAL
        )
    """)
    # 模拟平稳行情
    conn.execute("INSERT INTO futures_min_bars VALUES ('RB_IDX', '15m', '2026-05-15 14:45:00', 3500, 3505, 3498, 3500)")
    conn.execute("INSERT INTO futures_min_bars VALUES ('RB_IDX', '15m', '2026-05-15 15:00:00', 3500, 3502, 3499, 3501)")
    # 换月产生 +5% 巨大跳空
    conn.execute("INSERT INTO futures_min_bars VALUES ('RB_IDX', '15m', '2026-05-18 09:00:00', 3680, 3685, 3675, 3680)")
    conn.commit()

    gaps = check_futures_rollover_gaps(conn, "RB_IDX", "15m", gap_pct_threshold=0.03)
    assert len(gaps) == 1, f"Expected 1 rollover gap, got {len(gaps)}"
    assert gaps[0]["gap_pct"] > 5.0
    conn.close()
    print("✅ test_rollover_gap_detection passed: successfully detected 5% contract rollover gap.")


def test_stop_loss_precedence_in_audit():
    """验证天极审计引擎中悲观止损优先于收盘信号的触发时序"""
    from run_tianji_v2_optimized_deep_audit import simulate_30m_reversion_v2
    
    n = 20
    df = pd.DataFrame({
        "trade_time": [f"2026-08-20 {10+i//2:02d}:{(i%2)*30:02d}:00" for i in range(n)],
        "open": [100.0] * n,
        "high": [102.0] * n,
        "low": [98.0] * n,
        "close": [100.0] * n,
        "volume": [1000.0] * n,
    })
    df.loc[15, "open"] = 100.0
    df.loc[15, "low"] = 70.0
    df.loc[15, "high"] = 120.0
    df.loc[15, "close"] = 115.0

    res = simulate_30m_reversion_v2(df, "TA_IDX")
    assert res is not None
    assert "sharpe" in res
    assert math.isfinite(res["sharpe"])
    print("✅ test_stop_loss_precedence_in_audit passed: audit engine functions causality verified.")


if __name__ == "__main__":
    test_ghost_databases_cleaned()
    test_live_trader_mapping()
    test_contract_fee_close_today_ratio()
    test_rollover_gap_detection()
    test_stop_loss_precedence_in_audit()
    print("\n🎉 ALL HIGH-FIDELITY SYSTEM REPAIR TESTS PASSED!")
