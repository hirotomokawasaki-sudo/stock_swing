"""Tests for P2-A (latency tracking) and P2-B (token reduction contract)."""

from __future__ import annotations

import csv
import time
from pathlib import Path

import pytest

from stock_swing.utils.context_budget import (
    MODE_EMERGENCY,
    MODE_EXPANDED,
    MODE_NORMAL,
    TokenUsageTracker,
    compact_trading_context,
    select_context_mode,
)
from stock_swing.utils.latency_tracker import LatencyTracker


def test_latency_tracker_records_successful_call(tmp_path: Path) -> None:
    out = tmp_path / "latency.csv"
    tracker = LatencyTracker(out)

    with tracker.track("broker.fetch_account", symbol=""):
        time.sleep(0.001)

    tracker.flush()
    rows = list(csv.DictReader(out.read_text(encoding="utf-8").splitlines()))
    assert len(rows) == 1
    assert rows[0]["endpoint"] == "broker.fetch_account"
    assert rows[0]["status"] == "ok"
    assert float(rows[0]["duration_ms"]) > 0


def test_latency_tracker_records_error(tmp_path: Path) -> None:
    out = tmp_path / "latency.csv"
    tracker = LatencyTracker(out)

    with pytest.raises(ValueError):
        with tracker.track("broker.fetch_bars", symbol="AAPL"):
            raise ValueError("test error")

    tracker.flush()
    rows = list(csv.DictReader(out.read_text(encoding="utf-8").splitlines()))
    assert rows[0]["status"] == "error"
    assert rows[0]["error_type"] == "ValueError"


def test_latency_tracker_no_stale_file_when_empty(tmp_path: Path) -> None:
    out = tmp_path / "latency.csv"
    tracker = LatencyTracker(out)
    tracker.flush()
    assert not out.exists()


def test_compact_context_omits_large_arrays() -> None:
    snapshot = {
        "equity": 1000000.0,
        "open_position_count": 12,
        "realized_pnl": 50000.0,
        "win_rate": 0.55,
        "profit_factor": 1.8,
        "market_regime": "neutral",
        "all_trades": [{"trade_id": i} for i in range(192)],
        "raw_logs": "x" * 100000,
    }
    compact = compact_trading_context(snapshot)
    assert "all_trades" not in compact
    assert "raw_logs" not in compact
    assert compact["equity"] == 1000000.0
    assert compact["open_positions"] == 12


def test_select_context_mode_normal_by_default() -> None:
    assert select_context_mode() == MODE_NORMAL


def test_select_context_mode_emergency_on_integrity_issues() -> None:
    assert select_context_mode(integrity_issues=1) == MODE_EMERGENCY


def test_select_context_mode_expanded_on_errors() -> None:
    assert select_context_mode(recent_error_count=5) == MODE_EXPANDED


def test_token_usage_tracker_records_skip(tmp_path: Path) -> None:
    out = tmp_path / "tokens.csv"
    tracker = TokenUsageTracker(out)
    tracker.record_skip("paper_demo", "low_priority_candidate")
    tracker.flush()
    rows = list(csv.DictReader(out.read_text(encoding="utf-8").splitlines()))
    assert len(rows) == 1
    assert rows[0]["skip_reason"] == "low_priority_candidate"
    assert rows[0]["total_tokens"] == "0"
