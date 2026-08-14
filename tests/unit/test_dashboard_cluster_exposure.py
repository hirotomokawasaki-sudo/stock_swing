"""R5-v2 (2026-08-14): read-only correlation cluster exposure panel tests.

Covers DashboardService._get_cluster_exposure(), which surfaces
correlation_cluster.compute_cluster_exposures() (already enforced as a hard
BUY block in paper_demo._filter_buys_by_cluster_cap()) in the web dashboard
for the first time. Read-only observability -- must not change any blocking
behavior.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from console.services.dashboard_service import DashboardService


class _StubService(DashboardService):
    """Minimal DashboardService stub that avoids real broker/tracker I/O."""
    def __init__(self, project_root: Path) -> None:  # type: ignore[override]
        self.project_root = project_root
        self._broker = None
        self._tracker = None


def _position(symbol: str, market_value: float) -> dict:
    return {"symbol": symbol, "market_value": market_value, "qty": 10}


class TestGetClusterExposure:
    def test_no_positions_available_returns_empty(self, tmp_path):
        svc = _StubService(tmp_path)
        with patch.object(svc, "get_positions", return_value={"available": False}):
            result = svc._get_cluster_exposure()
        assert result == []

    def test_zero_equity_returns_empty(self, tmp_path):
        svc = _StubService(tmp_path)
        with patch.object(
            svc, "get_positions",
            return_value={"available": True, "positions": [_position("NVDA", 10000.0)]},
        ), patch.object(svc, "_get_account_info", return_value={"equity": 0}):
            result = svc._get_cluster_exposure()
        assert result == []

    def test_empty_clusters_omitted(self, tmp_path):
        """Clusters with zero current exposure are filtered out of the panel."""
        svc = _StubService(tmp_path)
        with patch.object(
            svc, "get_positions",
            return_value={"available": True, "positions": [_position("NVDA", 50000.0)]},
        ), patch.object(svc, "_get_account_info", return_value={"portfolio_value": 1_000_000.0}):
            result = svc._get_cluster_exposure()
        cluster_names = {r["cluster_name"] for r in result}
        assert "cybersecurity" not in cluster_names  # NVDA is not in this cluster
        assert "semis_us" in cluster_names or "hyperscale" in cluster_names

    def test_over_cap_flagged(self, tmp_path):
        """A cluster whose notional exceeds its cap must be flagged over_cap=True."""
        svc = _StubService(tmp_path)
        # cybersecurity cap = 20% of equity; equity=100k -> cap=$20k
        with patch.object(
            svc, "get_positions",
            return_value={"available": True, "positions": [_position("CRWD", 50000.0)]},
        ), patch.object(svc, "_get_account_info", return_value={"portfolio_value": 100_000.0}):
            result = svc._get_cluster_exposure()
        cyber = next(r for r in result if r["cluster_name"] == "cybersecurity")
        assert cyber["over_cap"] is True
        assert cyber["current_notional"] == 50000.0
        assert cyber["cap_notional"] == 20000.0

    def test_under_cap_not_flagged(self, tmp_path):
        svc = _StubService(tmp_path)
        with patch.object(
            svc, "get_positions",
            return_value={"available": True, "positions": [_position("CRWD", 5000.0)]},
        ), patch.object(svc, "_get_account_info", return_value={"portfolio_value": 1_000_000.0}):
            result = svc._get_cluster_exposure()
        cyber = next(r for r in result if r["cluster_name"] == "cybersecurity")
        assert cyber["over_cap"] is False

    def test_exception_in_positions_lookup_returns_empty(self, tmp_path):
        svc = _StubService(tmp_path)
        with patch.object(svc, "get_positions", side_effect=RuntimeError("boom")):
            result = svc._get_cluster_exposure()
        assert result == []

    def test_returned_rows_have_expected_shape(self, tmp_path):
        svc = _StubService(tmp_path)
        with patch.object(
            svc, "get_positions",
            return_value={"available": True, "positions": [_position("MSFT", 30000.0)]},
        ), patch.object(svc, "_get_account_info", return_value={"portfolio_value": 500_000.0}):
            result = svc._get_cluster_exposure()
        assert result, "expected at least one cluster row for MSFT"
        row = result[0]
        assert set(row.keys()) == {
            "cluster_name", "symbols", "current_notional", "cap_notional",
            "cap_pct", "over_cap", "utilization_pct",
        }

    def test_symbol_not_in_any_cluster_returns_empty(self, tmp_path):
        """A symbol with no cluster membership must not produce any rows."""
        svc = _StubService(tmp_path)
        with patch.object(
            svc, "get_positions",
            return_value={"available": True, "positions": [_position("ZZZZ_UNKNOWN", 10000.0)]},
        ), patch.object(svc, "_get_account_info", return_value={"portfolio_value": 1_000_000.0}):
            result = svc._get_cluster_exposure()
        assert result == []


class TestClusterExposureWiredIntoPipelineSummary:
    """Verify get_pipeline_summary() includes cluster_exposure in funnel dict."""

    def test_funnel_includes_cluster_exposure_key(self, tmp_path):
        svc = _StubService(tmp_path)
        with patch.object(svc, "_get_cluster_exposure", return_value=[{"cluster_name": "x"}]), \
             patch.object(svc, "data_adapter", create=True) as mock_adapter, \
             patch.object(svc, "_load_recent_decisions", return_value=[]), \
             patch.object(svc, "_load_recent_audit_lines", return_value=[]), \
             patch.object(svc, "get_positions", return_value={"available": False, "count": 0}), \
             patch.object(svc, "_get_buy_stop_list", return_value=[]), \
             patch.object(svc, "_get_small_sample_watchlist", return_value=[]), \
             patch.object(svc, "_summarize_paper_runs", return_value=[]), \
             patch.object(svc, "_enrich_strategy_overview", return_value={}):
            mock_adapter.get_counts.return_value = {}
            result = svc.get_pipeline_summary(trading={})
        assert "cluster_exposure" in result["funnel"]
        assert result["funnel"]["cluster_exposure"] == [{"cluster_name": "x"}]
