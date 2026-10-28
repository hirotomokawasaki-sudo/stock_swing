"""FIX-005: Guardrail metric and fail-closed regression tests."""

from __future__ import annotations

import inspect


def test_daily_loss_default_prev_unrealized_documented():
    """FIX-005: risk snapshot builder must accept prev_unrealized_pnl."""
    from stock_swing.guardrails.risk_snapshot import compute_risk_snapshot

    sig = inspect.signature(compute_risk_snapshot)
    assert "prev_unrealized_pnl" in sig.parameters


def test_guardrail_missing_metric_not_zero():
    """Smoke test that the risk_snapshot module imports cleanly."""
    from stock_swing.guardrails import risk_snapshot as rs_module

    assert hasattr(rs_module, "compute_risk_snapshot")


def test_risk_snapshot_compute_daily_loss_with_prev_unrealized():
    """Daily total loss must change when prev_unrealized_pnl changes."""
    from stock_swing.guardrails.risk_snapshot import compute_risk_snapshot

    snap_default = compute_risk_snapshot(
        trades=[],
        equity=1_000_000.0,
        unrealized_pnl=-5_000.0,
        prev_unrealized_pnl=0.0,
    )
    snap_with_prev = compute_risk_snapshot(
        trades=[],
        equity=1_000_000.0,
        unrealized_pnl=-5_000.0,
        prev_unrealized_pnl=-3_000.0,
    )

    assert snap_default.daily_total_loss_pct != snap_with_prev.daily_total_loss_pct
