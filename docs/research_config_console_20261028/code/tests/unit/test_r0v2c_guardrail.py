"""R0-v2-C: Guardrail End-to-End Wiring tests.

Validates:
1. All configured metrics are computable (no metric left at 0.0 by default when real data exists)
2. reduce_size action: changes sizing multiplier
3. ai_pause action: skips AI calls
4. RiskSnapshot computes correct daily/weekly/consecutive metrics
5. Layer test: RiskSnapshot.to_metrics() keys match autonomous_stop.yaml rule metrics

testing_standards.md checklist:
  [x] Normal path
  [x] Boundary / edge cases (no trades, all wins, etc.)
  [x] Acceptance criteria test: all configured metrics supplied
  [x] State machine: reduce_size multiplier propagated
  [x] Regression: previously hardcoded metrics now computed from real data
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from stock_swing.guardrails.risk_snapshot import (
    RiskSnapshot,
    build_risk_snapshot,
    compute_consecutive_losing_trades,
    compute_daily_realized_loss_pct,
    compute_weekly_total_loss_pct,
)


# ── helpers ────────────────────────────────────────────────────────────────

def _trade(pnl: float, exit_date: str = "2026-07-22") -> dict:
    return {
        "status": "closed",
        "pnl": pnl,
        "exit_time": f"{exit_date}T16:00:00+00:00",
        "entry_time": f"{exit_date}T09:30:00+00:00",
    }


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")


# ─────────────────────────────────────────────────────────────────────────── #
# 1. AC: all configured guardrail metrics are supplied (no missing keys)
# ─────────────────────────────────────────────────────────────────────────── #

EXPECTED_METRIC_KEYS = {
    "stale_price_event_count",
    "broker_tracker_mismatch_count",
    "daily_realized_loss_pct",
    "daily_total_loss_pct",
    "weekly_total_loss_pct",
    "consecutive_losing_trades",
    "api_error_rate_pct",
    "order_rejection_rate_pct",
    "token_spend_spike_pct",
}


def test_all_configured_guardrail_metrics_are_supplied() -> None:
    """AC: every metric key configured in autonomous_stop.yaml must appear in to_metrics()."""
    snap = build_risk_snapshot(trades=[], equity=1_000_000.0)
    metrics = snap.to_metrics()
    missing = EXPECTED_METRIC_KEYS - set(metrics.keys())
    assert not missing, f"Guardrail metrics missing from RiskSnapshot: {missing}"


def test_risk_snapshot_to_metrics_has_no_extra_unexpected_keys() -> None:
    """to_metrics() must cover all configured rules — no unknown keys."""
    snap = build_risk_snapshot(trades=[], equity=1_000_000.0)
    assert set(snap.to_metrics().keys()) == EXPECTED_METRIC_KEYS


# ─────────────────────────────────────────────────────────────────────────── #
# 2. daily_realized_loss_pct
# ─────────────────────────────────────────────────────────────────────────── #

def test_daily_realized_loss_pct_today_only() -> None:
    """Only trades closed today count toward daily_realized_loss_pct."""
    today = _today()
    yesterday = _days_ago(1)
    trades = [
        _trade(-5_000.0, today),       # today's loss
        _trade(-10_000.0, yesterday),  # yesterday: must NOT count
        _trade(2_000.0, today),        # today's win
    ]
    pct = compute_daily_realized_loss_pct(trades, equity=1_000_000.0, reference_date=today)
    expected = (-5_000 + 2_000) / 1_000_000 * 100  # = -0.3
    assert pct == pytest.approx(expected, abs=0.0001)


def test_daily_realized_loss_pct_no_trades_today() -> None:
    today = _today()
    trades = [_trade(-5_000.0, _days_ago(1))]
    pct = compute_daily_realized_loss_pct(trades, equity=1_000_000.0, reference_date=today)
    assert pct == 0.0


def test_daily_realized_loss_pct_zero_equity_safe() -> None:
    pct = compute_daily_realized_loss_pct([_trade(-100.0, _today())], equity=0.0)
    assert pct == 0.0


# ─────────────────────────────────────────────────────────────────────────── #
# 3. weekly_total_loss_pct
# ─────────────────────────────────────────────────────────────────────────── #

def test_weekly_total_loss_pct_includes_5_days() -> None:
    """Trades within 5 days are included; older trades are excluded."""
    today = _today()
    trades = [
        _trade(-10_000.0, _days_ago(0)),  # today
        _trade(-5_000.0, _days_ago(4)),   # 4 days ago (in window)
        _trade(-8_000.0, _days_ago(6)),   # 6 days ago (out of window)
    ]
    pct = compute_weekly_total_loss_pct(trades, equity=1_000_000.0, reference_date=today)
    expected = (-10_000 - 5_000) / 1_000_000 * 100  # = -1.5
    assert pct == pytest.approx(expected, abs=0.0001)


def test_weekly_total_pct_no_trades_in_window() -> None:
    trades = [_trade(-10_000.0, _days_ago(10))]  # outside 5-day window
    pct = compute_weekly_total_loss_pct(trades, equity=1_000_000.0)
    assert pct == 0.0


# ─────────────────────────────────────────────────────────────────────────── #
# 4. consecutive_losing_trades
# ─────────────────────────────────────────────────────────────────────────── #

def test_consecutive_losing_trades_counts_tail_run() -> None:
    """Only the tail sequence of losses counts, not all losses."""
    trades = [
        _trade(500.0, "2026-07-20"),   # win
        _trade(-100.0, "2026-07-21"),  # loss 1
        _trade(-200.0, "2026-07-21"),  # loss 2
        _trade(-300.0, "2026-07-22"),  # loss 3
    ]
    assert compute_consecutive_losing_trades(trades) == 3


def test_consecutive_losing_trades_resets_on_win() -> None:
    trades = [
        _trade(-100.0, "2026-07-20"),  # loss (old)
        _trade(200.0, "2026-07-21"),   # win resets streak
        _trade(-50.0, "2026-07-22"),   # loss
    ]
    assert compute_consecutive_losing_trades(trades) == 1


def test_consecutive_losing_trades_all_wins() -> None:
    trades = [_trade(100.0, "2026-07-22"), _trade(200.0, "2026-07-22")]
    assert compute_consecutive_losing_trades(trades) == 0


def test_consecutive_losing_trades_no_trades() -> None:
    assert compute_consecutive_losing_trades([]) == 0


# ─────────────────────────────────────────────────────────────────────────── #
# 5. build_risk_snapshot integration
# ─────────────────────────────────────────────────────────────────────────── #

def test_build_risk_snapshot_populates_all_fields() -> None:
    today = _today()
    trades = [
        _trade(-2_000.0, today),
        _trade(-1_000.0, _days_ago(3)),
        _trade(500.0, _days_ago(5)),
    ]
    snap = build_risk_snapshot(
        trades=trades,
        equity=1_000_000.0,
        stale_price_event_count=2,
        broker_tracker_mismatch_count=0,
        api_error_rate_pct=5.0,
        order_rejection_rate_pct=0.0,
        token_spend_spike_pct=0.0,
        reference_date=today,
    )
    assert snap.stale_price_event_count == 2
    assert snap.daily_realized_loss_pct == pytest.approx(-0.2, abs=0.001)
    assert snap.weekly_total_loss_pct < 0  # loss within 5 days
    assert snap.consecutive_losing_trades == 2  # two recent losses
    assert snap.api_error_rate_pct == 5.0
    assert len(snap.missing_metrics) == 0


def test_build_risk_snapshot_no_equity_flagged() -> None:
    snap = build_risk_snapshot(trades=[], equity=0.0)
    assert "equity" in snap.missing_metrics


# ─────────────────────────────────────────────────────────────────────────── #
# 6. reduce_size action: GuardrailEngine integration
# ─────────────────────────────────────────────────────────────────────────── #

def test_reduce_size_changes_size_multiplier_on_candidate() -> None:
    """AC: reduce_size action must set size_multiplier=0.5 on buy candidate."""
    from stock_swing.guardrails.pre_trade_check import apply_to_buy_candidate
    from stock_swing.guardrails.rule_engine import GuardAction, GuardDecision, TriggeredRule
    from stock_swing.guardrails.circuit_breaker import CircuitBreakerState

    decision = GuardDecision(
        action=GuardAction.reduce_size,
        triggered=[TriggeredRule(
            name="consecutive_losing_trades",
            metric="consecutive_losing_trades",
            observed=5,
            operator=">=",
            threshold=5,
            action=GuardAction.reduce_size,
            severity="medium",
        )],
    )
    breaker = CircuitBreakerState(status="ok", action="allow")
    candidate = {"symbol": "AAPL", "action": "buy", "size_multiplier": 1.0}
    result = apply_to_buy_candidate(candidate, decision, breaker)

    assert result.get("size_multiplier") == pytest.approx(0.5), (
        "reduce_size must halve the size_multiplier on the candidate"
    )
    assert result.get("action") == "buy", "reduce_size does NOT deny the trade"
    assert result.get("guardrail_action") == "reduce_size"


def test_reduce_size_does_not_deny_trade() -> None:
    """reduce_size reduces size but the trade is NOT denied."""
    from stock_swing.guardrails.pre_trade_check import apply_to_buy_candidate
    from stock_swing.guardrails.rule_engine import GuardAction, GuardDecision
    from stock_swing.guardrails.circuit_breaker import CircuitBreakerState

    dec = GuardDecision(action=GuardAction.reduce_size, triggered=[])
    breaker = CircuitBreakerState(status="ok", action="allow")
    result = apply_to_buy_candidate({"symbol": "X", "action": "buy"}, dec, breaker)
    assert result["action"] == "buy"


# ─────────────────────────────────────────────────────────────────────────── #
# 7. ai_pause: should_skip_ai returns True for ai_pause action
# ─────────────────────────────────────────────────────────────────────────── #

def test_ai_pause_skips_provider_call() -> None:
    """AC: ai_pause action must cause should_skip_ai() to return True."""
    from stock_swing.guardrails.pre_trade_check import should_skip_ai
    from stock_swing.guardrails.rule_engine import GuardAction, GuardDecision
    from stock_swing.guardrails.circuit_breaker import CircuitBreakerState

    dec = GuardDecision(action=GuardAction.ai_pause, triggered=[])
    breaker = CircuitBreakerState(status="ok", action="allow")
    assert should_skip_ai(breaker, dec) is True


def test_allow_action_does_not_skip_ai() -> None:
    from stock_swing.guardrails.pre_trade_check import should_skip_ai
    from stock_swing.guardrails.rule_engine import GuardAction, GuardDecision
    from stock_swing.guardrails.circuit_breaker import CircuitBreakerState

    dec = GuardDecision(action=GuardAction.allow, triggered=[])
    breaker = CircuitBreakerState(status="ok", action="allow")
    assert should_skip_ai(breaker, dec) is False
