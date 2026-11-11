"""R22 scheduled-reader lineage regression, 2026-10-21 / base 3a81598.

Acceptance: scheduled reports remain descriptive, carry the measured revision,
never splice quarantine trends across revisions, and preserve prior evidence on
unavailable/corrupt input. All ledgers are isolated fixtures, never production.
"""
import json

import pytest

from scripts import analyze_signal_strength_decile as decile
from scripts import check_quarantine_trend as quarantine
from stock_swing.tracking.history_migration import apply_migration
from stock_swing.tracking.ledger_transaction import FILES, LedgerConflict
from tests.unit.test_r22_history_migration import fixture_plan


def legacy_state(root, *, trades=None, quarantined=None):
    path = root / "data/tracking/pnl_state.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"trades": trades or [], "quarantined_trades": quarantined or []}))
    return path


def snapshot(count=2, *, revision=None):
    result = {"checked_at": "2026-10-21T06:00:00Z", "quarantine_count": count,
              "newest_quarantined_entry_time": "2026-07-20T13:30:00Z" if count else None}
    if revision is not None:
        result["measurement_provenance"] = {"ledger_revision": revision, "promotion_ready": False}
    return result


def configure_quarantine(monkeypatch, root):
    monkeypatch.setattr(quarantine, "STATE_PATH", root / "data/tracking/pnl_state.json")
    monkeypatch.setattr(quarantine, "HISTORY_PATH", root / "data/audits/quarantine_trend_history.jsonl")


def test_ac_migrated_decile_saves_descriptive_revision_without_modifying_ledger(tmp_path, monkeypatch, capsys):
    _, _, plan = fixture_plan(tmp_path)
    apply_migration(tmp_path, plan)
    before = {name: (tmp_path / "data/tracking" / name).read_bytes() for name in FILES}
    monkeypatch.setattr(decile, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["decile", "--save"])
    assert decile.main() == 0, "a coherent corrected snapshot remains available for descriptive reporting"
    report = json.loads((tmp_path / "reports/signal_strength_decile.json").read_text())
    context = report["measurement_provenance"]
    assert context["ledger_revision"] == plan["migration_id"], "saved output must identify the actual corrected revision"
    assert context["measurement_status"] == "historical_correction_unqualified"
    assert context["promotion_ready"] is False
    assert len(context["state_sha256"]) == len(context["events_sha256"]) == 64
    assert "Recommendation:" not in capsys.readouterr().out, "descriptive buckets are not a causal threshold recommendation"
    assert before == {name: (tmp_path / "data/tracking" / name).read_bytes() for name in FILES}


def test_ac_legacy_decile_metrics_preserved_and_context_saved(tmp_path, monkeypatch):
    legacy_state(tmp_path, trades=[{"status": "closed", "entry_signal_strength": .7, "pnl": 100},
                                  {"status": "closed", "entry_signal_strength": .8, "pnl": -50}])
    monkeypatch.setattr(decile, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["decile", "--save", "--buckets", "1"])
    assert decile.main() == 0
    report = json.loads((tmp_path / "reports/signal_strength_decile.json").read_text())
    assert report["decile_stats"][0]["profit_factor"] == pytest.approx(2)
    assert report["decile_stats"][0]["expectancy"] == pytest.approx(25)
    assert report["measurement_provenance"]["ledger_revision"] == "legacy"
    assert report["measurement_provenance"]["promotion_ready"] is False


@pytest.mark.parametrize("fault", ["missing", "corrupt", "prepared"])
def test_ac_decile_unavailable_state_preserves_prior_report(tmp_path, monkeypatch, fault):
    state = legacy_state(tmp_path)
    if fault == "missing":
        state.unlink()
    elif fault == "corrupt":
        state.write_text("{broken")
    else:
        (state.parent / ".ledger_transaction.json").write_text("{}")
    output = tmp_path / "reports/signal_strength_decile.json"
    output.parent.mkdir()
    output.write_bytes(b"prior-good-report")
    monkeypatch.setattr(decile, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["decile", "--save"])
    before = {p: p.read_bytes() for p in state.parent.iterdir() if p.is_file()}
    assert decile.main() == 2, "input unavailability is not successful empty analysis"
    assert output.read_bytes() == b"prior-good-report", "prior evidence must survive failed input validation"
    assert before == {p: p.read_bytes() for p in before}, "read-only reporting cannot recover or rewrite a prepared ledger"


@pytest.mark.parametrize("field", ["pnl", "entry_signal_strength"])
@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), "not-a-number"])
def test_ac_nonfinite_or_boolean_report_values_refuse_save(tmp_path, monkeypatch, field, bad):
    trade = {"status": "closed", "entry_signal_strength": .9, "pnl": 10}
    trade[field] = bad
    legacy_state(tmp_path, trades=[trade])
    output = tmp_path / "reports/signal_strength_decile.json"
    output.parent.mkdir()
    output.write_text("prior-good-report")
    monkeypatch.setattr(decile, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["decile", "--save"])
    assert decile.main() == 2, "NaN/Infinity/bool cannot become valid report metrics"
    assert output.read_text() == "prior-good-report"


