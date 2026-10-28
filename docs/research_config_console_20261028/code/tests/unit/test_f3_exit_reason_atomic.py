"""F3 tests: exit_reason_store atomic writes survive concurrent access."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from stock_swing.tracking.exit_reason_store import (
    delete_exit_reason,
    purge_old_entries,
    read_exit_reason,
    write_exit_reason,
)


def test_write_and_read(tmp_path):
    write_exit_reason(tmp_path, "ORD-001", "AAPL", "Trailing stop triggered", "trailing_stop")
    result = read_exit_reason(tmp_path, "ORD-001")
    assert result is not None
    assert result["exit_reason"] == "trailing_stop"
    assert result["symbol"] == "AAPL"


def test_delete_removes_entry(tmp_path):
    write_exit_reason(tmp_path, "ORD-002", "NVDA", "Stop loss", "stop_loss")
    delete_exit_reason(tmp_path, "ORD-002")
    assert read_exit_reason(tmp_path, "ORD-002") is None


def test_concurrent_writes_do_not_corrupt(tmp_path):
    """Multiple threads writing different order IDs must not corrupt the store."""
    errors = []

    def worker(order_id: str, symbol: str):
        try:
            for _ in range(10):
                write_exit_reason(
                    tmp_path, order_id, symbol, "trailing", "trailing_stop"
                )
                delete_exit_reason(tmp_path, order_id)
                write_exit_reason(
                    tmp_path, order_id, symbol, "trailing", "trailing_stop"
                )
        except Exception as exc:
            errors.append(str(exc))

    threads = [
        threading.Thread(target=worker, args=(f"ORD-{i:03d}", f"SYM{i}"))
        for i in range(6)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent write errors: {errors}"

    # Verify the store is valid JSON
    store_path = tmp_path / "data/tracking/pending_exit_reasons.json"
    if store_path.exists():
        data = json.loads(store_path.read_text())
        assert isinstance(data, dict)


def test_temp_file_not_left_behind_on_success(tmp_path):
    write_exit_reason(tmp_path, "ORD-003", "AAPL", "trigger", "stop_loss")
    store_dir = tmp_path / "data" / "tracking"
    tmp_files = list(store_dir.glob(".exit_reasons.*.tmp"))
    assert len(tmp_files) == 0, "Temp files must be cleaned up after atomic write"


def test_write_missing_order_id_is_noop(tmp_path):
    write_exit_reason(tmp_path, "", "AAPL", "trigger", "stop_loss")
    store_path = tmp_path / "data/tracking/pending_exit_reasons.json"
    assert not store_path.exists() or json.loads(store_path.read_text()) == {}
