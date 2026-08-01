import inspect
from pathlib import Path

import pytest

import deepseek_analyzer
from deepseek_quant_copilot import DeepSeekQuantCopilot
from web_server import validate_backtest_request


def test_valid_backtest_request_is_normalized():
    result = validate_backtest_request({
        "symbol": "000001",
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "initial_capital": 100_000,
    })

    assert result == {
        "symbol": "000001",
        "start_date": "2025-01-01",
        "end_date": "2025-12-31",
        "initial_capital": 100_000.0,
    }


@pytest.mark.parametrize("payload", [
    {"symbol": "1 OR 1=1"},
    {"start_date": "2025/01/01"},
    {"start_date": "2025-12-31", "end_date": "2025-01-01"},
    {"initial_capital": -1},
    {"initial_capital": float("inf")},
])
def test_invalid_single_stock_request_is_rejected(payload):
    with pytest.raises(ValueError):
        validate_backtest_request(payload)


def test_portfolio_symbol_list_is_bounded_and_validated():
    with pytest.raises(ValueError):
        validate_backtest_request(
            {"symbols": ["000001"] * 21},
            portfolio=True,
        )
    with pytest.raises(ValueError):
        validate_backtest_request(
            {"symbols": ["bad"]},
            portfolio=True,
        )


def test_deepseek_calls_do_not_disable_tls_verification():
    analyzer_source = inspect.getsource(deepseek_analyzer.analyze_notice_risk)
    copilot_source = inspect.getsource(DeepSeekQuantCopilot._call_api)

    assert "_create_unverified_context" not in analyzer_source
    assert "_create_unverified_context" not in copilot_source


def test_frontend_does_not_claim_fake_kelly_allocations():
    web_dir = Path(__file__).resolve().parents[1] / "web"
    html = (web_dir / "index.html").read_text(encoding="utf-8")
    script = (web_dir / "app.js").read_text(encoding="utf-8")

    assert "凯利" not in html + script
    assert "safe_half_kelly_pct" not in script
    assert "k.win_rate_pct" not in script
    assert "k.profit_loss_ratio" not in script
