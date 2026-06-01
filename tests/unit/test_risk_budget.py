"""Tests for stock_swing.risk.risk_budget module."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from stock_swing.risk.risk_budget import (
    BLOCK_PCT,
    WARN_PCT,
    _stop_loss_pct,
    compute_open_risk,
)


# ── _stop_loss_pct ─────────────────────────────────────────────────────────────

class TestStopLossPct:
    def test_none_returns_conservative(self):
        assert _stop_loss_pct(None) == 0.05

    def test_high_conviction(self):
        assert _stop_loss_pct(0.85) == 0.09
        assert _stop_loss_pct(1.0) == 0.09

    def test_standard(self):
        assert _stop_loss_pct(0.70) == 0.08
        assert _stop_loss_pct(0.80) == 0.08

    def test_low_conviction(self):
        assert _stop_loss_pct(0.50) == 0.05
        assert _stop_loss_pct(0.69) == 0.05


# ── compute_open_risk ──────────────────────────────────────────────────────────

def _make_project_root(trades: list[dict]) -> Path:
    """Create a temp project root with pnl_state.json containing given trades."""
    tmp = tempfile.mkdtemp()
    root = Path(tmp)
    tracking = root / "data" / "tracking"
    tracking.mkdir(parents=True)
    state = {"trades": trades}
    (tracking / "pnl_state.json").write_text(json.dumps(state))
    return root


class TestComputeOpenRiskNoState:
    def test_missing_file_returns_zero_risk(self, tmp_path):
        result = compute_open_risk(tmp_path, equity=1_000_000)
        assert result["total_open_risk"] == 0.0
        assert result["is_blocked"] is False
        assert result["is_warn"] is False
        assert "error" in result

    def test_no_open_trades(self):
        root = _make_project_root([
            {"status": "closed", "symbol": "NVDA", "qty": 10, "entry_price": 100.0},
        ])
        result = compute_open_risk(root, equity=1_000_000)
        assert result["total_open_risk"] == 0.0
        assert result["open_trades_count"] == 0
        assert result["is_warn"] is False
        assert result["is_blocked"] is False


class TestComputeOpenRiskCalculation:
    def test_single_trade_no_signal_strength(self):
        # qty=100, entry=100, stop=5% → max_loss=500
        root = _make_project_root([
            {"status": "open", "symbol": "AAPL", "qty": 100, "entry_price": 100.0},
        ])
        result = compute_open_risk(root, equity=1_000_000)
        assert result["total_open_risk"] == pytest.approx(500.0)
        assert result["pct_of_equity"] == pytest.approx(0.0005)
        assert result["is_warn"] is False
        assert result["is_blocked"] is False

    def test_single_trade_high_conviction(self):
        # qty=100, entry=100, stop=9% → max_loss=900
        root = _make_project_root([
            {"status": "open", "symbol": "NVDA", "qty": 100, "entry_price": 100.0,
             "entry_signal_strength": 0.90},
        ])
        result = compute_open_risk(root, equity=1_000_000)
        assert result["total_open_risk"] == pytest.approx(900.0)

    def test_legacy_signal_strength_fallback(self):
        """Old pnl_state.json entries using 'signal_strength' key still work."""
        root = _make_project_root([
            {"status": "open", "symbol": "NVDA", "qty": 100, "entry_price": 100.0,
             "signal_strength": 0.90},  # legacy key
        ])
        result = compute_open_risk(root, equity=1_000_000)
        assert result["total_open_risk"] == pytest.approx(900.0)

    def test_entry_signal_strength_takes_priority_over_legacy(self):
        """entry_signal_strength takes priority over legacy signal_strength."""
        root = _make_project_root([
            {"status": "open", "symbol": "X", "qty": 100, "entry_price": 100.0,
             "entry_signal_strength": 0.90,  # high conviction: 9%
             "signal_strength": 0.50},        # low conviction: 5% — should be ignored
        ])
        result = compute_open_risk(root, equity=1_000_000)
        assert result["total_open_risk"] == pytest.approx(900.0)

    def test_warn_threshold_triggered(self):
        # open risk = 4.1% of equity (WARN at 4%) → warn
        equity = 1_000_000
        # qty × entry × 0.05 = 41_000  →  qty × entry = 820_000
        # entry=1000, qty=820, stop=5%  →  max_loss=41_000 (4.1%)
        root = _make_project_root([
            {"status": "open", "symbol": "X", "qty": 820, "entry_price": 1000.0},
        ])
        result = compute_open_risk(root, equity=equity)
        assert result["is_warn"] is True
        assert result["is_blocked"] is False

    def test_block_threshold_triggered(self):
        # open risk = 6.5% of equity (BLOCK at 6%) → blocked
        equity = 1_000_000
        # qty × entry × 0.05 = 65_000  →  qty × entry = 1_300_000
        # entry=1000, qty=1300, stop=5%  →  max_loss=65_000 (6.5%)
        root = _make_project_root([
            {"status": "open", "symbol": "X", "qty": 1300, "entry_price": 1000.0},
        ])
        result = compute_open_risk(root, equity=equity)
        assert result["is_warn"] is True
        assert result["is_blocked"] is True

    def test_multiple_trades_sum(self):
        root = _make_project_root([
            {"status": "open", "symbol": "A", "qty": 100, "entry_price": 100.0},  # 500
            {"status": "open", "symbol": "B", "qty": 200, "entry_price": 50.0},   # 500
            {"status": "closed", "symbol": "C", "qty": 999, "entry_price": 999.0},  # ignored
        ])
        result = compute_open_risk(root, equity=1_000_000)
        assert result["total_open_risk"] == pytest.approx(1000.0)
        assert result["open_trades_count"] == 2

    def test_per_symbol_sorted_by_max_loss(self):
        root = _make_project_root([
            {"status": "open", "symbol": "SMALL", "qty": 10, "entry_price": 10.0},   # 5
            {"status": "open", "symbol": "BIG", "qty": 1000, "entry_price": 100.0},  # 5000
        ])
        result = compute_open_risk(root, equity=1_000_000)
        assert result["per_symbol"][0]["symbol"] == "BIG"
        assert result["per_symbol"][1]["symbol"] == "SMALL"

    def test_thresholds_scale_with_equity(self):
        root = _make_project_root([])
        result = compute_open_risk(root, equity=500_000)
        assert result["warn_threshold"] == pytest.approx(500_000 * WARN_PCT)
        assert result["block_threshold"] == pytest.approx(500_000 * BLOCK_PCT)

    def test_closed_trades_excluded(self):
        root = _make_project_root([
            {"status": "closed", "symbol": "A", "qty": 9999, "entry_price": 9999.0},
            {"status": "open",   "symbol": "B", "qty": 10,   "entry_price": 100.0},
        ])
        result = compute_open_risk(root, equity=1_000_000)
        assert result["open_trades_count"] == 1
        assert result["total_open_risk"] == pytest.approx(10 * 100.0 * 0.05)
