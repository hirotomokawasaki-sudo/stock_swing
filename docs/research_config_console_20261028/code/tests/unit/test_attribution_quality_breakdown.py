"""2026-08-14: Tests for PnlTracker.get_attribution_quality_breakdown() and
console rendering.

Motivation (roadmap gap analysis, docs/daily_logs/2026-08-14.md): a large
fraction of closed trades (197/228 as of 2026-08-14) carry
original_strategy_id="broker_reconstructed" -- reconstructed purely from
broker fill history with no decision provenance, rather than having gone
through an actual strategy decision. Real-data check found these
untracked-origin trades perform materially worse (PF=0.882) than trades
attributable to a real strategy decision (PF=1.317), meaning the commonly-
quoted blended "overall PF" understates how well the currently-running
strategy logic is actually doing.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from stock_swing.tracking.pnl_tracker import PnLTracker
from stock_swing.reporting.console_summary import ConsoleSummary
from stock_swing.reporting.console_renderer import ConsoleRenderer


def _record_trade(
    tracker: PnLTracker,
    symbol: str,
    pnl: float,
    original_strategy_id: str,
    idx: int,
) -> None:
    oid = f"oid-{original_strategy_id}-{idx}"
    tracker.record_submission(
        symbol, "strat", "buy", 10, 100.0,
        broker_order_id=oid, decision_id=f"did-{original_strategy_id}-{idx}",
        original_strategy_id=original_strategy_id,
    )
    tracker.record_exit(
        symbol, exit_price=100.0 + pnl / 10, exit_qty=10,
        broker_order_id=oid, exit_reason="trailing_stop" if pnl >= 0 else "stop_loss",
    )


def _make_tracker(tmp_path: Path) -> PnLTracker:
    tracker = PnLTracker(tmp_path)
    # Attributable trades (real strategy origin): 2 wins, 1 loss
    for i, (sym, pnl) in enumerate([("NVDA", 500.0), ("AMD", 300.0), ("INTC", -200.0)]):
        _record_trade(tracker, sym, pnl, "breakout_momentum_v1", i)

    # Untracked-origin trades (broker_reconstructed): 1 win, 2 losses
    for i, (sym, pnl) in enumerate([("HPE", 100.0), ("ORCL", -400.0), ("IBM", -300.0)]):
        _record_trade(tracker, sym, pnl, "broker_reconstructed", i)

    # Untracked-origin trades (reconciled_from_broker): 1 loss
    _record_trade(tracker, "DELL", -150.0, "reconciled_from_broker", 0)

    return tracker


class TestGetAttributionQualityBreakdown:
    def test_keys(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        bd = tracker.get_attribution_quality_breakdown()
        assert set(bd.keys()) == {"attributable", "untracked_origin", "all"}
        for key in bd:
            m = bd[key]
            assert "count" in m
            assert "profit_factor" in m
            assert "net_pnl" in m
            assert "win_rate" in m

    def test_attributable_bucket_counts(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        bd = tracker.get_attribution_quality_breakdown()
        attributable = bd["attributable"]
        assert attributable["count"] == 3
        assert attributable["wins"] == 2
        assert attributable["losses"] == 1

    def test_untracked_origin_bucket_merges_both_untracked_strategy_ids(self, tmp_path):
        """Both broker_reconstructed AND reconciled_from_broker must be
        merged into the same untracked_origin bucket."""
        tracker = _make_tracker(tmp_path)
        bd = tracker.get_attribution_quality_breakdown()
        untracked = bd["untracked_origin"]
        assert untracked["count"] == 4  # 3 broker_reconstructed + 1 reconciled_from_broker
        assert untracked["wins"] == 1
        assert untracked["losses"] == 3

    def test_all_bucket_is_sum_of_both(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        bd = tracker.get_attribution_quality_breakdown()
        assert bd["all"]["count"] == bd["attributable"]["count"] + bd["untracked_origin"]["count"]

    def test_profit_factor_computed_correctly_per_bucket(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        bd = tracker.get_attribution_quality_breakdown()
        # attributable: wins=500+300=800, losses=200 -> PF=4.0
        assert bd["attributable"]["profit_factor"] == 4.0
        # untracked: wins=100, losses=400+300+150=850 -> PF=100/850=0.118
        assert bd["untracked_origin"]["profit_factor"] == pytest.approx(0.118, abs=0.001)

    def test_no_untracked_trades_bucket_is_empty(self, tmp_path):
        tracker = PnLTracker(tmp_path)
        _record_trade(tracker, "NVDA", 500.0, "breakout_momentum_v1", 0)
        bd = tracker.get_attribution_quality_breakdown()
        assert bd["untracked_origin"]["count"] == 0
        assert bd["attributable"]["count"] == 1

    def test_no_closed_trades_returns_zero_counts(self, tmp_path):
        tracker = PnLTracker(tmp_path)
        bd = tracker.get_attribution_quality_breakdown()
        assert bd["attributable"]["count"] == 0
        assert bd["untracked_origin"]["count"] == 0
        assert bd["all"]["count"] == 0

    def test_missing_original_strategy_id_falls_back_to_strategy_id(self, tmp_path):
        """A trade with no original_strategy_id set (older records, or a
        direct record_submission call without the param) must fall back to
        checking strategy_id for the untracked-origin markers."""
        tracker = PnLTracker(tmp_path)
        oid = "oid-fallback-0"
        tracker.record_submission(
            "TEST", "broker_reconstructed", "buy", 10, 100.0,
            broker_order_id=oid, decision_id="did-fallback-0",
        )
        tracker.record_exit("TEST", exit_price=90.0, exit_qty=10, broker_order_id=oid, exit_reason="stop_loss")
        bd = tracker.get_attribution_quality_breakdown()
        assert bd["untracked_origin"]["count"] == 1
        assert bd["attributable"]["count"] == 0

    def test_open_trades_excluded(self, tmp_path):
        tracker = PnLTracker(tmp_path)
        tracker.record_submission(
            "OPEN1", "strat", "buy", 10, 100.0,
            broker_order_id="oid-open", decision_id="did-open",
            original_strategy_id="breakout_momentum_v1",
        )
        bd = tracker.get_attribution_quality_breakdown()
        assert bd["attributable"]["count"] == 0
        assert bd["all"]["count"] == 0


class TestConsoleSummaryIntegration:
    def test_attribution_quality_breakdown_included_in_dict(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        summary = ConsoleSummary.build(
            run_id="test", equity=1_000_000.0, open_position_count=0,
            attribution_quality_breakdown=tracker.get_attribution_quality_breakdown(),
        )
        d = summary.to_dict()
        assert "attribution_quality_breakdown" in d["portfolio"]
        assert d["portfolio"]["attribution_quality_breakdown"]["attributable"]["count"] == 3

    def test_defaults_to_empty_dict_when_omitted(self):
        summary = ConsoleSummary.build(run_id="test", equity=1_000_000.0, open_position_count=0)
        assert summary.attribution_quality_breakdown == {}


class TestConsoleRendererIntegration:
    def test_attribution_quality_section_shown_when_present(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        summary = ConsoleSummary.build(
            run_id="test", equity=1_000_000.0, open_position_count=0,
            attribution_quality_breakdown=tracker.get_attribution_quality_breakdown(),
        )
        out = ConsoleRenderer().render(summary)
        assert "ATTRIBUTION QUALITY" in out
        assert "TRACKED" in out
        assert "UNTRACKED" in out

    def test_attribution_quality_section_absent_when_empty(self):
        summary = ConsoleSummary.build(run_id="test", equity=1_000_000.0, open_position_count=0)
        out = ConsoleRenderer().render(summary)
        assert "ATTRIBUTION QUALITY" not in out

    def test_not_valid_when_ledger_invalid(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        summary = ConsoleSummary.build(
            run_id="test", equity=1_000_000.0, open_position_count=0,
            attribution_quality_breakdown=tracker.get_attribution_quality_breakdown(),
            ledger_gate_status="INVALID",
        )
        out = ConsoleRenderer().render(summary)
        assert "ATTRIBUTION QUALITY" in out
        assert "NOT_VALID" in out
