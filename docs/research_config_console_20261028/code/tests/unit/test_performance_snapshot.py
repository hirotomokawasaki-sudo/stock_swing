"""Tests for performance snapshot builder."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from stock_swing.reporting.performance_snapshot import PerformanceSnapshot, build_snapshot


def test_performance_snapshot_to_dict() -> None:
    """Test PerformanceSnapshot to_dict conversion."""
    snapshot = PerformanceSnapshot(
        equity=1_000_000.0,
        buying_power=250_000.0,
        account_status="ACTIVE",
        baseline_equity=1_000_000.0,
        cumulative_realized_pnl=-4710.27,
        unrealized_pnl=-1500.0,
        total_pnl=-6210.27,
        closed_trades=67,
        winning_trades=35,
        losing_trades=31,
        win_rate=0.5224,
        avg_return_per_trade=0.0027,
        avg_pnl_per_trade=-70.3,
        max_drawdown_pct=0.0017,
        trading_days=1,
        open_positions=[],
        positions_source="broker",
        current_prices={},
        recent_trades=[],
        tracking_context={},
        alerts=[],
    )

    result = snapshot.to_dict()
    assert result["equity"] == 1_000_000.0
    assert result["cumulative_realized_pnl"] == -4710.27
    assert result["unrealized_pnl"] == -1500.0
    assert result["total_pnl"] == -6210.27
    assert result["closed_trades"] == 67
    assert result["win_rate"] == 0.5224


def test_build_snapshot_with_mock_broker() -> None:
    """Test build_snapshot with mocked broker."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        (project_root / "data" / "tracking").mkdir(parents=True)
        (project_root / "data" / "audits").mkdir(parents=True)

        # Create minimal pnl_state.json
        state = {
            "total_trades": 10,
            "cumulative_realized_pnl": -100.0,
            "trades": [],
            "daily_snapshots": [],
            "strategy_daily_snapshots": [],
            "broker_account_id": "test",
            "baseline_date": "2026-05-12",
            "baseline_equity": 100000.0,
            "tracking_label": "test",
            "performance_scope": "test",
            "archived_from_account_id": None,
            "archive_path": None,
            "migration_note_path": None,
            "max_drawdown_pct": 0.0,
            "peak_equity": 100000.0,
            "last_updated": "2026-05-15T00:00:00Z",
        }
        import json
        (project_root / "data" / "tracking" / "pnl_state.json").write_text(json.dumps(state))

        # Mock broker client
        mock_broker = MagicMock()
        mock_broker.fetch_account.return_value.payload = {
            "equity": 99_900.0,
            "buying_power": 25_000.0,
            "status": "ACTIVE",
        }
        mock_broker.fetch_positions.return_value.payload = [
            {
                "symbol": "AMAT",
                "qty": "10",
                "avg_entry_price": "100.0",
                "current_price": "105.0",
                "unrealized_pl": "50.0",
                "unrealized_plpc": "0.05",
                "side": "long",
                "market_value": "1050.0",
                "cost_basis": "1000.0",
            }
        ]

        with patch.dict("os.environ", {
            "BROKER_API_KEY": "test",
            "BROKER_API_SECRET": "test",
            "BROKER_BASE_URL": "https://test",
        }):
            with patch("stock_swing.reporting.performance_snapshot.BrokerClient", return_value=mock_broker):
                snapshot = build_snapshot(project_root)

                assert snapshot.equity == 99_900.0
                assert snapshot.buying_power == 25_000.0
                assert snapshot.account_status == "ACTIVE"
                assert snapshot.cumulative_realized_pnl == -100.0
                assert snapshot.unrealized_pnl == 50.0
                assert snapshot.total_pnl == -50.0
                assert snapshot.positions_source == "broker"
                assert len(snapshot.open_positions) == 1
                assert snapshot.open_positions[0]["symbol"] == "AMAT"


def test_build_snapshot_generates_alerts() -> None:
    """Test alert generation in build_snapshot."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        (project_root / "data" / "tracking").mkdir(parents=True)
        (project_root / "data" / "audits").mkdir(parents=True)

        state = {
            "total_trades": 10,
            "cumulative_realized_pnl": -10000.0,
            "trades": [],
            "daily_snapshots": [],
            "strategy_daily_snapshots": [],
            "broker_account_id": "test",
            "baseline_date": "2026-05-12",
            "baseline_equity": 100000.0,
            "tracking_label": "test",
            "performance_scope": "test",
            "archived_from_account_id": None,
            "archive_path": None,
            "migration_note_path": None,
            "max_drawdown_pct": 0.0,
            "peak_equity": 100000.0,
            "last_updated": "2026-05-15T00:00:00Z",
        }
        import json
        (project_root / "data" / "tracking" / "pnl_state.json").write_text(json.dumps(state))

        mock_broker = MagicMock()
        mock_broker.fetch_account.return_value.payload = {
            "equity": 80_000.0,
            "buying_power": 25_000.0,
            "status": "ACTIVE",
        }
        mock_broker.fetch_positions.return_value.payload = [
            {
                "symbol": "AMAT",
                "qty": "100",
                "avg_entry_price": "100.0",
                "current_price": "90.0",
                "unrealized_pl": "-1000.0",
                "unrealized_plpc": "-0.1",
                "side": "long",
                "market_value": "9000.0",
                "cost_basis": "10000.0",
            }
        ]

        with patch.dict("os.environ", {
            "BROKER_API_KEY": "test",
            "BROKER_API_SECRET": "test",
            "BROKER_BASE_URL": "https://test",
        }):
            with patch("stock_swing.reporting.performance_snapshot.BrokerClient", return_value=mock_broker):
                snapshot = build_snapshot(
                    project_root,
                    alert_unrealized_threshold=-500.0,
                    alert_total_pnl_pct_threshold=-0.05,
                )

                # Should have alerts
                assert len(snapshot.alerts) >= 1
                
                # Check unrealized alert
                unrealized_alerts = [a for a in snapshot.alerts if a["type"] == "unrealized_pnl"]
                assert len(unrealized_alerts) == 1
                assert unrealized_alerts[0]["level"] == "warning"
                assert unrealized_alerts[0]["value"] == -1000.0
                
                # Check total pnl alert
                total_pnl_alerts = [a for a in snapshot.alerts if a["type"] == "total_pnl_pct"]
                assert len(total_pnl_alerts) == 1
                assert total_pnl_alerts[0]["level"] == "warning"
