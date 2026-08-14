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
