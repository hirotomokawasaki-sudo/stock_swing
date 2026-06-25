"""Tests for P0-B: stale entry price reconciliation including broker position avg."""

from pathlib import Path
from types import SimpleNamespace

from stock_swing.cli.reconcile_orders import reconcile_stale_entry_prices
from stock_swing.tracking.pnl_tracker import PnLTracker


def _make_tracker(tmp_path: Path, symbol: str, stale_price: float, qty: int = 10) -> PnLTracker:
    tracker = PnLTracker(tmp_path)
    tracker.record_submission(
        symbol=symbol,
        strategy_id="s1",
        side="buy",
        qty=qty,
        price=stale_price,
        broker_order_id=f"{symbol.lower()}-order",
        decision_id=f"{symbol.lower()}-decision",
    )
    return tracker


class _Broker:
    """Broker stub: fill == stale but position avg == correct price."""

    def __init__(self, symbol: str, stale_price: float, correct_price: float) -> None:
        self.symbol = symbol
        self.stale_price = stale_price
        self.correct_price = correct_price

    def get_order(self, order_id: str):
        return SimpleNamespace(
            payload={
                "id": order_id,
                "status": "filled",
                "filled_avg_price": str(self.stale_price),
            }
        )

    def fetch_positions(self):
        return SimpleNamespace(
            payload=[
                {
                    "symbol": self.symbol,
                    "qty": "10",
                    "avg_entry_price": str(self.correct_price),
                }
            ]
        )


def test_p0b_corrects_when_fill_is_stale_but_position_avg_is_correct(tmp_path: Path) -> None:
    tracker = _make_tracker(tmp_path, "KLAC", stale_price=2010.21)
    broker = _Broker("KLAC", stale_price=2010.21, correct_price=245.09)

    count = reconcile_stale_entry_prices(broker, tracker)

    assert count == 1
    trade = tracker.get_open_positions()[0]
    assert abs(trade["entry_price"] - 245.09) < 0.01


def test_p0b_peak_not_left_below_corrected_entry(tmp_path: Path) -> None:
    tracker = _make_tracker(tmp_path, "KLAC", stale_price=2010.21)
    tracker.get_open_positions()[0]["peak_price"] = 2010.21
    broker = _Broker("KLAC", stale_price=2010.21, correct_price=245.09)

    reconcile_stale_entry_prices(broker, tracker)

    trade = tracker.get_open_positions()[0]
    assert trade["peak_price"] >= trade["entry_price"]


def test_p0b_no_correction_when_within_tolerance(tmp_path: Path) -> None:
    tracker = _make_tracker(tmp_path, "AAPL", stale_price=150.00)
    broker = _Broker("AAPL", stale_price=150.00, correct_price=151.00)

    count = reconcile_stale_entry_prices(broker, tracker)

    assert count == 0


def test_p0b_fill_correction_takes_priority_over_position_avg(tmp_path: Path) -> None:
    tracker = _make_tracker(tmp_path, "MSFT", stale_price=200.00)

    class PriorityBroker:
        def get_order(self, order_id):
            return SimpleNamespace(
                payload={
                    "id": order_id,
                    "status": "filled",
                    "filled_avg_price": "320.00",
                }
            )

        def fetch_positions(self):
            return SimpleNamespace(
                payload=[
                    {
                        "symbol": "MSFT",
                        "qty": "10",
                        "avg_entry_price": "325.00",
                    }
                ]
            )

    count = reconcile_stale_entry_prices(PriorityBroker(), tracker)
    assert count == 1
    trade = tracker.get_open_positions()[0]
    assert abs(trade["entry_price"] - 320.00) < 0.01
