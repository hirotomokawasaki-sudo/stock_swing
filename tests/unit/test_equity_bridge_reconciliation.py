from __future__ import annotations

import json
from types import SimpleNamespace

from stock_swing.reporting.equity_bridge_reconciliation import (
    build_reconciliation_snapshot,
    compute_order_cash_realized,
    load_reconciliation_snapshot,
    summarize_account_activities,
)


def test_order_cash_realized_is_split_quantity_independent() -> None:
    orders = [
        {"symbol": "KLAC", "side": "buy", "filled_qty": "21", "filled_avg_price": "2126.92"},
        {"symbol": "KLAC", "side": "sell", "filled_qty": "210", "filled_avg_price": "238.38"},
    ]

    total, by_symbol = compute_order_cash_realized(orders, positions=[])

    assert round(total, 2) == 5_394.48
    assert round(by_symbol["KLAC"], 2) == 5_394.48


def test_order_cash_realized_adds_remaining_open_cost_basis() -> None:
    orders = [
        {"symbol": "XYZ", "side": "buy", "filled_qty": 10, "filled_avg_price": 100},
        {"symbol": "XYZ", "side": "sell", "filled_qty": 4, "filled_avg_price": 120},
    ]
    positions = [{"symbol": "XYZ", "cost_basis": 600}]

    total, _ = compute_order_cash_realized(orders, positions)

    assert total == 80


def test_activity_summary_separates_fees_and_external_cash() -> None:
    activities = [
        {"activity_type": "JNLC", "date": "2026-05-11", "net_amount": "1000000"},
        {"activity_type": "FEE", "date": "2026-05-12", "net_amount": "-1.25"},
        {"activity_type": "DIV", "date": "2026-05-13", "net_amount": "12.50"},
        {"activity_type": "SPLIT", "date": "2026-05-14", "net_amount": "0"},
    ]

    result = summarize_account_activities(activities, baseline_date="2026-05-12")

    assert result["fees"] == 1.25
    assert result["external_cash_adjustment"] == 12.50
    assert "JNLC" not in result["activity_counts"]


def test_snapshot_loader_rejects_identity_or_account_check_mismatch(tmp_path) -> None:
    snapshot = build_reconciliation_snapshot(
        generated_at="2026-10-16T00:00:00+00:00",
        broker_account_id="paper-1",
        baseline_date="2026-05-12",
        baseline_equity=1_000_000,
        tracker_realized=-56_000,
        broker_equity=950_000,
        broker_unrealized=-10_000,
        broker_order_cash_realized=-40_000,
        broker_realized_by_symbol={"A": -40_000},
        tracker_realized_by_symbol={"A": -56_000},
        fees=0,
        external_cash_adjustment=0,
        order_count=2,
        activity_count=2,
        last_filled_at="2026-10-15T00:00:00Z",
        quarantined_pnl_raw=-44_000,
        quarantine_count=6,
        tracker_trades=[],
    )
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")

    assert load_reconciliation_snapshot(
        path,
        expected_baseline_equity=1_000_000,
        expected_account_id="paper-1",
        current_trades=[],
    ) is not None
    assert load_reconciliation_snapshot(
        path,
        expected_baseline_equity=999_999,
        expected_account_id="paper-1",
        current_trades=[],
    ) is None
    assert load_reconciliation_snapshot(
        path,
        expected_baseline_equity=1_000_000,
        expected_account_id="other",
        current_trades=[],
    ) is None


def test_snapshot_loader_rejects_rewritten_historical_trade(tmp_path) -> None:
    closed_trade = {
        "trade_id": "trade-1",
        "status": "closed",
        "symbol": "XYZ",
        "qty": 10,
        "entry_price": 100,
        "exit_price": 110,
        "pnl": 100,
        "entry_time": "2026-10-14T13:30:00Z",
        "exit_time": "2026-10-15T13:30:00+00:00",
        "broker_order_id": "buy-1",
        "exit_broker_order_id": "sell-1",
    }
    snapshot = build_reconciliation_snapshot(
        generated_at="2026-10-16T00:00:00+00:00",
        broker_account_id="paper-1",
        baseline_date="2026-05-12",
        baseline_equity=1_000_000,
        tracker_realized=100,
        broker_equity=1_000_100,
        broker_unrealized=0,
        broker_order_cash_realized=100,
        broker_realized_by_symbol={"XYZ": 100},
        tracker_realized_by_symbol={"XYZ": 100},
        fees=0,
        external_cash_adjustment=0,
        order_count=2,
        activity_count=2,
        last_filled_at="2026-10-15T13:30:00Z",
        quarantined_pnl_raw=0,
        quarantine_count=0,
        tracker_trades=[closed_trade],
    )
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")

    assert load_reconciliation_snapshot(
        path,
        expected_baseline_equity=1_000_000,
        expected_account_id="paper-1",
        current_trades=[closed_trade],
    ) is not None

    rewritten = dict(closed_trade, pnl=99)
    assert load_reconciliation_snapshot(
        path,
        expected_baseline_equity=1_000_000,
        expected_account_id="paper-1",
        current_trades=[rewritten],
    ) is None


def test_paper_demo_bridge_consumes_validated_snapshot(tmp_path) -> None:
    from stock_swing.cli.paper_demo import _build_equity_bridge

    snapshot = build_reconciliation_snapshot(
        generated_at="2026-10-16T00:00:00+00:00",
        broker_account_id="paper-1",
        baseline_date="2026-05-12",
        baseline_equity=1_000_000,
        tracker_realized=-56_841.92,
        broker_equity=937_354.35,
        broker_unrealized=-11_916.01,
        broker_order_cash_realized=-50_635.06,
        broker_realized_by_symbol={"KLAC": 5_130.55},
        tracker_realized_by_symbol={"KLAC": -331.65},
        fees=94.58,
        external_cash_adjustment=0,
        order_count=805,
        activity_count=2037,
        last_filled_at="2026-10-15T13:37:13Z",
        quarantined_pnl_raw=-44_670.42,
        quarantine_count=6,
        tracker_trades=[],
    )
    audit_path = tmp_path / "data" / "audits" / "equity_bridge_reconciliation.json"
    audit_path.parent.mkdir(parents=True)
    audit_path.write_text(json.dumps(snapshot), encoding="utf-8")
    tracker = SimpleNamespace(
        project_root=tmp_path,
        state=SimpleNamespace(
            baseline_equity=1_000_000,
            cumulative_realized_pnl=-56_841.92,
            broker_account_id="paper-1",
            trades=[],
        ),
        get_quarantined_trades=lambda: [{"pnl": -44_670.42}],
    )

    result = _build_equity_bridge(
        broker_equity=937_354.35,
        pnl_tracker=tracker,
        unrealized_pnl=-11_916.01,
    )

    assert result["within_tolerance"] is True
    assert result["unexplained_diff"] == 0.0
    assert result["realized_pnl_adjustment"] == 6_206.86
    assert result["quarantined_pnl"] == -44_670.42
    assert result["quarantined_pnl_adjustment"] == 0.0
