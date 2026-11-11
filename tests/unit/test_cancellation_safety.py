"""Regression 2026-10-28/8909e79: cancel ACK is not terminal evidence."""
import json
from pathlib import Path
import httpx
import pytest
from stock_swing.sources.broker_client import BrokerClient


def order(status='new', filled='0', **overrides):
    return dict(id='fixture-order', symbol='AMD', side='sell', type='market',
                time_in_force='day', qty='5', filled_qty=filled, status=status,
                submitted_at='2026-06-07T01:34:06+00:00', **overrides)


_transport = None


@pytest.fixture(autouse=True)
def client_boundary(monkeypatch):
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kw: original(transport=_transport, **kw))


def setup(root, after='pending_cancel', filled='0', delete_error=False, mismatch=False):
    (root/'config/runtime').mkdir(parents=True)
    (root/'config/runtime/current_mode.yaml').write_text('mode: paper\n')
    calls=[]
    def transport(request):
        calls.append(request.method+' '+request.url.path)
        if request.url.path.endswith('/account'):
            return httpx.Response(200,json=dict(id='account-fixture',status='ACTIVE'))
        if request.method=='DELETE':
            if delete_error:raise httpx.ReadTimeout('fixture accepted ACK lost',request=request)
            return httpx.Response(204)
        if request.url.path.endswith('/fixture-order'):
            post=any(c.startswith('DELETE') for c in calls)
            if post and after=='404':return httpx.Response(404,json={})
            body=order(after if post else 'new',filled if post else '0')
            if post and mismatch:body['symbol']='MSFT'
            return httpx.Response(200,json=body)
        raise AssertionError(request.url.path)
    broker=BrokerClient(api_key='fixture',api_secret='fixture',paper_mode=True)
    global _transport
    _transport=httpx.MockTransport(transport)
    return broker,calls


def run_cancel(broker, root):
    from stock_swing.execution.cancellation_guard import cancel_order_safely
    return cancel_order_safely(broker,root,order())


@pytest.mark.parametrize('after,state', [('pending_cancel','requested'),('new','requested'),
    ('partially_filled','requested'),('404','unknown'),('canceled','terminal'),
    ('expired','terminal'),('rejected','terminal'),('filled','terminal')])
def test_ac_cancel_states_are_observed_not_inferred(tmp_path, after, state):
    filled='5' if after=='filled' else '2' if after=='partially_filled' else '0'
    broker,calls=setup(tmp_path,after,filled)
    result=run_cancel(broker,tmp_path)
    assert result['state']==state,result
    assert sum(c.startswith('DELETE') for c in calls)==1,calls
    assert result['cancelled'] is (after=='canceled'),result


@pytest.mark.parametrize('after', ['pending_cancel','404','canceled','filled'])
def test_ac_retry_does_not_repeat_delete(tmp_path,after):
    broker,calls=setup(tmp_path,after,'5' if after=='filled' else '0',delete_error=True)
    first=run_cancel(broker,tmp_path);second=run_cancel(broker,tmp_path)
    assert sum(c.startswith('DELETE') for c in calls)==1,calls
    assert first['state'] in {'unknown','terminal'},first
    assert second['state'] in {'unknown','terminal'},second


def test_ac_mismatched_lookup_remains_unknown(tmp_path):
    broker,calls=setup(tmp_path,mismatch=True)
    result=run_cancel(broker,tmp_path)
    assert result['state']=='unknown',result
    assert result['cancelled'] is False,result


def test_ac_corrupt_journal_refuses_mutation(tmp_path):
    broker,calls=setup(tmp_path)
    run_cancel(broker,tmp_path)
    journal=next((tmp_path/'data/tracking/cancel_intents').glob('*.jsonl'))
    journal.write_text('broken\n')
    result=run_cancel(broker,tmp_path)
    assert result['state']=='held',result
    assert sum(c.startswith('DELETE') for c in calls)==1,calls


def test_ac_pending_sell_cancel_retains_exit_reason(tmp_path):
    from stock_swing.cli import reconcile_orders
    from stock_swing.tracking.exit_reason_store import write_exit_reason,read_exit_reason
    broker,calls=setup(tmp_path)
    global _transport
    base_transport=_transport
    def transport(request):
        if request.url.path=='/v2/orders':return httpx.Response(200,json=[order()])
        return base_transport.handle_request(request)
    _transport=httpx.MockTransport(transport)
    write_exit_reason(tmp_path,'fixture-order','AMD','fixture','breakeven_stop',{'return_pct':-.07})
    result=reconcile_orders.cancel_stale_sell_orders(broker,tmp_path)
    assert read_exit_reason(tmp_path,'fixture-order') is not None,'ACK must not erase reason'
    assert not any(x.get('cancelled') for x in result),result


def test_ac_prior_cancellation_holds_new_buy(tmp_path):
    from stock_swing.execution.submission_guard import SubmissionGuard,SubmissionUncertain
    broker,calls=setup(tmp_path)
    run_cancel(broker,tmp_path)
    guard=SubmissionGuard(broker,tmp_path,'account-fixture')
    with pytest.raises(SubmissionUncertain):
        guard.submit_intent('new-buy',symbol='NVDA',side='buy',order_type='market',qty=1,time_in_force='day',limit_price=None)
    assert not any(c.startswith('POST') for c in calls),calls


