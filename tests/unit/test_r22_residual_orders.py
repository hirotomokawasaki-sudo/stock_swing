"""Regression: R22 residual 9 orders, baseline 1942fc5 (2026-10-21).

Acceptance: raw-fill-supported proposals, no ledger/event mutation, strict
ambiguity rejection, precise incremental proceeds and preserved quarantine.
"""
from copy import deepcopy
from decimal import Decimal as D
import importlib.util
import json
from pathlib import Path

import pytest

from stock_swing.tracking.execution_cost import incremental_sell_fill, ExecutionCostError

ROOT=Path(__file__).resolve().parents[2]
SPEC=importlib.util.spec_from_file_location('r22_residual_preview',ROOT/'docs/r22_residual_orders_20261021/repair_preview.py')
repair=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair)


@pytest.fixture
def evidence():
    return json.loads((ROOT/'docs/r22_residual_orders_20261021/review_packet/evidence/residual_cases.json').read_text())


def case(f,symbol):
    return next(c for c in f['cases'] if c['symbol']==symbol)


def rows(f,symbol):
    oid=case(f,symbol)['order_id']
    return [r for r in f['state']['trades'] if r.get('exit_broker_order_id')==oid]


def propose(f,symbol):
    c=case(f,symbol)
    args=(f['state'],f['orders'],f['activities'])
    if c['kind']=='precision':return repair.group_precision(*args,[c['order_id']])
    return repair.partial_economics(*args,f['fill_revisions'],[c['order_id']])


@pytest.mark.parametrize(('symbol','count'),[('NBIS',3),('HPQ',2),('CRM',3),('SKYY',3),('MRVL',2)])
def test_ac_multi_lot_precision_reproduces_stop_then_preserves_every_pnl(evidence,symbol,count):
    frozen=deepcopy(evidence)
    oid=case(evidence,symbol)['order_id'];order=next(o for o in evidence['orders'] if o['id']==oid)
    with pytest.raises(ExecutionCostError,match='same-quantity notional revision'):
        incremental_sell_fill(order,evidence['state']['trades'])
    changes=propose(evidence,symbol)
    assert len(changes)==count,'all group lots must be considered together'
    for c in changes:
        assert c['pnl_delta']=='0.00','price restoration must not create profit'
        diff={k for k in c['before'] if c['before'].get(k)!=c['after'].get(k)}
        assert diff<={'entry_price','exit_price'},'only price representations may change'
    projected=repair.project_rows(evidence['state'],changes)
    assert incremental_sell_fill(order,projected).qty==0,'whole SELL must be a replay no-op'
    again=deepcopy(evidence);again['state']['trades']=projected
    assert propose(again,symbol)==[],'precision preview must be idempotent'
    assert evidence==frozen,'input evidence and quarantine must not mutate'


@pytest.mark.parametrize('fault',['pnl','missing_fill','fill_qty','duplicate_fill','duplicate_order','wrong_symbol',
                                  'group_qty','shared_buy','quarantine','wide_price','nan','naive','future_buy','split'])
def test_ac_precision_withholds_entire_group_on_incomplete_or_conflicting_evidence(evidence,fault):
    symbol='NBIS';r=rows(evidence,symbol)[0];oid=case(evidence,symbol)['order_id']
    buy=next(o for o in evidence['orders'] if o['id']==r['broker_order_id'])
    fill=next(a for a in evidence['activities'] if a.get('order_id')==oid)
    if fault=='pnl':r['pnl']+=1
    elif fault=='missing_fill':evidence['activities'].remove(fill)
    elif fault=='fill_qty':fill['qty']='1'
    elif fault=='duplicate_fill':evidence['activities'].append(deepcopy(fill))
    elif fault=='duplicate_order':evidence['orders'].append(deepcopy(buy))
    elif fault=='wrong_symbol':r['symbol']='WRONG'
    elif fault=='group_qty':r['qty']+=1
    elif fault=='shared_buy':evidence['state']['trades'].append(deepcopy(r))
    elif fault=='quarantine':evidence['state']['quarantined_trades'].append(deepcopy(r))
    elif fault=='wide_price':r['entry_price']+=1
    elif fault=='nan':r['entry_price']=float('nan')
    elif fault=='naive':r['entry_time']='2026-08-04T10:00:00'
    elif fault=='future_buy':
        buy['filled_at']='2026-08-07T10:00:00Z'
        for a in evidence['activities']:
            if a.get('order_id')==buy['id']:a['transaction_time']=buy['filled_at']
    elif fault=='split':evidence['activities'].append(dict(id='extra-split',activity_type='SPLIT',symbol=symbol,date='2026-08-05'))
    frozen=deepcopy(evidence)
    with pytest.raises(ValueError):propose(evidence,symbol)
    # NaN does not compare equal in reconstructed objects; input bytes do.
    assert json.dumps(evidence,sort_keys=True)==json.dumps(frozen,sort_keys=True),'reject without partial mutation'


