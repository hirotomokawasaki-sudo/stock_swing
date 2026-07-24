import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from console.services.dashboard_service import DashboardService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _StubService(DashboardService):
    """Minimal DashboardService stub that avoids real broker/tracker I/O."""
    def __init__(self, project_root: Path) -> None:  # type: ignore[override]
        self.project_root = project_root
        self._broker = None
        self._tracker = None


def _write_pnl_state(tmp_path: Path, trades: list[dict]) -> Path:
    state_path = tmp_path / "data" / "tracking" / "pnl_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"trades": trades}))
    return state_path


def _open_trade(symbol: str, qty: float, ess: float | None) -> dict:
    return {
        "symbol": symbol,
        "status": "open",
        "qty": qty,
        "entry_signal_strength": ess,
    }


def _make_trade(symbol: str, hours_ago: float) -> dict:
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {
        "symbol": symbol,
        "status": "closed",
        "entry_time": ts,
        "exit_time": ts,
        "qty": 1,
        "entry_price": 100.0,
        "exit_price": 101.0,
        "pnl": 1.0,
        "return_pct": 0.01,
    }


def test_select_recent_closed_trades_prefers_last_48_hours():
    trades = [_make_trade(f"RECENT{i}", i % 24) for i in range(60)]
    trades += [_make_trade(f"OLD{i}", 72 + i) for i in range(10)]

    selected = DashboardService._select_recent_closed_trades(trades)

    assert len(selected) == 60
    assert all(t["symbol"].startswith("RECENT") for t in selected)


def test_select_recent_closed_trades_falls_back_to_minimum_count():
    trades = [_make_trade(f"RECENT{i}", i % 12) for i in range(5)]
    trades += [_make_trade(f"OLD{i}", 72 + i) for i in range(60)]

    selected = DashboardService._select_recent_closed_trades(trades)

    assert len(selected) == DashboardService.RECENT_TRADES_MIN_COUNT
    assert sum(1 for t in selected if t["symbol"].startswith("RECENT")) == 5


# ---------------------------------------------------------------------------
# _get_entry_signal_strength_for_symbol
# ---------------------------------------------------------------------------

