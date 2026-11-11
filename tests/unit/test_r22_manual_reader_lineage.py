"""R22 regression 2026-10-21: manual diagnostics cannot qualify stale history.

Acceptance: coherent input, explicit exact provenance, strict finite economics,
no journal recovery, and operational recovery kept separate from promotion.
"""
import json

import pytest

from scripts import check_operational_recovery as recovery
from scripts import check_pnl_invariants as invariants
from stock_swing.tracking.compatibility import read_analysis_snapshot
from stock_swing.tracking.history_migration import apply_migration
from stock_swing.tracking.ledger_transaction import FILES
from tests.unit.test_operational_recovery import NOW, seed
from tests.unit.test_r22_history_migration import fixture_plan


def _state(root, migrated=False):
    path = root / "data/tracking/pnl_state.json"
    if migrated:
        _, _, plan = fixture_plan(root)
        apply_migration(root, plan)
    else:
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"trades": [{"status": "closed", "pnl": 10.0}],
                                    "cumulative_realized_pnl": 10.0,
                                    "quarantined_trades": [{"pnl": -2.0}]}))
    return path


def _export(root, state_path):
    state, context = read_analysis_snapshot(state_path)
    path = root / "data/analysis/performance_summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"realized_pnl": state["cumulative_realized_pnl"],
                                "measurement_provenance": context}))
    return path


def _run(monkeypatch, state, perf):
    monkeypatch.setattr(invariants, "STATE_PATH", state)
    monkeypatch.setattr(invariants, "PERF_PATH", perf)
    return invariants.main()


def test_ac_recovery_emits_coherent_revision_without_authorizing_promotion(tmp_path):
    path = _state(tmp_path, migrated=True)
    seed_root = tmp_path / "operational_seed"
    seed(seed_root)
    for rel in ("reports/console/latest_console_summary.json", "data/guardrails/circuit_breaker.json",
                "data/guardrails/economic_risk_off.json"):
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((seed_root / rel).read_bytes())
    summary_path = tmp_path / 'reports/console/latest_console_summary.json'
    summary = json.loads(summary_path.read_text())
    summary['ledger_quality'] = {'measurement_lineage': json.loads(path.read_text())['measurement_lineage']}
    summary_path.write_text(json.dumps(summary))
    before = {n: (path.parent / n).read_bytes() for n in FILES}
    report = recovery.assess(tmp_path, now=NOW)
    assert report["operational_recovered"] is True, "measurement uncertainty is not a missed scheduled run"
    assert report["measurement_provenance"] == read_analysis_snapshot(path)[1]
    assert report["economic_viability"]["pass"] is False
    assert report["promotion_authorized_by_this_check"] is False
    assert before == {n: (path.parent / n).read_bytes() for n in FILES}


@pytest.mark.parametrize("damage", ["events", "prepared", "missing", "json"])
def test_ac_recovery_unavailable_economics_does_not_recover_ledger_or_hide_scheduled_evidence(tmp_path, damage):
    seed(tmp_path)
    path = tmp_path / "data/tracking/pnl_state.json"
    if damage == "events":
        (path.parent / "trade_events.jsonl").write_text("not-json\n")
    elif damage == "prepared":
        (path.parent / ".ledger_transaction.json").write_text('{"state":"prepared"}')
    elif damage == "missing":
        path.unlink()
    else:
        path.write_text("{")
    before = {p.name: p.read_bytes() for p in path.parent.iterdir() if p.is_file()}
    report = recovery.assess(tmp_path, now=NOW)
    assert report['scheduled_execution_evidence_complete'] is True
    assert report["operational_recovered"] is False
    assert report["economic_viability"]["pass"] is False
    assert report["measurement_provenance"] is None
    assert report["ledger_error"], "unavailable input needs an explicit error, not an empty-success fallback"
    assert all((path.parent / n).read_bytes() == raw for n, raw in before.items())


def test_ac_old_console_revision_cannot_be_operational_recovery_after_migration(tmp_path):
    seed(tmp_path)
    path = tmp_path / 'data/tracking/pnl_state.json'
    # Replace only this test's fixture state with a coherent corrected ledger;
    # leave the genuine/fresh console observation on its original old revision.
    for p in path.parent.iterdir():
        if p.is_file():
            p.unlink()
    path.parent.rmdir()
    _state(tmp_path, migrated=True)
    report = recovery.assess(tmp_path, now=NOW)
    assert report['scheduled_execution_evidence_complete'] is True
    assert report['operational_recovered'] is False
    assert report['summary_lineage_matches'] is False
    assert report['economic_viability']['pass'] is False


@pytest.mark.parametrize("bad", [True, "10", None, float("nan"), float("inf")])
def test_ac_recovery_rejects_invalid_economic_values_without_changing_operational_status(tmp_path, bad):
    seed(tmp_path)
    path = tmp_path / "data/tracking/pnl_state.json"
    state = json.loads(path.read_text())
    state["trades"][0]["pnl"] = bad
    path.write_text(json.dumps(state))
    report = recovery.assess(tmp_path, now=NOW)
    assert report["operational_recovered"] is True
    assert report["economic_viability"]["pass"] is False
    assert "invalid" in report["economic_viability"]["actual"].lower()


