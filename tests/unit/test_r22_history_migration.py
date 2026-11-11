"""R22 historical supersession regression, 2026-10-21 / baseline b542219.

Acceptance: preserve evidence, replace active economics, reject stale/ambiguous
plans, recover a prepared migration without duplicate consumption or events.
"""
from copy import deepcopy
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import pytest

from stock_swing.tracking.history_migration import prepare_migration, apply_migration
from stock_swing.tracking.ledger_transaction import FILES, digest, LedgerConflict
from stock_swing.tracking.pnl_tracker import PnLTracker
from stock_swing.tracking.trade_event_store import TradeEventStore

ROOT = Path(__file__).resolve().parents[2]

def fixture_plan(root):
    spec=importlib.util.spec_from_file_location('history_review',ROOT/'docs/r22_residual_orders_20261021/review.py')
    review=importlib.util.module_from_spec(spec);spec.loader.exec_module(review)
    f=json.loads((ROOT/'docs/r22_residual_orders_20261021/review_packet/evidence/residual_cases.json').read_text())
    s=f['state'];s.update(created_at='2026-05-12T00:00:00Z',last_updated='2026-10-21T00:00:00Z',broker_account_id='fixture-account',
        daily_snapshots=[dict(date='2026-08-20',equity=100000,cumulative_profit_factor=.8)],
        strategy_daily_snapshots=[dict(date='2026-08-20',strategy_version_id='old',equity_index=90)],peak_equity=110000,max_drawdown_pct=.2)
    for r in s['trades']+s['quarantined_trades']:r['account_id']='fixture-account'
    proposals=review.review(f)
    data={'pnl_state.json':json.dumps(s).encode(),'trade_events.jsonl':b''.join((json.dumps(e)+'\n').encode() for e in f['events']),
          'fill_ledger.jsonl':b'', 'fill_consumed_ledger.json':b'{"fills":[]}'}
    folder=root/'data/tracking';folder.mkdir(parents=True)
    for name,b in data.items():(folder/name).write_bytes(b)
    plan=prepare_migration(data,row_changes=proposals['row_changes'],corporate_plans=proposals['corporate_plans'],
        evidence_sha256=digest(json.dumps(f,sort_keys=True).encode()),recorded_at='2026-10-21T05:00:00Z',reason='R22 raw-fill review')
    return f,data,plan


def test_ac_old_quarantine_and_events_are_preserved_but_not_double_counted(tmp_path):
    f,before,plan=fixture_plan(tmp_path)
    result=apply_migration(tmp_path,plan)
    assert result['status']=='applied'
    tracker=PnLTracker(tmp_path)
    crwd=[r for r in tracker.state.trades if r['symbol']=='CRWD']
    assert len(crwd)==6 and sum(r['qty'] for r in crwd)==484
    assert not any(r['symbol']=='CRWD' for r in tracker.state.quarantined_trades)
    events=TradeEventStore(tmp_path).read_all()
    economic=[e for e in events if e.event_type=='trade_closed']
    assert sum(e.payload['exit_qty'] for e in economic)==sum(r['qty'] for r in tracker.state.trades if r['exit_broker_order_id'] in plan['affected_sell_orders'])
    assert (tmp_path/'data/tracking/trade_events.jsonl').read_bytes().startswith(before['trade_events.jsonl'])
    assert tracker.state.history_migrations[0]['before_sha256']['pnl_state.json']==digest(before['pnl_state.json'])
    frozen={n:(tmp_path/'data/tracking'/n).read_bytes() for n in FILES}
    assert apply_migration(tmp_path,plan)['status']=='already_applied'
    assert frozen=={n:(tmp_path/'data/tracking'/n).read_bytes() for n in FILES}


