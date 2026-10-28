"""Acceptance CMP-C01: strict pre-send receipt, unknown lookup and cooperating restart.

Regression incident: 2026-10-28,8909e79, initial POST repeated3 times after ACK loss.
Only external HTTP/filesystem boundaries are substituted; guard/event-store real.
"""
from pathlib import Path
import fcntl,json,os,subprocess,sys
import httpx
import pytest
from stock_swing.execution.submission_guard import SubmissionGuard,SubmissionUncertain,SubmissionHeld
from stock_swing.sources.broker_client import BrokerClient
from stock_swing.sources.retry import RetryConfig


ORDER=dict(symbol="MSFT",side="buy",order_type="market",qty=10,time_in_force="day",limit_price=None)


def setup_guard(monkeypatch,tmp_path,mode="normal",changes=None):
    calls=[];accepted={}
    def transport(request):
        calls.append(request.method)
        if request.method=="POST":
            body=json.loads(request.content)
            response=dict(body,id="fixture-id",status="new",filled_qty="0")
            accepted[body["client_order_id"]]=response
            if mode!="normal":raise httpx.ReadTimeout("fixture acceptance followed by response loss",request=request)
            return httpx.Response(200,json=response)
        key=request.url.params.get("client_order_id")
        if mode=="not_found":return httpx.Response(404,json={})
        row=accepted.get(key)
        if row and changes:row=dict(row,**changes)
        return httpx.Response(200,json=row) if row else httpx.Response(404,json={})
    original=httpx.Client
    monkeypatch.setattr(httpx,"Client",lambda **kw:original(transport=httpx.MockTransport(transport),**kw))
    broker=BrokerClient(api_key="fixture",api_secret="fixture",paper_mode=True,base_url="https://paper-fixture.invalid",retry_config=RetryConfig(initial_delay=.001))
    return SubmissionGuard(broker,tmp_path,"account-fixture"),calls,accepted


def test_ac_normal_prepare_before_side_effect_and_restart_noop(monkeypatch,tmp_path):
    guard,calls,accepted=setup_guard(monkeypatch,tmp_path)
    result=guard.submit_intent("decision",**ORDER)
    rows=[json.loads(line) for line in guard.store.path.read_text().splitlines()]
    assert [r["event_type"] for r in rows]==["submission_guard_initialized","submission_intent_prepared","submission_intent_outcome"], "fsync receipt before outcome"
    assert result["client_order_id"].startswith("ss-") and len(result["client_order_id"])==43, result
    restarted=SubmissionGuard(guard.broker,tmp_path,"account-fixture")
    with pytest.raises(SubmissionHeld):restarted.submit_intent("decision",**ORDER)
    assert calls==["POST"], "recorded intent must never be posted twice"


def test_ac_lost_ack_found_by_identity_no_retry(monkeypatch,tmp_path):
    guard,calls,accepted=setup_guard(monkeypatch,tmp_path,"lost_found")
    result=guard.submit_intent("decision",**ORDER)
    assert result["id"]=="fixture-id" and calls==["POST","GET"], "lookup, not retry"
    with pytest.raises(SubmissionHeld):guard.submit_intent("decision",**ORDER)
    assert calls.count("POST")==1, calls


def test_ac_not_found_never_authorizes_retry_and_other_sell_remains(monkeypatch,tmp_path):
    guard,calls,accepted=setup_guard(monkeypatch,tmp_path,"not_found")
    with pytest.raises(SubmissionUncertain):guard.submit_intent("decision",**ORDER)
    with pytest.raises(SubmissionUncertain):guard.submit_intent("another",**dict(ORDER,symbol="CRM"))
    with pytest.raises(SubmissionUncertain):guard.submit_intent("exit_same",**dict(ORDER,side="sell"))
    assert calls.count("POST")==1, "no retry after404/newBUY/reverse SELL"
    with pytest.raises(SubmissionUncertain):guard.submit_intent("exit_other",**dict(ORDER,symbol="CRM",side="sell"))
    assert calls.count("POST")==2, "unrelated eligible SELL reaches external boundary, remains unknown here"


