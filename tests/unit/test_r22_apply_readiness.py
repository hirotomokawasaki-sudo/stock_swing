"""R22 2026-10-21 readiness: legacy DDOG rounding blocks 0b5712f replay.

Acceptance: prove a precision-only proposal without weakening the runtime
contract or changing economic PnL, identity, chronology, or quarantine.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[2]
FOLDER=ROOT/'docs/r22_apply_readiness_20261021'
spec=importlib.util.spec_from_file_location('r22_precision_preview',FOLDER/'precision_preview.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture():
    return json.loads((FOLDER/'review_packet/evidence/ddog_precision.json').read_text())


def test_ac_ddog_original_rejected_preview_is_nonmutating_and_pnl_preserved():
    from stock_swing.tracking.execution_cost import incremental_sell_fill,ExecutionCostError
    data=fixture();original=deepcopy(data);sell=data['orders'][1]
    with pytest.raises(ExecutionCostError,match='notional revision'):
        incremental_sell_fill(sell,data['state']['trades'])
    after,changes,rejected=module.preview(**data)
    assert data==original, 'caller evidence must not be mutated'
    assert len(changes)==1 and not rejected, 'unique whole-lot source proof should qualify'
    assert after['trades'][0]['pnl']==3619.69, 'cash PnL already correct; do not add 12 cents'
    assert changes[0]['raw_sell_proceeds']=='42733.52', 'use all original executions'
    assert incremental_sell_fill(sell,after['trades']).qty==0, 'same runtime rule now verifies the recovered precision'
    for key,value in data['state']['trades'][0].items():
        if key not in {'entry_price','exit_price'}:
            assert after['trades'][0][key]==value, f'non-price field changed: {key}'
    repeated,new_changes,_=module.preview(after,data['orders'],data['activities'])
    assert repeated==after and not new_changes, 'preview must be idempotent at persisted float precision'


@pytest.mark.parametrize('case',['pnl','order_qty','fill_qty','order_price','partial_lot','quarantine',
                               'split','unknown_split_date','naive','future_buy','outside_rounding','nan','missing_order'])
def test_ac_unproven_evidence_never_yields_precision_proposal(case):
    data=fixture();row=data['state']['trades'][0]
    if case=='pnl':row['pnl']+=1
    if case=='order_qty':data['orders'][0]['filled_qty']='171'
    if case=='fill_qty':data['activities'][0]['qty']='0.5'
    if case=='order_price':data['orders'][0]['filled_avg_price']='200'
    if case=='partial_lot':data['state']['trades'].append(dict(row,trade_id='second',exit_broker_order_id='other'))
    if case=='quarantine':data['state']['quarantined_trades'].append(dict(row,status='quarantined'))
    if case in {'split','unknown_split_date'}:data['activities'].append(dict(symbol='DDOG',activity_type='SPLIT',date=row['entry_time'][:10] if case=='split' else 'unknown'))
    if case=='naive':row['entry_time']='2026-06-29T13:00:00'
    if case=='future_buy':data['orders'][0]['filled_at']='2026-07-10T00:00:00Z'
    if case=='outside_rounding':row['entry_price']+=.02;row['exit_price']+=.02
    if case=='nan':row['qty']=float('nan')
    if case=='missing_order':data['orders']=data['orders'][1:]
    _,changes,rejected=module.preview(**data)
    assert not changes and rejected, f'ambiguous {case} must not be repaired by this precision-only preview'


@pytest.mark.parametrize('collection',['orders','activities'])
def test_ac_duplicate_original_identity_rejected(collection):
    data=fixture();data[collection].append(deepcopy(data[collection][0]))
    with pytest.raises(ValueError,match='duplicate'):
        module.preview(**data)


def test_ac_actual_cron_entrypoint_blocks_original_and_accepts_preview(tmp_path,monkeypatch):
    from stock_swing.cli import reconcile_orders
    data=fixture();sell=data['orders'][1];tracking=tmp_path/'data/tracking';tracking.mkdir(parents=True)
    statepath=tracking/'pnl_state.json';statepath.write_text(json.dumps(data['state']))
    audits=tmp_path/'data/audits';audits.mkdir()
    (audits/'paper_demo_case.log').write_text(f"{sell['submitted_at']} | INFO | submission | paper | test | test-submission | Order submitted: sell 172 DDOG\n")
    class Broker:
        def __init__(self,*args,**kwargs):pass
        def fetch_orders(self,status='all',limit=500):return SimpleNamespace(payload=[] if status=='open' else data['orders'])
        def fetch_positions(self):return SimpleNamespace(payload=[])
        def cancel_order(self,*args):raise AssertionError('no trading side effect allowed')
        def fetch_latest_quote(self,*args):raise AssertionError('already complete fill needs no quote')
    monkeypatch.setattr(reconcile_orders,'BrokerClient',Broker)
    monkeypatch.setattr(reconcile_orders,'project_root',tmp_path)
    monkeypatch.setenv('BROKER_API_KEY','test-only');monkeypatch.setenv('BROKER_API_SECRET','test-only')
    before=statepath.read_bytes()
    assert reconcile_orders.main()==1, 'baseline migration obstacle must reproduce in actual entrypoint'
    assert statepath.read_bytes()==before, 'refusal must not rewrite existing financial state'
    proposed,_,_=module.preview(**data);statepath.write_text(json.dumps(proposed))
    after=statepath.read_bytes()
    assert reconcile_orders.main()==0 and reconcile_orders.main()==0, 'preview should pass with unchanged runtime thresholds'
    assert statepath.read_bytes()==after, 'repeated completion observation must not mutate the precision-restored copy'
