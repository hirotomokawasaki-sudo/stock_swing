#!/usr/bin/env python3
"""Broker connectivity check for paper trading readiness."""

from __future__ import annotations

import os
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root / "src"))

from stock_swing.core.runtime import RuntimeModeError, read_runtime_mode
from stock_swing.sources.broker_client import BrokerClient


def _read_env_file(env_path: Path) -> None:
    """Load simple KEY=VALUE pairs from .env into os.environ if not already set."""
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def main() -> int:
    _read_env_file(project_root / ".env")

    required = ["BROKER_API_KEY", "BROKER_API_SECRET", "BROKER_BASE_URL"]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        print({"status": "error", "reason": f"missing env vars: {', '.join(missing)}"})
        return 1

    try:
        runtime_mode = read_runtime_mode(project_root)
    except (FileNotFoundError, RuntimeModeError) as exc:
        print({"status": "error", "reason": f"runtime mode unavailable: {exc}"})
        return 1

    if runtime_mode != "paper":
        print({"status": "error", "reason": f"runtime_mode must be 'paper' for demo trading, got '{runtime_mode}'"})
        return 1

    client = BrokerClient(
        api_key=os.environ["BROKER_API_KEY"],
        api_secret=os.environ["BROKER_API_SECRET"],
        paper_mode=True,
        base_url=os.environ["BROKER_BASE_URL"],
    )

    try:
        account = client.fetch_account().payload
    except Exception as exc:
        print({"status": "error", "reason": f"broker connectivity failed: {exc}"})
        return 1

    print(
        {
            "status": "ok",
            "runtime_mode": runtime_mode,
            "broker_base_url": client.base_url,
            "account_status": account.get("status"),
            "account_id": account.get("id"),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
