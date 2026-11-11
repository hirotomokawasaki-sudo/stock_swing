"""FIX-06 regression 2026-11-09 / sealed v7 + 11/06 quantity reader.

The explanatory quality panel must not certify counts from a broken/inflight
state/events pair. All financial inputs below are synthetic and private.
"""
import json
import subprocess
import sys
import time
from datetime import datetime, timezone

import pytest

from console.services.operational_inputs_service import quality_context
from stock_swing.tracking.history_migration import prepare_migration
from tests.unit.test_console_evidence_20261028 import js
from tests.unit.test_console_consistency_20261029 import svc

NOW = datetime(2026, 11, 9, 0, tzinfo=timezone.utc)


def seed(root, events=b"", rows=None):
    folder = root / "data/tracking"
    folder.mkdir(parents=True)
    state = {"trades": rows if rows is not None else [], "quarantined_trades": [],
             "last_updated": "2026-11-06T20:55:06Z"}
    inputs = {"pnl_state.json": json.dumps(state).encode(), "trade_events.jsonl": events,
              "fill_ledger.jsonl": b"", "fill_consumed_ledger.json": b'{"fills":[]}'}
    for name, body in inputs.items():
        (folder / name).write_bytes(body)
    return folder, inputs


def frozen(folder):
    return {p.name: (p.read_bytes(), p.stat().st_mode & 0o777)
            for p in folder.iterdir() if p.is_file() and p.name != ".ledger.lock"}


@pytest.mark.parametrize("journal", [b'{"version":1,"state":"prepared","files":[]}', b'{PRIVATE-broken'])
def test_ac_prepared_or_corrupt_journal_withholds_counts(tmp_path, journal):
    folder, _ = seed(tmp_path)
    (folder / ".ledger_transaction.json").write_bytes(journal)
    before = frozen(folder)
    out = quality_context(tmp_path, now=NOW)
    assert out["status"] == "unknown" and out["inline_quarantined"] is None, "inflight journal was reported as a valid count"
    assert out["separate_quarantined"] is None and out.get("ledger_sha256") is None, "invalid pair received count or successful hash"
    assert "PRIVATE" not in json.dumps(out), "private journal detail escaped"
    assert frozen(folder) == before, "display repaired/changed prepared transaction"


@pytest.mark.parametrize("events", [b'{PRIVATE-broken', b'{"event_id":"x","event_type":"history_supersession","created_at":"2026-11-06T00:00:00Z","payload":{}}\n'])
def test_ac_invalid_or_orphan_events_withhold_counts(tmp_path, events):
    folder, _ = seed(tmp_path, events)
    before = frozen(folder)
    out = quality_context(tmp_path, now=NOW)
    assert out["status"] == "unknown" and out["inline_quarantined"] is None, "incoherent events were ignored by quality panel"
    assert frozen(folder) == before, "invalid financial pair changed"


