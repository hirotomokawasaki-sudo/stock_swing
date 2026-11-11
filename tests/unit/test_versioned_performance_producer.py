"""Exercise the real producer and invariant consumer; mock external I/O only."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from stock_swing.tracking.history_migration import apply_migration
from stock_swing.tracking.ledger_transaction import FILES, ledger_transaction
from tests.unit.test_r22_history_migration import fixture_plan

ROOT=Path(__file__).resolve().parents[2]
def script(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod


def setup(root):
    _,_,plan=fixture_plan(root);apply_migration(root,plan)
    state_path=root/'data/tracking/pnl_state.json'
    with ledger_transaction(root) as tx:
        state=json.loads(tx.read(state_path));state['baseline_equity']=100000
        tx.stage(state_path,json.dumps(state).encode())
    target=root/'data/analysis/performance_summary.json';target.parent.mkdir(parents=True)
    target.write_bytes(b'prior report')
    broker=Mock();broker.fetch_account.return_value=SimpleNamespace(payload={'equity':'100000'})
    broker.fetch_positions.return_value=SimpleNamespace(payload=[])
    return target,broker


def test_real_producer_consumed_by_version_matched_invariant_reader(tmp_path):
    target,broker=setup(tmp_path)
    before={n:(tmp_path/'data/tracking'/n).read_bytes() for n in FILES}
    out=script('build_performance_summary').export(tmp_path,broker)
    assert out['status']=='descriptive_complete' and out['unrealized_pnl']==0
    state=json.loads(before['pnl_state.json'])
    from decimal import Decimal
    independently=sum(Decimal(str(t['pnl'])) for t in state['trades'] if t['status']=='closed')
    assert out['realized_pnl']==pytest.approx(float(independently))
    assert out['promotion_ready'] is False and out['win_rate'] is None
    report=script('check_pnl_invariants').assess(tmp_path/'data/tracking/pnl_state.json',target)
    assert report['status']=='diagnostic_pass' and report['performance_qualified'] is False
    assert before=={n:(tmp_path/'data/tracking'/n).read_bytes() for n in FILES}


@pytest.mark.parametrize('damage',['missing','status','pnl','events','prepared'])
def test_invalid_ledger_preserves_report_and_does_no_external_io(tmp_path,damage):
    target,broker=setup(tmp_path);p=tmp_path/'data/tracking/pnl_state.json'
    if damage=='missing':p.unlink()
    if damage in {'status','pnl'}:
        s=json.loads(p.read_text());row=next(t for t in s['trades'] if t['status']=='closed')
        if damage=='status':row['status']='clsoed'
        else:row['pnl']=None
        p.write_text(json.dumps(s))
    if damage=='events':(p.parent/'trade_events.jsonl').write_text('bad')
    if damage=='prepared':(p.parent/'.ledger_transaction.json').write_text('{"state":"prepared"}')
    with pytest.raises(Exception):script('build_performance_summary').export(tmp_path,broker)
    assert target.read_bytes()==b'prior report' and not broker.mock_calls


@pytest.mark.parametrize('payload',[None,{},[{'unrealized_pl':'NaN'}],[{}]])
def test_unavailable_positions_remain_null_not_zero(tmp_path,payload):
    _,broker=setup(tmp_path);broker.fetch_positions.return_value=SimpleNamespace(payload=payload)
    out=script('build_performance_summary').export(tmp_path,broker)
    assert out['status']=='partial' and out['unrealized_pnl'] is None and out['total_pnl'] is None
    assert out['errors']==['positions_unavailable']


def test_writer_change_during_network_observation_cannot_replace_report(tmp_path):
    target,broker=setup(tmp_path);p=tmp_path/'data/tracking/pnl_state.json'
    def network():
        with ledger_transaction(tmp_path) as tx:
            state=json.loads(tx.read(p));state['last_updated']='2026-11-05T00:00:00Z'
            tx.stage(p,json.dumps(state).encode())
        return SimpleNamespace(payload=[])
    broker.fetch_positions.side_effect=network
    with pytest.raises(ValueError,match='changed'):script('build_performance_summary').export(tmp_path,broker)
    assert target.read_bytes()==b'prior report'


def test_missing_baseline_is_not_assumed_capital(tmp_path):
    _,broker=setup(tmp_path);p=tmp_path/'data/tracking/pnl_state.json'
    with ledger_transaction(tmp_path) as tx:
        state=json.loads(tx.read(p));state.pop('baseline_equity');tx.stage(p,json.dumps(state).encode())
    out=script('build_performance_summary').export(tmp_path,broker)
    assert out['baseline_equity'] is None and out['pnl_vs_baseline'] is None
    assert out['errors']==['baseline_unavailable'] and out['status']=='partial'