@pytest.mark.parametrize('field,value',[('qty','NaN'),('qty','0'),('qty',True),
    ('filled_qty','6'),('filled_qty','-1'),('status','pending_replace'),
    ('id',''),('type',None),('order_class','bracket')])
def test_ac_unqualified_order_never_deletes(tmp_path,field,value):
    from stock_swing.execution.cancellation_guard import cancel_order_safely
    broker,calls=setup(tmp_path);expected=order();expected[field]=value
    result=cancel_order_safely(broker,tmp_path,expected)
    assert result['state']=='held',result
    assert not any(c.startswith('DELETE') for c in calls),calls


def test_ac_missing_initialized_history_never_deletes_again(tmp_path):
    broker,calls=setup(tmp_path);run_cancel(broker,tmp_path)
    next((tmp_path/'data/tracking/cancel_intents').glob('*.jsonl')).unlink()
    result=run_cancel(broker,tmp_path)
    assert result['state']=='held',result
    assert sum(c.startswith('DELETE') for c in calls)==1,calls


def test_ac_write_blocked_before_prepare_means_no_delete(tmp_path):
    broker,calls=setup(tmp_path)
    folder=tmp_path/'data/tracking';folder.mkdir(parents=True)
    (folder/'cancel_intents').write_text('fixture file instead of directory')
    result=run_cancel(broker,tmp_path)
    assert result['state']=='held',result
    assert not any(c.startswith('DELETE') for c in calls),calls


def test_ac_other_process_submission_lock_blocks_cancel(tmp_path):
    import subprocess,sys,os
    from stock_swing.execution.submission_guard import SubmissionGuard
    broker,calls=setup(tmp_path)
    guard=SubmissionGuard(broker,tmp_path,'account-fixture')
    code='import fcntl,sys;f=open(sys.argv[1],"a");fcntl.flock(f,fcntl.LOCK_EX);print("ready",flush=True);sys.stdin.read()'
    child=subprocess.Popen([sys.executable,'-B','-c',code,str(guard.lock_path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    try:
        assert child.stdout.readline().strip()=='ready','child did not acquire real OS lock'
        result=run_cancel(broker,tmp_path)
        assert result['state']=='held' and result['reason']=='submission_guard_busy',result
        assert not any(c.startswith('DELETE') for c in calls),calls
    finally:
        child.communicate('',timeout=5)


@pytest.mark.parametrize('filled,keep',[('0',False),('2',True)])
def test_ac_terminal_cancel_preserves_any_fill_attribution(tmp_path,filled,keep):
    from stock_swing.cli.reconcile_orders import _cancel_checked
    from stock_swing.tracking.exit_reason_store import write_exit_reason,read_exit_reason
    broker,calls=setup(tmp_path,'canceled',filled)
    write_exit_reason(tmp_path,'fixture-order','AMD','fixture','stop_loss')
    result=_cancel_checked(broker,tmp_path,order(),'fixture')
    assert result['cancelled'] is True,result
    assert (read_exit_reason(tmp_path,'fixture-order') is not None) is keep,result


@pytest.mark.parametrize('entry,body',[('buy',[order()]*200),('sell',[order()]*500),
    ('buy',None),('sell',None),('buy',{}),('sell',{})])
def test_ac_unavailable_or_capped_list_is_not_empty_success(tmp_path,entry,body):
    from stock_swing.cli import reconcile_orders
    broker,calls=setup(tmp_path)
    global _transport
    base=_transport
    def transport(request):
        if request.url.path=='/v2/orders':
            return httpx.Response(503 if body is None else 200,json=body)
        return base.handle_request(request)
    _transport=httpx.MockTransport(transport)
    if entry=='buy':
        old=reconcile_orders.project_root;reconcile_orders.project_root=tmp_path
        try:result=reconcile_orders.cancel_stale_buy_orders(broker)
        finally:reconcile_orders.project_root=old
    else:result=reconcile_orders.cancel_stale_sell_orders(broker,tmp_path)
    assert result and result[0]['state']=='held',result
    assert not any(c.startswith('DELETE') for c in calls),calls


def test_ac_terminal_reversal_invalidates_persisted_reservation(tmp_path):
    from stock_swing.execution.submission_guard import SubmissionGuard
    from stock_swing.execution.cancellation_guard import pending_cancellations
    broker,calls=setup(tmp_path,'canceled')
    assert run_cancel(broker,tmp_path)['state']=='terminal'
    global _transport
    base=_transport
    def transport(request):
        if request.url.path.endswith('/fixture-order') and request.method=='GET':return httpx.Response(200,json=order('new'))
        return base.handle_request(request)
    _transport=httpx.MockTransport(transport)
    result=run_cancel(broker,tmp_path)
    assert result['state']=='unknown',result
    pending=pending_cancellations(SubmissionGuard(broker,tmp_path,'account-fixture'))
    assert len(pending)==1 and pending[0]['state']=='unknown',pending
    assert sum(c.startswith('DELETE') for c in calls)==1,calls
