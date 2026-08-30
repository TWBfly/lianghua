import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in (PROJECT_ROOT / "code", PROJECT_ROOT / "strategies"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from run_optimized_macro_trend_island_audit import (
    _result_reconciles,
    evaluate_macro_audit_gates,
)
from run_tianji_v2_optimized_deep_audit import build_tianji_scorecard
from run_tianji_v2_optimized_deep_audit import build_tianji_audit_gates


def test_negative_tianji_results_cannot_receive_positive_profitability_claims():
    card = build_tianji_scorecard(-2_000_000.0, -2_400_000.0, 600_000.0)

    assert sum(row[2] for row in card) < 85.0
    assert not any(
        "全历史大赚" in row[3] or "双红" in row[3]
        for row in card
    )


def test_tianji_report_serializes_explicit_rejection_gates():
    gates, verdict = build_tianji_audit_gates(
        total_pnl=-2_000_000.0,
        is_pnl=-2_400_000.0,
        oos_pnl=600_000.0,
        total_score=15.0,
    )

    assert verdict == "REJECTED"
    assert {gate["id"] for gate in gates} == {
        "positive_full_sample",
        "positive_is",
        "positive_oos",
        "approval_score",
    }


def test_tianji_report_source_has_no_symbol_assumptions_or_fixed_praise():
    from pathlib import Path
    import run_tianji_v2_optimized_deep_audit as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert 'v2_results["AU_IDX"]' not in source
    assert 'v2_results["P_IDX"]' not in source
    assert "净利翻倍" not in source
    assert "稳定狂揽" not in source


def test_macro_verdict_requires_every_declared_gate():
    gates, verdict = evaluate_macro_audit_gates(
        min_trades=809,
        oos_pnl=358_295.0,
        plateau_ratio=84.4,
        stressed_pnl=-62_971_534.0,
        ledger_reconciled=True,
    )

    assert verdict == "REJECTED"
    friction = next(gate for gate in gates if gate["id"] == "three_x_friction")
    assert friction["passed"] is False


def test_macro_verdict_rejects_unreconciled_ledger():
    gates, verdict = evaluate_macro_audit_gates(
        min_trades=1_000,
        oos_pnl=1.0,
        plateau_ratio=60.0,
        stressed_pnl=1.0,
        ledger_reconciled=False,
    )

    assert verdict == "REJECTED"
    ledger = next(gate for gate in gates if gate["id"] == "ledger_reconciled")
    assert ledger["passed"] is False


def test_result_reconciliation_includes_marked_equity():
    result = {
        "pnl": 0.0,
        "trades_list": [],
        "equity_curve": [1_000_000.0, 1_100_000.0],
    }

    assert _result_reconciles(result) is False
