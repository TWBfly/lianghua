"""Fail-closed runtime credential loading."""

import os
from pathlib import Path


def load_required_credentials(
    env_path,
    account_key="TQ_ACCOUNT",
    password_key="TQ_PASSWORD",
):
    values = {
        account_key: os.environ.get(account_key, "").strip(),
        password_key: os.environ.get(password_key, "").strip(),
    }
    path = Path(env_path)
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            key, separator, value = raw.partition("=")
            key = key.strip()
            if separator and key in values and not values[key]:
                values[key] = value.strip().strip("\"'")
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise RuntimeError(
            f"missing required credentials: {', '.join(missing)}"
        )
    return values[account_key], values[password_key]
