"""Acceptance: 2026-10-29 prospective recording gaps, baseline main8909e79/§3.47.

No broker substitutes are needed: real snapshot/exit stores and ledger are used.
Economic fields must remain identical when provenance is absent or withheld.
"""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import gzip
import json
import pytest

from stock_swing.experiments.feature_snapshot_store import FeatureSnapshotStore
from stock_swing.tracking.exit_reason_store import write_exit_reason, delete_exit_reason
from stock_swing.tracking.pnl_tracker import PnLTracker

def lineage(**overrides):
    return dict(dict(symbol='NVDA',broker_order_id='sell-1',exit_decision_id='exit-d',
                exit_run_id='exit-run',exit_experiment_id='exit-exp',exit_config_hash='a'*64,
                exit_decision_time='2026-10-28T15:00:00+00:00',exit_submission_id='exit-sub',
                exit_submitted_at='2026-10-28T15:00:01+00:00'),**overrides)

def test_real_engine_deny_is_not_stored_as_candidate_buy(tmp_path):
    from datetime import datetime, timezone
    from stock_swing.strategy_engine.base_strategy import CandidateSignal
    from stock_swing.decision_engine.decision_engine import DecisionEngine
    from stock_swing.core.runtime import RuntimeMode
    from stock_swing.core.run_context import attach_run_context, RunContext
    from stock_swing.experiments.feature_snapshot_store import decision_snapshot_features
    signal=CandidateSignal('fixture','NVDA','buy',.01,datetime.now(timezone.utc),'3d',.1,'private reasoning')
    decision=DecisionEngine(RuntimeMode.PAPER).process(signal)
    assert decision.action=='deny' and decision.deny_reasons
    decision.decision_time=decision.generated_at.isoformat()
    attach_run_context([decision],RunContext('actual-run','2026-10-28T14:00:00Z','fixture'))
    decision.config_hash='a'*64
    features=decision_snapshot_features(signal,decision)
    store=FeatureSnapshotStore(tmp_path)
    ref=store.save(experiment_id='exp',run_id=decision.run_id,decision_id=decision.decision_id,
        symbol=decision.symbol,features=features,schema_version='r11e-v2')
    doc=store.load(ref)
    assert doc['features']['action']=='deny' and doc['features']['signal_action']=='buy'
    assert doc['decision_time']==decision.generated_at.isoformat()
    assert doc['features']['decision_stage']=='decision_engine'
    assert doc['deny_reasons']==decision.deny_reasons and 'notes' not in doc['features']['evidence']

@pytest.mark.parametrize('field,value',[('experiment_id','../escape'),('run_id','/absolute'),('decision_id','a/b')])
def test_snapshot_identity_cannot_escape_root(tmp_path,field,value):
    store=FeatureSnapshotStore(tmp_path)
    args=dict(experiment_id='e',run_id='r',decision_id='d',symbol='NVDA',features={},schema_version='v2')
    args[field]=value
    with pytest.raises(ValueError):store.save(**args)

def test_corrupt_pending_store_cannot_borrow_previous_leg_context(tmp_path):
    tracker=opened(tmp_path);pending(tmp_path)
    tracker.record_exit('NVDA',110,4,'sell-1',exit_reason='stop_loss')
    (tmp_path/'data/tracking/pending_exit_reasons.json').write_text('{broken')
    tracker.record_exit('NVDA',110,6,'sell-1',exit_reason='stop_loss')
    latest=[t for t in tracker.state.trades if t.get('exit_broker_order_id')=='sell-1' and t['qty']==6][0]
    assert latest.get('exit_decision_id') is None and latest['pnl']==60

@pytest.mark.parametrize('mutation',['none','unknown','decision_mismatch','symbol_mismatch','missing_config','bad_clock'])
def test_submission_context_uses_existing_short_config_version(mutation):
    from datetime import datetime
    from types import SimpleNamespace
    from stock_swing.tracking.exit_reason_store import build_exit_lineage
    decision=SimpleNamespace(action='sell',symbol='NVDA',decision_id='exit-d',run_id='exit-run',
        experiment_id='exit-exp',config_hash='0123456789abcdef',decision_time='2026-10-28T15:00:00Z')
    submission=SimpleNamespace(side='sell',status='submitted',symbol='NVDA',decision_id='exit-d',
        submission_id='sub',broker_order_id='sell-1',submitted_at=datetime.fromisoformat('2026-10-28T15:00:01+00:00'))
    if mutation=='unknown':submission.status='unknown'
    elif mutation=='decision_mismatch':submission.decision_id='other'
    elif mutation=='symbol_mismatch':submission.symbol='OTHER'
    elif mutation=='missing_config':decision.config_hash=None
    elif mutation=='bad_clock':submission.submitted_at='not-a-datetime'
    result=build_exit_lineage(decision,submission)
    assert bool(result)==(mutation=='none')
    if result:assert result['exit_config_hash']=='0123456789abcdef' and 'exit_fill_id' not in result