def test_ac_archive_cash_aggregates_snapshots_and_runtime_readers_agree(tmp_path, monkeypatch):
    import base64
    from decimal import Decimal as D
    from stock_swing.tracking.execution_cost import incremental_sell_fill
    f,before,plan=fixture_plan(tmp_path)
    old=json.loads(before['pnl_state.json']);apply_migration(tmp_path,plan)
    tracker=PnLTracker(tmp_path);state=asdict(tracker.state)
    assert base64.b64decode(state['history_migrations'][0]['original_state_b64'])==before['pnl_state.json'],'byte-exact original is retained'
    assert sum(D(str(r['pnl'])) for r in state['trades'])-sum(D(str(r['pnl'])) for r in old['trades'] if r['status']=='closed')==D('-494.52')
    summary=tracker.get_summary()
    assert summary['cumulative_realized_pnl']==pytest.approx(sum(r['pnl'] for r in state['trades']))
    assert state['total_trades']==len(state['trades'])
    assert (state['peak_equity'],state['max_drawdown_pct'])==(old['peak_equity'],old['max_drawdown_pct'])
    for collection in ['daily_snapshots','strategy_daily_snapshots']:
        for original,now in zip(old[collection],state[collection]):
            assert {k:now[k] for k in original}==original,'historical values are not hindsight rewrites'
            assert now['history_basis']=='pre_correction_as_observed'
    for name in ['fill_ledger.jsonl','fill_consumed_ledger.json']:
        assert (tmp_path/'data/tracking'/name).read_bytes()==before[name],'consumption is never regenerated or doubled'
    for order in f['orders']:
        if order['side']=='sell' and order['id'] in plan['affected_sell_orders']:
            assert incremental_sell_fill(order,state['trades']+state['quarantined_trades']).qty==0
    raw=TradeEventStore(tmp_path).read_raw();active=TradeEventStore(tmp_path).read_all()
    assert len(raw)>len(active),'audit and economic views have deliberately different scopes'
    # Fake only external broker availability. No internal accounting mocked.
    for key in ['BROKER_API_KEY','BROKER_API_SECRET','BROKER_BASE_URL']:monkeypatch.delenv(key,raising=False)
    from stock_swing.reporting.performance_snapshot import build_snapshot
    report=build_snapshot(tmp_path).to_dict()
    assert report['tracking_context']['measurement_lineage']['promotion_ready'] is False
    assert any(a['type']=='historical_correction_unqualified' for a in report['alerts'])
    assert report['cumulative_realized_pnl']==pytest.approx(summary['cumulative_realized_pnl'])


def test_ac_stale_long_lived_writer_refreshes_and_preserves_history(tmp_path):
    f,before,plan=fixture_plan(tmp_path)
    stale=PnLTracker(tmp_path)
    apply_migration(tmp_path,plan)
    stale.record_submission('NEW','test','buy',2,100,'new-buy','new-client')
    stale.record_exit('NEW',105,2,'new-sell','test','test')
    current=PnLTracker(tmp_path)
    assert current.state.history_migrations[0]['migration_id']==plan['migration_id']
    assert current.state.cumulative_realized_pnl==pytest.approx(plan['stats']['new_active_pnl']+10)
    assert len([e for e in TradeEventStore(tmp_path).read_all() if e.broker_order_id=='new-sell'])==1
    frozen={n:(tmp_path/'data/tracking'/n).read_bytes() for n in FILES}
    assert apply_migration(tmp_path,plan)['status']=='already_applied'
    assert frozen=={n:(tmp_path/'data/tracking'/n).read_bytes() for n in FILES},'retry must preserve post-migration writes'


def test_ac_new_snapshot_does_not_splice_old_strategy_index(tmp_path):
    _,before,plan=fixture_plan(tmp_path);apply_migration(tmp_path,plan)
    tracker=PnLTracker(tmp_path);tracker.record_daily_snapshot(100000)
    state=PnLTracker(tmp_path).state
    assert state.daily_snapshots[-1]['ledger_revision']==plan['migration_id']
    assert state.daily_snapshots[0]['ledger_revision']!=plan['migration_id']
    assert state.strategy_daily_snapshots[0]['history_basis']=='pre_correction_as_observed'
    new=[r for r in state.strategy_daily_snapshots if r.get('ledger_revision')==plan['migration_id']]
    assert new and all(r['equity_index']==100 for r in new),'new origin; old equity indices cannot leak across revisions'


