"""Tests for open position signal summary (entry signal display in console).

Validates:
  - get_open_position_signal_summary() aggregates multiple lots per symbol
  - entry_signal_strength (ess) avg/min/max computed correctly
  - broker data joined when supplied
  - ConsoleRenderer shows OPEN POSITIONS table with ess column
  - None ess handled gracefully (legacy trades without signal data)
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from stock_swing.reporting.console_renderer import ConsoleRenderer
from stock_swing.reporting.console_summary import ConsoleSummary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_trade(
    symbol: str,
    qty: int = 10,
    entry_price: float = 100.0,
    ess: float | None = 0.75,
    asset_class: str = "stock",
    entry_time: str = "2026-07-20T09:35:00",
) -> dict[str, Any]:
    return {
        "trade_id": f"t-{symbol}-1",
        "symbol": symbol,
        "qty": qty,
        "entry_price": entry_price,
        "entry_signal_strength": ess,
        "asset_class": asset_class,
        "status": "open",
        "entry_time": entry_time,
        "peak_price": entry_price,
    }


def _make_tracker_with_trades(trades: list[dict]) -> Any:
    """Return a minimal PnlTracker-like object with the given open trades."""
    from stock_swing.tracking.pnl_tracker import PnLTracker
    tracker = MagicMock(spec=PnLTracker)
    # Attach real method
    tracker.state = SimpleNamespace(trades=trades)
    tracker.get_open_position_signal_summary = lambda **kw: (
        PnLTracker.get_open_position_signal_summary(tracker, **kw)
    )
    return tracker


# ---------------------------------------------------------------------------
# get_open_position_signal_summary – unit tests
# ---------------------------------------------------------------------------

class TestGetOpenPositionSignalSummary:
    def _call(self, trades, broker_positions=None):
        from stock_swing.tracking.pnl_tracker import PnLTracker
        tracker = MagicMock(spec=PnLTracker)
        tracker.state = SimpleNamespace(trades=trades)
        return PnLTracker.get_open_position_signal_summary(
            tracker, broker_positions=broker_positions
        )

    def test_single_position_no_broker(self):
        trades = [_open_trade("NVDA", qty=5, entry_price=120.0, ess=0.80)]
        result = self._call(trades)
        assert len(result) == 1
        row = result[0]
        assert row["symbol"] == "NVDA"
        assert row["total_qty"] == 5
        assert row["lots"] == 1
        assert row["avg_entry_price"] == pytest.approx(120.0)
        assert row["avg_ess"] == pytest.approx(0.80)

    def test_two_lots_same_symbol_aggregated(self):
        """Multiple lots per symbol must be aggregated into one row."""
        trades = [
            _open_trade("NVDA", qty=5, entry_price=120.0, ess=0.60),
            _open_trade("NVDA", qty=5, entry_price=130.0, ess=0.80),
        ]
        result = self._call(trades)
        assert len(result) == 1
        row = result[0]
        assert row["symbol"] == "NVDA"
        assert row["total_qty"] == 10
        assert row["lots"] == 2
        # weighted avg entry: (120*5 + 130*5) / 10 = 125
        assert row["avg_entry_price"] == pytest.approx(125.0)
        # avg ess: (0.60 + 0.80) / 2 = 0.70
        assert row["avg_ess"] == pytest.approx(0.70)
        assert row["min_ess"] == pytest.approx(0.60)
        assert row["max_ess"] == pytest.approx(0.80)

    def test_none_ess_handled_gracefully(self):
        """Legacy trades without entry_signal_strength return None for ess fields."""
        trades = [_open_trade("ADBE", qty=3, entry_price=220.0, ess=None)]
        result = self._call(trades)
        assert result[0]["avg_ess"] is None
        assert result[0]["min_ess"] is None
        assert result[0]["max_ess"] is None

    def test_mixed_ess_availability(self):
        """One lot with ess, one without – only the available value used."""
        trades = [
            _open_trade("MSFT", qty=5, entry_price=390.0, ess=0.53),
            _open_trade("MSFT", qty=5, entry_price=400.0, ess=None),
        ]
        result = self._call(trades)
        row = result[0]
        # Only one value available: avg = 0.53
        assert row["avg_ess"] == pytest.approx(0.53)

    def test_broker_positions_joined(self):
        """Broker unrealized_plpc / market_value / current_price merged."""
        trades = [_open_trade("NVDA", qty=5, entry_price=100.0, ess=0.80)]
        broker = {
            "NVDA": {
                "current_price": 110.0,
                "market_value": 550.0,
                "unrealized_plpc": 0.10,
                "unrealized_pl": 50.0,
            }
        }
        result = self._call(trades, broker_positions=broker)
        row = result[0]
        assert row["current_price"] == pytest.approx(110.0)
        assert row["market_value"] == pytest.approx(550.0)
        assert row["unrealized_plpc"] == pytest.approx(0.10)
        assert row["unrealized_pnl"] == pytest.approx(50.0)

    def test_multiple_symbols_separate_rows(self):
        trades = [
            _open_trade("NVDA", qty=5, ess=0.80),
            _open_trade("AMD",  qty=3, ess=0.60),
            _open_trade("MSFT", qty=8, ess=0.70),
        ]
        result = self._call(trades)
        assert len(result) == 3
        symbols = {r["symbol"] for r in result}
        assert symbols == {"NVDA", "AMD", "MSFT"}

    def test_sorted_by_abs_unrealized_pnl_desc(self):
        """Rows with larger abs(unrealized_pnl) come first."""
        trades = [
            _open_trade("A", qty=1, ess=0.5),
            _open_trade("B", qty=1, ess=0.5),
        ]
        broker = {
            "A": {"current_price": 100.0, "market_value": 100.0, "unrealized_plpc": 0.05, "unrealized_pl": 5.0},
            "B": {"current_price": 100.0, "market_value": 100.0, "unrealized_plpc": -0.15, "unrealized_pl": -15.0},
        }
        result = self._call(trades, broker_positions=broker)
        # B has higher abs pnl
        assert result[0]["symbol"] == "B"
        assert result[1]["symbol"] == "A"

    def test_excludes_non_open_trades(self):
        """Closed and quarantined trades must not appear."""
        trades = [
            _open_trade("NVDA", qty=5, ess=0.80),
            {**_open_trade("AMD", qty=3, ess=0.60), "status": "closed"},
            {**_open_trade("MSFT", qty=2, ess=0.70), "status": "quarantined"},
        ]
        result = self._call(trades)
        assert len(result) == 1
        assert result[0]["symbol"] == "NVDA"

    def test_empty_positions_returns_empty_list(self):
        result = self._call([])
        assert result == []


# ---------------------------------------------------------------------------
# ConsoleRenderer – OPEN POSITIONS table rendering
# ---------------------------------------------------------------------------

class TestConsoleRendererOpenPositions:
    def _build_summary(self, position_details: list[dict]) -> ConsoleSummary:
        return ConsoleSummary.build(
            run_id="test",
            equity=1_000_000.0,
            open_position_count=len(position_details),
            open_position_details=position_details,
        )

    def test_positions_table_appears_when_details_present(self):
        details = [
            {
                "symbol": "NVDA", "total_qty": 5, "lots": 1,
                "avg_entry_price": 120.0, "avg_ess": 0.80,
                "min_ess": 0.80, "max_ess": 0.80,
                "asset_class": "stock",
                "current_price": 125.0, "unrealized_plpc": 0.042,
                "unrealized_pnl": 25.0, "market_value": 625.0,
            }
        ]
        d = self._build_summary(details)
        renderer = ConsoleRenderer()
        output = renderer.render(d)
        assert "OPEN POSITIONS" in output
        assert "NVDA" in output
        assert "0.80" in output, "ess value must appear"

    def test_positions_section_absent_when_no_details(self):
        d = self._build_summary([])
        renderer = ConsoleRenderer()
        output = renderer.render(d)
        assert "OPEN POSITIONS" not in output

    def test_none_ess_renders_as_na(self):
        details = [
            {
                "symbol": "ADBE", "total_qty": 3, "lots": 1,
                "avg_entry_price": 220.0, "avg_ess": None,
                "min_ess": None, "max_ess": None,
                "asset_class": "stock",
                "current_price": None, "unrealized_plpc": None,
                "unrealized_pnl": None, "market_value": None,
            }
        ]
        d = self._build_summary(details)
        renderer = ConsoleRenderer()
        output = renderer.render(d)
        assert "ADBE" in output
        assert " N/A" in output  # ess and/or price shown as N/A

    def test_multi_lot_shows_x_tag(self):
        details = [
            {
                "symbol": "MSFT", "total_qty": 10, "lots": 2,
                "avg_entry_price": 395.0, "avg_ess": 0.58,
                "min_ess": 0.53, "max_ess": 0.63,
                "asset_class": "stock",
                "current_price": 401.0, "unrealized_plpc": 0.015,
                "unrealized_pnl": 60.0, "market_value": 4010.0,
            }
        ]
        d = self._build_summary(details)
        renderer = ConsoleRenderer()
        output = renderer.render(d)
        assert "x2" in output, "multi-lot tag x2 must appear"

    def test_etf_shows_e_asset_class(self):
        details = [
            {
                "symbol": "SMH", "total_qty": 5, "lots": 1,
                "avg_entry_price": 230.0, "avg_ess": 0.65,
                "min_ess": 0.65, "max_ess": 0.65,
                "asset_class": "etf",
                "current_price": 235.0, "unrealized_plpc": 0.022,
                "unrealized_pnl": 25.0, "market_value": 1175.0,
            }
        ]
        d = self._build_summary(details)
        renderer = ConsoleRenderer()
        output = renderer.render(d)
        assert " E " in output or " E\n" in output or "  E " in output
