import ast
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "code", ROOT / "strategies"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

try:
    import pytest
except ImportError:
    pytest = None

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


def _is_secret_name(name: str) -> bool:
    name = name.lower()
    if "author" in name:
        return False
    exact_match_keywords = ("pass", "pwd", "auth", "secret", "token")
    parts = name.split("_")
    if any(kw in parts for kw in exact_match_keywords):
        return True
    substring_keywords = (
        "password", "api_key", "apikey", "secret_key",
        "tq_user", "tq_pass", "tq_account", "tq_password",
        "private_key", "credential"
    )
    return any(kw in name for kw in substring_keywords)


def test_project_sources_contain_no_nonempty_password_fallback():
    findings = []
    for path in SECRET_PATHS:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                names = [
                    target.id.lower()
                    for target in node.targets
                    if isinstance(target, ast.Name)
                ]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names = [node.target.id.lower()]
            else:
                names = []

            # Check dict.get / os.getenv with non-empty default fallback on secret keys
            if isinstance(node, ast.Call):
                call_func = getattr(node.func, "attr", "") if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                if call_func in ("get", "getenv") and len(node.args) >= 2:
                    first_arg = node.args[0]
                    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                        if _is_secret_name(first_arg.value):
                            default_arg = node.args[1]
                            if isinstance(default_arg, ast.Constant) and isinstance(default_arg.value, str) and default_arg.value:
                                findings.append((path.name, node.lineno, f"Call default: {first_arg.value}={default_arg.value}"))

            if names and any(_is_secret_name(name) for name in names):
                value = getattr(node, "value", None)
                if (
                    isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                    and value.value
                ):
                    findings.append((path.name, node.lineno, f"Assign: {names}={value.value}"))
                elif isinstance(value, ast.BoolOp) and any(
                    isinstance(item, ast.Constant)
                    and isinstance(item.value, str)
                    and item.value
                    for item in value.values
                ):
                    findings.append((path.name, node.lineno, f"BoolOp fallback: {names}"))
                elif isinstance(value, ast.Call) and any(
                    isinstance(item, ast.Constant)
                    and isinstance(item.value, str)
                    and item.value
                    for item in value.args[1:]
                ):
                    findings.append((path.name, node.lineno, f"Call arg fallback: {names}"))

            if isinstance(node, ast.Return) and node.value:
                for subnode in ast.walk(node.value):
                    if isinstance(subnode, ast.Constant) and isinstance(subnode.value, str):
                        s = subnode.value
                        if s in ("13800000000", "redacted_password") or s.startswith("sk-"):
                            findings.append((path.name, node.lineno, f"Return literal: {s}"))

    assert findings == []


def test_project_sources_contain_no_plaintext_secrets():
    leaks = []
    for path in SECRET_PATHS:
        text = path.read_text(encoding="utf-8")
        if "13800000000" in text:
            leaks.append((path.name, "Found hardcoded account 13800000000"))
        if "redacted_password" in text:
            leaks.append((path.name, "Found hardcoded password redacted_password"))
        if "sk-" in text:
            # exclude python comments or non-key substrings
            for line_no, line in enumerate(text.splitlines(), start=1):
                if "sk-" in line and not line.strip().startswith("#"):
                    import re
                    if re.search(r"sk-[a-zA-Z0-9]{15,}", line):
                        leaks.append((path.name, f"line {line_no}: Found API key pattern"))
    assert leaks == []

