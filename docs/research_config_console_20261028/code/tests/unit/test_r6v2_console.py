"""R6-v2: Console data contract tests (H3).

Validates:
1. non-dry-run ConsoleSummary includes ledger_quality and entry_filter_stats
2. Full 7-stage funnel is present and correct
3. Funnel displays correctly in ConsoleRenderer
4. execution_leg_id present on partial fills (R1-v2)
5. status separation: last_run / data_quality present in to_dict()

Acceptance criteria (H3):
- test_non_dry_run_console_includes_ledger_quality
- test_funnel_counts_all_block_stages
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from stock_swing.reporting.console_renderer import ConsoleRenderer
from stock_swing.reporting.console_summary import ConsoleSummary


# ─────────────────────────────────────────────────────────────────────────── #
# 1. non-dry-run console includes ledger_quality / entry_filter_stats
# ─────────────────────────────────────────────────────────────────────────── #

def test_non_dry_run_console_includes_ledger_quality() -> None:
    """AC: non-dry-run ConsoleSummary must carry ledger_quality data."""
    lq = {"clean_closed": 183, "quarantined": 93, "attribution_coverage_pct": 100.0}
    s = ConsoleSummary.build(
        run_id="r1",
        equity=1_000_000.0,
        open_position_count=9,
        ledger_quality=lq,
    )
    d = s.to_dict()
    assert d["ledger_quality"]["clean_closed"] == 183
    assert d["ledger_quality"]["attribution_coverage_pct"] == 100.0


def test_non_dry_run_console_includes_entry_filter_stats() -> None:
    """AC: entry_filter_stats must be passed through to to_dict()."""
    efs = {"volume_blocked": ["SHOC"], "stock_reduced_blocked": ["PTF"]}
    s = ConsoleSummary.build(
        run_id="r2",
        equity=1_000_000.0,
        open_position_count=0,
        entry_filter_stats=efs,
    )
    d = s.to_dict()
    assert d["decision_funnel"]["stock_reduced_blocked"] == 1


def test_ledger_quality_empty_when_not_supplied() -> None:
    """Omitting ledger_quality must not crash and defaults to empty."""
    s = ConsoleSummary.build(run_id="r3", equity=1_000_000.0, open_position_count=0)
    assert s.ledger_quality == {}


# ─────────────────────────────────────────────────────────────────────────── #
# 2. Full 7-stage funnel
# ─────────────────────────────────────────────────────────────────────────── #

def test_funnel_counts_all_block_stages() -> None:
    """AC: funnel_stages must contain all 10 stage keys."""
    required_stages = {
        "generated", "risk_denied", "entry_blocked", "cluster_blocked",
        "guardrail_blocked", "qty_zero", "submitted", "accepted",
        "filled", "reconciled",
    }
    stages = {
        "generated": 10,
        "risk_denied": 1,
        "entry_blocked": 2,
        "cluster_blocked": 0,
        "guardrail_blocked": 1,
        "qty_zero": 2,
        "submitted": 4,
        "accepted": 4,
        "filled": 3,
        "reconciled": 3,
    }
    s = ConsoleSummary.build(
        run_id="fs1",
        equity=1_000_000.0,
        open_position_count=5,
        funnel_stages=stages,
    )
    d = s.to_dict()
    assert set(d["decision_funnel"]["stages"].keys()) == required_stages


def test_funnel_stages_values_propagate() -> None:
    stages = {"generated": 10, "submitted": 4, "filled": 3, "reconciled": 3,
              "risk_denied": 0, "entry_blocked": 0, "cluster_blocked": 0,
              "guardrail_blocked": 0, "qty_zero": 3, "accepted": 4}
    s = ConsoleSummary.build(run_id="fs2", equity=1_000_000.0, open_position_count=0,
                             funnel_stages=stages)
    d = s.to_dict()
    assert d["decision_funnel"]["stages"]["generated"] == 10
    assert d["decision_funnel"]["stages"]["filled"] == 3


def test_funnel_stages_renders_in_console() -> None:
    """ConsoleRenderer must display funnel stages when present."""
    stages = {"generated": 10, "risk_denied": 1, "entry_blocked": 2,
              "cluster_blocked": 0, "guardrail_blocked": 1, "qty_zero": 2,
              "submitted": 4, "accepted": 4, "filled": 3, "reconciled": 3}
    s = ConsoleSummary.build(run_id="fs3", equity=1_000_000.0, open_position_count=0,
                             funnel_stages=stages)
    out = ConsoleRenderer().render(s)
    assert "generated" in out
    assert "submitted" in out
    assert "reconciled" in out


def test_funnel_stages_absent_shows_legacy_format() -> None:
    """When funnel_stages is empty, renderer falls back to legacy format."""
    s = ConsoleSummary.build(run_id="fs4", equity=1_000_000.0, open_position_count=0)
    out = ConsoleRenderer().render(s)
    assert "DECISION FUNNEL" in out
    assert "candidates" in out


# ─────────────────────────────────────────────────────────────────────────── #
# 3. R1-v2: execution_leg_id on partial fills
# ─────────────────────────────────────────────────────────────────────────── #

def _make_tracker(tmp_path: Path):
    from stock_swing.tracking.pnl_tracker import PnLTracker
    return PnLTracker(project_root=tmp_path)


def test_partial_fill_has_unique_execution_leg_id(tmp_path: Path) -> None:
    """AC (R1-v2): each partial fill lot must have a unique execution_leg_id.

    Regression: before R1-v2, partial fills had no execution_leg_id.
    This made it impossible to uniquely identify individual fill legs.
    """
    tracker = _make_tracker(tmp_path)
    tracker.record_submission(
        symbol="AAPL", strategy_id="test", side="buy",
        qty=20, price=100.0, broker_order_id="ord-001", decision_id="dec-001",
    )
    time.sleep(0.01)

    # Partial exit: close 10 of 20 shares
    tracker.record_exit("AAPL", exit_price=110.0, exit_qty=10, exit_reason="trailing_stop")
    time.sleep(0.01)
    # Second partial exit: close remaining 10
    tracker.record_exit("AAPL", exit_price=115.0, exit_qty=10, exit_reason="time_based")

    closed = [t for t in tracker.state.trades if t.get("status") == "closed"]
    assert len(closed) == 2

    # The partial-close leg must have execution_leg_id
    partial_legs = [t for t in closed if t.get("execution_leg_id") is not None]
    assert len(partial_legs) >= 1, "At least the first partial-close leg must have execution_leg_id"

    # All present execution_leg_ids must be unique
    all_leg_ids = [t["execution_leg_id"] for t in partial_legs]
    assert len(set(all_leg_ids)) == len(all_leg_ids), "execution_leg_id must be unique"


def test_full_close_has_no_execution_leg_id(tmp_path: Path) -> None:
    """Full close (not partial) should NOT have execution_leg_id set."""
    tracker = _make_tracker(tmp_path)
    tracker.record_submission(
        symbol="MSFT", strategy_id="test", side="buy",
        qty=10, price=200.0, broker_order_id="ord-002", decision_id="dec-002",
    )
    time.sleep(0.01)
    tracker.record_exit("MSFT", exit_price=210.0, exit_reason="trailing_stop")

    closed = [t for t in tracker.state.trades if t.get("status") == "closed"]
    assert len(closed) == 1
    assert closed[0].get("execution_leg_id") is None, (
        "Full close should not have execution_leg_id"
    )


# ─────────────────────────────────────────────────────────────────────────── #
# 4. R6-v2: status separation in to_dict()
# ─────────────────────────────────────────────────────────────────────────── #

def test_last_run_status_in_to_dict() -> None:
    """R6-v2: to_dict()['run']['last_run'] must be present with status and as_of."""
    s = ConsoleSummary.build(run_id="sr1", equity=1_000_000.0, open_position_count=0)
    d = s.to_dict()
    last_run = d["run"].get("last_run")
    assert last_run is not None, "run.last_run must exist"
    assert "status" in last_run
    assert "as_of" in last_run


def test_data_quality_status_in_to_dict() -> None:
    """R6-v2: to_dict()['run']['data_quality'] must include ledger_gate_status."""
    s = ConsoleSummary.build(
        run_id="sr2",
        equity=1_000_000.0,
        open_position_count=0,
        ledger_gate_status="VALID",
    )
    d = s.to_dict()
    dq = d["run"].get("data_quality")
    assert dq is not None, "run.data_quality must exist"
    assert dq["status"] == "VALID"
    assert "as_of" in dq


def test_data_quality_invalid_propagates() -> None:
    s = ConsoleSummary.build(
        run_id="sr3",
        equity=1_000_000.0,
        open_position_count=0,
        ledger_gate_status="INVALID",
    )
    assert s.to_dict()["run"]["data_quality"]["status"] == "INVALID"
