"""Unit tests for exit_reason_store."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from stock_swing.tracking.exit_reason_store import (
    delete_exit_reason,
    purge_old_entries,
    read_exit_reason,
    write_exit_reason,
)


@pytest.fixture()
def tmp_root(tmp_path: Path) -> Path:
    return tmp_path


def test_write_and_read(tmp_root: Path) -> None:
    write_exit_reason(
        tmp_root, "order-001", "AAPL", "Trailing stop triggered", "trailing_stop",
        metadata={"signal_strength": 0.95},
    )
    result = read_exit_reason(tmp_root, "order-001")
    assert result is not None
    assert result["exit_reason"] == "trailing_stop"
    assert result["exit_trigger"] == "Trailing stop triggered"
    assert result["symbol"] == "AAPL"
    assert result["signal_strength"] == 0.95


def test_read_missing_key_returns_none(tmp_root: Path) -> None:
    assert read_exit_reason(tmp_root, "nonexistent") is None


def test_read_missing_file_returns_none(tmp_root: Path) -> None:
    assert read_exit_reason(tmp_root, "any-id") is None


def test_delete_removes_entry(tmp_root: Path) -> None:
    write_exit_reason(tmp_root, "order-002", "MSFT", "Stop loss triggered", "stop_loss")
    assert read_exit_reason(tmp_root, "order-002") is not None
    delete_exit_reason(tmp_root, "order-002")
    assert read_exit_reason(tmp_root, "order-002") is None


def test_delete_missing_key_is_noop(tmp_root: Path) -> None:
    # Should not raise
    delete_exit_reason(tmp_root, "does-not-exist")


def test_multiple_entries(tmp_root: Path) -> None:
    write_exit_reason(tmp_root, "oid-1", "AAPL", "Trailing stop triggered", "trailing_stop")
    write_exit_reason(tmp_root, "oid-2", "MSFT", "Breakeven stop triggered", "breakeven_stop")
    write_exit_reason(tmp_root, "oid-3", "NVDA", "Stop loss triggered", "stop_loss")

    assert read_exit_reason(tmp_root, "oid-1")["exit_reason"] == "trailing_stop"
    assert read_exit_reason(tmp_root, "oid-2")["exit_reason"] == "breakeven_stop"
    assert read_exit_reason(tmp_root, "oid-3")["exit_reason"] == "stop_loss"


def test_purge_removes_old_entries(tmp_root: Path) -> None:
    store_path = tmp_root / "data" / "tracking" / "pending_exit_reasons.json"
    store_path.parent.mkdir(parents=True, exist_ok=True)

    old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    new_ts = datetime.now(timezone.utc).isoformat()

    store = {
        "old-order": {"symbol": "AAPL", "exit_reason": "stop_loss", "written_at": old_ts},
        "new-order": {"symbol": "MSFT", "exit_reason": "trailing_stop", "written_at": new_ts},
    }
    store_path.write_text(json.dumps(store), encoding="utf-8")

    removed = purge_old_entries(tmp_root, max_age_days=7)
    assert removed == 1
    assert read_exit_reason(tmp_root, "old-order") is None
    assert read_exit_reason(tmp_root, "new-order") is not None


def test_purge_empty_store_is_noop(tmp_root: Path) -> None:
    removed = purge_old_entries(tmp_root, max_age_days=7)
    assert removed == 0


def test_write_with_empty_order_id_is_noop(tmp_root: Path) -> None:
    write_exit_reason(tmp_root, "", "AAPL", "Stop loss triggered", "stop_loss")
    store_path = tmp_root / "data" / "tracking" / "pending_exit_reasons.json"
    assert not store_path.exists()
