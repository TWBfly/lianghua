import inspect
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_shell_trader_launcher_fails_closed():
    completed = subprocess.run(
        ["bash", str(ROOT / "run_tqsim_trader.sh")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "TRADING_DISABLED" in completed.stderr


def test_python_trader_main_fails_before_credentials_or_tqsdk():
    import futures_live_trader

    source = inspect.getsource(futures_live_trader)
    assert futures_live_trader.main() == 2
    assert 'os.getenv("TQ_USER",' not in source
    assert 'os.getenv("TQ_PASS",' not in source
    assert "TqAuth(" not in inspect.getsource(futures_live_trader.main)


def test_dashboard_exposes_no_active_trading_or_legacy_backtest_api():
    from futures_dashboard_server import app

    client = app.test_client()
    for method, path in (
        (client.get, "/"),
        (client.get, "/api/status"),
        (client.get, "/api/logs"),
        (client.get, "/api/kline?symbol=AG_IDX"),
        (client.get, "/api/trades"),
        (client.post, "/api/trader/restart"),
    ):
        response = method(path)
        assert response.status_code == 503
        payload = response.get_json()
        assert payload["status"] == "TRADING_DISABLED"
        assert "disabled_reason" in payload
