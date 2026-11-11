"""FIX-06 regression 2026-11-06 / baseline8909e79 + sealed102/v7.
Actual service -> JSON -> actual renderer; synthetic ledgers only.
An interrupted/invalid pair must not become a successful quantity match.
"""
import base64
import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
import subprocess
import sys
import time
import pytest
from console.services.followthrough_service import position_comparison, get_followthrough
from tests.unit.test_console_evidence_20261028 import js
from stock_swing.tracking.history_migration import prepare_migration
from stock_swing.tracking.ledger_transaction import digest
NOW=datetime(2026,11,6,8,tzinfo=timezone.utc)
EV={"status":"ok","as_of":NOW.isoformat(),"complete":True}


def seed(root, *, rows=None, events=b""):
    folder=root/"data/tracking";folder.mkdir(parents=True,exist_ok=True)
    state={"trades":[] if rows is None else rows,"quarantined_trades":[],"last_updated":"2026-11-06T07:55:00Z"}
    inputs={"pnl_state.json":json.dumps(state).encode(),"trade_events.jsonl":events,"fill_ledger.jsonl":b"", "fill_consumed_ledger.json":b'{"fills":[]}'}
    for name,body in inputs.items():(folder/name).write_bytes(body)
    return folder,inputs


def frozen(folder):
    return {p.name:(p.read_bytes(),p.stat().st_mode&0o777) for p in folder.iterdir() if p.is_file() and p.name!=".ledger.lock"}


@pytest.mark.parametrize("journal",[b'{"version":1,"state":"prepared","files":[]}',b'{PRIVATE-broken'])
def test_ac_prepared_or_corrupt_journal_never_matches(tmp_path,journal):
    """Before fix, state-only double read falsely returns mismatch_count=0."""
    folder,_=seed(tmp_path);(folder/".ledger_transaction.json").write_bytes(journal);before=frozen(folder)
    out=position_comparison(tmp_path,[],EV,NOW)
    assert out["status"]=="unknown" and out["mismatch_count"] is None,"interrupted transaction was certified as matched quantity"
    assert out.get("tracker_sha256") is None,"failed pair acquired a successful fingerprint"
    assert "PRIVATE" not in json.dumps(out),"raw journal detail leaked"
    assert frozen(folder)==before,"display recovered or changed a prepared ledger"


@pytest.mark.parametrize("events",[b'{PRIVATE-broken',b'{"event_id":"x","event_type":"history_supersession","created_at":"2026-11-06T00:00:00Z","payload":{}}\n'])
def test_ac_corrupt_or_orphan_events_never_matches(tmp_path,events):
    folder,_=seed(tmp_path,events=events);before=frozen(folder)
    out=position_comparison(tmp_path,[],EV,NOW)
    assert out["status"]=="unknown" and out["mismatch_count"] is None,"state/events mismatch was shown as parity"
    assert frozen(folder)==before,"reader changed invalid evidence"


def test_ac_synthetic_valid_migrated_pair_preserves_revision(tmp_path):
    """A valid correction is readable, not silently refused or recertified."""
    closed=dict(trade_id="synthetic-lot",symbol="SYN",status="closed",broker_order_id="synthetic-buy",exit_broker_order_id="synthetic-sell",qty=1,entry_price=10.,exit_price=11.,pnl=1.,return_pct=.1,entry_time="2026-11-02T15:00:00Z",exit_time="2026-11-03T15:00:00Z",holding_days=1)
    folder,inputs=seed(tmp_path,rows=[closed])
    corrected={**closed,"exit_price":12.,"pnl":2.,"return_pct":.2}
    plan=prepare_migration(inputs,row_changes=[dict(row_index=0,before=closed,after=corrected)],corporate_plans=[],evidence_sha256="1"*64,recorded_at="2026-11-06T07:00:00Z",reason="synthetic reader regression only")
    (folder/"pnl_state.json").write_text(json.dumps(plan["after_state"]))
    (folder/"trade_events.jsonl").write_bytes(base64.b64decode(plan["after_events_b64"]))
    before=frozen(folder);out=position_comparison(tmp_path,[],EV,NOW)
    assert out["status"]=="matched_quantity_only" and out["mismatch_count"]==0,"valid migrated empty open population did not remain readable"
    assert out["tracker_ledger_revision"]==plan["migration_id"],"reader lost actual corrected revision"
    assert out["tracker_sha256"]==digest(before["pnl_state.json"][0]) and out["tracker_events_sha256"]==digest(before["trade_events.jsonl"][0]),"fingerprints do not identify same consumed pair"
    assert frozen(folder)==before,"reader rewrote migrated ledger"
    assert out["tracker_last_updated"]=="2026-11-06T07:00:00Z" and out["broker_as_of"]==EV["as_of"],"acquisition and ledger clocks merged"


def test_ac_real_process_lock_is_nonblocking_and_resumes(tmp_path):
    folder,_=seed(tmp_path);before=frozen(folder)
    code="import fcntl,sys; f=open(sys.argv[1],'a+b'); fcntl.flock(f,fcntl.LOCK_EX); print('LOCKED',flush=True); sys.stdin.readline()"
    child=subprocess.Popen([sys.executable,"-I","-B","-c",code,str(folder/".ledger.lock")],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        assert child.stdout.readline().strip()=="LOCKED","competing writer did not hold lock"
        start=time.monotonic();out=position_comparison(tmp_path,[],EV,NOW);elapsed=time.monotonic()-start
        assert out["status"]=="unknown" and out["mismatch_count"] is None and elapsed<1.,"display blocked or ignored an active writer"
    finally:
        child.communicate("release\n",timeout=5)
    assert child.returncode==0,"lock holder did not finish cleanly"
    assert position_comparison(tmp_path,[],EV,NOW)["mismatch_count"]==0,"reader did not resume after completed writer"
    assert frozen(folder)==before,"content changed during lock-only test"


def test_ac_failure_propagates_through_json_and_real_renderer(tmp_path):
    folder,_=seed(tmp_path);(folder/".ledger_transaction.json").write_bytes(b'{broken')
    wire=json.loads(json.dumps(get_followthrough(tmp_path,positions=[],positions_evidence=EV,now=NOW),allow_nan=False))
    assert wire["position_comparison"]["mismatch_count"] is None,"JSON payload converted unknown to zero"
    html=js("renderFollowthroughEvidence",{"data":{"operational_evidence":{"followthrough":wire}}})
    assert "数量差の銘柄数: 未確認" in html,"real renderer presents failed pair as healthy zero"


@pytest.mark.parametrize("rows,positions,count",[([],[],0),([dict(status="open",symbol="SYN",qty="3.7")],[dict(symbol="SYN",qty="3.7")],0),([dict(status="open",symbol="SYN",qty="3.7")],[dict(symbol="SYN",qty="1.2")],1)])
def test_ac_normal_fractional_and_mismatch_unchanged(tmp_path,rows,positions,count):
    folder,_=seed(tmp_path,rows=rows);before=frozen(folder)
    out=position_comparison(tmp_path,positions,EV,NOW)
    assert out["mismatch_count"]==count,"normal signed quantity comparison changed"
    assert out["tracker_events_sha256"]==hashlib.sha256(b"").hexdigest(),"empty event file lost its actual fingerprint"
    assert frozen(folder)==before,"normal reader changed financial inputs"
