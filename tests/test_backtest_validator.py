"""
tests/test_backtest_validator.py — 回测报告统计可靠性验证器单元测试
"""

import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = PROJECT_ROOT / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from backtest_validator import (
    wilson_score_interval,
    grade_reliability,
    check_data_coverage,
    stamp_symbol_report,
    validate_report,
    GRADE_A,
    GRADE_B,
    GRADE_F,
    MIN_TRADES_RELIABLE,
    MIN_DATA_MONTHS,
)


def test_wilson_score_small_sample():
    """测试小样本下的置信区间极宽特性 (3笔全胜不是真胜率)"""
    ci_low, ci_high = wilson_score_interval(3, 3)
    # 3/3 胜的真实置信区间下限应 < 0.50
    assert ci_low < 0.50, f"Expected ci_low < 0.50 for 3/3, got {ci_low}"
    assert math.isclose(ci_high, 1.0, rel_tol=1e-3), f"Expected ci_high close to 1.0, got {ci_high}"
    width = ci_high - ci_low
    assert width > 0.50, f"Expected width > 0.50 for 3/3, got {width}"
    grade = grade_reliability(3, ci_low, ci_high)
    assert grade == GRADE_F, f"Expected GRADE_F, got {grade}"
    print(f"✅ test_wilson_score_small_sample passed: 3/3 CI=[{ci_low:.3f}, {ci_high:.3f}], width={width:.3f}, grade={grade}")


def test_wilson_score_large_sample():
    """测试大样本下的置信区间收敛特性 (1000笔)"""
    ci_low, ci_high = wilson_score_interval(550, 1000)
    width = ci_high - ci_low
    assert width < 0.07, f"Expected width < 0.07 for 1000 trades, got {width}"
    grade = grade_reliability(1000, ci_low, ci_high)
    assert grade == GRADE_A, f"Expected GRADE_A, got {grade}"
    print(f"✅ test_wilson_score_large_sample passed: 550/1000 CI=[{ci_low:.3f}, {ci_high:.3f}], width={width:.3f}, grade={grade}")


def test_data_coverage_check():
    """测试数据时间跨度检查"""
    cov_short = check_data_coverage("2025-03-01", "2026-08-01")
    assert cov_short["data_months"] == 17
    assert cov_short["data_sufficient"] is False

    cov_long = check_data_coverage("2023-01-01", "2026-08-01")
    assert cov_long["data_months"] == 43
    assert cov_long["data_sufficient"] is True
    print("✅ test_data_coverage_check passed")


def test_validate_report_isolation():
    """测试不可靠子策略被隔离，不污染可靠组合统计"""
    mock_reports = [
        {"symbol": "SI_IDX", "timeframe": "15m", "trade_count": 2, "win_rate": 1.0, "net_pnl": 8800.0},
        {"symbol": "C_IDX", "timeframe": "15m", "trade_count": 3, "win_rate": 1.0, "net_pnl": 10200.0},
        {"symbol": "AG_IDX", "timeframe": "15m", "trade_count": 33, "win_rate": 0.485, "net_pnl": 15000.0},
        {"symbol": "AU_IDX", "timeframe": "15m", "trade_count": 35, "win_rate": 0.429, "net_pnl": -39000.0},
    ]
    data_ranges = {
        ("SI_IDX", "15m"): {"start": "2025-06-01", "end": "2026-08-01"},
        ("C_IDX", "15m"): {"start": "2025-03-01", "end": "2026-08-01"},
        ("AG_IDX", "15m"): {"start": "2023-11-01", "end": "2026-08-01"},
        ("AU_IDX", "15m"): {"start": "2023-11-01", "end": "2026-08-01"},
    }

    res = validate_report(mock_reports, data_ranges)
    rs = res["reliability_summary"]

    assert rs["reliable_count"] == 2  # 只有 AG 和 AU (>=30笔)
    assert rs["unreliable_count"] == 2  # SI 和 C 只有 2, 3 笔
    assert rs["reliable_trades"] == 68  # 33 + 35
    assert rs["reliable_net_pnl"] == -24000.0  # 15000 - 39000 (不可靠的 19000 不计入)
    assert rs["raw_total_net_pnl"] == -5000.0  # 原始总数
    print("✅ test_validate_report_isolation passed")


if __name__ == "__main__":
    test_wilson_score_small_sample()
    test_wilson_score_large_sample()
    test_data_coverage_check()
    test_validate_report_isolation()
    print("\n🎉 All backtest validator unit tests PASSED!")
