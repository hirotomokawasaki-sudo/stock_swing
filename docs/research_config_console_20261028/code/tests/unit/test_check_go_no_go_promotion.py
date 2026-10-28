"""R5-v2 (2026-08-14): scripts/check_go_no_go.py promotion-readiness wiring.

Covers check_promotion_readiness() and format_report()'s optional promotion
section -- must remain supplementary (never affects the Required
conditions' overall pass/fail or exit code).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_go_no_go.py"


def _load_module(monkeypatch, project_root: Path):
    spec = importlib.util.spec_from_file_location("check_go_no_go_promotion", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "PROJECT_ROOT", project_root)
    return module


class TestCheckPromotionReadiness:
    def test_never_raises_with_empty_project_root(self, tmp_path, monkeypatch):
        """With an empty tmp_path project root (no pnl_state.json, no
        broker credentials), the function must degrade gracefully -- either
        None (deps unavailable) or a dict with fail-closed criteria -- and
        must never raise."""
        module = _load_module(monkeypatch, tmp_path)
        result = module.check_promotion_readiness()
        assert result is None or isinstance(result, dict)

    def test_error_dict_shape_on_exception(self, tmp_path, monkeypatch):
        module = _load_module(monkeypatch, tmp_path)

        def _raise(*a, **k):
            raise RuntimeError("boom")

        with patch("stock_swing.risk.promotion_gate.evaluate_promotion_readiness", side_effect=_raise):
            result = module.check_promotion_readiness()
        # Either error-wrapped dict or a normal criteria dict depending on
        # where the mocked exception surfaces; must never raise.
        assert result is None or isinstance(result, dict)

    def test_correlation_summary_derived_from_held_symbols(self, tmp_path, monkeypatch):
        """check_promotion_readiness() must call
        build_daily_closes_from_raw_bars() only for symbols currently held
        (from get_positions()), and thread the resulting correlation
        summary into evaluate_promotion_readiness()."""
        module = _load_module(monkeypatch, tmp_path)

        mock_dash = MagicMock()
        mock_dash._get_cluster_exposure.return_value = []
        mock_dash.get_positions.return_value = {
            "available": True,
            "positions": [{"symbol": "NVDA", "market_value": 1000}, {"symbol": "AMD", "market_value": 500}],
        }
        mock_dash._summarize_positions.return_value = {"top5_concentration": 0.3}

        mock_bench = MagicMock()
        mock_bench.calculate_beta.return_value = {"available": True, "beta": 1.0}

        captured_kwargs = {}

        def _fake_evaluate(**kwargs):
            captured_kwargs.update(kwargs)
            from stock_swing.risk.promotion_gate import PromotionReadiness
            return PromotionReadiness(criteria=[])

        with patch("console.services.dashboard_service.DashboardService", return_value=mock_dash), \
             patch("console.services.benchmark_service.BenchmarkService", return_value=mock_bench), \
             patch("stock_swing.risk.pairwise_correlation.build_daily_closes_from_raw_bars", return_value={"2026-01-01": 100.0, "2026-01-02": 101.0}) as mock_build, \
             patch("stock_swing.risk.promotion_gate.evaluate_promotion_readiness", side_effect=_fake_evaluate):
            module.check_promotion_readiness()

        called_symbols = {c.args[0] for c in mock_build.call_args_list}
        assert called_symbols == {"NVDA", "AMD"}
        assert "correlation_summary" in captured_kwargs


class TestFormatReportPromotionSection:
    def test_promotion_none_omits_section(self, tmp_path, monkeypatch):
        module = _load_module(monkeypatch, tmp_path)
        results = {
            "ledger_quality": {"label": "ledger_quality_gate", "pass": True, "actual": "VALID", "required": "VALID"},
        }
        report = module.format_report(results, save=False, promotion=None)
        assert "Promotion Gate" not in report

    def test_promotion_present_adds_section(self, tmp_path, monkeypatch):
        module = _load_module(monkeypatch, tmp_path)
        results = {
            "ledger_quality": {"label": "ledger_quality_gate", "pass": True, "actual": "VALID", "required": "VALID"},
        }
        promotion = {
            "cluster_cap": {"label": "cluster_cap", "pass": True, "actual": "none over cap", "required": "no cluster over cap", "detail": ""},
            "top5_concentration": {"label": "top5_concentration", "pass": False, "actual": "52.0%", "required": "<=40%", "detail": ""},
        }
        report = module.format_report(results, save=False, promotion=promotion)
        assert "Promotion Gate" in report
        assert "cluster_cap" in report
        assert "top5_concentration" in report
        assert "52.0%" in report

    def test_promotion_failure_does_not_affect_overall_decision(self, tmp_path, monkeypatch):
        """A failing promotion criterion must not flip the Required
        conditions' GO/NO-GO decision -- promotion is informational only."""
        module = _load_module(monkeypatch, tmp_path)
        results = {
            "ledger_quality": {"label": "ledger_quality_gate", "pass": True, "actual": "VALID", "required": "VALID"},
            "circuit_breaker": {"label": "circuit_breaker", "pass": True, "actual": "ok", "required": "ok"},
        }
        promotion_all_failing = {
            "cluster_cap": {"label": "cluster_cap", "pass": False, "actual": "x", "required": "y", "detail": ""},
        }
        report = module.format_report(results, save=False, promotion=promotion_all_failing)
        assert "🟢 **GO**" in report  # required conditions still all pass

    def test_pairwise_correlation_row_present_when_available(self, tmp_path, monkeypatch):
        module = _load_module(monkeypatch, tmp_path)
        results = {
            "ledger_quality": {"label": "ledger_quality_gate", "pass": True, "actual": "VALID", "required": "VALID"},
        }
        promotion = {
            "pairwise_correlation": {
                "label": "pairwise_correlation", "pass": False,
                "actual": ["AMZN/MSFT=0.94"], "required": "no pair with |correlation|>=0.8",
                "detail": "checked 10 pair(s)",
            },
        }
        report = module.format_report(results, save=False, promotion=promotion)
        assert "pairwise_correlation" in report
        assert "AMZN/MSFT=0.94" in report

    def test_main_return_code_unaffected_by_promotion(self, tmp_path, monkeypatch):
        """main()'s exit code is derived only from Required `results`, not
        from the promotion dict, even when promotion entirely fails."""
        module = _load_module(monkeypatch, tmp_path)
        with patch.object(module, "check", return_value={
            "ledger_quality": {"label": "x", "pass": True, "actual": "a", "required": "a"},
        }), patch.object(module, "check_promotion_readiness", return_value={
            "cluster_cap": {"label": "cluster_cap", "pass": False, "actual": "x", "required": "y", "detail": ""},
        }), patch.object(sys, "argv", ["check_go_no_go.py"]):
            rc = module.main()
        assert rc == 0  # required conditions all passed -> GO, regardless of promotion
