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
    for path in ("/", "/api/strategies", "/api/status", "/api/kline?symbol=AG_IDX", "/api/trades"):
        response = client.get(path)
        assert response.status_code == 200, f"Endpoint {path} failed with {response.status_code}"


def test_dashboard_logs_are_not_publicly_exposed():
    from futures_dashboard_server import app

    assert app.test_client().get("/api/logs").status_code == 404


def test_tianji_heartbeat_daemons_fail_closed(capsys):
    import deploy_tianji_v2_tier1_trader as local
    import server_tianji_v2_daemon as server

    assert "NOT_IMPLEMENTED_LIVE_EXECUTION" in inspect.getsource(local)
    assert "NOT_IMPLEMENTED_LIVE_EXECUTION" in inspect.getsource(server)
    assert local.main() == 2
    assert server.main() == 2
    assert "NOT_IMPLEMENTED_LIVE_EXECUTION" in capsys.readouterr().out


def test_tianji_dedicated_deployers_fail_closed():
    paths = (
        ROOT / "code/auto_deploy_to_opt_lianghua.py",
        ROOT / "code/push_tianji_v2_to_server.py",
    )
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "NOT_IMPLEMENTED_LIVE_EXECUTION" in source
        assert "paramiko" not in source


def test_dashboard_never_reports_tianji_v2_as_running():
    from futures_dashboard_server import app

    response = app.test_client().get(
        "/api/status?strategy=tianji_dual_island_v2"
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["running"] is False
    assert payload["execution_status"] == "NOT_IMPLEMENTED_LIVE_EXECUTION"
    for field in (
        "initial_balance", "current_equity", "overall_win_rate",
        "total_symbols", "total_trades_count", "total_profit",
    ):
        assert field in payload


def test_general_dashboard_deployer_does_not_start_disabled_tianji():
    source = (
        ROOT / "code/deploy_and_restart_web_dashboard.py"
    ).read_text(encoding="utf-8")

    assert "deploy_tianji_v2_tier1_trader.py" not in source
    assert "100% 部署上线" not in source


def test_dashboard_html_defaults_to_available_strategy():
    from futures_dashboard_server import app

    html = app.test_client().get("/").get_data(as_text=True)

    assert 'let currentStrategy = "taichong_dual_squad"' in html
    assert "NOT_IMPLEMENTED_LIVE_EXECUTION" in html