def test_ac_real_process_lock_is_nonblocking_and_resumes(tmp_path):
    folder, _ = seed(tmp_path)
    before = frozen(folder)
    code = "import fcntl,sys; f=open(sys.argv[1],'a+b'); fcntl.flock(f,fcntl.LOCK_EX); print('LOCKED',flush=True); sys.stdin.readline()"
    child = subprocess.Popen([sys.executable, "-I", "-B", "-c", code, str(folder / ".ledger.lock")],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "LOCKED", "competing writer not locked"
        start = time.monotonic()
        out = quality_context(tmp_path, now=NOW)
        assert out["status"] == "unknown" and out["inline_quarantined"] is None, "active writer lock ignored"
        assert time.monotonic() - start < 1, "display blocked behind writer"
    finally:
        child.communicate("release\n", timeout=5)
    assert child.returncode == 0, "writer did not release cleanly"
    assert quality_context(tmp_path, now=NOW)["status"] == "reported", "reader did not resume after completed writer"
    assert frozen(folder) == before, "display mutated financial pair"


def test_ac_missing_input_does_not_create_tracking_directory(tmp_path):
    out = quality_context(tmp_path, now=NOW)
    assert out["status"] == "unknown" and out["inline_quarantined"] is None, "missing input became zero"
    assert not (tmp_path / "data").exists(), "read of absent input created tracking directory"


@pytest.mark.parametrize("body", [b'{broken', b'[]', b'{"trades":[],"quarantined_trades":NaN}', b'{"trades":[{"status":"typo"}]}'])
def test_ac_corrupt_state_fails_closed(tmp_path, body):
    folder, _ = seed(tmp_path)
    (folder / "pnl_state.json").write_bytes(body)
    before = frozen(folder)
    out = quality_context(tmp_path, now=NOW)
    assert out["status"] == "unknown" and out["inline_quarantined"] is None, "corrupt/schema-invalid state became valid count"
    assert frozen(folder) == before, "display rewrote corrupt state"


def test_ac_valid_pair_keeps_separate_counts_hashes_and_no_health_waiver(tmp_path):
    folder, _ = seed(tmp_path, rows=[{"status":"quarantined"}, {"status":"open"}])
    raw = json.loads((folder / "pnl_state.json").read_bytes())
    raw["quarantined_trades"] = [{"status":"quarantined"}]
    (folder / "pnl_state.json").write_text(json.dumps(raw))
    before = frozen(folder)
    out = quality_context(tmp_path, now=NOW)
    import hashlib
    assert out["status"] == "reported" and out["inline_quarantined"] == 1 and out["separate_quarantined"] == 1, "separate count semantics changed"
    assert out["ledger_sha256"] == hashlib.sha256(before["pnl_state.json"][0]).hexdigest(), "state hash not consumed bytes"
    assert out["ledger_events_sha256"] == hashlib.sha256(b"").hexdigest() and out["ledger_revision"] == "legacy", "pair identity missing"
    assert out["strict_health_waived"] is False and out["quality_stamp_updated"] is False and out["ledger_audit_status"] == "not_recertified", "descriptive count waived strict gate"
    assert frozen(folder) == before, "normal financial input changed"


def test_ac_valid_correction_pair_preserves_revision(tmp_path):
    row = dict(trade_id="synthetic-lot", symbol="SYN", status="closed", broker_order_id="buy", exit_broker_order_id="sell", qty=1, entry_price=10., exit_price=11., pnl=1., return_pct=.1, entry_time="2026-11-02T15:00:00Z", exit_time="2026-11-03T15:00:00Z", holding_days=1)
    folder, inputs = seed(tmp_path, rows=[row])
    plan = prepare_migration(inputs, row_changes=[dict(row_index=0, before=row, after={**row, "exit_price":12., "pnl":2., "return_pct":.2})], corporate_plans=[], evidence_sha256="1"*64, recorded_at="2026-11-06T07:00:00Z", reason="synthetic regression only")
    import base64
    (folder / "pnl_state.json").write_text(json.dumps(plan["after_state"]))
    (folder / "trade_events.jsonl").write_bytes(base64.b64decode(plan["after_events_b64"]))
    before = frozen(folder)
    out = quality_context(tmp_path, now=NOW)
    assert out["status"] == "reported" and out["ledger_revision"] == plan["migration_id"], "valid correction unreadable or wrong revision"
    assert frozen(folder) == before, "valid correction rewritten"


def test_ac_failure_propagates_through_json_and_real_renderer(tmp_path):
    folder, _ = seed(tmp_path)
    (folder / ".ledger_transaction.json").write_bytes(b'{broken')
    out = json.loads(json.dumps(quality_context(tmp_path, now=NOW), allow_nan=False))
    assert out["inline_quarantined"] is None and out["separate_quarantined"] is None, "wire converted unknown to zero"
    html = js("renderOperationalInputs", {"data":{"operational_evidence":{"quality_context":out}}})
    assert "台帳内隔離: 未確認行" in html and "別隔離配列: 未確認行" in html, "renderer converts unavailable counts to zero"


@pytest.mark.parametrize("invalid", ["prepared", "corrupt_journal", "corrupt_events"])
def test_ac_broker_failure_does_not_bypass_pair_guard_via_tracker_substitute(tmp_path, invalid):
    """A second direct read existed in the normal positions fallback."""
    folder, _ = seed(tmp_path, rows=[dict(status="open", symbol="SYN", qty=2, entry_price=10)])
    if invalid == "corrupt_events":
        (folder / "trade_events.jsonl").write_bytes(b'{PRIVATE-broken')
    else:
        (folder / ".ledger_transaction.json").write_bytes(b'{broken' if invalid == "corrupt_journal" else b'{"version":1,"state":"prepared","files":[]}')
    before = frozen(folder)
    out = json.loads(json.dumps(svc(tmp_path, [], failure=True).get_positions(), allow_nan=False))
    assert out["available"] is False and out["positions"] == [] and out["summary"] == {}, "incoherent financial pair became saved positions substitute"
    assert out["source"] == "none" and out["evidence"]["status"] == "error", "broker error lost during fallback"
    assert "PRIVATE" not in json.dumps(out), "private detail leaked"
    html = js("renderPositions", {"data":{"positions":out}})
    assert "取得範囲内に保有なし" not in html, "invalid fallback became confirmed flat"
    assert frozen(folder) == before, "fallback changed financial inputs"


def test_ac_tracker_substitute_checks_writer_lock_then_resumes(tmp_path):
    folder, _ = seed(tmp_path)
    before = frozen(folder)
    code = "import fcntl,sys; f=open(sys.argv[1],'a+b'); fcntl.flock(f,fcntl.LOCK_EX); print('LOCKED',flush=True); sys.stdin.readline()"
    child = subprocess.Popen([sys.executable, "-I", "-B", "-c", code, str(folder / ".ledger.lock")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "LOCKED", "competing writer not locked"
        start = time.monotonic()
        out = svc(tmp_path, [], failure=True).get_positions()
        assert out["available"] is False and time.monotonic() - start < 1, "fallback ignored or blocked behind writer"
    finally:
        child.communicate("release\n", timeout=5)
    out = svc(tmp_path, [], failure=True).get_positions()
    assert child.returncode == 0 and out["source"] == "tracker" and out["evidence"]["status"] == "substitute", "valid fallback did not resume"
    assert out["evidence"]["ledger_revision"] == "legacy", "substitute lost coherent pair identity"
    assert frozen(folder) == before, "fallback changed financial content"
