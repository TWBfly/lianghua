import inspect
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import deepseek_analyzer
from deepseek_quant_copilot import DeepSeekQuantCopilot
from web_server import validate_backtest_request


RESEARCH_ONLY_INVALIDATED = {
    "copper_v16_engine",
    "futures_live_trader",
    "futures_ml_strategy_engine",
    "futures_self_evolving_holy_grail_engine",
    "futures_v14_complete_self_evolving_engine",
    "futures_v15_anti_degradation_engine",
    "futures_v16_first_principles_engine",
    "generate_futures_html_report",
    "multi_timeframe_benchmark_evaluator",
    "symbol_strategies.decoupled_symbol_engines",
    "xauusd_ml_strategy",
    "xauusd_self_evolving_engine",
    "xauusd_hardcore_multi_tf",
    "xauusd_hardcore_stress_test",
    "xauusd_m5_runner",
}


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
        "backtest_mode": "STRICT",
        "strategy": "causal_ml",
    }


@pytest.mark.parametrize("payload", [
    {"symbol": "1 OR 1=1"},
    {"start_date": "2025/01/01"},
    {"start_date": "2025-12-31", "end_date": "2025-01-01"},
    {"initial_capital": -1},
    {"initial_capital": float("inf")},
    {"backtest_mode": "optimistic"},
    {"strategy": "not-real"},
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


def test_strategy_endpoint_reports_only_executable_registry():
    from strategy_signal_library import SIGNAL_FUNCTIONS
    from web_server import app

    response = app.test_client().get("/api/strategies")

    assert response.status_code == 200
    names = [item["name"] if isinstance(item, dict) else item for item in response.get_json()]
    assert "causal_ml" in names
    for fn_name in SIGNAL_FUNCTIONS:
        assert fn_name in names


def test_munger_endpoint_source_does_not_derive_roe_from_pb_pe():
    import web_server

    source = inspect.getsource(web_server.get_munger_stocks)

    assert "pb / pe_ttm" not in source
    assert "roe_est" not in source


def test_ungrounded_ai_audit_is_unavailable_without_calling_model(
        tmp_path, monkeypatch):
    copilot = DeepSeekQuantCopilot(env_path=tmp_path / "missing.env")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("ungrounded audit called the model")

    monkeypatch.setattr(copilot, "_call_api", forbidden)
    candidates = pd.DataFrame([{
        "symbol": "000001",
        "name": "样本",
        "price": 10.0,
        "pe_ttm": 10.0,
        "predicted_5d_return_pct": 3.0,
    }])

    result = copilot.audit_top_stocks(candidates)

    assert result["decision"].tolist() == ["UNAVAILABLE"]
    assert result["suggested_position_pct"].tolist() == [0.0]
    assert "MISSING_GROUNDED_DOCUMENTS" in result.iloc[0]["rationale"]


def test_fusion_engine_does_not_relax_unknown_fundamentals_or_fake_notices():
    import ashare_3d_fusion_engine

    source = inspect.getsource(
        ashare_3d_fusion_engine.AShare3DFusionEngine.run_3d_quant_pipeline
    )

    assert "fund_df = ml_picks.head" not in source
    assert "notices_summary" not in source


def test_api_key_mutation_routes_are_not_exposed():
    from web_server import app

    client = app.test_client()

    assert client.post("/api/set_api_key", json={"api_key": "sk-x"}).status_code == 404
    assert client.get("/api/check_api_key").status_code == 404


def test_sync_requires_configured_admin_bearer_token(monkeypatch):
    import web_server

    client = web_server.app.test_client()
    monkeypatch.delenv("LIANGHUA_ADMIN_TOKEN", raising=False)
    assert client.post(
        "/api/sync_data", json={"symbol": "000001"}
    ).status_code == 503

    monkeypatch.setenv("LIANGHUA_ADMIN_TOKEN", "secret")
    assert client.post(
        "/api/sync_data",
        json={"symbol": "000001"},
        headers={"Authorization": "Bearer wrong"},
    ).status_code == 401


@pytest.mark.parametrize(("summary", "expected_status", "expected_ok"), [
    ({
        "requested": 1,
        "committed": ["000001"],
        "unchanged": [],
        "empty": [],
        "failed": [],
    }, 200, True),
    ({
        "requested": 1,
        "committed": [],
        "unchanged": ["000001"],
        "empty": [],
        "failed": [],
    }, 200, True),
    ({
        "requested": 1,
        "committed": [],
        "unchanged": [],
        "empty": ["000001"],
        "failed": [],
    }, 502, False),
    ({
        "requested": 1,
        "committed": [],
        "unchanged": [],
        "empty": [],
        "failed": [{"symbol": "000001", "error": "down"}],
    }, 502, False),
])
def test_sync_response_uses_actual_daily_summary(
        monkeypatch, summary, expected_status, expected_ok):
    import web_server

    monkeypatch.setenv("LIANGHUA_ADMIN_TOKEN", "secret")
    monkeypatch.setattr(
        web_server.kline_engine.data_engine,
        "sync_stock_daily",
        lambda **_: summary,
    )

    response = web_server.app.test_client().post(
        "/api/sync_data",
        json={"symbol": "000001"},
        headers={"Authorization": "Bearer secret"},
    )

    payload = response.get_json()
    assert response.status_code == expected_status
    assert payload["ok"] is expected_ok
    assert payload["summary"] == summary
    assert "基本面" not in str(payload)


def test_frontend_exposes_truthful_strategy_and_mode_controls():
    web_dir = Path(__file__).resolve().parents[1] / "web"
    html = (web_dir / "index.html").read_text(encoding="utf-8")
    script = (web_dir / "app.js").read_text(encoding="utf-8")
    combined = html + script

    for false_claim in (
        "DeepSeek",
        "LightGBM+XGB+Cat",
        "330 策略",
        "roe_est",
        "强护城河",
        "五维",
        "下次运行回测时",
        "/api/set_api_key",
        "/api/check_api_key",
    ):
        assert false_claim not in combined
    assert 'id="strategySelect"' in html
    assert 'id="researchProxyMode"' in html
    assert "RESEARCH_PROXY" in script
    assert "backtest_mode" in script
    assert "strategy" in script
    assert "ai_used" in script


def test_invalidated_ml_engines_are_documented_and_not_executable():
    from backtest_kline_engine import EXECUTABLE_STRATEGIES
    from web_server import app

    root = Path(__file__).resolve().parents[1]
    status_path = root / "docs" / "research-only-ml-engines.md"
    assert status_path.exists()
    status = status_path.read_text(encoding="utf-8")
    executable = set(EXECUTABLE_STRATEGIES)
    response = app.test_client().get("/api/strategies")
    assert response.status_code == 200
    exposed = {
        item["name"] if isinstance(item, dict) else item
        for item in response.get_json()
    }

    for module in RESEARCH_ONLY_INVALIDATED:
        assert f"`{module}` — `RESEARCH_ONLY_INVALIDATED`" in status
        assert module not in executable
        assert module not in exposed
    assert "futures_research_backtest" not in executable
    assert "futures_research_backtest" not in exposed
    assert "`futures_research_backtest` — `AUDITED_RESEARCH_PROXY`" in status


def test_remote_strategy_registration_is_disabled(monkeypatch):
    from web_server import app, hot_plugger

    called = []
    monkeypatch.setattr(
        hot_plugger,
        "save_custom_strategy_code",
        lambda *args: called.append(args),
    )

    response = app.test_client().post("/api/register_strategy", json={
        "strategy_name": "remote_code",
        "code_content": "def calculate_signal(df): return 0",
    })

    assert response.status_code == 403
    assert response.get_json()["error_code"] == (
        "REMOTE_STRATEGY_REGISTRATION_DISABLED"
    )
    assert called == []
