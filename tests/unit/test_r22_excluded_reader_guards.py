"""R22 2026-10-21: excluded historical readers stop before analysis or I/O.

These 26 non-overlap acceptance cases are adapted from sibling commit 9b5bd30,
test_r22_reader_disposition.py. Operational/descriptive reader contracts are
deliberately excluded: those readers have separate lineage-aware tests.
"""
import importlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from stock_swing.tracking.history_migration import apply_migration
from stock_swing.tracking.ledger_transaction import LedgerConflict
from tests.unit.test_r22_history_migration import fixture_plan


LOADERS = [
    ("analyze_atr_risk_sizing_counterfactual", "load_state", "path"),
    ("analyze_breakeven_staged_floor", "load_breakeven_trades", None),
    ("analyze_earnings_blackout_counterfactual", "load_closed_trades", None),
    ("analyze_execution_costs", "load_closed_trades", None),
    ("analyze_news_impact", "load_closed_trades", "root"),
    ("analyze_regime_filter_counterfactual", "load_closed_trades", None),
    ("analyze_sector_cap_counterfactual", "load_data", "registry"),
    ("analyze_ss_sizing_counterfactual", "load_ss_trades", "path"),
    ("analyze_stop_loss_post_exit", "load_stop_loss_trades", None),
    ("analyze_tiered_min_hold_v2_historical", "load_stop_loss_trades", None),
    ("compare_exit_variants", "load_pnl_state", "path"),
    ("sector_shock_historical_replay", "load_stop_loss_trades", None),
    ("simulate_confidence_multiplier_sizing_fix", "load_closed_trades_by_decision_id", None),
    ("simulate_confidence_multiplier_sizing_fix", "load_any_status_trades_by_decision_id", None),
    ("simulate_daily_path_volatility_stop", "load_all_closed_trades", None),
    ("simulate_early_weakness_cut", "load_all_closed_trades", None),
    ("simulate_signal_strength_exit_decoupling", "load_trades_with_signal_strength", None),
    ("simulate_stop_loss_deepening", "load_all_closed_trades", None),
    ("simulate_volatility_adjusted_stop", "load_all_stop_loss_trades", None),
]
PROGRAMS = ["analyze_entry_exit_pairs", "compare_etf_stock_attribution", "g1_investigate_mismatch",
            "investigate_klac_split_anomaly", "report_exit_attribution", "check_exit_reasons", "sim_ae"]


def _migrated(root):
    _, _, plan = fixture_plan(root)
    apply_migration(root, plan)
    return root / "data/tracking/pnl_state.json"


def _bytes(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("module,function,argument", LOADERS)
def test_ac_excluded_imported_reader_refuses_corrected_history_before_analysis(tmp_path, monkeypatch, capsys,
                                                                            module, function, argument):
    source = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(source / "scripts"))
    path = _migrated(tmp_path)
    reader = importlib.import_module("scripts." + module)
    for name in ("ROOT", "PROJECT_ROOT", "project_root"):
        if hasattr(reader, name):
            monkeypatch.setattr(reader, name, tmp_path)
    for name in ("STATE_PATH", "STATE_FILE", "PNL_STATE", "PNL_STATE_PATH"):
        if hasattr(reader, name):
            monkeypatch.setattr(reader, name, path)
    arguments = {"path": [path], "root": [tmp_path], "registry": [path, tmp_path / "absent.yaml"], None: []}[argument]
    before = _bytes(tmp_path)
    with pytest.raises(LedgerConflict, match="unqualified"):
        getattr(reader, function)(*arguments)
    assert _bytes(tmp_path) == before, "excluded analysis cannot create reports or modify evidence"
    assert capsys.readouterr().out == "", "rejection must precede analytical output"


@pytest.mark.parametrize("program", PROGRAMS)
def test_ac_excluded_program_stops_before_secondary_inputs_reports_or_market_io(tmp_path, program):
    source = Path(__file__).resolve().parents[2]
    _migrated(tmp_path)
    script = tmp_path / "scripts" / (program + ".py")
    script.parent.mkdir()
    shutil.copy2(source / "scripts" / script.name, script)
    before = _bytes(tmp_path)
    result = subprocess.run([sys.executable, str(script)], cwd=tmp_path,
                            env={**os.environ, "PYTHONPATH": str(source / "src") + os.pathsep + str(source),
                                 "PYTHONDONTWRITEBYTECODE": "1"},
                            capture_output=True, text=True, timeout=20)
    assert result.returncode != 0, "excluded entrypoint must not complete an unsupported analysis"
    assert "unqualified" in result.stderr, "failure must be the history guard, not missing secondary input"
    assert result.stdout == "", "no analytical result may be emitted before rejection"
    assert before == _bytes(tmp_path), "reports, adjustment artifacts and financial evidence must remain unchanged"