@pytest.mark.parametrize("change", [dict(client_order_id="other"),dict(symbol="CRM"),dict(side="sell"),dict(qty="11"),dict(qty="nan"),dict(filled_qty="inf"),dict(filled_qty="11"),dict(status="mystery"),dict(type="limit"),dict(id=None),dict(time_in_force="gtc")])
def test_ac_mismatched_lookup_is_not_acceptance(monkeypatch,tmp_path,change):
    guard,calls,accepted=setup_guard(monkeypatch,tmp_path,"lost_found",change)
    with pytest.raises(SubmissionUncertain):guard.submit_intent("decision",**ORDER)
    assert calls==["POST","GET"], "mismatch must not submit again"


@pytest.mark.parametrize("damage", ["missing","partial","json","unknown","reverse","marker"])
def test_ac_corrupt_or_missing_history_never_resets_empty(monkeypatch,tmp_path,damage):
    guard,calls,accepted=setup_guard(monkeypatch,tmp_path)
    guard.submit_intent("decision",**ORDER)
    path=guard.store.path
    if damage=="missing":path.unlink()
    elif damage=="partial":path.write_bytes(path.read_bytes()+b'{')
    elif damage=="json":path.write_text('{\n')
    elif damage=="marker":guard.marker.write_text("wrong\n")
    else:
        row=json.loads(path.read_text().splitlines()[-1])
        row["event_type"]="unknown" if damage=="unknown" else "submission_intent_prepared"
        with path.open('a') as f:f.write(json.dumps(row)+'\n')
    with pytest.raises(SubmissionUncertain):guard.submit_intent("new",**ORDER)
    assert calls==["POST"], "corruption must not become new empty history"


def test_ac_cooperating_lock_refuses_send(monkeypatch,tmp_path):
    guard,calls,accepted=setup_guard(monkeypatch,tmp_path)
    with guard.lock_path.open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(SubmissionHeld):guard.submit_intent("decision",**ORDER)
    assert calls==[], "busy lock cannot fall through to broker"


def test_ac_payload_change_and_namespace_are_not_reinterpreted(monkeypatch,tmp_path):
    guard,calls,accepted=setup_guard(monkeypatch,tmp_path)
    guard.submit_intent("decision",**ORDER)
    with pytest.raises(SubmissionUncertain):guard.submit_intent("decision",**dict(ORDER,qty=11))
    assert calls==["POST"], "changed qty is not same authorized intent"
    other=SubmissionGuard(guard.broker,tmp_path,"other-account")
    assert other._client_id("decision")!=guard._client_id("decision"), "account-bound identity"


def test_ac_prior_unknown_lookup_requires_refreshed_snapshot(monkeypatch,tmp_path):
    guard,calls,accepted=setup_guard(monkeypatch,tmp_path,"lost_found")
    key=guard._client_id("prior")
    with guard.lock_path.open('a') as lock:
        guard._load();guard._append("submission_intent_prepared",client_order_id=key,decision_id="prior",order=ORDER)
    accepted[key]=dict(id="fixture-id",client_order_id=key,symbol="MSFT",side="buy",type="market",qty="10",filled_qty="0",time_in_force="day",status="partially_filled")
    with pytest.raises(SubmissionUncertain):guard.submit_intent("new",**dict(ORDER,symbol="CRM"))
    assert calls==["GET"], "old unresolved recovery is not a fresh capacity snapshot"


