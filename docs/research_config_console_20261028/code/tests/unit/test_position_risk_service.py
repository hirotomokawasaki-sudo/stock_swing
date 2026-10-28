"""Tests for position_risk_service."""
from __future__ import annotations
import csv
import json
from pathlib import Path
import pytest

from console.services.position_risk_service import get_open_position_risk


@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    (tmp_path / "exports").mkdir()
    (tmp_path / "data/tracking").mkdir(parents=True)
    return tmp_path


def _write_open_csv(root: Path, rows: list[dict]) -> None:
    path = root / "exports/open_positions.csv"
    fields = ["symbol", "qty", "entry_price", "peak_price", "entry_signal_strength"]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def test_missing_strength_maps_to_conservative_thresholds(tmp_root: Path) -> None:
    _write_open_csv(tmp_root, [
        {"symbol": "NVDA", "qty": 10, "entry_price": 100, "peak_price": 105, "entry_signal_strength": ""},
    ])
    result = get_open_position_risk(tmp_root)
    pos = result["positions"][0]
    assert pos["stop_loss_pct"]   == pytest.approx(-0.05, abs=0.001)
    assert pos["take_profit_pct"] == pytest.approx(0.10,  abs=0.001)
    assert pos["threshold_policy"] == "conservative_missing_strength"


def test_high_conviction_uses_wider_stop(tmp_root: Path) -> None:
    _write_open_csv(tmp_root, [
        {"symbol": "NVDA", "qty": 10, "entry_price": 100, "peak_price": 108, "entry_signal_strength": "0.90"},
    ])
    result = get_open_position_risk(tmp_root)
    pos = result["positions"][0]
    assert pos["stop_loss_pct"]   == pytest.approx(-0.09, abs=0.001)
    assert pos["take_profit_pct"] == pytest.approx(0.06,  abs=0.001)


def test_peak_gain_buckets_are_counted_correctly(tmp_root: Path) -> None:
    _write_open_csv(tmp_root, [
        {"symbol": "A", "qty": 10, "entry_price": 100, "peak_price": 115},   # >=10%
        {"symbol": "B", "qty": 10, "entry_price": 100, "peak_price": 109},   # 8-10%
        {"symbol": "C", "qty": 10, "entry_price": 100, "peak_price": 104},   # 3-6%
        {"symbol": "D", "qty": 10, "entry_price": 100, "peak_price": 98},    # <0%
    ])
    result = get_open_position_risk(tmp_root)
    buckets = {b["bucket"]: b["count"] for b in result["peak_gain_buckets"]}
    assert buckets[">=10%"] == 1
    assert buckets["8-10%"] == 1
    assert buckets["3-6%"]  == 1
    assert buckets["<0%"]   == 1


def test_missing_current_price_returns_unknown_attention(tmp_root: Path) -> None:
    _write_open_csv(tmp_root, [
        {"symbol": "NVDA", "qty": 10, "entry_price": 100, "peak_price": ""},
    ])
    result = get_open_position_risk(tmp_root)
    pos = result["positions"][0]
    # No current_price in static export → unknown or no useful signal
    assert pos["current_price"] is None


def test_entry_notional_is_sum_of_qty_times_entry(tmp_root: Path) -> None:
    _write_open_csv(tmp_root, [
        {"symbol": "NVDA", "qty": "10", "entry_price": "100", "peak_price": "110"},
        {"symbol": "AMD",  "qty": "5",  "entry_price": "200", "peak_price": "210"},
    ])
    result = get_open_position_risk(tmp_root)
    assert result["summary"]["entry_notional"] == pytest.approx(2000.0, abs=1.0)


def test_53_missing_strengths_on_current_exports() -> None:
    """Smoke test against actual open_positions.csv (skipped if absent)."""
    project_root = Path(__file__).parents[2]
    csv_path = project_root / "exports/open_positions.csv"
    if not csv_path.exists():
        pytest.skip("exports/open_positions.csv not present")

    result = get_open_position_risk(project_root)
    summary = result["summary"]
    assert summary["open_positions"] == 53
    assert summary["missing_entry_signal_strength"] == 53
    assert summary["conservative_threshold_positions"] == 53


def test_no_data_returns_empty_positions(tmp_root: Path) -> None:
    result = get_open_position_risk(tmp_root)
    assert isinstance(result["positions"], list)
    assert isinstance(result["warnings"], list)
