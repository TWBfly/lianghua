import ast
import warnings
from pathlib import Path

import pytest

from runtime_credentials import load_required_credentials


ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT_PATHS = (
    ROOT / "code/deploy_to_server.py",
    ROOT / "code/fix_and_restore_production.py",
    ROOT / "code/deploy_and_restart_web_dashboard.py",
    ROOT / "code/auto_deploy_to_opt_lianghua.py",
    ROOT / "code/push_tianji_v2_to_server.py",
)
SECRET_PATHS = tuple((ROOT / "code").rglob("*.py")) + tuple(
    (ROOT / "strategies").rglob("*.py")
)


def test_required_credentials_have_no_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("TQ_ACCOUNT", raising=False)
    monkeypatch.delenv("TQ_PASSWORD", raising=False)

    with pytest.raises(RuntimeError, match="TQ_ACCOUNT, TQ_PASSWORD"):
        load_required_credentials(tmp_path / ".env")


def test_required_credentials_load_from_ignored_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("TQ_ACCOUNT", raising=False)
    monkeypatch.delenv("TQ_PASSWORD", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "TQ_ACCOUNT=test-account\nTQ_PASSWORD='test-password'\n",
        encoding="utf-8",
    )

    assert load_required_credentials(env_path) == (
        "test-account", "test-password"
    )


def test_server_deployers_fail_before_ssh_without_password(tmp_path):
    from deploy_to_server import load_env_server_config
    from fix_and_restore_production import fix_server

    missing = tmp_path / "missing.env"
    with pytest.raises(RuntimeError, match="SERVER_PASSWORD"):
        load_env_server_config(missing)
    with pytest.raises(RuntimeError, match="SERVER_PASSWORD"):
        fix_server(missing)


def test_deployment_sources_require_known_hosts():
    for path in DEPLOYMENT_PATHS:
        source = path.read_text(encoding="utf-8")
        assert "AutoAddPolicy" not in source, path
        assert "WarningPolicy" not in source, path
        assert (
            "load_system_host_keys()" in source
            or "NOT_IMPLEMENTED_LIVE_EXECUTION" in source
        ), path


def test_project_sources_contain_no_nonempty_password_fallback():
    findings = []
    for path in SECRET_PATHS:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            names = [
                target.id.lower()
                for target in node.targets
                if isinstance(target, ast.Name)
            ]
            if not any(
                key in name
                for name in names
                for key in (
                    "password", "secret", "api_key", "apikey", "token",
                )
            ):
                continue
            value = node.value
            if (
                isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and value.value
            ):
                findings.append((path.name, node.lineno))
            if isinstance(value, ast.BoolOp) and any(
                isinstance(item, ast.Constant)
                and isinstance(item.value, str)
                and item.value
                for item in value.values
            ):
                findings.append((path.name, node.lineno))
            if isinstance(value, ast.Call) and any(
                isinstance(item, ast.Constant)
                and isinstance(item.value, str)
                and item.value
                for item in value.args[1:]
            ):
                findings.append((path.name, node.lineno))

    assert findings == []