def test_ac_real_process_death_after_acceptance_preserves_prepared(monkeypatch,tmp_path):
    # Kill only at external HTTP boundary after receipt; no internal guard mock.
    guard,calls,accepted=setup_guard(monkeypatch,tmp_path)
    script='''import httpx,os,json
from pathlib import Path
from stock_swing.sources.broker_client import BrokerClient
from stock_swing.execution.submission_guard import SubmissionGuard
def transport(request):
    if request.method=='POST':
        Path('accepted.json').write_bytes(request.content)
        os._exit(73)
    return httpx.Response(404,json={})
original=httpx.Client
httpx.Client=lambda **kw:original(transport=httpx.MockTransport(transport),**kw)
broker=BrokerClient(api_key='fixture',api_secret='fixture',paper_mode=True,base_url='https://paper-fixture.invalid')
SubmissionGuard(broker,Path.cwd(),'account-fixture').submit_intent('decision',symbol='MSFT',side='buy',order_type='market',qty=10,time_in_force='day',limit_price=None)
'''
    run=subprocess.run([sys.executable,'-B','-c',script],cwd=tmp_path,capture_output=True,text=True)
    assert run.returncode==73 and (tmp_path/'accepted.json').exists(), run.stderr
    with pytest.raises(SubmissionHeld):guard.submit_intent("decision",**ORDER)
    assert calls==["GET"], "restart may query but not resend"


def test_ac_missing_marker_and_failed_fsync_never_send(monkeypatch,tmp_path):
    guard,calls,_=setup_guard(monkeypatch,tmp_path)
    real_fsync=os.fsync
    def broken(fd):raise OSError("fixture disk fsync failure")
    monkeypatch.setattr(os,"fsync",broken)
    with pytest.raises(SubmissionUncertain):guard.submit_intent("decision",**ORDER)
    assert calls==[], "pre-send receipt must be durable before HTTP"
    monkeypatch.setattr(os,"fsync",real_fsync)
    with pytest.raises(SubmissionUncertain):guard.submit_intent("decision",**ORDER)
    assert calls==[], "partially initialized journal is not empty history"


def test_ac_recovery_invalidates_all_buys_in_same_snapshot(monkeypatch,tmp_path):
    original=httpx.Client
    guard,calls,accepted=setup_guard(monkeypatch,tmp_path,"not_found")
    with pytest.raises(SubmissionUncertain):guard.submit_intent("first",**ORDER)
    def recovered(request):
        calls.append(request.method)
        key=request.url.params.get("client_order_id")
        return httpx.Response(200,json=accepted[key])
    monkeypatch.setattr(httpx,"Client",lambda **kw:original(transport=httpx.MockTransport(recovered),**kw))
    for ident in ['second','third']:
        with pytest.raises(SubmissionUncertain):guard.submit_intent(ident,**dict(ORDER,symbol="CRM"))
    assert calls.count("POST")==1 and guard.snapshot_invalidated,"resolved receipt must not authorize later BUY with same snapshot"


def test_ac_true_child_process_lock_blocks_side_effect(monkeypatch,tmp_path):
    guard,calls,_=setup_guard(monkeypatch,tmp_path)
    code='import fcntl,sys; f=open(sys.argv[1],"a"); fcntl.flock(f,fcntl.LOCK_EX); print("locked",flush=True); sys.stdin.readline()'
    child=subprocess.Popen([sys.executable,'-B','-c',code,str(guard.lock_path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    try:
        assert child.stdout.readline().strip()=='locked', 'child must hold actual account lock'
        with pytest.raises(SubmissionHeld):guard.submit_intent('decision',**ORDER)
        assert calls==[], 'concurrent process cannot reach HTTP'
    finally:
        child.communicate('\n',timeout=5)


def test_ac_prepare_fsync_failure_cannot_submit(monkeypatch,tmp_path):
    guard,calls,_=setup_guard(monkeypatch,tmp_path);original=os.fsync;count=[]
    def fsync(fd):
        count.append(fd)
        if len(count)==3:raise OSError('fixture prepare fsync failure')
        original(fd)
    monkeypatch.setattr(os,'fsync',fsync)
    with pytest.raises(SubmissionUncertain):guard.submit_intent('decision',**ORDER)
    assert calls==[] and len(count)==3,'prepare failure precedes external send'
