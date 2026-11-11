"""R22 / baseline 2a8ca59: historical consumption gaps need explicit review.

Acceptance: append an evidenced bridge, not a fake historical execution; retain
all state/events/original fill bytes and refuse conflicting or stale evidence.
"""
from copy import deepcopy
from datetime import datetime,timezone
import json

import pytest

from tests.unit.test_r22_history_migration import fixture_plan
from stock_swing.tracking.history_migration import apply_migration
from stock_swing.tracking.pnl_tracker import PnLTracker
from stock_swing.tracking.fill_ledger import FillLedger
from stock_swing.tracking.settle_sell import settle_sell
from stock_swing.tracking.ledger_transaction import FILES,LedgerConflict,ledger_transaction
from stock_swing.tracking.consumption_bridge import prepare_bridge,apply_bridge


def snapshot(root):
    return {n:(root/'data/tracking'/n).read_bytes() for n in FILES}


def setup_bridge(root, consumed=None):
    _,_,migration=fixture_plan(root);apply_migration(root,migration)
    tracker=PnLTracker(root)
    tracker.record_submission('BRIDGE','fixture','buy',2,100,'bridge-buy','bridge-decision',asset_class='stock')
    tracker.record_exit('BRIDGE',105,2,'bridge-sell','fixture','fixture')
    order=dict(id='bridge-sell',symbol='BRIDGE',side='sell',filled_qty='2',filled_avg_price='105',
               filled_at=datetime.now(timezone.utc).isoformat(),status='filled')
    if consumed is not None:
        ledger=FillLedger(root);key=ledger.ingest(dict(order,qty='2'))
        if consumed:ledger.consume(key,'original-consumer',consumed)
    data=snapshot(root)
    plan=prepare_bridge(data,[order],evidence_sha256='a'*64,recorded_at=datetime.now(timezone.utc).isoformat())
    return data,order,plan


@pytest.mark.parametrize('consumed',[None,0,1,2])
def test_ac_append_only_bridge_preserves_economics_and_original_consumption(tmp_path,consumed):
    before,order,plan=setup_bridge(tmp_path,consumed)
    result=apply_bridge(tmp_path,plan)
    assert result['bridged_orders']==(0 if consumed==2 else 1)
    after=snapshot(tmp_path)
    for name in ['pnl_state.json','trade_events.jsonl']:assert after[name]==before[name]
    assert after['fill_ledger.jsonl'].startswith(before['fill_ledger.jsonl'])
    fill=FillLedger(tmp_path).get(order['id'])
    assert fill['consumed_qty']==2
    if consumed!=2:
        event=fill['consumption_events'][-1]
        assert event['kind']=='historical_accounting_bridge'
        assert event['not_broker_execution'] is True
        assert event['qty']==2-(consumed or 0)
        assert event['bridge_id']==plan['bridge_id']
    if consumed==1:assert fill['consumption_events'][0]['trade_id']=='original-consumer'
    assert settle_sell(tmp_path,order) is None
    assert snapshot(tmp_path)==after
    assert apply_bridge(tmp_path,plan)['status']=='already_applied'
    assert snapshot(tmp_path)==after


def test_ac_retry_after_legitimate_new_writes_preserves_new_records(tmp_path):
    _,_,plan=setup_bridge(tmp_path)
    apply_bridge(tmp_path,plan)
    tracker=PnLTracker(tmp_path);tracker.record_submission('NEW','fixture','buy',1,100,'new-buy','new-decision',asset_class='stock')
    settle_sell(tmp_path,dict(id='new-sell',symbol='NEW',side='sell',filled_qty='1',filled_avg_price='110',filled_at=datetime.now(timezone.utc).isoformat()))
    before=snapshot(tmp_path)
    assert apply_bridge(tmp_path,plan)['status']=='already_applied'
    assert snapshot(tmp_path)==before


def test_ac_real_increment_after_bridge_of_same_order_is_consumed_once(tmp_path):
    _,order,plan=setup_bridge(tmp_path)
    apply_bridge(tmp_path,plan)
    tracker=PnLTracker(tmp_path)
    tracker.record_submission('BRIDGE','fixture','buy',1,100,'bridge-buy-2','bridge-decision-2',asset_class='stock')
    order.update(filled_qty='3',filled_avg_price=str(320/3))
    result=settle_sell(tmp_path,order)
    assert result is not None
    fill=FillLedger(tmp_path).get(order['id'])
    assert fill['consumed_qty']==3 and fill['qty']==3
    state=json.loads(snapshot(tmp_path)['pnl_state.json'])
    assert sum(r['qty'] for r in state['trades'] if r.get('exit_broker_order_id')==order['id'])==3
    assert sum(r['pnl'] for r in state['trades'] if r.get('exit_broker_order_id')==order['id'])==pytest.approx(20)
    before=snapshot(tmp_path)
    assert settle_sell(tmp_path,order) is None
    assert apply_bridge(tmp_path,plan)['status']=='already_applied'
    assert snapshot(tmp_path)==before


