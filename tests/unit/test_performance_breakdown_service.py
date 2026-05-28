"""Tests for performance_breakdown_service."""
from __future__ import annotations
import csv
from pathlib import Path
import pytest

from console.services.performance_breakdown_service import get_performance_breakdown


@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    (tmp_path / "exports").mkdir()
    (tmp_path / "data/tracking").mkdir(parents=True)
    return tmp_path


def _write_csv(root: Path, rows: list[dict]) -> None:
    path = root / "exports/closed_trades.csv"
    fields = ["symbol", "pnl"]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def test_pf_and_asset_class_split(tmp_root: Path) -> None:
    _write_csv(tmp_root, [
        {"symbol": "NVDA",  "pnl": "1000"},   # stock win
        {"symbol": "AMD",   "pnl": "-500"},    # stock loss
        {"symbol": "SOXQ",  "pnl": "-800"},    # ETF loss
        {"symbol": "SOXX",  "pnl": "200"},     # ETF win
    ])
    result = get_performance_breakdown(tmp_root)
    assert result["overall"]["closed_trades"] == 4

    by_class = {r["asset_class"]: r for r in result["by_asset_class"]}
    assert by_class["ETF"]["pnl"]   == pytest.approx(-600, abs=0.01)
    assert by_class["Stock"]["pnl"] == pytest.approx(500,  abs=0.01)

    etf_pf = by_class["ETF"]["profit_factor"]
    assert etf_pf == pytest.approx(200 / 800, abs=0.01)

    stock_pf = by_class["Stock"]["profit_factor"]
    assert stock_pf == pytest.approx(1000 / 500, abs=0.01)


def test_zero_loss_returns_null_pf(tmp_root: Path) -> None:
    _write_csv(tmp_root, [
        {"symbol": "NVDA", "pnl": "500"},
        {"symbol": "AMD",  "pnl": "200"},
    ])
    result = get_performance_breakdown(tmp_root)
    stock = next(r for r in result["by_asset_class"] if r["asset_class"] == "Stock")
    assert stock["profit_factor"] is None
    assert any("null" in w.lower() or "no losing" in w.lower() for w in result["warnings"])


def test_missing_csv_falls_back_to_pnl_state(tmp_root: Path) -> None:
    import json
    state = {"trades": [
        {"status": "closed", "symbol": "NVDA", "pnl": 300},
        {"status": "closed", "symbol": "SOXX", "pnl": -500},
        {"status": "open",   "symbol": "AMD",  "pnl": None},
    ]}
    (tmp_root / "data/tracking/pnl_state.json").write_text(json.dumps(state))

    result = get_performance_breakdown(tmp_root)
    assert result["overall"]["closed_trades"] == 2  # open trade excluded


def test_diagnosis_identifies_etf_drag(tmp_root: Path) -> None:
    _write_csv(tmp_root, [
        {"symbol": "NVDA", "pnl": "1000"},
        {"symbol": "AMD",  "pnl": "500"},
        {"symbol": "SOXQ", "pnl": "-3000"},
        {"symbol": "SOXX", "pnl": "-2000"},
    ])
    result = get_performance_breakdown(tmp_root)
    diag = " ".join(result["diagnosis"]).lower()
    assert "etf" in diag


def test_no_data_returns_available_false(tmp_root: Path) -> None:
    result = get_performance_breakdown(tmp_root)
    assert result.get("available") is False or result.get("overall", {}).get("closed_trades", 0) == 0


def test_current_exports_approximate_known_values() -> None:
    """Smoke test against the actual repo exports (skipped if not present)."""
    project_root = Path(__file__).parents[2]
    csv_path = project_root / "exports/closed_trades.csv"
    if not csv_path.exists():
        pytest.skip("exports/closed_trades.csv not present")

    result = get_performance_breakdown(project_root)
    by_class = {r["asset_class"]: r for r in result["by_asset_class"]}

    # Known values from 2026-05-28 analysis
    assert by_class["ETF"]["profit_factor"]   == pytest.approx(0.168, abs=0.05)
    assert by_class["Stock"]["profit_factor"] == pytest.approx(1.731, abs=0.1)
