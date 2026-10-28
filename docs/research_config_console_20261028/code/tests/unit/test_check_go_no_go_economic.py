"""P0 (2026-09-05): scripts/check_go_no_go.py economic_viability gate.

Background: every Required condition before this gate checked only that the
system is INTACT (freshness / ledger / guardrails / cron health) -- none
asked whether the system is economically viable. With paper results at
PF 0.888 / realized PnL -$38,253 (5/12-09/05, 357 closed), an all-green GO
would have been a GO for a "not broken but not profitable" system.

The gate (user-approved 2026-09-05, intentionally fail-closed):
  - cohort: closed trades with exit_time >= 2026-08-14
    (overridable via --econ-cohort-start)
  - pass requires n>=30 AND PF>1.0 AND expectancy>0
  - n<30 -> insufficient_sample, fail-closed (NO-GO)
  - it is a REQUIRED condition: failing it must flip the overall verdict
    to NO-GO and main()'s exit code to 1. Thresholds must NOT be loosened
    to make it pass.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_go_no_go.py"


def _load_module(monkeypatch, project_root: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_go_no_go_economic", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "PROJECT_ROOT", project_root)
    return module


def _make_trades(n: int, pnl_each: float, exit_date: str = "2026-08-20") -> list[dict]:
    return [
        {
            "status": "closed",
            "exit_time": f"{exit_date}T15:30:00+00:00",
            "pnl": pnl_each,
            "symbol": f"SYM{i}",
        }
        for i in range(n)
    ]


def _write_pnl_state(project_root: Path, trades: list[dict]):
    tracking = project_root / "data" / "tracking"
    tracking.mkdir(parents=True, exist_ok=True)
    (tracking / "pnl_state.json").write_text(
        json.dumps({"trades": trades, "daily_snapshots": []}), encoding="utf-8"
    )


class TestCheckEconomicViability:
    """Unit tests against check_economic_viability() directly (pure logic,
    no filesystem beyond the pnl_state dict passed in)."""

    def test_pass_when_all_criteria_met(self, tmp_path, monkeypatch):
        module = _load_module(monkeypatch, tmp_path)
        # 20 winners +$200, 10 losers -$100 -> PF=4000/1000=4.0, expectancy>0
        trades = _make_trades(20, 200.0) + _make_trades(10, -100.0)
        result = module.check_economic_viability({"trades": trades}, "2026-08-14")
        assert result["pass"] is True
        assert "n=30" in result["actual"]
        assert result["econ_detail"]["insufficient_sample"] is False

    def test_no_go_when_pf_below_one(self, tmp_path, monkeypatch):
        """Mirrors the live 2026-09-05 situation (PF<1): sufficient sample
        but losing economics -> must fail. This is the INTENDED outcome;
        thresholds must not be loosened to flip it."""
        module = _load_module(monkeypatch, tmp_path)
        # 15 winners +$100, 15 losers -$200 -> PF=1500/3000=0.5, expectancy<0
        trades = _make_trades(15, 100.0) + _make_trades(15, -200.0)
        result = module.check_economic_viability({"trades": trades}, "2026-08-14")
        assert result["pass"] is False
        assert "PF=0.500" in result["actual"]
        assert "insufficient_sample" not in result["actual"]

    def test_insufficient_sample_fails_closed(self, tmp_path, monkeypatch):
        """n<30 must fail even with perfect economics (fail-closed)."""
        module = _load_module(monkeypatch, tmp_path)
        trades = _make_trades(20, 500.0) + _make_trades(9, -10.0)  # n=29, PF>>1
        result = module.check_economic_viability({"trades": trades}, "2026-08-14")
        assert result["pass"] is False
        assert result["actual"].startswith("insufficient_sample")
        assert result["econ_detail"]["insufficient_sample"] is True
        assert result["econ_detail"]["n"] == 29

    def test_empty_pnl_state_fails_closed(self, tmp_path, monkeypatch):
        module = _load_module(monkeypatch, tmp_path)
        result = module.check_economic_viability({}, "2026-08-14")
        assert result["pass"] is False
        assert result["actual"].startswith("insufficient_sample")
        assert result["econ_detail"]["n"] == 0

    def test_cohort_start_filters_older_trades(self, tmp_path, monkeypatch):
        """Trades exited before the cohort start must be excluded from n,
        PF, and expectancy."""
        module = _load_module(monkeypatch, tmp_path)
        old = _make_trades(100, 1000.0, exit_date="2026-08-13")  # day before cutoff
        recent = _make_trades(10, -50.0, exit_date="2026-08-14")
        result = module.check_economic_viability({"trades": old + recent}, "2026-08-14")
        assert result["econ_detail"]["n"] == 10  # only the recent 10
        assert result["pass"] is False  # insufficient_sample despite 110 total

    def test_open_and_pnl_less_trades_excluded(self, tmp_path, monkeypatch):
        module = _load_module(monkeypatch, tmp_path)
        trades = _make_trades(30, 100.0)
        trades += [{"status": "open", "exit_time": "2026-08-20T00:00:00", "pnl": 999.0}]
        trades += [{"status": "closed", "exit_time": "2026-08-20T00:00:00", "pnl": None}]
        result = module.check_economic_viability({"trades": trades}, "2026-08-14")
        assert result["econ_detail"]["n"] == 30

    def test_all_winners_pf_inf_passes(self, tmp_path, monkeypatch):
        """gross_loss=0 with gross_profit>0 -> PF=inf, which is > 1.0."""
        module = _load_module(monkeypatch, tmp_path)
        trades = _make_trades(30, 100.0)
        result = module.check_economic_viability({"trades": trades}, "2026-08-14")
        assert result["pass"] is True
        assert "PF=inf" in result["actual"]


class TestCheckIntegration:
    """economic_viability must be wired into check() as a Required condition
    read from data/tracking/pnl_state.json under PROJECT_ROOT."""

    def test_check_includes_economic_viability(self, tmp_path, monkeypatch):
        module = _load_module(monkeypatch, tmp_path)
        _write_pnl_state(tmp_path, _make_trades(15, 100.0) + _make_trades(15, -200.0))
        results = module.check()
        assert "economic_viability" in results
        assert results["economic_viability"]["pass"] is False

    def test_check_missing_pnl_state_fails_closed(self, tmp_path, monkeypatch):
        module = _load_module(monkeypatch, tmp_path)
        results = module.check()
        assert results["economic_viability"]["pass"] is False
        assert "insufficient_sample" in results["economic_viability"]["actual"]

    def test_check_econ_cohort_start_override(self, tmp_path, monkeypatch):
        """check(econ_cohort_start=...) (the --econ-cohort-start plumbing)
        changes which trades are counted."""
        module = _load_module(monkeypatch, tmp_path)
        _write_pnl_state(
            tmp_path,
            _make_trades(20, 200.0, exit_date="2026-07-01")
            + _make_trades(20, 300.0, exit_date="2026-08-20"),
        )
        default = module.check()
        assert default["economic_viability"]["econ_detail"]["n"] == 20  # >= 08-14 only
        widened = module.check(econ_cohort_start="2026-06-01")
        assert widened["economic_viability"]["econ_detail"]["n"] == 40
        assert widened["economic_viability"]["pass"] is True


class TestFormatReportAndExitCode:
    def test_failing_economic_gate_forces_no_go(self, tmp_path, monkeypatch):
        """Unlike the supplementary promotion section, economic_viability is
        Required: its failure alone must flip the verdict to NO-GO."""
        module = _load_module(monkeypatch, tmp_path)
        results = {
            "ledger_quality": {"label": "ledger_quality_gate", "pass": True, "actual": "VALID", "required": "VALID"},
            "economic_viability": {
                "label": "economic_viability", "pass": False,
                "actual": "n=45, PF=0.530, expectancy=$-551.33 (cohort exit_time>=2026-08-14)",
                "required": "n>=30 & PF>1.0 & expectancy>0",
                "econ_detail": {
                    "cohort_start": "2026-08-14", "n": 45,
                    "gross_profit": 10000.0, "gross_loss": 18868.0,
                    "pf": "0.530", "expectancy": "$-551.33",
                    "insufficient_sample": False,
                },
            },
        }
        report = module.format_report(results, save=False, promotion=None)
        assert "NO-GO" in report
        assert "economic_viability" in report
        # Detail section (styled like the R5-v2 promotion supplement) present:
        assert "経済性ゲート詳細" in report
        assert "0.530" in report

    def test_report_without_econ_detail_omits_section(self, tmp_path, monkeypatch):
        module = _load_module(monkeypatch, tmp_path)
        results = {
            "ledger_quality": {"label": "ledger_quality_gate", "pass": True, "actual": "VALID", "required": "VALID"},
        }
        report = module.format_report(results, save=False, promotion=None)
        assert "経済性ゲート詳細" not in report

    def test_main_exit_code_1_when_economic_gate_fails(self, tmp_path, monkeypatch):
        module = _load_module(monkeypatch, tmp_path)
        with patch.object(module, "check", return_value={
            "ledger_quality": {"label": "x", "pass": True, "actual": "a", "required": "a"},
            "economic_viability": {"label": "economic_viability", "pass": False, "actual": "n=45, PF=0.530", "required": "n>=30 & PF>1.0 & expectancy>0"},
        }), patch.object(module, "check_promotion_readiness", return_value=None), \
                patch.object(sys, "argv", ["check_go_no_go.py"]):
            rc = module.main()
        assert rc == 1

    def test_main_econ_cohort_start_flag_parsed(self, tmp_path, monkeypatch):
        module = _load_module(monkeypatch, tmp_path)
        captured = {}

        def _fake_check(econ_cohort_start=module.ECON_COHORT_START_DEFAULT):
            captured["start"] = econ_cohort_start
            return {"x": {"label": "x", "pass": True, "actual": "a", "required": "a"}}

        with patch.object(module, "check", side_effect=_fake_check), \
                patch.object(module, "check_promotion_readiness", return_value=None), \
                patch.object(sys, "argv", ["check_go_no_go.py", "--econ-cohort-start", "2026-07-01"]):
            module.main()
        assert captured["start"] == "2026-07-01"

    def test_main_econ_cohort_start_invalid_date_rejected(self, tmp_path, monkeypatch):
        module = _load_module(monkeypatch, tmp_path)
        with patch.object(sys, "argv", ["check_go_no_go.py", "--econ-cohort-start", "not-a-date"]):
            rc = module.main()
        assert rc == 2