def opened(root):
    tracker=PnLTracker(root)
    tracker.record_submission(symbol='NVDA',strategy_id='entry',side='buy',qty=10,price=100,
        broker_order_id='buy-1',decision_id='entry-d',run_id='entry-run',
        experiment_id='entry-exp',config_hash='b'*64)
    return tracker

def test_open_remainder_does_not_acquire_exit_schema(tmp_path):
    tracker=opened(tmp_path)
    assert not any(k.startswith('exit_') and k not in ('exit_price','exit_time','exit_reason','exit_strategy_id','exit_fill_id','exit_broker_order_id') for k in tracker.state.trades[0])
    pending(tmp_path);tracker.record_exit('NVDA',110,4,'sell-1',exit_reason='stop_loss')
    remainder=next(t for t in tracker.state.trades if t['status']=='open')
    assert 'exit_decision_id' not in remainder,'old writer must still accept the open remainder after code rollback'

def pending(root,context=None):
    write_exit_reason(root,'sell-1','NVDA','fixture trigger','stop_loss',
        {'exit_lineage':lineage() if context is None else context})

def save(store,features=None):
    return store.save(experiment_id='exp',run_id='run',decision_id='decision',symbol='NVDA',
        features=features or {'action':'deny','decision_time':'2026-10-28T15:00:00+00:00',
            'config_hash':'a'*64,'risk_state':'deny','deny_reasons':['fixture denial']},schema_version='r11e-v2')

def test_snapshot_provenance_is_discoverable_at_top_level(tmp_path):
    store=FeatureSnapshotStore(tmp_path);ref=save(store);doc=store.load(ref)
    assert doc.get('config_hash')=='a'*64,'snapshot must bind the recorded configuration version'
    assert doc.get('decision_time')=='2026-10-28T15:00:00+00:00'
    assert doc.get('deny_reasons')==['fixture denial']

def test_snapshot_conflicting_identity_cannot_overwrite(tmp_path):
    store=FeatureSnapshotStore(tmp_path);ref=save(store);before=Path(ref.path).read_bytes()
    with pytest.raises((ValueError,RuntimeError),match='conflict'):
        save(store,{'action':'sell'})
    assert Path(ref.path).read_bytes()==before,'conflicting retry must preserve original bytes'

def test_snapshot_reference_rejects_changed_bytes(tmp_path):
    store=FeatureSnapshotStore(tmp_path);ref=save(store)
    changed=store.load(ref);changed['features']['action']='sell'
    Path(ref.path).write_bytes(gzip.compress(json.dumps(changed).encode()))
    with pytest.raises((ValueError,RuntimeError),match='hash|drift'):
        store.load(ref)

def test_snapshot_identical_retry_preserves_first_receipt(tmp_path):
    store=FeatureSnapshotStore(tmp_path);first=save(store);raw=Path(first.path).read_bytes();second=save(store)
    assert Path(second.path).read_bytes()==raw,'retry must not mint a new captured-at timestamp'
    assert asdict(first)==asdict(second)

