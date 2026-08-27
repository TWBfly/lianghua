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


def test_dashboard_server_endpoints():
    from futures_dashboard_server import app

    client = app.test_client()
    for path in ("/", "/api/strategies", "/api/status", "/api/logs", "/api/kline?symbol=AG_IDX", "/api/trades"):
        response = client.get(path)
        assert response.status_code == 200, f"Endpoint {path} failed with {response.status_code}"
