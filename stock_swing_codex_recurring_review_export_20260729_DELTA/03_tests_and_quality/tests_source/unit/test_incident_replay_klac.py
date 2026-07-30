"""Incident replay regression tests for KLAC stale price incident (P3-B)."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from stock_swing.cli.reconcile_orders import reconcile_stale_entry_prices
from stock_swing.pricing import PriceResolver
from stock_swing.tracking.pnl_tracker import PnLTracker


FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "incidents" / "klac_20260624_stale_price.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class _BrokerStub:
    """Broker stub: fill == stale, but position avg == correct."""

    def __init__(self, fixture: dict) -> None:
        self._fixture = fixture

    def get_order(self, order_id: str):
        return SimpleNamespace(payload={
            "id": order_id,
            "status": "filled",
            "filled_avg_price": str(self._fixture["stale_entry_price"]),
        })

    def fetch_positions(self):
        return SimpleNamespace(payload=[{
            "symbol": self._fixture["symbol"],
            "qty": "10",
            "avg_entry_price": str(self._fixture["broker_position_avg_entry_price"]),
        }])

    def fetch_bars(self, symbol, **kwargs):
        b = self._fixture["stale_broker_bar"]
        return SimpleNamespace(payload={"bars": [{"c": b["close"], "t": b["timestamp"]}]})

    def fetch_latest_quote(self, symbol):
        p = self._fixture["fresh_market_price"]
        return SimpleNamespace(payload={"quote": {"bp": p - 0.01, "ap": p + 0.01}})


def test_klac_stale_entry_and_peak_repaired(tmp_path: Path) -> None:
    fixture = load_fixture()
    tracker = PnLTracker(tmp_path)
    tracker.record_submission(
        symbol=fixture["symbol"],
        strategy_id="breakout_momentum_v1",
        side="buy",
        qty=10,
        price=fixture["stale_entry_price"],
        broker_order_id="klac-buy",
        decision_id="klac-decision",
    )
    tracker.get_open_positions()[0]["peak_price"] = fixture["stale_peak_price"]

    broker = _BrokerStub(fixture)
    count = reconcile_stale_entry_prices(broker, tracker)

    assert count == 1
    trade = tracker.get_open_positions()[0]
    assert abs(trade["entry_price"] - fixture["expected"]["entry_price_after_reconcile"]) < 0.01
    assert abs(trade["peak_price"] - fixture["expected"]["peak_price_after_reconcile"]) < 0.01


def test_klac_price_resolver_rejects_stale_bar() -> None:
    fixture = load_fixture()
    broker = _BrokerStub(fixture)
    resolver = PriceResolver(broker_client=broker)
    r = resolver.resolve_entry_sizing_price("KLAC", decision=SimpleNamespace(evidence={}))
    assert abs(r.price - fixture["fresh_market_price"]) < 0.1
    assert r.source != "broker_bar"


def test_klac_exit_resolver_uses_feature_not_stale_position() -> None:
    fixture = load_fixture()
    resolver = PriceResolver()
    r = resolver.resolve_exit_price(
        "KLAC",
        position_current_price=fixture["stale_peak_price"],
        feature_price=fixture["fresh_market_price"],
    )
    assert r.price == pytest.approx(fixture["fresh_market_price"], abs=0.01)
    assert r.source == "feature_over_stale_position"
    assert fixture["expected"]["exit_signal_should_fire"] is False
