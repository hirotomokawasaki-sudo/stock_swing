"""R2-B: Tests for get_asset_class_breakdown() and console rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

from stock_swing.tracking.pnl_tracker import PnLTracker
from stock_swing.reporting.console_summary import ConsoleSummary
from stock_swing.reporting.console_renderer import ConsoleRenderer


def _make_tracker(tmp_path: Path) -> PnLTracker:
    tracker = PnLTracker(tmp_path)
    # ETF trades: 2 wins, 1 loss
    for i, (sym, pnl, ac) in enumerate([
        ("SMH", 500.0, "etf"),
        ("SOXX", -200.0, "etf"),
        ("QQQ", 300.0, "etf"),
    ]):
        oid = f"oid-etf-{i}"
        tracker.record_submission(sym, "strat", "buy", 10, 100.0, broker_order_id=oid,
                                  decision_id=f"did-{i}", asset_class=ac)
        tracker.record_exit(sym, exit_price=100.0 + pnl / 10, exit_qty=10,
                            broker_order_id=oid, exit_reason="trailing_stop")

    # Stock trades: 1 win, 2 losses
    for i, (sym, pnl, ac) in enumerate([
        ("NVDA", 400.0, "stock"),
        ("AMD", -300.0, "stock"),
        ("INTC", -150.0, "stock"),
    ]):
        oid = f"oid-stk-{i}"
        tracker.record_submission(sym, "strat", "buy", 10, 100.0, broker_order_id=oid,
                                  decision_id=f"did-stk-{i}", asset_class=ac)
        tracker.record_exit(sym, exit_price=100.0 + pnl / 10, exit_qty=10,
                            broker_order_id=oid, exit_reason="stop_loss")
    return tracker


def test_breakdown_keys(tmp_path: Path) -> None:
    tracker = _make_tracker(tmp_path)
    bd = tracker.get_asset_class_breakdown()
    assert set(bd.keys()) == {"etf", "stock", "all"}
    for key in ("etf", "stock", "all"):
        m = bd[key]
        assert "count" in m
        assert "profit_factor" in m
        assert "net_pnl" in m
        assert "win_rate" in m


def test_breakdown_etf_counts(tmp_path: Path) -> None:
    tracker = _make_tracker(tmp_path)
    bd = tracker.get_asset_class_breakdown()
    etf = bd["etf"]
    assert etf["count"] == 3
    assert etf["wins"] == 2
    assert etf["losses"] == 1
    assert abs(etf["net_pnl"] - 600.0) < 1.0


def test_breakdown_stock_counts(tmp_path: Path) -> None:
    tracker = _make_tracker(tmp_path)
    bd = tracker.get_asset_class_breakdown()
    stk = bd["stock"]
    assert stk["count"] == 3
    assert stk["wins"] == 1
    assert stk["losses"] == 2
    assert abs(stk["net_pnl"] - (-50.0)) < 1.0


def test_breakdown_all_total(tmp_path: Path) -> None:
    tracker = _make_tracker(tmp_path)
    bd = tracker.get_asset_class_breakdown()
    assert bd["all"]["count"] == 6
    assert bd["all"]["wins"] == 3
    assert bd["all"]["losses"] == 3


def test_breakdown_pf_inf_when_no_losses(tmp_path: Path) -> None:
    tracker = PnLTracker(tmp_path)
    tracker.record_submission("SMH", "s", "buy", 10, 100.0,
                              broker_order_id="o1", decision_id="d1", asset_class="etf")
    tracker.record_exit("SMH", exit_price=110.0, exit_qty=10,
                        broker_order_id="o1", exit_reason="trailing_stop")
    bd = tracker.get_asset_class_breakdown()
    assert bd["etf"]["profit_factor"] is None  # None = infinity


def test_console_renderer_shows_etf_stock(tmp_path: Path) -> None:
    tracker = _make_tracker(tmp_path)
    breakdown = tracker.get_asset_class_breakdown()
    cs = ConsoleSummary.build(
        run_id="test",
        equity=100_000.0,
        open_position_count=0,
        asset_class_breakdown=breakdown,
    )
    renderer = ConsoleRenderer()
    output = renderer.render(cs)
    assert "ETF vs STOCK" in output
    assert "ETF" in output
    assert "STOCK" in output
    assert "PF=" in output


def test_console_summary_dict_has_breakdown(tmp_path: Path) -> None:
    tracker = _make_tracker(tmp_path)
    breakdown = tracker.get_asset_class_breakdown()
    cs = ConsoleSummary.build(
        run_id="test",
        equity=100_000.0,
        open_position_count=0,
        asset_class_breakdown=breakdown,
    )
    d = cs.to_dict()
    assert "asset_class_breakdown" in d["portfolio"]
    assert d["portfolio"]["asset_class_breakdown"]["etf"]["count"] == 3
    assert d["portfolio"]["asset_class_breakdown"]["stock"]["count"] == 3


def test_empty_breakdown_no_crash(tmp_path: Path) -> None:
    tracker = PnLTracker(tmp_path)
    bd = tracker.get_asset_class_breakdown()
    assert bd["etf"]["count"] == 0
    assert bd["stock"]["count"] == 0
    cs = ConsoleSummary.build(
        run_id="test",
        equity=100_000.0,
        open_position_count=0,
        asset_class_breakdown=bd,
    )
    renderer = ConsoleRenderer()
    # Should not raise; empty breakdown not shown
    output = renderer.render(cs)
    assert "equity" in output.lower() or "PORTFOLIO" in output