@pytest.mark.parametrize('name',sorted(FILES))
def test_ac_changed_or_missing_dependency_rejects_without_partial_write(tmp_path,name):
    _,before,plan=fixture_plan(tmp_path)
    path=tmp_path/'data/tracking'/name;path.write_bytes(before[name]+b'\n')
    changed={n:(tmp_path/'data/tracking'/n).read_bytes() for n in FILES}
    with pytest.raises(LedgerConflict):apply_migration(tmp_path,plan)
    assert changed=={n:(tmp_path/'data/tracking'/n).read_bytes() for n in FILES}
    path.unlink()
    with pytest.raises(LedgerConflict,match='missing'):apply_migration(tmp_path,plan)


@pytest.mark.parametrize('fault',['after','id','schema','before','evidence','retirement','identity','arithmetic','holding','duplicate','nonfinite','missing_state','bad_events'])
def test_ac_invalid_proposals_or_plan_fail_closed(tmp_path,fault):
    _,before,plan=fixture_plan(tmp_path);bad=deepcopy(plan)
    if fault=='after':bad['after_state']['cumulative_realized_pnl']+=1
    elif fault=='id':bad['migration_id']='bad'
    elif fault=='schema':bad['schema_version']=999
    elif fault=='before':bad['intent']['before_sha256']['pnl_state.json']='0'*64
    else:
        intent=deepcopy(plan['intent']);inputs=dict(before)
        if fault=='evidence':intent['evidence_sha256']='invalid'
        elif fault=='retirement':intent['corporate_provenance'][0]['retire_records'].pop()
        elif fault=='identity':intent['row_changes'][0]['after']['trade_id']='different'
        elif fault=='arithmetic':intent['row_changes'][0]['after']['pnl']+=1
        elif fault=='holding':intent['corporate_provenance'][0]['candidate_rows'][0]['holding_days']=0
        elif fault=='duplicate':intent['row_changes'].append(deepcopy(intent['row_changes'][0]))
        elif fault=='nonfinite':intent['row_changes'][0]['after']['entry_price']=float('nan')
        elif fault=='missing_state':inputs['pnl_state.json']=b'{bad'
        elif fault=='bad_events':inputs['trade_events.jsonl']=b'{bad\n'
        with pytest.raises((ValueError,LedgerConflict)):
            prepare_migration(inputs,row_changes=intent['row_changes'],corporate_plans=intent['corporate_provenance'],
                evidence_sha256=intent['evidence_sha256'],recorded_at=intent['recorded_at'],reason=intent['reason'])
        return
    with pytest.raises(LedgerConflict):apply_migration(tmp_path,bad)
    assert before=={n:(tmp_path/'data/tracking'/n).read_bytes() for n in FILES}


