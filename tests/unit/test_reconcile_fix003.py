"""FIX-003: recently_sold_symbols time window + export mapping regression tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def test_recently_sold_old_sell_not_in_window():
    """A symbol sold more than 30 minutes ago must not remain suppressed."""
    from stock_swing.cli.reconcile_orders import RECENTLY_SOLD_WINDOW_MINUTES, _build_recently_sold_symbols

    old_sell_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    symbols = _build_recently_sold_symbols({"AAPL": [{"updated_at": old_sell_time}]})

    assert RECENTLY_SOLD_WINDOW_MINUTES == 30
    assert "AAPL" not in symbols


def test_recently_sold_new_sell_in_window():
    """A recent sell must keep the symbol in the suppression window."""
    from stock_swing.cli.reconcile_orders import _build_recently_sold_symbols

    recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    symbols = _build_recently_sold_symbols({"MSFT": [{"filled_at": recent}]})

    assert "MSFT" in symbols


def test_sell_then_rebuy_same_symbol_not_suppressed():
    """Regression: historical sells must not suppress a fresh re-buy forever."""
    from stock_swing.cli.reconcile_orders import _build_recently_sold_symbols

    old_sell_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    symbols = _build_recently_sold_symbols({"NVDA": [{"filled_at": old_sell_time}]})

    assert "NVDA" not in symbols, "2h-old sell should not suppress new broker position"


def test_closed_trade_export_mapping_prefers_qty_and_pnl_aliases():
    """closed_trades export rows must map qty/pnl into quantity/realized_pnl."""
    from stock_swing.cli.paper_demo import _build_closed_trade_export_row

    row = _build_closed_trade_export_row({
        "trade_id": "T1",
        "symbol": "AAPL",
        "qty": 12,
        "pnl": 345.67,
    })

    assert row["quantity"] == 12
    assert row["realized_pnl"] == 345.67
