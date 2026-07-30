"""Integration tests: asset_class persists through rebuild and ledger invariant detects gaps.

Covers the bug discovered 2026-07-28:
  - rebuild_pnl_state_from_broker.py wiped asset_class on every rebuild because
    --preserve-attribution only saved exit_reason + quarantined_trades.
  - check_ledger_invariants() did not check asset_class, so daily audit never caught it.
  - console fallback (classify_asset_class at runtime) masked the issue visually.

These tests ensure both the detection and the fix are durable.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ledger invariant: asset_class detection
# ---------------------------------------------------------------------------

from scripts.audit_trades_with_market_data import check_ledger_invariants


def _make_state(closed_trades: list[dict], cumulative_pnl: float = 0.0) -> dict:
    return {
        "trades": closed_trades,
        "quarantined_trades": [],
        "cumulative_realized_pnl": cumulative_pnl,
    }


def _closed(symbol: str, asset_class: str | None, pnl: float = 100.0,
            broker_order_id: str = "", exit_broker_order_id: str = "") -> dict:
    return {
        "trade_id": f"t_{symbol}",
        "symbol": symbol,
        "status": "closed",
        "asset_class": asset_class,
        "entry_time": "2026-07-01T13:00:00+00:00",
        "exit_time": "2026-07-10T15:00:00+00:00",
        "pnl": pnl,
        "holding_days": 9,
        "broker_order_id": broker_order_id,
        "exit_broker_order_id": exit_broker_order_id,
    }


class TestLedgerInvariantOverlapDetection:
    """Invariant 1: overlap must be detected by broker_order_id pair, not trade_id.

    Root cause (2026-07-28): trade_id='broker_match_NNNN_SYMBOL' is a sequential
    index that shifts on every rebuild when new fills are added.  After the 07-25
    SKYY phantom rebuild 14 quarantined trades appeared as overlaps solely because
    the same index now pointed to a different broker_order_id.  True overlap was 0.
    """

    def test_true_overlap_detected_by_broker_order_id(self):
        """Two trades with the same (broker_order_id, exit_broker_order_id) in
        both closed and quarantine → overlap=1."""
        state = {
            "trades": [
                _closed("AMD", "stock", pnl=100.0,
                        broker_order_id="buy-aaa", exit_broker_order_id="sell-bbb"),
            ],
            "quarantined_trades": [
                {"symbol": "AMD", "broker_order_id": "buy-aaa",
                 "exit_broker_order_id": "sell-bbb", "pnl": 100.0},
            ],
            "cumulative_realized_pnl": 100.0,
        }
        result = check_ledger_invariants(state)
        assert result["overlap_count"] == 1
        assert result["passed"] is False

    def test_false_overlap_trade_id_same_but_broker_id_different(self):
        """Regression: trade_id collision after rebuild (07-25 pattern).
        Same trade_id, different broker_order_id → NOT an overlap."""
        state = {
            "trades": [
                _closed("AMZN", "stock", pnl=50.0,
                        broker_order_id="buy-NEW", exit_broker_order_id="sell-NEW"),
            ],
            "quarantined_trades": [
                # Same trade_id prefix 't_AMZN' but different broker IDs (old rebuild)
                {"symbol": "AMZN", "trade_id": "t_AMZN",
                 "broker_order_id": "buy-OLD",
                 "exit_broker_order_id": "sell-OLD", "pnl": 50.0},
            ],
            "cumulative_realized_pnl": 50.0,
        }
        result = check_ledger_invariants(state)
        assert result["overlap_count"] == 0  # no true overlap
        assert result["passed"] is True

    def test_no_overlap_when_quarantine_empty(self):
        state = _make_state([
            _closed("NVDA", "stock", broker_order_id="b1", exit_broker_order_id="e1"),
        ], cumulative_pnl=100.0)
        result = check_ledger_invariants(state)
        assert result["overlap_count"] == 0


class TestLedgerInvariantAssetClass:
    """check_ledger_invariants must detect asset_class=None / unknown / missing."""

    def test_all_valid_asset_classes_passes(self):
        state = _make_state([
            _closed("AMD", "stock"),
            _closed("SMH", "etf"),
        ], cumulative_pnl=200.0)
        result = check_ledger_invariants(state)
        assert result["ac_unknown_count"] == 0
        assert result["passed"] is True

    def test_asset_class_none_detected(self):
        """Regression: 203 closed trades reverted to None after 07-25 SKYY rebuild."""
        state = _make_state([_closed("AMD", None)], cumulative_pnl=100.0)
        result = check_ledger_invariants(state)
        assert result["ac_unknown_count"] == 1
        assert result["passed"] is False

    def test_asset_class_unknown_string_detected(self):
        state = _make_state([_closed("XYZ", "unknown")], cumulative_pnl=100.0)
        result = check_ledger_invariants(state)
        assert result["ac_unknown_count"] == 1
        assert result["passed"] is False

    def test_asset_class_empty_string_detected(self):
        state = _make_state([_closed("XYZ", "")], cumulative_pnl=100.0)
        result = check_ledger_invariants(state)
        assert result["ac_unknown_count"] == 1
        assert result["passed"] is False

    def test_asset_class_missing_field_detected(self):
        trade = _closed("AMD", "stock")
        del trade["asset_class"]  # field absent entirely
        state = _make_state([trade], cumulative_pnl=100.0)
        result = check_ledger_invariants(state)
        assert result["ac_unknown_count"] == 1
        assert result["passed"] is False

    def test_mixed_valid_and_invalid_counts_correctly(self):
        state = _make_state([
            _closed("AMD", "stock"),
            _closed("SMH", "etf"),
            _closed("XYZ", None),
            _closed("FOO", "unknown"),
        ], cumulative_pnl=400.0)
        result = check_ledger_invariants(state)
        assert result["ac_unknown_count"] == 2
        assert result["passed"] is False

    def test_case_insensitive_stock_etf_are_valid(self):
        """asset_class='STOCK' and 'ETF' (uppercase) should be treated as valid."""
        state = _make_state([
            _closed("AMD", "STOCK"),
            _closed("SMH", "ETF"),
        ], cumulative_pnl=200.0)
        result = check_ledger_invariants(state)
        assert result["ac_unknown_count"] == 0
        assert result["passed"] is True

    def test_ac_unknown_count_key_always_present(self):
        """Callers depend on ac_unknown_count always being in the return dict."""
        state = _make_state([], cumulative_pnl=0.0)
        result = check_ledger_invariants(state)
        assert "ac_unknown_count" in result


# ---------------------------------------------------------------------------
# apply_asset_class_from_registry: unit tests
# ---------------------------------------------------------------------------

from scripts.rebuild_pnl_state_from_broker import apply_asset_class_from_registry


def _make_registry_yaml(tmp_path: Path, entries: dict[str, str]) -> Path:
    """Write a minimal symbol_registry.yaml for tests."""
    import yaml  # type: ignore[import-untyped]
    data = {"symbols": {sym: {"asset_class": ac} for sym, ac in entries.items()}}
    p = tmp_path / "symbol_registry.yaml"
    p.write_text(yaml.dump(data))
    return p


class TestApplyAssetClassFromRegistry:
    """apply_asset_class_from_registry fills asset_class from registry."""

    def test_fills_none_asset_class(self, tmp_path: Path):
        reg_path = _make_registry_yaml(tmp_path, {"AMD": "stock", "SMH": "etf"})
        state = {
            "trades": [
                {"symbol": "AMD", "status": "closed", "asset_class": None},
                {"symbol": "SMH", "status": "open", "asset_class": None},
            ]
        }
        updated = apply_asset_class_from_registry(state, registry_path=reg_path)
        assert updated == 2
        assert state["trades"][0]["asset_class"] == "stock"
        assert state["trades"][1]["asset_class"] == "etf"

    def test_preserves_existing_valid_asset_class(self, tmp_path: Path):
        """Already-set stock/etf must not be overwritten (e.g. manual overrides)."""
        reg_path = _make_registry_yaml(tmp_path, {"AMD": "etf"})  # registry says etf
        state = {
            "trades": [
                {"symbol": "AMD", "status": "closed", "asset_class": "stock"},  # manual: stock
            ]
        }
        updated = apply_asset_class_from_registry(state, registry_path=reg_path)
        assert updated == 0
        assert state["trades"][0]["asset_class"] == "stock"  # untouched

    def test_unknown_symbol_gets_unknown(self, tmp_path: Path):
        reg_path = _make_registry_yaml(tmp_path, {"AMD": "stock"})
        state = {
            "trades": [
                {"symbol": "NOTREAL", "status": "closed", "asset_class": None},
            ]
        }
        apply_asset_class_from_registry(state, registry_path=reg_path)
        assert state["trades"][0]["asset_class"] == "unknown"

    def test_overwrites_unknown_string(self, tmp_path: Path):
        """Trades with asset_class='unknown' should be re-backfilled."""
        reg_path = _make_registry_yaml(tmp_path, {"SMH": "etf"})
        state = {
            "trades": [
                {"symbol": "SMH", "status": "closed", "asset_class": "unknown"},
            ]
        }
        updated = apply_asset_class_from_registry(state, registry_path=reg_path)
        assert updated == 1
        assert state["trades"][0]["asset_class"] == "etf"

    def test_returns_zero_when_all_valid(self, tmp_path: Path):
        reg_path = _make_registry_yaml(tmp_path, {"AMD": "stock"})
        state = {
            "trades": [
                {"symbol": "AMD", "status": "closed", "asset_class": "stock"},
            ]
        }
        updated = apply_asset_class_from_registry(state, registry_path=reg_path)
        assert updated == 0

    def test_rebuild_then_invariant_passes(self, tmp_path: Path):
        """Integration: after apply_asset_class_from_registry, ledger invariant passes."""
        reg_path = _make_registry_yaml(tmp_path, {"AMD": "stock", "SMH": "etf"})
        pnl_state = {
            "trades": [
                {"trade_id": "t1", "symbol": "AMD", "status": "closed",
                 "asset_class": None, "pnl": 100.0,
                 "entry_time": "2026-07-01T13:00:00+00:00",
                 "exit_time": "2026-07-05T15:00:00+00:00", "holding_days": 4},
                {"trade_id": "t2", "symbol": "SMH", "status": "closed",
                 "asset_class": None, "pnl": 200.0,
                 "entry_time": "2026-07-02T13:00:00+00:00",
                 "exit_time": "2026-07-06T15:00:00+00:00", "holding_days": 4},
            ],
            "quarantined_trades": [],
            "cumulative_realized_pnl": 300.0,
        }
        # Before fix: invariant fails
        result_before = check_ledger_invariants(pnl_state)
        assert result_before["ac_unknown_count"] == 2
        assert result_before["passed"] is False

        # After fix
        apply_asset_class_from_registry(pnl_state, registry_path=reg_path)
        result_after = check_ledger_invariants(pnl_state)
        assert result_after["ac_unknown_count"] == 0
        assert result_after["passed"] is True
