"""Actual PF boundary + corrected-ledger observation never resets or releases."""
import copy
import fcntl
import json
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import pytest
from stock_swing.risk.entry_filter import EntryFilterConfig, EntryFilterEngine
from stock_swing.risk.entry_restriction_review import observe_restricted_entries, STORE_V6
from stock_swing.risk.pf_history_receipt import PFHistoryCapture
from stock_swing.tracking.compatibility import read_analysis_snapshot
from stock_swing.tracking.history_migration import apply_migration
from stock_swing.tracking.ledger_transaction import FILES, ledger_transaction
from tests.unit.test_r22_history_migration import fixture_plan

NOW=datetime(2026,11,5,15,tzinfo=timezone.utc)

def setup(root, monkeypatch):
    _, _, plan=fixture_plan(root);apply_migration(root,plan)
    monkeypatch.setenv('ENTRY_RESTRICTION_REVIEW_VERSION','v6')
    monkeypatch.setenv('ENTRY_RESTRICTION_REVIEW_LEDGER_REVISION',plan['migration_id'])
    return root/'data/tracking/pnl_state.json'


def run(root, *, sequence=0, trades=None, override=None, now=None, records=None):
    state,_=read_analysis_snapshot(root/'data/tracking/pnl_state.json')
    trades=state['trades'] if trades is None else trades
    # Compute actual decisions and actual filter output; never synthesize a refusal.
    symbols=sorted({t['symbol'] for t in trades if t.get('status')=='closed'})
    now=now or NOW+timedelta(seconds=sequence)
    decisions=[SimpleNamespace(symbol=s,action='buy',decision_id=f'd-{s}-{sequence}',
        generated_at=now,strategy_id='fixture-strategy',strategy_version_id='fixture-v1') for s in symbols]
    config=EntryFilterConfig(min_volume=0,min_adr_pct=0,min_trades_for_gate=1,rolling_pf_gate=100000)
    capture=PFHistoryCapture(root=root,run_id=f'run-{sequence}',experiment_config_hash='cfg',
        decisions=decisions,closed_trades=trades,entry_config=config,etf_symbols=set(),observed_at=now)
    result=EntryFilterEngine(config).filter(decisions,{},trades,set())
    ref=capture.finish(result)
    original=copy.deepcopy(decisions)
    report=observe_restricted_entries(root=root,decisions=decisions,blocked=result.blocked,
        stop_list=[{'symbol':s} for s,_ in result.blocked],records_by_symbol=records or {},entry_config=config,
        run_id=f'run-{sequence}',config_hash='cfg',observed_at=now,pf_history_receipt=override or ref)
    assert original==decisions
    assert report['eligible_to_trade'] is False
    return report,result


def test_exact_actual_boundary_corrected_revision_and_no_cohort_reset(tmp_path,monkeypatch):
    path=setup(tmp_path,monkeypatch)
    financial={n:(path.parent/n).read_bytes() for n in FILES}
    a,result=run(tmp_path)
    assert result.blocked and a['status']=='observing' and a['observations']>0
    first=json.loads((tmp_path/STORE_V6).read_text())['state']
    assert first['definition']['ledger_contract']['ledger_revision']!='legacy'
    item=first['observations'][0]
    assert item['ledger_input']['pf_history_receipt']['status']=='recorded'
    assert item['ledger_input']['financial_file_sha256']['pnl_state.json']
    assert financial=={n:(path.parent/n).read_bytes() for n in FILES}
    with ledger_transaction(tmp_path) as tx:
        state=json.loads(tx.read(path));state['last_updated']=(NOW+timedelta(seconds=1)).isoformat()
        tx.stage(path,json.dumps(state).encode())
    b,_=run(tmp_path,sequence=1)
    assert b['status']=='observing' and b['definition_hash']==a['definition_hash']
    second=json.loads((tmp_path/STORE_V6).read_text())['state']
    assert second['last_ledger_input']['state_sha256']!=first['last_ledger_input']['state_sha256']
    assert second['observations']==first['observations'], 'overlapping opportunities are not independent'


@pytest.mark.parametrize('damage',['expected_revision','missing_receipt','stale_consumed','prepared','missing_fill','corrupt_receipt','lock','old_namespace'])
def test_unknown_boundaries_preserve_existing_observations(tmp_path,monkeypatch,damage):
    path=setup(tmp_path,monkeypatch);assert run(tmp_path)[0]['status']=='observing'
    store=tmp_path/STORE_V6
    stale=None;override=None
    if damage=='expected_revision':monkeypatch.setenv('ENTRY_RESTRICTION_REVIEW_LEDGER_REVISION','different')
    if damage=='missing_receipt':override={'status':'unavailable'}
    if damage=='stale_consumed':stale=[]
    if damage=='prepared':(path.parent/'.ledger_transaction.json').write_text('{"state":"prepared"}')
    if damage=='missing_fill':(path.parent/'fill_ledger.jsonl').unlink()
    if damage=='corrupt_receipt':override={'status':'recorded','schema':'bad'}
    if damage=='old_namespace':
        old=json.loads(store.read_text());old['state']['definition']['protocol']['version']='pf-review-v5-20261105'
        store.write_text(json.dumps(old))
    before=store.read_bytes()
    if damage in {'lock','prepared'}:
        first=json.loads(store.read_text())['state']['last_ledger_input']['pf_history_receipt']
        def call():
            return observe_restricted_entries(root=tmp_path,decisions=[],blocked=[],stop_list=[],records_by_symbol={},
                entry_config=EntryFilterConfig(),run_id='run-0',config_hash='cfg',observed_at=NOW,pf_history_receipt=first)
        if damage=='lock':
            with (path.parent/'.ledger.lock').open('a+b') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX)
                result=call()
        else:
            result=call()
    else:
        result,_=run(tmp_path,sequence=1,trades=stale,override=override)
    assert result['status']=='error' and result['candidates']==[]
    assert store.read_bytes()==before


def test_matured_v6_outcome_names_its_actual_ledger_input(tmp_path,monkeypatch):
    from datetime import date
    from tests.unit.test_entry_restriction_review import bar
    setup(tmp_path,monkeypatch);first,_=run(tmp_path)
    items=json.loads((tmp_path/STORE_V6).read_text())['state']['observations']
    now=datetime(2026,11,12,21,6,tzinfo=timezone.utc)
    records={item['symbol']:[bar(date.fromisoformat(d),now,symbol=item['symbol']) for d in item['sessions']] for item in items}
    result,_=run(tmp_path,sequence=1,now=now,records=records)
    assert result['status']=='observing' and result['candidates']==[]
    after=json.loads((tmp_path/STORE_V6).read_text())['state']['observations']
    for item in after[:len(items)]:
        assert item['outcome'] is not None
        assert item['outcome']['ledger_input']['run_id']=='run-1'
        assert item['outcome']['ledger_input']['ledger_revision']==item['ledger_input']['ledger_revision']
