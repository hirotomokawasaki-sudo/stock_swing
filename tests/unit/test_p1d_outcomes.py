"""Tests for P1-D: post signal outcome computation."""

from __future__ import annotations

import pytest

from scripts.build_post_signal_outcomes import compute_forward_returns


def test_compute_forward_returns_basic() -> None:
    closes = {
        "2026-06-01": 100.0,
        "2026-06-02": 103.0,
        "2026-06-03": 105.0,
        "2026-06-04": 102.0,
        "2026-06-05": 108.0,
    }
    result = compute_forward_returns(closes, signal_date="2026-05-31", price_at_signal=100.0)

    assert result["return_1d"] == pytest.approx(0.03)
    assert result["return_3d"] == pytest.approx(0.05)
    assert result["max_favorable_excursion"] == pytest.approx(0.08)
    assert result["max_adverse_excursion"] == pytest.approx(0.02)


def test_compute_forward_returns_insufficient_data() -> None:
    closes = {"2026-06-01": 100.0}
    result = compute_forward_returns(closes, signal_date="2026-05-31", price_at_signal=100.0)
    assert result["return_3d"] is None
    assert result["return_1d"] == pytest.approx(0.0)