def test_exit_context_survives_partial_restart_and_entry_ids_unchanged(tmp_path):
    tracker=opened(tmp_path);pending(tmp_path)
    tracker.record_exit('NVDA',110,4,'sell-1',exit_reason='stop_loss',fill_id='actual-first-fill')
    first=[t for t in tracker.state.trades if t['status']=='closed'][0]
    assert first.get('exit_decision_id')=='exit-d','closed leg must carry the SELL identity, not entry identity'
    assert first['decision_id']=='entry-d' and first['run_id']=='entry-run'
    assert first['exit_fill_id']=='actual-first-fill'
    delete_exit_reason(tmp_path,'sell-1')
    tracker=PnLTracker(tmp_path)
    tracker.record_exit('NVDA',110,6,'sell-1',exit_reason='stop_loss',fill_id='actual-second-fill')
    closed=[t for t in tracker.state.trades if t['status']=='closed']
    assert sum(t['qty'] for t in closed)==10 and sum(t['pnl'] for t in closed)==100
    assert all(t.get('exit_decision_id')=='exit-d' for t in closed)
    assert all(t['config_hash']=='b'*64 and t['exit_config_hash']=='a'*64 for t in closed)
    assert {t['exit_fill_id'] for t in closed}=={'actual-first-fill','actual-second-fill'}
    events=tracker.event_store.read_all()
    assert all(e.payload.get('exit_decision_id')=='exit-d' for e in events if e.event_type=='trade_closed')

@pytest.mark.parametrize('kind',['missing','corrupt','wrong_symbol','wrong_order','missing_config','bad_hash','naive_clock','reversed_clock','unexpected_field'])
def test_unqualified_context_does_not_invent_lineage_or_block_economics(tmp_path,kind):
    tracker=opened(tmp_path);c=lineage()
    if kind=='wrong_symbol':c['symbol']='OTHER'
    elif kind=='wrong_order':c['broker_order_id']='other-order'
    elif kind=='missing_config':c.pop('exit_config_hash')
    elif kind=='bad_hash':c['exit_config_hash']='not-a-hash'
    elif kind=='naive_clock':c['exit_decision_time']='2026-10-28T15:00:00'
    elif kind=='reversed_clock':c['exit_decision_time']='2026-10-28T16:00:00Z'
    elif kind=='unexpected_field':c['free_text']='must not propagate'
    if kind not in ('missing','corrupt'):pending(tmp_path,c)
    if kind=='corrupt':
        path=tmp_path/'data/tracking/pending_exit_reasons.json';path.write_text('{bad json')
    tracker.record_exit('NVDA',110,10,'sell-1',exit_reason='stop_loss')
    closed=[t for t in tracker.state.trades if t['status']=='closed'][0]
    assert closed.get('exit_decision_id') is None,'unqualified source is not an exit decision'
    assert closed['decision_id']=='entry-d' and closed['pnl']==100 and closed['qty']==10
    assert closed.get('exit_fill_id') is None,'never manufacture fill identity from order identity'

def test_context_does_not_cross_sell_order_on_same_symbol(tmp_path):
    tracker=opened(tmp_path);pending(tmp_path)
    tracker.record_exit('NVDA',110,4,'sell-1',exit_reason='stop_loss')
    delete_exit_reason(tmp_path,'sell-1')
    tracker.record_exit('NVDA',110,6,'sell-2',exit_reason='stop_loss')
    later=[t for t in tracker.state.trades if t.get('exit_broker_order_id')=='sell-2'][0]
    assert later.get('exit_decision_id') is None,'same symbol is not the same exit order'

def test_conflicting_prior_legs_are_not_resolved_by_picking_one(tmp_path):
    tracker=opened(tmp_path);pending(tmp_path)
    tracker.record_exit('NVDA',110,4,'sell-1',exit_reason='stop_loss')
    delete_exit_reason(tmp_path,'sell-1')
    prior=deepcopy([t for t in tracker.state.trades if t['status']=='closed'][0]);prior['exit_decision_id']='other-d'
    tracker.state.trades.append(prior)
    tracker.record_exit('NVDA',110,6,'sell-1',exit_reason='stop_loss')
    latest=[t for t in tracker.state.trades if t.get('exit_broker_order_id')=='sell-1' and t['qty']==6][0]
    assert latest.get('exit_decision_id') is None,'conflicting order context must remain unavailable'

def test_snapshot_missing_corrupt_and_symlink_fail_without_repair(tmp_path):
    store=FeatureSnapshotStore(tmp_path);ref=save(store);path=Path(ref.path);path.unlink()
    with pytest.raises((OSError,ValueError)):store.load(ref)
    path.write_bytes(b'not gzip')
    with pytest.raises((OSError,ValueError)):store.load(ref)
    target=tmp_path/'elsewhere';target.write_bytes(b'untouched');path.unlink();path.symlink_to(target)
    with pytest.raises((OSError,ValueError,RuntimeError)):save(store)
    assert target.read_bytes()==b'untouched'