@pytest.mark.parametrize(('symbol','delta','final_price'),[('NVDA','0.04',210.32),('CIEN','10.96',424.79),('AMAT','-169.97',453.6986956521739)])
def test_ac_raw_partial_intervals_and_buy_basis_determine_economic_delta(evidence,symbol,delta,final_price):
    frozen=deepcopy(evidence);oid=case(evidence,symbol)['order_id']
    order=next(o for o in evidence['orders'] if o['id']==oid)
    with pytest.raises(ExecutionCostError,match='same-quantity notional revision'):
        incremental_sell_fill(order,evidence['state']['trades'])
    changes=propose(evidence,symbol)
    assert len(changes)==2,'both partial rows are included in provenance'
    assert sum(D(c['pnl_delta']) for c in changes)==D(delta),'independent raw cash difference'
    assert changes[-1]['after']['exit_price']==pytest.approx(final_price),'incremental price is not cumulative VWAP'
    for c in changes:
        for key in ['qty','entry_time','exit_time','trade_id','broker_order_id','exit_broker_order_id','strategy_id','execution_leg_id']:
            assert c['before'].get(key)==c['after'].get(key),'numeric proposal must preserve lineage and recorded observation times'
    projected=repair.project_rows(evidence['state'],changes)
    assert incremental_sell_fill(order,projected).qty==0,'fixed historical proceeds must reconcile'
    again=deepcopy(evidence);again['state']['trades']=projected
    assert propose(again,symbol)==[],'economic preview must not apply its delta twice'
    assert evidence==frozen,'no ledger or event mutation'


@pytest.mark.parametrize('fault',['missing_revision','revision_price','revision_reorder','consumption','boundary',
                                  'lifecycle_qty','quarantine','same_time','future_buy','raw_price','unknown_order','shared_exit',
                                  'early_observation','early_revision'])
def test_ac_partial_requires_complete_boundary_lifecycle_and_raw_evidence(evidence,fault):
    symbol='NVDA';selected=rows(evidence,symbol);oid=case(evidence,symbol)['order_id']
    revisions=[r for r in evidence['fill_revisions'] if r.get('order_id')==oid]
    buyid=selected[0]['broker_order_id'];buy=next(o for o in evidence['orders'] if o['id']==buyid)
    if fault=='missing_revision':evidence['fill_revisions']=[r for r in evidence['fill_revisions'] if r.get('order_id')!=oid]
    elif fault=='revision_price':revisions[0]['price']+=1
    elif fault=='revision_reorder':evidence['fill_revisions'].reverse()
    elif fault=='consumption':revisions[-1]['consumed_qty']+=1
    elif fault=='boundary':selected[0]['qty']+=1;selected[1]['qty']-=1
    elif fault=='lifecycle_qty':buy['filled_qty']='351'
    elif fault=='quarantine':evidence['state']['quarantined_trades'].append(deepcopy(selected[0]))
    elif fault=='same_time':selected[0]['exit_time']=selected[1]['exit_time']
    elif fault=='early_observation':selected[1]['exit_time']='2026-08-24T15:59:00Z'
    elif fault=='early_revision':revisions[0]['filled_at']='2026-08-24T15:59:00Z'
    elif fault=='future_buy':
        buy['filled_at']='2026-08-25T00:00:00Z'
        for a in evidence['activities']:
            if a.get('order_id')==buyid:a['transaction_time']=buy['filled_at']
    elif fault=='raw_price':next(a for a in evidence['activities'] if a.get('order_id')==oid)['price']='500'
    elif fault=='unknown_order':selected[0]['broker_order_id']='not-in-evidence'
    elif fault=='shared_exit':
        other=deepcopy(selected[0]);other['broker_order_id']='another-buy';evidence['state']['trades'].append(other)
    frozen=deepcopy(evidence)
    with pytest.raises(ValueError):propose(evidence,symbol)
    assert evidence==frozen,'ambiguous partial evidence must leave originals intact'


def test_ac_corporate_plan_preserves_old_quarantine_and_shows_full_scope_delta(evidence):
    frozen=deepcopy(evidence)
    plan=repair.corporate_plan(evidence['state'],evidence['orders'],evidence['activities'],'CRWD','2026-08-24')
    assert len(plan['candidate_rows'])==6 and sum(r['qty'] for r in plan['candidate_rows'])==484
    assert plan['old_active_pnl']=='-1828.15' and plan['new_active_pnl']=='-2163.70'
    assert plan['pnl_delta']=='-335.55' and plan['cash_pnl']=='-2163.70'
    assert len(plan['retire_records'])==7,'five main rows and two quarantine copies must be mapped'
    assert not plan['apply_ready'],'numeric reconstruction is not a migration'
    assert all(repair.utc_time(r['entry_time'])<=repair.utc_time(r['exit_time']) for r in plan['candidate_rows'])
    # The 99 tracked-order sample contains only the later CRWD exit. Check all
    # reconstructed exits too: retained legacy quarantine double-consumes two.
    retire={x['row_index'] for x in plan['retire_records'] if x['collection']=='trades'}
    candidate=[r for i,r in enumerate(evidence['state']['trades']) if i not in retire]+plan['candidate_rows']
    targets={r['exit_broker_order_id'] for r in plan['candidate_rows']}
    failures=[]
    for order in evidence['orders']:
        if order['id'] not in targets:continue
        try:incremental_sell_fill(order,candidate+evidence['state']['quarantined_trades'])
        except ExecutionCostError:failures.append(order['filled_at'][:10])
        assert incremental_sell_fill(order,candidate).qty==0,'explicitly superseded view reconciles raw exits'
    assert sorted(failures)==['2026-07-13','2026-07-15'],'unmodified quarantine blocks full lifecycle, even if tracked sample passes'
    assert evidence==frozen,'historical quarantine is evidence, not disposable noise'


