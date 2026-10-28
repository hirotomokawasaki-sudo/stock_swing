"""Tests for P4-D: staged AI context packs."""
from __future__ import annotations

from stock_swing.utils.context_budget import (
    MODE_EMERGENCY,
    MODE_EXPANDED,
    MODE_MINIMAL,
    MODE_NORMAL,
    build_context_pack,
    estimate_token_count,
)


def _snapshot() -> dict:
    return {
        "equity": 1_000_000.0,
        "open_position_count": 12,
        "realized_pnl": 26_000.0,
        "unrealized_pnl": 39_000.0,
        "win_rate": 0.55,
        "profit_factor": 1.18,
        "market_regime": "neutral",
        "stale_warnings": ["KLAC: stale price detected"],
        "integrity_issues": [],
    }


def test_minimal_pack_contains_only_basics() -> None:
    pack = build_context_pack(_snapshot(), mode=MODE_MINIMAL)
    assert "equity" in pack
    assert "realized_pnl" not in pack
    assert "recent_events" not in pack


def test_normal_pack_contains_pnl_fields() -> None:
    pack = build_context_pack(_snapshot(), mode=MODE_NORMAL)
    assert "realized_pnl" in pack
    assert "win_rate" in pack


def test_normal_pack_includes_last_run_when_provided() -> None:
    cs = {
        "run_id": "r1",
        "orders": {"submitted": 2},
        "risk": {"cluster_blocks": ["NVDA"]},
        "data_quality": {"stale_symbols": []},
        "warnings": [],
    }
    pack = build_context_pack(_snapshot(), mode=MODE_NORMAL, console_summary=cs)
    assert pack["last_run"]["run_id"] == "r1"
    assert pack["last_run"]["cluster_blocks"] == ["NVDA"]


def test_expanded_pack_includes_stale_warnings() -> None:
    pack = build_context_pack(_snapshot(), mode=MODE_EXPANDED)
    assert "stale_warnings" in pack
    assert "KLAC" in str(pack["stale_warnings"])


def test_emergency_pack_includes_integrity_issues() -> None:
    pack = build_context_pack(_snapshot(), mode=MODE_EMERGENCY)
    assert "integrity_issues" in pack


def test_recent_events_capped_at_max() -> None:
    events = [{"type": f"e{i}"} for i in range(20)]
    pack = build_context_pack(_snapshot(), recent_events=events, max_events=5)
    assert len(pack.get("recent_events", [])) == 5


def test_estimate_token_count_is_positive() -> None:
    pack = build_context_pack(_snapshot())
    count = estimate_token_count(pack)
    assert count > 0


def test_minimal_pack_tokens_less_than_normal() -> None:
    min_pack = build_context_pack(_snapshot(), mode=MODE_MINIMAL)
    norm_pack = build_context_pack(_snapshot(), mode=MODE_NORMAL)
    assert estimate_token_count(min_pack) < estimate_token_count(norm_pack)