@pytest.mark.parametrize("migrated", [False, True])
def test_ac_versioned_matching_invariants_are_only_descriptive(tmp_path, monkeypatch, capsys, migrated):
    path = _state(tmp_path, migrated)
    perf = _export(tmp_path, path)
    assert _run(monkeypatch, path, perf) == 0
    out = capsys.readouterr().out
    assert '"measurement_provenance"' in out
    assert '"performance_qualified": false' in out
    assert '"promotion_ready": false' in out
    assert "All invariants PASS" not in out, "a local accounting diagnostic cannot claim full qualification"


@pytest.mark.parametrize("field", ["ledger_revision", "state_sha256", "events_sha256"])
@pytest.mark.parametrize("mutation", ["remove", "different"])
def test_ac_equal_pnl_cannot_hide_stale_or_missing_provenance(tmp_path, monkeypatch, capsys, field, mutation):
    path = _state(tmp_path, migrated=True)
    perf = _export(tmp_path, path)
    payload = json.loads(perf.read_text())
    if mutation == "remove":
        del payload["measurement_provenance"][field]
    else:
        payload["measurement_provenance"][field] = "another-observation"
    perf.write_text(json.dumps(payload))
    assert _run(monkeypatch, path, perf) != 0
    assert "provenance" in capsys.readouterr().out.lower()


def test_ac_missing_performance_export_is_skipped_diagnostic_not_full_pass(tmp_path, monkeypatch, capsys):
    path = _state(tmp_path)
    perf = tmp_path / "data/analysis/absent.json"
    assert _run(monkeypatch, path, perf) == 2
    out = capsys.readouterr().out
    assert "diagnostic_only" in out and "skipped" in out
    assert "All invariants PASS" not in out


@pytest.mark.parametrize("location", ["closed", "quarantined", "cumulative", "performance"])
@pytest.mark.parametrize("bad", [True, "10", None, float("nan"), float("inf")])
def test_ac_malformed_financial_values_never_launder_as_zero_or_boolean(tmp_path, monkeypatch, capsys, location, bad):
    path = _state(tmp_path)
    state = json.loads(path.read_text())
    if location == "closed":
        state["trades"][0]["pnl"] = bad
    elif location == "quarantined":
        state["quarantined_trades"][0]["pnl"] = bad
    elif location == "cumulative":
        state["cumulative_realized_pnl"] = bad
    path.write_text(json.dumps(state))
    perf = _export(tmp_path, path)
    if location == "performance":
        payload = json.loads(perf.read_text())
        payload["realized_pnl"] = bad
        perf.write_text(json.dumps(payload))
    assert _run(monkeypatch, path, perf) != 0
    assert "All invariants PASS" not in capsys.readouterr().out


@pytest.mark.parametrize("damage", ["missing_state", "corrupt_state", "corrupt_events", "prepared", "corrupt_perf", "perf_shape"])
def test_ac_damaged_manual_inputs_fail_without_repair_or_unsafe_rebuild_advice(tmp_path, monkeypatch, capsys, damage):
    path = _state(tmp_path, migrated=True)
    perf = _export(tmp_path, path)
    if damage == "missing_state":
        path.unlink()
    elif damage == "corrupt_state":
        path.write_text("{")
    elif damage == "corrupt_events":
        (path.parent / "trade_events.jsonl").write_text("no-json\n")
    elif damage == "prepared":
        (path.parent / ".ledger_transaction.json").write_text('{"state":"prepared"}')
    elif damage == "corrupt_perf":
        perf.write_text("{")
    else:
        perf.write_text("[]")
    before = {p.name: p.read_bytes() for p in path.parent.iterdir() if p.is_file()}
    assert _run(monkeypatch, path, perf) != 0
    out = capsys.readouterr().out
    assert "rebuild_pnl_source_of_truth.py" not in out
    assert before == {p.name: p.read_bytes() for p in path.parent.iterdir() if p.is_file()}


def test_ac_numeric_overflow_and_mismatched_sums_are_rejected(tmp_path, monkeypatch, capsys):
    path = _state(tmp_path)
    state = json.loads(path.read_text())
    state["trades"] = [{"status": "closed", "pnl": 1e308}] * 2
    path.write_text(json.dumps(state))
    perf = _export(tmp_path, path)
    assert _run(monkeypatch, path, perf) != 0
    out = capsys.readouterr().out
    assert "All invariants PASS" not in out
    state["trades"] = [{"status": "closed", "pnl": 12.0}]
    path.write_text(json.dumps(state))
    perf.unlink()
    perf = _export(tmp_path, path)
    assert _run(monkeypatch, path, perf) == 1


@pytest.mark.parametrize("delta,expected", [(1.0, 0), (-1.0, 0), (1.0001, 1), (-1.0001, 1)])
def test_ac_version_matched_performance_still_requires_amount_agreement(tmp_path, monkeypatch, delta, expected):
    path = _state(tmp_path)
    perf = _export(tmp_path, path)
    payload = json.loads(perf.read_text())
    payload["realized_pnl"] += delta
    perf.write_text(json.dumps(payload))
    assert _run(monkeypatch, path, perf) == expected, "exact provenance cannot waive the existing $1 amount tolerance"


def test_ac_recovery_report_persists_measurement_context_without_qualifying_it(tmp_path):
    seed(tmp_path)
    report = recovery.assess(tmp_path, now=NOW)
    output = tmp_path / "reports/operations/operational_recovery_status.json"
    recovery.save_report(report, output)
    saved = json.loads(output.read_text())
    assert saved["measurement_provenance"] == read_analysis_snapshot(tmp_path / "data/tracking/pnl_state.json")[1]
    assert saved["measurement_provenance"]["promotion_ready"] is False
    assert saved["performance_qualified"] is False
