"""Tests for P4-B: correlation cluster risk cap."""
from __future__ import annotations

import pytest

from stock_swing.risk.correlation_cluster import (
    compute_cluster_exposures,
    get_cluster_for_symbol,
    is_buy_blocked_by_cluster_cap,
)


def test_semis_symbol_in_correct_clusters() -> None:
    clusters = get_cluster_for_symbol("NVDA")
    assert "semis_us" in clusters
    assert "semis_combined" in clusters
    assert "hyperscale" in clusters


def test_non_semis_symbol_not_in_semis_cluster() -> None:
    clusters = get_cluster_for_symbol("PLTR")
    assert "semis_us" not in clusters
    assert "semis_combined" not in clusters
    assert "cloud_software" in clusters


def test_compute_exposures_empty_positions() -> None:
    exps = compute_cluster_exposures([], account_equity=100_000)
    for e in exps:
        assert e.current_notional == 0.0
        assert not e.over_cap


def test_compute_exposures_over_cap() -> None:
    positions = [
        {"symbol": "NVDA", "market_value": "20000", "qty": "1"},
        {"symbol": "AMD", "market_value": "15000", "qty": "1"},
        {"symbol": "INTC", "market_value": "10000", "qty": "1"},
    ]
    exps = compute_cluster_exposures(positions, account_equity=100_000)
    semis_us = next(e for e in exps if e.cluster_name == "semis_us")
    assert semis_us.current_notional == pytest.approx(45_000)
    assert semis_us.over_cap


def test_buy_blocked_when_cluster_over_cap() -> None:
    positions = [
        {"symbol": "NVDA", "market_value": "35000", "qty": "1"},
    ]
    blocked, reason = is_buy_blocked_by_cluster_cap(
        "LRCX", positions, account_equity=100_000
    )
    assert blocked
    assert "semis" in reason


def test_buy_allowed_when_cluster_under_cap() -> None:
    positions = [
        {"symbol": "NVDA", "market_value": "5000", "qty": "1"},
    ]
    blocked, reason = is_buy_blocked_by_cluster_cap(
        "AMD", positions, account_equity=100_000
    )
    assert not blocked
    assert reason == ""


def test_unknown_symbol_always_allowed() -> None:
    positions = [{"symbol": "NVDA", "market_value": "99999", "qty": "1"}]
    blocked, _ = is_buy_blocked_by_cluster_cap("AAPL", positions, account_equity=100_000)
    assert not blocked
