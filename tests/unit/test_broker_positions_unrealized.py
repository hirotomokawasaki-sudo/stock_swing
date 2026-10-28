"""Regression: 2026-10-21 flat-account false HALT on baseline commit 63c8c39.

A successfully decoded empty broker list proves zero; unavailable, partial or
malformed financial evidence never does. These tests use no broker/network I/O.
"""
from __future__ import annotations

import pytest

from stock_swing.guardrails.day_start_snapshot import broker_positions_unrealized


def _position(**overrides):
    return {"symbol": "AAPL", "qty": "2", "unrealized_pl": "12.50", **overrides}


def test_confirmed_empty_positions_proves_zero():
    assert broker_positions_unrealized([]) == pytest.approx(0), "confirmed flat is not missing"


def test_aggregate_includes_fractional_and_short_positions():
    positions = [_position(qty="0.25"), _position(symbol="MSFT", qty="-3", unrealized_pl="-2.25")]
    assert broker_positions_unrealized(positions) == pytest.approx(10.25), "do not use long-only exit filtering"


@pytest.mark.parametrize("payload", [None, {}, {"positions": []}, "[]", [None], ["AAPL"]])
def test_unknown_or_malformed_payload_is_not_zero(payload):
    assert broker_positions_unrealized(payload) is None, "invalid broker response must fail closed"


@pytest.mark.parametrize("field,value", [
    ("symbol", None), ("symbol", ""), ("symbol", " "), ("symbol", 12),
    ("qty", None), ("qty", "bad"), ("qty", True), ("qty", "NaN"),
    ("qty", "Infinity"), ("qty", "0"),
    ("unrealized_pl", None), ("unrealized_pl", ""), ("unrealized_pl", "bad"),
    ("unrealized_pl", True), ("unrealized_pl", "NaN"), ("unrealized_pl", "Infinity"),
])
def test_bad_position_financial_evidence_is_not_zero(field, value):
    assert broker_positions_unrealized([_position(**{field: value})]) is None, "unknown values cannot become zero"


@pytest.mark.parametrize("field", ["symbol", "qty", "unrealized_pl"])
def test_missing_required_position_field_is_not_zero(field):
    position = _position()
    del position[field]
    assert broker_positions_unrealized([position]) is None, "missing field must remain unknown"


def test_explicit_zero_unrealized_is_valid():
    assert broker_positions_unrealized([_position(unrealized_pl="0")]) == pytest.approx(0), "numeric zero is evidence"


def test_partial_list_and_duplicate_symbol_do_not_certify_total():
    assert broker_positions_unrealized([_position(), _position(symbol="MSFT", unrealized_pl=None)]) is None
    assert broker_positions_unrealized([_position(), _position()]) is None, "duplicated positions would double count"


def test_overflowing_total_is_unknown():
    positions = [_position(unrealized_pl="1e308"), _position(symbol="MSFT", unrealized_pl="1e308")]
    assert broker_positions_unrealized(positions) is None, "nonfinite total must fail closed"