@pytest.mark.parametrize('damage',['missing_file','json','snapshot','duplicate_order','side','symbol','qty','price','nonfinite','quarantine','event_quantity','watermark_ahead'])
def test_ac_invalid_review_evidence_refused_without_writes(tmp_path,damage):
    data,order,_=setup_bridge(tmp_path,1)
    orders=[order]
    if damage=='missing_file':data.pop('trade_events.jsonl')
    if damage=='json':data['fill_ledger.jsonl']=b'{broken\n'
    if damage=='snapshot':data['fill_consumed_ledger.json']=b'{"fills":[]}'
    if damage=='duplicate_order':orders.append(dict(order))
    if damage=='side':order['side']='buy'
    if damage=='symbol':order['symbol']='WRONG'
    if damage=='qty':order['filled_qty']='3'
    if damage=='price':order['filled_avg_price']='106'
    if damage=='nonfinite':order['filled_qty']=True
    if damage=='quarantine':
        state=json.loads(data['pnl_state.json']);row=deepcopy(next(r for r in state['trades'] if r['symbol']=='BRIDGE'));row['status']='quarantined';state['quarantined_trades'].append(row);data['pnl_state.json']=json.dumps(state).encode()
    if damage=='event_quantity':
        events=[json.loads(line) for line in data['trade_events.jsonl'].splitlines()]
        next(e for e in events if e.get('broker_order_id')=='bridge-sell')['payload']['exit_qty']=3
        data['trade_events.jsonl']=b''.join(json.dumps(e).encode()+b'\n' for e in events)
    if damage=='watermark_ahead':
        rows=[json.loads(line) for line in data['fill_ledger.jsonl'].splitlines()];rows[-1]['consumed_qty']=3
        data['fill_ledger.jsonl']=b''.join(json.dumps(r).encode()+b'\n' for r in rows)
    before=snapshot(tmp_path)
    with pytest.raises((LedgerConflict,ValueError)):prepare_bridge(data,orders,evidence_sha256='a'*64,recorded_at=datetime.now(timezone.utc).isoformat())
    assert snapshot(tmp_path)==before


@pytest.mark.parametrize('damage',['plan','stale','partial_marker'])
def test_ac_changed_plan_or_files_refused(tmp_path,damage):
    _,_,plan=setup_bridge(tmp_path)
    if damage=='plan':plan['intent']['entries'][0]['target_qty']=999
    if damage=='stale':
        tracker=PnLTracker(tmp_path);tracker.record_submission('OTHER','fixture','buy',1,50,'other-buy','other-decision',asset_class='stock')
    if damage=='partial_marker':
        apply_bridge(tmp_path,plan)
        path=tmp_path/'data/tracking/fill_ledger.jsonl';rows=path.read_bytes().splitlines(keepends=True);rows[-1]=rows[-1].replace(b'"not_broker_execution": true',b'"not_broker_execution": false');path.write_bytes(b''.join(rows))
    before=snapshot(tmp_path)
    with pytest.raises((LedgerConflict,ValueError)):apply_bridge(tmp_path,plan)
    assert snapshot(tmp_path)==before


def test_ac_prepared_interruption_recovers_once_then_retry_noop(tmp_path,monkeypatch):
    _,_,plan=setup_bridge(tmp_path)
    import stock_swing.tracking.ledger_transaction as lt
    recover=lt._recover;calls=[]
    def stop(folder):
        calls.append(1)
        if len(calls)==2:raise OSError('injected death after durable prepare')
        return recover(folder)
    monkeypatch.setattr(lt,'_recover',stop)
    with pytest.raises(OSError):apply_bridge(tmp_path,plan)
    monkeypatch.setattr(lt,'_recover',recover)
    with ledger_transaction(tmp_path):pass
    after=snapshot(tmp_path)
    assert apply_bridge(tmp_path,plan)['status']=='already_applied'
    assert snapshot(tmp_path)==after


def test_ac_retry_cannot_launder_damaged_consumption_snapshot(tmp_path):
    _,_,plan=setup_bridge(tmp_path);apply_bridge(tmp_path,plan)
    path=tmp_path/'data/tracking/fill_consumed_ledger.json'
    path.write_text('{"fills":[]}')
    before=snapshot(tmp_path)
    with pytest.raises(LedgerConflict):apply_bridge(tmp_path,plan)
    assert snapshot(tmp_path)==before


@pytest.mark.parametrize('damage',['missing','corrupt'])
def test_ac_apply_missing_or_corrupt_dependency_refuses_without_writes(tmp_path,damage):
    _,_,plan=setup_bridge(tmp_path)
    folder=tmp_path/'data/tracking'
    if damage=='missing':(folder/'fill_consumed_ledger.json').unlink()
    else:(folder/'pnl_state.json').write_bytes(b'{broken')
    def remaining():
        return {n:(folder/n).read_bytes() if (folder/n).exists() else None for n in FILES}
    before=remaining()
    with pytest.raises(LedgerConflict):apply_bridge(tmp_path,plan)
    assert remaining()==before