@pytest.mark.parametrize('fault',['missing_state','missing_events','missing_history','archive','reactivated','changed_row','marker','missing_replacement','event_hash','unsupported_marker','duplicate_event'])
def test_ac_corrupt_postmigration_pairs_block_readers_and_writers(tmp_path,fault):
    _,_,plan=fixture_plan(tmp_path);apply_migration(tmp_path,plan)
    folder=tmp_path/'data/tracking';s=json.loads((folder/'pnl_state.json').read_bytes())
    events=[json.loads(x) for x in (folder/'trade_events.jsonl').read_text().splitlines()]
    if fault=='missing_state':pass
    elif fault=='missing_events':events=[]
    elif fault=='missing_history':s.pop('history_migrations')
    elif fault=='archive':s['history_migrations'][0]['original_state_b64']='e30='
    elif fault=='reactivated':s['quarantined_trades'].append(plan['intent']['retire_records'][-1]['before'])
    elif fault=='changed_row':s['trades'][0]['pnl']+=1
    elif fault=='marker':events.pop()
    elif fault=='missing_replacement':events.pop(-2)
    elif fault=='event_hash':events[0]['payload']['pnl']=999999
    elif fault=='unsupported_marker':events[-1]['payload']['schema_version']=999
    elif fault=='duplicate_event':events.append(deepcopy(events[0]))
    (folder/'pnl_state.json').write_text(json.dumps(s));(folder/'trade_events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    if fault=='missing_state':(folder/'pnl_state.json').unlink()
    with pytest.raises((ValueError,LedgerConflict)):PnLTracker(tmp_path)
    with pytest.raises((ValueError,LedgerConflict)):TradeEventStore(tmp_path).read_all()
    with pytest.raises((ValueError,LedgerConflict)):apply_migration(tmp_path,plan)


WORKER=r'''
import json,os,sys,time
from pathlib import Path
from stock_swing.tracking.history_migration import apply_migration
root=Path(sys.argv[1]);point=sys.argv[2];plan=json.loads((root/'plan.json').read_text())
real_replace=os.replace
if point!='concurrent':
 def replaced(src,dst):
  if point=='before_prepare' and Path(dst).name=='.ledger_transaction.json':os._exit(73)
  result=real_replace(src,dst)
  if Path(dst).name==point:os._exit(73)
  return result
 os.replace=replaced
 real_unlink=Path.unlink
 def unlinked(self,*a,**kw):
  result=real_unlink(self,*a,**kw)
  if point=='after_unlink' and self.name=='.ledger_transaction.json':os._exit(73)
  return result
 Path.unlink=unlinked
print(apply_migration(root,plan)['status'])
'''

def worker(root,point):
    import subprocess,sys,os
    return subprocess.Popen([sys.executable,'-c',WORKER,str(root),point],env=dict(os.environ,PYTHONPATH=str(ROOT/'src')),
        text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)


@pytest.mark.parametrize('point',['before_prepare','.ledger_transaction.json','pnl_state.json','trade_events.jsonl','after_unlink'])
def test_ac_abrupt_death_and_recovery_publish_exactly_one_transition(tmp_path,point):
    _,before,plan=fixture_plan(tmp_path);(tmp_path/'plan.json').write_text(json.dumps(plan))
    p=worker(tmp_path,point);out,err=p.communicate(timeout=15)
    assert p.returncode==73,(out,err)
    if point=='before_prepare':
        assert before=={n:(tmp_path/'data/tracking'/n).read_bytes() for n in FILES}
    # This explicit read can roll forward a prepared transaction.
    PnLTracker(tmp_path)
    apply_migration(tmp_path,plan)
    state=PnLTracker(tmp_path).state
    assert len(state.history_migrations)==1
    assert state.cumulative_realized_pnl==pytest.approx(plan['stats']['new_active_pnl'])
    assert len(TradeEventStore(tmp_path).read_raw())==len(before['trade_events.jsonl'].splitlines())+plan['stats']['corrected_events']+1
    assert not (tmp_path/'data/tracking/.ledger_transaction.json').exists()
    for n in ['fill_ledger.jsonl','fill_consumed_ledger.json']:assert (tmp_path/'data/tracking'/n).read_bytes()==before[n]


def test_ac_two_processes_cannot_double_apply(tmp_path):
    _,_,plan=fixture_plan(tmp_path);(tmp_path/'plan.json').write_text(json.dumps(plan))
    children=[worker(tmp_path,'concurrent') for _ in range(2)];results=[]
    for child in children:
        out,err=child.communicate(timeout=15);assert child.returncode==0,err;results.append(out.strip())
    assert sorted(results)==['already_applied','applied']
    assert len(PnLTracker(tmp_path).state.history_migrations)==1


def test_ac_long_lived_readers_refresh_at_migration_boundary(tmp_path):
    _,_,plan=fixture_plan(tmp_path);reader=PnLTracker(tmp_path)
    assert not reader.state.history_migrations
    apply_migration(tmp_path,plan)
    assert reader.get_summary()['cumulative_realized_pnl']==pytest.approx(plan['stats']['new_active_pnl'])
    assert len(reader.get_recent_trades(1000))==len(reader.state.trades)
    assert reader.get_open_positions()==[]
    assert reader.get_asset_class_breakdown()['all']['net_pnl']==pytest.approx(plan['stats']['new_active_pnl'])


def test_ac_stale_explicit_editor_cannot_erase_migration(tmp_path):
    _,_,plan=fixture_plan(tmp_path);editor=PnLTracker(tmp_path)
    apply_migration(tmp_path,plan);editor.state.trades[0]['pnl']+=1
    with pytest.raises(LedgerConflict):editor._save_state()
    with pytest.raises(LedgerConflict):editor.get_summary()
    assert len(PnLTracker(tmp_path).state.history_migrations)==1


def test_ac_prepared_journal_conflict_never_overwrites_third_party(tmp_path):
    from stock_swing.tracking.ledger_transaction import recover_ledger
    _,_,plan=fixture_plan(tmp_path);(tmp_path/'plan.json').write_text(json.dumps(plan))
    child=worker(tmp_path,'pnl_state.json');child.communicate(timeout=15)
    assert child.returncode==73
    path=tmp_path/'data/tracking/trade_events.jsonl';path.write_bytes(path.read_bytes()+b'\n')
    before={n:(tmp_path/'data/tracking'/n).read_bytes() for n in FILES}
    with pytest.raises(LedgerConflict,match='differs'):recover_ledger(tmp_path)
    assert before=={n:(tmp_path/'data/tracking'/n).read_bytes() for n in FILES}
    assert (tmp_path/'data/tracking/.ledger_transaction.json').exists(),'retain evidence rather than erase conflicted journal'


def test_ac_schema_dropping_old_writer_is_detected(tmp_path):
    _,_,plan=fixture_plan(tmp_path);apply_migration(tmp_path,plan)
    path=tmp_path/'data/tracking/pnl_state.json';state=json.loads(path.read_bytes())
    state.pop('history_migrations');state.pop('measurement_lineage');path.write_text(json.dumps(state))
    with pytest.raises((ValueError,LedgerConflict)):PnLTracker(tmp_path)
    with pytest.raises((ValueError,LedgerConflict)):TradeEventStore(tmp_path).read_all()
    # A raw legacy JSON reader cannot be protected by a library lock. Deployment
    # therefore requires its removal/upgrade, not a claim of global atomicity.
    raw=[json.loads(x) for x in (tmp_path/'data/tracking/trade_events.jsonl').read_text().splitlines()]
    assert len(raw)>len(plan['after_state']['trades'])


def test_ac_event_store_does_not_accept_orphan_correction(tmp_path):
    from stock_swing.tracking.trade_event_store import TradeEvent
    _,_,plan=fixture_plan(tmp_path);apply_migration(tmp_path,plan)
    store=TradeEventStore(tmp_path);before=store.path.read_bytes()
    event=TradeEvent.create('trade_closed',payload={'history_migration_id':'orphan','pnl':1})
    with pytest.raises(LedgerConflict,match='orphan'):store.append(event)
    assert store.path.read_bytes()==before


def test_ac_regression_old_amat_duplicate_event_is_excluded_once(tmp_path):
    f,before,plan=fixture_plan(tmp_path)
    oid=next(c['order_id'] for c in f['cases'] if c['symbol']=='AMAT')
    def rows():return [e for e in TradeEventStore(tmp_path).read_all() if e.event_type=='trade_closed' and e.broker_order_id==oid]
    assert sum(e.payload['exit_qty'] for e in rows())==242,'baseline b542219 reproduces duplicate 98-share close'
    apply_migration(tmp_path,plan)
    assert sum(e.payload['exit_qty'] for e in rows())==144
    assert sum(e.payload['pnl'] for e in rows())==pytest.approx(-9782.99)
    assert len([e for e in TradeEventStore(tmp_path).read_raw() if e.broker_order_id==oid and e.event_type=='trade_closed'])==5,'3 original plus 2 correction events retained'


def test_ac_migration_io_failure_preserves_recoverable_journal(tmp_path,monkeypatch):
    import os
    from stock_swing.tracking.ledger_transaction import recover_ledger
    _,_,plan=fixture_plan(tmp_path);original=os.replace
    def fail(src,dst):
        if Path(dst).name=='trade_events.jsonl':raise OSError('injected filesystem failure')
        return original(src,dst)
    with monkeypatch.context() as patch:
        patch.setattr(os,'replace',fail)
        with pytest.raises(OSError,match='injected'):apply_migration(tmp_path,plan)
    assert (tmp_path/'data/tracking/.ledger_transaction.json').exists()
    recover_ledger(tmp_path)
    assert apply_migration(tmp_path,plan)['status']=='already_applied'
