"""Tests for P3-A: PriceResolver."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from stock_swing.pricing import PriceResolver


class _FreshBroker:
    def __init__(self, bar_price: float, quote_bid: float, quote_ask: float, bar_ts: str | None = None):
        self._bar_price = bar_price
        self._quote_bid = quote_bid
        self._quote_ask = quote_ask
        self._bar_ts = bar_ts or datetime.now(timezone.utc).isoformat()

    def fetch_bars(self, symbol, **kwargs):
        return SimpleNamespace(payload={"bars": [{"c": self._bar_price, "t": self._bar_ts}]})

    def fetch_latest_quote(self, symbol):
        return SimpleNamespace(payload={"quote": {"bp": self._quote_bid, "ap": self._quote_ask}})


def test_prefers_decision_latest_close_over_everything():
    broker = _FreshBroker(bar_price=2010.21, quote_bid=244.9, quote_ask=245.1)
    resolver = PriceResolver(
        broker_client=broker,
        now_fn=lambda: datetime(2026, 6, 24, tzinfo=timezone.utc),
    )
    decision = SimpleNamespace(evidence={"latest_close": 245.09})
    r = resolver.resolve_entry_sizing_price("KLAC", decision=decision)
    assert r.price == 245.09
    assert r.source == "decision_latest_close"


def test_falls_back_to_quote_when_bar_is_stale():
    stale_ts = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    broker = _FreshBroker(bar_price=2010.21, quote_bid=244.9, quote_ask=245.1, bar_ts=stale_ts)
    resolver = PriceResolver(broker_client=broker)
    r = resolver.resolve_entry_sizing_price("KLAC", decision=SimpleNamespace(evidence={}))
    assert r.price == pytest.approx(245.0, abs=0.01)
    assert r.source == "broker_quote_mid"


def test_falls_back_to_broker_bar_when_fresh():
    fresh_ts = datetime.now(timezone.utc).isoformat()
    broker = _FreshBroker(bar_price=245.09, quote_bid=0, quote_ask=0, bar_ts=fresh_ts)
    resolver = PriceResolver(broker_client=broker)
    r = resolver.resolve_entry_sizing_price("AAPL", decision=SimpleNamespace(evidence={}))
    assert r.price == pytest.approx(245.09)
    assert r.source == "broker_bar"


def test_uses_feature_over_stale_position_price():
    resolver = PriceResolver()
    r = resolver.resolve_exit_price("KLAC", position_current_price=2010.21, feature_price=245.09)
    assert r.price == pytest.approx(245.09)
    assert r.source == "feature_over_stale_position"
    assert len(r.warnings) > 0


def test_uses_position_price_when_fresh():
    resolver = PriceResolver()
    r = resolver.resolve_exit_price("AAPL", position_current_price=151.0, feature_price=150.0)
    assert r.source == "position_current_price"
    assert r.price == pytest.approx(151.0)


def test_no_price_returns_ok_false():
    resolver = PriceResolver()
    r = resolver.resolve_entry_sizing_price("NONE", decision=SimpleNamespace(evidence={}))
    assert not r.ok
    assert r.source == "none"


def test_as_dict_contains_expected_keys():
    resolver = PriceResolver()
    r = resolver.resolve_exit_price("AAPL", position_current_price=150.0, feature_price=150.0)
    d = r.as_dict()
    assert "price" in d and "source" in d and "candidates" in d and "warnings" in d