def test_ac_best_observed_bucket_is_not_a_threshold_recommendation(capsys):
    rows = decile.compute_decile_stats([{"status": "closed", "entry_signal_strength": .9, "pnl": 20},
                                        {"status": "closed", "entry_signal_strength": .8, "pnl": -10}], n_buckets=1)
    decile.print_table(rows, 2, 2)
    output = capsys.readouterr().out
    assert "Recommendation:" not in output, "in-sample best buckets do not establish a causal threshold improvement"
    assert "descriptive" in output.lower()


@pytest.mark.parametrize("buckets", [0, -1, True, 1.5])
def test_ac_invalid_bucket_count_cannot_silently_produce_empty_analysis(buckets):
    with pytest.raises(ValueError, match="positive integer"):
        decile.compute_decile_stats([], n_buckets=buckets)


def test_ac_finite_inputs_that_overflow_aggregate_refuse_report():
    with pytest.raises(ValueError, match="finite number"):
        decile.compute_decile_stats([{"status": "closed", "entry_signal_strength": .8, "pnl": 1e308},
                                    {"status": "closed", "entry_signal_strength": .9, "pnl": 1e308}], n_buckets=1)


def test_ac_migrated_quarantine_snapshot_and_saved_history_carry_revision(tmp_path, monkeypatch, capsys):
    _, _, plan = fixture_plan(tmp_path)
    apply_migration(tmp_path, plan)
    configure_quarantine(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.argv", ["quarantine", "--save"])
    assert quarantine.main() == 0
    saved = quarantine.load_history()[-1]
    assert saved["measurement_provenance"]["ledger_revision"] == plan["migration_id"]
    assert saved["measurement_provenance"]["promotion_ready"] is False
    assert plan["migration_id"] in capsys.readouterr().out, "console output must disclose the reported revision"


@pytest.mark.parametrize("count", [1, 4])
def test_ac_revision_crossing_never_claims_quarantine_growth_or_repair(count):
    current = snapshot(count, revision="corrected-revision")
    result = quarantine.evaluate_trend(current, [snapshot(2)])
    assert result["status"] == "revision_changed"
    assert result["count_delta"] is None, "a ledger replacement is not an economic trend observation"
    assert result["new_quarantine_detected"] is False
    assert "legacy" in result["message"] and "corrected-revision" in result["message"]


def test_ac_contextless_legacy_history_remains_comparable():
    result = quarantine.evaluate_trend(snapshot(3, revision="legacy"), [snapshot(2)])
    assert result["status"] == "growing"
    assert result["count_delta"] == 1


def test_ac_same_corrected_revision_remains_comparable():
    result = quarantine.evaluate_trend(snapshot(2, revision="same-revision"), [snapshot(2, revision="same-revision")])
    assert result["status"] == "stable"
    assert result["count_delta"] == 0


@pytest.mark.parametrize("fault", ["missing", "corrupt", "prepared"])
def test_ac_quarantine_unavailable_state_never_appends_history(tmp_path, monkeypatch, fault):
    state = legacy_state(tmp_path)
    if fault == "missing":
        state.unlink()
    elif fault == "corrupt":
        state.write_text("{broken")
    else:
        (state.parent / ".ledger_transaction.json").write_text("{}")
    configure_quarantine(monkeypatch, tmp_path)
    history = quarantine.HISTORY_PATH
    history.parent.mkdir()
    history.write_text(json.dumps(snapshot()) + "\n")
    before = history.read_bytes()
    monkeypatch.setattr("sys.argv", ["quarantine", "--save"])
    assert quarantine.main() == 2
    assert history.read_bytes() == before, "failed snapshot cannot append a false successful baseline"


@pytest.mark.parametrize("bad_line", ["not JSON", "[]", '{"quarantine_count":101}',
                                     json.dumps(dict(snapshot(), quarantine_count=True)),
                                     json.dumps(dict(snapshot(), newest_quarantined_entry_time="not-a-date")),
                                     json.dumps(dict(snapshot(), measurement_provenance={"ledger_revision": None}))])
def test_ac_corrupt_history_is_not_silently_skipped_into_success(tmp_path, monkeypatch, bad_line):
    legacy_state(tmp_path)
    configure_quarantine(monkeypatch, tmp_path)
    quarantine.HISTORY_PATH.parent.mkdir()
    quarantine.HISTORY_PATH.write_text(bad_line + "\n" + json.dumps(snapshot()) + "\n")
    before = quarantine.HISTORY_PATH.read_bytes()
    with pytest.raises((ValueError, LedgerConflict)):
        quarantine.load_history()
    monkeypatch.setattr("sys.argv", ["quarantine", "--save"])
    assert quarantine.main() == 2, "corrupt history cannot be reported as a successful stable/baseline trend"
    assert quarantine.HISTORY_PATH.read_bytes() == before


def test_ac_direct_trend_refuses_malformed_previous_snapshot():
    with pytest.raises(ValueError):
        quarantine.evaluate_trend(snapshot(), [{"quarantine_count": "2"}])