@pytest.mark.parametrize('fault',['missing_split','split_qty','split_group','missing_buy'])
def test_ac_corporate_never_guesses_inventory_or_split_identity(evidence,fault):
    splits=[a for a in evidence['activities'] if a.get('activity_type')=='SPLIT']
    if fault=='missing_split':evidence['activities'].remove(splits[0])
    elif fault=='split_qty':next(a for a in splits if D(a['qty'])>0)['qty']='173'
    elif fault=='split_group':splits[0]['group_id']='other-group'
    elif fault=='missing_buy':evidence['orders']=[o for o in evidence['orders'] if not(o['symbol']=='CRWD' and o['side']=='buy' and o['filled_qty']=='43')]
    with pytest.raises(ValueError):repair.corporate_plan(evidence['state'],evidence['orders'],evidence['activities'],'CRWD','2026-08-24')


def test_ac_projection_is_compare_and_swap_idempotent_and_rejects_overlap(evidence):
    changes=propose(evidence,'CIEN');before=deepcopy(evidence['state'])
    projected=repair.project_rows(before,changes)
    assert repair.project_rows({'trades':projected},changes)==projected
    assert evidence['state']==before,'projection must not mutate input'
    with pytest.raises(ValueError,match='overlapping'):repair.project_rows(before,changes+changes)
    stale=deepcopy(before);stale['trades'][changes[0]['row_index']]['qty']+=1
    with pytest.raises(ValueError,match='stale'):repair.project_rows(stale,changes)


@pytest.mark.parametrize('symbol',['NBIS','HPQ','CRM','SKYY','MRVL'])
def test_ac_existing_corrected_settlement_conserves_multi_lot_event_economics(tmp_path,evidence,symbol):
    """Actual inherited runtime, not a mocked event emitter or historical replay."""
    from stock_swing.tracking.pnl_tracker import PnLTracker
    from stock_swing.tracking.settle_sell import settle_sell
    from stock_swing.tracking.trade_event_store import TradeEventStore
    source=repair.Evidence(evidence['orders'],evidence['activities'])
    target=case(evidence,symbol)['order_id'];sell=source.order(target,'sell',symbol)
    selected=sorted(rows(evidence,symbol),key=lambda r:repair.utc_time(r['entry_time']))
    tracker=PnLTracker(tmp_path)
    for index,row in enumerate(selected):
        buy=source.order(row['broker_order_id'],'buy',symbol)
        tracker.record_submission(symbol,'research','buy',buy['qty'],float(buy['price']),
                                  buy['order']['id'],f'{index:08d}-fixture')
    order=dict(sell['order'],filled_avg_price=str(sell['price']))
    settle_sell(tmp_path,order)
    closed=[e for e in TradeEventStore(tmp_path).read_all() if e.event_type=='trade_closed']
    assert len(closed)==len(selected),'corrected writer emits each actual lot separately'
    assert sum(e.payload['exit_qty'] for e in closed)==sell['qty'],'event qty conservation'
    assert sum(D(str(e.payload['pnl'])) for e in closed)==sum(D(str(r['pnl'])) for r in selected),'event PnL conservation'
    before={p.name:p.read_bytes() for p in (tmp_path/'data/tracking').glob('*') if p.is_file()}
    assert settle_sell(tmp_path,order) is None,'cumulative replay must not close twice'
    after={p.name:p.read_bytes() for p in (tmp_path/'data/tracking').glob('*') if p.is_file()}
    assert before==after,'all files stable on retry'


@pytest.mark.parametrize('fault',[None,'duplicate_case','unknown_kind'])
def test_ac_review_reports_scope_and_does_not_double_count_cases(evidence,fault):
    spec=importlib.util.spec_from_file_location('r22_residual_review',ROOT/'docs/r22_residual_orders_20261021/review.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    if fault=='duplicate_case':evidence['cases'].append(deepcopy(evidence['cases'][0]))
    elif fault=='unknown_kind':evidence['cases'][0]['kind']='guess'
    frozen=deepcopy(evidence)
    if fault:
        with pytest.raises(ValueError):module.review(evidence)
    else:
        result=module.review(evidence)
        assert result['summary']['case_count']==9
        assert result['summary']['ordinary_changed_rows']==19
        assert result['summary']['ordinary_pnl_delta']=='-158.97'
        assert result['summary']['all_case_scopes_pnl_delta']=='-494.52'
        assert sum(r['duplicate_excess_rows'] for r in result['summary']['event_review'])==1
        assert all(not p['apply_ready'] for p in result['corporate_plans'])
    assert evidence==frozen,'review and failed review must preserve inputs'