class TestGetEntrySignalStrengthForSymbol:
    """Unit tests for DashboardService._get_entry_signal_strength_for_symbol().

    testing_standards.md: 1-A (normal / boundary / missing-file / corrupt).
    """

    def test_single_lot_returns_ess(self, tmp_path):
        """Normal: single open trade → returns that trade's ESS."""
        _write_pnl_state(tmp_path, [_open_trade("AAPL", qty=100, ess=0.9918)])
        svc = _StubService(tmp_path)
        result = svc._get_entry_signal_strength_for_symbol("AAPL")
        assert result == pytest.approx(0.9918, abs=1e-4), (
            f"Expected ~0.9918, got {result}"
        )

    def test_multi_lot_returns_qty_weighted_avg(self, tmp_path):
        """Normal: two lots with different ESS → qty-weighted average."""
        _write_pnl_state(tmp_path, [
            _open_trade("MSFT", qty=50, ess=0.60),
            _open_trade("MSFT", qty=50, ess=0.40),
        ])
        svc = _StubService(tmp_path)
        result = svc._get_entry_signal_strength_for_symbol("MSFT")
        assert result == pytest.approx(0.50, abs=1e-4), (
            "Weighted avg of (50×0.60 + 50×0.40) / 100 should be 0.50"
        )

    def test_ess_none_on_trade_is_excluded_from_avg(self, tmp_path):
        """Boundary: lot without ESS is excluded; remaining lots still averaged."""
        _write_pnl_state(tmp_path, [
            _open_trade("GOOG", qty=100, ess=0.80),
            _open_trade("GOOG", qty=100, ess=None),  # no ESS
        ])
        svc = _StubService(tmp_path)
        result = svc._get_entry_signal_strength_for_symbol("GOOG")
        assert result == pytest.approx(0.80, abs=1e-4), (
            "Only the lot with ESS should contribute"
        )

    def test_all_lots_missing_ess_returns_none(self, tmp_path):
        """Boundary: no lot has ESS → returns None (not 0)."""
        _write_pnl_state(tmp_path, [_open_trade("NVDA", qty=10, ess=None)])
        svc = _StubService(tmp_path)
        result = svc._get_entry_signal_strength_for_symbol("NVDA")
        assert result is None, "Should return None when no ESS data is available"

    def test_symbol_not_found_returns_none(self, tmp_path):
        """Boundary: symbol not in pnl_state → returns None."""
        _write_pnl_state(tmp_path, [_open_trade("AAPL", qty=100, ess=0.75)])
        svc = _StubService(tmp_path)
        result = svc._get_entry_signal_strength_for_symbol("TSLA")
        assert result is None, "Unknown symbol should return None"

    def test_closed_trades_are_ignored(self, tmp_path):
        """Boundary: only open trades count; closed ones are skipped."""
        _write_pnl_state(tmp_path, [
            {**_open_trade("META", qty=100, ess=0.90), "status": "closed"},
            _open_trade("META", qty=50, ess=0.60),
        ])
        svc = _StubService(tmp_path)
        result = svc._get_entry_signal_strength_for_symbol("META")
        assert result == pytest.approx(0.60, abs=1e-4), (
            "Closed trade ESS should not be included"
        )

    def test_missing_pnl_state_file_returns_none(self, tmp_path):
        """File-missing: pnl_state.json does not exist → returns None (no crash)."""
        svc = _StubService(tmp_path)  # no pnl_state written
        result = svc._get_entry_signal_strength_for_symbol("AAPL")
        assert result is None, "Missing file should return None, not raise"

    def test_corrupt_pnl_state_returns_none(self, tmp_path):
        """Corrupt: invalid JSON → returns None (no crash)."""
        state_path = tmp_path / "data" / "tracking" / "pnl_state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("NOT_VALID_JSON{{{")
        svc = _StubService(tmp_path)
        result = svc._get_entry_signal_strength_for_symbol("AAPL")
        assert result is None, "Corrupt JSON should return None, not raise"

    def test_weighted_avg_unequal_lots(self, tmp_path):
        """Normal: unequal lot sizes → correct weighted average."""
        # 200 shares @ 0.90, 100 shares @ 0.60 → (200*0.90 + 100*0.60) / 300 = 0.80
        _write_pnl_state(tmp_path, [
            _open_trade("HPE", qty=200, ess=0.90),
            _open_trade("HPE", qty=100, ess=0.60),
        ])
        svc = _StubService(tmp_path)
        result = svc._get_entry_signal_strength_for_symbol("HPE")
        assert result == pytest.approx(0.80, abs=1e-4), (
            "(200×0.90 + 100×0.60) / 300 = 0.80"
        )


# ---------------------------------------------------------------------------
# _enrich_broker_position: entry_signal_strength propagation
# ---------------------------------------------------------------------------

class TestEnrichBrokerPositionEssField:
    """Verify entry_signal_strength is included in _enrich_broker_position() output.

    testing_standards.md: 1-C (layer propagation: pnl_state → service → dict).
    """

    def _minimal_broker_pos(self, symbol: str) -> dict:
        return {
            "symbol": symbol,
            "qty": "100",
            "avg_entry_price": "50.00",
            "current_price": "52.00",
        }

    def test_ess_in_enriched_dict_when_present(self, tmp_path):
        """Layer propagation: ESS from pnl_state appears in enriched position dict."""
        _write_pnl_state(tmp_path, [_open_trade("ANET", qty=100, ess=0.9918)])
        svc = _StubService(tmp_path)
        # Stub out methods that need real broker/tracker I/O
        svc._apply_price_override = lambda sym, price: price
        svc._get_position_entry_context = lambda sym, qty: (None, None)
        svc._get_latest_decision_for_symbol = lambda sym: None
        svc._derive_position_decision_status = lambda dec, holding_days=None: "unknown"
        svc._get_asset_class_for_symbol = lambda sym: "stock"
        svc._get_peak_price_for_symbol = lambda sym, fallback: fallback

        result = svc._enrich_broker_position(self._minimal_broker_pos("ANET"))

        assert "entry_signal_strength" in result, (
            "_enrich_broker_position must include entry_signal_strength key"
        )
        assert result["entry_signal_strength"] == pytest.approx(0.9918, abs=1e-4)

    def test_ess_is_none_when_no_pnl_state(self, tmp_path):
        """Layer propagation: missing pnl_state → entry_signal_strength is None (no crash)."""
        svc = _StubService(tmp_path)
        svc._apply_price_override = lambda sym, price: price
        svc._get_position_entry_context = lambda sym, qty: (None, None)
        svc._get_latest_decision_for_symbol = lambda sym: None
        svc._derive_position_decision_status = lambda dec, holding_days=None: "unknown"
        svc._get_asset_class_for_symbol = lambda sym: "stock"
        svc._get_peak_price_for_symbol = lambda sym, fallback: fallback

        result = svc._enrich_broker_position(self._minimal_broker_pos("AAPL"))

        assert "entry_signal_strength" in result, (
            "Key must be present even when value is None"
        )
        assert result["entry_signal_strength"] is None
