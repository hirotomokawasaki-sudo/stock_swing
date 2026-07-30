"""Tests for guardrail_service."""
from __future__ import annotations
import csv
import json
import os
from pathlib import Path
import pytest

from console.services.guardrail_service import get_guardrail_status


@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    (tmp_path / "exports").mkdir()
    (tmp_path / "data/tracking").mkdir(parents=True)
    return tmp_path


def _write_open_positions(root: Path, rows: list[dict]) -> None:
    path = root / "exports/open_positions.csv"
    fields = ["symbol", "qty", "entry_price", "entry_signal_strength"]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def test_etf_buys_disabled_shows_warning(tmp_root: Path, monkeypatch) -> None:
    """When ETF buys are disabled a warning is emitted but status stays guarded."""
    monkeypatch.delenv("PAPER_DEMO_ALLOW_ETF_BUYS", raising=False)
    result = get_guardrail_status(tmp_root)
    assert result["etf_buys_enabled"] is False
    assert result["status"] == "guarded"  # no risk condition; just a warning
    assert any("ETF buys are disabled" in w for w in result.get("warnings", []))


def test_etf_buys_enabled_via_env(tmp_root: Path, monkeypatch) -> None:
    """ETF buys enabled is no longer a risk condition (PF=2.776 validated 2026-06-23)."""
    monkeypatch.setenv("PAPER_DEMO_ALLOW_ETF_BUYS", "true")
    result = get_guardrail_status(tmp_root)
    assert result["etf_buys_enabled"] is True
    assert result["status"] == "guarded"  # enabled is the intended normal state


def test_etf_position_multiplier_is_070(tmp_root: Path, monkeypatch) -> None:
    """ETF multiplier restored to 0.70: actual PF=2.776 per broker data (2026-06-23)."""
    monkeypatch.delenv("PAPER_DEMO_ALLOW_ETF_BUYS", raising=False)
    result = get_guardrail_status(tmp_root)
    assert result["etf_position_multiplier"] == pytest.approx(0.70, abs=0.01)


def test_missing_strength_policy_is_conservative(tmp_root: Path, monkeypatch) -> None:
    monkeypatch.delenv("PAPER_DEMO_ALLOW_ETF_BUYS", raising=False)
    result = get_guardrail_status(tmp_root)
    policy = result["missing_strength_policy"]
    assert policy["mode"] == "conservative"
    assert policy["stop_loss_pct"] == pytest.approx(-0.05, abs=0.001)
    assert policy["take_profit_pct"] == pytest.approx(0.10, abs=0.001)


def test_missing_strength_count_from_csv(tmp_root: Path, monkeypatch) -> None:
    monkeypatch.delenv("PAPER_DEMO_ALLOW_ETF_BUYS", raising=False)
    _write_open_positions(tmp_root, [
        {"symbol": "NVDA", "qty": 10, "entry_price": 100, "entry_signal_strength": ""},
        {"symbol": "AMD",  "qty": 5,  "entry_price": 50,  "entry_signal_strength": "0.8"},
        {"symbol": "SOXX", "qty": 3,  "entry_price": 200, "entry_signal_strength": "None"},
    ])
    result = get_guardrail_status(tmp_root)
    audit = result["open_position_audit"]
    assert audit["total"] == 3
    assert audit["missing_entry_signal_strength"] == 2  # NVDA and SOXX


def test_missing_files_return_warnings_not_error(tmp_root: Path, monkeypatch) -> None:
    monkeypatch.delenv("PAPER_DEMO_ALLOW_ETF_BUYS", raising=False)
    result = get_guardrail_status(tmp_root)
    assert "status" in result  # endpoint didn't crash
    assert isinstance(result["warnings"], list)


def test_p0_flags_are_off(tmp_root: Path, monkeypatch) -> None:
    monkeypatch.delenv("PAPER_DEMO_ALLOW_ETF_BUYS", raising=False)
    result = get_guardrail_status(tmp_root)
    assert result["missing_price_fallback_enabled"] is False
    assert result["placeholder_position_limit_enabled"] is False
